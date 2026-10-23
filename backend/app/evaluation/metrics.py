"""
SLA Guardian - SLA Metric Evaluator
Implements EvaluatorInterface to evaluate network state transitions and diagnostics.
Calculates interval/run throughput, p95 latency, packet cohort conservation,
resource utilization, SLA compliance, and allocation churn.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import numpy as np

from ..schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig
from ..schemas.state import NetworkState
from ..schemas.actions import ExecutedAction
from ..schemas.metrics import StepMetrics
from ..schemas.results import RunResult, RunStatus
from ..interfaces.policy import EvaluatorInterface
from ..interfaces.simulator import SimulatorDiagnostics


@dataclass
class EpisodeAccumulator:
    """
    Per-run accumulator for tracking whole-episode cohort packet counts,
    cumulative bytes, and overall SLA breach history.
    """
    total_offered_packets: Dict[SliceId, int] = field(default_factory=lambda: {s: 0 for s in CANONICAL_SLICE_IDS})
    total_delivered_packets: Dict[SliceId, int] = field(default_factory=lambda: {s: 0 for s in CANONICAL_SLICE_IDS})
    total_dropped_packets: Dict[SliceId, int] = field(default_factory=lambda: {s: 0 for s in CANONICAL_SLICE_IDS})
    total_delivered_bytes: Dict[SliceId, int] = field(default_factory=lambda: {s: 0 for s in CANONICAL_SLICE_IDS})
    step_metrics_history: List[StepMetrics] = field(default_factory=list)
    previous_executed_action: Optional[ExecutedAction] = None

    def reset(self):
        """Clears all accumulators to prevent cross-run contamination."""
        self.total_offered_packets = {s: 0 for s in CANONICAL_SLICE_IDS}
        self.total_delivered_packets = {s: 0 for s in CANONICAL_SLICE_IDS}
        self.total_dropped_packets = {s: 0 for s in CANONICAL_SLICE_IDS}
        self.total_delivered_bytes = {s: 0 for s in CANONICAL_SLICE_IDS}
        self.step_metrics_history.clear()
        self.previous_executed_action = None


class SlaMetricEvaluator(EvaluatorInterface):
    """
    Evaluates simulation state transitions against SLA contracts and empirical telemetry.
    Strictly separates empirical measurements from policy rewards.
    """

    def __init__(self):
        self.accumulator = EpisodeAccumulator()

    def reset_accumulator(self):
        """Resets run-level accumulators between simulation runs."""
        self.accumulator.reset()

    def evaluate_transition(
        self,
        current_state: NetworkState,
        executed_action: ExecutedAction,
        next_state: NetworkState,
        config: Optional[RunConfig] = None,
        diagnostics: Optional[SimulatorDiagnostics] = None,
    ) -> StepMetrics:
        """
        Evaluates a single state transition (t -> t+1).
        
        Args:
            current_state: State at step t.
            executed_action: Action executed across step t -> t+1.
            next_state: Resulting state at step t+1.
            config: Active RunConfig containing SLA thresholds.
            diagnostics: SimulatorDiagnostics emitted by the simulator for step t+1.
            
        Returns:
            StepMetrics: Telemetry record for step t+1.
        """
        step = next_state.step
        sim_time = next_state.sim_time_sec
        step_duration_sec = max(1e-4, next_state.sim_time_sec - current_state.sim_time_sec)

        # 1. Extract slice diagnostics if available
        slice_diags: Dict[str, Any] = {}
        if diagnostics and diagnostics.extra_info and "slice_diagnostics" in diagnostics.extra_info:
            slice_diags = diagnostics.extra_info["slice_diagnostics"]

        throughput_mbps: Dict[SliceId, float] = {}
        p95_latencies: Dict[SliceId, Optional[float]] = {}
        pdr_values: Dict[SliceId, Optional[float]] = {}
        sla_statuses: Dict[SliceId, bool] = {}
        sla_state_details: Dict[SliceId, str] = {}
        offered_pkts: Dict[SliceId, int] = {}
        delivered_pkts: Dict[SliceId, int] = {}
        dropped_pkts: Dict[SliceId, int] = {}
        pending_pkts: Dict[SliceId, int] = {}

        total_radio_delivered_mbps = 0.0
        total_compute_delivered_mbps = 0.0
        active_breaches = 0

        for s in CANONICAL_SLICE_IDS:
            s_key = s.value
            sdiag = slice_diags.get(s_key, {})
            sstate = next_state.slice_states[s]

            # A. Delivered throughput for step
            deliv_mbps = sdiag.get("delivered_throughput_mbps", sstate.delivered_throughput_mbps)
            if deliv_mbps is None:
                deliv_mbps = 0.0
            throughput_mbps[s] = float(deliv_mbps)

            # B. p95 Latency
            p95_lat = sdiag.get("p95_latency_ms", sstate.p95_latency_ms)
            p95_latencies[s] = float(p95_lat) if p95_lat is not None else None

            # C. Packet counts
            offered = sdiag.get("offered_packets", 0)
            deliv = sdiag.get("compute_completed_packets", 0)
            dropped = sdiag.get("dropped_packets", 0)
            r_queue = sdiag.get("radio_queue_packets", 0)
            c_queue = sdiag.get("compute_queue_packets", 0)
            pending = r_queue + c_queue

            offered_pkts[s] = offered
            delivered_pkts[s] = deliv
            dropped_pkts[s] = dropped
            pending_pkts[s] = pending

            # Update accumulator
            self.accumulator.total_offered_packets[s] += offered
            self.accumulator.total_delivered_packets[s] += deliv
            self.accumulator.total_dropped_packets[s] += dropped
            if "offered_bytes" in sdiag:
                # compute bytes delivered from throughput
                deliv_bytes = int((throughput_mbps[s] * 1e6 * step_duration_sec) / 8.0)
                self.accumulator.total_delivered_bytes[s] += deliv_bytes

            # D. Packet Delivery Ratio for step
            step_finished = deliv + dropped
            if step_finished > 0:
                pdr = float(deliv / step_finished)
            else:
                pdr = 1.0 if pending == 0 else None
            pdr_values[s] = pdr

            # E. SLA Compliance Evaluation
            if config and s in config.sla_thresholds:
                sla = config.sla_thresholds[s]
                # Missing latency telemetry is strictly INSUFFICIENT_DATA, never a PASS
                if p95_lat is None:
                    sla_state = "INSUFFICIENT_DATA"
                    is_compliant = False
                elif p95_lat > sla.max_latency_ms:
                    sla_state = "BREACH"
                    is_compliant = False
                elif throughput_mbps[s] < sla.min_throughput_mbps:
                    sla_state = "BREACH"
                    is_compliant = False
                elif pdr is not None and pdr < sla.min_packet_delivery_ratio:
                    sla_state = "BREACH"
                    is_compliant = False
                else:
                    sla_state = "PASS"
                    is_compliant = True
            else:
                sla_state = "PASS"
                is_compliant = True

            sla_statuses[s] = is_compliant
            sla_state_details[s] = sla_state
            if sla_state == "BREACH":
                active_breaches += 1

            total_radio_delivered_mbps += sdiag.get("radio_capacity_mbps", throughput_mbps[s])
            total_compute_delivered_mbps += throughput_mbps[s]

        # 2. Resource Utilization Ratios
        tot_radio_cap = config.total_radio_capacity if config else next_state.total_radio_capacity
        tot_compute_cap = config.total_compute_capacity if config else next_state.total_compute_capacity

        radio_util = float(min(1.0, max(0.0, total_radio_delivered_mbps / max(1.0, tot_radio_cap))))
        compute_util = float(min(1.0, max(0.0, total_compute_delivered_mbps / max(1.0, tot_compute_cap))))

        # 3. Allocation Churn (L1 distance of resource shift)
        churn = 0.0
        if self.accumulator.previous_executed_action is not None:
            prev = self.accumulator.previous_executed_action
            for s in CANONICAL_SLICE_IDS:
                churn += abs(executed_action.radio_allocations[s] - prev.radio_allocations[s])
                churn += abs(executed_action.compute_allocations[s] - prev.compute_allocations[s])
        self.accumulator.previous_executed_action = executed_action

        # 4. Construct StepMetrics record
        metric = StepMetrics(
            step=step,
            sim_time_sec=round(sim_time, 4),
            throughput_mbps=throughput_mbps,
            p95_latency_ms=p95_latencies,
            packet_delivery_ratio=pdr_values,
            sla_status=sla_statuses,
            sla_breach_count=active_breaches,
            radio_utilization_ratio=round(radio_util, 4),
            compute_utilization_ratio=round(compute_util, 4),
            allocation_churn=round(churn, 4),
            safety_intervention=executed_action.is_modified_by_safety,
            reward_components=None,  # Decoupled from RL reward
            offered_packets=offered_pkts,
            delivered_packets=delivered_pkts,
            dropped_packets=dropped_pkts,
            pending_packets=pending_pkts,
            sla_state_details=sla_state_details,
        )

        self.accumulator.step_metrics_history.append(metric)
        return metric

    def build_run_result(
        self,
        run_id: str,
        scenario_id: str,
        seed: int,
        policy_id: str,
        policy_version: str = "1.0",
        config: Optional[RunConfig] = None,
    ) -> RunResult:
        """
        Builds a comprehensive RunResult summarizing the entire executed episode.
        Calculates whole-run throughput and overall SLA compliance.
        """
        history = self.accumulator.step_metrics_history
        completed_steps = len(history)
        total_time_sec = history[-1].sim_time_sec if history else 0.0

        aggregate: Dict[str, float] = {}

        # Whole-run throughput per slice
        for s in CANONICAL_SLICE_IDS:
            tot_bytes = self.accumulator.total_delivered_bytes[s]
            if total_time_sec > 0.0:
                run_tput = (tot_bytes * 8.0) / (total_time_sec * 1e6)
            else:
                run_tput = 0.0
            aggregate[f"mean_throughput_mbps_{s.value}"] = round(run_tput, 3)

            # Whole-run PDR
            tot_deliv = self.accumulator.total_delivered_packets[s]
            tot_drop = self.accumulator.total_dropped_packets[s]
            tot_finished = tot_deliv + tot_drop
            pdr = float(tot_deliv / tot_finished) if tot_finished > 0 else 1.0
            aggregate[f"overall_pdr_{s.value}"] = round(pdr, 4)

            # Final pending packets
            if history and history[-1].pending_packets:
                aggregate[f"final_pending_packets_{s.value}"] = float(history[-1].pending_packets[s])

        # Overall SLA breach rate across steps
        if completed_steps > 0:
            breach_steps = sum(1 for m in history if m.sla_breach_count > 0)
            aggregate["sla_breach_step_ratio"] = round(breach_steps / completed_steps, 4)
            aggregate["mean_radio_utilization"] = round(float(np.mean([m.radio_utilization_ratio for m in history])), 4)
            aggregate["mean_compute_utilization"] = round(float(np.mean([m.compute_utilization_ratio for m in history])), 4)
            aggregate["total_churn"] = round(float(sum(m.allocation_churn for m in history)), 3)

        return RunResult(
            run_id=run_id,
            scenario_id=scenario_id,
            seed=seed,
            policy_id=policy_id,
            policy_version=policy_version,
            status=RunStatus.COMPLETED,
            completed_steps=completed_steps,
            metrics_history=list(history),
            aggregate_metrics=aggregate,
        )
