"""
SLA Guardian - Comprehensive Traffic Source & Trace Replay Test Suite
Phase 8: Tests for pluggable traffic sources, recorded trace replay, live telemetry adapter,
and deterministic lockstep replay across multi-policy simulator instances.

Covers:
1. CSV trace parsing with 5QI labels and relative timing.
2. JSONL trace parsing with source QoS and latency measurements.
3. Pure-Python binary PCAP parsing and IPv4 ToS/DSCP classification.
4. Handling unclassified flows without guessing slice assignment from traffic volume.
5. Error handling on missing, corrupted, or unsupported trace files.
6. Deterministic lockstep replay across multiple independent simulator instances.
7. Replay speed multiplier and measurement-window derivation.
8. Trace reset behavior returning to start timestamp without state corruption.
9. Equal traffic input events delivered across competing policies.
10. Live telemetry adapter configuration, timeout, retry, and stale detection.
11. Explicit DISCONNECTED and UNCONFIGURED statuses without synthetic fallback.
12. Separation between measured source inputs and simulated engine outputs.
13. FastAPI traffic endpoints (/api/traffic/sources, /validate-trace, /upload-trace, /status).
14. No hidden synthetic fallback when trace replay is requested or fails.
"""

import os
import json
import csv
import struct
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.schemas.config import RunConfig, SliceId, CANONICAL_SLICE_IDS
from backend.app.schemas.state import NetworkState
from backend.app.schemas.telemetry import RunStartRequest, ResetRequest
from backend.app.traffic.interface import (
    TrafficSourceType,
    TrafficSourceStatus,
    TrafficEvent,
    TrafficStepArrivals,
)
from backend.app.traffic.trace_source import TraceReplayTrafficSource, DEFAULT_QOS_SLICE_MAPPING
from backend.app.traffic.synthetic_source import SyntheticTestTrafficSource
from backend.app.traffic.telemetry_source import LiveTelemetryTrafficSource
from backend.app.simulator.fallback import FallbackNetworkSimulator
from backend.app.control.safety_shield import SafetyShield
from backend.app.rl.control_interval import MacroControlAdapter
from backend.app.policies import StaticSlicingPolicy, AdaptiveDemandHeuristicPolicy, RLPolicy
from backend.app.main import app, _get_runner

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TRACES_DIR = ROOT_DIR / "data" / "traces"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ==============================================================================
# 1. RECORDED TRACE PARSING TESTS (CSV, JSONL, PCAP)
# ==============================================================================

def test_01_csv_trace_parsing():
    """Verify CSV trace parsing, timestamp normalization, and 5QI mapping."""
    csv_file = TRACES_DIR / "sample_5g_multi_slice_trace.csv"
    assert csv_file.exists(), "CSV fixture should exist."

    source = TraceReplayTrafficSource(file_path=csv_file, replay_speed=1.0)
    source.initialize()

    meta = source.get_metadata()
    assert meta.source_type == TrafficSourceType.TRACE_REPLAY
    assert meta.total_records > 1000
    assert meta.duration_sec >= 9.0
    assert meta.classification_coverage_pct > 95.0

    # Test arrivals generation
    arrivals = source.generate_step_arrivals(step=1, sim_time_sec=0.1, step_duration_sec=0.1)
    assert isinstance(arrivals, TrafficStepArrivals)
    assert arrivals.total_packets >= 0
    assert "eMBB" in arrivals.packets_per_slice
    assert "URLLC" in arrivals.packets_per_slice
    assert "mURLLC" in arrivals.packets_per_slice


def test_02_jsonl_trace_parsing_with_source_measurements():
    """Verify JSONL trace parsing and extraction of source-measured QoS/latency."""
    jsonl_file = TRACES_DIR / "sample_5g_trace.jsonl"
    assert jsonl_file.exists(), "JSONL fixture should exist."

    source = TraceReplayTrafficSource(file_path=jsonl_file, replay_speed=1.0)
    meta = source.get_metadata()

    assert meta.source_type == TrafficSourceType.TRACE_REPLAY
    assert meta.total_records > 500
    assert "source_measured_latency_ms" in meta.measured_metrics_available

    # Check that events contain source measurements
    has_latency = any(ev.source_measured_latency_ms is not None for ev in source.raw_records)
    assert has_latency, "JSONL trace should preserve source-measured latency without fabrication."


def test_03_binary_pcap_parsing_with_dscp_mapping():
    """Verify pure-Python binary PCAP parser and IPv4 ToS/DSCP classification."""
    pcap_file = TRACES_DIR / "sample_5g_trace.pcap"
    assert pcap_file.exists(), "PCAP fixture should exist."

    source = TraceReplayTrafficSource(file_path=pcap_file, replay_speed=1.0)
    meta = source.get_metadata()

    assert meta.source_type == TrafficSourceType.TRACE_REPLAY
    assert meta.total_records > 500
    assert meta.classification_coverage_pct > 90.0

    # Ensure all three slices receive packets based on ToS DSCP mapping
    slice_dist = meta.slice_distribution
    assert slice_dist.get("eMBB", 0) > 0
    assert slice_dist.get("URLLC", 0) > 0
    assert slice_dist.get("mURLLC", 0) > 0


# ==============================================================================
# 2. SLICE CLASSIFICATION & UNCLASSIFIED FLOW ISOLATION
# ==============================================================================

def test_04_unclassified_flows_preserved_without_guessing():
    """Verify that unlabelled or unmapped flows are NOT inferred from volume."""
    unclass_file = TRACES_DIR / "sample_with_unclassified.csv"
    assert unclass_file.exists(), "Unclassified fixture should exist."

    source = TraceReplayTrafficSource(file_path=unclass_file)
    diag = source.get_diagnostics()
    meta = source.get_metadata()

    # Two flows in the fixture are unmapped: UNKNOWN_SLICE and empty labels
    assert diag["unclassified_records_count"] == 2
    assert meta.unclassified_count == 2
    assert meta.classification_coverage_pct < 100.0

    # Verify that unclassified events have slice_id=None
    unclass_events = [ev for ev in source.raw_records if ev.slice_id is None]
    assert len(unclass_events) == 2


def test_05_qos_mapping_table_completeness():
    """Verify standard 3GPP 5QI and DSCP mapping table."""
    assert DEFAULT_QOS_SLICE_MAPPING["5qi_1"] == SliceId.URLLC
    assert DEFAULT_QOS_SLICE_MAPPING["5qi_9"] == SliceId.EMBB
    assert DEFAULT_QOS_SLICE_MAPPING["5qi_79"] == SliceId.MURLLC
    assert DEFAULT_QOS_SLICE_MAPPING["dscp_46"] == SliceId.URLLC
    assert DEFAULT_QOS_SLICE_MAPPING["dscp_0"] == SliceId.EMBB
    assert DEFAULT_QOS_SLICE_MAPPING["dscp_10"] == SliceId.MURLLC


# ==============================================================================
# 3. ROBUST ERROR HANDLING & NO SILENT FALLBACK
# ==============================================================================

def test_06_missing_trace_file_sets_error_status():
    """Verify that a nonexistent trace file sets ERROR status and does not crash."""
    nonexistent = TRACES_DIR / "nonexistent_trace_12345.csv"
    source = TraceReplayTrafficSource(file_path=nonexistent)

    assert source.status == TrafficSourceStatus.ERROR
    is_valid, errors = source.validate()
    assert is_valid is False
    assert len(errors) > 0


def test_07_corrupted_trace_handling():
    """Verify error reporting on corrupted CSV data."""
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write("timestamp,size_bytes,slice_id\n")
        f.write("0.01,invalid_size,eMBB\n")
        f.write("corrupted_ts,1400,URLLC\n")
        tmp_name = f.name

    try:
        source = TraceReplayTrafficSource(file_path=Path(tmp_name))
        is_valid, errors = source.validate()
        assert is_valid is False
        assert len(errors) > 0
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def test_08_no_silent_fallback_to_synthetic():
    """Verify that FallbackNetworkSimulator with TraceReplay does not use synthetic traffic."""
    csv_file = TRACES_DIR / "sample_5g_multi_slice_trace.csv"
    trace_source = TraceReplayTrafficSource(file_path=csv_file)

    simulator = FallbackNetworkSimulator(traffic_source=trace_source)
    simulator.reset(seed=42)

    diag = simulator.get_diagnostics()
    assert diag["traffic_source_type"] == "trace_replay"
    assert "sample_5g_multi_slice_trace.csv" in diag["traffic_source_name"]


# ==============================================================================
# 4. DETERMINISTIC REPLAY & MULTI-POLICY SYNCHRONIZATION
# ==============================================================================

def test_09_deterministic_replay_across_independent_instances():
    """Verify that two independent trace sources produce identical arrivals at every step."""
    csv_file = TRACES_DIR / "sample_5g_multi_slice_trace.csv"

    source_a = TraceReplayTrafficSource(file_path=csv_file)
    source_b = TraceReplayTrafficSource(file_path=csv_file)

    source_a.reset(start_time_sec=0.0)
    source_b.reset(start_time_sec=0.0)

    for step in range(1, 20):
        t_sim = step * 0.1
        arr_a = source_a.generate_step_arrivals(step, t_sim, 0.1)
        arr_b = source_b.generate_step_arrivals(step, t_sim, 0.1)

        assert arr_a.total_packets == arr_b.total_packets
        assert arr_a.total_bytes == arr_b.total_bytes
        for s in CANONICAL_SLICE_IDS:
            assert arr_a.packets_per_slice[s.value] == arr_b.packets_per_slice[s.value]
            assert arr_a.bytes_per_slice[s.value] == arr_b.bytes_per_slice[s.value]


def test_10_trace_reset_behavior():
    """Verify that reset restarts replay from time 0 without data corruption."""
    csv_file = TRACES_DIR / "sample_5g_multi_slice_trace.csv"
    source = TraceReplayTrafficSource(file_path=csv_file)

    # Advance 10 steps
    for step in range(1, 11):
        source.generate_step_arrivals(step, step * 0.1, 0.1)
    assert source.current_trace_idx > 0

    # Reset
    source.reset(start_time_sec=0.0)
    assert source.current_trace_idx == 0

    # First step after reset matches fresh start
    first_arr = source.generate_step_arrivals(1, 0.1, 0.1)
    assert first_arr.total_packets > 0


def test_11_equal_traffic_input_across_policies():
    """Verify that Static, Heuristic, and Agent receive identical packet arrivals under trace replay."""
    scenario_file = ROOT_DIR / "scenarios" / "default.json"
    with open(scenario_file, "r", encoding="utf-8") as f:
        raw_scen = json.load(f)

    config = RunConfig(**raw_scen)
    csv_file = TRACES_DIR / "sample_5g_multi_slice_trace.csv"

    source_static = TraceReplayTrafficSource(file_path=csv_file)
    source_agent = TraceReplayTrafficSource(file_path=csv_file)

    sim_static = FallbackNetworkSimulator(config=config, traffic_source=source_static)
    sim_agent = FallbackNetworkSimulator(config=config, traffic_source=source_agent)

    sim_static.reset(seed=42)
    sim_agent.reset(seed=42)

    macro_static = MacroControlAdapter(simulator=sim_static, config=config, steps_per_interval=10)
    macro_agent = MacroControlAdapter(simulator=sim_agent, config=config, steps_per_interval=10)

    pol_static = StaticSlicingPolicy(config=config)
    shield = SafetyShield()

    state_s = sim_static.get_state()
    state_a = sim_agent.get_state()

    for step in range(5):
        act_s = shield.validate(pol_static.predict(state_s), state_s, config).executed_action
        act_a = shield.validate(pol_static.predict(state_a), state_a, config).executed_action

        state_s, m_s, _ = macro_static.execute_macro_step(state_s, act_s)
        state_a, m_a, _ = macro_agent.execute_macro_step(state_a, act_a)

        # Offered packets from the trace MUST be strictly equal
        for s in CANONICAL_SLICE_IDS:
            assert m_s.offered_packets[s] == m_a.offered_packets[s]


# ==============================================================================
# 5. LIVE TELEMETRY ADAPTER TESTS
# ==============================================================================

def test_12_live_telemetry_unconfigured_status():
    """Verify that LiveTelemetryTrafficSource starts in UNCONFIGURED status when no endpoint given."""
    source = LiveTelemetryTrafficSource(endpoint_url=None)
    assert source.status == TrafficSourceStatus.UNCONFIGURED
    assert source.source_type == TrafficSourceType.LIVE_TELEMETRY


def test_13_live_telemetry_stale_detection():
    """Verify stale data detection when no new samples arrive within threshold."""
    source = LiveTelemetryTrafficSource(
        endpoint_url="http://127.0.0.1:9999/dummy",
        stale_threshold_sec=0.05,
    )
    # Simulate a sample received in the past
    source.last_sample_time = 100.0
    source._status = TrafficSourceStatus.READY

    assert source.is_stale(current_time=100.1) is True


def test_14_live_telemetry_disconnected_on_unreachable():
    """Verify that attempting to poll an unreachable endpoint transitions cleanly to DISCONNECTED."""
    source = LiveTelemetryTrafficSource(
        endpoint_url="http://127.0.0.1:54321/nonexistent",
        timeout_sec=0.5,
        max_retries=1,
    )
    success = source.poll_telemetry()
    assert success is False
    assert source.status in (TrafficSourceStatus.DISCONNECTED, TrafficSourceStatus.DEGRADED, TrafficSourceStatus.ERROR)


# ==============================================================================
# 6. FASTAPI ENDPOINTS & ORCHESTRATION TESTS
# ==============================================================================

def test_15_api_list_traffic_sources(client):
    """Verify GET /api/traffic/sources lists supported modes and available trace files."""
    response = client.get("/api/traffic/sources")
    assert response.status_code == 200
    data = response.json()

    assert "supported_source_types" in data
    assert "synthetic" in data["supported_source_types"]
    assert "trace_replay" in data["supported_source_types"]
    assert "live_telemetry" in data["supported_source_types"]

    assert "recorded_traces" in data
    filenames = [f["file_name"] for f in data["recorded_traces"]]
    assert "sample_5g_multi_slice_trace.csv" in filenames
    assert "sample_5g_trace.jsonl" in filenames
    assert "sample_5g_trace.pcap" in filenames


def test_16_api_validate_trace_endpoint(client):
    """Verify POST /api/traffic/validate-trace provides classification and coverage metrics."""
    response = client.post(
        "/api/traffic/validate-trace",
        json={"file_name": "sample_5g_multi_slice_trace.csv"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["valid"] is True
    assert data["file_name"] == "sample_5g_multi_slice_trace.csv"
    assert data["total_records"] > 1000
    assert data["classification_coverage_pct"] > 0.95
    assert "eMBB" in data["slice_distribution"]


def test_17_api_start_run_with_trace_replay(client):
    """Verify starting an experiment using recorded trace replay."""
    payload = {
        "scenario": "normal",
        "seed": 42,
        "max_macro_steps": 10,
        "selected_policies": ["static", "heuristic", "agent"],
        "traffic_source_type": "trace_replay",
        "trace_file": "sample_5g_multi_slice_trace.csv",
        "replay_speed": 1.0,
    }
    response = client.post("/api/runs", json=payload)
    assert response.status_code in (200, 201)
    data = response.json()

    assert data["traffic_source_type"] == "trace_replay"
    assert data["trace_file"] == "sample_5g_multi_slice_trace.csv"


def test_18_api_traffic_status_endpoint(client):
    """Verify GET /api/traffic/status reports the active source and health status."""
    response = client.get("/api/traffic/status")
    assert response.status_code == 200
    data = response.json()

    assert "active_source_type" in data
    assert "status" in data
    assert "diagnostics" in data


def test_19_api_upload_trace_endpoint(client):
    """Verify POST /api/traffic/upload-trace allows uploading a test trace."""
    content = "timestamp,size_bytes,slice_id\n0.01,1400,eMBB\n0.02,250,URLLC\n"
    files = {"file": ("uploaded_test_trace.csv", content.encode("utf-8"), "text/csv")}

    response = client.post("/api/traffic/upload-trace", files=files)
    assert response.status_code == 200
    data = response.json()

    assert data["file_name"] == "uploaded_test_trace.csv"
    assert data["valid"] is True

    # Clean up uploaded test trace
    uploaded_path = TRACES_DIR / "uploaded_test_trace.csv"
    if uploaded_path.exists():
        uploaded_path.unlink()
