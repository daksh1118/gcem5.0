# Merged Solution API & Dashboard Contract

This document specifies the FastAPI REST and WebSocket interface connecting the multi-policy simulation orchestrator to the live three-panel dashboard.

---

## 1. REST Endpoints Specification

### A. Health & Diagnostics
- **`GET /health`**
  - **Description:** Verifies service health, active Python environment, and loaded model status.
  - **Response (200 OK):**
    ```json
    {
      "status": "healthy",
      "model_loaded": true,
      "model_path": "models/agent.zip",
      "active_scenario": "normal",
      "macro_step": 42
    }
    ```

### B. Scenario Metadata
- **`GET /scenarios`**
  - **Description:** Returns list of available scenario profiles and parameters.
  - **Response (200 OK):**
    ```json
    {
      "scenarios": [
        {"id": "normal", "description": "Nominal balanced load"},
        {"id": "embb_surge", "description": "eMBB high-throughput video surge"},
        {"id": "urllc_burst", "description": "Sudden mission-critical factory burst"},
        {"id": "murllc_storm", "description": "Massive IoT sensor storm"},
        {"id": "mixed_stress", "description": "Overload testing congestion boundaries"}
      ]
    }
    ```

### C. Live Control Commands
- **`POST /reset`**
  - **Description:** Resets all three policy simulators (`Static`, `Heuristic`, `Agent`) to step 0 with a synchronized seed.
  - **Request Body (Optional):**
    ```json
    {
      "scenario": "normal",
      "seed": 42
    }
    ```
  - **Response (200 OK):**
    ```json
    {
      "status": "reset_successful",
      "scenario": "normal",
      "step": 0
    }
    ```

- **`POST /spike`**
  - **Description:** Injects an instantaneous demand burst into the active simulation run to test live policy responsiveness and Safety Shield interventions.
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
      "duration_steps": 20
    }
    ```

- **`GET /summary`**
  - **Description:** Returns comparative cumulative performance metrics for the three policies.
  - **Response (200 OK):**
    ```json
    {
      "static": {
        "mean_embb_tput_mbps": 26.52,
        "critical_violations": 142,
        "shield_interventions": 0
      },
      "heuristic": {
        "mean_embb_tput_mbps": 42.25,
        "critical_violations": 84,
        "shield_interventions": 0
      },
      "agent": {
        "mean_embb_tput_mbps": 46.80,
        "critical_violations": 9,
        "shield_interventions": 2,
        "current_lambda": 1.45
      }
    }
    ```

---

## 2. Real-Time Streaming Protocol (`WebSocket /ws`)

The dashboard establishes a single WebSocket connection to receive synchronous step updates across all three competing policies.

- **Endpoint:** `ws://localhost:8000/ws`
- **Stream Cadence:** 10 Hz (every 100 ms macro-control interval).

### Message Schema (`PolicyStepUpdate`)
```json
{
  "macro_step": 25,
  "sim_time_sec": 2.500,
  "active_scenario": "normal",
  "spike_active": false,
  "policies": {
    "static": {
      "policy_id": "static_fixed",
      "radio_allocations": {"eMBB": 40.0, "URLLC": 35.0, "mURLLC": 25.0},
      "compute_allocations": {"eMBB": 40.0, "URLLC": 35.0, "mURLLC": 25.0},
      "delivered_tput_mbps": {"eMBB": 26.5, "URLLC": 8.0, "mURLLC": 14.2},
      "p95_latency_ms": {"eMBB": 15.2, "URLLC": 9.5, "mURLLC": 11.2},
      "queue_depths": {"eMBB": 120, "URLLC": 0, "mURLLC": 4},
      "critical_violations": 0,
      "shield_status": "PASSED",
      "intervention_reasons": []
    },
    "heuristic": {
      "policy_id": "adaptive_heuristic",
      "radio_allocations": {"eMBB": 55.0, "URLLC": 25.0, "mURLLC": 20.0},
      "compute_allocations": {"eMBB": 50.0, "URLLC": 30.0, "mURLLC": 20.0},
      "delivered_tput_mbps": {"eMBB": 42.2, "URLLC": 8.0, "mURLLC": 14.1},
      "p95_latency_ms": {"eMBB": 12.1, "URLLC": 9.5, "mURLLC": 10.8},
      "queue_depths": {"eMBB": 18, "URLLC": 0, "mURLLC": 2},
      "critical_violations": 0,
      "shield_status": "PASSED",
      "intervention_reasons": []
    },
    "agent": {
      "policy_id": "constrained_ppo",
      "radio_allocations": {"eMBB": 62.4, "URLLC": 22.6, "mURLLC": 15.0},
      "compute_allocations": {"eMBB": 58.2, "URLLC": 26.8, "mURLLC": 15.0},
      "delivered_tput_mbps": {"eMBB": 47.1, "URLLC": 8.0, "mURLLC": 14.0},
      "p95_latency_ms": {"eMBB": 10.4, "URLLC": 9.4, "mURLLC": 10.5},
      "queue_depths": {"eMBB": 5, "URLLC": 0, "mURLLC": 1},
      "critical_violations": 0,
      "shield_status": "PASSED",
      "intervention_reasons": [],
      "lagrangian_lambda": 1.25,
      "explanation": "eMBB demand high; URLLC/mURLLC demand nominal. Allocating surplus PRBs to eMBB while protecting slice reservations."
    }
  }
}
```

---

## 3. Frontend Dashboard Architecture

- **Path:** `frontend/index.html` (served via FastAPI static mount).
- **Technology:** Pure HTML5, CSS3, vanilla JavaScript, Chart.js from CDN (zero build tools).
- **Layout:**
  1. **Top Control Bar:** Scenario selector dropdown (`normal`, `embb_surge`, `urllc_burst`, `murllc_storm`), Trigger Spike button, Reset button, Connection Status indicator.
  2. **Three Side-by-Side Policy Panels:**
     - Panel 1: **Static Baseline (Fixed Split)**
     - Panel 2: **Adaptive Heuristic Baseline**
     - Panel 3: **SLA Guardian (Constrained PPO + Shield)**
  3. **Visual Components per Panel:**
     - Donut charts for Radio and Compute allocation splits.
     - Live KPI cards: eMBB Throughput (Mbps), Critical Violations Count, Queue Backlog.
     - Safety Shield status pill: Green (`PASSED`), Amber (`CORRECTED`), Red (`REJECTED`).
  4. **Comparative Time-Series Charts (Bottom):**
     - Live line chart 1: eMBB Delivered Throughput over time.
     - Live line chart 2: Cumulative Critical-Slice Packet Violations.
     - Live line chart 3: Lagrangian Multiplier $\lambda(t)$ trajectory.
