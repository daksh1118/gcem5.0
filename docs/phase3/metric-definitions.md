# SLA Guardian — Phase 3 Metric Definitions & KPI Semantics
**Project:** SLA Guardian — Reinforcement Learning-Based Network Slicing and Resource Allocation for 5G  
**Phase:** Phase 3 — SLA Metrics Engine, Static Baseline and Adaptive Heuristic Baseline  
**Document Status:** Formal Specification  

---

## 1. Overview & Scope

This document defines the mathematical formulation, measurement intervals, aggregation rules, and boundary behaviors for all Key Performance Indicators (KPIs) evaluated in SLA Guardian.

All metrics are designed to evaluate both:
1. **Step-Level Dynamics:** Instantaneous behavior at discrete time step $t$ ($\Delta t = 10\text{ ms}$).
2. **Episode-Level Aggregate Outcomes:** End-of-run summaries across $T$ steps.

---

## 2. Metric Specifications

### 2.1 Delivered Throughput

Delivered throughput measures the rate of payload bits successfully processed through the radio stage AND the edge-compute stage and delivered to the application.

#### A. Step-Level Interval Throughput ($R_{\text{step}, s}^{(t)}$)
$$\text{Throughput}_{\text{step}, s}^{(t)} = \frac{\text{DeliveredBytes}_{s}^{(t)} \times 8}{\Delta t \times 10^6} \quad [\text{Mbps}]$$
- **Units:** Megabits per second (Mbps).
- **Interval:** Exactly one simulation step $\Delta t$ (e.g. $0.010\text{ s}$).
- **Missing Data:** If $0$ bytes are delivered in step $t$, interval throughput is $0.0\text{ Mbps}$.

#### B. Whole-Run Average Throughput ($R_{\text{run}, s}$)
$$\text{Throughput}_{\text{run}, s} = \frac{\sum_{t=1}^{T} \text{DeliveredBytes}_{s}^{(t)} \times 8}{T_{\text{elapsed\_sec}} \times 10^6} \quad [\text{Mbps}]$$
- **Critical Rule:** The denominator is total elapsed simulation time ($T_{\text{elapsed\_sec}} = \sum \Delta t$), NEVER a single step duration $\Delta t$.

---

### 2.2 End-to-End Latency

End-to-end packet latency measures the physical duration from packet arrival ($t_{\text{arrival}}$) at the gNodeB ingress queue until final execution completion ($t_{\text{compute\_exit}}$) at the edge-compute stage:

$$\text{Latency}_{i} = (t_{\text{compute\_exit}, i} - t_{\text{arrival}, i}) \times 1000.0 \quad [\text{ms}]$$

It incorporates:
$$\text{Latency}_{i} = \text{Radio Queuing Delay} + \text{Radio Transmission Delay} + \text{Compute Queuing Delay} + \text{Edge CPU Processing Delay}$$

#### A. Step & Rolling Statistics
- **Sample Population:** For step $t$, latency is evaluated across a rolling FIFO window of the most recent $N = 200$ delivered packets for slice $s$.
- **Percentiles:**
  - $\text{p50 Latency (ms)} = \text{Percentile}_{50}(\{\text{Latency}_i\})$
  - $\text{p95 Latency (ms)} = \text{Percentile}_{95}(\{\text{Latency}_i\})$
  - $\text{Mean Latency (ms)} = \frac{1}{|S|} \sum_{i \in S} \text{Latency}_i$
- **Missing / Insufficient Data Rule:**
  - If zero packets have been delivered for a slice, the metric is strictly **`None` / Unavailable**.
  - **Zero latency is NEVER substituted** when delay samples are absent.

---

### 2.3 Packet Cohort Accounting & Delivery Ratio

To prevent cohort skew where packets arriving in step $t$ are delivered in step $t+k$, packet accounting tracks four mutually exclusive states:

1. **`OfferedPackets` ($N_{\text{offered}}$):** Packets generated and submitted to the ingress queue.
2. **`DeliveredPackets` ($N_{\text{delivered}}$):** Packets that successfully completed radio transmission and edge compute.
3. **`DroppedPackets` ($N_{\text{dropped}}$):** Packets purged due to buffer overflow or latency deadline expiration.
4. **`PendingPackets` ($N_{\text{pending}}$):** Packets currently waiting in either the radio queue or compute queue at time $T$.

#### Packet Conservation Invariant:
$$N_{\text{offered}} = N_{\text{delivered}} + N_{\text{dropped}} + N_{\text{pending}}$$

#### Packet Delivery Ratio (PDR):
$$\text{PDR}_{\text{episode}, s} = \frac{N_{\text{delivered}, s}}{N_{\text{delivered}, s} + N_{\text{dropped}, s}} \quad [0.0 \dots 1.0]$$
- **Pending Packets:** Pending packets are reported separately. They are NEVER counted as delivered.
- **Empty Flow Rule:** If $N_{\text{offered}} = 0$, $\text{PDR} = 1.0$ (no packet loss occurred).

---

### 2.4 Resource Utilization

Measures how efficiently the allocated or total capacity was actively consumed by transmitted traffic:

#### A. Radio Utilization Ratio ($\rho_{\text{radio}}$)
$$\rho_{\text{radio}} = \frac{\sum_{s} \text{RadioBytesServed}_{s}^{(t)} \times 8 / (\Delta t \times 10^6)}{\text{TotalRadioCapacity}_{\text{config}} \times R_{\text{radio\_base}}} \quad [0.0 \dots 1.0]$$

#### B. Compute Utilization Ratio ($\rho_{\text{compute}}$)
$$\rho_{\text{compute}} = \frac{\sum_{s} \text{ComputeBytesProcessed}_{s}^{(t)} \times 8 / (\Delta t \times 10^6)}{\text{TotalComputeCapacity}_{\text{config}} \times R_{\text{compute\_base}}} \quad [0.0 \dots 1.0]$$

- **Denominator:** Dynamically loaded from active `RunConfig.total_radio_capacity` and `total_compute_capacity`. Never hard-coded.

---

### 2.5 SLA Compliance Evaluation

Evaluates per-slice SLA thresholds loaded from `RunConfig.sla_thresholds`:
- `max_latency_ms`: Evaluated against current p95 latency.
- `min_throughput_mbps`: Evaluated against delivered throughput.
- `min_packet_delivery_ratio`: Evaluated against packet delivery ratio.

#### Compliance States:
1. **`PASS`:** All active criteria are fully satisfied ($\text{Latency}_{\text{p95}} \le \text{Threshold}$, $\text{Throughput} \ge \text{Threshold}$, $\text{PDR} \ge \text{Threshold}$).
2. **`BREACH`:** One or more criteria are violated.
3. **`INSUFFICIENT_DATA`:** Insufficient packets delivered to measure latency or throughput (e.g. step 0).

> **Integrity Rule:**  
> `INSUFFICIENT_DATA` is **never** counted as a `PASS`.  
> RL reward values (which may include shaped bonuses or penalties) are strictly decoupled from SLA compliance.

---

### 2.6 Allocation Switching (Churn)

Measures resource instability between consecutive time steps to penalize unnecessary allocation oscillations:

$$\text{Churn}^{(t)} = \sum_{s \in \text{Slices}} \left( \left| \text{alloc}_{\text{radio}, s}^{(t)} - \text{alloc}_{\text{radio}, s}^{(t-1)} \right| + \left| \text{alloc}_{\text{compute}, s}^{(t)} - \text{alloc}_{\text{compute}, s}^{(t-1)} \right| \right)$$

- **Units:** Abstract resource units reallocated per step.
- At $t=0$, $\text{Churn}^{(0)} = 0.0$.
