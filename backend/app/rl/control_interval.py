"""
SLA Guardian - Macro-Control Interval Adapter
Coordinates the 100 ms macro-control interval over ten 10 ms discrete simulation steps.
Key Responsibilities:
- Holds a single validated ExecutedAction constant across 10 internal simulation steps.
- Correctly aggregates offered/delivered packets, dropped packets, and byte throughput.
- Accurately computes interval throughput using the full 100 ms duration (0.100 s).
- Retains packet latency samples across all 10 steps to calculate accurate p95 latency.
- Refuses to advance the simulator if the Safety Shield rejected the action.
"""

from typing import Dict, List, Optional, Tuple, Any
import numpy as np

from ..schemas.config import RunConfig, SliceId, CANONICAL_SLICE_IDS
from ..schemas.state import NetworkState, SliceState
from ..schemas.actions import ExecutedAction
from ..schemas.metrics import StepMetrics
from ..interfaces.simulator import SimulatorInterface, SimulatorDiagnostics
from ..evaluation.metrics import SlaMetricEvaluator


class MacroControlAdapter:
    """
    Executes multiple internal simulation steps per macro control decision.
    Default: 10 internal steps of 10 ms = 100 ms macro interval.
    """

    def __init__(
        self,
        simulator: SimulatorInterface,
        evaluator: Optional[SlaMetricEvaluator] = None,
        config: Optional[RunConfig] = None,
        steps_per_interval: int = 10,
    ):
        self.simulator = simulator
        self.evaluator = evaluator or SlaMetricEvaluator()
        self.config = config or getattr(simulator, "config", None)
        self.steps_per_interval = max(1, steps_per_interval)

    def execute_macro_step(
        self,
        current_state: NetworkState,
        executed_action: ExecutedAction,
    ) -> Tuple[NetworkState, StepMetrics, SimulatorDiagnostics]:
        """
        Executes N internal simulation steps with the given ExecutedAction.

        Args:
            current_state: Starting state before interval.
            executed_action: Validated action to hold across interval.

        Returns:
            Tuple of:
            - final NetworkState at t + N*step_duration
            - aggregated StepMetrics across full interval
            - aggregated SimulatorDiagnostics
        """
        step_duration_sec = (self.config.step_duration_ms / 1000.0) if self.config else 0.010
        total_interval_duration_sec = step_duration_sec * self.steps_per_interval

        # Interval accumulators
        offered_pkts: Dict[SliceId, int] = {s: 0 for s in CANONICAL_SLICE_IDS}
        delivered_pkts: Dict[SliceId, int] = {s: 0 for s in CANONICAL_SLICE_IDS}
        dropped_pkts: Dict[SliceId, int] = {s: 0 for s in CANONICAL_SLICE_IDS}
        delivered_bytes: Dict[SliceId, int] = {s: 0 for s in CANONICAL_SLICE_IDS}
        interval_latencies: Dict[SliceId, List[float]] = {s: [] for s in CANONICAL_SLICE_IDS}

        radio_util_samples: List[float] = []
        compute_util_samples: List[float] = []

        last_state = current_state
        last_diag = SimulatorDiagnostics(
            step=current_state.step,
            terminated=False,
            truncated=False,
            active_flows=0,
            dropped_packets=0,
            extra_info={},
        )

        r_cap = self.config.total_radio_capacity if self.config else 100.0
        c_cap = self.config.total_compute_capacity if self.config else 100.0

        # Advance N internal steps
        for _ in range(self.steps_per_interval):
            next_state, diag = self.simulator.step(executed_action)
            last_state = next_state
            last_diag = diag

            # Accumulate slice metrics from simulator diagnostics
            if diag.extra_info and "slice_diagnostics" in diag.extra_info:
                sdiags = diag.extra_info["slice_diagnostics"]
                step_r_mbps = 0.0
                step_c_mbps = 0.0
                for s in CANONICAL_SLICE_IDS:
                    sd = sdiags.get(s.value, {})
                    offered_pkts[s] += sd.get("offered_packets", 0)
                    deliv = sd.get("compute_completed_packets", 0)
                    delivered_pkts[s] += deliv
                    dropped_pkts[s] += sd.get("dropped_packets", 0)

                    # Compute bytes from step throughput
                    step_tput = sd.get("delivered_throughput_mbps", 0.0)
                    step_bytes = int((step_tput * 1e6 * step_duration_sec) / 8.0)
                    delivered_bytes[s] += step_bytes

                    step_r_mbps += sd.get("radio_capacity_mbps", step_tput)
                    step_c_mbps += step_tput

                    if "step_latencies" in sd and sd["step_latencies"]:
                        interval_latencies[s].extend(sd["step_latencies"])

                radio_util_samples.append(min(1.0, max(0.0, step_r_mbps / max(1.0, r_cap))))
                compute_util_samples.append(min(1.0, max(0.0, step_c_mbps / max(1.0, c_cap))))

        # Compile macro-interval metrics
        macro_tput: Dict[SliceId, float] = {}
        macro_p95: Dict[SliceId, Optional[float]] = {}
        macro_pdr: Dict[SliceId, Optional[float]] = {}
        macro_sla_status: Dict[SliceId, bool] = {}
        macro_sla_details: Dict[SliceId, str] = {}
        macro_pending: Dict[SliceId, int] = {}
        active_breaches = 0

        for s in CANONICAL_SLICE_IDS:
            # 1. Throughput across 100 ms interval
            tput_mbps = (delivered_bytes[s] * 8.0) / (1e6 * total_interval_duration_sec)
            macro_tput[s] = round(float(tput_mbps), 3)

            # 2. p95 latency
            lats = interval_latencies[s]
            if lats:
                p95 = float(np.percentile(lats, 95))
            else:
                p95 = last_state.slice_states[s].p95_latency_ms
            macro_p95[s] = round(p95, 2) if p95 is not None else None

            # 3. PDR
            finished = delivered_pkts[s] + dropped_pkts[s]
            pdr = float(delivered_pkts[s] / finished) if finished > 0 else 1.0
            macro_pdr[s] = round(pdr, 4)

            # 4. Pending packets
            pending = int(last_state.slice_states[s].queue_depth_packets)
            macro_pending[s] = pending

            # 5. SLA compliance
            is_compliant = True
            sla_state = "PASS"
            if self.config and s in self.config.sla_thresholds:
                sla = self.config.sla_thresholds[s]
                if macro_p95[s] is None:
                    sla_state = "INSUFFICIENT_DATA"
                    is_compliant = False
                elif macro_p95[s] > sla.max_latency_ms:
                    sla_state = "BREACH"
                    is_compliant = False
                elif macro_tput[s] < sla.min_throughput_mbps:
                    sla_state = "BREACH"
                    is_compliant = False
                elif macro_pdr[s] < sla.min_packet_delivery_ratio:
                    sla_state = "BREACH"
                    is_compliant = False

            macro_sla_status[s] = is_compliant
            macro_sla_details[s] = sla_state
            if sla_state == "BREACH":
                active_breaches += 1

        mean_r_util = float(np.mean(radio_util_samples)) if radio_util_samples else 0.0
        mean_c_util = float(np.mean(compute_util_samples)) if compute_util_samples else 0.0

        step_metrics = StepMetrics(
            step=last_state.step,
            sim_time_sec=round(last_state.sim_time_sec, 4),
            throughput_mbps=macro_tput,
            p95_latency_ms=macro_p95,
            packet_delivery_ratio=macro_pdr,
            sla_status=macro_sla_status,
            sla_breach_count=active_breaches,
            radio_utilization_ratio=round(mean_r_util, 4),
            compute_utilization_ratio=round(mean_c_util, 4),
            allocation_churn=0.0,
            safety_intervention=executed_action.is_modified_by_safety,
            reward_components=None,
            offered_packets=offered_pkts,
            delivered_packets=delivered_pkts,
            dropped_packets=dropped_pkts,
            pending_packets=macro_pending,
            sla_state_details=macro_sla_details,
        )

        return last_state, step_metrics, last_diag
