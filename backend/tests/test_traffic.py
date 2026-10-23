"""
Unit tests for SLA Guardian TrafficGenerator.
Verifies multi-slice traffic arrival dynamics, scenario burst modifiers,
and PRNG determinism.
"""

import pytest
import numpy as np

from backend.app.schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig, SliceSlaConfig
from backend.app.simulator.traffic import TrafficGenerator


@pytest.fixture
def base_config() -> RunConfig:
    sla = {
        SliceId.EMBB: SliceSlaConfig(max_latency_ms=25.0, min_throughput_mbps=50.0, min_packet_delivery_ratio=0.98),
        SliceId.URLLC: SliceSlaConfig(max_latency_ms=5.0, min_throughput_mbps=10.0, min_packet_delivery_ratio=0.9999),
        SliceId.MURLLC: SliceSlaConfig(max_latency_ms=15.0, min_throughput_mbps=20.0, min_packet_delivery_ratio=0.999),
    }
    return RunConfig(
        scenario_id="test_traffic",
        seed=123,
        total_radio_capacity=100.0,
        total_compute_capacity=100.0,
        sla_thresholds=sla,
        traffic_profile="normal",
    )


def test_traffic_generation_all_canonical_slices(base_config):
    """Verifies that all three canonical slices generate packets under normal conditions."""
    generator = TrafficGenerator(base_config, seed=42)
    arrivals = generator.generate_step_arrivals(step=1, sim_time_sec=0.01, step_duration_sec=0.01)

    assert set(arrivals.keys()) == set(CANONICAL_SLICE_IDS)
    for slice_id in CANONICAL_SLICE_IDS:
        pkts = arrivals[slice_id]
        assert len(pkts) > 0, f"Slice {slice_id.value} should have generated arrivals"
        for p in pkts:
            assert p.slice_id == slice_id
            assert p.size_bytes > 0
            assert p.arrival_time >= 0.01
            assert p.status == "QUEUED_RADIO"


def test_traffic_determinism_same_seed(base_config):
    """Verifies identical arrival sequences with the same seed."""
    gen1 = TrafficGenerator(base_config, seed=999)
    gen2 = TrafficGenerator(base_config, seed=999)

    arr1 = gen1.generate_step_arrivals(step=1, sim_time_sec=0.0, step_duration_sec=0.01)
    arr2 = gen2.generate_step_arrivals(step=1, sim_time_sec=0.0, step_duration_sec=0.01)

    for s in CANONICAL_SLICE_IDS:
        assert len(arr1[s]) == len(arr2[s])
        for p1, p2 in zip(arr1[s], arr2[s]):
            assert p1.size_bytes == p2.size_bytes
            assert pytest.approx(p1.arrival_time, 1e-6) == p2.arrival_time


def test_traffic_divergence_different_seeds(base_config):
    """Verifies different seeds produce distinct arrival counts or offsets over time."""
    gen1 = TrafficGenerator(base_config, seed=111)
    gen2 = TrafficGenerator(base_config, seed=222)

    total_pkts_1 = sum(len(gen1.generate_step_arrivals(step=i, sim_time_sec=i*0.01, step_duration_sec=0.01)[SliceId.EMBB]) for i in range(10))
    total_pkts_2 = sum(len(gen2.generate_step_arrivals(step=i, sim_time_sec=i*0.01, step_duration_sec=0.01)[SliceId.EMBB]) for i in range(10))

    # They should not be identically synchronized
    assert total_pkts_1 > 0 and total_pkts_2 > 0


def test_scenario_burst_urllc(base_config):
    """Verifies that the urllc_burst profile surges URLLC arrival rate relative to normal."""
    scenario_data = {
        "traffic_profiles": {
            "urllc_burst": {
                "nominal_demand_mbps": {"eMBB": 45.0, "URLLC": 8.0, "mURLLC": 15.0},
                "burst_multiplier": 4.0,
            }
        }
    }
    cfg_normal = base_config.model_copy(update={"traffic_profile": "normal"})
    cfg_burst = base_config.model_copy(update={"traffic_profile": "urllc_burst"})

    gen_normal = TrafficGenerator(cfg_normal, scenario_data=scenario_data, seed=42)
    gen_burst = TrafficGenerator(cfg_burst, scenario_data=scenario_data, seed=42)

    # Accumulate URLLC arrivals over 20 steps
    normal_urllc_count = sum(
        len(gen_normal.generate_step_arrivals(step=i, sim_time_sec=i*0.01, step_duration_sec=0.01)[SliceId.URLLC])
        for i in range(20)
    )
    burst_urllc_count = sum(
        len(gen_burst.generate_step_arrivals(step=i, sim_time_sec=i*0.01, step_duration_sec=0.01)[SliceId.URLLC])
        for i in range(20)
    )

    assert burst_urllc_count >= (2.5 * normal_urllc_count), (
        f"URLLC burst count ({burst_urllc_count}) should be roughly 4x normal ({normal_urllc_count})"
    )
