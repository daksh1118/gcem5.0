"""
SLA Guardian - Simulation Diagnostics
Defines granular, typed step diagnostics for KPI tracking, SLA monitoring, and debugging.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from ..schemas.config import SliceId, CANONICAL_SLICE_IDS
from ..interfaces.simulator import SimulatorDiagnostics


class GranularSliceDiagnostics(BaseModel):
    """Detailed stage-by-stage measurements for a single slice in one step."""
    slice_id: SliceId
    offered_packets: int = 0
    offered_bytes: int = 0
    radio_completed_packets: int = 0
    compute_completed_packets: int = 0
    dropped_packets: int = 0
    radio_queue_packets: int = 0
    compute_queue_packets: int = 0
    radio_capacity_mbps: float = 0.0
    compute_capacity_mbps: float = 0.0
    delivered_throughput_mbps: float = 0.0
    mean_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    drop_reasons: Dict[str, int] = Field(default_factory=dict)


class StepDiagnostics(BaseModel):
    """
    Rich diagnostic container for the entire network simulator step.
    Can be seamlessly converted into the standard SimulatorDiagnostics model.
    """
    step: int
    sim_time_sec: float
    terminated: bool = False
    truncated: bool = False
    total_offered_packets: int = 0
    total_delivered_packets: int = 0
    total_dropped_packets: int = 0
    slice_diagnostics: Dict[SliceId, GranularSliceDiagnostics]

    def to_interface_diagnostics(self) -> SimulatorDiagnostics:
        """Converts into the standard SimulatorDiagnostics required by SimulatorInterface."""
        active_flows = sum(
            sd.radio_queue_packets + sd.compute_queue_packets for sd in self.slice_diagnostics.values()
        )
        extra = {
            "total_offered_packets": self.total_offered_packets,
            "total_delivered_packets": self.total_delivered_packets,
            "slice_diagnostics": {
                s.value: sd.model_dump() for s, sd in self.slice_diagnostics.items()
            },
        }
        return SimulatorDiagnostics(
            step=self.step,
            terminated=self.terminated,
            truncated=self.truncated,
            active_flows=active_flows,
            dropped_packets=self.total_dropped_packets,
            extra_info=extra,
        )
