"""
SLA Guardian - RL Action Mapping Adapter
Decodes 6 continuous policy logits into a valid ProposedAction schema.
Inputs:
- 3 radio logits: [eMBB, URLLC, mURLLC]
- 3 compute logits: [eMBB, URLLC, mURLLC]
Mapping:
- Numerically stable softmax generates fractional shares independently for radio and compute.
- Configured minimum reservations are guaranteed first; remaining capacity is distributed
  proportionally to the softmax shares.
- Scheduling priorities are derived deterministically based on slice urgency.
- Returns an immutable ProposedAction compliant with Phase 1-4 contracts.
"""

from typing import Dict, Sequence, Union, Optional
import numpy as np

from ..schemas.config import RunConfig, SliceId, CANONICAL_SLICE_IDS
from ..schemas.actions import ProposedAction


ACTION_DIM: int = 6  # 3 radio logits + 3 compute logits


def stable_softmax(logits: Union[np.ndarray, Sequence[float]]) -> np.ndarray:
    """Computes numerically stable softmax over a 1D sequence."""
    arr = np.asarray(logits, dtype=np.float64)
    if not np.all(np.isfinite(arr)):
        raise ValueError("Softmax input contains non-finite values (NaN or Inf).")
    shifted = arr - np.max(arr)
    exp_vals = np.exp(shifted)
    sum_exp = np.sum(exp_vals)
    if sum_exp <= 0.0 or not np.isfinite(sum_exp):
        return np.full_like(arr, 1.0 / len(arr))
    return exp_vals / sum_exp


class ActionMappingAdapter:
    """
    Decodes 6 continuous RL logits into a strictly structured ProposedAction.
    """

    def __init__(self, policy_id: str = "constrained_ppo"):
        self.policy_id = policy_id

    def decode_action(
        self,
        action_logits: Union[np.ndarray, Sequence[float]],
        config: RunConfig,
    ) -> ProposedAction:
        """
        Decodes a 6-element action vector into a ProposedAction.

        Args:
            action_logits: Array-like containing exactly 6 finite floats.
            config: Active RunConfig with capacity limits and reservations.

        Returns:
            ProposedAction: Formatted proposal ready for Safety Shield verification.
        """
        arr = np.asarray(action_logits, dtype=np.float64)
        if arr.shape != (6,):
            raise ValueError(f"Action vector must have shape (6,), got {arr.shape}.")

        if not np.all(np.isfinite(arr)):
            raise ValueError("Action vector contains non-finite values (NaN or Inf).")

        radio_logits = arr[:3]
        compute_logits = arr[3:]

        radio_shares = stable_softmax(radio_logits)
        compute_shares = stable_softmax(compute_logits)

        # Map to capacities with reservations
        radio_allocations: Dict[SliceId, float] = {}
        compute_allocations: Dict[SliceId, float] = {}

        # 1. Radio budget distribution
        r_total = float(config.total_radio_capacity)
        r_reservations = {s: 0.0 for s in CANONICAL_SLICE_IDS}
        if config.minimum_reservations:
            for s, res in config.minimum_reservations.items():
                if s in r_reservations:
                    r_reservations[s] = float(res.min_radio_capacity)

        sum_r_res = sum(r_reservations.values())
        r_free = max(0.0, r_total - sum_r_res)

        for idx, s in enumerate(CANONICAL_SLICE_IDS):
            allocated = r_reservations[s] + r_free * float(radio_shares[idx])
            radio_allocations[s] = round(allocated, 3)

        # 2. Compute budget distribution
        c_total = float(config.total_compute_capacity)
        c_reservations = {s: 0.0 for s in CANONICAL_SLICE_IDS}
        if config.minimum_reservations:
            for s, res in config.minimum_reservations.items():
                if s in c_reservations:
                    c_reservations[s] = float(res.min_compute_capacity)

        sum_c_res = sum(c_reservations.values())
        c_free = max(0.0, c_total - sum_c_res)

        for idx, s in enumerate(CANONICAL_SLICE_IDS):
            allocated = c_reservations[s] + c_free * float(compute_shares[idx])
            compute_allocations[s] = round(allocated, 3)

        # 3. Deterministic scheduling priorities
        # URLLC receives highest strict priority (10), mURLLC intermediate (5), eMBB standard (1)
        priorities: Dict[SliceId, int] = {
            SliceId.URLLC: 10,
            SliceId.MURLLC: 5,
            SliceId.EMBB: 1,
        }

        return ProposedAction(
            radio_allocations=radio_allocations,
            compute_allocations=compute_allocations,
            priorities=priorities,
            policy_id=self.policy_id,
        )
