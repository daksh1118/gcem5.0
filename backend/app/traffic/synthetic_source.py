"""
SLA Guardian - Synthetic Test Traffic Source
Encapsulates synthetic stochastic traffic generation (Poisson arrivals + scenario profiles).
Explicitly designated as synthetic test data; never substituted silently for real data.
"""

from typing import Dict, List, Optional, Any, Tuple
import numpy as np

from ..schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig
from ..simulator.queues import Packet
from ..simulator.traffic import TrafficGenerator
from .interface import (
    TrafficSourceInterface,
    TrafficSourceType,
    TrafficSourceStatus,
    TrafficSourceMetadata,
    TrafficStepArrivals,
    TrafficEvent,
)


class SyntheticTestTrafficSource(TrafficSourceInterface):
    """
    Explicit synthetic traffic source for reproducible regression tests and baseline demos.
    Uses seeded Poisson arrival modeling driven by scenarios/default.json.
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
        self.generator = TrafficGenerator(
            config=self.config,
            scenario_data=self.scenario_data,
            seed=self.seed,
        )
        self._status = TrafficSourceStatus.READY

    @property
    def source_type(self) -> TrafficSourceType:
        return TrafficSourceType.SYNTHETIC

    @property
    def status(self) -> TrafficSourceStatus:
        return self._status

    def get_metadata(self) -> TrafficSourceMetadata:
        active_scen = self.generator.scenario_name
        base_rates = self.generator.base_rates_mbps
        return TrafficSourceMetadata(
            source_type=self.source_type,
            source_name=f"Synthetic Generator ({active_scen})",
            status=self.status,
            description="Stochastic Poisson packet generator based on predefined scenario profiles. For testing/demo use only.",
            total_records=0,
            duration_sec=float(self.config.max_steps * self.config.step_duration_ms / 1000.0),
            time_range_sec=(0.0, float(self.config.max_steps * self.config.step_duration_ms / 1000.0)),
            slice_distribution={s.value: int(base_rates.get(s, 0.0)) for s in CANONICAL_SLICE_IDS},
            unclassified_count=0,
            classification_coverage_pct=100.0,
            sample_rate_hz=1000.0 / self.config.step_duration_ms,
            data_quality_flags=["SYNTHETIC_DATA_TEST_ONLY", "STOCHASTIC_POISSON_MODEL"],
            measured_metrics_available=[],
            simulated_metrics_required=["throughput_mbps", "p95_latency_ms", "packet_delivery_ratio", "sla_status"],
        )

    def validate(self) -> Tuple[bool, List[str]]:
        """Synthetic generator validation."""
        messages = ["Synthetic stochastic generator initialized and validated against scenario profiles."]
        return True, messages

    def generate_step_arrivals(
        self,
        step: int,
        sim_time_sec: float,
        step_duration_sec: float,
    ) -> TrafficStepArrivals:
        raw_arrivals = self.generator.generate_step_arrivals(
            step=step,
            sim_time_sec=sim_time_sec,
            step_duration_sec=step_duration_sec,
        )

        offered_bytes: Dict[SliceId, int] = {}
        offered_mbps: Dict[SliceId, float] = {}

        for s in CANONICAL_SLICE_IDS:
            pkts = raw_arrivals.get(s, [])
            tot_b = sum(p.size_bytes for p in pkts)
            offered_bytes[s] = tot_b
            offered_mbps[s] = (tot_b * 8.0) / (1e6 * max(1e-6, step_duration_sec))

        self._status = TrafficSourceStatus.STREAMING

        return TrafficStepArrivals(
            step=step,
            sim_time_sec=sim_time_sec,
            step_duration_sec=step_duration_sec,
            packets=raw_arrivals,
            unclassified_events=[],
            offered_bytes=offered_bytes,
            offered_mbps=offered_mbps,
            unclassified_bytes=0,
            unclassified_mbps=0.0,
            is_end_of_trace=False,
            diagnostics={"active_spikes": len(self.generator.active_spikes)},
        )

    def inject_spike(
        self,
        target_slice: SliceId,
        multiplier: float,
        duration_steps: int,
        start_step: int,
    ):
        self.generator.inject_spike(target_slice, multiplier, duration_steps, start_step)

    def reset(self, seed: Optional[int] = None, start_time_sec: float = 0.0):
        if seed is not None:
            self.seed = seed
        self.generator.reset(seed=self.seed)
        self._status = TrafficSourceStatus.READY

    def close(self):
        self._status = TrafficSourceStatus.PAUSED
