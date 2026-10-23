# SLA Guardian: 5G Network Slicing & Resource Allocation

An intelligent, safety-critical 5G network slicing and edge-compute resource allocation prototype utilizing Constrained Reinforcement Learning (PPO with Lagrangian multipliers) and a deterministic Safety Shield.

---

## Key Features

- **Multi-Policy Simulation Engine:** Runs Static Baseline, Adaptive Demand Heuristic, and Constrained PPO Agent concurrently on matched 5G traffic.
- **Deterministic Safety Shield:** Enforces hard PRB and compute reservations for mission-critical slices (URLLC & mURLLC) before commands reach the network simulator.
- **Constrained RL with Lagrangian Multiplier:** Optimizes eMBB throughput while enforcing critical-slice violation constraints.
- **Real-Time Telemetry Streaming:** Exposes WebSocket (`/ws`) at 10 Hz cadence and full REST control endpoints (`/api/runs`, `/api/spike`, `/api/reset`, `/api/pause`, `/api/summary`).
- **Interactive Control-Room Dashboard:** Three-panel side-by-side comparison UI, live Chart.js time-series analytics, grounded agent decision rationale, and live spike injection.
- **Reproducible Abstracted Simulation:** Coupled OFDMA radio scheduling, stochastic Rayleigh fading, and multi-tenant edge compute processing.

---

## Quickstart & Demo Setup

### 1. Environment Activation & Dependencies
```powershell
# Dependencies are verified in .venv (CPU only, Python 3.11)
.\.venv\Scripts\activate
```

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

### 4. Run Automated Test Suite
```powershell
# Run the complete test suite (88 tests passing in ~8s)
.\.venv\Scripts\python.exe -m pytest backend/tests -v
```

---

## Interactive Demo Walkthrough

1. **Verify System Health:**
   - Look at the top navigation bar: Live Beacon shows green (`CONNECTED`), Model Badge indicates `PPO LOADED` from `models/agent.zip`, and Status is `IDLE`.
2. **Execute Nominal Experiment:**
   - Select scenario **NORMAL** from the dropdown.
   - Click **▶ Start**.
   - Observe live telemetry streaming at 10 Hz across all three policy panels.
   - Note that PPO dynamically reallocates unutilized PRBs to eMBB (boosting throughput from 26.5 to ~37.7 Mbps) while preserving 100% packet delivery for URLLC and mURLLC.
3. **Trigger Runtime Traffic Spikes:**
   - Click **⚡ URLLC x4** quick burst button during the run.
   - Observe how the Heuristic policy reacts abruptly with high churn, dropping packets on other slices.
   - Observe how SLA Guardian's Safety Shield maintains critical reservations with zero dropped packets.
4. **Inspect Policy Explainability:**
   - Review the **Policy Decision Rationale** box on the Agent panel for grounded explanations of surplus allocations.
   - Inspect the **Lagrangian Multiplier $\lambda$** gauge tracking constraint enforcement.
5. **Interactive Controls:**
   - Click **⏸ Pause** to inspect state at any macro step.
   - Click **⏭ Step** to advance exactly one 100 ms interval.
   - Click **↺ Reset** to clear accumulators and return to step 0.

---

## REST & WebSocket API Overview

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` | GET | Interactive operations console dashboard (`frontend/index.html`). |
| `/health` | GET | System health, model readiness (`demo_ready`), and active scenario status. |
| `/api/scenarios` | GET | Available traffic scenarios (`normal`, `embb_surge`, `urllc_burst`, `murllc_storm`, `mixed_stress`). |
| `/api/runs` | POST | Start a new synchronized multi-policy experiment. |
| `/api/pause` | POST | Pause live simulation loop. |
| `/api/resume` | POST | Resume live simulation loop. |
| `/api/reset` | POST | Reset simulators and accumulators to step 0. |
| `/api/step` | POST | Advance one synchronized 100 ms macro step. |
| `/api/spike` | POST | Inject a runtime demand surge across all policies simultaneously. |
| `/api/status` | GET | Real-time run status, current step, and client subscriber count. |
| `/api/summary` | GET | Cumulative whole-run metrics across all three policies. |
| `/ws` | WebSocket | Live streaming of synchronized 100 ms macro-interval telemetry. |

---

## Project Structure

```
├── frontend/               # Interactive operations dashboard
│   ├── index.html          # HTML5 single-page application console
│   ├── styles.css          # Control-room visual styling & tokens
│   └── app.js              # Real-time WebSocket streaming & Chart.js logic
├── backend/
│   ├── app/
│   │   ├── api/            # API routers and dependencies
│   │   ├── control/        # Safety Shield & Policy Execution Pipeline
│   │   ├── evaluation/     # SLA evaluation engine & accumulators
│   │   ├── policies/       # Static, Heuristic, and RL policy inference
│   │   ├── rl/             # Observation adapter, action mapping, Gymnasium env, reward
│   │   ├── schemas/        # Pydantic data contracts (actions, config, state, telemetry)
│   │   ├── services/       # ExperimentRunner multi-policy coordinator
│   │   ├── simulator/      # Fallback network simulator, queues, radio, compute, traffic
│   │   └── main.py         # FastAPI application entry point & static mount
│   ├── artifacts/          # Evaluation results, trained RL checkpoints, run logs
│   └── tests/              # 88 comprehensive unit, integration, & UI tests
├── docs/                   # Architectural specifications and phase reports
├── models/                 # Pre-trained PPO model checkpoint (models/agent.zip)
└── scenarios/              # Default configuration and scenario definitions (default.json)
```
