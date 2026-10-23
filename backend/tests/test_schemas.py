"""
Unit tests for SLA Guardian shared data models.
Verifies slice validation, action distinguishability, telemetry serialization,
and state consistency rules.
"""

import json
import pytest
from pydantic import ValidationError

from backend.app.schemas.config import SliceId, CANONICAL_SLICE_IDS
from backend.app.schemas.state import SliceState, NetworkState
from backend.app.schemas.actions import (
    ProposedAction,
    ExecutedAction,
    SafetyValidationStatus,
    SafetyResult,
)
from backend.app.schemas.metrics import StepMetrics
from backend.app.schemas.results import RunStatus, RunResult


def test_slice_state_initialization_rule():
    """Verify that unmeasured metrics at initialization remain None rather than false zeroes."""
    init_state = SliceState(
        slice_id=SliceId.EMBB,
        offered_demand_mbps=45.0,
        current_radio_allocation=30.0,
        current_compute_allocation=30.0,
    )
    assert init_state.delivered_throughput_mbps is None
    assert init_state.p95_latency_ms is None
    assert init_state.packet_delivery_ratio is None
    assert init_state.sla_headroom == 1.0


def test_network_state_requires_exact_three_canonical_slices():
    """Requirement 4 & 5: Exactly canonical slices are accepted; missing/duplicates rejected."""
    s_embb = SliceState(slice_id=SliceId.EMBB, offered_demand_mbps=50.0, current_radio_allocation=30.0, current_compute_allocation=30.0)
    s_urllc = SliceState(slice_id=SliceId.URLLC, offered_demand_mbps=10.0, current_radio_allocation=35.0, current_compute_allocation=35.0)
    s_murllc = SliceState(slice_id=SliceId.MURLLC, offered_demand_mbps=20.0, current_radio_allocation=30.0, current_compute_allocation=30.0)

    # Valid state
    net_state = NetworkState(
        step=0,
        sim_time_sec=0.0,
        total_radio_capacity=100.0,
        total_compute_capacity=100.0,
        slice_states={
            SliceId.EMBB: s_embb,
            SliceId.URLLC: s_urllc,
            SliceId.MURLLC: s_murllc,
        }
    )
    assert len(net_state.slice_states) == 3

    # Missing mURLLC fails
    with pytest.raises(ValidationError) as exc:
        NetworkState(
            step=0,
            sim_time_sec=0.0,
            total_radio_capacity=100.0,
            total_compute_capacity=100.0,
            slice_states={
                SliceId.EMBB: s_embb,
                SliceId.URLLC: s_urllc,
            }
        )
    assert "Missing slice states" in str(exc.value)


def test_network_state_rejects_exceeded_total_capacity():
    """Verify total resource allocation consistency check."""
    s_embb = SliceState(slice_id=SliceId.EMBB, offered_demand_mbps=50.0, current_radio_allocation=50.0, current_compute_allocation=30.0)
    s_urllc = SliceState(slice_id=SliceId.URLLC, offered_demand_mbps=10.0, current_radio_allocation=40.0, current_compute_allocation=30.0)
    s_murllc = SliceState(slice_id=SliceId.MURLLC, offered_demand_mbps=20.0, current_radio_allocation=30.0, current_compute_allocation=30.0)

    # Total radio allocation = 50 + 40 + 30 = 120 > 100
    with pytest.raises(ValidationError) as exc:
        NetworkState(
            step=1,
            sim_time_sec=0.01,
            total_radio_capacity=100.0,
            total_compute_capacity=100.0,
            slice_states={
                SliceId.EMBB: s_embb,
                SliceId.URLLC: s_urllc,
                SliceId.MURLLC: s_murllc,
            }
        )
    assert "exceeds total radio capacity" in str(exc.value)


def test_action_distinguishability():
    """Requirement 6: Proposed actions and executed actions remain distinguishable."""
    proposed = ProposedAction(
        radio_allocations={SliceId.EMBB: 30.0, SliceId.URLLC: 40.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 30.0, SliceId.URLLC: 40.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
        policy_id="test_ppo_agent",
    )

    executed = ExecutedAction(
        radio_allocations={SliceId.EMBB: 25.0, SliceId.URLLC: 45.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 25.0, SliceId.URLLC: 45.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
        is_modified_by_safety=True,
        proposal_reference="prop_001",
    )

    # Type check distinguishability
    assert isinstance(proposed, ProposedAction)
    assert not isinstance(proposed, ExecutedAction)
    assert isinstance(executed, ExecutedAction)
    assert not isinstance(executed, ProposedAction)

    assert hasattr(proposed, "policy_id")
    assert not hasattr(executed, "policy_id")
    assert hasattr(executed, "is_modified_by_safety")
    assert not hasattr(proposed, "is_modified_by_safety")


def test_safety_result_contract():
    """Verify SafetyResult combines proposed and executed actions transparently."""
    proposed = ProposedAction(
        radio_allocations={SliceId.EMBB: 60.0, SliceId.URLLC: 10.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 50.0, SliceId.URLLC: 20.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 2, SliceId.URLLC: 1, SliceId.MURLLC: 3},
    )
    executed = ExecutedAction(
        radio_allocations={SliceId.EMBB: 45.0, SliceId.URLLC: 25.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 2, SliceId.URLLC: 1, SliceId.MURLLC: 3},
        is_modified_by_safety=True,
    )

    res = SafetyResult(
        proposed_action=proposed,
        executed_action=executed,
        intervention_occurred=True,
        validation_status=SafetyValidationStatus.INTERVENED_CLAMPED,
        intervention_reasons=["URLLC minimum reservation of 25.0 PRBs violated by proposal."],
        resource_budget_verified=True,
        step=5,
    )

    assert res.intervention_occurred is True
    assert res.validation_status == SafetyValidationStatus.INTERVENED_CLAMPED
    assert len(res.intervention_reasons) == 1


def test_metric_payload_json_serialization():
    """Requirement 7: Metric payloads serialize cleanly to JSON."""
    step_metric = StepMetrics(
        step=10,
        sim_time_sec=0.10,
        throughput_mbps={SliceId.EMBB: 52.3, SliceId.URLLC: 9.8, SliceId.MURLLC: 19.5},
        p95_latency_ms={SliceId.EMBB: 22.1, SliceId.URLLC: 4.2, SliceId.MURLLC: 14.1},
        packet_delivery_ratio={SliceId.EMBB: 0.985, SliceId.URLLC: 0.9999, SliceId.MURLLC: 0.9992},
        sla_status={SliceId.EMBB: True, SliceId.URLLC: True, SliceId.MURLLC: True},
        sla_breach_count=0,
        radio_utilization_ratio=0.82,
        compute_utilization_ratio=0.74,
        allocation_churn=0.05,
        safety_intervention=False,
        reward_components={"sla_bonus": 1.0, "churn_penalty": -0.05},
    )

    json_str = step_metric.model_dump_json()
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)

    assert parsed["step"] == 10
    assert parsed["throughput_mbps"]["eMBB"] == 52.3
    assert parsed["throughput_mbps"]["URLLC"] == 9.8
    assert parsed["throughput_mbps"]["mURLLC"] == 19.5
    assert parsed["sla_status"]["URLLC"] is True
    assert parsed["reward_components"]["sla_bonus"] == 1.0


def test_run_result_json_serialization():
    """Requirement 8: Run results serialize consistently to JSON."""
    step_metric = StepMetrics(
        step=1,
        sim_time_sec=0.01,
        throughput_mbps={SliceId.EMBB: 48.0, SliceId.URLLC: 10.0, SliceId.MURLLC: 20.0},
        p95_latency_ms={SliceId.EMBB: 21.0, SliceId.URLLC: 3.5, SliceId.MURLLC: 12.0},
        packet_delivery_ratio={SliceId.EMBB: 0.99, SliceId.URLLC: 1.0, SliceId.MURLLC: 0.999},
        sla_status={SliceId.EMBB: True, SliceId.URLLC: True, SliceId.MURLLC: True},
        radio_utilization_ratio=0.78,
        compute_utilization_ratio=0.65,
    )

    run_result = RunResult(
        run_id="run_exp_001",
        scenario_id="default_three_slice_baseline",
        seed=42,
        policy_id="heuristic_proportional",
        status=RunStatus.COMPLETED,
        completed_steps=1,
        metrics_history=[step_metric],
        aggregate_metrics={"mean_sla_compliance": 1.0, "mean_radio_util": 0.78},
    )

    json_str = run_result.model_dump_json()
    parsed = json.loads(json_str)

    assert parsed["run_id"] == "run_exp_001"
    assert parsed["status"] == "COMPLETED"
    assert len(parsed["metrics_history"]) == 1
    assert parsed["aggregate_metrics"]["mean_sla_compliance"] == 1.0
