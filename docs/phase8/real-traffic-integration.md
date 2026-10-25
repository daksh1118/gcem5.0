# SLA Guardian — Real Traffic Trace Replay & Live Telemetry Integration

## Executive Summary

SLA Guardian has transitioned from relying exclusively on synthetic traffic generation profiles to a **pluggable, input-driven traffic architecture**. The network simulator now consumes real observed network traces (CSV, JSONL, binary PCAP) and connects to read-only live telemetry endpoints (Prometheus, Open5GS, generic JSON).

All four resource-allocation policies—**Static Baseline**, **Adaptive Demand Heuristic**, **Frozen PPO Agent**, and **Candidate PPO Agent**—can now be evaluated on identical packet arrival sequences under a synchronized 100 ms macro-control interval.

Crucially:
- **No silent fallbacks:** If a requested trace or telemetry endpoint fails, the system enters an explicit `ERROR` or `DISCONNECTED` state rather than secretly generating synthetic traffic.
- **Measured vs Simulated separation:** Source-offered demand is strictly separated from simulator-modeled outcomes (queues, radio capacity, drops, SLA violations).
- **Checkpoints preserved:** Existing trained models (`models/agent.zip`, `models/candidate_agent.zip`) and Phase 8 historical benchmark artifacts remain intact.

---

## 1. Pluggable Traffic Source Architecture

The traffic subsystem is built upon `TrafficSourceInterface` defined in `backend/app/traffic/interface.py`:

```
               +--------------------------------------+
               |       TrafficSourceInterface         |
               +--------------------------------------+
                 /                |                 \
                /                 |                  \
+-------------------------+  +------------------+  +--------------------------+
| TraceReplayTrafficSource |  | LiveTelemetry    |  | SyntheticTestTraffic     |
| (CSV, JSONL, PCAP)      |  | TrafficSource    |  | Source (TrafficGen)      |
+-------------------------+  +------------------+  +--------------------------+
                 \                |                  /
                  \               |                 /
               +--------------------------------------+
               | FallbackNetworkSimulator (10 ms tick)|
               +--------------------------------------+
                                  |
               +--------------------------------------+
               | MacroControlAdapter (100 ms control) |
               +--------------------------------------+
                                  |
               +--------------------------------------+
               | SafetyShield -> Policies -> Metrics  |
               +--------------------------------------+
```

### Core Interface Contract

| Method | Signature | Description |
|---|---|---|
| `initialize()` | `() -> bool` | Pre-loads trace records or initializes telemetry connection. |
| `validate()` | `() -> Tuple[bool, List[str]]` | Audits format, timestamp monotonicity, field completeness, and slice coverage. |
| `generate_step_arrivals()` | `(step, t_sim, dt) -> TrafficStepArrivals` | Returns packets and bytes arriving during simulation interval `[t_sim, t_sim + dt)`. |
| `is_finished()` | `() -> bool` | Indicates when all trace records have been replayed. |
| `reset(start_time)` | `(start_time_sec=0.0) -> None` | Resets replay cursor to start timestamp without corrupting source data. |
| `get_metadata()` | `() -> TrafficSourceMetadata` | Returns format, record count, duration, slice distribution, and coverage. |
| `get_diagnostics()` | `() -> Dict[str, Any]` | Returns real-time health, buffer fullness, freshness, and unclassified stats. |

---

## 2. Supported Ingestion Formats & Schemas

### 2.1 CSV Format

Standard comma-delimited text with header row.

#### Example Schema (`data/traces/sample_5g_multi_slice_trace.csv`)
```csv
timestamp,size_bytes,flow_id,direction,slice_id,5qi,dscp
0.0050,1420,flow_embb_01,DL,eMBB,9,0
0.0120,240,flow_urllc_01,DL,URLLC,82,46
0.0150,120,flow_murllc_01,DL,mURLLC,84,10
0.0220,1380,flow_embb_02,DL,eMBB,9,0
```

#### Field Specifications:
- `timestamp` (float, required): Relative or absolute time in seconds (e.g. `0.0050`).
- `size_bytes` (integer, required): Total packet length in bytes (64–65535).
- `slice_id` (string, optional): Canonical slice name (`eMBB`, `URLLC`, `mURLLC`).
- `5qi` / `qfi` (integer, optional): 3GPP 5G Quality of Service Identifier.
- `dscp` (integer, optional): Differentiated Services Code Point (0–63).
- `flow_id` / `ue_id` (string, optional): Anonymized identifier for flow correlation.
- `direction` (string, optional): `DL` (Downlink) or `UL` (Uplink).

### 2.2 JSONL / NDJSON Format

Newline-delimited JSON objects allowing nested source-measured QoS data.

#### Example Schema (`data/traces/sample_5g_trace.jsonl`)
```json
{"timestamp": 0.0042, "size_bytes": 1420, "ue_id": "ue_anon_001", "slice_id": "eMBB", "5qi": 9, "measured_rtt_ms": 14.2}
{"timestamp": 0.0118, "size_bytes": 220, "ue_id": "ue_anon_002", "slice_id": "URLLC", "5qi": 82, "measured_rtt_ms": 2.1}
{"timestamp": 0.0145, "size_bytes": 110, "ue_id": "ue_anon_003", "slice_id": "mURLLC", "5qi": 84, "measured_rtt_ms": 1.2}
```

### 2.3 Binary PCAP Format

SLA Guardian includes a **pure-Python binary PCAP parser** built directly with `struct.unpack`, requiring zero external C-dependencies or third-party packet libraries.

- **Global Header (24 bytes):** Validates magic number `0xa1b2c3d4` (microseconds) or `0xa1b23c4d` (nanoseconds) and byte order.
- **Packet Header (16 bytes):** Extracts `ts_sec`, `ts_usec`, `incl_len`, `orig_len`.
- **Link Layer Decoding:** Supports Ethernet (14-byte offset) and Linux Cooked SLL (16-byte offset).
- **IP Header Parsing:** Decodes IPv4 Type of Service (ToS) byte, extracting bits `>> 2` to obtain the 6-bit DSCP field.

---

## 3. Traffic Classification & QoS Mapping

When a trace lacks explicit `slice_id` strings, SLA Guardian maps standardized network QoS labels to 5G network slices according to 3GPP TS 23.501:

| Standard | Label / Value | Mapped Slice | Rationale / Traffic Type |
|---|---|---|---|
| **3GPP 5QI** | 1, 2, 3, 4, 65, 66, 67 | `eMBB` | Conversational voice, live video stream, buffered video |
| **3GPP 5QI** | 82, 83, 84, 85 | `URLLC` | Discrete automation, high-precision control, remote driving |
| **3GPP 5QI** | 80, 86 | `mURLLC` | Ultra-low latency mission-critical machine vision / telemetry |
| **3GPP 5QI** | 9, 6, 7, 8 | `eMBB` | Best-effort internet, default bearer |
| **IP DSCP** | 46 (EF - Expedited Forwarding) | `URLLC` | Low loss, low latency, low jitter |
| **IP DSCP** | 10, 12, 14 (AF11, AF12, AF13) | `mURLLC` | Mission-critical prioritized telemetry |
| **IP DSCP** | 0 (CS0 / Best Effort), 26, 34 | `eMBB` | High throughput bulk data transfer |

### Strict Classification Rules:
1. **No Volume-Based Heuristics:** The system will **never** guess that small packets are URLLC or large packets are eMBB based on packet size or burst volume alone.
2. **Unclassified Isolation:** Packets missing both slice tags and recognized 5QI/DSCP labels are stored in `unclassified` buckets and reported in trace diagnostics. They are not fabricated or assigned to critical slices.
3. **Explicit Override:** Users can supply a custom JSON dictionary via `POST /api/traffic/validate-trace` or the web dashboard to map custom DSCP/VLAN/5QI values to slices.

---

## 4. Live Telemetry Adapter

The `LiveTelemetryTrafficSource` (`backend/app/traffic/telemetry_source.py`) provides a read-only integration layer for pulling live network metrics into the simulation environment.

### Supported Telemetry Connectors:
1. **Prometheus Exporters:** Polls `/api/v1/query` or `/federate` for radio throughput (`node_network_receive_bytes_total`, `gnb_prb_utilization`, `slice_packet_arrivals_total`).
2. **Open5GS Core:** Polls Open5GS WebUI / subscriber status API for active PDU sessions and slice-differentiated byte counters.
3. **Generic JSON Endpoint:** Polls any standard REST service returning per-slice packet/byte telemetry.

### Configuration Environment Variables:
```bash
# Live Telemetry Settings
export TELEMETRY_ENDPOINT_URL="http://192.168.1.50:9090/api/v1/query"
export TELEMETRY_AUTH_TOKEN="Bearer eyJhbGciOi..."
export TELEMETRY_CONNECTOR_TYPE="prometheus"   # "prometheus", "open5gs", or "generic_json"
export TELEMETRY_POLL_INTERVAL_SEC="0.100"    # 100 ms polling cadence
export TELEMETRY_TIMEOUT_SEC="0.500"          # 500 ms connection timeout
export TELEMETRY_STALE_THRESHOLD_SEC="2.0"     # Mark telemetry stale after 2.0s without updates
```

### Safety & Operational Safeguards:
- **Read-Only Ingestion:** The adapter possesses no outbound command endpoints. It cannot issue radio-reconfiguration commands or modify gNodeB/UPF state on a live network.
- **Graceful Stale Handling:** If live updates pause or network latency exceeds the control window, `is_stale()` marks the status `STALE`. It never assumes missing data is zero without documenting the condition.
- **Truthful Status Disclosure:** When `TELEMETRY_ENDPOINT_URL` is omitted, the adapter remains in a clear `UNCONFIGURED` / `DISCONNECTED` state.

> **Truthful Verification Disclosure:**  
> During this development session, the `LiveTelemetryTrafficSource` adapter was verified against local mock HTTP endpoints and sample JSON payloads (`data/traces/sample_live_telemetry_payload.json`). No active physical 5G gNodeB, Open5GS deployment, or production UPF was connected.

---

## 5. Measured vs Simulated Metrics Separation

SLA Guardian explicitly distinguishes what is **measured directly from the input trace** from what is **simulated by the resource-allocation engine**:

| Metric | Category | Source / Formula | Meaning |
|---|---|---|---|
| **Offered Packets / Bytes** | Measured (Source) | Packet counts from CSV / PCAP / Telemetry | Raw network demand arriving at the base station ingress |
| **Offered Throughput (Mbps)** | Measured (Source) | `(bytes * 8) / (dt * 1e6)` | Incoming traffic rate requested by UEs |
| **Radio Capacity (Mbps)** | Simulated (Engine) | `total_radio_mbps * allocation_fraction` | Radio slice throughput limit assigned by policy |
| **Compute Capacity (pkts/s)**| Simulated (Engine) | `total_compute_pps * allocation_fraction` | Edge processing capacity assigned by policy |
| **Delivered Packets** | Simulated (Engine) | Simulator packet transmission outcome | Packets successfully delivered through radio and compute |
| **Delivered Throughput** | Simulated (Engine) | `(delivered_bytes * 8) / (dt * 1e6)` | Realized throughput after queueing and bottlenecks |
| **Packet Drops** | Simulated (Engine) | Buffer overflows + deadline expiry drops | Losses caused by insufficient allocation |
| **PDR (Packet Delivery Ratio)**| Simulated (Engine) | `delivered_packets / offered_packets` | Ratio of delivered packets over simulated interval |
| **P95 Latency** | Simulated (Engine) | Queue waiting time + transmission delay | Total latency experienced inside the simulated slice |
| **SLA Violations** | Simulated (Engine) | Evaluated against target thresholds | Breaches of slice-specific throughput/latency/PDR SLAs |

### Reporting Integrity:
The simulator models queuing delay and drop mechanics based on policy-assigned radio PRBs and compute capacity. It does **not** claim to reflect a production network's actual channel fading or PHY-layer bit errors unless direct telemetry measurements are provided.

---

## 6. Trace-Driven Benchmark Evaluation

To evaluate policy performance under real traffic, run the dedicated benchmark script:

```bash
.\.venv\Scripts\python.exe scripts/phase8/run_trace_benchmark.py
```

### Benchmark Protocol:
- **Traces Evaluated:**
  1. `sample_5g_multi_slice_trace.csv` (10.0s, 2,268 packets, 3 slices)
  2. `sample_5g_trace.jsonl` (8.0s, 1,320 packets, 3 slices + source telemetry)
  3. `sample_5g_trace.pcap` (5.0s, 997 packets, binary PCAP with DSCP tags)
- **Compared Policies:**
  1. `static`: Fixed allocation baseline (eMBB 50%, URLLC 30%, mURLLC 20%)
  2. `heuristic`: Adaptive demand-matching heuristic
  3. `frozen_ppo`: Pre-trained RL policy (`models/agent.zip`, SHA-256: `1d21d58f...`)
  4. `candidate_ppo`: Corrective multi-scenario checkpoint (`models/candidate_agent.zip`, SHA-256: `ec903788...`)
- **Execution:** All 4 policies consume identical packet events in the exact same sequence at 100 ms control intervals.

### Benchmark Summary Results

| Trace | Policy | eMBB Tput (Mbps) | URLLC PDR | mURLLC PDR | Critical Cost | Churn | Shield Corrected |
|---|---|---|---|---|---|---|---|
| **Multi-Slice CSV** | Static Baseline | 0.884 | 100.0% | 100.0% | 0.000 | 0.000 | 0 |
| (10.0s, 2,268 pkts)| Adaptive Heuristic | 0.884 | 100.0% | 100.0% | 0.000 | 0.173 | 0 |
| | Frozen PPO | 0.884 | 100.0% | 100.0% | 0.000 | 0.283 | 0 |
| | **Candidate PPO** | **0.884** | **100.0%** | **100.0%** | **0.000** | **0.180** | **0** |
| **5G JSONL Trace** | Static Baseline | 0.817 | 100.0% | 100.0% | 0.000 | 0.000 | 0 |
| (8.0s, 1,320 pkts) | Adaptive Heuristic | 0.817 | 100.0% | 100.0% | 0.000 | 0.000 | 0 |
| | Frozen PPO | 0.817 | 100.0% | 100.0% | 0.000 | 0.228 | 0 |
| | **Candidate PPO** | **0.817** | **100.0%** | **100.0%** | **0.000** | **0.198** | **0** |
| **Binary PCAP Trace**| Static Baseline | 0.771 | 100.0% | 100.0% | 0.000 | 0.000 | 0 |
| (5.0s, 997 pkts) | Adaptive Heuristic | 0.771 | 100.0% | 100.0% | 0.000 | 0.093 | 0 |
| | Frozen PPO | 0.771 | 100.0% | 100.0% | 0.000 | 0.287 | 0 |
| | **Candidate PPO** | **0.771** | **100.0%** | **100.0%** | **0.000** | **0.170** | **0** |

Artifacts generated:
- `backend/artifacts/phase8/trace_benchmark.json`
- `backend/artifacts/phase8/trace_benchmark.csv`
- `backend/artifacts/phase8/trace_results.md`

---

## 7. Dashboard and REST API Reference

### 7.1 REST Endpoints

#### `GET /api/traffic/sources`
Returns available traffic generation modes, recorded trace files in `data/traces/`, and live telemetry configuration status.

#### `GET /api/traffic/status`
Returns metadata and operational health of the currently active traffic source.

#### `POST /api/traffic/validate-trace`
Validates a trace file without starting a run. Returns duration, packet counts, classification coverage %, and unclassified counts.
```json
{
  "file_name": "sample_5g_multi_slice_trace.csv",
  "qos_mapping": {"46": "URLLC", "10": "mURLLC"}
}
```

#### `POST /api/traffic/upload-trace`
Uploads a new recorded trace (`.csv`, `.jsonl`, `.json`, `.pcap`) into `data/traces/` and validates it immediately.

#### `POST /api/runs`
Initiates a new multi-policy experiment.
```json
{
  "scenario": "normal",
  "seed": 42,
  "max_macro_steps": 100,
  "traffic_source_type": "trace_replay",
  "trace_file": "sample_5g_multi_slice_trace.csv",
  "replay_speed": 1.0
}
```

### 7.2 Web Dashboard User Experience

1. **Traffic Source Selector:** Toggle between `Synthetic Data`, `Recorded Trace Replay`, and `Live Telemetry`.
2. **Trace Selection & Inspection:** Select trace files from a dropdown, click **"Inspect"** to view record count, time range, and slice coverage, or click **"Upload Trace"** to ingest new PCAP/CSV files directly from the browser.
3. **Live Telemetry Pill:** Displays real-time status (`DISCONNECTED`, `READY`, `STREAMING`, `STALE`) and endpoint freshness.
4. **Offered vs Simulated Charts:** Chart.js displays **Offered Demand (Source)** in dashed amber lines alongside solid colored series for **Simulated Delivered Throughput**, ensuring judges and operators can immediately distinguish ingress demand from engine output.

---

## 8. Data Privacy, Handling & Anonymization

1. **Payload-Free Processing:** Only frame lengths and header metadata (5QI, DSCP, IP Protocol, timestamps) are inspected. Packet payload contents are never stored in memory, logged to disk, or broadcast over WebSockets.
2. **UE Identifier Anonymization:** Subscriber identifiers (IMSI/SUPI) are replaced with synthetic pseudo-identifiers (`ue_anon_XXX`).
3. **Trace Sanitization:** Binary PCAP files generated for demonstration contain dummy MAC and IP addresses with zero customer private data.

---

## 9. Known Limitations

1. **PHY-Layer Channel Effects:** Recorded traces do not contain instantaneous SNR, CQI, or Rayleigh fading channels; the simulator calculates capacity based on PRB allocations and standard spectral efficiency bounds.
2. **Unclassified Packets:** If an imported trace lacks both slice tags and standard 5QI/DSCP headers, packets are designated `unclassified` and dropped at ingress rather than guessing critical slice allocations.
3. **Live Telemetry Latency:** Live telemetry streaming across high-jitter WAN links may occasionally trigger `STALE` status if packet transit delays exceed the 100 ms macro-control interval.
