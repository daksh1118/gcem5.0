"""
SLA Guardian - Safety Shield Controller
Enforces deterministic hard resource limits, reservation guarantees, and auditable action execution.
Sits between policy proposals and the simulator execution stage.
"""

from typing import Dict, List, Optional, Tuple, Any
import math

from ..schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig
from ..schemas.state import NetworkState
from ..schemas.actions import (
    ProposedAction,
    ExecutedAction,
    SafetyValidationStatus,
    SafetyResult,
)


class SafetyShield:
    """
    Deterministic Safety Controller for 5G Resource Allocation.
    
    Guarantees:
    1. Budget Invariant: sum(radio) <= total_radio_capacity and sum(compute) <= total_compute_capacity.
    2. Non-Negativity: All allocations are strictly >= 0.0 and finite.
    3. Isolation Invariant: Configured minimum slice reservations are preserved whenever feasible.
    4. Determinism: Identical inputs produce identical executed actions and audit reasons.
    5. Proposal Immutability: The input ProposedAction is never modified in place.
    """

    def __init__(self, default_priorities: Optional[Dict[SliceId, int]] = None):
        self.default_priorities = default_priorities or {
            SliceId.URLLC: 1,
            SliceId.MURLLC: 2,
            SliceId.EMBB: 3,
        }

    def validate(
        self,
        proposed_action: ProposedAction,
        network_state: NetworkState,
        config: Optional[RunConfig] = None,
    ) -> SafetyResult:
        """
        Validates and, if necessary, corrects an unvalidated policy proposal.
        
        Args:
            proposed_action: Raw proposal from RL, heuristic, or static policy.
            network_state: Current observation of the network.
            config: Active RunConfig with capacity limits and reservations.
            
        Returns:
            SafetyResult: Encapsulating original proposal, executed action (or None),
            intervention flags, audit log reasons, and validation status.
        """
        step = network_state.step
        reasons: List[str] = []
        tot_radio = config.total_radio_capacity if config else network_state.total_radio_capacity
        tot_compute = config.total_compute_capacity if config else network_state.total_compute_capacity

        # 1. Inspect Numerical Integrity of Proposal
        for name, alloc_dict in [("radio", proposed_action.radio_allocations), ("compute", proposed_action.compute_allocations)]:
            for s in CANONICAL_SLICE_IDS:
                if s not in alloc_dict:
                    return self._build_rejection(
                        proposed_action, step,
                        f"Missing allocation for slice '{s.value}' in {name} allocations."
                    )
                val = alloc_dict[s]
                if not math.isfinite(val):
                    return self._build_rejection(
                        proposed_action, step,
                        f"Non-finite value ({val}) in {name} allocation for slice '{s.value}'."
                    )

        # 2. Check Feasibility of Configured Reservations
        min_radio: Dict[SliceId, float] = {s: 0.0 for s in CANONICAL_SLICE_IDS}
        min_compute: Dict[SliceId, float] = {s: 0.0 for s in CANONICAL_SLICE_IDS}

        if config and config.minimum_reservations:
            for s, res in config.minimum_reservations.items():
                min_radio[s] = res.min_radio_capacity
                min_compute[s] = res.min_compute_capacity

        tot_min_r = sum(min_radio.values())
        if tot_min_r > tot_radio + 1e-4:
            return self._build_rejection(
                proposed_action, step,
                f"Infeasible configuration: minimum radio reservations ({tot_min_r:.2f}) exceed capacity ({tot_radio:.2f})."
            )

        tot_min_c = sum(min_compute.values())
        if tot_min_c > tot_compute + 1e-4:
            return self._build_rejection(
                proposed_action, step,
                f"Infeasible configuration: minimum compute reservations ({tot_min_c:.2f}) exceed capacity ({tot_compute:.2f})."
            )

        # 3. Independent Projection for Radio and Compute
        radio_corrected, r_modified, r_reasons = self._project_resource(
            proposed=proposed_action.radio_allocations,
            min_reservations=min_radio,
            total_capacity=tot_radio,
            resource_name="radio",
        )
        reasons.extend(r_reasons)

        compute_corrected, c_modified, c_reasons = self._project_resource(
            proposed=proposed_action.compute_allocations,
            min_reservations=min_compute,
            total_capacity=tot_compute,
            resource_name="compute",
        )
        reasons.extend(c_reasons)

        # 4. Validate Scheduling Priorities
        prio_corrected, p_modified, p_reasons = self._validate_priorities(proposed_action.priorities)
        reasons.extend(p_reasons)

        # 5. Determine Intervention Status
        intervention_occurred = r_modified or c_modified or p_modified
        if intervention_occurred:
            status = SafetyValidationStatus.INTERVENED_CLAMPED
            explanation = f"Safety Shield intervened on step {step}: corrected {len(reasons)} resource constraint violation(s)."
        else:
            status = SafetyValidationStatus.VALID
            explanation = f"Proposal verified conforming to all hard resource budgets and reservations on step {step}."

        executed_action = ExecutedAction(
            radio_allocations=radio_corrected,
            compute_allocations=compute_corrected,
            priorities=prio_corrected,
            is_modified_by_safety=intervention_occurred,
            proposal_reference=f"prop_step_{step}",
        )

        return SafetyResult(
            proposed_action=proposed_action,
            executed_action=executed_action,
            intervention_occurred=intervention_occurred,
            validation_status=status,
            intervention_reasons=reasons,
            resource_budget_verified=True,
            radio_budget_verified=True,
            compute_budget_verified=True,
            reservation_verified=True,
            explanation=explanation,
            step=step,
        )

    def _project_resource(
        self,
        proposed: Dict[SliceId, float],
        min_reservations: Dict[SliceId, float],
        total_capacity: float,
        resource_name: str,
    ) -> Tuple[Dict[SliceId, float], bool, List[str]]:
        """
        Applies reservation-aware proportional projection to a single resource dimension.
        """
        modified = False
        reasons: List[str] = []
        allocated: Dict[SliceId, float] = {}

        # Step A: Enforce non-negativity and reservation floor
        for s in CANONICAL_SLICE_IDS:
            p_val = proposed[s]
            res_val = min_reservations[s]

            if p_val < 0.0:
                modified = True
                reasons.append(f"Negative {resource_name} allocation for {s.value} ({p_val:.2f}) clamped to 0.0.")
                p_val = 0.0

            if p_val < res_val:
                modified = True
                reasons.append(
                    f"Restored {s.value} {resource_name} allocation from {p_val:.2f} to minimum reservation {res_val:.2f}."
                )
                allocated[s] = res_val
            else:
                allocated[s] = p_val

        # Step B: Check capacity budget
        tot_allocated = sum(allocated.values())
        EPS = 1e-4

        if tot_allocated <= total_capacity + EPS:
            # Within budget
            return {s: round(allocated[s], 3) for s in CANONICAL_SLICE_IDS}, modified, reasons

        # Budget exceeded: apply proportional projection on surplus above reservations
        modified = True
        tot_min = sum(min_reservations.values())
        rem_capacity = max(0.0, total_capacity - tot_min)

        surpluses = {s: max(0.0, allocated[s] - min_reservations[s]) for s in CANONICAL_SLICE_IDS}
        tot_surplus = sum(surpluses.values())

        final_alloc: Dict[SliceId, float] = {}
        for s in CANONICAL_SLICE_IDS:
            if tot_surplus > 0.0:
                share = surpluses[s] / tot_surplus
                final_alloc[s] = min_reservations[s] + rem_capacity * share
            else:
                final_alloc[s] = min_reservations[s]

        # Round to 3 decimal places
        final_alloc = {s: round(final_alloc[s], 3) for s in CANONICAL_SLICE_IDS}

        # Resolve minor floating point difference on largest slice
        diff = total_capacity - sum(final_alloc.values())
        max_s = max(final_alloc, key=final_alloc.get)
        final_alloc[max_s] = round(final_alloc[max_s] + diff, 3)

        reasons.append(
            f"Total {resource_name} allocation ({tot_allocated:.2f}) exceeded capacity ({total_capacity:.2f}); "
            f"projected surplus proportionally above minimum reservations."
        )

        return final_alloc, modified, reasons

    def _validate_priorities(
        self,
        priorities: Dict[SliceId, int],
    ) -> Tuple[Dict[SliceId, int], bool, List[str]]:
        """Ensures priority values are positive integers >= 1 and canonical."""
        modified = False
        reasons: List[str] = []
        validated: Dict[SliceId, int] = {}

        for s in CANONICAL_SLICE_IDS:
            prio = priorities.get(s, self.default_priorities[s])
            if prio < 1 or not isinstance(prio, int):
                modified = True
                default_prio = self.default_priorities[s]
                reasons.append(f"Invalid priority for {s.value} ({prio}) corrected to {default_prio}.")
                validated[s] = default_prio
            else:
                validated[s] = prio

        return validated, modified, reasons

    def _build_rejection(
        self,
        proposed_action: ProposedAction,
        step: int,
        reason: str,
    ) -> SafetyResult:
        """Constructs an explicit REJECTED SafetyResult without an ExecutedAction."""
        return SafetyResult(
            proposed_action=proposed_action,
            executed_action=None,
            intervention_occurred=True,
            validation_status=SafetyValidationStatus.REJECTED,
            intervention_reasons=[reason],
            resource_budget_verified=False,
            radio_budget_verified=False,
            compute_budget_verified=False,
            reservation_verified=False,
            explanation=f"Safety Shield REJECTED proposal on step {step}: {reason}",
            step=step,
        )
