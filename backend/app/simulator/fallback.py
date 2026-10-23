"""
SLA Guardian - Fallback 5G Network Slicing & Edge-Compute Simulator
Implements SimulatorInterface with coupled OFDMA radio scheduling,
stochastic channel fading, and multi-tenant edge-compute processing.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from pathlib import Path
import json

from ..schemas.config import (
    SliceId,
    CANONICAL_SLICE_IDS,
    RunConfig,
    SliceSlaConfig,
)
from ..schemas.state import SliceState, NetworkState
from ..schemas.actions import ExecutedAction
from ..interfaces.simulator import SimulatorInterface, SimulatorDiagnostics
from .queues import Packet, PacketQueue
from .traffic import TrafficGenerator
from .radio import RadioModel
from .compute import EdgeComputeModel
from .diagnostics import GranularSliceDiagnostics, StepDiagnostics


class FallbackNetworkSimulator(SimulatorInterface):
    """
    High-fidelity discrete-event fallback simulator for 5G network slicing.
    
    Coupled Architecture:
    [Traffic Generator] -> [Radio Queue] -> (Radio Model: OFDMA + Fading)
                        -> [Compute Queue] -> (Edge-Compute Model: CPU Processing)
                        -> [Application Delivery & SLA Telemetry]
    """

    def __init__(self, config: Optional[RunConfig] = None, scenario_data: Optional[dict] = None):
        self.config = config or self._load_default_config()
        self.scenario_data = scenario_data or self._load_default_scenario_data()

        self.step_duration_sec = self.config.step_duration_ms / 1000.0
        self.current_step = 0
        self.sim_time_sec = 0.0

        # Sub-models
        self.traffic_gen = TrafficGenerator(self.config, self.scenario_data, seed=self.config.seed)
        self.radio_model = RadioModel(
            total_radio_capacity=self.config.total_radio_capacity,
            service_rate_mbps_per_unit=1.0,
            seed=self.config.seed,
        )
        self.compute_model = EdgeComputeModel(
            total_compute_capacity=self.config.total_compute_capacity,
            compute_service_rate_mbps_per_unit=1.0,
        )

        # Per-slice queues for Radio and Compute stages
        self.radio_queues: Dict[SliceId, PacketQueue] = {
            s: PacketQueue(s, "radio", max_packets=5000) for s in CANONICAL_SLICE_IDS
        }
        self.compute_queues: Dict[SliceId, PacketQueue] = {
            s: PacketQueue(s, "compute", max_packets=5000) for s in CANONICAL_SLICE_IDS
        }

        # Rolling packet latency window per slice for robust percentile calculation
        self.delivered_latency_history: Dict[SliceId, List[float]] = {s: [] for s in CANONICAL_SLICE_IDS}
        self.last_known_p95: Dict[SliceId, Optional[float]] = {s: None for s in CANONICAL_SLICE_IDS}
        self.last_offered_demand: Dict[SliceId, float] = {s: 0.0 for s in CANONICAL_SLICE_IDS}

    def _load_default_scenario_data(self) -> dict:
        root = Path(__file__).resolve().parent.parent.parent.parent
        scen_path = root / "scenarios" / "default.json"
        if scen_path.exists():
            with open(scen_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _load_default_config(self) -> RunConfig:
        data = self._load_default_scenario_data()
        if data:
            return RunConfig(**data)
        # Minimal fallback config if file missing
        sla = {
            SliceId.EMBB: SliceSlaConfig(max_latency_ms=25.0, min_throughput_mbps=50.0, min_packet_delivery_ratio=0.98),
            SliceId.URLLC: SliceSlaConfig(max_latency_ms=5.0, min_throughput_mbps=10.0, min_packet_delivery_ratio=0.9999),
            SliceId.MURLLC: SliceSlaConfig(max_latency_ms=15.0, min_throughput_mbps=20.0, min_packet_delivery_ratio=0.999),
        }
        return RunConfig(
            scenario_id="default_fallback",
            total_radio_capacity=100.0,
            total_compute_capacity=100.0,
            sla_thresholds=sla,
        )

    def reset(
        self,
        seed: Optional[int] = None,
        scenario: Optional[Dict[str, Any]] = None,
        config: Optional[RunConfig] = None,
    ) -> NetworkState:
        """
        Resets all simulation components, queues, and clocks to Step 0.
        """
        if config is not None:
            self.config = config
            self.step_duration_sec = self.config.step_duration_ms / 1000.0
        if scenario is not None:
            self.scenario_data = scenario

        effective_seed = seed if seed is not None else self.config.seed
        self.current_step = 0
        self.sim_time_sec = 0.0

        # Reset queues
        for q in self.radio_queues.values():
            q.clear()
        for q in self.compute_queues.values():
            q.clear()

        # Reset sub-models
        self.traffic_gen.reset(seed=effective_seed)
        self.radio_model.reset(seed=effective_seed)
        self.compute_model.reset()

        self.delivered_latency_history = {s: [] for s in CANONICAL_SLICE_IDS}
        self.last_known_p95 = {s: None for s in CANONICAL_SLICE_IDS}

        # Build initial step 0 state
        slice_states: Dict[SliceId, SliceState] = {}
        for s in CANONICAL_SLICE_IDS:
            nom_mbps = self.traffic_gen.base_rates_mbps[s]
            self.last_offered_demand[s] = nom_mbps
            slice_states[s] = SliceState(
                slice_id=s,
                offered_demand_mbps=nom_mbps,
                demand_growth_rate=0.0,
                queue_depth_packets=0,
                delivered_throughput_mbps=None,
                p95_latency_ms=None,
                packet_delivery_ratio=None,
                current_radio_allocation=0.0,
                current_compute_allocation=0.0,
                sla_headroom=1.0,
            )

        return NetworkState(
            run_id=None,
            step=0,
            sim_time_sec=0.0,
            total_radio_capacity=self.config.total_radio_capacity,
            total_compute_capacity=self.config.total_compute_capacity,
            slice_states=slice_states,
            is_congested=False,
            congested_slices=[],
            scenario_id=self.config.scenario_id,
            seed=effective_seed,
        )

    def step(
        self,
        executed_action: ExecutedAction,
    ) -> Tuple[NetworkState, SimulatorDiagnostics]:
        """
        Executes one discrete simulation step of duration `config.step_duration_ms`.
        Consumes verified `ExecutedAction` and outputs the resulting observation and diagnostics.
        """
        # 1. Validate ExecutedAction budgets
        self.radio_model.validate_allocation(executed_action.radio_allocations)
        self.compute_model.validate_allocation(executed_action.compute_allocations)

        # 2. Drop expired packets from existing queues
        step_dropped_packets: Dict[SliceId, List[Packet]] = {s: [] for s in CANONICAL_SLICE_IDS}
        for s in CANONICAL_SLICE_IDS:
            r_expired = self.radio_queues[s].drop_expired(self.sim_time_sec)
            c_expired = self.compute_queues[s].drop_expired(self.sim_time_sec)
            step_dropped_packets[s].extend(r_expired + c_expired)

        # 3. Generate new packet arrivals for step
        new_arrivals = self.traffic_gen.generate_step_arrivals(
            step=self.current_step,
            sim_time_sec=self.sim_time_sec,
            step_duration_sec=self.step_duration_sec,
        )

        # Enqueue new arrivals into radio queue
        for s, pkts in new_arrivals.items():
            for pkt in pkts:
                ok = self.radio_queues[s].enqueue(pkt)
                if not ok:
                    step_dropped_packets[s].append(pkt)

        # 4. Process Radio Service Stage
        radio_serviced_packets, radio_capacities = self.radio_model.service_queues(
            radio_queues=self.radio_queues,
            radio_allocations=executed_action.radio_allocations,
            sim_time_sec=self.sim_time_sec,
            step_duration_sec=self.step_duration_sec,
        )

        # Transfer radio-completed packets to Edge-Compute stage
        for s, pkts in radio_serviced_packets.items():
            for pkt in pkts:
                pkt.compute_enter_time = pkt.radio_exit_time
                ok = self.compute_queues[s].enqueue(pkt)
                if not ok:
                    step_dropped_packets[s].append(pkt)

        # 5. Process Edge-Compute Service Stage
        delivered_packets, compute_capacities = self.compute_model.service_queues(
            compute_queues=self.compute_queues,
            compute_allocations=executed_action.compute_allocations,
            sim_time_sec=self.sim_time_sec,
            step_duration_sec=self.step_duration_sec,
        )

        # 6. Calculate Metrics and SLA Compliance per slice
        next_step_index = self.current_step + 1
        next_sim_time = self.sim_time_sec + self.step_duration_sec

        slice_states: Dict[SliceId, SliceState] = {}
        granular_diags: Dict[SliceId, GranularSliceDiagnostics] = {}
        congested_slices: List[SliceId] = []

        total_offered_pkts = sum(len(pkts) for pkts in new_arrivals.values())
        total_delivered_pkts = sum(len(pkts) for pkts in delivered_packets.values())
        total_dropped_pkts = sum(len(pkts) for pkts in step_dropped_packets.values())

        for s in CANONICAL_SLICE_IDS:
            sla = self.config.sla_thresholds[s]
            delivered = delivered_packets[s]
            dropped = step_dropped_packets[s]
            offered = new_arrivals[s]

            # Throughput delivered in this step
            deliv_bytes = sum(p.size_bytes for p in delivered)
            deliv_mbps = (deliv_bytes * 8.0) / (1e6 * self.step_duration_sec)

            # Offered demand in Mbps
            offered_bytes = sum(p.size_bytes for p in offered)
            offered_mbps = (offered_bytes * 8.0) / (1e6 * self.step_duration_sec)
            growth_rate = (offered_mbps - self.last_offered_demand[s]) / max(1.0, self.last_offered_demand[s])
            self.last_offered_demand[s] = offered_mbps

            # Latency measurements for delivered packets
            step_latencies = [p.end_to_end_latency_ms for p in delivered if p.end_to_end_latency_ms is not None]
            if step_latencies:
                self.delivered_latency_history[s].extend(step_latencies)
                # Keep sliding window of latest 200 samples
                if len(self.delivered_latency_history[s]) > 200:
                    self.delivered_latency_history[s] = self.delivered_latency_history[s][-200:]
                current_p95 = float(np.percentile(self.delivered_latency_history[s], 95))
                mean_lat = float(np.mean(step_latencies))
                self.last_known_p95[s] = current_p95
            else:
                current_p95 = self.last_known_p95[s]
                mean_lat = None

            # Packet Delivery Ratio
            total_finished = len(delivered) + len(dropped)
            if total_finished > 0:
                pdr = float(len(delivered) / total_finished)
            else:
                pdr = 1.0 if (self.radio_queues[s].size() == 0 and self.compute_queues[s].size() == 0) else None

            # SLA Headroom calculation
            # Positive = within SLA; Negative = SLA breach
            lat_headroom = 1.0
            if current_p95 is not None:
                lat_headroom = (sla.max_latency_ms - current_p95) / sla.max_latency_ms

            tput_headroom = 1.0
            if sla.min_throughput_mbps > 0.0:
                tput_headroom = (deliv_mbps - sla.min_throughput_mbps) / sla.min_throughput_mbps

            overall_headroom = min(lat_headroom, tput_headroom)
            total_queue_pkts = self.radio_queues[s].size() + self.compute_queues[s].size()

            if overall_headroom < 0.0 or total_queue_pkts > 50:
                congested_slices.append(s)

            slice_states[s] = SliceState(
                slice_id=s,
                offered_demand_mbps=round(offered_mbps, 3),
                demand_growth_rate=round(growth_rate, 3),
                queue_depth_packets=total_queue_pkts,
                delivered_throughput_mbps=round(deliv_mbps, 3),
                p95_latency_ms=round(current_p95, 2) if current_p95 is not None else None,
                packet_delivery_ratio=round(pdr, 4) if pdr is not None else None,
                current_radio_allocation=executed_action.radio_allocations[s],
                current_compute_allocation=executed_action.compute_allocations[s],
                sla_headroom=round(overall_headroom, 3),
            )

            # Drop reasons tally
            drop_reasons: Dict[str, int] = {}
            for p in dropped:
                reason = p.drop_reason or "UNKNOWN"
                drop_reasons[reason] = drop_reasons.get(reason, 0) + 1

            granular_diags[s] = GranularSliceDiagnostics(
                slice_id=s,
                offered_packets=len(offered),
                offered_bytes=offered_bytes,
                radio_completed_packets=len(radio_serviced_packets[s]),
                compute_completed_packets=len(delivered),
                dropped_packets=len(dropped),
                radio_queue_packets=self.radio_queues[s].size(),
                compute_queue_packets=self.compute_queues[s].size(),
                radio_capacity_mbps=round(radio_capacities[s], 3),
                compute_capacity_mbps=round(compute_capacities[s], 3),
                delivered_throughput_mbps=round(deliv_mbps, 3),
                mean_latency_ms=round(mean_lat, 2) if mean_lat is not None else None,
                p95_latency_ms=round(current_p95, 2) if current_p95 is not None else None,
                drop_reasons=drop_reasons,
            )

        # 7. Advance Clock & State
        self.current_step = next_step_index
        self.sim_time_sec = next_sim_time

        truncated = (self.current_step >= self.config.max_steps)
        terminated = False

        step_diag = StepDiagnostics(
            step=self.current_step,
            sim_time_sec=round(self.sim_time_sec, 4),
            terminated=terminated,
            truncated=truncated,
            total_offered_packets=total_offered_pkts,
            total_delivered_packets=total_delivered_pkts,
            total_dropped_packets=total_dropped_pkts,
            slice_diagnostics=granular_diags,
        )

        next_network_state = NetworkState(
            run_id=None,
            step=self.current_step,
            sim_time_sec=round(self.sim_time_sec, 4),
            total_radio_capacity=self.config.total_radio_capacity,
            total_compute_capacity=self.config.total_compute_capacity,
            slice_states=slice_states,
            is_congested=(len(congested_slices) > 0),
            congested_slices=congested_slices,
            scenario_id=self.config.scenario_id,
            seed=self.config.seed,
        )

        return next_network_state, step_diag.to_interface_diagnostics()
