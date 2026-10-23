"""
SLA Guardian - Traffic Generator
Generates reproducible, slice-specific packet arrivals using seeded NumPy RNG.
Supports 'normal', 'urllc_burst', and 'mixed_stress' scenarios.
"""

from typing import Dict, List, Optional, Any
import numpy as np

from ..schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig
from .queues import Packet


class TrafficGenerator:
    """
    Stochastic, reproducible 5G traffic generator for eMBB, URLLC, and mURLLC slices.
    Driven by configured scenario arrival rates, packet size distributions, and burst parameters.
    """

    def __init__(
        self,
        config: RunConfig,
        scenario_data: Optional[dict] = None,
        seed: Optional[int] = None,
    ):
        self.config = config
        self.scenario_data = scenario_data or {}
        self.seed = seed if seed is not None else config.seed
        self.rng = np.random.default_rng(self.seed)
        self.packet_counter = 0
        self.active_spikes: List[Dict[str, Any]] = []

        # Extract scenario profile parameters
        self.scenario_name = config.traffic_profile
        self._init_slice_profiles()

    def _init_slice_profiles(self):
        """Initializes per-slice baseline parameters from scenario data or defaults."""
        profiles = self.scenario_data.get("traffic_profiles", {})
        active_profile = profiles.get(self.scenario_name, {})
        nominal_rates = active_profile.get("nominal_demand_mbps", {})

        # Default baseline nominal rates in Mbps
        self.base_rates_mbps: Dict[SliceId, float] = {
            SliceId.EMBB: float(nominal_rates.get("eMBB", 45.0)),
            SliceId.URLLC: float(nominal_rates.get("URLLC", 8.0)),
            SliceId.MURLLC: float(nominal_rates.get("mURLLC", 15.0)),
        }

        # Apply scenario-specific overrides if configured
        if self.scenario_name == "urllc_burst":
            multiplier = float(active_profile.get("burst_multiplier", 4.0))
            self.base_rates_mbps[SliceId.URLLC] *= multiplier

        # Configured packet sizes (bytes)
        self.packet_sizes: Dict[SliceId, int] = {
            SliceId.EMBB: 1400,   # Video streaming / large payload MTU
            SliceId.URLLC: 250,   # Compact tactile control / telemetry
            SliceId.MURLLC: 500,  # Sensor aggregation / industrial telemetry
        }

        # Latency deadlines in seconds (derived from SLA or scenario)
        sla = self.config.sla_thresholds
        self.deadlines_sec: Dict[SliceId, float] = {
            SliceId.EMBB: (sla[SliceId.EMBB].max_latency_ms * 1.5) / 1000.0,
            SliceId.URLLC: (sla[SliceId.URLLC].max_latency_ms * 1.5) / 1000.0,
            SliceId.MURLLC: (sla[SliceId.MURLLC].max_latency_ms * 1.5) / 1000.0,
        }

    def generate_step_arrivals(
        self,
        step: int,
        sim_time_sec: float,
        step_duration_sec: float,
    ) -> Dict[SliceId, List[Packet]]:
        """
        Generates packet arrivals for one discrete time step.
        
        Returns:
            Dict[SliceId, List[Packet]]: New packets arriving during this step.
        """
        arrivals: Dict[SliceId, List[Packet]] = {s: [] for s in CANONICAL_SLICE_IDS}

        for slice_id in CANONICAL_SLICE_IDS:
            nominal_mbps = self.base_rates_mbps[slice_id]

            # Workload dynamics by slice type
            if slice_id == SliceId.EMBB:
                # eMBB exhibits slow demand variation + Poisson arrivals
                # Sinusoidal modulation simulating user video sessions
                modulation = 1.0 + 0.15 * np.sin(2 * np.pi * step / 100.0)
                mean_mbps = nominal_mbps * modulation
            elif slice_id == SliceId.URLLC:
                # URLLC: steady periodic packets with random micro-bursts
                mean_mbps = nominal_mbps
            else:
                # mURLLC: massive sensor arrivals with Poisson fluctuation
                mean_mbps = nominal_mbps

            # Apply active runtime spikes if present
            for spike in self.active_spikes:
                if spike["slice_id"] == slice_id:
                    s_start = spike["start_step"]
                    s_end = s_start + spike["duration_steps"]
                    if s_start <= step < s_end:
                        mean_mbps *= spike["multiplier"]

            # Total expected bytes in this step interval
            expected_bytes = (mean_mbps * 1e6 * step_duration_sec) / 8.0
            pkt_size = self.packet_sizes[slice_id]
            expected_pkts = expected_bytes / pkt_size

            # Poisson arrival count for step
            num_pkts = int(self.rng.poisson(lam=max(0.1, expected_pkts)))

            deadline_delta = self.deadlines_sec[slice_id]

            for _ in range(num_pkts):
                self.packet_counter += 1
                # Spread arrival time evenly or randomly across step interval
                sub_offset = float(self.rng.uniform(0.0, step_duration_sec))
                arrival_time = sim_time_sec + sub_offset

                pkt = Packet(
                    packet_id=self.packet_counter,
                    slice_id=slice_id,
                    size_bytes=pkt_size,
                    arrival_time=arrival_time,
                    deadline_time=arrival_time + deadline_delta,
                    radio_enter_time=arrival_time,
                    status="QUEUED_RADIO",
                )
                arrivals[slice_id].append(pkt)

        return arrivals

    def inject_spike(
        self,
        target_slice: SliceId,
        multiplier: float,
        duration_steps: int,
        start_step: int,
    ):
        """Injects a transient multiplier surge into a specific slice's demand."""
        self.active_spikes.append({
            "slice_id": target_slice,
            "multiplier": float(multiplier),
            "duration_steps": int(duration_steps),
            "start_step": int(start_step),
        })

    def reset(self, seed: Optional[int] = None):
        """Resets PRNG, packet sequence counters, and active spikes."""
        if seed is not None:
            self.seed = seed
        self.rng = np.random.default_rng(self.seed)
        self.packet_counter = 0
        self.active_spikes.clear()
        self._init_slice_profiles()
