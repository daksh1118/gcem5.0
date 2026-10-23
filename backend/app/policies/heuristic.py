"""
SLA Guardian - Adaptive Demand-Aware Heuristic Policy
Dynamically allocates radio and edge-compute resources based on queue backlogs,
offered demand growth, and SLA compliance headroom.
"""

from typing import Dict, Optional
import numpy as np

from ..schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig
from ..schemas.state import NetworkState
from ..schemas.actions import ProposedAction
from ..interfaces.policy import PolicyInterface


class AdaptiveDemandHeuristicPolicy(PolicyInterface):
    """
    Adaptive rule-based heuristic controller.
    Dynamically balances resources across eMBB, URLLC, and mURLLC by evaluating:
    - Current offered traffic demand & instantaneous growth rate.
    - Accumulated queue depth in radio and compute stages.
    - SLA headroom margins (prioritizing slices nearing or experiencing SLA breaches).
    - Hard minimum slice reservations to guarantee isolation.
    """

    def __init__(
        self,
        config: Optional[RunConfig] = None,
        smoothing_factor: float = 0.25,
        criticality_weights: Optional[Dict[SliceId, float]] = None,
    ):
        self.config = config
        self.smoothing_factor = smoothing_factor  # Churn dampener: weight given to previous allocation
        self._policy_id = "adaptive_demand_heuristic"
        self._policy_version = "1.1.0"

        # Baseline slice criticality weighting (URLLC has highest intrinsic urgency)
        self.criticality_weights = criticality_weights or {
            SliceId.EMBB: 1.0,
            SliceId.URLLC: 2.2,
            SliceId.MURLLC: 1.4,
        }

        self.last_radio_allocation: Optional[Dict[SliceId, float]] = None
        self.last_compute_allocation: Optional[Dict[SliceId, float]] = None

    @property
    def policy_id(self) -> str:
        return self._policy_id

    @property
    def policy_version(self) -> str:
        return self._policy_version

    def reset_state(self):
        """Resets temporal smoothing history."""
        self.last_radio_allocation = None
        self.last_compute_allocation = None

    def predict(self, observation: NetworkState) -> ProposedAction:
        """
        Calculates adaptive radio and compute allocations for each slice.
        """
        tot_radio = observation.total_radio_capacity
        tot_compute = observation.total_compute_capacity

        # 1. Establish baseline reservations
        min_radio: Dict[SliceId, float] = {s: 0.0 for s in CANONICAL_SLICE_IDS}
        min_compute: Dict[SliceId, float] = {s: 0.0 for s in CANONICAL_SLICE_IDS}

        if self.config and self.config.minimum_reservations:
            for s, res in self.config.minimum_reservations.items():
                min_radio[s] = res.min_radio_capacity
                min_compute[s] = res.min_compute_capacity

        rem_radio = max(0.0, tot_radio - sum(min_radio.values()))
        rem_compute = max(0.0, tot_compute - sum(min_compute.values()))

        # 2. Compute slice urgency scores
        radio_urgencies: Dict[SliceId, float] = {}
        compute_urgencies: Dict[SliceId, float] = {}

        for s in CANONICAL_SLICE_IDS:
            sstate = observation.slice_states[s]

            # Workload demand weight (with growth rate anticipation)
            growth_mult = 1.0 + max(0.0, sstate.demand_growth_rate)
            demand_weight = max(1.0, sstate.offered_demand_mbps * growth_mult)

            # Queue backlog factor
            queue_mult = 1.0 + (sstate.queue_depth_packets / 25.0)

            # SLA headroom factor (severe penalty if headroom is negative or near zero)
            headroom = sstate.sla_headroom
            if headroom < 0.0:
                sla_urgency = 3.0  # Active breach: maximum urgency
            elif headroom < 0.20:
                sla_urgency = 1.8  # Critical danger zone
            else:
                sla_urgency = 1.0

            crit = self.criticality_weights.get(s, 1.0)
            urgency = crit * demand_weight * queue_mult * sla_urgency

            radio_urgencies[s] = urgency
            compute_urgencies[s] = urgency

        # 3. Distribute remaining capacities proportionally to urgency
        tot_r_urg = sum(radio_urgencies.values())
        tot_c_urg = sum(compute_urgencies.values())

        target_radio: Dict[SliceId, float] = {}
        target_compute: Dict[SliceId, float] = {}

        for s in CANONICAL_SLICE_IDS:
            r_share = (radio_urgencies[s] / tot_r_urg) if tot_r_urg > 0 else (1.0 / len(CANONICAL_SLICE_IDS))
            c_share = (compute_urgencies[s] / tot_c_urg) if tot_c_urg > 0 else (1.0 / len(CANONICAL_SLICE_IDS))

            target_radio[s] = min_radio[s] + rem_radio * r_share
            target_compute[s] = min_compute[s] + rem_compute * c_share

        # 4. Anti-churn temporal smoothing
        final_radio: Dict[SliceId, float] = {}
        final_compute: Dict[SliceId, float] = {}

        for s in CANONICAL_SLICE_IDS:
            if self.last_radio_allocation is not None:
                smoothed_r = (1.0 - self.smoothing_factor) * target_radio[s] + self.smoothing_factor * self.last_radio_allocation[s]
                smoothed_c = (1.0 - self.smoothing_factor) * target_compute[s] + self.smoothing_factor * self.last_compute_allocation[s]
            else:
                smoothed_r = target_radio[s]
                smoothed_c = target_compute[s]

            final_radio[s] = max(min_radio[s], smoothed_r)
            final_compute[s] = max(min_compute[s], smoothed_c)

        # Normalize to ensure sum strictly matches total capacity
        tot_r_actual = sum(final_radio.values())
        if tot_r_actual > 0:
            final_radio = {s: round((final_radio[s] / tot_r_actual) * tot_radio, 3) for s in CANONICAL_SLICE_IDS}

        tot_c_actual = sum(final_compute.values())
        if tot_c_actual > 0:
            final_compute = {s: round((final_compute[s] / tot_c_actual) * tot_compute, 3) for s in CANONICAL_SLICE_IDS}

        # Fix minor floating point rounding difference on the largest slice
        r_diff = tot_radio - sum(final_radio.values())
        max_r_slice = max(final_radio, key=final_radio.get)
        final_radio[max_r_slice] = round(final_radio[max_r_slice] + r_diff, 3)

        c_diff = tot_compute - sum(final_compute.values())
        max_c_slice = max(final_compute, key=final_compute.get)
        final_compute[max_c_slice] = round(final_compute[max_c_slice] + c_diff, 3)

        self.last_radio_allocation = final_radio
        self.last_compute_allocation = final_compute

        # 5. Determine scheduling priority based on urgency
        sorted_by_urgency = sorted(CANONICAL_SLICE_IDS, key=lambda s: radio_urgencies[s], reverse=True)
        priorities: Dict[SliceId, int] = {}
        for idx, s in enumerate(sorted_by_urgency):
            priorities[s] = idx + 1  # 1 = highest priority

        return ProposedAction(
            radio_allocations=final_radio,
            compute_allocations=final_compute,
            priorities=priorities,
            policy_id=self.policy_id,
            metadata={"strategy": "adaptive_demand_queue_urgency"},
        )
