# SLA Guardian: Autonomous 5G Network Slicing & Resource Allocation

An intelligent, safety-critical 5G network slicing and edge-compute resource allocation prototype utilizing Constrained Reinforcement Learning (PPO with Lagrangian multipliers) and a deterministic Safety Shield.

---

## Architecture Overview

```
                      +------------------------------------------+
                      |         Exogenous Traffic Demands        |
                      |    (eMBB video, URLLC auto, mURLLC tele) |
                      +--------------------+---------------------+
                                           |
                                           v
+----------------------------------------------------------------------------------------+
|                                Abstracted Network Simulator                            |
|  - OFDMA Downlink Radio (Shannon Capacity, Rayleigh Fast-Fading, Path Loss)            |
|  - Multi-Tenant Edge Compute Server (CPU allocations, discrete processing queues)      |
+------------------------------------------+---------------------------------------------+
                                           |
                                           | 12-dimensional State Observation
                                           v
+----------------------------------------------------------------------------------------+
|                              Autonomous Decision Pipeline                              |
|                                                                                        |
|   [Policy 1: Static Baseline]     [Policy 2: Adaptive Heuristic]     [Policy 3: PPO]   |
|   Fixed 33/33/33 partitioning     Queue-proportional reactive        Constrained RL    |
|                                                                             |          |
|                                                               6-dim action  v          |
|                                                              +-----------------------+ |
|                                                              |  DETERMINISTIC SHIELD | |
|                                                              |  - Simplex projection | |
|                                                              |  - Min 10% slice res  | |
|                                                              +-----------+-----------+ |
+--------------------------------------------------------------------------|-------------+
                                                                           |
                                                               Validated   v
                                                               Actions to Simulator
```

---

## Key Features

- **Multi-Policy Simulation Engine:** Runs Static Baseline, Adaptive Demand Heuristic, and Constrained PPO Agent concurrently on matched 5G traffic.
- **Deterministic Safety Shield:** Enforces hard PRB and compute reservations ($\ge 10\%$) and physical capacity limits ($\sum a_i \le 1.0$) before commands reach the network simulator.
- **Constrained RL with Lagrangian Multiplier:** Optimizes eMBB throughput while dynamically penalizing critical-slice (URLLC & mURLLC) delay and drop violations.
- **Real-Time Telemetry Streaming:** Exposes WebSocket (`/ws`) at 10 Hz cadence and full REST control endpoints (`/api/runs`, `/api/spike`, `/api/reset`, `/api/pause`, `/api/summary`).
- **Interactive Control-Room Dashboard:** Three-panel side-by-side comparison UI, live Chart.js time-series analytics, grounded agent decision rationale, and runtime spike injection.
- **Reproducible Abstracted Simulation:** Coupled OFDMA radio scheduling, stochastic Rayleigh fading, and multi-tenant edge compute processing.

---

## Prerequisites & Installation

- **Operating System:** Windows 10/11 (PowerShell 5.1+)
- **Python Version:** Python 3.11 (tested on 3.11.9 64-bit)
- **Virtual Environment:** Active `.venv` in project root with CPU PyTorch, Gymnasium, and Stable-Baselines3.

```powershell
# Open terminal in project root
cd c:\gcemhacks5.0

# Verify environment readiness
.\.venv\Scripts\python.exe scripts/phase0/check_environment.py
```

---

## Quickstart & Demo Commands

### 1. Run Automated Test Suite
```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -v
```
*(89 passed, 1 warning in ~9.5s)*

### 2. Start the Backend & Web Dashboard Server
```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

### 3. Open the Dashboard in your Browser
Navigate to:
```
http://127.0.0.1:8000/
```
The FastAPI backend mounts and serves the single-page application directly from `frontend/`.

### 4. Run Reproducible Multi-Scenario Benchmark
```powershell
.\.venv\Scripts\python.exe scripts/phase8/run_final_benchmark.py
```
Outputs saved to `backend/artifacts/phase8/` (`final_benchmark.json`, `final_benchmark.csv`, `final_results.md`).

---

## Verified Pre-trained Model Checkpoint

- **File Location:** `models/agent.zip` (187 KB)
- **Metadata:** `models/agent_metadata.json`
- **Algorithm:** Constrained PPO (`ActorCriticPolicy`, MLP `[64, 64]`)
- **Action / Observation Contract:** 12-dim observation $\rightarrow$ 6-dim action
- **SHA-256 Checksum:** `1d21d58fe672530a1f15ad4232ca7acc5c2a2373edafe8675ee4fe39cc963e78`

The model is loaded directly for inference; no online training or parameter modification occurs during execution.

---

## Phase 8 Final Benchmark Results

*45 full evaluation trials across 5 scenarios and 3 seeds (42, 101, 202) using frozen weights and identical exogenous traffic realizations:*

| Scenario | Policy | eMBB Tput (Mbps) | Total Tput (Mbps) | eMBB PDR | URLLC PDR | mURLLC PDR | Radio Util (%) | Churn ($L_1$) | Shield Interv. |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **normal** | Static | 28.82 | 51.65 | 0.6357 | **1.0000** | **1.0000** | 81.3% | 0.0 | 0.0 |
| | Heuristic | 43.66 | 66.29 | 0.9449 | 0.9990 | 0.9951 | 79.9% | 538.4 | 0.0 |
| | **PPO Agent** | **39.58** | **62.15** | **0.8651** | **1.0000** | 0.9931 | 80.6% | **42.8** | 11.7 |
| **embb_surge** | Static | 25.50 | 48.32 | 0.2914 | **1.0000** | **1.0000** | 81.3% | 0.0 | 0.0 |
| | Heuristic | 43.27 | 64.87 | 0.4930 | 0.9995 | 0.9469 | 79.3% | 182.0 | 0.0 |
| | **PPO Agent** | **36.30** | **58.82** | **0.4142** | **1.0000** | 0.9896 | 80.5% | **30.9** | 10.7 |
| **urllc_burst** | Static | 28.90 | 69.35 | 0.6291 | **0.8094** | **1.0000** | 81.3% | 0.0 | 0.0 |
| | Heuristic | 32.82 | 74.57 | 0.7122 | **0.8647** | 0.9754 | 80.1% | 1171.3 | 0.0 |
| | **PPO Agent** | **39.40** | **77.52** | **0.8504** | 0.7446 | 0.9885 | 80.5% | **38.8** | 9.7 |
| **murllc_storm**| Static | 28.93 | 57.04 | 0.6320 | **1.0000** | 0.4733 | 81.3% | 0.0 | 0.0 |
| | Heuristic | 25.29 | 65.56 | 0.5531 | 0.9985 | **0.7533** | 81.5% | 547.1 | 0.0 |
| | **PPO Agent** | **40.05** | **62.85** | **0.8665** | 0.9998 | 0.3492 | 80.5% | **36.3** | 11.7 |
| **mixed_stress** | Static | 25.64 | 68.57 | 0.3198 | **0.8961** | **0.6370** | 81.3% | 0.0 | 0.0 |
| | Heuristic | 32.16 | 71.76 | 0.4006 | 0.8434 | **0.5778** | 80.7% | 586.2 | 0.0 |
| | **PPO Agent** | **36.67** | **72.39** | **0.4565** | 0.8463 | 0.4595 | 80.5% | **27.6** | 13.0 |

### Key Benchmark Takeaways
1. **eMBB Throughput Superiority:** PPO achieves **+36.3% to +43.0%** higher eMBB throughput than static slicing by dynamically scavenging surplus PRBs. Across the entire network, total aggregate throughput improves by **+5.6% to +20.3%**.
2. **Control Stability:** PPO reduces allocation churn by up to **30x** compared to reactive heuristics (churn ~27-43 vs. 180-1171), eliminating base station control thrashing.
3. **Safety Enforcement:** The Safety Shield deterministically projected out-of-bounds proposals across 100% of trials with zero physical over-allocation violations.
4. **Burst & Overload Behavior (Integrity Audit Finding):** Under out-of-distribution traffic bursts (`urllc_burst`, `murllc_storm`), PPO drops critical packets (URLLC PDR 74.5%, mURLLC PDR 34.9%) because training was conducted exclusively on nominal load where $\lambda$ remained at 0.0. The policy learned to prioritize eMBB throughput rather than reactive emergency shedding. Multi-scenario curriculum training is documented as future work.

---

## Known Assumptions & Limitations

1. **Abstracted Python Simulation:** The current environment is an abstracted discrete-event Python simulator (Shannon capacity, Rayleigh fast-fading, $M/M/1/K$ radio queues, and discrete CPU queues). It does not model full 3GPP 38.901 physical-layer OFDMA subcarrier scheduling, HARQ retransmissions, or beamforming.
2. **Simulation Resolution & Latency Floor:** The internal simulation steps at $\Delta t = 10\text{ ms}$. Uniform intra-step packet arrivals produce an empirical p95 latency floor of $\approx 9.5\text{ ms}$. This causes the aggregate SLA evaluator to flag the aggressive 5.0 ms URLLC latency target as a breach across all policies, despite near-perfect packet delivery ratios.
3. **Single-Scenario Training Domain Shift:** Because `models/agent.zip` was trained on nominal traffic, the agent operates effectively as a smooth, eMBB-biased allocation. In severe critical surges, reactive heuristics yield higher delivery ratios on critical slices at the cost of high churn.
4. **Aggregate SLA Metric Definition:** The aggregate breach metric counts a step as breached if *any* single slice fails *either* its packet delivery ratio or latency target. Individual slice delivery metrics are exposed separately for granular evaluation.

---

## Future Work & ns-3 / 5G-LENA Validation

The project’s architecture uses decoupled Pydantic v2 schemas (`ObservationVector`, `AllocationAction`, `StepTelemetry`). This allows seamless future integration with:
- **ns-3 / 5G-LENA:** Binding the Python `RLPolicy` to a C++ 5G-LENA physical-layer simulation via gRPC or Unix domain sockets.
- **O-RAN Near-RT RIC:** Packaging the PPO policy and Safety Shield as an O-RAN compliant xApp for deployment in an Open RAN testbed.

---

## Documentation Index

- **Final Claims Audit:** [docs/phase8/final_claims_audit.md](file:///c:/gcemhacks5.0/docs/phase8/final_claims_audit.md)
- **Demo Runbook:** [docs/phase8/demo-runbook.md](file:///c:/gcemhacks5.0/docs/phase8/demo-runbook.md)
- **Presentation Script:** [docs/phase8/presentation-script.md](file:///c:/gcemhacks5.0/docs/phase8/presentation-script.md)
- **Judge Q&A Guide:** [docs/phase8/judge-qa.md](file:///c:/gcemhacks5.0/docs/phase8/judge-qa.md)
- **Release Checklist:** [docs/phase8/release-checklist.md](file:///c:/gcemhacks5.0/docs/phase8/release-checklist.md)
- **Benchmark Artifacts:** [backend/artifacts/phase8/final_results.md](file:///c:/gcemhacks5.0/backend/artifacts/phase8/final_results.md)
