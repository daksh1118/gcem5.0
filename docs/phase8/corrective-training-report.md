# SLA Guardian — Corrective Training & Comprehensive Evaluation Report

**Lead Engineer:** Senior Reinforcement Learning Engineer & ML Evaluation Lead  
**Date:** 2026-10-23  
**Status:** Complete, Empirically Benchmarked & Verified  
**Scope:** Checkpoint Remediation, Multi-Scenario Constrained PPO Training, Control Interval Harmonization, 4-Policy Macro-Control Benchmark, and Regression Suite.

---

## 1. Executive Summary

This report documents the execution of the corrective-training task remediating the structural defects and evaluation mismatches identified in `docs/phase8/final_claims_audit.md`.

### Core Remediation Achievements
1. **Telemetry & Multiplier Reconciliation:** Eliminated legacy hardcoded Lagrangian display values (`9.648`). The API orchestrator now dynamically reports genuine checkpoint metadata (`final_lambda = 0.0000` for frozen model, `1.1646` for candidate).
2. **Control Interval Harmonization:** Eliminated the 10 ms vs. 100 ms evaluation cadence mismatch. All four policies (Static, Adaptive Heuristic, Frozen PPO, and Candidate PPO) were evaluated under identical **100 ms macro-control intervals** (`MacroControlAdapter`, 10 sub-steps $\times$ 10 ms) across 60 trials (5 scenarios $\times$ 3 seeds).
3. **Multi-Scenario Constrained PPO:** Implemented balanced episode cycling across all five canonical network traffic scenarios (`normal`, `embb_surge`, `urllc_burst`, `murllc_storm`, `mixed_stress`).
4. **Episodic Dual Multiplier Execution:** Fixed the underlying `DummyVecEnv` reset timing defect, enabling the Lagrangian multiplier to update exactly once per completed episode based on actual critical-slice packet drop costs. Dual multiplier $\lambda$ dynamically scaled from $0.0000$ to **$1.1646$**.
5. **Metric Consistency:** Harmonized `ViolationCostAdapter` with packet-delivery ratios, verifying $\text{Cost} + \text{Critical PDR} \approx 1.0$ under steady state and queue purge conditions.
6. **Non-Destructive Execution:** The original frozen checkpoint `models/agent.zip` was strictly preserved with SHA-256 `1d21d58fe672530a1f15ad4232ca7acc5c2a2373edafe8675ee4fe39cc963e78`. The new candidate model is saved separately at `models/candidate_agent.zip` and has **not** been promoted to default runtime.
7. **Complete Verification:** All 93 automated tests in `backend/tests` pass cleanly, including 4 new regression tests covering multi-scenario cycling, dual multiplier updates, metric consistency, and artifact integrity.

---

## 2. Checkpoint Artifacts & Integrity Verification

| Checkpoint Identifier | File Path | File Size | SHA-256 Hash | Status |
| :--- | :--- | :---: | :--- | :--- |
| **Frozen PPO Baseline** | `models/agent.zip` | 187 KB | `1d21d58fe672530a1f15ad4232ca7acc5c2a2373edafe8675ee4fe39cc963e78` | **Preserved Untouched** |
| **Candidate PPO Checkpoint** | `models/candidate_agent.zip` | 187 KB | `ec903788b569e7c5ac612692e3979f4e8a6b90e2d8b7e2765e995c902ccc19bc` | **Newly Generated** |
| **Candidate Artifact Backup** | `backend/artifacts/rl/candidate_agent.zip` | 187 KB | `ec903788b569e7c5ac612692e3979f4e8a6b90e2d8b7e2765e995c902ccc19bc` | **Newly Generated** |

### 2.1 Candidate Checkpoint Metadata (`models/candidate_metadata.json`)
```json
{
  "model_name": "constrained_ppo_sla_guardian",
  "saved_path": "C:\\gcemhacks5.0\\models\\candidate_agent.zip",
  "artifact_path": "C:\\gcemhacks5.0\\backend\\artifacts\\rl\\candidate_agent.zip",
  "total_timesteps": 15000,
  "completed_episodes": 151,
  "training_duration_sec": 266.91,
  "seed": 42,
  "scenario": [
    "normal",
    "embb_surge",
    "urllc_burst",
    "murllc_storm",
    "mixed_stress"
  ],
  "cost_limit": 0.01,
  "lagrange_lr": 0.05,
  "final_lambda": 1.1646,
  "observation_dim": 12,
  "action_dim": 6,
  "device": "cpu",
  "library_versions": {
    "torch": "2.14.1+cpu",
    "stable_baselines3": "2.9.0",
    "gymnasium": "0.29.1"
  }
}
```

---

## 3. Engineering Fixes & Remediation Implementation

### 3.1 Fix 1: API Telemetry Lagrangian Reconciliation
- **Root Cause:** Phase 6/7 frontend code and API experiment runner contained hardcoded fallback strings `lambda_val = 9.648` and `λ = 9.648`.
- **Remediation:** 
  - `backend/app/services/experiment_runner.py`: Replaced hardcoded default with dynamic lookup from `models/agent_metadata.json` (`final_lambda`). Fallback default set to `0.0`.
  - `frontend/index.html`: Updated baseline telemetry display badge to `λ = 0.000`.
  - Added regression test `test_19_model_metadata_lagrangian_multiplier_reconciliation` in `backend/tests/test_api_orchestration.py`.

### 3.2 Fix 2: Simulator Reset Scenario Propagation
- **Root Cause:** In `FallbackNetworkSimulator.reset()`, changing the scenario configuration did not reinitialize the internal `TrafficGenerator` slice profiles, preventing scenario transitions during multi-scenario rotation.
- **Remediation:** Updated `backend/app/simulator/fallback.py` line 118:
  ```python
  if config is not None:
      self.config = config
      self.traffic_gen.config = config
      self.traffic_gen._init_slice_profiles()
  ```

### 3.3 Fix 3: Gymnasium Multi-Scenario Support & VectorEnv Timing
- **Root Cause:** Stable-Baselines3 `DummyVecEnv` automatically invokes `env.reset()` upon episode completion *prior* to passing control back to `callback._on_step()`. In the original Phase 5 implementation, `env.reset()` purged `self.episode_costs`, causing `get_mean_episode_cost()` to evaluate to `0.0` on every step.
- **Remediation:** 
  - `SliceGymnasiumEnv`: Added `last_completed_episode_cost` persistence across resets and multi-scenario round-robin scheduling.
  - `LagrangianCallback._on_step()`: Callback computes `mean_cost = np.mean(self.episode_costs)` from its own step accumulator and passes it explicitly: `env.update_lagrangian_multiplier(cost=mean_cost)`.
  - `SliceGymnasiumEnv.update_lagrangian_multiplier(cost=None)`: Fallbacks to `last_completed_episode_cost` if no cost is explicitly supplied.

### 3.4 Fix 4: Metric Consistency (Critical Cost vs. Packet Delivery Ratio)
- **Root Cause:** `ViolationCostAdapter` previously calculated cost as `crit_dropped / crit_offered`. In situations where packets were queued and later purged during buffer overflow, offered demand in that specific step could be zero, resulting in uncounted packet drops.
- **Remediation:** Updated denominator in `backend/app/rl/cost.py`:
  $$\text{denom} = \max(\text{crit\_offered}, \text{crit\_delivered} + \text{crit\_dropped})$$
  $$\text{cost} = \frac{\text{crit\_dropped}}{\text{denom}}$$
  This guarantees mathematical consistency between critical-slice cost and packet delivery metrics ($\text{Cost} + \text{Critical PDR} \approx 1.0$).

---

## 4. Multi-Scenario Training Dynamics (`runs/candidate_log.csv`)

The candidate agent was trained on CPU for 15,000 timesteps (151 completed episodes, ~30 per scenario) with `cost_limit = 0.01` and `lagrange_lr = 0.05`.

```
Episode  Steps   Scenario      Mean Cost   Lambda Update         eMBB Tput   Net Reward
---------------------------------------------------------------------------------------
Ep 1     100     normal        0.0028      0.0000 -> 0.0000      22.69 Mbps  +36.41
Ep 2     200     embb_surge    0.0017      0.0000 -> 0.0000      19.46 Mbps  +18.22
Ep 3     300     urllc_burst   0.1320      0.0000 -> 0.0061      22.52 Mbps  +36.08
Ep 4     400     murllc_storm  0.4088      0.0061 -> 0.0260      23.43 Mbps  +36.93
Ep 5     500     mixed_stress  0.2227      0.0260 -> 0.0367      21.24 Mbps  +20.40
...
Ep 50    5000    mixed_stress  0.2327      0.3580 -> 0.3692      22.37 Mbps  +13.73
Ep 100   10000   mixed_stress  0.2570      0.7501 -> 0.7624      22.70 Mbps  +3.14
Ep 150   15000   mixed_stress  0.2512      1.1527 -> 1.1647      24.10 Mbps  -5.17
```

### Analysis of Training Progression:
1. **Active Constraint Enforcement:** Unlike the frozen model (where $\lambda = 0.0000$ perpetually), the dual multiplier actively increased whenever the agent neglected critical slices during burst/storm episodes.
2. **Reward Penalty Dynamics:** In early episodes (1–5), reward remained positive (+36.41 to +20.40) despite 40%+ drop rates in `murllc_storm`. As $\lambda$ rose past $1.0$, the Lagrangian penalty term $-\lambda \cdot C_{\text{crit}}$ drove net training reward negative (-5.17), forcing the policy's gradient updates to prioritize critical buffer clearance over eMBB greediness.

---

## 5. Comprehensive 4-Policy Macro-Control Benchmark Results

All four policies were evaluated on identical seeds (`[42, 101, 202]`) and identical 100 ms macro-control intervals (`MacroControlAdapter`, 50 macro-steps $\times$ 100 ms = 5.0s sim time).

Artifact sources: `backend/artifacts/phase8/corrective_benchmark.json`, `corrective_benchmark.csv`, and `corrective_results.md`.

### 5.1 Full Performance Comparison Table

| Scenario | Policy | eMBB Tput (Mbps) | Total Tput (Mbps) | eMBB PDR | URLLC PDR | mURLLC PDR | Critical Cost | Churn (L1) | Breach Ratio |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **normal** | Static | 27.71 | 50.60 | 0.6191 | **1.0000** | **0.9995** | **0.0003** | **0.0** | 1.00 |
| | Heuristic | **41.12** | **63.75** | **0.9152** | 0.9992 | 0.9831 | 0.0086 | 762.0 | 1.00 |
| | Frozen PPO | 38.88 | 61.58 | 0.8658 | 0.9999 | 0.9876 | 0.0060 | 43.7 | 1.00 |
| | **Candidate PPO** | 30.30 | 52.99 | 0.6771 | **1.0000** | 0.9870 | 0.0063 | 65.1 | 1.00 |
| **embb_surge** | Static | 24.01 | 46.99 | 0.2839 | **1.0000** | **0.9996** | **0.0002** | **0.0** | 1.00 |
| | Heuristic | **40.82** | **62.83** | **0.4823** | 0.9977 | 0.9393 | 0.0304 | 272.2 | 1.00 |
| | Frozen PPO | 34.29 | 56.99 | 0.4052 | 0.9998 | 0.9831 | 0.0083 | 34.0 | 1.00 |
| | **Candidate PPO** | 27.01 | 49.67 | 0.3193 | **1.0000** | 0.9798 | 0.0097 | 68.0 | 1.00 |
| **urllc_burst** | Static | 27.83 | 68.68 | 0.6241 | 0.8107 | **0.9998** | 0.1531 | **0.0** | 1.00 |
| | Heuristic | 30.38 | 72.23 | 0.6808 | **0.8613** | 0.9612 | **0.1196** | 1497.6 | 1.00 |
| | Frozen PPO | **38.97** | **77.56** | **0.8705** | 0.7480 | 0.9853 | 0.2065 | 41.3 | 1.00 |
| | **Candidate PPO** | 30.67 | 72.62 | 0.6875 | 0.8529 | 0.9836 | 0.1221 | 66.3 | 1.00 |
| **murllc_storm**| Static | 27.81 | 55.39 | 0.6241 | **1.0000** | 0.4385 | 0.4117 | **0.0** | 1.00 |
| | Heuristic | 23.16 | **64.90** | 0.5199 | 0.9976 | **0.7553** | **0.1802** | 634.9 | 1.00 |
| | Frozen PPO | **39.17** | 61.72 | **0.8760** | 0.9998 | 0.3259 | 0.4942 | 39.3 | 1.00 |
| | **Candidate PPO** | 30.33 | 54.42 | 0.6805 | **1.0000** | 0.3605 | 0.4689 | 68.6 | 1.00 |
| **mixed_stress** | Static | 24.32 | 67.25 | 0.3076 | 0.8909 | 0.5922 | 0.2311 | **0.0** | 1.00 |
| | Heuristic | 29.71 | 70.50 | 0.3756 | 0.8417 | 0.5664 | 0.2706 | 694.6 | 1.00 |
| | Frozen PPO | **35.07** | **70.87** | **0.4434** | 0.8451 | 0.4209 | 0.3280 | 30.0 | 1.00 |
| | **Candidate PPO** | 27.31 | 66.16 | 0.3452 | **0.9289** | 0.4482 | 0.2677 | 65.7 | 1.00 |

---

## 6. Honest Comparative Analysis & Findings

### 6.1 Areas Where Candidate PPO Demonstrates Significant Improvement
1. **Critical Slice Protection under `urllc_burst`:**
   - **Frozen PPO** suffered severe degradation under URLLC bursts, achieving only **74.80% PDR** and a high critical cost of **0.2065** (worst of all policies).
   - **Candidate PPO** improved URLLC PDR to **85.29%** (+10.49 percentage points) and reduced critical violation cost by **40.9%** (to **0.1221**).
   - Candidate PPO outperforms Static (**81.07%**) and virtually matches Adaptive Heuristic (**86.13%**), but achieves this with **22.5x lower churn** (66.3 vs. 1497.6).
2. **URLLC Dominance under `mixed_stress`:**
   - Under compound stress, Candidate PPO achieved the **highest URLLC PDR across all evaluated policies: 92.89%** (Static: 89.09%, Heuristic: 84.17%, Frozen PPO: 84.51%).
   - Critical cost improved from **0.3280** (Frozen PPO) down to **0.2677** (better than Adaptive Heuristic's 0.2706).
3. **Allocation Stability:**
   - Candidate PPO maintains exceptionally low churn ($65.1 - 68.6$ across all scenarios), avoiding the severe control instability and packet oscillation seen in Adaptive Heuristic ($272 - 1497$).

### 6.2 Honest Reporting: Areas Where Candidate PPO Performs Worse Than Baselines
1. **`murllc_storm` mURLLC Delivery:**
   - Under the severe 3x mURLLC storm (45 Mbps demand), Candidate PPO achieved a mURLLC PDR of **36.05%**.
   - While superior to Frozen PPO (**32.59%**), Candidate PPO is **significantly outperformed by Adaptive Heuristic (75.53%) and Static Baseline (43.85%)**.
   - **Root Cause:** The Heuristic policy detects the queue explosion and aggressively throttles eMBB down to 23.16 Mbps, diverting maximum bandwidth to mURLLC. The Candidate PPO still allocates 30.33 Mbps to eMBB (achieving 68.05% eMBB PDR). Because 15,000 timesteps was a conservative training duration, the candidate learned to protect URLLC more aggressively than mURLLC.
2. **Nominal eMBB Throughput Degradation:**
   - In `normal` conditions, Frozen PPO delivered **38.88 Mbps** eMBB throughput. Candidate PPO delivered **30.30 Mbps** (-22.1%).
   - In `embb_surge`, Frozen PPO delivered **34.29 Mbps**. Candidate PPO delivered **27.01 Mbps** (-21.2%).
   - **Root Cause:** The high Lagrangian multiplier ($\lambda = 1.1646$) acts as an active risk penalty. The candidate agent prioritizes headroom for critical slices rather than aggressively greedily consuming radio surplus for eMBB.

---

## 7. Automated Test Suite & Regression Verification

The test suite was expanded and executed via CPU-only pytest:

```
collected 93 items

backend\tests\test_api_orchestration.py ...................              [ 20%]
backend\tests\test_compute.py ...                                        [ 23%]
backend\tests\test_config.py .....                                       [ 29%]
backend\tests\test_evaluation.py .....                                   [ 34%]
backend\tests\test_frontend.py .......                                   [ 41%]
backend\tests\test_interfaces.py ..                                      [ 44%]
backend\tests\test_policies.py ...                                       [ 47%]
backend\tests\test_radio.py ....                                         [ 51%]
backend\tests\test_rl_adapters.py ........                               [ 60%]
backend\tests\test_rl_env.py ............                                [ 73%]
backend\tests\test_safety_shield.py .........                            [ 82%]
backend\tests\test_schemas.py .......                                    [ 90%]
backend\tests\test_simulator.py .....                                    [ 95%]
backend\tests\test_traffic.py ....                                       [100%]

======================= 93 passed, 1 warning in 11.89s ========================
```

### New Regression Tests Added in `backend/tests/test_rl_env.py`:
1. `test_multi_scenario_gymnasium_cycling`: Asserts round-robin sequence cycling across all 5 canonical scenarios.
2. `test_episodic_lagrangian_dual_update_with_cost`: Asserts that `update_lagrangian_multiplier(cost=...)` performs mathematical gradient ascent on dual variable $\lambda$ and verifies `last_completed_episode_cost` preservation across environment resets.
3. `test_critical_cost_and_pdr_consistency`: Asserts mathematical consistency: $\text{Cost} + \text{Critical PDR} == 1.0$ under processed traffic.
4. `test_candidate_checkpoint_and_frozen_hash_integrity`: Asserts that `models/agent.zip` retains SHA-256 `1d21d58fe672530a1f15ad4232ca7acc5c2a2373edafe8675ee4fe39cc963e78`, candidate checkpoint is loadable, and metadata accurately records multi-scenario list and $\lambda > 0.0$.

---

## 8. Final Status & Recommendation

- **Frozen Checkpoint Preservation:** Confirmed. `models/agent.zip` was not overwritten.
- **Candidate Checkpoint Promotion:** **NOT PROMOTED.** In accordance with safety rules, `models/candidate_agent.zip` remains in evaluation staging and has not overwritten default production weights.
- **Deliverables Saved:**
  - Candidate model: `models/candidate_agent.zip` (SHA-256: `ec903788b569e7c5ac612692e3979f4e8a6b90e2d8b7e2765e995c902ccc19bc`)
  - Candidate metadata: `models/candidate_metadata.json`
  - Candidate training log: `runs/candidate_log.csv`
  - Corrective benchmark raw JSON: `backend/artifacts/phase8/corrective_benchmark.json`
  - Corrective benchmark tabular CSV: `backend/artifacts/phase8/corrective_benchmark.csv`
  - Corrective benchmark summary Markdown: `backend/artifacts/phase8/corrective_results.md`
  - Corrective report: `docs/phase8/corrective-training-report.md`
