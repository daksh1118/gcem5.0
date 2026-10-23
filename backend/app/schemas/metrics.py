"""
SLA Guardian - Telemetry & Metrics Data Contracts
Defines StepMetrics model capturing empirical measurements, SLA compliance,
utilization ratios, and decoupled RL reward components.
"""

from typing import Dict, Optional
from pydantic import BaseModel, Field, field_validator
from .config import SliceId, CANONICAL_SLICE_IDS


class StepMetrics(BaseModel):
    """
    Empirical measurements and SLA compliance status at a single simulation step.
    
    Design Rule:
    Measured network performance metrics (throughput, latency, delivery ratio, utilization)
    are strictly kept separate from calculated reinforcement learning rewards
    (`reward_components`), ensuring objective benchmarking across non-RL and RL controllers.
    """
    step: int = Field(
        ...,
        ge=0,
        description="Discrete simulation step index."
    )
    sim_time_sec: float = Field(
        ...,
        ge=0.0,
        description="Elapsed simulation time in seconds."
    )
    throughput_mbps: Dict[SliceId, float] = Field(
        ...,
        description="Empirical delivered throughput in Mbps per slice."
    )
    p95_latency_ms: Dict[SliceId, Optional[float]] = Field(
        ...,
        description="Empirical 95th percentile latency in milliseconds per slice. None if no delay samples."
    )
    packet_delivery_ratio: Dict[SliceId, Optional[float]] = Field(
        ...,
        description="Packet delivery ratio (0.0 to 1.0) per slice. None if no finished packets."
    )
    sla_status: Dict[SliceId, bool] = Field(
        ...,
        description="Binary SLA compliance status per slice (True = Compliant, False = SLA Breach or Insufficient Data)."
    )
    sla_breach_count: int = Field(
        default=0,
        ge=0,
        description="Total number of active slice SLA breaches in this step (0, 1, 2, or 3)."
    )
    radio_utilization_ratio: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Total fraction of available radio capacity actively utilized (0.0 to 1.0)."
    )
    compute_utilization_ratio: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Total fraction of available edge compute capacity actively utilized (0.0 to 1.0)."
    )
    allocation_churn: float = Field(
        default=0.0,
        ge=0.0,
        description="L1 norm of resource reallocations between consecutive steps."
    )
    safety_intervention: bool = Field(
        default=False,
        description="Whether a safety intervention occurred in this step."
    )
    reward_components: Optional[Dict[str, float]] = Field(
        default=None,
        description="Decoupled reward terms (e.g. sla_reward, efficiency_reward, churn_penalty) for RL."
    )

    # Detailed packet cohort accounting (optional extensions)
    offered_packets: Optional[Dict[SliceId, int]] = Field(
        default=None,
        description="Total packets generated during this step per slice."
    )
    delivered_packets: Optional[Dict[SliceId, int]] = Field(
        default=None,
        description="Total packets delivered during this step per slice."
    )
    dropped_packets: Optional[Dict[SliceId, int]] = Field(
        default=None,
        description="Total packets dropped during this step per slice."
    )
    pending_packets: Optional[Dict[SliceId, int]] = Field(
        default=None,
        description="Packets currently pending in queues at this step."
    )
    sla_state_details: Optional[Dict[SliceId, str]] = Field(
        default=None,
        description="Detailed SLA state per slice ('PASS', 'BREACH', 'INSUFFICIENT_DATA')."
    )

    @field_validator("throughput_mbps", "p95_latency_ms", "packet_delivery_ratio", "sla_status")
    @classmethod
    def validate_canonical_slice_metrics(cls, v: dict) -> dict:
        keys = set(v.keys())
        expected = set(CANONICAL_SLICE_IDS)
        if keys != expected:
            missing = expected - keys
            extra = keys - expected
            raise ValueError(
                f"Metric dictionary keys must match canonical slices. Missing: {[m.value for m in missing]}, Extra: {[e for e in extra]}"
            )
        return v
