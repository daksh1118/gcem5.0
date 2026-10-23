"""
SLA Guardian - Lagrangian-Constrained Reward Engine
Computes multi-objective constrained reward:
    R_training = R_service(eMBB) - lambda * C_critical(URLLC, mURLLC)

Where:
- R_service(eMBB) = delivered_eMBB_packets / max(1, offered_eMBB_packets + initial_queue_eMBB)
- C_critical = (dropped_URLLC + dropped_mURLLC) / max(1, offered_URLLC + offered_mURLLC)
"""

from typing import Dict, Any, Tuple
import numpy as np

from ..schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig
from ..schemas.metrics import StepMetrics
from ..interfaces.simulator import SimulatorDiagnostics
from .cost import ViolationCostAdapter, CRITICAL_SLICES


class LagrangianRewardEngine:
    """
    Computes transparent, finite, and bounded rewards for Constrained PPO.
    """

    def __init__(self, cost_limit: float = 0.01):
        self.cost_adapter = ViolationCostAdapter(cost_limit=cost_limit)

    def compute_reward(
        self,
        step_metrics: StepMetrics,
        diagnostics: SimulatorDiagnostics,
        lambda_val: float,
        is_rejected: bool = False,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Computes the training reward and diagnostic components.

        Args:
            step_metrics: Evaluated StepMetrics over the macro interval.
            diagnostics: Simulator diagnostics emitted over the interval.
            lambda_val: Current non-negative Lagrangian multiplier.
            is_rejected: True if the Safety Shield rejected the proposed action.

        Returns:
            Tuple of:
            - total_reward (float)
            - reward_info (Dict[str, Any])
        """
        if is_rejected:
            # Bounded failure penalty for rejected actions without advancing simulator
            penalty = -1.0
            info = {
                "service_reward": 0.0,
                "critical_cost": 1.0,
                "lambda_val": float(lambda_val),
                "training_reward": penalty,
                "is_rejected": True,
            }
            return penalty, info

        # 1. Primary service satisfaction (eMBB)
        embb_deliv = step_metrics.delivered_packets.get(SliceId.EMBB, 0)
        embb_offered = step_metrics.offered_packets.get(SliceId.EMBB, 0)
        embb_pending = step_metrics.pending_packets.get(SliceId.EMBB, 0)

        # Eligible demand considers arrivals plus existing backlog
        eligible_demand = max(1, embb_offered + min(embb_pending, 200))
        service_reward = float(np.clip(embb_deliv / eligible_demand, 0.0, 1.0))

        # 2. Critical slice violation cost
        critical_cost = self.cost_adapter.compute_step_cost(step_metrics, diagnostics)

        # 3. Constrained Training Reward: R = Service - lambda * Cost
        multiplier = max(0.0, float(lambda_val))
        training_reward = float(service_reward - multiplier * critical_cost)

        # Guard finiteness
        if not np.isfinite(training_reward):
            training_reward = 0.0

        info = {
            "service_reward": round(service_reward, 4),
            "critical_cost": round(critical_cost, 4),
            "lambda_val": round(multiplier, 4),
            "training_reward": round(training_reward, 4),
            "is_rejected": False,
            "embb_delivered_pkts": embb_deliv,
            "embb_offered_pkts": embb_offered,
            "urllc_delivered_pkts": step_metrics.delivered_packets.get(SliceId.URLLC, 0),
            "urllc_dropped_pkts": step_metrics.dropped_packets.get(SliceId.URLLC, 0),
            "murllc_delivered_pkts": step_metrics.delivered_packets.get(SliceId.MURLLC, 0),
            "murllc_dropped_pkts": step_metrics.dropped_packets.get(SliceId.MURLLC, 0),
        }

        return training_reward, info
