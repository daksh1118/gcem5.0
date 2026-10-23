# SLA Guardian — Final Benchmark Integrity Audit & Reconciliation Report

**Auditor:** Senior ML Evaluation Engineer  
**Date:** 2026-10-23  
**Status:** Complete & Verified  
**Scope:** PPO Checkpoint (`models/agent.zip`), Training Logs (`runs/log.csv`), Metadata (`models/agent_metadata.json`), Evaluation Harness (`scripts/phase8/run_final_benchmark.py`), Benchmark Artifacts (`backend/artifacts/phase8/*`), and API Orchestrator (`backend/app/services/experiment_runner.py`).

---

## 1. Executive Summary

This audit performs an end-to-end reconciliation between reported PPO training behavior, the frozen model checkpoint, and the Phase 8 multi-policy evaluation results across 45 trials (5 scenarios $\times$ 3 seeds $\times$ 3 policies).

### Primary Findings
1. **Critical Slice Vulnerability under Stress:** The PPO agent achieves a URLLC Packet Delivery Ratio (PDR) of **74.46%** in `urllc_burst` (inferior to Heuristic's **86.47%** and Static's **80.94%**), and a mURLLC PDR of **34.92%** in `murllc_storm` (inferior to Heuristic's **75.33%** and Static's **47.33%**).
2. **Root Cause Identified (Training Regime & Passive Multiplier):**
   - The model was trained **exclusively on scenario `normal`** for 10,000 timesteps (`models/agent_metadata.json`).
   - In scenario `normal`, critical slice demand is low (8 Mbps URLLC, 15 Mbps mURLLC), well below the minimum reservation capacities.
   - Consequently, critical packet drop rates stayed between $0.0007$ and $0.0092$, never exceeding the configured `cost_limit = 0.01`.
   - The Lagrangian dual multiplier $\lambda$ **remained exactly $0.0000$ across all 102 training episodes** (`runs/log.csv`).
   - The training reward reduced to pure eMBB service satisfaction: $R = R_{\text{service}}(\text{eMBB}) - 0.0 \cdot C_{\text{crit}} = R_{\text{service}}(\text{eMBB})$.
   - The policy converged to a near-static allocation maximizing eMBB share ($\approx 48.2\%$ radio, $\approx 45.7\%$ compute) while providing only baseline shares to URLLC ($\approx 30.4\%$) and mURLLC ($\approx 21.4\%$).
   - When exposed out-of-distribution to `urllc_burst` or `murllc_storm`, the agent continues allocating surplus to eMBB rather than shifting resources to congested critical slices.
3. **Throughput Claim Correction:** The claim of *"45% aggregate-throughput improvement"* is mathematically inaccurate if applied to total network throughput. The measured improvement in **eMBB slice throughput** is **+36.3% to +43.0%** over Static. The improvement in **total aggregate throughput** across all three slices is **+5.6% to +20.3%**.
4. **Hardcoded Telemetry Artifact:** `experiment_runner.py` (lines 413, 671) and `index.html` hardcoded `lambda_val = 9.648` as a legacy display placeholder from Phase 6/7, directly contradicting the actual checkpoint metadata (`final_lambda = 0.0`) and training log.
5. **Legitimate Achievements Verified:** The model exhibits exceptional allocation stability (churn of $27.6 - 42.8$ vs. Heuristic's $182 - 1171$, up to 30x lower), successfully boosts eMBB throughput under nominal loads, and the deterministic Safety Shield successfully guarantees 100% compliance with physical simplex capacity and regulatory reservations across all 45 trials.

---

## 2. Checkpoint & Artifact Verification Evidence

### 2.1 File Hashes & Integrity
- **Checkpoint Path:** `models/agent.zip` (187 KB)
- **Calculated SHA-256:** `1d21d58fe672530a1f15ad4232ca7acc5c2a2373edafe8675ee4fe39cc963e78`
- **Verification Status:** **MATCHES** documentation in `README.md`, `final_benchmark.json`, and `docs/phase8/release-checklist.md`.

### 2.2 Model Training Metadata (`models/agent_metadata.json`)
```json
{
  "model_name": "constrained_ppo_sla_guardian",
  "saved_path": "C:\\gcemhacks5.0\\models\\agent.zip",
  "total_timesteps": 10000,
  "completed_episodes": 102,
  "training_duration_sec": 126.47,
  "seed": 42,
  "scenario": "normal",
  "cost_limit": 0.01,
  "lagrange_lr": 0.05,
  "final_lambda": 0.0,
  "observation_dim": 12,
  "action_dim": 6,
  "device": "cpu"
}
```

### 2.3 Training Log Analysis (`runs/log.csv`)
Inspection of all 102 completed training episodes reveals:
- **Episode 1 (step 100):** `mean_critical_cost: 0.0031`, `lambda_val: 0.0`, `mean_embb_tput_mbps: 22.69`
- **Episode 50 (step 5000):** `mean_critical_cost: 0.0029`, `lambda_val: 0.0`, `mean_embb_tput_mbps: 26.49`
- **Episode 102 (step 10200):** `mean_critical_cost: 0.0063`, `lambda_val: 0.0`, `mean_embb_tput_mbps: 33.71`
- **Summary:** Across all 10,200 steps, `mean_critical_cost` never exceeded `cost_limit = 0.01`. As a result, the dual gradient update $\lambda \leftarrow \max(0, \lambda + \alpha(C_{\text{crit}} - 0.01))$ never evaluated to a positive delta, keeping $\lambda = 0.0$ for the entire training lifetime.

---

## 3. Mathematical Recalculation from Raw Benchmark Records

Data extracted from `backend/artifacts/phase8/final_benchmark.json` (45 trials, 3 seeds per scenario, frozen weights):

### 3.1 Per-Slice Packet Delivery Ratios (PDR)
$$\text{PDR}_s = \frac{\sum \text{delivered\_packets}_s}{\sum \text{delivered\_packets}_s + \sum \text{dropped\_packets}_s}$$

| Scenario | Policy | eMBB PDR | URLLC PDR | mURLLC PDR | Audit Status |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **normal** | Static | 0.6357 | **1.0000** | **1.0000** | Verified exact |
| | Heuristic | 0.9449 | 0.9990 | 0.9951 | Verified exact |
| | **PPO Agent** | 0.8651 | **1.0000** | 0.9931 | Verified exact |
| **embb_surge** | Static | 0.2914 | **1.0000** | **1.0000** | Verified exact |
| | Heuristic | 0.4930 | 0.9995 | 0.9469 | Verified exact |
| | **PPO Agent** | 0.4142 | **1.0000** | 0.9896 | Verified exact |
| **urllc_burst** | Static | 0.6291 | **0.8094** | **1.0000** | Verified exact |
| | Heuristic | 0.7122 | **0.8647** | 0.9754 | Verified exact |
| | **PPO Agent** | 0.8504 | **0.7446** | 0.9885 | **Agent < Heuristic & Static** |
| **murllc_storm**| Static | 0.6320 | **1.0000** | **0.4733** | Verified exact |
| | Heuristic | 0.5531 | 0.9985 | **0.7533** | Verified exact |
| | **PPO Agent** | 0.8665 | 0.9998 | **0.3492** | **Agent < Heuristic & Static** |
| **mixed_stress** | Static | 0.3198 | **0.8961** | **0.6370** | Verified exact |
| | Heuristic | 0.4006 | 0.8434 | **0.5778** | Verified exact |
| | **PPO Agent** | 0.4565 | 0.8463 | **0.4595** | **Agent lowest on mURLLC** |

### 3.2 Delivered Throughput: Slice vs. Total Aggregate

$$\text{Total Throughput} = T_{\text{eMBB}} + T_{\text{URLLC}} + T_{\text{mURLLC}}$$

| Scenario | Policy | eMBB Tput (Mbps) | Total Tput (Mbps) | Agent vs. Static (eMBB) | Agent vs. Static (Total) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **normal** | Static | 28.82 | 51.65 | — | — |
| | Heuristic | 43.66 | 66.29 | — | — |
| | **PPO Agent** | 39.58 | 62.15 | **+37.33%** | **+20.33%** |
| **embb_surge** | Static | 25.50 | 48.32 | — | — |
| | Heuristic | 43.27 | 64.87 | — | — |
| | **PPO Agent** | 36.30 | 58.82 | **+42.35%** | **+21.73%** |
| **urllc_burst** | Static | 28.90 | 69.35 | — | — |
| | Heuristic | 32.82 | 74.57 | — | — |
| | **PPO Agent** | 39.40 | 77.52 | **+36.33%** | **+11.78%** |
| **murllc_storm**| Static | 28.93 | 57.04 | — | — |
| | Heuristic | 25.29 | 65.56 | — | — |
| | **PPO Agent** | 40.05 | 62.85 | **+38.44%** | **+10.19%** |
| **mixed_stress** | Static | 25.64 | 68.57 | — | — |
| | Heuristic | 32.16 | 71.76 | — | — |
| | **PPO Agent** | 36.67 | 72.39 | **+43.02%** | **+5.57%** |

**Audit Conclusion on Throughput:**
- The claim of *"+45% aggregate-throughput"* is **FALSE** when interpreted as whole-network aggregate throughput (actual gain is +5.6% to +21.7%).
- The claim is **APPROXIMATELY TRUE ONLY for eMBB slice throughput** (actual gain is +36.3% to +43.0%, averaging +39.5%).

---

## 4. In-Depth Investigation of Critical-Slice Delivery Failures

### 4.1 Investigation: mURLLC PDR = 34.92% in `murllc_storm`
- **Scenario Demand:** mURLLC traffic surges from 15 Mbps to 45 Mbps (3x storm). eMBB demand is 45 Mbps, URLLC is 8 Mbps.
- **Observed Allocations:**
  - **Static Policy:** Allocates fixed 33.3% radio / 33.3% compute to mURLLC $\implies$ delivers 33.3 Mbps capacity $\implies$ **PDR = 47.33%**.
  - **Adaptive Heuristic:** Detects queue buildup on mURLLC, reduces eMBB allocation down to 25.29 Mbps, shifts capacity to mURLLC $\implies$ **PDR = 75.33%**.
  - **PPO Agent:** Proposes radio allocation of **48.2% to eMBB**, **30.4% to URLLC**, and only **21.4% to mURLLC**. Compute allocation is **45.7% eMBB**, **35.1% URLLC**, **19.2% mURLLC**.
- **Physical Reason for Failure:** The Agent gave mURLLC only 21.4 Mbps of radio service. Since incoming offered load was 45 Mbps, the 21.4 Mbps capacity quickly backed up the buffer and dropped over 65% of all incoming mURLLC packets.
- **Why Did Agent Give Less than Static?** The Static policy assigns an even 33.3% to all slices. The Agent's minimum reservation for mURLLC is only 15.0%. Because the Agent assigned 70% of surplus to eMBB, mURLLC received only 21.4%, which is 11.9% *less* than Static!

### 4.2 Investigation: URLLC PDR = 74.46% in `urllc_burst`
- **Scenario Demand:** URLLC tactile demand spikes 4x from 8 Mbps to 32 Mbps.
- **Observed Allocations:**
  - **Static Policy:** Allocates 33.3% radio to URLLC $\implies$ **PDR = 80.94%**.
  - **Adaptive Heuristic:** Throttles eMBB, dynamically allocates 40%+ to URLLC $\implies$ **PDR = 86.47%**.
  - **PPO Agent:** Allocates **48.1% to eMBB**, **30.4% to URLLC**, and **21.5% to mURLLC** $\implies$ **PDR = 74.46%**.
- **Physical Reason for Failure:** 30.4% radio bandwidth cannot service 32 Mbps of peak burst traffic plus queuing overhead. Because the Agent prioritized eMBB at 48.1% (delivering 39.40 Mbps eMBB), URLLC dropped 25.5% of its packets.

### 4.3 Policy Sensitivity Diagnosis
To determine whether the policy is sensitive to incoming queue depths, we injected synthetic states into `RLPolicy.predict()`:
```text
State: Normal (all queues = 0)
  Obs: [0, 0.45, 0, 0,  0, 0.08, 0, 0,  0, 0.15, 0, 0]
  Radio Allocation: eMBB=40.87, URLLC=34.53, mURLLC=24.60

State: Huge URLLC Queue (1000 packets backlog on URLLC)
  Obs: [0, 0.45, 0, 0,  1.0, 0.80, 0, 0,  0, 0.15, 0, 0]
  Radio Allocation: eMBB=40.97, URLLC=34.44, mURLLC=24.59

State: Huge mURLLC Queue (1000 packets backlog on mURLLC)
  Obs: [0, 0.45, 0, 0,  0, 0.08, 0, 0,  1.0, 0.80, 0, 0]
  Radio Allocation: eMBB=44.07, URLLC=32.80, mURLLC=23.13
```
**Diagnosis:** The neural network's weights are virtually insensitive to queue backlogs on critical slices. In fact, when mURLLC queue depth increases to maximum (1000 packets), the network's eMBB logit increases from `0.5836` to `0.8161`, shifting *more* capacity to eMBB.

---

## 5. Metric & Environmental Definitions: Training vs. Evaluation

| Dimension | Training Environment (`SliceGymnasiumEnv`) | Evaluation Harness (`run_final_benchmark.py`) | Consistency Check |
| :--- | :--- | :--- | :--- |
| **Observation Adapter** | `ObservationAdapter(queue_scale=1000.0)` | `ObservationAdapter(queue_scale=1000.0)` | **Identical** |
| **Action Adapter** | `ActionMappingAdapter(policy_id="constrained_ppo")` | `ActionMappingAdapter(policy_id="constrained_ppo")` | **Identical** |
| **Safety Shield** | `SafetyShield()` with simplex projection | `SafetyShield()` with simplex projection | **Identical** |
| **Traffic Generators** | `FallbackNetworkSimulator` + `default.json` | `FallbackNetworkSimulator` + `default.json` | **Identical** |
| **Traffic Scenario** | **Only `normal`** | **All 5 scenarios** | **Severe Domain Shift** |
| **Step Cadence** | `MacroControlAdapter` (10 steps $\times$ 10 ms = 100 ms) | `PolicyExecutionPipeline` (1 step $\times$ 10 ms = 10 ms) | **Granularity Mismatch** |
| **Critical Cost Metric** | Drops only on URLLC/mURLLC | Drops, Latency breaches, & Throughput | **Objective Mismatch** |

### 5.1 Step Cadence Validation
To test whether the 10 ms vs. 100 ms execution cadence in the evaluation harness distorted the agent's performance, we rolled out the identical three policies across 50 full **macro-intervals (100 ms intervals = 5.0 seconds)** using `MacroControlAdapter`:
- In `urllc_burst`: Agent URLLC PDR was **72.97%** (Heuristic was **81.44%**, Static was **62.70%**).
- In `murllc_storm`: Agent mURLLC PDR was **31.16%** (Heuristic was **84.26%**, Static was **46.80%**).
- In `normal`: Agent eMBB throughput was **38.64 Mbps** vs. Static **35.77 Mbps**.
**Conclusion:** The qualitative and quantitative conclusions remain identical regardless of whether 10 ms sub-steps or 100 ms macro-intervals are evaluated: the agent operates as an eMBB-biased allocation that drops critical packets under unexpected bursts.

---

## 6. Implementation Defect & Smallest Corrective Fix

### Defect Identified: Hardcoded Multiplier in API Telemetry
In `backend/app/services/experiment_runner.py`:
- Line 413: `lambda_val = 9.648  # Loaded trained multiplier`
- Line 671: `lagrangian_lambda=9.648 if key == "agent" else None`

### Evidence
- `models/agent_metadata.json` explicitly records `"final_lambda": 0.0`.
- `runs/log.csv` records `lambda_val = 0.0` for all 102 episodes.
- Hardcoding `9.648` creates a direct contradiction between the live telemetry stream and the underlying evaluation artifacts.

### Proposed Smallest Corrective Change
Update `experiment_runner.py` to inspect `models/agent_metadata.json` upon initialization and read `final_lambda`, defaulting to `0.0` if metadata is missing. No interfaces, contracts, or schemas are modified.

---

## 7. Corrected Presentation Claims

The presentation script, README, and demo documentation must be revised to eliminate unsupported assertions and ground every claim in verifiable benchmark evidence.

### Prohibited / Refuted Claims
- ❌ **DO NOT CLAIM:** *"PPO achieves a +45% aggregate-throughput improvement."*  
  *(Total network throughput improves by +5.6% to +20.3%; only the eMBB slice improves by +36% to +43%.)*
- ❌ **DO NOT CLAIM:** *"PPO protects critical slices with zero packet drops during URLLC bursts and mURLLC storms."*  
  *(Under bursts and storms, PPO drops up to 25.5% of URLLC packets and 65.1% of mURLLC packets because it was trained only on nominal load with $\lambda = 0$.)*
- ❌ **DO NOT CLAIM:** *"The Lagrangian multiplier actively penalized critical drops during training with $\lambda = 9.648$."*  
  *($\lambda$ remained at $0.0$ throughout training because nominal critical drops never exceeded the 1% cost budget.)*

### Approved / Supported Claims
- ✔ **CAN CLAIM:** **Scavenging Surplus Capacity:** By dynamically allocating idle radio capacity to best-effort eMBB traffic, PPO increases eMBB delivered throughput by **+37% to +43%** over rigid 33/33/33 static slicing.
- ✔ **CAN CLAIM:** **Deterministic Physical Safety:** The decoupled Safety Shield guarantees 100% adherence to physical capacity constraints ($\sum a_i \le 1.0$) and regulatory slice reservations ($r_i \ge 0.10$), actively projecting out-of-bounds proposals across all trials without system crashes.
- ✔ **CAN CLAIM:** **Exceptional Control Stability:** PPO reduces allocation churn to **27.6 – 42.8**, representing a **15x to 30x reduction in control thrashing** compared to reactive heuristics (churn up to 1,171).
- ✔ **CAN CLAIM:** **Nominal Protection:** Under nominal load and eMBB video surges, PPO maintains a **1.0000 URLLC PDR** and **~0.99 mURLLC PDR**, avoiding the reactive drops caused by heuristic churn.
- ✔ **CAN CLAIM:** **Honest Research Limitations:** Because the model was trained on nominal traffic where critical drops were within budget, the agent did not learn reactive burst defense. Multi-scenario curriculum training is documented as the direct next research milestone.
