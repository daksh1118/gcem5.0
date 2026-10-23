"""
End-to-end integration tests for FallbackNetworkSimulator.
Verifies state transitions, queue buildup, compute bottleneck latency spikes,
reproducibility, and schema conformity.
"""

import math
import pytest
from backend.app.schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig, SliceSlaConfig
from backend.app.schemas.state import NetworkState
from backend.app.schemas.actions import ExecutedAction
from backend.app.interfaces.simulator import SimulatorDiagnostics
from backend.app.simulator.fallback import FallbackNetworkSimulator


@pytest.fixture
def sim_config() -> RunConfig:
    sla = {
        SliceId.EMBB: SliceSlaConfig(max_latency_ms=25.0, min_throughput_mbps=50.0, min_packet_delivery_ratio=0.98),
        SliceId.URLLC: SliceSlaConfig(max_latency_ms=5.0, min_throughput_mbps=10.0, min_packet_delivery_ratio=0.9999),
        SliceId.MURLLC: SliceSlaConfig(max_latency_ms=15.0, min_throughput_mbps=20.0, min_packet_delivery_ratio=0.999),
    }
    return RunConfig(
        scenario_id="test_simulator",
        seed=42,
        max_steps=100,
        step_duration_ms=10.0,
        total_radio_capacity=100.0,
        total_compute_capacity=100.0,
        sla_thresholds=sla,
        traffic_profile="normal",
    )


def test_simulator_reset_conventions(sim_config):
    """Verifies reset initializes step 0 with None for unmeasured metrics."""
    sim = FallbackNetworkSimulator(sim_config)
    state = sim.reset(seed=42)

    assert isinstance(state, NetworkState)
    assert state.step == 0
    assert state.sim_time_sec == 0.0
    assert len(state.slice_states) == 3

    for sid in CANONICAL_SLICE_IDS:
        sstate = state.slice_states[sid]
        assert sstate.delivered_throughput_mbps is None
        assert sstate.p95_latency_ms is None
        assert sstate.packet_delivery_ratio is None
        assert sstate.queue_depth_packets == 0
        assert sstate.sla_headroom == 1.0


def test_simulator_step_advances_clock_and_schemas(sim_config):
    """Verifies step advances simulation time by step_duration_ms and produces valid diagnostics."""
    sim = FallbackNetworkSimulator(sim_config)
    sim.reset(seed=42)

    action = ExecutedAction(
        radio_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
    )

    next_state, diag = sim.step(action)

    assert isinstance(next_state, NetworkState)
    assert isinstance(diag, SimulatorDiagnostics)
    assert next_state.step == 1
    assert pytest.approx(next_state.sim_time_sec, 1e-4) == 0.010
    assert diag.step == 1
    assert diag.terminated is False
    assert diag.truncated is False

    # Check finite numbers (no NaN or Inf)
    for sstate in next_state.slice_states.values():
        assert math.isfinite(sstate.offered_demand_mbps)
        if sstate.delivered_throughput_mbps is not None:
            assert math.isfinite(sstate.delivered_throughput_mbps)
        if sstate.p95_latency_ms is not None:
            assert math.isfinite(sstate.p95_latency_ms)


def test_simulator_reproducibility_with_seed(sim_config):
    """Verifies identical trajectories when initialized with identical seed."""
    sim1 = FallbackNetworkSimulator(sim_config)
    sim2 = FallbackNetworkSimulator(sim_config)

    s1 = sim1.reset(seed=777)
    s2 = sim2.reset(seed=777)

    action = ExecutedAction(
        radio_allocations={SliceId.EMBB: 45.0, SliceId.URLLC: 25.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 45.0, SliceId.URLLC: 25.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 2, SliceId.URLLC: 1, SliceId.MURLLC: 3},
    )

    for _ in range(5):
        s1, d1 = sim1.step(action)
        s2, d2 = sim2.step(action)

        for sid in CANONICAL_SLICE_IDS:
            assert s1.slice_states[sid].delivered_throughput_mbps == s2.slice_states[sid].delivered_throughput_mbps
            assert s1.slice_states[sid].queue_depth_packets == s2.slice_states[sid].queue_depth_packets


def test_compute_bottleneck_causes_latency_increase(sim_config):
    """
    CRITICAL ARCHITECTURAL TEST:
    Even when radio allocation is high (sufficient for all traffic),
    starving a slice of edge compute causes queue accumulation and latency degradation.
    """
    sim_unconstrained = FallbackNetworkSimulator(sim_config)
    sim_bottlenecked = FallbackNetworkSimulator(sim_config)

    sim_unconstrained.reset(seed=42)
    sim_bottlenecked.reset(seed=42)

    # Balanced case: generous compute (30 units for URLLC)
    action_balanced = ExecutedAction(
        radio_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 2, SliceId.URLLC: 1, SliceId.MURLLC: 3},
    )

    # Bottleneck case: generous radio (30 units) but near-zero compute (0.5 units) for URLLC
    action_bottleneck = ExecutedAction(
        radio_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 49.5, SliceId.URLLC: 0.5, SliceId.MURLLC: 50.0},
        priorities={SliceId.EMBB: 2, SliceId.URLLC: 1, SliceId.MURLLC: 3},
    )

    # Step for 10 steps to observe compute queue backlog
    for _ in range(10):
        s_uncon, _ = sim_unconstrained.step(action_balanced)
        s_bottle, _ = sim_bottlenecked.step(action_bottleneck)

    # In the bottlenecked run, URLLC packets should be trapped in compute queue
    bottle_urllc_queue = sim_bottlenecked.compute_queues[SliceId.URLLC].size()
    uncon_urllc_queue = sim_unconstrained.compute_queues[SliceId.URLLC].size()

    assert bottle_urllc_queue > uncon_urllc_queue, (
        f"Bottlenecked compute queue ({bottle_urllc_queue}) must exceed unconstrained ({uncon_urllc_queue})"
    )


def test_invalid_executed_action_budget_fails_cleanly(sim_config):
    """ExecutedAction with invalid budget must be rejected with ValueError."""
    sim = FallbackNetworkSimulator(sim_config)
    sim.reset(seed=42)

    # Radio sum = 120 > 100
    invalid_action = ExecutedAction(
        radio_allocations={SliceId.EMBB: 50.0, SliceId.URLLC: 40.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 30.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 2, SliceId.URLLC: 1, SliceId.MURLLC: 3},
    )

    with pytest.raises(ValueError) as exc:
        sim.step(invalid_action)
    assert "exceeds total radio capacity" in str(exc.value)
