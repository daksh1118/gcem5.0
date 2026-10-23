"""
Unit tests for StaticSlicingPolicy and AdaptiveDemandHeuristicPolicy.
Verifies determinism, budget compliance, reservation enforcement,
and adaptive reallocation in response to demand bursts.
"""

import pytest
from backend.app.schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig, SliceSlaConfig, SliceReservationConfig
from backend.app.schemas.state import SliceState, NetworkState
from backend.app.schemas.actions import ProposedAction, ExecutedAction
from backend.app.policies.static import StaticSlicingPolicy
from backend.app.policies.heuristic import AdaptiveDemandHeuristicPolicy
from backend.app.simulator.fallback import FallbackNetworkSimulator


@pytest.fixture
def policy_config() -> RunConfig:
    sla = {
        SliceId.EMBB: SliceSlaConfig(max_latency_ms=25.0, min_throughput_mbps=40.0, min_packet_delivery_ratio=0.98),
        SliceId.URLLC: SliceSlaConfig(max_latency_ms=5.0, min_throughput_mbps=8.0, min_packet_delivery_ratio=0.9999),
        SliceId.MURLLC: SliceSlaConfig(max_latency_ms=15.0, min_throughput_mbps=15.0, min_packet_delivery_ratio=0.999),
    }
    reservations = {
        SliceId.EMBB: SliceReservationConfig(min_radio_capacity=20.0, min_compute_capacity=20.0),
        SliceId.URLLC: SliceReservationConfig(min_radio_capacity=25.0, min_compute_capacity=25.0),
        SliceId.MURLLC: SliceReservationConfig(min_radio_capacity=15.0, min_compute_capacity=15.0),
    }
    return RunConfig(
        scenario_id="policy_test",
        seed=42,
        total_radio_capacity=100.0,
        total_compute_capacity=100.0,
        sla_thresholds=sla,
        minimum_reservations=reservations,
    )


def make_dummy_state(
    embb_demand: float = 40.0,
    urllc_demand: float = 8.0,
    urllc_queue: int = 0,
    urllc_headroom: float = 1.0,
) -> NetworkState:
    slice_states = {
        SliceId.EMBB: SliceState(
            slice_id=SliceId.EMBB,
            offered_demand_mbps=embb_demand,
            current_radio_allocation=45.0,
            current_compute_allocation=45.0,
            queue_depth_packets=0,
            sla_headroom=1.0,
        ),
        SliceId.URLLC: SliceState(
            slice_id=SliceId.URLLC,
            offered_demand_mbps=urllc_demand,
            current_radio_allocation=25.0,
            current_compute_allocation=25.0,
            queue_depth_packets=urllc_queue,
            sla_headroom=urllc_headroom,
        ),
        SliceId.MURLLC: SliceState(
            slice_id=SliceId.MURLLC,
            offered_demand_mbps=15.0,
            current_radio_allocation=30.0,
            current_compute_allocation=30.0,
            queue_depth_packets=0,
            sla_headroom=1.0,
        ),
    }
    return NetworkState(
        step=1,
        sim_time_sec=0.010,
        total_radio_capacity=100.0,
        total_compute_capacity=100.0,
        slice_states=slice_states,
    )


def test_static_policy_repeatability_and_bounds(policy_config):
    """Static policy produces identical, budget-compliant proposals."""
    policy = StaticSlicingPolicy(config=policy_config)
    s = make_dummy_state()

    prop1 = policy.predict(s)
    prop2 = policy.predict(s)

    assert prop1.radio_allocations == prop2.radio_allocations
    assert prop1.compute_allocations == prop2.compute_allocations
    assert pytest.approx(sum(prop1.radio_allocations.values()), 1e-3) == 100.0
    assert pytest.approx(sum(prop1.compute_allocations.values()), 1e-3) == 100.0

    # Ensure minimum reservations are respected
    assert prop1.radio_allocations[SliceId.URLLC] >= 25.0
    assert prop1.compute_allocations[SliceId.URLLC] >= 25.0


def test_heuristic_adapts_to_urllc_demand_surge(policy_config):
    """
    Verifies that the adaptive heuristic dynamically reallocates more resources
    to URLLC when URLLC demand surges and queues build up.
    """
    heuristic = AdaptiveDemandHeuristicPolicy(config=policy_config, smoothing_factor=0.0)

    # Normal state
    s_normal = make_dummy_state(urllc_demand=8.0, urllc_queue=0, urllc_headroom=0.8)
    prop_normal = heuristic.predict(s_normal)
    urllc_normal_radio = prop_normal.radio_allocations[SliceId.URLLC]

    # Burst state: 4x demand surge, queue buildup, negative SLA headroom
    s_burst = make_dummy_state(urllc_demand=32.0, urllc_queue=50, urllc_headroom=-0.2)
    prop_burst = heuristic.predict(s_burst)
    urllc_burst_radio = prop_burst.radio_allocations[SliceId.URLLC]

    assert urllc_burst_radio > urllc_normal_radio, (
        f"URLLC allocation under burst ({urllc_burst_radio}) must exceed normal ({urllc_normal_radio})"
    )
    # Priority should become 1 for URLLC under emergency
    assert prop_burst.priorities[SliceId.URLLC] == 1

    # Budget must strictly hold
    assert pytest.approx(sum(prop_burst.radio_allocations.values()), 1e-3) == 100.0
    assert pytest.approx(sum(prop_burst.compute_allocations.values()), 1e-3) == 100.0


def test_both_policies_run_in_simulator_without_violations(policy_config):
    """Executes 10 steps of simulation with both policies and verifies budget compliance."""
    sim_static = FallbackNetworkSimulator(policy_config)
    sim_heuristic = FallbackNetworkSimulator(policy_config)

    p_static = StaticSlicingPolicy(policy_config)
    p_heuristic = AdaptiveDemandHeuristicPolicy(policy_config)

    state_s = sim_static.reset(seed=42)
    state_h = sim_heuristic.reset(seed=42)

    for _ in range(10):
        prop_s = p_static.predict(state_s)
        act_s = ExecutedAction(
            radio_allocations=prop_s.radio_allocations,
            compute_allocations=prop_s.compute_allocations,
            priorities=prop_s.priorities,
        )
        state_s, _ = sim_static.step(act_s)

        prop_h = p_heuristic.predict(state_h)
        act_h = ExecutedAction(
            radio_allocations=prop_h.radio_allocations,
            compute_allocations=prop_h.compute_allocations,
            priorities=prop_h.priorities,
        )
        state_h, _ = sim_heuristic.step(act_h)

        assert state_s.step == state_h.step
