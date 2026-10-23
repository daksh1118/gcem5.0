"""
SLA Guardian - Unit Tests for RL Compatibility Adapters
Tests ObservationAdapter, ActionMappingAdapter, ViolationCostAdapter,
LagrangianMultiplier, and MacroControlAdapter.
"""

import json
from pathlib import Path
import numpy as np
import pytest

from backend.app.schemas.config import RunConfig, SliceId, CANONICAL_SLICE_IDS
from backend.app.schemas.state import NetworkState, SliceState
from backend.app.schemas.actions import ExecutedAction
from backend.app.schemas.metrics import StepMetrics
from backend.app.simulator.fallback import FallbackNetworkSimulator
from backend.app.control.safety_shield import SafetyShield
from backend.app.rl.observation import ObservationAdapter, OBSERVATION_DIM
from backend.app.rl.action_mapping import ActionMappingAdapter, ACTION_DIM, stable_softmax
from backend.app.rl.cost import ViolationCostAdapter
from backend.app.rl.lagrangian import LagrangianMultiplier
from backend.app.rl.control_interval import MacroControlAdapter


@pytest.fixture
def default_config() -> RunConfig:
    scen_path = Path(__file__).resolve().parent.parent.parent / "scenarios" / "default.json"
    with open(scen_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return RunConfig(**data)


@pytest.fixture
def sample_network_state() -> NetworkState:
    slice_states = {
        SliceId.EMBB: SliceState(
            slice_id=SliceId.EMBB,
            offered_demand_mbps=45.0,
            demand_growth_rate=0.0,
            queue_depth_packets=150,
            delivered_throughput_mbps=35.0,
            p95_latency_ms=18.5,
            packet_delivery_ratio=0.985,
            current_radio_allocation=40.0,
            current_compute_allocation=40.0,
            sla_headroom=0.25,
        ),
        SliceId.URLLC: SliceState(
            slice_id=SliceId.URLLC,
            offered_demand_mbps=8.0,
            demand_growth_rate=0.0,
            queue_depth_packets=0,
            delivered_throughput_mbps=8.0,
            p95_latency_ms=9.5,
            packet_delivery_ratio=1.0,
            current_radio_allocation=35.0,
            current_compute_allocation=35.0,
            sla_headroom=-0.9,
        ),
        SliceId.MURLLC: SliceState(
            slice_id=SliceId.MURLLC,
            offered_demand_mbps=15.0,
            demand_growth_rate=0.0,
            queue_depth_packets=10,
            delivered_throughput_mbps=14.0,
            p95_latency_ms=11.2,
            packet_delivery_ratio=1.0,
            current_radio_allocation=25.0,
            current_compute_allocation=25.0,
            sla_headroom=0.25,
        ),
    }
    return NetworkState(
        step=5,
        sim_time_sec=0.050,
        total_radio_capacity=100.0,
        total_compute_capacity=100.0,
        slice_states=slice_states,
        active_alarms=[],
    )


# ---------------------------------------------------------------------------
# 1. ObservationAdapter Tests
# ---------------------------------------------------------------------------

def test_observation_adapter_dimensions_and_bounds(sample_network_state, default_config):
    adapter = ObservationAdapter(queue_scale=1000.0)
    obs = adapter.build_observation(sample_network_state, default_config)

    assert isinstance(obs, np.ndarray)
    assert obs.shape == (OBSERVATION_DIM,)
    assert obs.dtype == np.float32
    assert np.all(np.isfinite(obs))
    # All features should be non-negative and bounded
    assert np.all(obs >= 0.0)
    assert np.all(obs <= 2.0)


def test_observation_adapter_deterministic(sample_network_state, default_config):
    adapter = ObservationAdapter()
    obs1 = adapter.build_observation(sample_network_state, default_config)
    obs2 = adapter.build_observation(sample_network_state, default_config)
    np.testing.assert_array_equal(obs1, obs2)


# ---------------------------------------------------------------------------
# 2. ActionMappingAdapter Tests
# ---------------------------------------------------------------------------

def test_stable_softmax_extreme_values():
    # Large positive and negative values
    logits = [1000.0, 1000.0, 990.0]
    probs = stable_softmax(logits)
    assert np.isclose(np.sum(probs), 1.0)
    assert np.all(probs >= 0.0)
    assert np.all(np.isfinite(probs))

    # All identical
    equal_probs = stable_softmax([0.0, 0.0, 0.0])
    np.testing.assert_allclose(equal_probs, [1/3, 1/3, 1/3])


def test_action_mapping_decoding(default_config):
    adapter = ActionMappingAdapter(policy_id="test_ppo")
    logits = [1.0, 0.5, -0.5, 0.0, 1.0, 0.2]
    prop = adapter.decode_action(logits, default_config)

    assert prop.policy_id == "test_ppo"
    assert len(prop.radio_allocations) == 3
    assert len(prop.compute_allocations) == 3

    # Total capacity must not exceed 100
    r_sum = sum(prop.radio_allocations.values())
    c_sum = sum(prop.compute_allocations.values())
    assert r_sum <= 100.01
    assert c_sum <= 100.01

    # Reservations must be respected
    assert prop.radio_allocations[SliceId.EMBB] >= 20.0
    assert prop.radio_allocations[SliceId.URLLC] >= 25.0
    assert prop.radio_allocations[SliceId.MURLLC] >= 15.0

    # Deterministic priority hierarchy
    assert prop.priorities[SliceId.URLLC] == 10
    assert prop.priorities[SliceId.MURLLC] == 5
    assert prop.priorities[SliceId.EMBB] == 1


def test_action_mapping_invalid_inputs(default_config):
    adapter = ActionMappingAdapter()
    with pytest.raises(ValueError, match="shape"):
        adapter.decode_action([1.0, 2.0], default_config)

    with pytest.raises(ValueError, match="non-finite"):
        adapter.decode_action([1.0, np.nan, 0.0, 1.0, 0.0, 0.0], default_config)


# ---------------------------------------------------------------------------
# 3. ViolationCostAdapter Tests
# ---------------------------------------------------------------------------

def test_violation_cost_calculation():
    adapter = ViolationCostAdapter(cost_limit=0.01)

    # 1. Zero offered packets on critical slices
    step_zero = StepMetrics(
        step=1, sim_time_sec=0.01,
        throughput_mbps={s: 0.0 for s in CANONICAL_SLICE_IDS},
        p95_latency_ms={s: None for s in CANONICAL_SLICE_IDS},
        packet_delivery_ratio={s: None for s in CANONICAL_SLICE_IDS},
        sla_status={s: True for s in CANONICAL_SLICE_IDS},
        sla_breach_count=0,
        radio_utilization_ratio=0.0,
        compute_utilization_ratio=0.0,
        allocation_churn=0.0,
        safety_intervention=False,
        reward_components=None,
        offered_packets={SliceId.EMBB: 100, SliceId.URLLC: 0, SliceId.MURLLC: 0},
        delivered_packets={SliceId.EMBB: 100, SliceId.URLLC: 0, SliceId.MURLLC: 0},
        dropped_packets={SliceId.EMBB: 0, SliceId.URLLC: 0, SliceId.MURLLC: 0},
        pending_packets={s: 0 for s in CANONICAL_SLICE_IDS},
        sla_state_details={s: "PASS" for s in CANONICAL_SLICE_IDS},
    )
    assert adapter.compute_step_cost(step_zero) == 0.0

    # 2. 10 drops out of 100 critical packets (cost = 0.10)
    step_loss = step_zero.model_copy(update={
        "offered_packets": {SliceId.EMBB: 100, SliceId.URLLC: 50, SliceId.MURLLC: 50},
        "dropped_packets": {SliceId.EMBB: 0, SliceId.URLLC: 5, SliceId.MURLLC: 5},
    })
    assert np.isclose(adapter.compute_step_cost(step_loss), 0.10)


# ---------------------------------------------------------------------------
# 4. LagrangianMultiplier Tests
# ---------------------------------------------------------------------------

def test_lagrangian_multiplier_update():
    lag = LagrangianMultiplier(init_lambda=0.0, lr=0.1, cost_limit=0.01, max_lambda=10.0)

    # Cost below limit -> remains 0.0 (non-negative projection)
    new_lambda = lag.update(episode_mean_cost=0.005)
    assert new_lambda == 0.0

    # Cost above limit (0.05 > 0.01 -> diff 0.04 -> +0.004)
    new_lambda = lag.update(episode_mean_cost=0.05)
    assert np.isclose(new_lambda, 0.004)

    # Successive high violations
    for _ in range(5):
        lag.update(episode_mean_cost=0.20)
    assert lag.value > 0.05

    # Checkpoint serialization
    state = lag.get_state()
    lag2 = LagrangianMultiplier()
    lag2.load_state(state)
    assert np.isclose(lag2.value, lag.value)

    # Reset
    lag.reset()
    assert lag.value == 0.0


# ---------------------------------------------------------------------------
# 5. MacroControlAdapter Tests
# ---------------------------------------------------------------------------

def test_macro_control_adapter_ten_steps(default_config):
    sim = FallbackNetworkSimulator(config=default_config)
    curr_state = sim.reset(seed=42)
    adapter = MacroControlAdapter(simulator=sim, config=default_config, steps_per_interval=10)

    action = ExecutedAction(
        radio_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 35.0, SliceId.MURLLC: 25.0},
        compute_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 35.0, SliceId.MURLLC: 25.0},
        priorities={SliceId.URLLC: 10, SliceId.MURLLC: 5, SliceId.EMBB: 1},
        is_modified_by_safety=False,
    )

    next_state, metrics, diag = adapter.execute_macro_step(curr_state, action)

    # Clock should advance by 10 steps of 10 ms = 100 ms = 0.100 s
    assert next_state.step == 10
    assert np.isclose(next_state.sim_time_sec, 0.100)

    # Metrics should have valid throughput and packet counts
    assert metrics.step == 10
    assert metrics.throughput_mbps[SliceId.EMBB] > 0.0
    assert sum(metrics.offered_packets.values()) > 0
    assert sum(metrics.delivered_packets.values()) > 0
