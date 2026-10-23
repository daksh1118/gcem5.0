"""
SLA Guardian - Radio Resource Allocation Model
Models OFDMA-inspired bandwidth allocation, stochastic channel fading,
and per-slice transmission service over discrete time steps.
"""

from typing import Dict, List, Tuple, Optional
import numpy as np

from ..schemas.config import SliceId, CANONICAL_SLICE_IDS
from .queues import Packet, PacketQueue


class RadioModel:
    """
    Abstracted 5G-inspired radio access network (RAN) resource model.
    Converts executed radio PRB allocations and stochastic channel conditions
    into achievable physical layer service throughput.
    """

    def __init__(
        self,
        total_radio_capacity: float = 100.0,
        service_rate_mbps_per_unit: float = 1.0,
        enable_channel_fading: bool = True,
        seed: int = 42,
    ):
        self.total_radio_capacity = total_radio_capacity
        self.service_rate_mbps_per_unit = service_rate_mbps_per_unit
        self.enable_channel_fading = enable_channel_fading
        self.rng = np.random.default_rng(seed)

        # Current dimensionless channel power gains (bounded positive values, mean ~1.0)
        self.current_channel_gains: Dict[SliceId, float] = {s: 1.0 for s in CANONICAL_SLICE_IDS}

    def update_channel_conditions(self):
        """
        Updates stochastic channel power gains per slice.
        Models Rayleigh power fading with a bounded floor [0.35, 1.85] to maintain physical stability.
        """
        if not self.enable_channel_fading:
            self.current_channel_gains = {s: 1.0 for s in CANONICAL_SLICE_IDS}
            return

        for slice_id in CANONICAL_SLICE_IDS:
            # Exponential random variable with mean 1.0 (Rayleigh power distribution)
            raw_gain = float(self.rng.exponential(scale=1.0))
            # Clip between 0.35 (severe deep fade) and 1.85 (constructive peak)
            gain = max(0.35, min(1.85, raw_gain))
            self.current_channel_gains[slice_id] = gain

    def validate_allocation(self, radio_allocations: Dict[SliceId, float]):
        """
        Validates that allocations are non-negative and within configured radio capacity.
        Raises ValueError on violation.
        """
        EPS = 1e-4
        tot_alloc = sum(radio_allocations.values())
        if tot_alloc > (self.total_radio_capacity + EPS):
            raise ValueError(
                f"Total radio allocation ({tot_alloc:.3f}) exceeds total radio capacity ({self.total_radio_capacity:.3f})"
            )

        for s, val in radio_allocations.items():
            if val < 0.0 or not np.isfinite(val):
                raise ValueError(f"Radio allocation for slice '{s.value}' is invalid: {val}")

    def service_queues(
        self,
        radio_queues: Dict[SliceId, PacketQueue],
        radio_allocations: Dict[SliceId, float],
        sim_time_sec: float,
        step_duration_sec: float,
    ) -> Tuple[Dict[SliceId, List[Packet]], Dict[SliceId, float]]:
        """
        Processes packets in each slice's radio queue up to the allocated service capacity.
        
        Returns:
            Tuple:
            - Dict[SliceId, List[Packet]]: Packets successfully serviced by radio (ready for compute stage).
            - Dict[SliceId, float]: Effective service capacity in Mbps per slice during this step.
        """
        self.validate_allocation(radio_allocations)
        self.update_channel_conditions()

        serviced_packets: Dict[SliceId, List[Packet]] = {s: [] for s in CANONICAL_SLICE_IDS}
        service_capacities_mbps: Dict[SliceId, float] = {}

        for slice_id in CANONICAL_SLICE_IDS:
            alloc = radio_allocations.get(slice_id, 0.0)
            gain = self.current_channel_gains[slice_id]

            # Achievable service capacity in Mbps
            cap_mbps = alloc * self.service_rate_mbps_per_unit * gain
            service_capacities_mbps[slice_id] = cap_mbps

            # Available byte budget for this step
            remaining_bytes = (cap_mbps * 1e6 * step_duration_sec) / 8.0
            queue = radio_queues[slice_id]

            # Drain queue FIFO
            while queue.size() > 0:
                head = queue.peek()
                if head is None:
                    break

                if head.size_bytes <= remaining_bytes:
                    pkt = queue.pop()
                    if pkt is not None:
                        remaining_bytes -= pkt.size_bytes
                        # Fractional transmission completion timestamp
                        pkt.radio_exit_time = sim_time_sec + step_duration_sec
                        pkt.status = "QUEUED_COMPUTE"
                        serviced_packets[slice_id].append(pkt)
                else:
                    # Packet cannot fit in remaining step capacity; remains head of queue
                    break

        return serviced_packets, service_capacities_mbps

    def reset(self, seed: Optional[int] = None):
        """Resets channel state and RNG."""
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self.current_channel_gains = {s: 1.0 for s in CANONICAL_SLICE_IDS}
