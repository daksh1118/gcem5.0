# Phase 5 — Gymnasium Environment Architecture & Observation/Action Contract

## 1. Overview

The `SliceGymnasiumEnv` ([`backend/app/rl/environment.py`](file:///c:/gcemhacks5.0/backend/app/rl/environment.py)) adapts the discrete-event network simulator (`FallbackNetworkSimulator`) into an OpenAI / Farama Gymnasium environment (`gymnasium.Env`) adhering to standard RL interfaces.

The environment bridges the timescale between:
1. **Sub-frame Physical Resource Slicing (10 ms):** Internal discrete-event queue draining, stochastic wireless fading, deadline tracking, and edge User Plane Function (UPF) compute processing.
2. **Macro-Tier Slice Orchestration (100 ms):** Reinforcement Learning macro-control interval where one policy action is held constant across ten internal simulation steps.

---

## 2. Observation Space (12-Dimensional Continuous)

- **Class:** `gymnasium.spaces.Box(low=0.0, high=2.0, shape=(12,), dtype=np.float32)`
- **Builder:** `ObservationAdapter` ([`backend/app/rl/observation.py`](file:///c:/gcemhacks5.0/backend/app/rl/observation.py))

### Feature Structure
Features are strictly ordered by canonical slice identifier: `[eMBB, URLLC, mURLLC]`. Each slice contributes four normalized continuous metrics:

| Index | Slice | Feature Description | Mathematical Formula | Nominal Range |
| :---: | :--- | :--- | :--- | :---: |
| 0 | `eMBB` | Normalized Queue Depth | $\text{clip}\left(\frac{Q_{\text{embb}}}{1000}, 0.0, 1.0\right)$ | $[0.0, 1.0]$ |
| 1 | `eMBB` | Normalized Offered Demand Ratio | $\text{clip}\left(\frac{\text{demand}_{\text{embb}}}{R_{\text{total}}}, 0.0, 2.0\right)$ | $[0.0, 2.0]$ |
| 2 | `eMBB` | Current Radio PRB Share | $\frac{\text{PRB}_{\text{embb}}}{R_{\text{total}}}$ | $[0.0, 1.0]$ |
| 3 | `eMBB` | Current Compute CPU Share | $\frac{\text{CPU}_{\text{embb}}}{C_{\text{total}}}$ | $[0.0, 1.0]$ |
| 4 | `URLLC` | Normalized Queue Depth | $\text{clip}\left(\frac{Q_{\text{urllc}}}{1000}, 0.0, 1.0\right)$ | $[0.0, 1.0]$ |
| 5 | `URLLC` | Normalized Offered Demand Ratio | $\text{clip}\left(\frac{\text{demand}_{\text{urllc}}}{R_{\text{total}}}, 0.0, 2.0\right)$ | $[0.0, 2.0]$ |
| 6 | `URLLC` | Current Radio PRB Share | $\frac{\text{PRB}_{\text{urllc}}}{R_{\text{total}}}$ | $[0.0, 1.0]$ |
| 7 | `URLLC` | Current Compute CPU Share | $\frac{\text{CPU}_{\text{urllc}}}{C_{\text{total}}}$ | $[0.0, 1.0]$ |
| 8 | `mURLLC`| Normalized Queue Depth | $\text{clip}\left(\frac{Q_{\text{murllc}}}{1000}, 0.0, 1.0\right)$ | $[0.0, 1.0]$ |
| 9 | `mURLLC`| Normalized Offered Demand Ratio | $\text{clip}\left(\frac{\text{demand}_{\text{murllc}}}{R_{\text{total}}}, 0.0, 2.0\right)$ | $[0.0, 2.0]$ |
| 10 | `mURLLC`| Current Radio PRB Share | $\frac{\text{PRB}_{\text{murllc}}}{R_{\text{total}}}$ | $[0.0, 1.0]$ |
| 11 | `mURLLC`| Current Compute CPU Share | $\frac{\text{CPU}_{\text{murllc}}}{C_{\text{total}}}$ | $[0.0, 1.0]$ |

All values are guaranteed to be finite, non-negative, and bounded.

---

## 3. Action Space (6-Dimensional Continuous)

- **Class:** `gymnasium.spaces.Box(low=-1.0, high=1.0, shape=(6,), dtype=np.float32)`
- **Decoder:** `ActionMappingAdapter` ([`backend/app/rl/action_mapping.py`](file:///c:/gcemhacks5.0/backend/app/rl/action_mapping.py))

### Action Allocation Vector
$$a = [z_{r, \text{embb}}, z_{r, \text{urllc}}, z_{r, \text{murllc}}, z_{c, \text{embb}}, z_{c, \text{urllc}}, z_{c, \text{murllc}}]$$

### Proportional Softmax Decoding
1. **Independent Softmax:**
   $$\sigma_{r, s} = \frac{\exp(z_{r, s} - \max_j z_{r, j})}{\sum_j \exp(z_{r, j} - \max_j z_{r, j})}, \quad \sigma_{c, s} = \frac{\exp(z_{c, s} - \max_j z_{c, j})}{\sum_j \exp(z_{c, j} - \max_j z_{c, j})}$$
2. **Guaranteed Minimum Reservations:** Feasible minimum baseline reservations ($R_{\min}, C_{\min}$) are guaranteed first:
   - eMBB: $20\text{ PRBs}, 15\text{ Cores}$
   - URLLC: $25\text{ PRBs}, 30\text{ Cores}$
   - mURLLC: $15\text{ PRBs}, 15\text{ Cores}$
3. **Surplus Budget Distribution:** The unreserved remaining capacity ($R_{\text{free}} = R_{\text{total}} - \sum R_{\min} = 40.0$) is distributed proportionally to $\sigma_s$:
   $$R_s = R_{\min, s} + R_{\text{free}} \cdot \sigma_{r, s}, \quad C_s = C_{\min, s} + C_{\text{free}} \cdot \sigma_{c, s}$$
4. **Deterministic Priority Mapping:**
   - URLLC: Priority 10 (Strict preemption / highest weight)
   - mURLLC: Priority 5 (Intermediate sensor telemetry)
   - eMBB: Priority 1 (Best effort broadband)

---

## 4. Safety Shield Boundary & Rejection Semantics

Every proposed action from PPO is validated through `SafetyShield.validate()` before reaching the simulator:
- **Accepted / Corrected:** If the proposal violates budget or reservations, reservation-aware proportional projection clamps it safely without dropping below minimum reservations. The resulting `ExecutedAction` advances the simulator.
- **Rejected:** If non-finite values (NaN/Inf) or unrecoverable inconsistencies occur, `SafetyValidationStatus.REJECTED` is returned. **The simulator clock does not advance**, and a failure penalty is returned to the agent.

---

## 5. Lifecycle & Verification

- **Reset Contract:** `reset(seed=None) -> (obs, info)`. Resets the internal simulator and packet queues, seeds the PRNG, resets episode cost accumulators, but preserves the persistent Lagrangian dual multiplier across episodes.
- **Step Contract:** `step(action) -> (obs, reward, terminated, truncated, info)`. Executes 10 internal steps (100 ms duration), aggregates metrics, and returns truncation when `current_macro_step >= max_macro_steps`.
- **Environment Checks:** Verified with both `stable_baselines3.common.env_checker.check_env()` and `gymnasium.utils.env_checker.check_env()`.
