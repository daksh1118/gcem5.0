"""
SLA Guardian - Configuration Schema and Slice Identifiers
Defines canonical slice IDs, SLA threshold requirements, and run configuration contracts.
"""

from enum import Enum
from typing import Dict, Optional, Tuple
from pydantic import BaseModel, Field, model_validator, field_validator, ConfigDict


class SliceId(str, Enum):
    """
    Canonical 5G Network Slice Identifiers.
    
    Note on mURLLC:
    The third workload profile is canonically designated as 'mURLLC' per problem requirements.
    It represents massive/mixed ultra-reliable low-latency workloads. It is kept distinct
    from standard 3GPP mMTC (Massive Machine Type Communication) while allowing its
    underlying SLA and resource parameters to be configured without structural changes.
    """
    EMBB = "eMBB"
    URLLC = "URLLC"
    MURLLC = "mURLLC"


CANONICAL_SLICE_IDS: Tuple[SliceId, ...] = (
    SliceId.EMBB,
    SliceId.URLLC,
    SliceId.MURLLC,
)

SLICE_DISPLAY_LABELS: Dict[SliceId, str] = {
    SliceId.EMBB: "Enhanced Mobile Broadband (eMBB)",
    SliceId.URLLC: "Ultra-Reliable Low-Latency Communication (URLLC)",
    SliceId.MURLLC: "Massive / Mixed Ultra-Reliable Low-Latency Communication (mURLLC)",
}


class SliceSlaConfig(BaseModel):
    """Service Level Agreement targets per slice."""
    max_latency_ms: float = Field(
        ...,
        gt=0.0,
        description="Maximum acceptable p95 end-to-end latency in milliseconds (strict upper bound)."
    )
    min_throughput_mbps: float = Field(
        ...,
        ge=0.0,
        description="Minimum acceptable delivered throughput in Megabits per second."
    )
    min_packet_delivery_ratio: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Minimum acceptable packet delivery ratio (between 0.0 and 1.0, e.g. 0.9999 for URLLC)."
    )
    max_jitter_ms: Optional[float] = Field(
        None,
        gt=0.0,
        description="Optional maximum acceptable packet jitter in milliseconds."
    )


class SliceReservationConfig(BaseModel):
    """Guaranteed minimum baseline reservation for a slice to ensure isolation."""
    min_radio_capacity: float = Field(
        default=0.0,
        ge=0.0,
        description="Minimum reserved radio capacity (in abstract capacity units / PRBs)."
    )
    min_compute_capacity: float = Field(
        default=0.0,
        ge=0.0,
        description="Minimum reserved edge compute capacity (in abstract compute units / CPU cores)."
    )


class RunConfig(BaseModel):
    """
    Complete configuration specification for an SLA Guardian simulation run.
    Validates scenario parameters, total capacities, and per-slice SLA contracts.
    """
    model_config = ConfigDict(extra="allow")

    scenario_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the simulation scenario."
    )
    seed: int = Field(
        default=42,
        ge=0,
        description="Pseudorandom generator seed for deterministic simulation and reproducibility."
    )
    max_steps: int = Field(
        default=1000,
        gt=0,
        description="Maximum number of discrete simulation steps in an episode."
    )
    step_duration_ms: float = Field(
        default=10.0,
        gt=0.0,
        description="Discrete time duration of each simulation step in milliseconds (e.g. 10 ms)."
    )
    total_radio_capacity: float = Field(
        ...,
        gt=0.0,
        description="Total radio bandwidth capacity available for scheduling across all slices."
    )
    total_compute_capacity: float = Field(
        ...,
        gt=0.0,
        description="Total edge compute capacity available across all slice workloads."
    )
    sla_thresholds: Dict[SliceId, SliceSlaConfig] = Field(
        ...,
        description="SLA requirements mapped to each of the three canonical slice classes."
    )
    minimum_reservations: Optional[Dict[SliceId, SliceReservationConfig]] = Field(
        default=None,
        description="Optional minimum baseline reservations per slice."
    )
    policy_id: str = Field(
        default="heuristic_proportional",
        min_length=1,
        description="Identifier of the resource allocation policy to execute."
    )
    traffic_profile: str = Field(
        default="normal",
        min_length=1,
        description="Traffic generation profile identifier (e.g. 'normal', 'urllc_burst', 'mixed_stress')."
    )

    @field_validator("sla_thresholds")
    @classmethod
    def validate_canonical_slices_in_sla(cls, v: Dict[SliceId, SliceSlaConfig]) -> Dict[SliceId, SliceSlaConfig]:
        keys = set(v.keys())
        expected = set(CANONICAL_SLICE_IDS)
        if keys != expected:
            missing = expected - keys
            extra = keys - expected
            err_msg = []
            if missing:
                err_msg.append(f"Missing required canonical slice SLA configs: {[m.value for m in missing]}")
            if extra:
                err_msg.append(f"Unexpected slice configs: {[e for e in extra]}")
            raise ValueError("; ".join(err_msg))
        return v

    @model_validator(mode="after")
    def validate_capacity_reservations(self) -> "RunConfig":
        if self.minimum_reservations:
            # Check for unknown slice keys in reservations
            res_keys = set(self.minimum_reservations.keys())
            expected = set(CANONICAL_SLICE_IDS)
            if not res_keys.issubset(expected):
                unexpected = res_keys - expected
                raise ValueError(f"Reservations contain non-canonical slice IDs: {[u for u in unexpected]}")

            tot_min_radio = sum(r.min_radio_capacity for r in self.minimum_reservations.values())
            if tot_min_radio > self.total_radio_capacity:
                raise ValueError(
                    f"Sum of minimum radio reservations ({tot_min_radio}) "
                    f"exceeds total radio capacity ({self.total_radio_capacity})."
                )

            tot_min_compute = sum(r.min_compute_capacity for r in self.minimum_reservations.values())
            if tot_min_compute > self.total_compute_capacity:
                raise ValueError(
                    f"Sum of minimum compute reservations ({tot_min_compute}) "
                    f"exceeds total compute capacity ({self.total_compute_capacity})."
                )
        return self
