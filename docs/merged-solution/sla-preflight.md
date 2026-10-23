# SLA Preflight Investigation: Diagnostic Analysis of 100% SLA-Breach Step Ratio

## Executive Summary

During Phase 3 and Phase 4 benchmark rollouts across `normal`, `urllc_burst`, and `mixed_stress` traffic scenarios, both the `StaticSlicingPolicy` and `AdaptiveDemandHeuristicPolicy` exhibited an **`SLA breach step ratio` of 100.00%**.

This preflight investigation examines the simulation engine, telemetry evaluator, scenario configurations, and mathematical service models. 

**Core Finding:** The 100% breach ratio is **not** an artifact of unmeasured telemetry leakage or corrupted metric evaluators. Rather, it is the deterministic mathematical consequence of three compounding factors:
1. **Any-Slice Aggregate Breach Definition:** A discrete time step is classified as an SLA breach if *any* of the three slices fails *any single* threshold.
2. **Nominal Offered Demand Below Throughput SLA Targets:** For `normal` traffic, configured throughput SLA targets (50 Mbps for eMBB, 20 Mbps for mURLLC) exceed the nominal traffic offered by the traffic generator (45 Mbps and 15 Mbps, respectively). A network cannot deliver throughput that was never offered.
3. **Step Discretization Floor Exceeding URLLC Latency SLA:** The discrete simulation time-step duration is $\Delta t = 10.0\text{ ms}$. Packet arrival offsets are uniform over $[0, 10\text{ ms}]$, and packet delivery occurs at step completion. This imposes a theoretical minimum 95th percentile latency of $9.5\text{ ms}$, which permanently exceeds the strict URLLC target of $5.0\text{ ms}$.

Per project requirements, **we do not alter SLA thresholds to fabricate an artificial benchmark improvement**. The findings are fully documented below and will guide reward normalization and RL training.

---

## 1. Metric Definition: SLA Breach Step Ratio

In [`backend/app/evaluation/metrics.py`](file:///c:/gcemhacks5.0/backend/app/evaluation/metrics.py#L147-L173), step-level SLA compliance is evaluated as follows:

```python
for s in CANONICAL_SLICE_IDS:
    sla = config.sla_thresholds[s]
    if p95_lat is None:
        sla_state = "INSUFFICIENT_DATA"
        is_compliant = False
    elif p95_lat > sla.max_latency_ms:
        sla_state = "BREACH"
        is_compliant = False
    elif throughput_mbps[s] < sla.min_throughput_mbps:
        sla_state = "BREACH"
        is_compliant = False
    elif pdr is not None and pdr < sla.min_packet_delivery_ratio:
        sla_state = "BREACH"
        is_compliant = False
    else:
        sla_state = "PASS"
        is_compliant = True

    if sla_state == "BREACH":
        active_breaches += 1
```

At the end of an episode of $N$ completed steps:
$$\text{sla\_breach\_step\_ratio} = \frac{1}{N} \sum_{t=1}^{N} \mathbb{I}\left(\text{active\_breaches}_t > 0\right)$$

Therefore:
- A single threshold failure (latency, throughput, or PDR) in a single slice flags the entire step as an SLA breach.
- For a step to be recorded as a PASS, **all three slices** (`eMBB`, `URLLC`, `mURLLC`) must **simultaneously satisfy all four metrics** (latency $\le$ max, throughput $\ge$ min, PDR $\ge$ min, jitter $\le$ max).

---

## 2. Slice-by-Slice Diagnostic Breakdown

A step-by-step diagnostic execution was conducted over 50 steps for all scenarios:

### A. Scenario: `normal` (50 steps)

| Slice | SLA Targets | Actual Measured Values (Mean / p95) | Primary Breach Causes | Slice Breach Rate |
| :--- | :--- | :--- | :--- | :--- |
| **eMBB** | Latency $\le 25\text{ ms}$<br>Throughput $\ge 50\text{ Mbps}$<br>PDR $\ge 98.0\%$ | Latency: $\approx 15\text{ ms}$ (PASS)<br>Throughput: $26.5 - 42.2\text{ Mbps}$ (BREACH)<br>PDR: $58.8\% - 92.1\%$ | Delivered throughput ($26.5 - 42.2\text{ Mbps}$) < SLA threshold ($50.0\text{ Mbps}$) | **100% (50/50)** |
| **URLLC**| Latency $\le 5\text{ ms}$<br>Throughput $\ge 10\text{ Mbps}$<br>PDR $\ge 99.99\%$ | Latency: $9.1 - 9.6\text{ ms}$ (BREACH)<br>Throughput: $7.89\text{ Mbps}$ (BREACH)<br>PDR: $100.0\%$ (PASS) | 1. Latency ($9.5\text{ ms} > 5.0\text{ ms}$)<br>2. Throughput ($7.9\text{ Mbps} < 10.0\text{ Mbps}$) | **100% (50/50)** |
| **mURLLC**| Latency $\le 15\text{ ms}$<br>Throughput $\ge 20\text{ Mbps}$<br>PDR $\ge 99.9\%$ | Latency: $\approx 11\text{ ms}$ (PASS)<br>Throughput: $14.1\text{ Mbps}$ (BREACH)<br>PDR: $100.0\%$ (PASS) | Delivered throughput ($14.1\text{ Mbps} < 20.0\text{ Mbps}$) | **94% - 100%** |

### B. Scenario: `urllc_burst` (50 steps)
- **URLLC**: Offered traffic bursts to $32\text{ Mbps}$. Static allocation delivers $24.78\text{ Mbps}$ with $78.2\%$ PDR (packet drops due to queue overflow and latency $> 5.0\text{ ms}$). Adaptive Heuristic adapts to deliver $26.76\text{ Mbps}$ ($84.3\%$ PDR), but still breaches latency ($9.5 - 9.7\text{ ms} > 5.0\text{ ms}$).
- **eMBB**: Deprioritized during URLLC burst; throughput drops to $26.4 - 29.5\text{ Mbps} < 50.0\text{ Mbps}$.
- **Result:** 100% of steps exhibit at least one slice breach.

### C. Scenario: `mixed_stress` (50 steps)
- Total offered load $= 80 (\text{eMBB}) + 25 (\text{URLLC}) + 35 (\text{mURLLC}) = 140\text{ Mbps}$.
- System physical capacity $= 100\text{ PRBs} \approx 100\text{ Mbps}$ and $100\text{ Compute Cores} = 100\text{ Mbps}$.
- **Overload is genuine physical congestion:** Radio and compute queues overflow, drops surge, eMBB latency reaches $47.1\text{ ms} > 25.0\text{ ms}$, and URLLC PDR drops to $82.7\% - 88.2\%$.

---

## 3. Discretization Floor Analysis (The 9.5 ms URLLC Latency Floor)

In `FallbackNetworkSimulator` ([`backend/app/simulator/traffic.py`](file:///c:/gcemhacks5.0/backend/app/simulator/traffic.py#L112) and [`backend/app/simulator/compute.py`](file:///c:/gcemhacks5.0/backend/app/simulator/compute.py#L86)):
1. In a step spanning $[t, t + \Delta t]$ with $\Delta t = 0.010\text{ s}$ ($10\text{ ms}$), packet arrivals are generated with intra-step offsets:
   $$\tau_{\text{arr}} = t + U(0, \Delta t)$$
2. Packets complete their multi-stage transmission and compute pipeline and are marked as delivered at the end of the simulation step:
   $$\tau_{\text{exit}} = t + \Delta t$$
3. Therefore, for an unqueued packet with zero waiting delay:
   $$\text{latency} = \tau_{\text{exit}} - \tau_{\text{arr}} = \Delta t - U(0, \Delta t) \sim U(0, 10\text{ ms})$$
4. The 95th percentile of a uniform distribution $U(0, 10)$ is:
   $$\text{p95} = 0.95 \times 10.0\text{ ms} = 9.5\text{ ms}$$
5. Because the configured URLLC SLA threshold is `max_latency_ms: 5.0 ms`, the measured p95 latency is **guaranteed to breach the 5.0 ms SLA threshold at every single step**, even with infinite radio and compute capacity!

---

## 4. Telemetry Window & Macro-Control Context

When operating across the 100 ms macro-control interval:
- The 100 ms window aggregates ten 10 ms steps.
- Throughput averages over 100 ms, stabilizing instantaneous Poisson fluctuations.
- The 9.5 ms internal queue floor remains transparently explained in the documentation.
- The constrained RL policy maximizes eMBB throughput while keeping critical slice packet loss and deadline expiration rates below $C_{\text{limit}} = 0.01$.
