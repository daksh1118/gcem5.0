"""
SLA Guardian - Simulation Queue & Packet Lifecycle Models
Tracks packet-level metadata, arrival timestamps, stage transitions, and queue dynamics.
"""

from dataclasses import dataclass
from typing import Optional, List, Deque
from collections import deque
from ..schemas.config import SliceId


@dataclass
class Packet:
    """Represents an individual packet flowing through the radio and edge-compute stages."""
    packet_id: int
    slice_id: SliceId
    size_bytes: int
    arrival_time: float  # seconds
    deadline_time: Optional[float] = None  # seconds (None for best-effort)

    # Radio stage timestamps
    radio_enter_time: float = 0.0
    radio_exit_time: Optional[float] = None

    # Compute stage timestamps
    compute_enter_time: Optional[float] = None
    compute_exit_time: Optional[float] = None

    # Lifecycle state
    status: str = "QUEUED_RADIO"  # QUEUED_RADIO, QUEUED_COMPUTE, DELIVERED, DROPPED
    drop_reason: Optional[str] = None

    @property
    def radio_latency_ms(self) -> Optional[float]:
        """Radio latency in milliseconds if radio service is complete."""
        if self.radio_exit_time is not None:
            return (self.radio_exit_time - self.radio_enter_time) * 1000.0
        return None

    @property
    def compute_latency_ms(self) -> Optional[float]:
        """Edge compute latency in milliseconds if compute service is complete."""
        if self.compute_exit_time is not None and self.compute_enter_time is not None:
            return (self.compute_exit_time - self.compute_enter_time) * 1000.0
        return None

    @property
    def end_to_end_latency_ms(self) -> Optional[float]:
        """Total end-to-end packet latency in milliseconds from generation to compute delivery."""
        if self.compute_exit_time is not None:
            return (self.compute_exit_time - self.arrival_time) * 1000.0
        return None


class PacketQueue:
    """
    FIFO queue for a network slice stage (Radio or Compute).
    Enforces maximum packet capacity and tracks total queued bytes.
    """

    def __init__(self, slice_id: SliceId, stage_name: str, max_packets: int = 5000):
        self.slice_id: SliceId = slice_id
        self.stage_name: str = stage_name
        self.max_packets: int = max_packets
        self._queue: Deque[Packet] = deque()
        self._total_bytes: int = 0

    def enqueue(self, packet: Packet) -> bool:
        """
        Enqueues a packet. Returns False and marks packet as DROPPED if queue is full.
        """
        if len(self._queue) >= self.max_packets:
            packet.status = "DROPPED"
            packet.drop_reason = f"QUEUE_OVERFLOW_{self.stage_name.upper()}"
            return False

        self._queue.append(packet)
        self._total_bytes += packet.size_bytes
        return True

    def peek(self) -> Optional[Packet]:
        """Inspects head packet without removing it."""
        if self._queue:
            return self._queue[0]
        return None

    def pop(self) -> Optional[Packet]:
        """Removes and returns head packet."""
        if self._queue:
            pkt = self._queue.popleft()
            self._total_bytes = max(0, self._total_bytes - pkt.size_bytes)
            return pkt
        return None

    def size(self) -> int:
        """Current number of packets waiting in the queue."""
        return len(self._queue)

    def queued_bytes(self) -> int:
        """Total payload bytes currently queued."""
        return self._total_bytes

    def drop_expired(self, current_time: float) -> List[Packet]:
        """
        Drops packets whose latency deadline has been exceeded.
        Returns the list of dropped packets.
        """
        active_packets: Deque[Packet] = deque()
        dropped: List[Packet] = []

        while self._queue:
            pkt = self._queue.popleft()
            if pkt.deadline_time is not None and current_time > pkt.deadline_time:
                pkt.status = "DROPPED"
                pkt.drop_reason = f"DEADLINE_EXCEEDED_{self.stage_name.upper()}"
                self._total_bytes = max(0, self._total_bytes - pkt.size_bytes)
                dropped.append(pkt)
            else:
                active_packets.append(pkt)

        self._queue = active_packets
        return dropped

    def clear(self):
        """Empties the queue."""
        self._queue.clear()
        self._total_bytes = 0
