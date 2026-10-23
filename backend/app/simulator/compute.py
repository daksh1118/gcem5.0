"""
SLA Guardian - Edge-Compute Processing Model
Models multi-tenant edge server CPU resource allocation, queuing,
and workload execution for packets egressing from the radio interface.
"""

from typing import Dict, List, Tuple, Optional
import numpy as np

from ..schemas.config import SliceId, CANONICAL_SLICE_IDS
from .queues import Packet, PacketQueue


class EdgeComputeModel:
    """
    Edge-compute execution model representing MEC (Multi-Access Edge Computing) servers.
    Converts compute allocations (CPU core shares / execution units) into service rate,
    processing packets that have completed radio transmission.
    """

    def __init__(
        self,
        total_compute_capacity: float = 100.0,
        compute_service_rate_mbps_per_unit: float = 1.0,
    ):
        self.total_compute_capacity = total_compute_capacity
        self.service_rate_mbps_per_unit = compute_service_rate_mbps_per_unit

    def validate_allocation(self, compute_allocations: Dict[SliceId, float]):
        """
        Validates that compute allocations are non-negative and do not exceed capacity.
        Raises ValueError if violated.
        """
        EPS = 1e-4
        tot_alloc = sum(compute_allocations.values())
        if tot_alloc > (self.total_compute_capacity + EPS):
            raise ValueError(
                f"Total compute allocation ({tot_alloc:.3f}) exceeds total compute capacity ({self.total_compute_capacity:.3f})"
            )

        for s, val in compute_allocations.items():
            if val < 0.0 or not np.isfinite(val):
                raise ValueError(f"Compute allocation for slice '{s.value}' is invalid: {val}")

    def service_queues(
        self,
        compute_queues: Dict[SliceId, PacketQueue],
        compute_allocations: Dict[SliceId, float],
        sim_time_sec: float,
        step_duration_sec: float,
    ) -> Tuple[Dict[SliceId, List[Packet]], Dict[SliceId, float]]:
        """
        Processes packets in each slice's compute queue up to the allocated compute capacity.
        
        Returns:
            Tuple:
            - Dict[SliceId, List[Packet]]: Packets successfully processed and delivered to user application.
            - Dict[SliceId, float]: Effective compute service capacity in Mbps per slice.
        """
        self.validate_allocation(compute_allocations)

        delivered_packets: Dict[SliceId, List[Packet]] = {s: [] for s in CANONICAL_SLICE_IDS}
        service_capacities_mbps: Dict[SliceId, float] = {}

        for slice_id in CANONICAL_SLICE_IDS:
            alloc = compute_allocations.get(slice_id, 0.0)

            # Effective processing capacity in Mbps
            cap_mbps = alloc * self.service_rate_mbps_per_unit
            service_capacities_mbps[slice_id] = cap_mbps

            # Byte budget for this step
            remaining_bytes = (cap_mbps * 1e6 * step_duration_sec) / 8.0
            queue = compute_queues[slice_id]

            # Drain compute queue FIFO
            while queue.size() > 0:
                head = queue.peek()
                if head is None:
                    break

                if head.size_bytes <= remaining_bytes:
                    pkt = queue.pop()
                    if pkt is not None:
                        remaining_bytes -= pkt.size_bytes
                        pkt.compute_exit_time = sim_time_sec + step_duration_sec
                        pkt.status = "DELIVERED"
                        delivered_packets[slice_id].append(pkt)
                else:
                    # Packet cannot finish processing in current step; remains in queue
                    break

        return delivered_packets, service_capacities_mbps

    def reset(self):
        """Resets compute state."""
        pass
