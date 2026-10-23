# SLA Guardian — Merged Phase Roadmap

This document outlines the sequential, time-boxed phases for SLA Guardian, reconciling completed architectural milestones with the final hackathon demo delivery.

---

## Completed Phases (Phases 0–4)

- **Phase 0 — Environment & Simulator Validation:** Validated host Windows 11 platform, verified Python 3.11 virtual environment, established Python discrete-event fallback due to absence of ns-3/5G-LENA.
- **Phase 1 — Project Scaffolding & Shared Data Contracts:** Created validated Pydantic schemas for network state, actions, safety results, metrics, and abstract interfaces.
- **Phase 2 — Discrete-Event Network Simulator:** Implemented `FallbackNetworkSimulator`, packet queues, Poisson traffic generator with burst profiles, OFDMA radio model, and edge-compute service queues.
- **Phase 3 — SLA Metrics Engine & Baseline Policies:** Implemented `SlaMetricEvaluator`, `StaticSlicingPolicy` (fixed split), and `AdaptiveDemandHeuristicPolicy` (EWMA tracking).
- **Phase 4 — Safety Shield & Safe Execution Pipeline:** Implemented deterministic `SafetyShield` with reservation-aware proportional projection and `PolicyExecutionPipeline` ensuring rejected actions never advance the simulator.

---

## Active Phase: Merger Compatibility & Alignment Phase

- **Objective:** Establish the unified architecture reconciling the existing modular codebase with the uploaded constrained-RL demo guide.
- **Deliverables:**
  - `PROJECT_GUIDE.md` reflecting merged decisions A through J.
  - `docs/merged-solution/` architecture, migration map, SLA preflight, API contract, and roadmap documentation.
  - Reconciled scenario profiles (`normal`, `embb_surge`, `urllc_burst`, `murllc_storm`, `mixed_stress`).
  - Implemented and unit-tested RL compatibility adapters:
    - `backend/app/rl/observation.py`
    - `backend/app/rl/action_mapping.py`
    - `backend/app/rl/cost.py`
    - `backend/app/rl/lagrangian.py`
    - `backend/app/rl/control_interval.py`
  - Zero test regressions on existing 47 tests.

---

## Forward Execution Roadmap

### Phase 5 — Constrained Reinforcement Learning (PPO)
- Implement `GymnasiumNetworkEnv` wrapping `FallbackNetworkSimulator` and `MacroControlAdapter` (100 ms macro-interval).
- Implement the Lagrangian reward function: $R_t = R_{\text{embb}} - \lambda C_{\text{crit}}$.
- Build CPU-based training script (`backend/app/rl/train.py`) using Stable-Baselines3 PPO with periodic episodic $\lambda$ multiplier updates.
- Save trained checkpoint to `models/agent.zip` (and copy to `backend/artifacts/rl/ppo_sla_guardian.zip`).
- Implement `RLPolicy` loading the saved checkpoint for deterministic inference.
- Run baseline comparison across all 5 scenarios comparing `Static`, `Heuristic`, and `RLPolicy`.

### Phase 6 — FastAPI Orchestration & WebSocket Streaming
- Wire FastAPI application (`backend/app/api/`) with WebSocket `/ws` endpoint streaming live 10 Hz telemetry for all three policies in lockstep.
- Implement `/spike`, `/reset`, `/summary`, and `/scenarios` endpoints.
- Ensure identical seeded traffic streams for fair real-time comparison.

### Phase 7 — Three-Panel Live Dashboard (Frontend)
- Build lightweight, CDN-based single-page interface (`frontend/index.html`):
  - 3 side-by-side panels: Static vs. Heuristic vs. SLA Guardian Agent.
  - Live Chart.js graphs for eMBB throughput and critical violations.
  - Interactive scenario selector and Trigger Spike button.
  - Real-time Safety Shield intervention pills.
- Zero npm or node build dependencies required.

### Phase 8 — Multi-Seed Benchmark Evaluation & Final Release
- Execute multi-seed paired evaluations (seeds 42, 100, 2026) across all 5 traffic profiles.
- Generate comparative publication-quality markdown tables and JSON artifacts.
- Freeze trained model weights in `models/agent.zip`.
- Author complete `README.md` with system architecture diagrams, benchmark results, and step-by-step demo runbook.
- Conduct complete dry-run demo test.

### Phase 9 — Optional ns-3 / 5G-LENA Validation (Time-Boxed)
- Time-boxed exploration of ns-3 / 5G-LENA containerization.
- Under strict rule: **must never block or delay the functional Python demo**.
