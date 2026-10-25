"""
SLA Guardian - Pluggable Traffic Source Interface & Data Models
Defines the standard contracts for synthetic generators, recorded trace replay,
and live telemetry ingestion into the 5G network simulator.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
from pydantic import BaseModel, Field, ConfigDict

from ..schemas.config import SliceId, CANONICAL_SLICE_IDS


class TrafficSourceType(str, Enum):
    """Identifies the operational mode of the traffic ingestion pipeline."""
    SYNTHETIC = "synthetic"
    TRACE_REPLAY = "trace_replay"
    LIVE_TELEMETRY = "live_telemetry"


class TrafficSourceStatus(str, Enum):
    """Health and lifecycle status of a traffic source."""
    UNINITIALIZED = "uninitialized"
    UNCONFIGURED = "unconfigured"
    READY = "ready"
    STREAMING = "streaming"
    PAUSED = "paused"
    STALE = "stale"
    END_OF_TRACE = "end_of_trace"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class TrafficEvent(BaseModel):
    """
    Normalized representation of a single timestamped network packet event.
    Supports anonymized identifiers and QoS mappings without payload storage.
    """
    packet_id: int = Field(..., description="Unique sequence identifier for the packet.")
    timestamp_sec: float = Field(..., description="Arrival timestamp relative to simulation start (seconds).")
    size_bytes: int = Field(..., gt=0, description="Packet size in bytes.")
    slice_id: Optional[SliceId] = Field(default=None, description="Assigned 5G slice if classified.")
    flow_id: Optional[str] = Field(default=None, description="Anonymized flow identifier.")
    ue_id: Optional[str] = Field(default=None, description="Anonymized user equipment or sensor identifier.")
    direction: Optional[str] = Field(default="downlink", description="Transmission direction: 'downlink' or 'uplink'.")
    qos_label: Optional[str] = Field(default=None, description="Source 5QI, QFI, DSCP, or traffic-class label.")
    source_measured_latency_ms: Optional[float] = Field(default=None, description="Latency measured at source if available.")
    source_measured_pdr: Optional[float] = Field(default=None, description="Delivery ratio measured at source if available.")


class TrafficStepArrivals(BaseModel):
    """
    Encapsulates all traffic arriving during a single simulation step.
    Maintains clean separation between classified slice packets and unclassified events.
    """
    step: int
    sim_time_sec: float
    step_duration_sec: float
    packets: Dict[SliceId, List[Any]] = Field(
        default_factory=lambda: {s: [] for s in CANONICAL_SLICE_IDS},
        description="Classified packets ready for radio and edge queues."
    )
    unclassified_events: List[TrafficEvent] = Field(
        default_factory=list,
        description="Packets lacking valid slice mapping, excluded from active slice queues."
    )
    offered_bytes: Dict[SliceId, int] = Field(
        default_factory=lambda: {s: 0 for s in CANONICAL_SLICE_IDS}
    )
    offered_mbps: Dict[SliceId, float] = Field(
        default_factory=lambda: {s: 0.0 for s in CANONICAL_SLICE_IDS}
    )
    unclassified_bytes: int = 0
    unclassified_mbps: float = 0.0
    is_end_of_trace: bool = False
    diagnostics: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def total_packets(self) -> int:
        return sum(len(pkts) for pkts in self.packets.values())

    @property
    def total_bytes(self) -> int:
        return sum(self.offered_bytes.values())

    @property
    def packets_per_slice(self) -> Dict[str, int]:
        return {s.value if hasattr(s, "value") else str(s): len(pkts) for s, pkts in self.packets.items()}

    @property
    def bytes_per_slice(self) -> Dict[str, int]:
        return {s.value if hasattr(s, "value") else str(s): self.offered_bytes.get(s, 0) for s in self.packets}


class TrafficSourceMetadata(BaseModel):
    """Descriptive metadata and quality metrics for a traffic source."""
    source_type: TrafficSourceType
    source_name: str
    status: TrafficSourceStatus
    description: str
    total_records: int = 0
    duration_sec: float = 0.0
    time_range_sec: Optional[Tuple[float, float]] = None
    slice_distribution: Dict[str, int] = Field(default_factory=dict)
    unclassified_count: int = 0
    classification_coverage_pct: float = 100.0
    sample_rate_hz: Optional[float] = None
    data_quality_flags: List[str] = Field(default_factory=list)
    measured_metrics_available: List[str] = Field(default_factory=list)
    simulated_metrics_required: List[str] = Field(
        default_factory=lambda: ["throughput_mbps", "p95_latency_ms", "packet_delivery_ratio", "sla_status"]
    )


class TrafficSourceInterface(ABC):
    """
    Abstract interface for all traffic providers in SLA Guardian.
    Ensures pluggability between synthetic models, recorded traces, and live telemetry.
    """

    @property
    @abstractmethod
    def source_type(self) -> TrafficSourceType:
        """Returns the specific traffic source type."""
        pass

    @property
    @abstractmethod
    def status(self) -> TrafficSourceStatus:
        """Returns the current operational status of the source."""
        pass

    @abstractmethod
    def get_metadata(self) -> TrafficSourceMetadata:
        """Returns structured metadata, data quality summary, and classification coverage."""
        pass

    @abstractmethod
    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validates data integrity, timestamp ordering, schema conformance, and slice mappings.
        Returns (is_valid, list_of_validation_messages).
        """
        pass

    @abstractmethod
    def generate_step_arrivals(
        self,
        step: int,
        sim_time_sec: float,
        step_duration_sec: float,
    ) -> TrafficStepArrivals:
        """
        Retrieves or generates new packet arrivals for the specified simulation step.
        """
        pass

    def initialize(self):
        """Initializes or opens underlying resources. Safe no-op by default."""
        pass

    def get_diagnostics(self) -> Dict[str, Any]:
        """Returns runtime diagnostic metrics for this traffic source."""
        return self.get_metadata().model_dump()

    @abstractmethod
    def reset(self, seed: Optional[int] = None, start_time_sec: float = 0.0):
        """
        Resets replay index or internal PRNG state for deterministic reproducibility.
        """
        pass

    @abstractmethod
    def close(self):
        """Releases file handles, network sockets, or background polling loops."""
        pass

