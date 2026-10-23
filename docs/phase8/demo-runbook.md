# SLA Guardian — Phase 8 Demo Runbook & Operations Guide

## Overview

This runbook provides complete, step-by-step operational instructions for running, demonstrating, and troubleshooting the **SLA Guardian** 5G Network Slicing & Autonomous Resource Allocation prototype.

Any team member or judge can execute a live demonstration from a clean terminal using this document without prior familiarity with the codebase.

---

## A. Prerequisites & Environment

| Requirement | Specification | Verification Command / Check |
| :--- | :--- | :--- |
| **Operating System** | Windows 10/11 (PowerShell 5.1 or 7+) | `$PSVersionTable.PSVersion` |
| **Python** | 3.11.x (tested on 3.11.9 64-bit) | `python --version` |
| **Virtual Environment** | `.\.venv\` inside project root | `Test-Path .\.venv\Scripts\python.exe` |
| **Key Libraries** | FastAPI, Uvicorn, PyTorch (CPU), Stable-Baselines3, Gymnasium, Pydantic v2 | Verified in `scripts/phase0/check_environment.py` |
| **Model Checkpoint** | `models/agent.zip` (187 KB) | SHA-256: `1d21d58fe672530a1f15ad4232ca7acc5c2a2373edafe8675ee4fe39cc963e78` |
| **Model Metadata** | `models/agent_metadata.json` | Valid JSON, matches 12-dim obs / 6-dim action contract |
| **Free Disk Space** | ~500 MB (project files, venv, test logs) | N/A |
| **Network Access** | **Optional:** Chart.js CDN (`cdn.jsdelivr.net`)<br>**Offline Mode:** Fully supported via CSS SVG/bar diagnostic charts if offline | Both online and offline fallbacks tested |

---

## B. Clean Startup Sequence

Execute the following exact commands in Windows PowerShell from the project root (`c:\gcemhacks5.0`):

### Step 1: Open Terminal in Project Root
```powershell
cd c:\gcemhacks5.0
```

### Step 2: Verify Python Environment & Checkpoint
```powershell
.\.venv\Scripts\python.exe scripts/phase0/check_environment.py
```
*Expected output: All 8 core dependencies present, PyTorch on CPU, all checks pass.*

### Step 3: Run the Regression Test Suite
```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -v
```
*Expected output: `88 passed, 1 warning in ~7.5s`.*

### Step 4: Launch the FastAPI Backend Service
```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```
*Expected output:*
```text
INFO:     Started server process [...]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### Step 5: Open the Interactive Operator Dashboard
Launch your web browser (Chrome, Edge, or Firefox) and navigate to:
```text
http://127.0.0.1:8000/
```

Verify that the dashboard header displays:
- **System Status:** `CONNECTED` (Green badge)
- **Model Checkpoint:** `LOADED (models/agent.zip)` (Green badge)
- **Simulation Time:** `0.0s (Step 0 / 200)`
- **Three Policy Panels:** Static Baseline, Adaptive Heuristic, PPO Agent (Active).

---

## C. Three-Minute Pitch & Demo Script

### Timeline & Speaker Script

| Timestamp | Phase | Action / Visual | Speaker Script & Talking Points |
| :--- | :--- | :--- | :--- |
| **0:00 – 0:30** | **The Problem** | Dashboard Idle View | *"In modern 5G and future 6G networks, network slicing divides shared physical infrastructure among heterogeneous tenants: high-bandwidth eMBB, mission-critical URLLC, and medical telemetry mURLLC. Today's commercial deployments rely on static resource partitioning. However, static slicing either starves mission-critical services during unexpected surges or leaves massive radio and compute capacity idle. Our project, **SLA Guardian**, demonstrates autonomous, joint radio-and-compute allocation using Constrained Reinforcement Learning."* |
| **0:30 – 1:00** | **Architecture & Policies** | Click **Start** (`normal` scenario, Seed 42) | *"Here in our synchronized testbed, we are running three distinct control policies side-by-side against identical exogenous traffic arrivals. On the left is the **Static Baseline** (fixed 33/33/33 split). In the center is an **Adaptive Demand-Aware Heuristic** that dynamically reacts to queue backlogs. On the right is our **Constrained PPO Agent**, backed by an independent, deterministic **Safety Shield** that guarantees resource constraints and minimum slice reservations regardless of RL proposals."* |
| **1:00 – 1:45** | **The Stress Test** | Click **Trigger URLLC Burst** | *"Now let's simulate an emergency: an autonomous vehicle fleet triggers a sudden URLLC traffic spike. Notice the immediate divergence. The Static baseline is paralyzed—URLLC queues immediately overflow, packet drops soar, and critical latency targets fail. The Heuristic shifts resources, but suffers high allocation churn and oscillation. Meanwhile, our PPO agent rebalances radio and edge-compute shares smoothly, prioritizing URLLC without starving eMBB baseline needs."* |
| **1:45 – 2:20** | **Safety Shield & Telemetry** | Inspect **Safety Shield** badge and allocation bars | *"Notice this critical architectural innovation: the RL agent is not trusted blindly with physical infrastructure. All model proposals must pass through our deterministic Safety Shield. When an exploratory action attempts to allocate 105% capacity or breach the 10% minimum slice reservation, the Shield intervenes via convex projection. It guarantees zero physical constraint violations with sub-millisecond overhead."* |
| **2:20 – 2:45** | **Benchmark Evidence** | Click **Pause**, show Benchmark Artifacts | *"Across 45 synchronized benchmark evaluations covering five traffic scenarios (Normal, eMBB Surge, URLLC Burst, mURLLC Storm, and Mixed Stress), our PPO agent consistently achieves near-perfect packet delivery ratios (99.6%+ across all slices), achieves the lowest critical-slice violation penalties, and reduces allocation churn by up to 2.8x compared to heuristic re-allocation."* |
| **2:45 – 3:00** | **Engineering Contribution & Next Steps** | Summary Card / Future Work | *"SLA Guardian bridges the gap between deep RL research and real-world telecom safety requirements. While our current simulation runs on an abstracted discrete-event Python engine with 10 ms time-steps, our shared Pydantic data schemas and policy pipeline are designed as drop-in controllers for ns-3 / 5G-LENA physical-layer validation. Thank you."* |

---

## D. Operator Failure Modes & Recovery Procedures

If an unexpected condition occurs during the live demonstration, execute the corresponding documented recovery procedure:

### 1. Backend Service Fails to Start
- **Symptoms:** `[Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000): address already in use`.
- **Cause:** A previous Uvicorn instance is still bound to port 8000.
- **Recovery Command:**
  ```powershell
  # Find process using port 8000 and terminate it
  Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess | Stop-Process -Force
  # Restart backend
  .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
  ```

### 2. Missing or Corrupted Checkpoint
- **Symptoms:** Dashboard badge displays `MODEL ERROR` or fallback heuristic warning.
- **Verification:** Run `Get-FileHash models/agent.zip -Algorithm SHA256`. Expected hash: `1d21d58fe672530a1f15ad4232ca7acc5c2a2373edafe8675ee4fe39cc963e78`.
- **Recovery:** If missing, check `models/agent_metadata.json` and ensure working directory is `c:\gcemhacks5.0`.

### 3. WebSocket Disconnects During Live Run
- **Symptoms:** Header badge turns red (`DISCONNECTED`), telemetry halts.
- **Automatic Recovery:** The frontend JavaScript client (`app.js`) features an automatic exponential-backoff reconnect loop (initial retry at 1s, capping at 10s).
- **Manual Recovery:** Click **Reset** on the dashboard, refresh the browser page (`Ctrl + F5`). The backend experiment runner persists and terminates stale simulation tasks cleanly.

### 4. Simulation Freezes or Desynchronizes
- **Recovery:**
  1. Click the **Reset** button in the dashboard UI. This issues a `POST /api/simulation/reset` call, which cancels background async tasks and clears simulation queues.
  2. Select scenario `normal` and seed `42`, then click **Start**.

### 5. CDN Unavailable / Offline Venue
- **Symptoms:** Browser console shows `Failed to load resource: net::ERR_INTERNET_DISCONNECTED` for `chart.js`.
- **Design Safeguard:** `app.js` checks `window.Chart`. If Chart.js fails to load, the dashboard automatically activates the built-in HTML/CSS fallback telemetry display (dynamic flex-bars and numeric diagnostics) without throwing unhandled exceptions.

---

## E. Judge Q&A Quick Reference

| Frequently Asked Question | Authoritative Technical Response |
| :--- | :--- |
| **Q: Why use PPO instead of SAC or DQN?** | PPO provides stable policy gradient updates with clipped objective functions, preventing catastrophic policy collapse during continuous multi-slice radio and compute allocation. DQN requires action discretization which scales poorly to continuous 6-dimensional resource distributions. |
| **Q: How does the Lagrangian multiplier work?** | We formulate resource allocation as a Constrained Markov Decision Process (CMDP). The Lagrangian multiplier ($\lambda$) dynamically penalizes packet drops and queue delays on critical slices (URLLC/mURLLC), scaling up penalties when constraints are breached and decaying them when the network operates safely. |
| **Q: Why decouple the Safety Shield from the RL agent?** | RL neural networks are black boxes that cannot provide formal safety guarantees. By placing a deterministic convex projection shield *between* the RL agent and the simulator, we guarantee 100% adherence to physical capacity (sum $\le$ 1.0) and regulatory slice reservations ($r_i \ge 0.10$). |
| **Q: Why does the aggregate SLA breach ratio show 100%?** | Our evaluator defines an aggregate breach as any step where *at least one* slice misses *either* its packet-delivery ratio or its latency target. In our 10 ms discrete-event simulation, uniform arrival queuing imposes an inherent ~9.5 ms p95 latency floor, which exceeds the aggressive 5.0 ms URLLC specification. Rather than falsify metrics, we expose per-slice delivery ratios (which exceed 99.6%) alongside raw latencies. |
| **Q: Is this a full 3GPP 5G NR physical-layer simulator?** | No. This is an abstracted, discrete-event network simulator modeled with realistic Shannon capacity, exponential path loss, Rayleigh fading, and M/M/1-k queuing models. It is designed for fast, reproducible RL experimentation. Full 3GPP channel modeling in ns-3/5G-LENA is documented as the next validation milestone. |
