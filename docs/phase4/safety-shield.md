# Phase 4 — Safety Shield, Resource Constraint Enforcement, and Auditable Action Execution

## 1. Safety Architecture Overview

The **Safety Shield** (`SafetyShield`) is a deterministic, safety-critical verification and correction layer embedded directly into the control pipeline between resource-allocation policies (Static, Adaptive Heuristic, or future Reinforcement Learning agents) and the network simulator (`FallbackNetworkSimulator`).

In network slicing systems, unconstrained or exploratory policies (especially deep reinforcement learning algorithms during early training) may generate malformed, invalid, or capacity-violating resource allocations. If submitted directly to RAN schedulers or compute virtualization orchestrators, such allocations can destabilize physical or virtual infrastructure, trigger resource exhaustion crashes, or starve critical safety-critical slices (e.g., URLLC / mURLLC).

```
+------------------+         ProposedAction          +------------------+
|  Control Policy  | ------------------------------> |   Safety Shield  |
| (Static / Heur / |                                 |  (Deterministic  |
|    Future RL)    |                                 |   Constraints)   |
+------------------+                                 +------------------+
                                                              |
                                                              v
                                                        SafetyResult
                                                       /            \
                                           [REJECTED] /              \ [PASSED / CORRECTED]
                                                     v                v
                                          +--------------+   +------------------+
                                          | Simulator    |   |  ExecutedAction  |
                                          | Remains      |   +------------------+
                                          | Frozen       |            |
                                          +--------------+            v
                                                             +------------------+
                                                             | Fallback Network |
                                                             |    Simulator     |
                                                             +------------------+
```

### Key Architectural Tenets
1. **Policy-Agnostic Operation:** The Shield evaluates proposals strictly based on configured resource capacities, slice reservations, and numerical safety invariants—independent of the policy identity or origin.
2. **Determinism:** Given identical `ProposedAction`, `NetworkState`, and `RunConfig` inputs, `SafetyShield.validate()` produces bitwise identical `SafetyResult` outputs.
3. **Proposal Immutability:** The original `ProposedAction` is never modified in place; audit records preserve the raw proposal alongside the executed action.
4. **Zero-Execution Rejection:** Any proposal containing unrecoverable non-finite values (NaN, $\pm\infty$), missing slices, or infeasible system configurations results in explicit rejection (`SafetyValidationStatus.REJECTED`) with `executed_action = None`. No unvalidated or rejected action ever touches the simulator.

---

## 2. Hard Safety Invariants

For any action to transition from proposal to execution, the Shield strictly verifies the following invariants:

### A. Numerical Validity & Slice Completeness
- Every canonical slice (`eMBB`, `URLLC`, `mURLLC`) must be explicitly present in `radio_allocations`, `compute_allocations`, and `priority_weights`.
- All resource values must be finite numbers: $\forall s \in \mathcal{S}, \; r_s \in [0, \infty), \; c_s \in [0, \infty)$. Any presence of `NaN`, $+\infty$, or $-\infty$ triggers immediate rejection.
- Negative allocations are prohibited. When feasible, negative proposals are bounded to non-negative minimums and flagged as interventions.

### B. Radio Resource Budget
The aggregate Physical Resource Block (PRB) allocation across all slices cannot exceed total system radio capacity:
$$\sum_{s \in \mathcal{S}} \text{radio\_allocation}_s \le R_{\text{total}} \quad (\text{typically } 100.0)$$

### C. Compute Resource Budget
The aggregate processing unit allocation across all slices cannot exceed total system edge compute capacity:
$$\sum_{s \in \mathcal{S}} \text{compute\_allocation}_s \le C_{\text{total}} \quad (\text{typically } 100.0)$$

Radio and compute resources are strictly decoupled and validated independently.

### D. Priority Range Invariants
Slice scheduling priority scores must be finite, non-negative, and respect configured bounds $[P_{\min}, P_{\max}]$ (default $[1.0, 10.0]$):
$$\forall s \in \mathcal{S}, \quad 1.0 \le \text{priority}_s \le 10.0$$

---

## 3. Reservation Feasibility Checks and Infeasibility Semantics

Each slice configuration specifies a minimum guaranteed reservation for both radio and compute resources:
- Radio reservation: $R_{\min, s} = \text{slice\_config}[s].\text{min\_radio\_percent}$
- Compute reservation: $C_{\min, s} = \text{slice\_config}[s].\text{min\_compute\_percent}$

### Feasibility Criteria
A system configuration is **feasible** if and only if the sum of slice reservations does not exceed total capacity:
$$\sum_{s \in \mathcal{S}} R_{\min, s} \le R_{\text{total}} \quad \text{and} \quad \sum_{s \in \mathcal{S}} C_{\min, s} \le C_{\text{total}}$$

### Infeasibility Rejection
If a misconfiguration or contradictory configuration specifies $\sum R_{\min, s} > R_{\text{total}}$ or $\sum C_{\min, s} > C_{\text{total}}$:
- The Safety Shield **refuses to fabricate a compromise or silently violate reservations**.
- The proposal is marked as `SafetyValidationStatus.REJECTED`.
- `executed_action` is explicitly set to `None`.
- `reservation_verified = False` is recorded in the `SafetyResult`.
- The explanation records an audit log: `Configured radio reservations exceed total capacity: X.X > Y.Y`.
- The simulation step halts without advancing time.

---

## 4. Deterministic Projection and Correction Algorithm

When an incoming proposal requests valid numerical values but exceeds resource capacity or violates minimum reservations, the Shield computes a **reservation-aware proportional projection**.

### Multi-Stage Projection Procedure
For each resource type $k \in \{\text{radio}, \text{compute}\}$ independently:

1. **Reservation Baseline:**
   Ensure each slice allocation satisfies its minimum guarantee:
   $$y_s^{(0)} = \max(p_{k, s}, R_{\min, s})$$
   where $p_{k, s}$ is the proposed allocation for slice $s$. If any $p_{k, s} < R_{\min, s}$, an intervention reason `RESERVATION_RESTORED` is recorded.

2. **Capacity Check:**
   Compute total baseline allocation $T = \sum_{s \in \mathcal{S}} y_s^{(0)}$.
   - If $T \le K_{\text{total}}$, the allocation is safe and accepted as $y_s = y_s^{(0)}$.
   - If $T > K_{\text{total}}$, capacity correction is required:

3. **Surplus Computation:**
   Calculate the remaining unreserved budget and proposed demand surpluses:
   $$B_{\text{remaining}} = K_{\text{total}} - \sum_{s \in \mathcal{S}} R_{\min, s}$$
   $$S_s = \max(0.0, \, y_s^{(0)} - R_{\min, s})$$
   $$S_{\text{total}} = \sum_{s \in \mathcal{S}} S_s$$

4. **Proportional Surplus Scaling:**
   - If $S_{\text{total}} > 0$:
     $$y_s = R_{\min, s} + B_{\text{remaining}} \cdot \left(\frac{S_s}{S_{\text{total}}}\right)$$
   - If $S_{\text{total}} = 0$:
     $$y_s = R_{\min, s}$$
   This guarantees that no slice drops below its contractual reservation, while the excess demand is scaled down proportionally to fit exactly within $K_{\text{total}}$.

5. **Post-Projection Invariant Assertion:**
   The Shield verifies $\sum_{s} y_s \le K_{\text{total}} + \epsilon$ and $y_s \ge R_{\min, s} - \epsilon$. The outcome is marked as `SafetyValidationStatus.CORRECTED`, and `is_modified_by_safety = True` is assigned to the resulting `ExecutedAction`.

---

## 5. Proposal-versus-Execution Auditing

To maintain accountability, compliance, and debugging transparency, the control pipeline enforces strict separation between what a policy intended and what the physical environment executed:

| Data Contract Field | Type | Description |
| :--- | :--- | :--- |
| `DecisionRecord.step` | `int` | Sequential discrete simulation step. |
| `DecisionRecord.policy_name` | `str` | Identifier of the originating policy (`static`, `heuristic`, `ppo`). |
| `DecisionRecord.proposed_action` | `ProposedAction` | Raw unedited proposal from the policy. |
| `DecisionRecord.safety_result` | `SafetyResult` | Complete audit breakdown: status, reasons, budget verification flags. |
| `DecisionRecord.executed_action` | `Optional[ExecutedAction]` | Null if rejected; populated if passed or corrected. |
| `DecisionRecord.accepted` | `bool` | True if the action advanced into the simulator. |

### Verification Flags in `SafetyResult`
- `radio_budget_verified: bool` — Confirms $\sum \text{PRB} \le R_{\text{total}}$.
- `compute_budget_verified: bool` — Confirms $\sum \text{CPU} \le C_{\text{total}}$.
- `reservation_verified: bool` — Confirms $\forall s, \text{alloc}_s \ge \text{reservation}_s$.
- `reasons: List[str]` — Human- and machine-readable tags (e.g., `["OVER_RADIO_BUDGET", "RESERVATION_RESTORED"]`).

---

## 6. Policy Execution Pipeline Integration

The `PolicyExecutionPipeline` orchestrates the complete control loop:

```python
class PolicyExecutionPipeline:
    def execute_step(self, network_state: NetworkState) -> Tuple[DecisionRecord, Optional[NetworkState]]:
        # 1. Query policy for proposed action
        proposed = self.policy.predict(network_state)

        # 2. Validate through Safety Shield
        safety_result = self.shield.validate(proposed, network_state, self.config)

        # 3. Create auditable decision record
        decision_record = DecisionRecord(
            step=self.simulator.current_step,
            policy_name=self.policy_name,
            proposed_action=proposed,
            safety_result=safety_result,
            executed_action=safety_result.executed_action,
            accepted=safety_result.is_accepted,
        )

        # 4. If rejected: freeze simulator, return None state
        if not safety_result.is_accepted or safety_result.executed_action is None:
            return decision_record, None

        # 5. If accepted: advance simulator with ExecutedAction
        next_state = self.simulator.step(safety_result.executed_action)
        return decision_record, next_state
```

Both `StaticSlicingPolicy` and `AdaptiveDemandHeuristicPolicy` in `scripts/phase3/run_baseline_comparison.py` now execute exclusively through this pipeline.

---

## 7. Safety Guarantees vs. Non-Guarantees

### What the Safety Shield Guarantees
1. **Physical Capacity Enforcement:** No executed action will ever exceed the configured 100% PRB or 100% Compute limits.
2. **Deterministic Reservation Invariance:** No executed action will allocate fewer resources than configured minimum reservations, provided configuration feasibility holds.
3. **Fail-Closed Execution:** Any uncorrectable, non-finite, or malformed input is rejected; zero unvalidated actions reach the simulator.
4. **Complete Audit Trail:** Every step records the raw proposal, intervention status, and mathematical reasons for any adjustments.

### What the Safety Shield Does NOT Guarantee
1. **Universal SLA Compliance:** The Shield protects system stability and resource reservations; it **does not** guarantee zero SLA packet loss or latency compliance if incoming traffic demand exceeds total physical capacity.
2. **Channel Quality Compensation:** If radio channel SNR degrades significantly, causing spectral efficiency to drop, an allocation within PRB limits may still experience latency spikes.
3. **Admission Control / Dropping:** The Shield handles slice-level resource slicing; individual packet queuing and head-of-line drop decisions occur inside the discrete-event simulator queue managers.

---

## 8. Verification and Test Summary

All safety mechanisms are verified by automated tests in `backend/tests/test_safety_shield.py` and the existing test suite:

- `test_valid_action_passes_unmodified`: Confirms clean pass-through for compliant proposals.
- `test_shield_does_not_mutate_proposed_action`: Confirms raw proposal immutability.
- `test_radio_over_allocation_projected`: Confirms over-allocated PRB is projected down while preserving minimum guarantees.
- `test_compute_over_allocation_projected`: Confirms compute over-allocation is corrected independently of radio.
- `test_below_reservation_elevated`: Confirms under-reserved allocations are lifted to $R_{\min}$.
- `test_nan_rejected`: Confirms non-finite values (NaN, Inf) trigger `REJECTED` and `executed_action = None`.
- `test_infeasible_reservations_rejected`: Confirms $\sum R_{\min} > 100$ produces clean rejection without silent relaxation.
- `test_projection_idempotent`: Confirms repeated passes of a corrected action produce identical, unmodified allocations.
- `test_pipeline_rejection_halts_simulator`: Confirms rejected actions never advance simulator step count or time.

**Suite Status:** 47 passing tests across Phase 1–4 modules.
