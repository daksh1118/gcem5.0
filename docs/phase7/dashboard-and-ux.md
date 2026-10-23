# Phase 7: Interactive Three-Policy Dashboard & Demo Experience

This document details the frontend architecture, visual design system, WebSocket integration, and demo presentation controls for the **SLA Guardian** interactive operations console.

---

## 1. UI Component Hierarchy & Architecture

The user interface is built as a zero-build, laptop-friendly, single-page application using HTML5, modern CSS, vanilla JavaScript, and Chart.js for data visualization.

```mermaid
graph TD
    Dashboard[index.html: SLA Guardian Console]
    
    subgraph Navigation & Health
        Dashboard --> TopNav[Top Navigation Bar]
        TopNav --> LiveBeacon[Connection Beacon (WS Status)]
        TopNav --> ModelBadge[Model Status Badge]
        TopNav --> RunBadge[Run Status (Idle/Running/Paused)]
        TopNav --> StepPill[Step Counter & Sim Clock]
    end

    subgraph Control Room Toolbar
        Dashboard --> Toolbar[Control Toolbar]
        Toolbar --> ScenSelect[Scenario Selector (5 Profiles)]
        Toolbar --> SeedInput[Seed & Step Config]
        Toolbar --> ActionButtons[Start / Pause / Resume / Step / Reset]
        Toolbar --> QuickSpikes[Quick Burst Triggers (eMBB/URLLC/mURLLC)]
    end

    subgraph Three-Panel Comparison Grid
        Dashboard --> Grid[Three-Policy Slicing Grid]
        Grid --> StaticPanel[Panel 1: Static Baseline (Fixed 45/25/30)]
        Grid --> HeuristicPanel[Panel 2: Adaptive Heuristic (Demand-Aware)]
        Grid --> AgentPanel[Panel 3: SLA Guardian (Constrained PPO + Shield)]
        
        StaticPanel --> SlaCards1[Per-Slice SLA Badges]
        StaticPanel --> StackedBars1[Radio & Compute Stacked Bars]
        StaticPanel --> Diags1[Offered / Delivered / Dropped / Backlog]
        
        HeuristicPanel --> SlaCards2[Per-Slice SLA Badges]
        HeuristicPanel --> StackedBars2[Radio & Compute Stacked Bars]
        HeuristicPanel --> Diags2[Offered / Delivered / Dropped / Backlog]

        AgentPanel --> SlaCards3[Per-Slice SLA Badges]
        AgentPanel --> StackedBars3[Radio & Compute Stacked Bars]
        AgentPanel --> Diags3[Offered / Delivered / Dropped / Backlog]
        AgentPanel --> LambdaGauge[Lagrangian Multiplier λ]
        AgentPanel --> RationaleBox[Grounded Decision Explainability]
    end

    subgraph Comparison & Analytics
        Dashboard --> Analytics[Global Analytics & History]
        Analytics --> Charts[Comparative Time-Series Charts (Throughput / Drops / Utilization)]
        Analytics --> Scoreboard[Cumulative Scoreboard Table]
        Analytics --> EventFeed[Real-Time Audit Event Stream]
    end
```

---

## 2. Visual Design System

The console utilizes a dark control-room theme engineered for high legibility under demo and projection conditions.

| Token | Hex Value | Usage |
| :--- | :--- | :--- |
| `var(--bg-base)` | `#0B1220` | Root background |
| `var(--bg-panel)` | `#111B2E` | Elevated panel backgrounds |
| `var(--bg-card)` | `#16243D` | Individual metric & diagnostic cards |
| `var(--border-strong)`| `#263449` | High-contrast component borders |
| `var(--slice-embb)` | `#3B82F6` | eMBB High-Throughput slice (Electric Blue) |
| `var(--slice-urllc)` | `#14B8A6` | URLLC Mission-Critical slice (Teal) |
| `var(--slice-murllc)`| `#F59E0B` | mURLLC Sensor Telemetry slice (Amber) |
| `var(--status-pass)` | `#10B981` | SLA Pass & Shield verified (Emerald) |
| `var(--status-breach)`| `#EF4444` | True SLA Breach & packet drops (Crimson) |

---

## 3. Real-Time Telemetry & WebSocket Event Handling

The dashboard connects to `ws://127.0.0.1:8000/ws` upon initialization.

### Lifecycle & Resilience
1. **Initial Snapshot:** On connection, the server immediately emits a full `TelemetryEvent` snapshot of the active state.
2. **Streaming Cadence:** During active runs, updates stream at 10 Hz (every 100 ms macro interval).
3. **Monotonic Sequence Enforcement:** Incoming packets with sequence numbers strictly less than `state.lastSequenceNumber` are dropped to prevent out-of-order rendering.
4. **Auto-Reconnection:** If the connection drops, the live beacon transitions to red (`DISCONNECTED`), data is marked stale, and exponential retry reconnects within 3 seconds.
5. **Memory Bounds:** Historical chart buffers and the chronological event feed retain a maximum of 40 and 30 items respectively, preventing browser memory leaks during extended demonstrations.

---

## 4. Grounded Agent Explainability

The SLA Guardian panel directly displays the mathematical factors driving the PPO policy:
1. **Lagrangian Multiplier ($\lambda$):** Displayed in real time (e.g., $\lambda = 9.648$). Indicates the dynamic penalty weight enforcing critical slice constraints against eMBB throughput greediness.
2. **Critical Slice Cost ($C_{\text{critical}}$):** Shows measured packet drops across URLLC and mURLLC cohorts ($0.0000$ during safe operation).
3. **Safety Shield Interventions:** Reflects whether the Shield validated proposals unmodified (`PASSED`), adjusted over-allocations (`CORRECTED`), or blocked non-finite commands (`REJECTED`).
4. **Grounded Rationale Stream:** Decision rationale text is generated strictly from verified allocation Deltas relative to slice reservations, preventing fabricated or misleading statements.

---

## 5. Known Visualization and Simulation Limitations

1. **Theoretical Latency Floor (9.5 ms):** Because the Python discrete simulation operates on $\Delta t = 10\text{ ms}$ sub-steps, uniform arrival distribution produces a minimum 95th percentile waiting time of $9.5$ ms. Consequently, URLLC target latency ($5.0$ ms) triggers a step breach even when 100% of packets are delivered without drops. The UI accurately reports `"BREACH"` without masking the truth.
2. **Abstract Resource Units:** Radio PRBs and Compute cores are abstract 0–100 capacity units rather than full 3GPP PHY-layer numerologies.

---

## 6. Demo Presentation Walkthrough

### Recommended Presentation Flow
1. **Initial State Inspection:**
   - Open `http://127.0.0.1:8000/`.
   - Point out top bar: Model `PPO LOADED`, status `IDLE`, connection `CONNECTED`.
   - Show symmetric starting partitions across all 3 panels.
2. **Nominal Balanced Load (`normal`):**
   - Click **▶ Start**.
   - Observe PPO dynamic allocation: safely shifting surplus PRBs from under-utilized URLLC/mURLLC to boost eMBB throughput from 26.5 Mbps to ~37.7 Mbps (+42% gain).
   - Point out that URLLC and mURLLC packet delivery ratios remain at 1.0000 (zero drops).
3. **Surge Stress Test (`embb_surge` or Trigger Burst):**
   - Click **⚡ URLLC x4** quick burst button.
   - Point out how the reactive Heuristic causes packet drops on other slices due to abrupt switching.
   - Point out how the Safety Shield and Lagrangian constraint protect URLLC allocations on SLA Guardian, maintaining zero critical drops and bounded allocation churn.
4. **Pause & Step Inspection:**
   - Click **⏸ Pause** to freeze simulation state for detailed inspection.
   - Click **⏭ Step** to advance discrete 100 ms intervals step-by-step.
   - Click **↺ Reset** to cleanly return all simulators to step 0.
