# SLA Guardian — Phase 1 System Architecture Specification
**Project:** SLA Guardian — Reinforcement Learning-Based Network Slicing and Resource Allocation for 5G  
**Phase:** Phase 1 — Project Scaffolding, Virtual Environment and Shared Data Contracts  
**Status:** Complete  

---

## 1. System Architecture Overview

SLA Guardian is a closed-loop autonomous control and telemetry system designed to dynamically allocate 5G radio resources and edge-compute resources across multi-tenant network slices while strictly enforcing Service Level Agreements (SLAs).

The system architecture separates policy inference from physical execution, sandwiching an active **Safety Shield** between the decision-making engine and the underlying simulator.

```mermaid
graph TD
    subgraph Control Loop
        SIM[5G Simulator / Fallback Engine] -->|NetworkState (t)| POLICY[Allocation Policy / RL Agent]
        POLICY -->|ProposedAction| SAFETY[Safety Shield Controller]
        SAFETY -->|ExecutedAction| SIM
        SIM -->|State Transition| EVAL[Metrics & SLA Evaluator]
        EVAL -->|StepMetrics| API[FastAPI Telemetry Service]
        API -->|WebSocket / REST| DASH[Live Dashboard]
    end
```

---

## 2. Component Boundaries & Responsibilities

### 2.1 Simulator Layer (`backend.app.interfaces.simulator`)
- **Protocol:** `SimulatorInterface`
- **Role:** Encapsulates the discrete-event environment. Advances network dynamics step-by-step ($t \to t + \Delta t$).
- **Crucial Invariant:** The simulator **never** consumes a raw `ProposedAction`. It only accepts an `ExecutedAction` that has been passed through and approved by the Safety Shield.
- **Diagnostics:** Emits `SimulatorDiagnostics` signaling active flows, packet drops, and gym lifecycle events (`terminated`, `truncated`).

### 2.2 Policy Layer (`backend.app.interfaces.policy`)
- **Protocol:** `PolicyInterface`
- **Role:** Observes `NetworkState` and outputs a `ProposedAction`.
- **Implementations:** Designed to support interchangeable implementations without API modifications:
  1. Static Proportional Allocator (Baseline)
  2. Classical Heuristic (Deficit Round Robin / Queue-Proportional)
  3. Convex / Linear Programming Optimizer
  4. Reinforcement Learning Agent (PPO, Maskable PPO)

### 2.3 Safety Shield Layer (Data Contract: `SafetyResult`)
- **Role:** Acts as an deterministic supervisor enforcing hard constraints:
  - Total resource conservation: $\sum \text{PRB} \le \text{Total Radio Capacity}$, $\sum \text{CPU} \le \text{Total Compute Capacity}$.
  - Minimum slice isolation reservations (e.g. guaranteeing URLLC baseline bandwidth even under eMBB overload).
  - Rapid intervention: Clamps, rebalances, or substitutes fallback allocations when policy proposals violate safety thresholds.
- **Transparency:** Pairs `proposed_action` with `executed_action` inside `SafetyResult` with structured reason strings.

### 2.4 Metrics & Evaluation Layer (`backend.app.interfaces.policy.EvaluatorInterface`)
- **Role:** Observes state transitions $(s_t, a_t, s_{t+1})$ and computes objective telemetry:
  - Throughput (Mbps), p95 latency (ms), packet delivery ratio (PDR).
  - SLA breach detection based on `RunConfig.sla_thresholds`.
  - Radio and compute utilization ratios.
  - Allocation churn / switching cost.
- **Decoupling Rule:** Raw empirical measurements are strictly kept distinct from RL `reward_components`.

### 2.5 API & Presentation Layer (`backend.app.main`)
- **Role:** Serves REST endpoints for run initialization, scenario loading, and configuration introspection, as well as WebSocket streams for live dashboard visualization.

---

## 3. Distinction: ProposedAction vs. ExecutedAction

A central design principle in SLA Guardian is that an AI policy's output is an **advisory proposal**, not an execution mandate:

| Attribute | `ProposedAction` | `ExecutedAction` |
| :--- | :--- | :--- |
| **Origin** | Policy (RL agent, heuristic, solver) | Safety Shield (after validation/clamping) |
| **Consumer** | Safety Shield | Simulator (`SimulatorInterface.step()`) |
| **Integrity** | May contain unvalidated or unsafe values | Mathematically guaranteed safe & budget-compliant |
| **Metadata** | `policy_id`, exploratory logits | `is_modified_by_safety`, `proposal_reference` |

---

## 4. Where the Edge-Compute Model Belongs

In 3GPP 5G architectures, network slicing spans both the **Radio Access Network (RAN)** and the **Edge Compute Host (MEC / UPF)**.

$$\text{End-to-End Latency} = \text{Radio Transmission Delay} + \text{RAN Queuing Delay} + \text{Transport Delay} + \text{Edge Compute Processing Delay}$$

1. **Why Radio Slicing Alone Fails:** Even if URLLC radio transmission achieves sub-millisecond air-interface latency, a saturated edge microservice will cause large compute queuing delays, violating the overall end-to-end SLA.
2. **Architectural Placement:**
   - The edge-compute model belongs inside the **Simulator Engine** as a coupled stage following radio packet egress.
   - Slices compete for compute capacity (CPU cores / execution slots) just as they compete for physical resource blocks (PRBs).
   - `AllocationAction` carries distinct allocations for **both** radio and compute dimensions.

---

## 5. Current Fallback Simulator Limitations

In Phase 1, the fallback simulator interface is formally established, but full continuous-time physical layer dynamics are not yet integrated:
- **Radio Abstraction:** Radio capacity is modeled in abstract resource blocks / capacity units rather than detailed 3GPP NR LDPC/Polar coding and MIMO beamforming.
- **Simplified Propagation:** Radio channels will use statistical fading distributions (Rayleigh / Rician) rather than 3D ray-tracing.
- **Traffic Aggregation:** Traffic is generated as flow bursts at discrete step intervals ($\Delta t = 10\text{ ms}$) rather than continuous nanosecond packet interrupts.
- **Future ns-3 Integration:** The interfaces (`SimulatorInterface`) are intentionally small and POSIX-agnostic so that an ns-3/5G-LENA socket/IPC adapter can replace the fallback simulator in future phases without altering schemas or policies.
