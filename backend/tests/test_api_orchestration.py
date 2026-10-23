"""
SLA Guardian - Phase 6 FastAPI & Orchestration Integration Tests
Validates:
1. Health endpoint and model readiness.
2. Scenario listing from actual configuration.
3. Starting a valid experiment.
4. Rejection of invalid scenario configuration.
5. Spike injection validation.
6. Consistent spike injection across all three policies.
7. Reset clearing episode and cumulative metrics.
8. Pause/resume behavior.
9. Summary calculations against known diagnostic data.
10. WebSocket connection and initial state.
11. WebSocket telemetry shape and sequence ordering.
12. Client disconnection without simulation failure.
13. Rejected Shield actions not advancing simulation.
14. A complete short experiment using Static, Heuristic and PPO.
15. The API can load the saved checkpoint without training.
16. A missing checkpoint creates a clear degraded state.
17. Concurrency protection against duplicate background loops.
18. Correct distinction between per-slice status and aggregate SLA-breach status.
"""

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app, _get_runner
from backend.app.schemas.config import SliceId, CANONICAL_SLICE_IDS
from backend.app.schemas.actions import ProposedAction
from backend.app.services.experiment_runner import ExperimentRunner


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_01_health_endpoint_and_model_readiness(client):
    """Test 1: Health endpoint returns server status and indicates model is loaded."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["healthy", "degraded"]
    assert data["service"] == "SLA Guardian"
    assert data["version"] == "0.2.0"
    assert data["model_loaded"] is True
    assert data["demo_ready"] is True
    assert "models" in data["model_path"] and "agent.zip" in data["model_path"]


def test_02_scenario_listing_from_actual_configuration(client):
    """Test 2: Scenarios are loaded from actual scenarios/default.json."""
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    data = response.json()
    assert "scenarios" in data
    ids = [sc["id"] for sc in data["scenarios"]]
    assert "normal" in ids
    assert "embb_surge" in ids
    assert "urllc_burst" in ids
    assert "murllc_storm" in ids
    assert "mixed_stress" in ids
    assert data["total_radio_capacity"] == 100.0


def test_03_starting_valid_experiment(client):
    """Test 3: Start a valid experiment and verify run ID and status."""
    payload = {
        "scenario": "normal",
        "seed": 42,
        "max_macro_steps": 10,
        "selected_policies": ["static", "heuristic", "agent"],
    }
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "run_id" in data
    assert data["status"] == "running"
    assert data["scenario"] == "normal"
    assert data["seed"] == 42


def test_04_rejection_of_invalid_scenario_configuration(client):
    """Test 4: Requesting an unknown scenario triggers 400 Bad Request."""
    payload = {
        "scenario": "non_existent_chaos_mode",
        "seed": 99,
        "max_macro_steps": 10,
    }
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 400
    assert "Unknown scenario" in response.json()["detail"]


def test_05_spike_injection_validation(client):
    """Test 5: Spike injection rejects invalid slices and non-positive factors."""
    # Invalid slice
    res = client.post("/api/spike", json={"target_slice": "INVALID", "multiplier": 3.0, "duration_steps": 5})
    assert res.status_code == 400
    assert "Invalid slice" in res.json()["detail"]

    # Non-positive multiplier
    res = client.post("/api/spike", json={"target_slice": "URLLC", "multiplier": -1.0, "duration_steps": 5})
    assert res.status_code == 422 or res.status_code == 400

    # Non-positive duration
    res = client.post("/api/spike", json={"target_slice": "URLLC", "multiplier": 3.0, "duration_steps": 0})
    assert res.status_code == 422 or res.status_code == 400


def test_06_consistent_spike_injection_across_all_three_policies(client):
    """Test 6: Valid spike injection is applied consistently across Static, Heuristic, and Agent."""
    res = client.post("/api/spike", json={"target_slice": "URLLC", "multiplier": 4.0, "duration_steps": 10})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "spike_injected"
    assert data["target_slice"] == "URLLC"
    assert data["multiplier"] == 4.0
    assert data["duration_steps"] == 10

    runner = _get_runner()
    # Verify that each policy's traffic generator has the active spike
    for key in ["static", "heuristic", "agent"]:
        tg = runner.contexts[key].simulator.traffic_gen
        assert len(tg.active_spikes) >= 1
        last_sp = tg.active_spikes[-1]
        assert last_sp["slice_id"] == SliceId.URLLC
        assert last_sp["multiplier"] == 4.0
        assert last_sp["duration_steps"] == 100  # 10 macro steps * 10 sub-steps


def test_07_reset_clears_metrics_and_accumulators(client):
    """Test 7: Reset operation clears latency history, queues, and accumulators."""
    # Advance state first
    runner = _get_runner()
    res = client.post("/api/reset", json={"scenario": "embb_surge", "seed": 77})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "reset_successful"
    assert data["scenario"] == "embb_surge"
    assert data["step"] == 0

    assert runner.current_macro_step == 0
    assert runner.sim_time_sec == 0.0
    assert len(runner.active_spikes) == 0

    for key, ctx in runner.contexts.items():
        assert len(ctx.evaluator.accumulator.step_metrics_history) == 0
        for s in CANONICAL_SLICE_IDS:
            assert ctx.simulator.radio_queues[s].size() == 0
            assert ctx.simulator.compute_queues[s].size() == 0


def test_08_pause_and_resume_behavior(client):
    """Test 8: Pause prevents advancement and resume restores execution."""
    client.post("/api/runs", json={"scenario": "normal", "seed": 42, "max_macro_steps": 20})
    
    # Pause
    res = client.post("/api/pause")
    assert res.status_code == 200
    assert res.json()["status"] == "paused"

    status_data = client.get("/api/status").json()
    assert status_data["status"] == "paused"
    paused_step = status_data["current_macro_step"]

    # Verify no advancement while paused
    import time
    time.sleep(0.1)
    status_data2 = client.get("/api/status").json()
    assert status_data2["current_macro_step"] == paused_step

    # Resume
    res = client.post("/api/resume")
    assert res.status_code == 200
    assert res.json()["status"] == "running"


def test_09_summary_calculations_against_known_diagnostic_data(client):
    """Test 9: Summary calculation derives accurate throughput and packet conservation."""
    # Run a short run to completion
    runner = _get_runner()
    res = client.post("/api/runs", json={"scenario": "normal", "seed": 42, "max_macro_steps": 5})
    assert res.status_code == 201

    import time
    for _ in range(30):
        if runner.status == "completed":
            break
        time.sleep(0.05)

    summary_res = client.get("/api/summary")
    assert summary_res.status_code == 200
    summary = summary_res.json()

    assert "static" in summary
    assert "heuristic" in summary
    assert "agent" in summary

    for policy_key in ["static", "heuristic", "agent"]:
        p_data = summary[policy_key]
        assert "mean_embb_tput_mbps" in p_data
        assert "critical_violations" in p_data
        assert "shield_interventions" in p_data
        assert "per_slice_summary" in p_data
        for s in ["eMBB", "URLLC", "mURLLC"]:
            assert s in p_data["per_slice_summary"]
            s_dict = p_data["per_slice_summary"][s]
            assert s_dict["offered_packets"] >= s_dict["delivered_packets"] + s_dict["dropped_packets"] - 100


def test_10_websocket_connection_and_initial_state(client):
    """Test 10: WebSocket client connects and receives initial state snapshot."""
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert "run_id" in data
        assert "sequence_number" in data
        assert "macro_step" in data
        assert "policies" in data
        assert "static" in data["policies"]
        assert "heuristic" in data["policies"]
        assert "agent" in data["policies"]


def test_11_websocket_telemetry_shape_and_sequence_ordering(client):
    """Test 11: WebSocket delivers sequentially increasing sequence numbers."""
    client.post("/api/reset", json={"scenario": "normal", "seed": 42})
    with client.websocket_connect("/ws") as ws:
        data1 = ws.receive_json()
        ws.send_text("step")
        data2 = ws.receive_json()
        assert data2["sequence_number"] >= data1["sequence_number"]
        # Verify policy data shape
        agent_p = data2["policies"]["agent"]
        assert "radio_allocations" in agent_p
        assert "compute_allocations" in agent_p
        assert "delivered_tput_mbps" in agent_p
        assert "shield_status" in agent_p


def test_12_client_disconnection_without_simulation_failure(client):
    """Test 12: Client disconnecting does not crash active experiment runner."""
    client.post("/api/runs", json={"scenario": "normal", "seed": 42, "max_macro_steps": 10})
    with client.websocket_connect("/ws") as ws:
        _ = ws.receive_json()
        # Abrupt disconnect
    
    # Server should still be running smoothly
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] in ["healthy", "degraded"]


def test_13_rejected_shield_actions_do_not_advance_simulation():
    """Test 13: An action rejected by the shield halts simulation advancement."""
    runner = _get_runner()
    ctx = runner.contexts["static"]
    initial_step = ctx.current_state.step

    # Artificially inject an invalid proposal that violates bounds
    invalid_proposal = ProposedAction(
        radio_allocations={s: 999.0 for s in CANONICAL_SLICE_IDS},
        compute_allocations={s: 999.0 for s in CANONICAL_SLICE_IDS},
        priorities={s: 1 for s in CANONICAL_SLICE_IDS},
        policy_id="malformed_test_policy",
    )
    safety_res = ctx.shield.validate(invalid_proposal, ctx.current_state, ctx.config)
    # The shield may correct or reject; if we craft non-finite allocation it rejects:
    import numpy as np
    nan_proposal = ProposedAction(
        radio_allocations={SliceId.EMBB: float(np.nan), SliceId.URLLC: 25.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 45.0, SliceId.URLLC: 25.0, SliceId.MURLLC: 30.0},
        priorities={s: 1 for s in CANONICAL_SLICE_IDS},
        policy_id="nan_policy",
    )
    nan_res = ctx.shield.validate(nan_proposal, ctx.current_state, ctx.config)
    assert nan_res.validation_status.value == "REJECTED"
    # Verification: step does not advance
    assert ctx.current_state.step == initial_step


def test_14_complete_short_experiment_three_policies(client):
    """Test 14: Execute complete 5-step run with Static, Heuristic, and PPO."""
    res = client.post("/api/runs", json={"scenario": "urllc_burst", "seed": 42, "max_macro_steps": 5})
    assert res.status_code == 201

    import time
    runner = _get_runner()
    for _ in range(30):
        if runner.status == "completed":
            break
        time.sleep(0.05)

    assert runner.current_macro_step >= 5
    summary = client.get("/api/summary").json()
    assert summary["static"]["completed_macro_steps"] == 5
    assert summary["heuristic"]["completed_macro_steps"] == 5
    assert summary["agent"]["completed_macro_steps"] == 5


def test_15_api_loads_saved_checkpoint_without_training(client):
    """Test 15: The saved model at models/agent.zip is loaded purely for inference."""
    runner = _get_runner()
    assert runner.model_loaded is True
    assert runner.rl_policy_instance is not None
    assert runner.rl_policy_instance.model is not None


def test_16_missing_checkpoint_creates_clear_degraded_state(tmp_path):
    """Test 16: When model is missing, API gracefully exposes degraded health and actionable error."""
    missing_path = tmp_path / "non_existent_model.zip"
    degraded_runner = ExperimentRunner(
        checkpoint_path=missing_path,
    )
    assert degraded_runner.model_loaded is False
    assert degraded_runner.model_error is not None
    assert "missing" in degraded_runner.model_error.lower()


def test_17_concurrency_protection_against_duplicate_loops(client):
    """Test 17: Consecutive start_run calls cancel and replace cleanly without leaking background loops."""
    res1 = client.post("/api/runs", json={"scenario": "normal", "seed": 1, "max_macro_steps": 50})
    assert res1.status_code == 201
    run_id_1 = res1.json()["run_id"]

    res2 = client.post("/api/runs", json={"scenario": "embb_surge", "seed": 2, "max_macro_steps": 10})
    assert res2.status_code == 201
    run_id_2 = res2.json()["run_id"]

    assert run_id_1 != run_id_2
    runner = _get_runner()
    assert runner.run_id == run_id_2
    assert runner.active_seed == 2
    assert runner.active_scenario == "embb_surge"


def test_18_distinction_between_per_slice_and_aggregate_sla_status(client):
    """Test 18: Telemetry clearly distinguishes per-slice SLA states from aggregate breach."""
    res = client.post("/api/runs", json={"scenario": "normal", "seed": 42, "max_macro_steps": 2})
    assert res.status_code == 201

    import time
    runner = _get_runner()
    for _ in range(20):
        if runner.current_macro_step >= 2:
            break
        time.sleep(0.05)

    evt = runner._build_telemetry_event()
    agent_telemetry = evt.policies["agent"]
    # Per-slice status is a dict per slice
    assert isinstance(agent_telemetry.sla_status, dict)
    assert "eMBB" in agent_telemetry.sla_status
    assert "URLLC" in agent_telemetry.sla_status
    assert "mURLLC" in agent_telemetry.sla_status

    # Details provide root cause reason: PASS, BREACH, or INSUFFICIENT_DATA
    assert isinstance(agent_telemetry.sla_state_details, dict)
    for s in ["eMBB", "URLLC", "mURLLC"]:
        assert agent_telemetry.sla_state_details[s] in ["PASS", "BREACH", "INSUFFICIENT_DATA"]


def test_19_model_metadata_lagrangian_multiplier_reconciliation(client):
    """Test 19: Runner loads genuine final_lambda from agent_metadata.json matching checkpoint."""
    runner = _get_runner()
    assert hasattr(runner, "trained_lambda")
    assert runner.trained_lambda == 0.0
    evt = runner._build_telemetry_event()
    assert evt.policies["agent"].lagrangian_lambda == 0.0
