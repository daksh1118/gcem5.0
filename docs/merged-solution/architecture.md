# Merged Solution Architecture — SLA Guardian

## 1. Architectural Overview

SLA Guardian unifies discrete-event 5G network slicing simulation with a safe, constrained Reinforcement Learning policy and an inviolable Safety Shield.

The architecture integrates two operational tiers:
1. **Macro-Tier Orchestration (100 ms Control Interval):** The RL policy or baseline controller evaluates aggregated slice metrics and determines radio PRB and compute vCPU share distributions.
2. **Micro-Tier Simulation (10 ms Discrete Timestep):** The `FallbackNetworkSimulator` models Poisson packet arrivals, per-slice queuing, stochastic wireless channel realization, deadline expiration, and multi-stage edge-compute service.

```mermaid
graph TD
    subgraph Traffic & Environment
        TG[Seeded Traffic Generator] -->|Packet Arrivals| RQ[Per-Slice Radio Queues]
        RQ -->|Radio Service 10ms| RM[OFDMA Radio Model]
        RM -->|Forwarding| CQ[Per-Slice Compute Queues]
        CQ -->|Compute Service 10ms| CM[Edge Compute Model]
        CM -->|Completed Packets| SDiag[Simulator Diagnostics]
    end

    subgraph Macro-Tier Control Loop (100 ms)
        SDiag -->|10-step Aggregation| MCA[MacroControlAdapter]
        MCA -->|Normalized Observation| Obs[12-Feature Observation]
        Obs -->|PPO Inference| PPO[Constrained PPO Agent]
        PPO -->|6 Logits| Dec[ActionMappingAdapter]
        Dec -->|ProposedAction| SS[Phase 4 Safety Shield]
        SS -->|Validation / Projection| SR{Safety Result}
        SR -->|REJECTED| Halt[Halt Step / Zero Advance]
        SR -->|ACCEPTED / ExecutedAction| PEP[PolicyExecutionPipeline]
        PEP -->|Holds Action for 10x 10ms steps| FallbackSim[FallbackNetworkSimulator]
    end

    subgraph Constrained Optimization
        SDiag -->|Critical Violations| Cost[ViolationCostAdapter]
        Cost -->|Episode Mean Cost| Lag[LagrangianMultiplier]
        Lag -->|Lambda Penalty| Rew[Lagrangian Reward]
    end
```

---

## 2. Completed Foundation Components (Phases 0–4)

The merged architecture builds upon four thoroughly tested foundational phases:
- **Phase 0:** Validated host environment and selected Python discrete-event fallback over uninstalled ns-3.
- **Phase 1:** Established validated Pydantic data contracts ([`backend/app/schemas/`](file:///c:/gcemhacks5.0/backend/app/schemas/)) and abstract component interfaces ([`backend/app/interfaces/`](file:///c:/gcemhacks5.0/backend/app/interfaces/)).
- **Phase 2:** Delivered `FallbackNetworkSimulator` with queue managers, stochastic channel fading, and packet deadline drops across three canonical slices (`eMBB`, `URLLC`, `mURLLC`).
- **Phase 3:** Built `SlaMetricEvaluator`, `StaticSlicingPolicy` (fixed allocation), and `AdaptiveDemandHeuristicPolicy` (EWMA demand tracking).
- **Phase 4:** Implemented deterministic `SafetyShield` with reservation-aware proportional projection and `PolicyExecutionPipeline` ensuring rejected actions never advance the simulator.

---

## 3. Merged Control Loop & Timing Reconciliations

### 100 ms Macro-Control Interval vs. 10 ms Micro-Timestep
- The physical radio scheduler and packet queues operate on a **10 ms discrete simulation step** ($\Delta t_{\text{sim}} = 0.010\text{ s}$).
- Network slice orchestration operates at a **100 ms macro-control interval** ($T_{\text{macro}} = 0.100\text{ s}$).
- The `MacroControlAdapter` executes 10 consecutive simulator steps using a single validated `ExecutedAction`:
  $$\text{macro\_step}(A_{\text{exec}}) = \sum_{k=1}^{10} \text{simulator.step}(A_{\text{exec}})$$
- Metrics (throughput, offered bytes, delivered packets, drops) are accumulated across the full 100 ms window. Throughput is computed using $T_{\text{macro}} = 0.100\text{ s}$, preventing timescale calculation errors.

---

## 4. Constrained RL & Lagrangian Relaxation

Standard reinforcement learning optimizes average unconstrained return, often starving low-volume URLLC slices to maximize high-bandwidth eMBB throughput. We formulate the problem as a **Constrained Markov Decision Process (CMDP)**:

$$\max_{\pi} \mathbb{E}\left[\sum_{t} \gamma^t R_{\text{service}, t}(\text{eMBB})\right] \quad \text{s.t.} \quad \bar{C}_{\text{critical}} \le C_{\text{limit}}$$

Where:
- $R_{\text{service}, t} = \frac{\text{throughput}_{t, \text{eMBB}}}{\text{target}_{\text{eMBB}}}$: Normalized eMBB delivered service.
- $C_{\text{critical}, t} = \frac{\text{dropped}_{\text{URLLC}} + \text{expired}_{\text{URLLC}} + \text{dropped}_{\text{mURLLC}} + \text{expired}_{\text{mURLLC}}}{\text{offered}_{\text{URLLC}} + \text{offered}_{\text{mURLLC}} + \epsilon}$: Violation rate on critical slices.
- $C_{\text{limit}} = 0.01$ (max 1% allowed critical packet violation rate).

### Lagrangian Multiplier Update
At the conclusion of each episode $k$:
$$\lambda_{k+1} = \max\left(0.0, \; \lambda_k + \alpha_{\text{lagrange}} \cdot (\bar{C}_k - C_{\text{limit}})\right)$$
When critical slice violations exceed 1%, $\lambda$ increases, penalizing the PPO policy during rollouts.

---

## 5. Six-Action PPO Output Contract

The policy outputs six continuous action logits $a \in [-1.0, 1.0]^6$:
- $z_{\text{radio}} = [a_0, a_1, a_2]$ for `[eMBB, URLLC, mURLLC]`
- $z_{\text{compute}} = [a_3, a_4, a_5]$ for `[eMBB, URLLC, mURLLC]`

### Decoding Algorithm:
1. Compute softmax shares independently:
   $$\sigma_{\text{radio}, s} = \frac{\exp(z_{\text{radio}, s})}{\sum_j \exp(z_{\text{radio}, j})}, \quad \sigma_{\text{compute}, s} = \frac{\exp(z_{\text{compute}, s})}{\sum_j \exp(z_{\text{compute}, j})}$$
2. Allocate configured minimum feasible reservations ($R_{\min, s}, C_{\min, s}$).
3. Distribute remaining capacity proportionally to softmax shares:
   $$R_s = R_{\min, s} + \left(R_{\text{total}} - \sum_j R_{\min, j}\right) \cdot \sigma_{\text{radio}, s}$$
   $$C_s = C_{\min, s} + \left(C_{\text{total}} - \sum_j C_{\min, j}\right) \cdot \sigma_{\text{compute}, s}$$
4. Priorities are derived deterministically based on queue latency risk:
   - URLLC: Priority 10 (Highest)
   - mURLLC: Priority 5
   - eMBB: Priority 1

---

## 6. Safety Shield Enforcement

Every proposed allocation from PPO passes through `SafetyShield.validate()`:
1. Validates numerical finiteness (rejects NaN/Inf).
2. Verifies $\sum R_s \le 100.0$ and $\sum C_s \le 100.0$.
3. Verifies slice minimum reservations.
4. If a proposal attempts an over-allocation, reservation-aware proportional projection clamps it safely while preserving slice floors.
5. If an action is rejected, the simulator is frozen and time does not advance.

---

## 7. Future API and Dashboard Integration

- **FastAPI Backend:** Exposes REST metadata and a high-throughput WebSocket (`/ws`) streaming step telemetry for Static, Heuristic, and PPO policies concurrently.
- **Frontend Dashboard:** Lightweight, single-page HTML/JS application using Chart.js (CDN, no npm build step) featuring 3 side-by-side policy panels, real-time violation plots, cumulative scoreboards, and manual spike triggers (`/spike`).

---

## 8. Known Limitations and Non-Guarantees

1. **Abstracted Physical Layer:** The simulation models channel SNR and OFDMA capacity abstractly, not full 3GPP 5G-NR LDPC/Polar coding or mini-slot puncturing.
2. **True System Overload:** Neither the Safety Shield nor the Lagrangian RL agent can prevent packet drops when total offered demand exceeds 100% of physical capacity.
3. **Discretization Floor:** The 10 ms simulation timestep introduces an inherent uniform arrival delay floor ($9.5\text{ ms}$ p95), which must be accounted for during SLA interpretation.
