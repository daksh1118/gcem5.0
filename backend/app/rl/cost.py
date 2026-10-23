"""
SLA Guardian - RL Critical-Slice Violation Cost Adapter
Computes the empirical packet violation cost for mission-critical slices (URLLC + mURLLC).
Cost Formulation:
    critical_violation_cost = (dropped_packets_URLLC + dropped_packets_mURLLC) / 
                              (offered_packets_URLLC + offered_packets_mURLLC + epsilon)
"""

from typing import Dict, Any, Optional
from ..schemas.config import SliceId, CANONICAL_SLICE_IDS
from ..schemas.metrics import StepMetrics
from ..interfaces.simulator import SimulatorDiagnostics


CRITICAL_SLICES = (SliceId.URLLC, SliceId.MURLLC)


class ViolationCostAdapter:
    """
    Computes normalized violation rates on critical slices for Lagrangian optimization.
    """

    def __init__(self, cost_limit: float = 0.01):
        self.cost_limit = cost_limit

    def compute_step_cost(
        self,
        step_metrics: StepMetrics,
        diagnostics: Optional[SimulatorDiagnostics] = None,
    ) -> float:
        """
        Computes the step-level critical violation cost.

        Args:
            step_metrics: Evaluated StepMetrics record.
            diagnostics: Optional simulator diagnostics.

        Returns:
            float: Cost in [0.0, 1.0]. Returns 0.0 if no critical packets were offered.
        """
        crit_offered = 0
        crit_dropped = 0

        # Primary source: step_metrics packet counts
        if step_metrics.offered_packets and step_metrics.dropped_packets:
            for s in CRITICAL_SLICES:
                crit_offered += step_metrics.offered_packets.get(s, 0)
                crit_dropped += step_metrics.dropped_packets.get(s, 0)
        elif diagnostics and diagnostics.extra_info and "slice_diagnostics" in diagnostics.extra_info:
            diags = diagnostics.extra_info["slice_diagnostics"]
            for s in CRITICAL_SLICES:
                s_diag = diags.get(s.value, {})
                crit_offered += s_diag.get("offered_packets", 0)
                crit_dropped += s_diag.get("dropped_packets", 0)

        if crit_offered == 0:
            return 0.0

        cost = float(crit_dropped) / float(crit_offered)
        return float(min(1.0, max(0.0, cost)))
