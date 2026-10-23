"""
SLA Guardian - Static Resource Slicing Policy
Implements a fixed, invariant resource partitioning baseline respecting total capacities
and configured minimum slice reservations.
"""

from typing import Dict, Optional
from ..schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig
from ..schemas.state import NetworkState
from ..schemas.actions import ProposedAction
from ..interfaces.policy import PolicyInterface


class StaticSlicingPolicy(PolicyInterface):
    """
    Static resource allocation baseline.
    Partitions total radio and compute capacities according to fixed, pre-configured shares.
    Produces identical allocations across all steps regardless of state changes.
    """

    def __init__(
        self,
        config: Optional[RunConfig] = None,
        radio_shares: Optional[Dict[SliceId, float]] = None,
        compute_shares: Optional[Dict[SliceId, float]] = None,
        priorities: Optional[Dict[SliceId, int]] = None,
    ):
        self.config = config
        self._policy_id = "static_slicing_baseline"
        self._policy_version = "1.0.0"

        # Default normalized shares summing to 1.0
        self.radio_shares = radio_shares or {
            SliceId.EMBB: 0.45,
            SliceId.URLLC: 0.25,
            SliceId.MURLLC: 0.30,
        }
        self.compute_shares = compute_shares or {
            SliceId.EMBB: 0.45,
            SliceId.URLLC: 0.25,
            SliceId.MURLLC: 0.30,
        }
        self.priorities = priorities or {
            SliceId.EMBB: 3,
            SliceId.URLLC: 1,
            SliceId.MURLLC: 2,
        }

        self._validate_shares(self.radio_shares, "radio")
        self._validate_shares(self.compute_shares, "compute")

    @property
    def policy_id(self) -> str:
        return self._policy_id

    @property
    def policy_version(self) -> str:
        return self._policy_version

    def _validate_shares(self, shares: Dict[SliceId, float], name: str):
        keys = set(shares.keys())
        expected = set(CANONICAL_SLICE_IDS)
        if keys != expected:
            raise ValueError(f"Static {name} shares must contain exactly canonical slices.")
        for s, val in shares.items():
            if val < 0.0:
                raise ValueError(f"Share for slice '{s.value}' must be non-negative, got {val}")
        tot = sum(shares.values())
        if abs(tot - 1.0) > 1e-4:
            raise ValueError(f"Static {name} shares must sum to 1.0 (got {tot:.4f})")

    def predict(self, observation: NetworkState) -> ProposedAction:
        """
        Calculates fixed allocation based on observation capacity and pre-configured shares.
        Guarantees minimum slice reservations if specified in configuration.
        """
        tot_radio = observation.total_radio_capacity
        tot_compute = observation.total_compute_capacity

        min_radio = {s: 0.0 for s in CANONICAL_SLICE_IDS}
        min_compute = {s: 0.0 for s in CANONICAL_SLICE_IDS}

        if self.config and self.config.minimum_reservations:
            for s, res in self.config.minimum_reservations.items():
                min_radio[s] = res.min_radio_capacity
                min_compute[s] = res.min_compute_capacity

        tot_min_r = sum(min_radio.values())
        if tot_min_r > tot_radio + 1e-4:
            raise ValueError(
                f"Configured minimum radio reservations ({tot_min_r:.2f}) exceed total radio capacity ({tot_radio:.2f})"
            )

        tot_min_c = sum(min_compute.values())
        if tot_min_c > tot_compute + 1e-4:
            raise ValueError(
                f"Configured minimum compute reservations ({tot_min_c:.2f}) exceed total compute capacity ({tot_compute:.2f})"
            )

        rem_radio = max(0.0, tot_radio - tot_min_r)
        rem_compute = max(0.0, tot_compute - tot_min_c)

        radio_allocations: Dict[SliceId, float] = {}
        compute_allocations: Dict[SliceId, float] = {}

        for s in CANONICAL_SLICE_IDS:
            r_alloc = min_radio[s] + rem_radio * self.radio_shares[s]
            c_alloc = min_compute[s] + rem_compute * self.compute_shares[s]

            radio_allocations[s] = round(r_alloc, 3)
            compute_allocations[s] = round(c_alloc, 3)

        # Fix minor floating point rounding differences on the largest slice
        r_diff = tot_radio - sum(radio_allocations.values())
        max_r_slice = max(radio_allocations, key=radio_allocations.get)
        radio_allocations[max_r_slice] = round(radio_allocations[max_r_slice] + r_diff, 3)

        c_diff = tot_compute - sum(compute_allocations.values())
        max_c_slice = max(compute_allocations, key=compute_allocations.get)
        compute_allocations[max_c_slice] = round(compute_allocations[max_c_slice] + c_diff, 3)

        return ProposedAction(
            radio_allocations=radio_allocations,
            compute_allocations=compute_allocations,
            priorities=dict(self.priorities),
            policy_id=self.policy_id,
            metadata={"strategy": "static_fixed_shares"},
        )
