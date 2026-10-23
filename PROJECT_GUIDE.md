# SLA Guardian — Merged Project Guide
## RL-Based 5G Network Slicing & Resource Allocation Demo

**Target:** High-fidelity, auditable, laptop-friendly 5G slicing resource allocation demo.  
**Platform:** Windows 11, Python 3.11, CPU-only, no Docker, no external database.  
**Core Innovation:** Joint radio + compute allocation, constrained RL with Lagrangian relaxation, and deterministic Safety Shield.

---

## 1. Context & Problem Formulation

5G operators deploy network slices to serve diverse service classes simultaneously:
- **eMBB (Enhanced Mobile Broadband):** High-volume throughput, video streaming, latency tolerant ($\le 25\text{ ms}$).
- **URLLC (Ultra-Reliable Low-Latency Communication):** Mission-critical, industrial robotics, strict deadlines ($\le 5\text{ ms}$), ultra-high delivery ratio ($\ge 99.99\%$).
- **mURLLC (Massive Machine-Type Ultra-Reliable Communication):** Massive sensor deployments, intermittent high-density bursts, strict reliability ($\ge 99.9\%$).

### Industry Bottlenecks Solved by SLA Guardian:
1. **Stranded Capacity in Static Slicing:** Conventional fixed splits (e.g., 60/25/15) waste spectrum when demand fluctuates.
2. **Coupled Radio and Edge-Compute Bottlenecks:** Allocating radio spectrum without commensurate edge User Plane Function (UPF) CPU capacity shifts the bottleneck into compute queues, breaching latency SLAs despite abundant wireless capacity.
3. **Unsafe Exploration in Standard RL:** Unconstrained RL policies maximize average reward by sacrificing rare mission-critical URLLC packets for massive eMBB throughput gains.
4. **Timescale Mismatch:** Micro-tier radio packet scheduling operates at sub-frame intervals (10 ms internal discrete simulation timestep); macro-tier resource orchestration operates at 100 ms control intervals.

---

## 2. Canonical Merged Architecture & System Decisions

The project unifies the existing modular codebase (`backend/app/`) with the uploaded constrained-RL demo guide:

### Decision A — Preserve Existing Modular Architecture
- Maintain all existing Pydantic data contracts (`RunConfig`, `NetworkState`, `ProposedAction`, `ExecutedAction`, `SafetyResult`, `StepMetrics`, `RunResult`).
- Retain the discrete-event simulation engine (`FallbackNetworkSimulator`), queue managers (`PacketQueue`), and SLA evaluator (`SlaMetricEvaluator`).
- Integrate new capabilities through explicit adapters in `backend/app/rl/` rather than replacing tested modules with monolithic files.

### Decision B — Constrained RL via Lagrangian Relaxation
- Primary RL objective: Maximize delivered eMBB throughput while strictly constraining critical-slice (URLLC + mURLLC) packet violations:
  $$\text{Training Reward} = R_{\text{service}}(\text{eMBB}) - \lambda \cdot C_{\text{violation}}(\text{URLLC}, \text{mURLLC})$$
- Episodic Lagrangian Multiplier update:
  $$\lambda_{k+1} = \max\left(0.0, \; \lambda_k + \alpha_{\text{lagrange}} \cdot (\bar{C}_k - C_{\text{limit}})\right)$$
- The multiplier $\lambda$ automatically penalizes the policy when critical slice violations exceed the configured threshold $C_{\text{limit}}$.

### Decision C — Six-Dimensional Action Space
- The policy outputs six continuous logits $a \in [-1, 1]^6$:
  - 3 radio logits: $[z_{\text{radio, eMBB}}, z_{\text{radio, URLLC}}, z_{\text{radio, mURLLC}}]$
  - 3 compute logits: $[z_{\text{compute, eMBB}}, z_{\text{compute, URLLC}}, z_{\text{compute, mURLLC}}]$
- Numerically stable softmax converts logits into normalized fractional shares independently for radio and compute.
- Shares are mapped onto total capacities ($R_{\text{total}} = 100$, $C_{\text{total}} = 100$) while guaranteeing configured minimum reservations ($R_{\min}, C_{\min}$).
- Scheduling priorities are derived deterministically based on slice urgency and backlog, keeping the initial model clean and stable.

### Decision D — 100 ms Macro-Control Interval over 10 ms Simulator Steps
- The RL agent makes resource orchestration decisions every **100 ms** (macro-control interval).
- The network simulator operates on a discrete **10 ms** internal step duration.
- The `MacroControlAdapter` holds a single validated `ExecutedAction` constant across ten internal simulation steps, properly aggregating offered/delivered bytes, packet counts, drop events, and latency samples.

### Decision E — Standardized Normalized Capacity Units
- Radio capacity: 100.0 abstract capacity units / PRBs.
- Compute capacity: 100.0 abstract compute units / CPU cores.
- Slices receive fractional shares mapped to these budgets. Independent accounting prevents compute starvation.

### Decision F — Safety Shield as Inviolable Hard Constraint
- Every action proposed by any policy (Static, Heuristic, PPO) must pass through the Phase 4 `SafetyShield`.
- The execution chain is strictly:
  $$\text{ProposedAction} \xrightarrow{\quad} \text{SafetyShield} \xrightarrow{\quad} \text{SafetyResult} \xrightarrow{\quad} \text{ExecutedAction} \xrightarrow{\quad} \text{Simulator}$$
- Rejections halt the simulator without advancing time. Valid reservations are preserved via proportional projection.

### Decision G — Single Authoritative Configuration
- `RunConfig` and `scenarios/default.json` remain the single source of truth for capacities, reservations, and traffic parameters.

### Decision H — Realistic Packet Dynamics
- Retain per-slice radio and compute queues, deadline tracking, and drop-on-expiry semantics.

### Decision I — Fair Evaluation Protocol
- Static, Heuristic, and RL policies must encounter identical exogenous traffic arrivals and channel variations during paired comparisons.

### Decision J — Transparent SLA Accounting
- Maintain honest, uncorrupted reporting of SLA outcomes across all slices and metrics.

---

## 3. Merged Roadmap

- **Merger Compatibility Phase (Current):** Reconcile architecture, build adapters (`observation`, `action_mapping`, `cost`, `lagrangian`, `control_interval`), align scenarios, diagnose SLA preflight, and document API and roadmap.
- **Phase 5 — Constrained PPO:** Gymnasium environment, Lagrangian training loop, save checkpoint to `models/agent.zip`, and evaluate against baselines.
- **Phase 6 — FastAPI Orchestration:** WebSocket streaming of live side-by-side simulation metrics, `/spike` injection, and experiment controls.
- **Phase 7 — Frontend Dashboard:** Lightweight 3-panel dashboard (HTML/JS/Chart.js) comparing Static, Heuristic, and Agent with real-time graphs and violation logs.
- **Phase 8 — Final Evaluation & Rehearsal:** Multi-seed benchmark generation, frozen model verification, and demo runbook execution.
- **Phase 9 — Optional ns-3 Feasibility:** Isolated exploration of ns-3 / 5G-LENA containerization without blocking the Python demo.

---

## 4. Development & Operational Constraints

1. **CPU Only:** All training and simulation runs on the host CPU. No CUDA, GPU, or Docker containers required.
2. **Demo Rule:** The presentation demo **must load** the pre-trained checkpoint (`models/agent.zip`). Never train live during presentation.
3. **Zero Test Regressions:** All existing unit and integration tests must pass at every phase boundary.
