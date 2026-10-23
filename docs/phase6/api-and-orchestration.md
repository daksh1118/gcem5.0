# Phase 6: FastAPI Backend, Live Telemetry Streaming & Orchestration

This document details the backend orchestration and API layer for **SLA Guardian**, connecting the multi-policy simulation engine to live dashboard clients.

---

## 1. System Architecture & Module Boundaries

The backend orchestrator synchronizes three competing policies on identical 5G traffic scenarios, passing all resource allocation proposals through a deterministic Safety Shield before advancing the network simulator.

```mermaid
graph TD
    Client[Web Dashboard / WebSocket Client] -->|HTTP REST / WebSocket /ws| FastAPI[FastAPI Application (backend/app/main.py)]
    FastAPI --> Runner[ExperimentRunner (backend/app/services/experiment_runner.py)]
    
    subgraph Multi-Policy Execution Pipeline (100 ms Macro Interval)
        Runner -->|Synchronized Seed| StaticSim[Static Policy Simulator]
        Runner -->|Synchronized Seed| HeuristicSim[Heuristic Policy Simulator]
        Runner -->|Synchronized Seed| AgentSim[PPO Policy Simulator]
        
        StaticPolicy[Static Policy] -->|Proposal| Shield1[Safety Shield] -->|ExecutedAction| StaticSim
        HeuristicPolicy[Heuristic Policy] -->|Proposal| Shield2[Safety Shield] -->|ExecutedAction| HeuristicSim
        RLPolicy[PPO Agent (models/agent.zip)] -->|Proposal| Shield3[Safety Shield] -->|ExecutedAction| AgentSim
    end
    
    StaticSim -->|Diagnostics| Evaluator1[SLA Evaluator]
    HeuristicSim -->|Diagnostics| Evaluator2[SLA Evaluator]
    AgentSim -->|Diagnostics| Evaluator3[SLA Evaluator]
    
    Evaluator1 --> Runner
    Evaluator2 --> Runner
    Evaluator3 --> Runner
    
    Runner -->|TelemetryEvent Broadcast (10 Hz)| FastAPI
    FastAPI -->|JSON Stream| Client
    Runner -->|Persist Run Data| RunStorage[backend/artifacts/runs/<run_id>/]
```

### Key Modules
- **`backend/app/main.py`**: FastAPI application entry point, route definitions, CORS, and lifespan management.
- **`backend/app/services/experiment_runner.py`**: Core multi-policy coordinator managing simulators, policies, Safety Shield execution, background stepping loops, WebSocket client dispatch, and run persistence.
- **`backend/app/schemas/telemetry.py`**: Pydantic data models for requests, live step updates, and comparative summaries.
- **`backend/artifacts/runs/<run_id>/`**: Local file storage for run configurations, per-step telemetry logs, and final evaluation summaries.

---

## 2. API Endpoint Contracts

### A. Health & Diagnostics
- **`GET /health`**
  - Verifies service operational status, model availability, and active run metadata.
  - Distinguishes basic API operation from full three-policy demo readiness (`demo_ready`).
  - **Example Response (200 OK):**
    ```json
    {
      "status": "healthy",
      "service": "SLA Guardian",
      "version": "0.2.0",
      "phase": "Phase 6 - FastAPI Backend & Telemetry Streaming",
      "demo_ready": true,
      "model_loaded": true,
      "model_path": "C:\\gcemhacks5.0\\models\\agent.zip",
      "model_error": null,
      "active_scenario": "normal",
      "macro_step": 0,
      "run_status": "idle"
    }
    ```

### B. Scenario Listing
- **`GET /api/scenarios`** (Alias: `GET /scenarios`)
  - Returns real scenario profiles and thresholds dynamically from `scenarios/default.json`.
  - Scenarios: `normal`, `embb_surge`, `urllc_burst`, `murllc_storm`, `mixed_stress`.
  - **Example Response (200 OK):**
    ```json
    {
      "scenario_id": "default_three_slice_baseline",
      "total_radio_capacity": 100.0,
      "total_compute_capacity": 100.0,
      "scenarios": [
        {"id": "normal", "description": "Steady-state offered demand within nominal network capacity.", "nominal_demand_mbps": {"eMBB": 45.0, "URLLC": 8.0, "mURLLC": 15.0}},
        {"id": "embb_surge", "description": "High-throughput video streaming surge testing capacity headroom.", "nominal_demand_mbps": {"eMBB": 85.0, "URLLC": 8.0, "mURLLC": 15.0}},
        {"id": "urllc_burst", "description": "Sudden 4x surge in URLLC mission-critical tactile demand.", "burst_multiplier": 4.0},
        {"id": "murllc_storm", "description": "Massive IoT sensor telemetry storm testing connection density.", "storm_multiplier": 3.0},
        {"id": "mixed_stress", "description": "High simultaneous load testing congestion and Safety Shield intervention."}
      ]
    }
    ```

### C. Experiment Lifecycle Control
- **`POST /api/runs`** (Alias: `POST /runs`)
  - Starts a new synchronized experiment, resetting simulators and accumulators.
  - Cancels and replaces any existing run task atomically under an async lock.
  - **Request Body:**
    ```json
    {
      "scenario": "normal",
      "seed": 42,
      "max_macro_steps": 100,
      "selected_policies": ["static", "heuristic", "agent"]
    }
    ```
  - **Response (201 Created):**
    ```json
    {
      "run_id": "run_20261023_100000_normal",
      "status": "running",
      "scenario": "normal",
      "seed": 42,
      "max_macro_steps": 100
    }
    ```

- **`POST /api/pause`** / **`POST /api/resume`**
  - Pauses or resumes the live background stepping loop.
  - **Response (200 OK):**
    ```json
    {
      "status": "paused",
      "macro_step": 25
    }
    ```

- **`POST /api/reset`** (Alias: `POST /reset`)
  - Resets all policy environments, packet queues, and accumulators to step 0.
  - Guarantees zero cross-run state or sample leakage.
  - **Request Body (Optional):**
    ```json
    {
      "scenario": "embb_surge",
      "seed": 42
    }
    ```

- **`POST /api/step`**
  - Triggers exactly one manual synchronized 100 ms macro step (useful for stepped debugging).

- **`POST /api/spike`** (Alias: `POST /spike`)
  - Injects a demand surge into all three policy simulators simultaneously.
  - **Request Body:**
    ```json
    {
      "target_slice": "URLLC",
      "multiplier": 4.0,
      "duration_steps": 20
    }
    ```
  - **Response (200 OK):**
    ```json
    {
      "status": "spike_injected",
      "target_slice": "URLLC",
      "multiplier": 4.0,
      "duration_steps": 20,
      "start_step": 12
    }
    ```

### D. Status & Cumulative Results
- **`GET /api/status`**
  - Returns current execution status, simulation clock, and client count.

- **`GET /api/summary`** (Alias: `GET /summary`)
  - Derives whole-run metrics across all policies from true accumulators (not averaged per-step rates).
  - Includes mean eMBB throughput, critical violations, shield interventions, breach ratio, and resource utilization.

---

## 3. Real-Time WebSocket Telemetry Protocol (`WS /ws`)

Subscribers connect to `ws://127.0.0.1:8000/ws` to receive live step updates at 10 Hz cadence.

### Telemetry Event Schema (`TelemetryEvent`)
```json
{
  "run_id": "run_20261023_100000_normal",
  "sequence_number": 42,
  "macro_step": 42,
  "sim_time_sec": 4.200,
  "active_scenario": "normal",
  "spike_active": false,
  "run_status": "running",
  "seed": 42,
  "synchronization_status": "perfect_matched_seed",
  "policies": {
    "static": {
      "policy_id": "static_slicing_baseline",
      "policy_version": "1.0.0",
      "radio_allocations": {"eMBB": 45.0, "URLLC": 25.0, "mURLLC": 30.0},
      "compute_allocations": {"eMBB": 45.0, "URLLC": 25.0, "mURLLC": 30.0},
      "delivered_tput_mbps": {"eMBB": 26.5, "URLLC": 8.0, "mURLLC": 14.1},
      "p95_latency_ms": {"eMBB": 46.9, "URLLC": 9.6, "mURLLC": 13.8},
      "pdr": {"eMBB": 0.588, "URLLC": 1.0, "mURLLC": 1.0},
      "offered_packets": {"eMBB": 395, "URLLC": 40, "mURLLC": 37},
      "delivered_packets": {"eMBB": 235, "URLLC": 40, "mURLLC": 37},
      "dropped_packets": {"eMBB": 0, "URLLC": 0, "mURLLC": 0},
      "pending_packets": {"eMBB": 160, "URLLC": 0, "mURLLC": 0},
      "queue_depths": {"eMBB": 160, "URLLC": 0, "mURLLC": 0},
      "critical_violations": 0,
      "sla_status": {"eMBB": false, "URLLC": false, "mURLLC": true},
      "sla_state_details": {"eMBB": "BREACH", "URLLC": "BREACH", "mURLLC": "PASS"},
      "shield_status": "PASSED",
      "intervention_reasons": []
    },
    "heuristic": {
      "policy_id": "adaptive_demand_heuristic",
      "policy_version": "1.0.0",
      "radio_allocations": {"eMBB": 57.3, "URLLC": 25.0, "mURLLC": 17.7},
      "compute_allocations": {"eMBB": 55.0, "URLLC": 30.0, "mURLLC": 15.0},
      "delivered_tput_mbps": {"eMBB": 42.1, "URLLC": 8.0, "mURLLC": 14.0},
      "p95_latency_ms": {"eMBB": 15.2, "URLLC": 9.5, "mURLLC": 11.2},
      "pdr": {"eMBB": 0.921, "URLLC": 1.0, "mURLLC": 1.0},
      "offered_packets": {"eMBB": 395, "URLLC": 40, "mURLLC": 37},
      "delivered_packets": {"eMBB": 370, "URLLC": 40, "mURLLC": 37},
      "dropped_packets": {"eMBB": 0, "URLLC": 0, "mURLLC": 0},
      "pending_packets": {"eMBB": 25, "URLLC": 0, "mURLLC": 0},
      "queue_depths": {"eMBB": 25, "URLLC": 0, "mURLLC": 0},
      "critical_violations": 0,
      "sla_status": {"eMBB": false, "URLLC": false, "mURLLC": true},
      "sla_state_details": {"eMBB": "BREACH", "URLLC": "BREACH", "mURLLC": "PASS"},
      "shield_status": "PASSED",
      "intervention_reasons": []
    },
    "agent": {
      "policy_id": "constrained_ppo",
      "policy_version": "1.0.0",
      "radio_allocations": {"eMBB": 60.0, "URLLC": 25.0, "mURLLC": 15.0},
      "compute_allocations": {"eMBB": 55.0, "URLLC": 30.0, "mURLLC": 15.0},
      "delivered_tput_mbps": {"eMBB": 37.7, "URLLC": 8.0, "mURLLC": 14.0},
      "p95_latency_ms": {"eMBB": 18.4, "URLLC": 9.5, "mURLLC": 12.1},
      "pdr": {"eMBB": 0.837, "URLLC": 1.0, "mURLLC": 1.0},
      "offered_packets": {"eMBB": 395, "URLLC": 40, "mURLLC": 37},
      "delivered_packets": {"eMBB": 331, "URLLC": 40, "mURLLC": 37},
      "dropped_packets": {"eMBB": 0, "URLLC": 0, "mURLLC": 0},
      "pending_packets": {"eMBB": 64, "URLLC": 0, "mURLLC": 0},
      "queue_depths": {"eMBB": 64, "URLLC": 0, "mURLLC": 0},
      "critical_violations": 0,
      "sla_status": {"eMBB": false, "URLLC": false, "mURLLC": true},
      "sla_state_details": {"eMBB": "BREACH", "URLLC": "BREACH", "mURLLC": "PASS"},
      "shield_status": "PASSED",
      "intervention_reasons": [],
      "lagrangian_lambda": 9.648,
      "critical_cost": 0.000,
      "explanation": "Allocating +15.0 PRBs surplus to eMBB while protecting URLLC/mURLLC reservations."
    }
  }
}
```

---

## 4. Scenario Synchronization & Fairness

All three policies execute on separate simulator instances seeded with the **exact same random seed** (`seed=42`).
1. **Traffic Determinism:** `TrafficGenerator` uses an isolated seeded NumPy RNG whose state transitions depend only on step counter and time, ensuring all three instances see identical exogenous packet arrivals.
2. **Channel Fading Synchronization:** `RadioModel` draws identical Rayleigh power fading multipliers per step across instances.
3. **Spike Synchronization:** Injected spikes specify the target slice, multiplier, and start step, and are applied simultaneously to all three simulators.

---

## 5. Model Loading & Degradation Handling

- The PPO model is loaded from **`models/agent.zip`** during startup.
- **Inference Only:** No model training occurs during server initialization.
- **Degraded Health Mode:** If `models/agent.zip` is missing or corrupted:
  - `GET /health` reports `"status": "degraded"` and `"demo_ready": false`.
  - The API does NOT crash or silently replace the agent with a heuristic.
  - Actionable guidance is exposed via `model_error`.

---

## 6. Run Persistence

Completed experiments automatically persist to `backend/artifacts/runs/<run_id>/`:
- **`config.json`**: Initial parameters (scenario, seed, step budget, timestamp).
- **`summary.json`**: Final multi-policy comparative metrics.
- **`telemetry.jsonl`**: Full per-step telemetry history for replay and offline analysis.
- **Retention:** Newest 10 runs are retained; older runs are automatically pruned.

---

## 7. Startup and Testing Commands

### Virtual Environment Activation & Server Startup
```powershell
# Start Uvicorn development server on localhost:8000
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

### Running Integration Tests
```powershell
# Run API and orchestration integration test suite
.\.venv\Scripts\python.exe -m pytest backend/tests/test_api_orchestration.py -v

# Run the complete test suite (81 tests)
.\.venv\Scripts\python.exe -m pytest backend/tests -v
```

---

## 8. Known SLA and Simulation Limitations

1. **Theoretical Latency Floor (9.5 ms):** The simulation models discrete time steps of $\Delta t = 10\text{ ms}$. With uniform packet arrivals within a step, the 95th percentile waiting time has a lower bound of $9.5$ ms. Consequently, the URLLC SLA target of $5.0$ ms is physically unattainable in this discrete abstraction, triggering a step-level breach even when 100% of packets are delivered without drops.
2. **Honest Reporting:** The API and WebSocket accurately report these breaches (`"URLLC": "BREACH"`) without altering thresholds or falsifying SLA compliance.
