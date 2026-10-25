"""
SLA Guardian - Recorded Trace Replay Traffic Source
Parses and deterministically replays real network traffic traces in CSV, JSONL, and PCAP formats.
Preserves relative arrival timing, derives per-step packet arrivals, and tracks unclassified traffic.
"""

import os
import csv
import json
import struct
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Union
import numpy as np

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

logger = logging.getLogger("sla_guardian.traffic.trace")


# Standard 3GPP 5QI / DSCP to 5G Slice Mapping Table
DEFAULT_QOS_SLICE_MAPPING: Dict[str, SliceId] = {
    # Direct slice identifiers
    "embb": SliceId.EMBB,
    "e_mbb": SliceId.EMBB,
    "urllc": SliceId.URLLC,
    "murllc": SliceId.MURLLC,
    "m_urllc": SliceId.MURLLC,

    # 3GPP 5QI standard values
    "5qi_1": SliceId.URLLC,    # Conversational Voice
    "5qi_2": SliceId.URLLC,    # Conversational Video
    "5qi_3": SliceId.URLLC,    # Real Time Gaming
    "5qi_4": SliceId.EMBB,     # Non-Conversational Video
    "5qi_5": SliceId.URLLC,    # IMS Signalling
    "5qi_6": SliceId.EMBB,     # Video, TCP-based
    "5qi_7": SliceId.EMBB,     # Voice, Video
    "5qi_8": SliceId.EMBB,     # Best Effort / High Priority
    "5qi_9": SliceId.EMBB,     # Default Internet / Video
    "5qi_65": SliceId.URLLC,   # Mission Critical user plane
    "5qi_66": SliceId.URLLC,   # Mission Critical delay sensitive
    "5qi_67": SliceId.URLLC,   # Mission Critical video
    "5qi_69": SliceId.MURLLC,  # Mission Critical delay sensitive
    "5qi_70": SliceId.MURLLC,  # Mission Critical data
    "5qi_75": SliceId.URLLC,   # V2X messaging
    "5qi_79": SliceId.MURLLC,  # Industrial sensors / automation
    "5qi_80": SliceId.MURLLC,  # Low latency eMBB / automation
    "5qi_82": SliceId.URLLC,   # Discrete automation
    "5qi_83": SliceId.MURLLC,  # Process automation
    "5qi_84": SliceId.MURLLC,  # Intelligent transport systems

    # IP DSCP / ToS names and numeric codes
    "dscp_ef": SliceId.URLLC,   # Expedited Forwarding
    "dscp_46": SliceId.URLLC,   # Expedited Forwarding (numeric 46)
    "dscp_af41": SliceId.EMBB,  # Assured Forwarding 41
    "dscp_34": SliceId.EMBB,    # AF41 numeric
    "dscp_af42": SliceId.EMBB,
    "dscp_af43": SliceId.EMBB,
    "dscp_cs6": SliceId.MURLLC, # Network Control
    "dscp_48": SliceId.MURLLC,  # CS6 numeric
    "dscp_cs7": SliceId.MURLLC,
    "dscp_56": SliceId.MURLLC,  # CS7 numeric
    "dscp_be": SliceId.EMBB,    # Best Effort
    "dscp_0": SliceId.EMBB,     # Best Effort (numeric 0)
    "dscp_10": SliceId.MURLLC,  # AF11 numeric
    "dscp_26": SliceId.URLLC,   # AF31 numeric
}


class TraceReplayTrafficSource(TrafficSourceInterface):
    """
    Deterministic trace replay engine for recorded 5G packet traces.
    Loads CSV, JSONL, or PCAP traces, parses packet timestamps and sizes,
    and maps QoS/5QI attributes to canonical slices without payload inspection.
    """

    def __init__(
        self,
        file_path: Union[str, Path],
        config: Optional[RunConfig] = None,
        qos_mapping: Optional[Dict[str, SliceId]] = None,
        replay_speed: float = 1.0,
        loop: bool = False,
        strict_timestamps: bool = True,
    ):
        self.file_path = Path(file_path).resolve()
        self.config = config
        self.qos_mapping = qos_mapping or DEFAULT_QOS_SLICE_MAPPING
        self.replay_speed = max(0.01, float(replay_speed))
        self.loop = loop
        self.strict_timestamps = strict_timestamps

        self._status = TrafficSourceStatus.UNINITIALIZED
        self.raw_records: List[TrafficEvent] = []
        self.unclassified_records: List[TrafficEvent] = []
        self.validation_errors: List[str] = []
        self.data_quality_flags: List[str] = []

        self.current_trace_idx = 0
        self.trace_start_time_sec = 0.0
        self.trace_end_time_sec = 0.0
        self.duration_sec = 0.0
        self.total_records = 0
        self.total_bytes = 0

        # Load and parse file
        self._load_and_parse()

    @property
    def source_type(self) -> TrafficSourceType:
        return TrafficSourceType.TRACE_REPLAY

    @property
    def status(self) -> TrafficSourceStatus:
        return self._status

    def _load_and_parse(self):
        """Dispatches parser based on file suffix."""
        if not self.file_path.exists():
            self._status = TrafficSourceStatus.ERROR
            self.validation_errors.append(f"Trace file does not exist: {self.file_path}")
            return

        suffix = self.file_path.suffix.lower()
        try:
            if suffix in (".csv", ".tsv"):
                self._parse_csv()
            elif suffix in (".jsonl", ".ndjson"):
                self._parse_jsonl()
            elif suffix == ".json":
                self._parse_json()
            elif suffix == ".pcap":
                self._parse_pcap()
            else:
                self._status = TrafficSourceStatus.ERROR
                self.validation_errors.append(f"Unsupported trace format '{suffix}'. Supported: .csv, .jsonl, .json, .pcap")
                return

            self._post_parse_validation()
        except Exception as e:
            self._status = TrafficSourceStatus.ERROR
            self.validation_errors.append(f"Fatal parser error while reading {self.file_path.name}: {e}")
            logger.error(f"Error parsing trace {self.file_path}: {e}", exc_info=True)

    def _classify_slice(self, raw_slice: Optional[str], qos: Optional[str]) -> Optional[SliceId]:
        """Maps slice or QoS fields to canonical SliceId without guessing based on volume."""
        if raw_slice:
            s_clean = str(raw_slice).strip().lower().replace("-", "_")
            if s_clean in self.qos_mapping:
                return self.qos_mapping[s_clean]
            for s in CANONICAL_SLICE_IDS:
                if s.value.lower() == s_clean:
                    return s

        if qos:
            q_clean = str(qos).strip().lower().replace("-", "_").replace(" ", "_")
            if q_clean in self.qos_mapping:
                return self.qos_mapping[q_clean]
            # Try 5qi prefix
            q_5qi = f"5qi_{q_clean}"
            if q_5qi in self.qos_mapping:
                return self.qos_mapping[q_5qi]
            q_dscp = f"dscp_{q_clean}"
            if q_dscp in self.qos_mapping:
                return self.qos_mapping[q_dscp]

        return None

    def _parse_csv(self):
        """Parses CSV/TSV trace files."""
        delimiter = "\t" if self.file_path.suffix.lower() == ".tsv" else ","
        with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            if not reader.fieldnames:
                self.validation_errors.append("Empty CSV header or missing columns.")
                return

            # Normalize header lookup
            headers = {k.strip().lower().replace(" ", "_"): k for k in reader.fieldnames if k}

            col_ts = headers.get("timestamp") or headers.get("time") or headers.get("ts") or headers.get("arrival_time") or headers.get("frame.time_epoch")
            col_size = headers.get("size_bytes") or headers.get("bytes") or headers.get("length") or headers.get("packet_size") or headers.get("frame.len")
            col_slice = headers.get("slice_id") or headers.get("slice") or headers.get("slice_type")
            col_qos = headers.get("qos_label") or headers.get("5qi") or headers.get("qfi") or headers.get("dscp") or headers.get("traffic_class")
            col_flow = headers.get("flow_id") or headers.get("stream_id") or headers.get("flow")
            col_ue = headers.get("ue_id") or headers.get("device_id")
            col_dir = headers.get("direction") or headers.get("dir")
            col_lat = headers.get("latency_ms") or headers.get("delay_ms")
            col_pdr = headers.get("pdr") or headers.get("delivery_ratio")

            if not col_ts or not col_size:
                self.validation_errors.append(f"Missing required columns in CSV. Found: {list(headers.keys())}. Required: timestamp, size_bytes")
                return

            row_num = 1
            for row in reader:
                row_num += 1
                try:
                    ts_val = float(row[col_ts])
                    size_val = int(float(row[col_size]))
                except (ValueError, TypeError):
                    self.validation_errors.append(f"Row {row_num}: Invalid timestamp or size_bytes: {row}")
                    continue

                if size_val <= 0 or size_val > 65535:
                    self.validation_errors.append(f"Row {row_num}: Packet size {size_val} out of valid range (1..65535).")
                    continue

                raw_s = row.get(col_slice) if col_slice else None
                raw_q = row.get(col_qos) if col_qos else None
                slice_id = self._classify_slice(raw_s, raw_q)

                lat_val = float(row[col_lat]) if col_lat and row.get(col_lat) else None
                pdr_val = float(row[col_pdr]) if col_pdr and row.get(col_pdr) else None

                event = TrafficEvent(
                    packet_id=row_num - 1,
                    timestamp_sec=ts_val,
                    size_bytes=size_val,
                    slice_id=slice_id,
                    flow_id=row.get(col_flow) if col_flow else None,
                    ue_id=row.get(col_ue) if col_ue else None,
                    direction=row.get(col_dir, "downlink") if col_dir else "downlink",
                    qos_label=raw_q or (slice_id.value if slice_id else None),
                    source_measured_latency_ms=lat_val,
                    source_measured_pdr=pdr_val,
                )
                self.raw_records.append(event)
                if slice_id is None:
                    self.unclassified_records.append(event)

    def _parse_jsonl(self):
        """Parses newline-delimited JSON (JSONL)."""
        line_num = 0
        with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line_num += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception as e:
                    self.validation_errors.append(f"Line {line_num}: Malformed JSON record: {e}")
                    continue

                ts = obj.get("timestamp") or obj.get("timestamp_sec") or obj.get("time") or obj.get("ts")
                size = obj.get("size_bytes") or obj.get("bytes") or obj.get("length")
                if ts is None or size is None:
                    self.validation_errors.append(f"Line {line_num}: Missing timestamp or size_bytes.")
                    continue

                try:
                    ts_val = float(ts)
                    size_val = int(size)
                except (ValueError, TypeError):
                    self.validation_errors.append(f"Line {line_num}: Non-numeric timestamp or size.")
                    continue

                if size_val <= 0 or size_val > 65535:
                    self.validation_errors.append(f"Line {line_num}: Invalid size {size_val}.")
                    continue

                raw_s = obj.get("slice_id") or obj.get("slice")
                raw_q = obj.get("qos_label") or obj.get("5qi") or obj.get("dscp")
                slice_id = self._classify_slice(raw_s, raw_q)

                event = TrafficEvent(
                    packet_id=line_num,
                    timestamp_sec=ts_val,
                    size_bytes=size_val,
                    slice_id=slice_id,
                    flow_id=obj.get("flow_id"),
                    ue_id=obj.get("ue_id"),
                    direction=obj.get("direction", "downlink"),
                    qos_label=raw_q or (slice_id.value if slice_id else None),
                    source_measured_latency_ms=obj.get("latency_ms"),
                    source_measured_pdr=obj.get("pdr"),
                )
                self.raw_records.append(event)
                if slice_id is None:
                    self.unclassified_records.append(event)

    def _parse_json(self):
        """Parses array-based JSON traces."""
        with open(self.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        records = data if isinstance(data, list) else data.get("records", [])
        if not records:
            self.validation_errors.append("JSON file does not contain a records array.")
            return

        for idx, obj in enumerate(records):
            ts = obj.get("timestamp") or obj.get("timestamp_sec") or obj.get("time")
            size = obj.get("size_bytes") or obj.get("bytes") or obj.get("length")
            if ts is None or size is None:
                continue
            ts_val = float(ts)
            size_val = int(size)
            raw_s = obj.get("slice_id") or obj.get("slice")
            raw_q = obj.get("qos_label") or obj.get("5qi")
            slice_id = self._classify_slice(raw_s, raw_q)

            event = TrafficEvent(
                packet_id=idx + 1,
                timestamp_sec=ts_val,
                size_bytes=size_val,
                slice_id=slice_id,
                flow_id=obj.get("flow_id"),
                ue_id=obj.get("ue_id"),
                direction=obj.get("direction", "downlink"),
                qos_label=raw_q or (slice_id.value if slice_id else None),
                source_measured_latency_ms=obj.get("latency_ms"),
                source_measured_pdr=obj.get("pdr"),
            )
            self.raw_records.append(event)
            if slice_id is None:
                self.unclassified_records.append(event)

    def _parse_pcap(self):
        """
        Pure-Python binary PCAP parser using standard struct module.
        Zero external dependencies, parses classical libpcap format headers.
        """
        with open(self.file_path, "rb") as f:
            global_header = f.read(24)
            if len(global_header) < 24:
                self.validation_errors.append("Invalid PCAP: file shorter than 24 bytes.")
                return

            magic = struct.unpack("<I", global_header[:4])[0]
            if magic == 0xA1B2C3D4:
                endian = "<"
                nano = False
            elif magic == 0xD4C3B2A1:
                endian = ">"
                nano = False
            elif magic == 0xA1B23C4D:
                endian = "<"
                nano = True
            elif magic == 0x4D3CB2A1:
                endian = ">"
                nano = True
            else:
                self.validation_errors.append(f"Unrecognized PCAP magic number: 0x{magic:08x}")
                return

            pkt_idx = 0
            while True:
                hdr = f.read(16)
                if len(hdr) < 16:
                    break
                ts_sec, ts_subsec, incl_len, orig_len = struct.unpack(f"{endian}IIII", hdr)
                payload = f.read(incl_len)
                if len(payload) < incl_len:
                    break

                pkt_idx += 1
                subsec_factor = 1e9 if nano else 1e6
                timestamp = float(ts_sec) + float(ts_subsec) / subsec_factor

                # Extract QoS/DSCP from IPv4 header if payload available
                dscp_val = None
                if len(payload) >= 15:
                    # Check for IPv4 header after standard Ethernet (14 bytes)
                    ip_hdr = payload[14:34]
                    if len(ip_hdr) >= 2 and (ip_hdr[0] >> 4) == 4:
                        tos = ip_hdr[1]
                        dscp = tos >> 2
                        dscp_val = f"dscp_{dscp}"

                slice_id = self._classify_slice(None, dscp_val)

                event = TrafficEvent(
                    packet_id=pkt_idx,
                    timestamp_sec=timestamp,
                    size_bytes=int(orig_len),
                    slice_id=slice_id,
                    flow_id=f"pcap_pkt_{pkt_idx}",
                    direction="downlink",
                    qos_label=dscp_val or "pcap_unclassified",
                )
                self.raw_records.append(event)
                if slice_id is None:
                    self.unclassified_records.append(event)

    def _post_parse_validation(self):
        """Sorts records, normalizes timestamps, and builds quality metrics."""
        if not self.raw_records:
            self._status = TrafficSourceStatus.ERROR
            self.validation_errors.append("Trace file contains zero valid packet records.")
            return

        # Sort records chronologically
        self.raw_records.sort(key=lambda e: e.timestamp_sec)

        # Check for non-monotonic timestamps before normalization
        first_ts = self.raw_records[0].timestamp_sec
        last_ts = self.raw_records[-1].timestamp_sec

        # Normalize timestamps relative to start of trace (t = 0.0s)
        for e in self.raw_records:
            e.timestamp_sec = round(e.timestamp_sec - first_ts, 6)

        self.trace_start_time_sec = 0.0
        self.trace_end_time_sec = self.raw_records[-1].timestamp_sec
        self.duration_sec = max(0.001, self.trace_end_time_sec - self.trace_start_time_sec)
        self.total_records = len(self.raw_records)
        self.total_bytes = sum(e.size_bytes for e in self.raw_records)

        # Quality flags
        if self.unclassified_records:
            cov = 100.0 * (1.0 - len(self.unclassified_records) / self.total_records)
            self.data_quality_flags.append(f"UNCLASSIFIED_FLOWS_PRESENT ({len(self.unclassified_records)} pkts, {cov:.1f}% coverage)")
        else:
            self.data_quality_flags.append("100%_CLASSIFIED_COVERAGE")

        if self.duration_sec < 1.0:
            self.data_quality_flags.append("SHORT_TRACE_DURATION (<1.0s)")

        self._status = TrafficSourceStatus.READY
        logger.info(
            f"Loaded trace '{self.file_path.name}': {self.total_records} packets, "
            f"duration {self.duration_sec:.2f}s, unclassified {len(self.unclassified_records)}"
        )

    def get_metadata(self) -> TrafficSourceMetadata:
        slice_counts = {s.value: 0 for s in CANONICAL_SLICE_IDS}
        for e in self.raw_records:
            if e.slice_id:
                slice_counts[e.slice_id.value] += 1

        unclass = len(self.unclassified_records)
        cov = 100.0 * (1.0 - (unclass / max(1, self.total_records)))

        measured = [
            "packet_timestamps",
            "packet_sizes_bytes",
            "offered_packet_rates",
            "offered_byte_rates",
        ]
        if any(e.source_measured_latency_ms is not None for e in self.raw_records):
            measured.append("source_measured_latency_ms")
        if any(e.source_measured_pdr is not None for e in self.raw_records):
            measured.append("source_measured_pdr")

        return TrafficSourceMetadata(
            source_type=self.source_type,
            source_name=self.file_path.name,
            status=self.status,
            description=f"Recorded network packet trace from {self.file_path.name}.",
            total_records=self.total_records,
            duration_sec=self.duration_sec,
            time_range_sec=(self.trace_start_time_sec, self.trace_end_time_sec),
            slice_distribution=slice_counts,
            unclassified_count=unclass,
            classification_coverage_pct=round(cov, 2),
            sample_rate_hz=round(self.total_records / max(0.001, self.duration_sec), 1),
            data_quality_flags=self.data_quality_flags,
            measured_metrics_available=measured,
            simulated_metrics_required=[
                "throughput_mbps",
                "p95_latency_ms",
                "packet_delivery_ratio",
                "sla_status",
            ],
        )

    def validate(self) -> Tuple[bool, List[str]]:
        is_valid = (self._status != TrafficSourceStatus.ERROR) and (self.total_records > 0)
        messages = list(self.validation_errors)
        if is_valid:
            cov = self.get_metadata().classification_coverage_pct
            messages.append(
                f"Valid trace '{self.file_path.name}': {self.total_records} packets, "
                f"{self.duration_sec:.2f}s duration, {cov:.1f}% slice classification coverage."
            )
        return is_valid, messages

    def generate_step_arrivals(
        self,
        step: int,
        sim_time_sec: float,
        step_duration_sec: float,
    ) -> TrafficStepArrivals:
        """
        Derives discrete packet arrivals for the interval [sim_time_sec, sim_time_sec + step_duration_sec).
        Applies replay speed scaling and constructs queue-ready Packet instances.
        """
        if self._status == TrafficSourceStatus.ERROR or not self.raw_records:
            return TrafficStepArrivals(
                step=step,
                sim_time_sec=sim_time_sec,
                step_duration_sec=step_duration_sec,
                is_end_of_trace=True,
            )

        effective_step_duration = step_duration_sec * self.replay_speed
        window_start = sim_time_sec * self.replay_speed
        window_end = window_start + effective_step_duration

        classified_pkts: Dict[SliceId, List[Packet]] = {s: [] for s in CANONICAL_SLICE_IDS}
        unclass_events: List[TrafficEvent] = []
        offered_bytes: Dict[SliceId, int] = {s: 0 for s in CANONICAL_SLICE_IDS}
        unclass_b = 0

        # Retrieve SLA thresholds for deadlines
        sla_thresholds = self.config.sla_thresholds if self.config else None

        is_end = False

        # Advance trace pointer
        while self.current_trace_idx < self.total_records:
            event = self.raw_records[self.current_trace_idx]
            if event.timestamp_sec < window_end:
                # Arrived in this simulation window
                self.current_trace_idx += 1

                # Calculate arrival time mapped into current simulation step
                rel_offset = (event.timestamp_sec - window_start) / max(1e-6, self.replay_speed)
                sub_arrival = sim_time_sec + max(0.0, min(step_duration_sec, rel_offset))

                if event.slice_id is not None:
                    s_id = event.slice_id
                    # Deadline derived from SLA or default 50ms
                    max_lat_ms = 25.0
                    if sla_thresholds and s_id in sla_thresholds:
                        max_lat_ms = sla_thresholds[s_id].max_latency_ms
                    deadline_sec = sub_arrival + (max_lat_ms * 1.5) / 1000.0

                    pkt = Packet(
                        packet_id=event.packet_id,
                        slice_id=s_id,
                        size_bytes=event.size_bytes,
                        arrival_time=sub_arrival,
                        deadline_time=deadline_sec,
                        radio_enter_time=sub_arrival,
                        status="QUEUED_RADIO",
                    )
                    classified_pkts[s_id].append(pkt)
                    offered_bytes[s_id] += event.size_bytes
                else:
                    unclass_events.append(event)
                    unclass_b += event.size_bytes
            else:
                # Event belongs to a future step
                break

        # Check for end of trace
        if self.current_trace_idx >= self.total_records:
            if self.loop:
                # Rewind for continuous looping if explicitly requested
                self.current_trace_idx = 0
                is_end = False
            else:
                is_end = True
                self._status = TrafficSourceStatus.END_OF_TRACE

        offered_mbps = {
            s: (offered_bytes[s] * 8.0) / (1e6 * max(1e-6, step_duration_sec))
            for s in CANONICAL_SLICE_IDS
        }
        unclass_mbps = (unclass_b * 8.0) / (1e6 * max(1e-6, step_duration_sec))

        if not is_end:
            self._status = TrafficSourceStatus.STREAMING

        return TrafficStepArrivals(
            step=step,
            sim_time_sec=sim_time_sec,
            step_duration_sec=step_duration_sec,
            packets=classified_pkts,
            unclassified_events=unclass_events,
            offered_bytes=offered_bytes,
            offered_mbps=offered_mbps,
            unclassified_bytes=unclass_b,
            unclassified_mbps=unclass_mbps,
            is_end_of_trace=is_end,
            diagnostics={
                "trace_file": self.file_path.name,
                "current_trace_index": self.current_trace_idx,
                "total_records": self.total_records,
                "replay_speed": self.replay_speed,
                "unclassified_count": len(unclass_events),
            },
        )

    def get_diagnostics(self) -> Dict[str, Any]:
        """Returns runtime diagnostics for source health and event tracking."""
        return {
            "source_type": self.source_type.value,
            "status": self._status.value,
            "current_trace_idx": self.current_trace_idx,
            "total_records": self.total_records,
            "unclassified_records_count": len(self.unclassified_records),
            "validation_errors": list(self.validation_errors),
            "data_quality_flags": list(self.data_quality_flags),
            "duration_sec": self.duration_sec,
        }

    def reset(self, seed: Optional[int] = None, start_time_sec: float = 0.0):
        """Resets replay index to start_time_sec for deterministic replay across competing policies."""
        self.current_trace_idx = 0
        if start_time_sec > 0.0:
            while self.current_trace_idx < self.total_records:
                if self.raw_records[self.current_trace_idx].timestamp_sec >= start_time_sec:
                    break
                self.current_trace_idx += 1
        self._status = TrafficSourceStatus.READY

    def close(self):
        self._status = TrafficSourceStatus.PAUSED

