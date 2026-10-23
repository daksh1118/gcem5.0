"""
SLA Guardian - Action & Safety Data Contracts
Defines ProposedAction, ExecutedAction, and SafetyResult data contracts.
Distinguishes unvalidated policy proposals from verified execution commands.
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
from .config import SliceId, CANONICAL_SLICE_IDS


class SafetyValidationStatus(str, Enum):
    """Result status of the safety intervention pipeline."""
    VALID = "VALID"
    INTERVENED_CLAMPED = "INTERVENED_CLAMPED"
    INTERVENED_FALLBACK = "INTERVENED_FALLBACK"
    REJECTED = "REJECTED"


class ProposedAction(BaseModel):
    """
    Unvalidated resource allocation proposed by a policy (RL agent, heuristic, or optimizer).
    
    Resource Units:
    - radio_allocations: Abstract capacity units / PRBs per slice.
    - compute_allocations: Abstract compute units / CPU cores per slice.
    - priorities: Scheduling priority level per slice, following 3GPP 5QI conventions
      where 1 is highest priority (urgent preemption) and larger integers indicate lower priority.
    """
    radio_allocations: Dict[SliceId, float] = Field(
        ...,
        description="Proposed radio bandwidth per slice (>= 0.0)."
    )
    compute_allocations: Dict[SliceId, float] = Field(
        ...,
        description="Proposed edge compute capacity per slice (>= 0.0)."
    )
    priorities: Dict[SliceId, int] = Field(
        ...,
        description="Proposed scheduling priority per slice (1 = highest priority, 2, 3 = lower)."
    )
    policy_id: Optional[str] = Field(
        default=None,
        description="Identifier of the policy that generated this proposal."
    )
    metadata: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional diagnostic metadata from policy inference."
    )

    @field_validator("radio_allocations", "compute_allocations")
    @classmethod
    def validate_canonical_slices_and_non_negative(cls, v: Dict[SliceId, float]) -> Dict[SliceId, float]:
        keys = set(v.keys())
        expected = set(CANONICAL_SLICE_IDS)
        if keys != expected:
            missing = expected - keys
            extra = keys - expected
            errs = []
            if missing:
                errs.append(f"Missing canonical slice keys: {[m.value for m in missing]}")
            if extra:
                errs.append(f"Unexpected slice keys: {[e for e in extra]}")
            raise ValueError("; ".join(errs))

        for sid, val in v.items():
            if val < 0.0:
                raise ValueError(f"Allocation for slice '{sid.value}' must be non-negative, got {val}")
        return v

    @field_validator("priorities")
    @classmethod
    def validate_priorities(cls, v: Dict[SliceId, int]) -> Dict[SliceId, int]:
        keys = set(v.keys())
        expected = set(CANONICAL_SLICE_IDS)
        if keys != expected:
            raise ValueError(f"Priorities must contain exactly canonical slices: {[c.value for c in CANONICAL_SLICE_IDS]}")
        for sid, prio in v.items():
            if prio < 1:
                raise ValueError(f"Priority for slice '{sid.value}' must be >= 1 (1 = highest priority), got {prio}")
        return v


class ExecutedAction(BaseModel):
    """
    Verified, safe allocation command delivered to the network simulator.
    May be identical to ProposedAction (if VALID) or altered by the Safety Shield.
    """
    radio_allocations: Dict[SliceId, float] = Field(
        ...,
        description="Verified radio bandwidth per slice (>= 0.0)."
    )
    compute_allocations: Dict[SliceId, float] = Field(
        ...,
        description="Verified compute capacity per slice (>= 0.0)."
    )
    priorities: Dict[SliceId, int] = Field(
        ...,
        description="Verified scheduling priority per slice."
    )
    is_modified_by_safety: bool = Field(
        default=False,
        description="True if Safety Shield altered the original proposed allocation."
    )
    proposal_reference: Optional[str] = Field(
        default=None,
        description="Reference or hash linking to the original proposed action."
    )

    @field_validator("radio_allocations", "compute_allocations")
    @classmethod
    def validate_canonical_slices_and_non_negative(cls, v: Dict[SliceId, float]) -> Dict[SliceId, float]:
        keys = set(v.keys())
        expected = set(CANONICAL_SLICE_IDS)
        if keys != expected:
            raise ValueError(f"ExecutedAction allocations must contain exactly canonical slices.")
        for sid, val in v.items():
            if val < 0.0:
                raise ValueError(f"Executed allocation for slice '{sid.value}' must be non-negative, got {val}")
        return v

    @field_validator("priorities")
    @classmethod
    def validate_priorities(cls, v: Dict[SliceId, int]) -> Dict[SliceId, int]:
        keys = set(v.keys())
        expected = set(CANONICAL_SLICE_IDS)
        if keys != expected:
            raise ValueError(f"ExecutedAction priorities must contain exactly canonical slices.")
        for sid, prio in v.items():
            if prio < 1:
                raise ValueError(f"Priority for slice '{sid.value}' must be >= 1, got {prio}")
        return v


class SafetyResult(BaseModel):
    """
    Data contract encapsulating the outcome of Safety Shield validation.
    Maintains transparency by pairing the proposed action with the executed action.
    """
    proposed_action: ProposedAction = Field(
        ...,
        description="The raw unvalidated action proposed by the policy."
    )
    executed_action: Optional[ExecutedAction] = Field(
        default=None,
        description="The final action approved or adjusted for simulation execution. None if REJECTED."
    )
    intervention_occurred: bool = Field(
        ...,
        description="True if the Safety Shield overrode or modified any component of the proposal."
    )
    validation_status: SafetyValidationStatus = Field(
        ...,
        description="Categorical status of safety validation."
    )
    intervention_reasons: List[str] = Field(
        default_factory=list,
        description="Human-readable audit log of violations triggered (e.g. 'URLLC minimum PRB breached')."
    )
    resource_budget_verified: bool = Field(
        default=True,
        description="Verification that sum of allocations does not exceed total network capacity."
    )
    radio_budget_verified: bool = Field(
        default=True,
        description="Verification that radio allocation does not exceed total radio capacity."
    )
    compute_budget_verified: bool = Field(
        default=True,
        description="Verification that compute allocation does not exceed total compute capacity."
    )
    reservation_verified: bool = Field(
        default=True,
        description="Verification that minimum reservations are respected."
    )
    explanation: Optional[str] = Field(
        default=None,
        description="Concise human-readable explanation of safety validation outcome."
    )
    step: Optional[int] = Field(
        default=None,
        ge=0,
        description="Simulation step index where this validation took place."
    )

    @property
    def is_accepted(self) -> bool:
        """True if the action was approved or corrected for execution."""
        return self.validation_status != SafetyValidationStatus.REJECTED and self.executed_action is not None

    @property
    def reasons(self) -> List[str]:
        """Convenience alias for intervention_reasons."""
        return self.intervention_reasons
