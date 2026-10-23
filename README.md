# SLA Guardian: 5G Network Slicing & Resource Allocation

An intelligent, safety-critical 5G network slicing and edge-compute resource allocation prototype utilizing Constrained Reinforcement Learning (PPO with Lagrangian multipliers) and a deterministic Safety Shield.

---

## Features

- **Multi-Policy Simulation Engine:** Runs Static Baseline, Adaptive Demand Heuristic, and Constrained PPO Agent concurrently on matched 5G traffic.
- **Deterministic Safety Shield:** Guarantees minimum PRB and compute reservations for mission-critical slices (URLLC & mURLLC) before commands reach the network simulator.
- **Constrained RL with Lagrangian Multiplier:** Optimizes eMBB throughput while enforcing critical-slice violation constraints.
- **Real-Time Telemetry Streaming:** Exposes WebSocket (`/ws`) at 10 Hz cadence and full REST control endpoints (`/api/runs`, `/api/spike`, `/api/reset`, `/api/pause`, `/api/summary`).
- **Reproducible Abstracted Simulation:** Coupled OFDMA radio scheduling, stochastic Rayleigh fading, and multi-tenant edge compute processing.

---

## Quickstart

### 1. Environment Activation & Dependencies
```powershell
# Dependencies are verified in .venv (CPU only, Python 3.11)
.\.venv\Scripts\activate
```

### 2. Start the Backend API Server
```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

### 3. Run Automated Tests
```powershell
# Run the entire test suite (81 tests)
.\.venv\Scripts\python.exe -m pytest backend/tests -v
```

---

## REST & WebSocket API Overview

| Endpoint | Method | Description |
| :--- | :--- | :--- |
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
│   │   └── main.py         # FastAPI application entry point
│   ├── artifacts/          # Evaluation results, trained RL checkpoints, run logs
│   └── tests/              # 81 comprehensive unit & integration tests
├── docs/                   # Architectural specifications and phase reports
├── models/                 # Pre-trained PPO model checkpoint (models/agent.zip)
└── scenarios/              # Default configuration and scenario definitions (default.json)
```
