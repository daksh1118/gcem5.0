# Phase 5 — Constrained Reward & Lagrangian Dual Formulation

## 1. Problem Formulation: Constrained Markov Decision Process (CMDP)

In network slicing, standard average-reward reinforcement learning exhibits an inherent failure mode: because eMBB represents 70–80% of aggregate traffic volume, an unconstrained agent will starve URLLC packets (which represent only 5–10% of volume) to maximize aggregate throughput.

To prevent this, SLA Guardian formulates resource allocation as a **Constrained Markov Decision Process (CMDP)**:

$$\max_{\pi} \mathbb{E}\left[\sum_{t=0}^{T} \gamma^t R_{\text{service}, t}(\text{eMBB})\right] \quad \text{subject to} \quad \bar{C}_{\text{critical}} \le C_{\text{limit}}$$

Where:
- $R_{\text{service}, t}$: eMBB service satisfaction.
- $\bar{C}_{\text{critical}}$: Empirical packet violation rate on mission-critical slices (URLLC + mURLLC).
- $C_{\text{limit}} = 0.01$: Maximum allowable critical packet drop rate (1.0%).

---

## 2. Multi-Objective Reward Terms

Implemented in [`backend/app/rl/reward.py`](file:///c:/gcemhacks5.0/backend/app/rl/reward.py) and [`backend/app/rl/cost.py`](file:///c:/gcemhacks5.0/backend/app/rl/cost.py):

### A. Primary eMBB Service Reward ($R_{\text{service}}$)
$$R_{\text{service}} = \text{clip}\left(\frac{\text{delivered\_packets}_{\text{eMBB}}}{\max(1, \text{offered\_packets}_{\text{eMBB}} + \min(\text{pending}_{\text{eMBB}}, 200))}, 0.0, 1.0\right)$$
- Measures the fraction of offered eMBB demand and backlog that was successfully transmitted across radio and processed by edge-compute.
- Uses a non-zero denominator guard ($\max(1, \cdot)$) preventing division-by-zero during low traffic.
- Clamped to $[0.0, 1.0]$.

### B. Critical Slice Violation Cost ($C_{\text{critical}}$)
$$C_{\text{critical}} = \frac{\text{dropped\_packets}_{\text{URLLC}} + \text{dropped\_packets}_{\text{mURLLC}}}{\max(1, \text{offered\_packets}_{\text{URLLC}} + \text{offered\_packets}_{\text{mURLLC}})}$$
- Measures the empirical packet drop rate on critical slices due to queue buffer overflow or packet deadline expiration.
- If zero critical packets were offered during the interval, $C_{\text{critical}} = 0.0$.
- Strictly bounded in $[0.0, 1.0]$.

### C. Total Training Reward ($R_{\text{training}}$)
$$R_{\text{training}} = R_{\text{service}} - \lambda \cdot C_{\text{critical}}$$
- When critical slices experience zero drops, $R_{\text{training}} = R_{\text{service}} \in [0.0, 1.0]$.
- When drops occur, the agent is penalized by $\lambda \cdot C_{\text{critical}}$.

---

## 3. Episodic Lagrangian Dual Multiplier Update

Implemented in [`backend/app/rl/lagrangian.py`](file:///c:/gcemhacks5.0/backend/app/rl/lagrangian.py):

Rather than using an arbitrary static penalty, the multiplier $\lambda$ dynamically adapts at the conclusion of each completed episode $k$:

$$\lambda_{k+1} = \text{clip}\left(\lambda_k + \alpha_{\text{lagrange}} \cdot (\bar{C}_k - C_{\text{limit}}), \; 0.0, \; \lambda_{\max}\right)$$

### Hyperparameters:
- Initial multiplier: $\lambda_0 = 0.0$
- Dual learning rate: $\alpha_{\text{lagrange}} = 0.05$
- Constraint limit: $C_{\text{limit}} = 0.01$ (1%)
- Maximum multiplier bound: $\lambda_{\max} = 50.0$

### Dual Update Mechanics:
- **Case 1: Safe Operation ($\bar{C}_k \le 0.01$):** $(\bar{C}_k - C_{\text{limit}}) \le 0$. $\lambda$ decreases or remains at $0.0$. The agent focuses on optimizing eMBB bandwidth.
- **Case 2: Constraint Violation ($\bar{C}_k > 0.01$):** $(\bar{C}_k - C_{\text{limit}}) > 0$. $\lambda$ increases, intensifying the penalty on critical drops during subsequent rollouts.

---

## 4. Diagnostics & Observability

Every macro-step outputs full component metrics in the Gymnasium `info` dictionary:
- `service_reward`: Instantaneous eMBB satisfaction score.
- `critical_cost`: Instantaneous critical violation rate.
- `lambda_val`: Active multiplier value.
- `training_reward`: Composite reward passed to PPO optimizer.
- `throughput_embb_mbps`, `throughput_urllc_mbps`, `throughput_murllc_mbps`.
- `shield_intervention`: Boolean flag indicating whether Safety Shield intervened.
- `shield_reasons`: Structured tags (e.g. `OVER_RADIO_BUDGET`).
