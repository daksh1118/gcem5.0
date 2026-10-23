# Component Migration & Compatibility Map

This document reconciles the specifications from the uploaded *5G Slicing Demo Full Build Guide* with the existing, tested modular architecture of **SLA Guardian**.

---

## Component-by-Component Mapping Matrix

| Guide Component | Existing Repository Equivalent | Compatibility Gap | Proposed Adapter / Resolution | Dependency Impact | Schema / Interface Impact | Verification Method |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`sim.py` (`SliceEnv`)** | `FallbackNetworkSimulator` + `PacketQueue` | Guide specifies a 100 ms macro-step and 0-queue URLLC drops; repo uses 10 ms internal discrete event queues for both radio and compute. | Build `MacroControlAdapter` in `backend/app/rl/control_interval.py` that executes 10x 10 ms steps per macro-action. | None | None | Unit tests in `test_rl_adapters.py` verifying 10-step aggregation. |
| **`config.yaml`** | `backend/app/schemas/config.py` + `scenarios/default.json` | Guide uses flat YAML; repo uses typed Pydantic models with nested `SliceSlaConfig` and JSON scenario profiles. | Retain Pydantic `RunConfig` as authoritative. Reconcile scenario profiles in `scenarios/default.json`. | None (avoids adding PyYAML) | None | `test_config.py` validation. |
| **Action Space (6D Continuous)** | `ProposedAction` in `backend/app/schemas/actions.py` | Guide uses 6 logits (3 radio, 3 compute); repo `ProposedAction` expects absolute capacity allocations & priority dicts. | Implement `ActionMappingAdapter` in `backend/app/rl/action_mapping.py` with stable softmax + reservation projection + priority heuristics. | None | None | Test mathematical bounds and reservation guarantees. |
| **Observation Space (12D Vector)** | `NetworkState` in `backend/app/schemas/state.py` | Guide uses 12 normalized floats; repo uses rich nested Pydantic `SliceState` dicts. | Implement `ObservationAdapter` in `backend/app/rl/observation.py` mapping `NetworkState` to a normalized 12-dim NumPy array. | None | None | Test feature shapes, dtype, finite bounds in $[-1, 1]$. |
| **Constrained Reward / Lagrangian** | `SlaMetricEvaluator` in `backend/app/evaluation/metrics.py` | Repo evaluator computes comprehensive metrics but no Lagrangian $\lambda$ penalty; guide combines eMBB service with critical-slice cost. | Implement `ViolationCostAdapter` (`cost.py`) and `LagrangianMultiplier` (`lagrangian.py`) to compute $R = R_{\text{embb}} - \lambda C_{\text{crit}}$. | None | None | Unit tests verifying multiplier updates when cost $>$ or $<$ limit. |
| **`shield.py`** | `SafetyShield` in `backend/app/control/safety_shield.py` | Guide uses load-dependent PRB floors; repo uses reservation-aware proportional projection and explicit rejection. | Retain existing Phase 4 `SafetyShield`. It already guarantees hard capacity and minimum reservations. | None | None | Verify Phase 4 tests pass (9/9). |
| **`baselines.py`** | `StaticSlicingPolicy` & `AdaptiveDemandHeuristicPolicy` in `backend/app/policies/` | Guide implements simple 60/25/15 and queue-proportional heuristics; repo implements typed `PolicyInterface` baselines. | Retain existing baselines; they are fully compatible with both 10 ms and 100 ms macro-control intervals. | None | None | Multi-scenario rollout comparisons in `run_baseline_comparison.py`. |
| **`train.py` (PPO)** | Planned for Phase 5 (`backend/app/rl/train.py`) | Guide trains PPO on CPU using SB3; repo has not yet trained RL model. | Phase 5 will implement SB3 PPO wrapping the Gymnasium adapter and saving to `models/agent.zip`. | SB3 + PyTorch CPU (installed in `.venv`) | None | Verify learning loss decrease and checkpoint persistence. |
| **`evaluate.py`** | `scripts/phase3/run_baseline_comparison.py` | Guide compares 3 policies across 4 scenarios; repo currently compares Static vs Heuristic across 3 scenarios. | Expand evaluation script to include PPO `RLPolicy` across 5 aligned scenarios (`normal`, `embb_surge`, `urllc_burst`, `murllc_storm`, `mixed_stress`). | None | None | Execution of `evaluate_ppo.py` saving JSON results. |
| **`api.py` (FastAPI)** | `backend/app/api/` (Scaffolded in Phase 1) | Guide serves single FastAPI script with WebSocket `/ws` and `/spike`; repo has structured APIRouter. | Phase 6 will implement `/ws`, `/spike`, `/reset`, and `/summary` reusing existing FastAPI app. | websockets | None | Test WebSocket packet stream with test client. |
| **`static/index.html`** | Planned for Phase 7 (`frontend/index.html`) | Guide uses plain HTML/JS with Chart.js CDN; no npm build required. | Adopt guide's lightweight frontend approach in Phase 7. | None (CDN based) | None | Browser rendering and interactive trigger validation. |
| **Optional ns-3 (Phase 8/9)** | `docs/phase0/simulator-decision.md` | Guide includes optional ns-3 Docker/source build; Phase 0 established no-go decision for native Windows. | Retain ns-3 as isolated, optional Phase 9 exploration that does not block Python demo. | Optional C++ build tools | None | Documented build feasibility check. |

---

## Compatibility Invariants Maintained

1. **Deterministic Contracts:** All internal simulator interactions continue to use `ExecutedAction` validated by `SafetyShield`.
2. **Immutability of Baseline Tests:** Existing Phase 0–4 tests are not altered. Adapters wrap existing interfaces cleanly.
3. **Reproducibility:** All adapters and random generators accept explicit seed inputs.
