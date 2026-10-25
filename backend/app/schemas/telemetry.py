"""
SLA Guardian - Telemetry & API Request/Response Schemas
Defines structured data contracts for live multi-policy experiment streaming,
control endpoints, and comparative performance summaries.
"""

from typing import Dict, List, Optional, Any, Tuple
from pydantic import BaseModel, Field
from .config import SliceId, CANONICAL_SLICE_IDS


class RunStartRequest(BaseModel):
    """Request model for starting a new simulation run."""
    scenario: str = Field(default="normal", description="Traffic scenario identifier or trace mode.")
    seed: int = Field(default=42, ge=0, description="Random seed for reproducible traffic and channels.")
    max_macro_steps: int = Field(default=100, ge=1, le=1000, description="Total 100 ms macro-control intervals to run.")
    selected_policies: List[str] = Field(
        default_factory=lambda: ["static", "heuristic", "agent"],
        description="Policies to evaluate in this run.",
    )
    # Traffic Source configuration
    traffic_source_type: str = Field(
        default="synthetic",
        description="Traffic source mode: 'synthetic', 'trace_replay', or 'live_telemetry'."
    )
    trace_file: Optional[str] = Field(
        default=None,
        description="Trace filename within data/traces/ (e.g. 'sample_5g_multi_slice_trace.csv')."
    )
    telemetry_endpoint: Optional[str] = Field(
        default=None,
        description="Authorized live metrics endpoint URL."
    )
    replay_speed: float = Field(
        default=1.0,
        ge=0.01,
        le=100.0,
        description="Trace replay speed multiplier relative to real time."
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
    traffic_source_type: Optional[str] = Field(default=None, description="Traffic source type to set upon reset.")
    trace_file: Optional[str] = Field(default=None, description="Trace file to set upon reset.")


class TraceValidationRequest(BaseModel):
    """Request model for validating an uploaded or selected trace."""
    file_name: str = Field(..., description="Name of trace file in data/traces/.")
    qos_mapping: Optional[Dict[str, str]] = Field(default=None, description="Optional custom QoS-to-slice overrides.")


class TraceValidationResponse(BaseModel):
    """Validation analysis for a recorded trace."""
    valid: bool
    file_name: str
    total_records: int
    duration_sec: float
    classification_coverage_pct: float
    unclassified_count: int
    slice_distribution: Dict[str, int]
    messages: List[str]
    time_range_sec: Optional[Tuple[float, float]] = None


class TrafficSourceSelectionRequest(BaseModel):
    """Request to change active traffic source globally."""
    source_type: str = Field(..., description="'synthetic', 'trace_replay', or 'live_telemetry'.")
    trace_file: Optional[str] = Field(default=None, description="Trace file if trace_replay.")
    telemetry_endpoint: Optional[str] = Field(default=None, description="Endpoint URL if live_telemetry.")
    replay_speed: float = Field(default=1.0, ge=0.01)


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
    traffic_source: Optional[Dict[str, Any]] = None
    input_measurements: Optional[Dict[str, Any]] = None
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
