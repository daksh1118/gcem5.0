"""
Unit and integration tests for SafetyShield and PolicyExecutionPipeline.
Verifies hard constraint enforcement, reservation-aware projection,
rejection semantics, determinism, and simulator boundary protection.
"""

import math
import pytest
from backend.app.schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig, SliceSlaConfig, SliceReservationConfig
from backend.app.schemas.state import SliceState, NetworkState
from backend.app.schemas.actions import ProposedAction, ExecutedAction, SafetyValidationStatus, SafetyResult
from backend.app.control.safety_shield import SafetyShield
from backend.app.control.pipeline import PolicyExecutionPipeline, DecisionRecord
from backend.app.simulator.fallback import FallbackNetworkSimulator
from backend.app.policies.static import StaticSlicingPolicy
from backend.app.policies.heuristic import AdaptiveDemandHeuristicPolicy
from backend.app.evaluation.metrics import SlaMetricEvaluator


@pytest.fixture
def base_config() -> RunConfig:
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
        scenario_id="shield_test",
        seed=42,
        total_radio_capacity=100.0,
        total_compute_capacity=100.0,
        sla_thresholds=sla,
        minimum_reservations=reservations,
    )


def make_dummy_state(step: int = 1, sim_time: float = 0.010) -> NetworkState:
    slice_states = {
        s: SliceState(
            slice_id=s,
            offered_demand_mbps=20.0,
            current_radio_allocation=33.3,
            current_compute_allocation=33.3,
        )
        for s in CANONICAL_SLICE_IDS
    }
    return NetworkState(
        step=step,
        sim_time_sec=sim_time,
        total_radio_capacity=100.0,
        total_compute_capacity=100.0,
        slice_states=slice_states,
    )


def test_valid_proposal_passes_unmodified(base_config):
    """An already valid proposal within budgets and reservations passes with VALID status."""
    shield = SafetyShield()
    state = make_dummy_state()

    proposal = ProposedAction(
        radio_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
        policy_id="test_policy",
    )

    result = shield.validate(proposal, state, base_config)

    assert result.validation_status == SafetyValidationStatus.VALID
    assert result.intervention_occurred is False
    assert len(result.intervention_reasons) == 0
    assert result.executed_action is not None
    assert result.executed_action.is_modified_by_safety is False
    assert result.executed_action.radio_allocations == proposal.radio_allocations
    assert result.executed_action.priorities == proposal.priorities


def test_proposal_immutability(base_config):
    """Validates that the input ProposedAction is never modified in place."""
    shield = SafetyShield()
    state = make_dummy_state()

    proposal = ProposedAction(
        radio_allocations={SliceId.EMBB: 60.0, SliceId.URLLC: 50.0, SliceId.MURLLC: 40.0},
        compute_allocations={SliceId.EMBB: 50.0, SliceId.URLLC: 50.0, SliceId.MURLLC: 50.0},
        priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
    )

    original_radio_sum = sum(proposal.radio_allocations.values())
    result = shield.validate(proposal, state, base_config)

    # Proposal remains unchanged
    assert sum(proposal.radio_allocations.values()) == original_radio_sum
    # But executed action is clamped to 100.0
    assert result.executed_action is not None
    assert pytest.approx(sum(result.executed_action.radio_allocations.values()), 1e-3) == 100.0


def test_radio_over_allocation_corrected_with_reservations(base_config):
    """
    Over-allocated proposal (sum = 150 > 100) is projected proportionally
    while strictly guaranteeing minimum reservations (URLLC >= 25, eMBB >= 20, mURLLC >= 15).
    """
    shield = SafetyShield()
    state = make_dummy_state()

    # Requests 70, 50, 30 = 150 > 100
    proposal = ProposedAction(
        radio_allocations={SliceId.EMBB: 70.0, SliceId.URLLC: 50.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 30.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
    )

    result = shield.validate(proposal, state, base_config)

    assert result.validation_status == SafetyValidationStatus.INTERVENED_CLAMPED
    assert result.intervention_occurred is True
    assert result.executed_action is not None
    assert result.executed_action.is_modified_by_safety is True

    exec_r = result.executed_action.radio_allocations
    assert pytest.approx(sum(exec_r.values()), 1e-3) == 100.0
    assert exec_r[SliceId.URLLC] >= 25.0
    assert exec_r[SliceId.EMBB] >= 20.0
    assert exec_r[SliceId.MURLLC] >= 15.0


def test_compute_under_reservation_restored(base_config):
    """Proposals below minimum reservations are elevated to the required baseline."""
    shield = SafetyShield()
    state = make_dummy_state()

    # URLLC compute proposed as 5.0 (min reservation is 25.0)
    proposal = ProposedAction(
        radio_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 50.0, SliceId.URLLC: 5.0, SliceId.MURLLC: 25.0},
        priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
    )

    result = shield.validate(proposal, state, base_config)

    assert result.intervention_occurred is True
    assert result.executed_action is not None
    assert result.executed_action.compute_allocations[SliceId.URLLC] >= 25.0
    assert any("Restored URLLC compute" in r for r in result.intervention_reasons)


def test_non_finite_allocation_rejected():
    """NaN or Infinite allocations cause immediate explicit rejection with no ExecutedAction."""
    shield = SafetyShield()
    state = make_dummy_state()

    proposal = ProposedAction.model_construct(
        radio_allocations={SliceId.EMBB: float("nan"), SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
    )

    result = shield.validate(proposal, state)

    assert result.validation_status == SafetyValidationStatus.REJECTED
    assert result.executed_action is None
    assert result.resource_budget_verified is False
    assert any("Non-finite" in r for r in result.intervention_reasons)


def test_infeasible_reservation_config_rejected():
    """If reservations exceed total capacity (e.g. sum = 120 > 100), Shield rejects proposal."""
    infeasible_sla = {
        SliceId.EMBB: SliceSlaConfig(max_latency_ms=25.0, min_throughput_mbps=40.0, min_packet_delivery_ratio=0.98),
        SliceId.URLLC: SliceSlaConfig(max_latency_ms=5.0, min_throughput_mbps=8.0, min_packet_delivery_ratio=0.9999),
        SliceId.MURLLC: SliceSlaConfig(max_latency_ms=15.0, min_throughput_mbps=15.0, min_packet_delivery_ratio=0.999),
    }
    # Infeasible reservations summing to 120
    infeasible_res = {
        SliceId.EMBB: SliceReservationConfig(min_radio_capacity=50.0, min_compute_capacity=10.0),
        SliceId.URLLC: SliceReservationConfig(min_radio_capacity=50.0, min_compute_capacity=10.0),
        SliceId.MURLLC: SliceReservationConfig(min_radio_capacity=20.0, min_compute_capacity=10.0),
    }
    infeasible_config = RunConfig.model_construct(
        scenario_id="infeasible",
        total_radio_capacity=100.0,
        total_compute_capacity=100.0,
        sla_thresholds=infeasible_sla,
        minimum_reservations=infeasible_res,
    )

    shield = SafetyShield()
    state = make_dummy_state()
    proposal = ProposedAction(
        radio_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
    )

    result = shield.validate(proposal, state, infeasible_config)

    assert result.validation_status == SafetyValidationStatus.REJECTED
    assert result.executed_action is None
    assert any("Infeasible configuration" in r for r in result.intervention_reasons)


def test_projection_idempotence(base_config):
    """Validating an already projected action produces no further changes."""
    shield = SafetyShield()
    state = make_dummy_state()

    over_alloc = ProposedAction(
        radio_allocations={SliceId.EMBB: 70.0, SliceId.URLLC: 50.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 30.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
    )

    res1 = shield.validate(over_alloc, state, base_config)
    assert res1.executed_action is not None

    # Feed the executed action back as a new proposal
    prop2 = ProposedAction(
        radio_allocations=res1.executed_action.radio_allocations,
        compute_allocations=res1.executed_action.compute_allocations,
        priorities=res1.executed_action.priorities,
    )

    res2 = shield.validate(prop2, state, base_config)
    assert res2.validation_status == SafetyValidationStatus.VALID
    assert res2.intervention_occurred is False
    assert res2.executed_action.radio_allocations == res1.executed_action.radio_allocations


def test_pipeline_prevents_simulator_advance_on_rejection(base_config):
    """Pipeline intercepts rejected actions: simulator step count and sim time do not advance."""
    sim = FallbackNetworkSimulator(base_config)
    state = sim.reset(seed=42)
    assert state.step == 0

    class BrokenPolicy:
        policy_id = "broken_nan_policy"
        policy_version = "0.0.1"
        def predict(self, obs):
            return ProposedAction.model_construct(
                radio_allocations={SliceId.EMBB: float("nan"), SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
                compute_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
                priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
            )

    pipeline = PolicyExecutionPipeline(simulator=sim, config=base_config)
    next_state, record = pipeline.execute_step(state, BrokenPolicy())

    assert record.accepted is False
    assert record.safety_result.validation_status == SafetyValidationStatus.REJECTED
    # Simulator must remain at step 0
    assert next_state.step == 0
    assert next_state.sim_time_sec == 0.0


def test_pipeline_executes_valid_and_corrected_actions(base_config):
    """Pipeline successfully advances simulator when action is valid or corrected."""
    sim = FallbackNetworkSimulator(base_config)
    evaluator = SlaMetricEvaluator()
    pipeline = PolicyExecutionPipeline(simulator=sim, evaluator=evaluator, config=base_config)

    state = sim.reset(seed=42)

    class OverAllocatingPolicy:
        policy_id = "greedy_policy"
        policy_version = "0.1.0"
        def predict(self, obs):
            # Proposes 120 total radio
            return ProposedAction(
                radio_allocations={SliceId.EMBB: 50.0, SliceId.URLLC: 40.0, SliceId.MURLLC: 30.0},
                compute_allocations={SliceId.EMBB: 33.3, SliceId.URLLC: 33.4, SliceId.MURLLC: 33.3},
                priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
            )

    next_state, record = pipeline.execute_step(state, OverAllocatingPolicy())

    assert record.accepted is True
    assert record.safety_result.validation_status == SafetyValidationStatus.INTERVENED_CLAMPED
    assert next_state.step == 1
    assert pytest.approx(next_state.sim_time_sec, 1e-4) == 0.010
    assert record.step_metrics is not None
    assert record.step_metrics.step == 1
