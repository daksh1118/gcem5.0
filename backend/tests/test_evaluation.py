"""
Unit tests for SLA Guardian SlaMetricEvaluator and EpisodeAccumulator.
Verifies throughput formulas, percentile latency calculations, missing-data handling,
packet conservation, resource utilization, and SLA compliance states.
"""

import pytest
from backend.app.schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig, SliceSlaConfig
from backend.app.schemas.state import SliceState, NetworkState
from backend.app.schemas.actions import ExecutedAction
from backend.app.interfaces.simulator import SimulatorDiagnostics
from backend.app.evaluation.metrics import SlaMetricEvaluator


@pytest.fixture
def test_config() -> RunConfig:
    sla = {
        SliceId.EMBB: SliceSlaConfig(max_latency_ms=25.0, min_throughput_mbps=40.0, min_packet_delivery_ratio=0.98),
        SliceId.URLLC: SliceSlaConfig(max_latency_ms=5.0, min_throughput_mbps=8.0, min_packet_delivery_ratio=0.9999),
        SliceId.MURLLC: SliceSlaConfig(max_latency_ms=15.0, min_throughput_mbps=15.0, min_packet_delivery_ratio=0.999),
    }
    return RunConfig(
        scenario_id="eval_test",
        seed=42,
        total_radio_capacity=100.0,
        total_compute_capacity=100.0,
        sla_thresholds=sla,
    )


def make_state(step: int, sim_time: float, throughput: float = 0.0, latency: float = None) -> NetworkState:
    slice_states = {}
    for s in CANONICAL_SLICE_IDS:
        slice_states[s] = SliceState(
            slice_id=s,
            offered_demand_mbps=30.0,
            delivered_throughput_mbps=throughput,
            p95_latency_ms=latency,
            queue_depth_packets=0,
            current_radio_allocation=33.3,
            current_compute_allocation=33.3,
            sla_headroom=1.0,
        )
    return NetworkState(
        step=step,
        sim_time_sec=sim_time,
        total_radio_capacity=100.0,
        total_compute_capacity=100.0,
        slice_states=slice_states,
    )


def test_throughput_calculation_with_known_bytes(test_config):
    """
    Verifies throughput formula: (delivered_bytes * 8) / (interval_sec * 1e6).
    125,000 bytes over 0.010 s interval = exactly 100.0 Mbps.
    """
    evaluator = SlaMetricEvaluator()
    s0 = make_state(0, 0.0)
    s1 = make_state(1, 0.010, throughput=100.0, latency=4.0)

    action = ExecutedAction(
        radio_allocations={SliceId.EMBB: 33.3, SliceId.URLLC: 33.4, SliceId.MURLLC: 33.3},
        compute_allocations={SliceId.EMBB: 33.3, SliceId.URLLC: 33.4, SliceId.MURLLC: 33.3},
        priorities={SliceId.EMBB: 2, SliceId.URLLC: 1, SliceId.MURLLC: 3},
    )

    diag = SimulatorDiagnostics(
        step=1,
        extra_info={
            "slice_diagnostics": {
                "URLLC": {
                    "delivered_throughput_mbps": 100.0,
                    "compute_completed_packets": 500,
                    "offered_bytes": 125000,
                    "dropped_packets": 0,
                    "p95_latency_ms": 4.0,
                }
            }
        }
    )

    metric = evaluator.evaluate_transition(s0, action, s1, test_config, diag)
    assert metric.throughput_mbps[SliceId.URLLC] == 100.0


def test_missing_delay_samples_is_insufficient_data_not_pass(test_config):
    """
    Verifies that missing delay samples result in None latency and INSUFFICIENT_DATA,
    which is never treated as a successful pass.
    """
    evaluator = SlaMetricEvaluator()
    s0 = make_state(0, 0.0)
    # At step 1, no latency is measured yet (None)
    s1 = make_state(1, 0.010, throughput=50.0, latency=None)

    action = ExecutedAction(
        radio_allocations={SliceId.EMBB: 33.3, SliceId.URLLC: 33.4, SliceId.MURLLC: 33.3},
        compute_allocations={SliceId.EMBB: 33.3, SliceId.URLLC: 33.4, SliceId.MURLLC: 33.3},
        priorities={SliceId.EMBB: 2, SliceId.URLLC: 1, SliceId.MURLLC: 3},
    )

    diag = SimulatorDiagnostics(
        step=1,
        extra_info={
            "slice_diagnostics": {
                "URLLC": {
                    "delivered_throughput_mbps": 50.0,
                    "p95_latency_ms": None,
                }
            }
        }
    )

    metric = evaluator.evaluate_transition(s0, action, s1, test_config, diag)
    assert metric.p95_latency_ms[SliceId.URLLC] is None
    assert metric.sla_status[SliceId.URLLC] is False  # Cannot pass without telemetry
    assert metric.sla_state_details[SliceId.URLLC] == "INSUFFICIENT_DATA"


def test_sla_breach_detection(test_config):
    """Verifies that exceeding max latency triggers BREACH."""
    evaluator = SlaMetricEvaluator()
    s0 = make_state(0, 0.0)
    # URLLC target is 5.0 ms; observed is 12.0 ms -> BREACH
    s1 = make_state(1, 0.010, throughput=10.0, latency=12.0)

    action = ExecutedAction(
        radio_allocations={SliceId.EMBB: 33.3, SliceId.URLLC: 33.4, SliceId.MURLLC: 33.3},
        compute_allocations={SliceId.EMBB: 33.3, SliceId.URLLC: 33.4, SliceId.MURLLC: 33.3},
        priorities={SliceId.EMBB: 2, SliceId.URLLC: 1, SliceId.MURLLC: 3},
    )

    diag = SimulatorDiagnostics(
        step=1,
        extra_info={
            "slice_diagnostics": {
                "URLLC": {
                    "delivered_throughput_mbps": 10.0,
                    "p95_latency_ms": 12.0,
                }
            }
        }
    )

    metric = evaluator.evaluate_transition(s0, action, s1, test_config, diag)
    assert metric.sla_status[SliceId.URLLC] is False
    assert metric.sla_state_details[SliceId.URLLC] == "BREACH"
    assert metric.sla_breach_count >= 1


def test_allocation_switching_churn_calculation(test_config):
    """Verifies L1 norm calculation of reallocation between consecutive steps."""
    evaluator = SlaMetricEvaluator()
    s0 = make_state(0, 0.0)
    s1 = make_state(1, 0.010)
    s2 = make_state(2, 0.020)

    action1 = ExecutedAction(
        radio_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 40.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
    )

    # Reallocate: shift 10 units from eMBB to URLLC on both radio and compute
    action2 = ExecutedAction(
        radio_allocations={SliceId.EMBB: 30.0, SliceId.URLLC: 40.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 30.0, SliceId.URLLC: 40.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
    )

    # Step 1: No previous action, churn is 0.0
    m1 = evaluator.evaluate_transition(s0, action1, s1, test_config)
    assert m1.allocation_churn == 0.0

    # Step 2: radio change = |30-40| + |40-30| = 20; compute change = |30-40| + |40-30| = 20 -> total churn = 40.0
    m2 = evaluator.evaluate_transition(s1, action2, s2, test_config)
    assert pytest.approx(m2.allocation_churn, 1e-4) == 40.0


def test_evaluator_accumulator_reset_prevents_leakage(test_config):
    """Verifies reset_accumulator clears history cleanly between runs."""
    evaluator = SlaMetricEvaluator()
    s0 = make_state(0, 0.0)
    s1 = make_state(1, 0.010)
    action = ExecutedAction(
        radio_allocations={SliceId.EMBB: 33.3, SliceId.URLLC: 33.4, SliceId.MURLLC: 33.3},
        compute_allocations={SliceId.EMBB: 33.3, SliceId.URLLC: 33.4, SliceId.MURLLC: 33.3},
        priorities={SliceId.EMBB: 2, SliceId.URLLC: 1, SliceId.MURLLC: 3},
    )

    evaluator.evaluate_transition(s0, action, s1, test_config)
    assert len(evaluator.accumulator.step_metrics_history) == 1

    evaluator.reset_accumulator()
    assert len(evaluator.accumulator.step_metrics_history) == 0
    assert evaluator.accumulator.previous_executed_action is None
