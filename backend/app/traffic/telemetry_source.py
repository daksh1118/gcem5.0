"""
SLA Guardian - Live Telemetry Traffic Source
Read-only adapter for streaming live telemetry from authorized 5G Core (Open5GS),
Prometheus exporters, or RAN metrics endpoints into the simulation pipeline.
Enforces strict read-only operation, stale-data detection, and unconfigured states.
"""

import os
import time
import json
import logging
import socket
from typing import Dict, List, Optional, Any, Tuple
import urllib.request
import urllib.error

from ..schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig
from ..simulator.queues import Packet
from .interface import (
    TrafficSourceInterface,
    TrafficSourceType,
    TrafficSourceStatus,
    TrafficSourceMetadata,
    TrafficStepArrivals,
    TrafficEvent,
)

logger = logging.getLogger("sla_guardian.traffic.telemetry")


class LiveTelemetryTrafficSource(TrafficSourceInterface):
    """
    Read-only adapter ingesting metrics from Prometheus, Open5GS, or custom RAN telemetry exporters.
    Maintains a rolling observation window and distinguishes measured zero from unavailable/stale data.
    """

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        config: Optional[RunConfig] = None,
        poll_interval_sec: float = 0.10,
        timeout_sec: float = 2.0,
        stale_threshold_sec: float = 2.0,
        max_retries: int = 3,
        exporter_type: str = "generic_json",  # "generic_json", "prometheus", "open5gs"
    ):
        self.endpoint_url = endpoint_url or os.getenv("TELEMETRY_ENDPOINT_URL")
        self.auth_token = auth_token or os.getenv("TELEMETRY_AUTH_TOKEN")
        self.config = config
        self.poll_interval_sec = max(0.01, float(poll_interval_sec))
        self.timeout_sec = max(0.1, float(timeout_sec))
        self.stale_threshold_sec = max(0.01, float(stale_threshold_sec))
        self.max_retries = max(1, int(max_retries))
        self.exporter_type = exporter_type

        self._status = TrafficSourceStatus.UNCONFIGURED
        self.last_poll_time: Optional[float] = None
        self.last_successful_fetch_time: Optional[float] = None
        self.rolling_observations: List[Dict[str, Any]] = []
        self.max_history = 100

        self.last_known_demand_mbps: Dict[SliceId, Optional[float]] = {s: None for s in CANONICAL_SLICE_IDS}
        self.last_known_core_metrics: Dict[str, Any] = {}
        self.data_quality_flags: List[str] = []
        self.consecutive_failures = 0
        self.packet_counter = 0

        # Initial connection attempt or unconfigured status
        if not self.endpoint_url:
            self._status = TrafficSourceStatus.UNCONFIGURED
            self.data_quality_flags.append("UNCONFIGURED_ENDPOINT")
        else:
            self._status = TrafficSourceStatus.READY
            self._poll_telemetry()

    @property
    def source_type(self) -> TrafficSourceType:
        return TrafficSourceType.LIVE_TELEMETRY

    @property
    def status(self) -> TrafficSourceStatus:
        return self._status

    def _poll_telemetry(self) -> Optional[Dict[str, Any]]:
        """Executes a single read-only HTTP GET request to the authorized metrics endpoint."""
        if not self.endpoint_url:
            self._status = TrafficSourceStatus.DISCONNECTED
            return None

        self.last_poll_time = time.time()
        headers = {
            "Accept": "application/json",
            "User-Agent": "SLAGuardian-TelemetryAdapter/0.2.0 (Read-Only)",
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        req = urllib.request.Request(self.endpoint_url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as response:
                if response.status == 200:
                    raw_body = response.read().decode("utf-8", errors="replace")
                    payload = json.loads(raw_body)
                    self.last_successful_fetch_time = time.time()
                    self.consecutive_failures = 0
                    self._process_payload(payload)
                    self._status = TrafficSourceStatus.STREAMING
                    return payload
                else:
                    self.consecutive_failures += 1
                    self._status = TrafficSourceStatus.DEGRADED
                    logger.warning(f"Telemetry endpoint returned HTTP {response.status}")
        except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
            self.consecutive_failures += 1
            self._status = TrafficSourceStatus.DISCONNECTED
            logger.debug(f"Telemetry poll error or timeout ({self.endpoint_url}): {e}")
        except Exception as e:
            self.consecutive_failures += 1
            self._status = TrafficSourceStatus.ERROR
            logger.error(f"Error parsing live telemetry payload: {e}")

        return None

    def _process_payload(self, payload: Dict[str, Any]):
        """
        Parses live metrics according to exporter type.
        Separates Core network metrics from Radio-level telemetry.
        """
        now = time.time()
        record = {
            "fetch_timestamp": now,
            "raw_payload": payload,
            "slice_demand_mbps": {},
            "core_metrics": {},
        }

        if self.exporter_type == "open5gs":
            # Open5GS metrics format: Core UPF session and byte counters
            # Note: Radio telemetry (PRB utilization, CQI) is NOT emitted by Open5GS core
            sessions = payload.get("active_sessions", 0)
            record["core_metrics"]["open5gs_sessions"] = sessions
            subscribers = payload.get("subscribers", [])
            for s in CANONICAL_SLICE_IDS:
                # Map DNN/S-NSSAI if present
                rate = payload.get("slice_rates_mbps", {}).get(s.value)
                self.last_known_demand_mbps[s] = float(rate) if rate is not None else 0.0
                record["slice_demand_mbps"][s.value] = self.last_known_demand_mbps[s]

        elif self.exporter_type == "prometheus":
            # Prometheus /api/v1/query vector result
            results = payload.get("data", {}).get("result", [])
            for res in results:
                metric_name = res.get("metric", {}).get("__name__", "")
                slice_label = res.get("metric", {}).get("slice")
                val = res.get("value", [None, "0"])[1]
                try:
                    num_val = float(val)
                except ValueError:
                    num_val = 0.0

                if "upf_bytes" in metric_name:
                    record["core_metrics"][metric_name] = num_val
                elif slice_label:
                    for s in CANONICAL_SLICE_IDS:
                        if s.value.lower() == slice_label.lower():
                            # Normalize bytes/sec to Mbps
                            mbps = (num_val * 8.0) / 1e6
                            self.last_known_demand_mbps[s] = mbps
                            record["slice_demand_mbps"][s.value] = mbps

        else:
            # Generic JSON exporter schema
            slices_data = payload.get("slices", {})
            for s in CANONICAL_SLICE_IDS:
                s_key = s.value
                s_info = slices_data.get(s_key, {})
                if isinstance(s_info, (int, float)):
                    mbps = float(s_info)
                elif isinstance(s_info, dict):
                    mbps = s_info.get("offered_demand_mbps") or s_info.get("throughput_mbps")
                else:
                    mbps = None
                self.last_known_demand_mbps[s] = float(mbps) if mbps is not None else None
                record["slice_demand_mbps"][s_key] = self.last_known_demand_mbps[s]

            # Core network metrics separated
            record["core_metrics"] = payload.get("core_network", {})

        self.rolling_observations.append(record)
        if len(self.rolling_observations) > self.max_history:
            self.rolling_observations.pop(0)

    def is_stale(self, current_time: Optional[float] = None) -> bool:
        """Returns True if the most recent successful fetch exceeds stale_threshold_sec."""
        if not self.last_successful_fetch_time:
            return True
        now = current_time if current_time is not None else time.time()
        return (now - self.last_successful_fetch_time) > self.stale_threshold_sec

    def poll_telemetry(self) -> bool:
        """Public alias to poll telemetry, returning True if successful."""
        res = self._poll_telemetry()
        return res is not None

    def get_metadata(self) -> TrafficSourceMetadata:
        flags = list(self.data_quality_flags)
        if not self.endpoint_url:
            flags.append("NO_ENDPOINT_CONFIGURED")
        elif self.is_stale():
            flags.append("STALE_TELEMETRY_DATA")

        avail_metrics = ["core_session_info"]
        if self.rolling_observations:
            avail_metrics.extend(["measured_slice_demand_mbps", "fetch_timestamps"])

        # Construct status description
        if not self.endpoint_url:
            desc = "Live Telemetry Adapter: Disconnected / Unconfigured. Configure TELEMETRY_ENDPOINT_URL."
        elif self.is_stale():
            desc = f"Live Telemetry Adapter: Stale data from {self.endpoint_url} (last fetch > {self.stale_threshold_sec}s ago)."
        else:
            desc = f"Live Telemetry Adapter: Streaming live telemetry from {self.endpoint_url}."

        return TrafficSourceMetadata(
            source_type=self.source_type,
            source_name=f"Live Telemetry ({self.exporter_type})",
            status=self.status,
            description=desc,
            total_records=len(self.rolling_observations),
            duration_sec=float(len(self.rolling_observations) * self.poll_interval_sec),
            slice_distribution={s.value: int(self.last_known_demand_mbps[s] or 0.0) for s in CANONICAL_SLICE_IDS},
            unclassified_count=0,
            classification_coverage_pct=100.0,
            data_quality_flags=flags,
            measured_metrics_available=avail_metrics,
            simulated_metrics_required=["throughput_mbps", "p95_latency_ms", "packet_delivery_ratio", "sla_status"],
        )

    def validate(self) -> Tuple[bool, List[str]]:
        if not self.endpoint_url:
            return False, ["No live telemetry endpoint configured. Provide TELEMETRY_ENDPOINT_URL."]
        if self.consecutive_failures > 3:
            return False, [f"Live endpoint {self.endpoint_url} unreachable ({self.consecutive_failures} failures)."]
        return True, [f"Live endpoint {self.endpoint_url} is active ({self.exporter_type})."]

    def generate_step_arrivals(
        self,
        step: int,
        sim_time_sec: float,
        step_duration_sec: float,
    ) -> TrafficStepArrivals:
        """
        Polls telemetry endpoint and converts measured demand into discrete simulated packet arrivals.
        """
        # Periodic poll if interval has elapsed (with 2s backoff on failures)
        poll_interval = self.poll_interval_sec if self.consecutive_failures < 3 else max(2.0, self.poll_interval_sec)
        if self.last_poll_time is None or (time.time() - self.last_poll_time) >= poll_interval:
            self._poll_telemetry()

        classified_pkts: Dict[SliceId, List[Packet]] = {s: [] for s in CANONICAL_SLICE_IDS}
        offered_bytes: Dict[SliceId, int] = {s: 0 for s in CANONICAL_SLICE_IDS}
        offered_mbps: Dict[SliceId, float] = {s: 0.0 for s in CANONICAL_SLICE_IDS}

        sla_thresholds = self.config.sla_thresholds if self.config else None

        # Packet sizes by slice
        packet_sizes = {
            SliceId.EMBB: 1400,
            SliceId.URLLC: 250,
            SliceId.MURLLC: 500,
        }

        for s in CANONICAL_SLICE_IDS:
            demand = self.last_known_demand_mbps[s]
            if demand is not None and demand > 0.0:
                step_bytes = int((demand * 1e6 * step_duration_sec) / 8.0)
                pkt_size = packet_sizes[s]
                num_pkts = max(1, step_bytes // pkt_size)
                max_lat_ms = 25.0
                if sla_thresholds and s in sla_thresholds:
                    max_lat_ms = sla_thresholds[s].max_latency_ms
                deadline_sec = sim_time_sec + (max_lat_ms * 1.5) / 1000.0

                for _ in range(num_pkts):
                    self.packet_counter += 1
                    pkt = Packet(
                        packet_id=self.packet_counter,
                        slice_id=s,
                        size_bytes=pkt_size,
                        arrival_time=sim_time_sec,
                        deadline_time=deadline_sec,
                        radio_enter_time=sim_time_sec,
                        status="QUEUED_RADIO",
                    )
                    classified_pkts[s].append(pkt)

                offered_bytes[s] = num_pkts * pkt_size
                offered_mbps[s] = (offered_bytes[s] * 8.0) / (1e6 * max(1e-6, step_duration_sec))

        return TrafficStepArrivals(
            step=step,
            sim_time_sec=sim_time_sec,
            step_duration_sec=step_duration_sec,
            packets=classified_pkts,
            unclassified_events=[],
            offered_bytes=offered_bytes,
            offered_mbps=offered_mbps,
            unclassified_bytes=0,
            unclassified_mbps=0.0,
            is_end_of_trace=False,
            diagnostics={
                "endpoint_url": self.endpoint_url or "UNCONFIGURED",
                "is_stale": self.is_stale(),
                "exporter_type": self.exporter_type,
                "consecutive_failures": self.consecutive_failures,
            },
        )

    def reset(self, seed: Optional[int] = None, start_time_sec: float = 0.0):
        self.packet_counter = 0
        self.rolling_observations.clear()
        if self.endpoint_url:
            self._poll_telemetry()

    def close(self):
        self._status = TrafficSourceStatus.DISCONNECTED
