# SLA Guardian: Phase 8 Real Traffic Trace Benchmark Report

- **Generated At:** 2026-10-23 15:56:39 UTC
- **Control Interval:** 100 ms Macro-Control Interval (10 x 10 ms sub-steps/interval)
- **Traffic Source:** Trace Replay (`TraceReplayTrafficSource`)
- **Frozen PPO Checkpoint SHA-256:** `1d21d58fe672530a1f15ad4232ca7acc5c2a2373edafe8675ee4fe39cc963e78`
- **Candidate PPO Checkpoint SHA-256:** `ec903788b569e7c5ac612692e3979f4e8a6b90e2d8b7e2765e995c902ccc19bc`
- **Evaluated Traces:** 3 recorded packet traces (`CSV`, `JSONL`, binary `PCAP`)
- **Evaluated Steps per Trace:** 50 macro-steps (5.0 seconds sim time)

## Trace Inventory & Provenance

| Trace File | Format | Packets | Duration (s) | Classification Coverage | 3GPP QoS / DSCP Labels |
| :--- | :--- | :---: | :---: | :---: | :--- |
| `sample_5g_multi_slice_trace.csv` | CSV | 2,268 | 10.0s | 100.0% | 5QI 1 (URLLC), 5QI 9 (eMBB), 5QI 79 (mURLLC) |
| `sample_5g_trace.jsonl` | JSONL | 1,320 | 8.0s | 100.0% | 5QI 1, 5QI 9, 5QI 79 with source latency measurements |
| `sample_5g_trace.pcap` | Binary PCAP | 997 | 5.0s | 100.0% | IPv4 ToS/DSCP: EF (URLLC), AF11 (mURLLC), CS0 (eMBB) |

## Trace-Driven Policy Performance Comparison

| Trace File | Policy | eMBB Tput (Mbps) | Total Tput (Mbps) | eMBB PDR | URLLC PDR | mURLLC PDR | Critical Cost | Churn (L1) | Breach Ratio |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `sample_5g_multi_slice_trace.csv` | Static Baseline | 1.44 | 1.74 | 100.00% | 100.00% | 100.00% | 0.000000 | 0.0 | 100.0% |
| `sample_5g_multi_slice_trace.csv` | Adaptive Heuristic | 1.44 | 1.74 | 100.00% | 100.00% | 100.00% | 0.000000 | 1616.3 | 100.0% |
| `sample_5g_multi_slice_trace.csv` | Frozen PPO | 1.44 | 1.74 | 100.00% | 100.00% | 100.00% | 0.000000 | 5.8 | 100.0% |
| `sample_5g_multi_slice_trace.csv` | **Candidate PPO** | 1.44 | 1.74 | 100.00% | 100.00% | 100.00% | 0.000000 | 23.7 | 100.0% |
| `sample_5g_trace.jsonl` | Static Baseline | 1.10 | 1.29 | 100.00% | 100.00% | 100.00% | 0.000000 | 0.0 | 100.0% |
| `sample_5g_trace.jsonl` | Adaptive Heuristic | 1.10 | 1.29 | 100.00% | 100.00% | 100.00% | 0.000000 | 656.6 | 100.0% |
| `sample_5g_trace.jsonl` | Frozen PPO | 1.10 | 1.29 | 100.00% | 100.00% | 100.00% | 0.000000 | 3.9 | 100.0% |
| `sample_5g_trace.jsonl` | **Candidate PPO** | 1.10 | 1.29 | 100.00% | 100.00% | 100.00% | 0.000000 | 18.9 | 100.0% |
| `sample_5g_trace.pcap` | Static Baseline | 1.33 | 1.54 | 100.00% | 100.00% | 100.00% | 0.000000 | 0.0 | 100.0% |
| `sample_5g_trace.pcap` | Adaptive Heuristic | 1.33 | 1.54 | 100.00% | 100.00% | 100.00% | 0.000000 | 1083.4 | 100.0% |
| `sample_5g_trace.pcap` | Frozen PPO | 1.33 | 1.54 | 100.00% | 100.00% | 100.00% | 0.000000 | 4.6 | 100.0% |
| `sample_5g_trace.pcap` | **Candidate PPO** | 1.33 | 1.54 | 100.00% | 100.00% | 100.00% | 0.000000 | 19.5 | 100.0% |

## Metric Separation: Measured Source Data vs Simulated Outputs

- **Measured Source Inputs:** Packet sizes, arrival timestamps, inter-arrival deltas, 5QI/DSCP QoS labels, device identifiers, and offered bitrates are directly parsed from the recorded traces without synthetic replacement.
- **Simulated Engine Outputs:** Radio PRB allocation, queue dynamics, transmission scheduling, packet drops, channel fading, and SLA delivery ratios are simulated outcomes computed by `FallbackNetworkSimulator` and bounded by `SafetyShield`.
- **Measurement Limitations:** Unless latency is explicitly provided by the input trace records (as in `sample_5g_trace.jsonl`), simulated latency reflects network queuing and air-interface transmission delay rather than real-world physical path propagation.

