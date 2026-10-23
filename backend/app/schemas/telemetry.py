"""
SLA Guardian - Telemetry & API Request/Response Schemas
Defines structured data contracts for live multi-policy experiment streaming,
control endpoints, and comparative performance summaries.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from .config import SliceId, CANONICAL_SLICE_IDS


class RunStartRequest(BaseModel):
    """Request model for starting a new simulation run."""
    scenario: str = Field(default="normal", description="Traffic scenario identifier.")
    seed: int = Field(default=42, ge=0, description="Random seed for reproducible traffic and channels.")
    max_macro_steps: int = Field(default=100, ge=1, le=1000, description="Total 100 ms macro-control intervals to run.")
    selected_policies: List[str] = Field(
        default_factory=lambda: ["static", "heuristic", "agent"],
        description="Policies to evaluate in this run.",
    )


class SpikeRequest(BaseModel):
    """Request model for runtime demand burst injection."""
    target_slice: str = Field(..., description="Target slice ID: eMBB, URLLC, or mURLLC.")
    multiplier: float = Field(..., gt=0.0, description="Positive burst demand multiplier (e.g., 4.0 for 4x surge).")
    duration_steps: int = Field(..., ge=1, le=500, description="Duration in macro-control steps (100 ms each).")
    start_step: Optional[int] = Field(default=None, description="Optional start macro-step. Defaults to current step.")


class ResetRequest(BaseModel):
    """Request model for resetting active simulation environments."""
    scenario: Optional[str] = Field(default=None, description="Scenario to set upon reset. Defaults to active scenario.")
    seed: Optional[int] = Field(default=None, ge=0, description="Seed to set upon reset. Defaults to active seed.")


class PolicyTelemetry(BaseModel):
    """Telemetry snapshot for one policy at a single macro interval."""
    policy_id: str
    policy_version: str
    radio_allocations: Dict[str, float]
    compute_allocations: Dict[str, float]
    delivered_tput_mbps: Dict[str, float]
    p95_latency_ms: Dict[str, Optional[float]]
    pdr: Dict[str, Optional[float]]
    offered_packets: Dict[str, int]
    delivered_packets: Dict[str, int]
    dropped_packets: Dict[str, int]
    pending_packets: Dict[str, int]
    queue_depths: Dict[str, int]
    critical_violations: int
    sla_status: Dict[str, bool]
    sla_state_details: Dict[str, str]
    shield_status: str  # "PASSED", "CORRECTED", "REJECTED"
    intervention_reasons: List[str]
    # Agent-specific telemetry
    lagrangian_lambda: Optional[float] = None
    critical_cost: Optional[float] = None
    explanation: Optional[str] = None


class TelemetryEvent(BaseModel):
    """Unified telemetry event broadcast across WebSocket subscribers."""
    run_id: str
    sequence_number: int
    macro_step: int
    sim_time_sec: float
    active_scenario: str
    spike_active: bool
    run_status: str  # "idle", "running", "paused", "completed"
    seed: int
    synchronization_status: str = "perfect_matched_seed"
    policies: Dict[str, PolicyTelemetry]


class SinglePolicySummary(BaseModel):
    """Cumulative performance summary for one policy across a run."""
    policy_id: str
    policy_version: str
    mean_embb_tput_mbps: float
    critical_violations: int
    shield_interventions: int
    sla_breach_step_ratio: float
    mean_radio_utilization: float
    mean_compute_utilization: float
    total_churn: float
    per_slice_summary: Dict[str, Dict[str, Any]]
    run_duration_sec: float
    completed_macro_steps: int
    lagrangian_lambda: Optional[float] = None


class MultiPolicySummary(BaseModel):
    """Overall multi-policy comparative summary for GET /api/summary."""
    run_id: str
    scenario_id: str
    seed: int
    run_status: str
    completed_macro_steps: int
    static: SinglePolicySummary
    heuristic: SinglePolicySummary
    agent: SinglePolicySummary
