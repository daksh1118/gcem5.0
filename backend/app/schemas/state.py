"""
SLA Guardian - State Data Contracts
Defines SliceState and NetworkState models representing granular observation vectors.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from .config import SliceId, CANONICAL_SLICE_IDS


class SliceState(BaseModel):
    """
    Granular observation state for an individual network slice.
    
    Initialization Rules:
    - At simulation step 0 (or before initial packet departure), delivered metrics 
      (`delivered_throughput_mbps`, `p95_latency_ms`, `packet_delivery_ratio`)
      are initialized to None to represent unavailable measurements rather than 
      fabricating false zero-delay or zero-loss performance.
    - `sla_headroom`: Normalized margin between current performance and SLA threshold.
      Positive (> 0.0) indicates compliance buffer (e.g. +0.40 = 40% headroom).
      Zero (0.0) indicates operation exactly at SLA limit.
      Negative (< 0.0) indicates an active SLA breach.
    """
    slice_id: SliceId = Field(
        ...,
        description="Canonical slice identifier (eMBB, URLLC, mURLLC)."
    )
    offered_demand_mbps: float = Field(
        ...,
        ge=0.0,
        description="Current offered traffic arrival rate in Megabits per second (Mbps)."
    )
    demand_growth_rate: float = Field(
        default=0.0,
        description="Instantaneous rate of change of offered demand relative to previous step."
    )
    queue_depth_packets: int = Field(
        default=0,
        ge=0,
        description="Number of packets currently awaiting transmission in the slice buffer."
    )
    delivered_throughput_mbps: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Delivered throughput in Mbps across the observation interval. None at step 0."
    )
    p95_latency_ms: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="95th percentile end-to-end packet delivery latency in milliseconds. None at step 0."
    )
    packet_delivery_ratio: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Ratio of successfully delivered packets to transmitted packets (0.0 to 1.0). None at step 0."
    )
    current_radio_allocation: float = Field(
        default=0.0,
        ge=0.0,
        description="Current radio bandwidth allocated to this slice (in abstract capacity units / PRBs)."
    )
    current_compute_allocation: float = Field(
        default=0.0,
        ge=0.0,
        description="Current edge compute capacity allocated to this slice (in compute units / CPU cores)."
    )
    sla_headroom: float = Field(
        default=1.0,
        description="Normalized SLA headroom indicator. Value < 0.0 indicates an SLA violation."
    )


class NetworkState(BaseModel):
    """
    Comprehensive multi-slice network state observation vector.
    Serves as input to allocation policies, the Safety Shield, and metrics engine.
    """
    run_id: Optional[str] = Field(
        default=None,
        description="Unique identifier of the executing simulation run."
    )
    step: int = Field(
        ...,
        ge=0,
        description="Current discrete simulation step index (0, 1, 2, ...)."
    )
    sim_time_sec: float = Field(
        ...,
        ge=0.0,
        description="Total elapsed simulation time in seconds."
    )
    total_radio_capacity: float = Field(
        ...,
        gt=0.0,
        description="Total radio bandwidth capacity available across the gNodeB / RAN."
    )
    total_compute_capacity: float = Field(
        ...,
        gt=0.0,
        description="Total edge compute processing capacity available at the local UPF/MEC node."
    )
    slice_states: Dict[SliceId, SliceState] = Field(
        ...,
        description="Per-slice state observations. Must contain exactly the three canonical slices."
    )
    is_congested: bool = Field(
        default=False,
        description="Global binary flag indicating whether overall network demand exceeds capacity."
    )
    congested_slices: List[SliceId] = Field(
        default_factory=list,
        description="List of specific slice IDs currently experiencing queuing congestion or SLA breaches."
    )
    scenario_id: Optional[str] = Field(
        default=None,
        description="Scenario identifier metadata."
    )
    seed: Optional[int] = Field(
        default=None,
        description="Seed metadata."
    )

    @field_validator("slice_states")
    @classmethod
    def validate_canonical_slice_states(cls, v: Dict[SliceId, SliceState]) -> Dict[SliceId, SliceState]:
        keys = set(v.keys())
        expected = set(CANONICAL_SLICE_IDS)
        if keys != expected:
            missing = expected - keys
            extra = keys - expected
            err_msg = []
            if missing:
                err_msg.append(f"Missing slice states for canonical slices: {[m.value for m in missing]}")
            if extra:
                err_msg.append(f"Unexpected slice states: {[e for e in extra]}")
            raise ValueError("; ".join(err_msg))

        # Ensure internal SliceState.slice_id matches dict key
        for sid, sstate in v.items():
            if sstate.slice_id != sid:
                raise ValueError(
                    f"Slice key '{sid.value}' does not match SliceState.slice_id '{sstate.slice_id.value}'"
                )
        return v

    @model_validator(mode="after")
    def validate_resource_consistency(self) -> "NetworkState":
        # Sum of current allocations must not exceed total capacity + numerical tolerance
        EPS = 1e-4
        tot_radio_alloc = sum(s.current_radio_allocation for s in self.slice_states.values())
        if tot_radio_alloc > (self.total_radio_capacity + EPS):
            raise ValueError(
                f"Sum of current slice radio allocations ({tot_radio_alloc:.3f}) "
                f"exceeds total radio capacity ({self.total_radio_capacity:.3f})"
            )

        tot_compute_alloc = sum(s.current_compute_allocation for s in self.slice_states.values())
        if tot_compute_alloc > (self.total_compute_capacity + EPS):
            raise ValueError(
                f"Sum of current slice compute allocations ({tot_compute_alloc:.3f}) "
                f"exceeds total compute capacity ({self.total_compute_capacity:.3f})"
            )
        return self
