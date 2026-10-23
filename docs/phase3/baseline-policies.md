# SLA Guardian — Phase 3 Baseline Policies Specification
**Project:** SLA Guardian — Reinforcement Learning-Based Network Slicing and Resource Allocation for 5G  
**Phase:** Phase 3 — SLA Metrics Engine, Static Baseline and Adaptive Heuristic Baseline  
**Document Status:** Implementation & Technical Reference  

---

## 1. Overview & Objectives

In Phase 3, two reference allocation controllers were developed to establish rigorous benchmarks against which future Reinforcement Learning (RL) agents will be evaluated:

1. **`StaticSlicingPolicy`:** A fixed-share partitioner representing traditional rigid telecom network slicing.
2. **`AdaptiveDemandHeuristicPolicy`:** A dynamic, explainable, rule-based controller that reallocates radio and compute capacity in response to offered traffic growth, queue depths, and SLA breach risks.

Both policies implement the canonical [PolicyInterface](file:///c:/gcemhacks5.0/backend/app/interfaces/policy.py) and output validated [ProposedAction](file:///c:/gcemhacks5.0/backend/app/schemas/actions.py) schemas.

---

## 2. Static Slicing Policy (`StaticSlicingPolicy`)

### 2.1 Formulation & Philosophy
Traditional network slicing operates with fixed, pre-provisioned resource quotas per tenant. This guarantees isolation but leads to severe resource underutilization when a slice is idle, and severe packet drops when demand spikes.

### 2.2 Mathematical Model
Given:
- Total Radio Capacity $R_{\text{total}}$ and Total Compute Capacity $C_{\text{total}}$.
- Configured minimum baseline reservations $R_{\min, s}$ and $C_{\min, s}$ per slice.
- Configured baseline shares $w_{\text{radio}, s}$ and $w_{\text{compute}, s}$ ($\sum w = 1.0$).

The remaining unreserved capacity is partitioned proportionally:
$$R_{\text{alloc}, s} = R_{\min, s} + \left( R_{\text{total}} - \sum_{k} R_{\min, k} \right) \times w_{\text{radio}, s}$$
$$C_{\text{alloc}, s} = C_{\min, s} + \left( C_{\text{total}} - \sum_{k} C_{\min, k} \right) \times w_{\text{compute}, s}$$

- **Default Baseline Shares:** eMBB: 45%, URLLC: 25%, mURLLC: 30%.
- **Invariant:** Allocations are completely invariant across time steps, regardless of observed traffic spikes or queuing delays.

---

## 3. Adaptive Demand-Aware Heuristic (`AdaptiveDemandHeuristicPolicy`)

### 3.1 Formulation & Philosophy
To address the rigidity of static slicing, the adaptive heuristic continuously senses slice traffic demand, queue accumulation, and SLA risk margins, dynamically reallocating capacity from unburdened slices to congested slices.

### 3.2 Multi-Factor Urgency Scoring
At every decision step $t$, an urgency score $U_s^{(t)}$ is computed for each slice $s \in \{\text{eMBB}, \text{URLLC}, \text{mURLLC}\}$:

$$U_s^{(t)} = W_{\text{criticality}, s} \times D_s^{(t)} \times Q_s^{(t)} \times H_s^{(t)}$$

Where:
1. **Intrinsic Criticality Weight ($W_{\text{criticality}, s}$):**
   - URLLC: $2.2$ (highest priority for ultra-low latency).
   - mURLLC: $1.4$ (industrial telemetry priority).
   - eMBB: $1.0$ (best-effort broadband priority).
2. **Dynamic Demand Factor ($D_s^{(t)}$):**
   $$D_s^{(t)} = \max\left(1.0, \text{OfferedDemand}_{s}^{(t)} \times \left(1.0 + \max(0.0, \text{GrowthRate}_s^{(t)})\right)\right)$$
   Anticipates surging traffic before queues overflow.
3. **Queue Backlog Factor ($Q_s^{(t)}$):**
   $$Q_s^{(t)} = 1.0 + \frac{\text{QueueDepthPackets}_s^{(t)}}{25.0}$$
   Rapidly escalates urgency as packets queue in the radio or edge-compute buffers.
4. **SLA Headroom Multiplier ($H_s^{(t)}$):**
   - Active SLA Breach ($\text{Headroom} < 0.0$): Multiplier $= 3.0$ (Emergency state).
   - Danger Zone ($0.0 \le \text{Headroom} < 0.20$): Multiplier $= 1.8$.
   - Compliant Buffer ($\text{Headroom} \ge 0.20$): Multiplier $= 1.0$.

### 3.3 Resource Allocation & Anti-Churn Smoothing
1. **Target Distribution:**
   Remaining capacity above minimum reservations is distributed proportionally to $U_s^{(t)}$:
   $$R_{\text{target}, s} = R_{\min, s} + R_{\text{rem}} \times \frac{U_{\text{radio}, s}}{\sum_k U_{\text{radio}, k}}$$
2. **Temporal Smoothing (Anti-Churn):**
   To prevent high-frequency oscillations that destabilize scheduler state, a smoothing factor $\beta = 0.20$ is applied:
   $$R_{\text{final}, s}^{(t)} = (1 - \beta) \cdot R_{\text{target}, s}^{(t)} + \beta \cdot R_{\text{final}, s}^{(t-1)}$$
   Followed by strict normalization to ensure $\sum R_{\text{final}} = R_{\text{total}}$ and $\sum C_{\text{final}} = C_{\text{total}}$.
3. **Dynamic Priority Assignment:**
   Slices are sorted in descending order of urgency score. The slice with the highest urgency is assigned Priority 1 (highest scheduling priority).

---

## 4. Empirical Performance Comparison

Results from running `scripts/phase3/run_baseline_comparison.py` over 50 simulation steps with identical seeds:

| Scenario | Policy | eMBB Throughput | URLLC Throughput | eMBB PDR | URLLC PDR | Total Churn |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Normal** | Static | $26.52\text{ Mbps}$ | $7.89\text{ Mbps}$ | $0.5885$ | $1.0000$ | $0.0$ |
| | **Adaptive Heuristic** | **$42.25\text{ Mbps}$** | **$7.89\text{ Mbps}$** | **$0.9213$** | **$1.0000$** | $464.9$ |
| **URLLC Burst**| Static | $26.45\text{ Mbps}$ | $24.78\text{ Mbps}$ | $0.5675$ | $0.7824$ | $0.0$ |
| | **Adaptive Heuristic** | **$29.55\text{ Mbps}$** | **$26.76\text{ Mbps}$** | **$0.6323$** | **$0.8429$** | $1306.6$ |
| **Mixed Stress**| Static | $23.88\text{ Mbps}$ | $21.61\text{ Mbps}$ | $0.2999$ | $0.8821$ | $0.0$ |
| | **Adaptive Heuristic** | **$29.90\text{ Mbps}$** | $20.14\text{ Mbps}$ | **$0.3751$** | $0.8269$ | $634.3$ |

### Key Findings:
1. **Demand Awareness Wins in Normal Load:** In normal conditions, the heuristic detects that URLLC ($8\text{ Mbps}$) does not need excess capacity, reallocating surplus to eMBB ($45\text{ Mbps}$ offered). This increases eMBB PDR from $58.8\%$ to $92.1\%$.
2. **Mitigation of Burst Drops:** In `urllc_burst`, URLLC drops in the static baseline are $21.8\%$ (PDR 0.7824). The adaptive heuristic quickly detects the surge, increasing URLLC throughput to $26.76\text{ Mbps}$ and PDR to $0.8429$.

---

## 5. Limitations of Rule-Based Control

While the adaptive heuristic outperforms static slicing, it exhibits inherent limitations:
1. **Myopic Reactive Decisions:** The heuristic responds to queue growth after packets have already accumulated, resulting in a lag before extra capacity takes effect.
2. **Churn Overhead:** Rapid priority shifting incurs allocation churn ($>1000\text{ L1 units}$ during bursts), which in physical 5G base stations triggers RRC reconfiguration signaling overhead.
3. **Suboptimal Multi-Objective Tradeoffs:** Hand-tuned urgency weights cannot find the optimal Pareto frontier balancing throughput maximization, strict latency bounds, and compute cost.

*These fundamental limitations motivate the RL agent (PPO) and deterministic Safety Shield developed in subsequent phases.*

---

## 6. How to Run Baseline Comparisons

Execute the comparison runner:
```powershell
.\.venv\Scripts\python.exe scripts\phase3\run_baseline_comparison.py
```
This generates:
- Live terminal comparative tables across `normal`, `urllc_burst`, and `mixed_stress`.
- Machine-readable JSON summary artifact at `backend/artifacts/phase3/baseline_comparison_results.json`.
