# SLA Guardian — Phase 1 Data Contracts & Schema Reference
**Project:** SLA Guardian — Reinforcement Learning-Based Network Slicing and Resource Allocation for 5G  
**Phase:** Phase 1 — Project Scaffolding, Virtual Environment and Shared Data Contracts  
**Status:** Validated with Pydantic v2  

---

## 1. Canonical Slice Identifiers

The system enforces three immutable slice identifiers across all backend models, database records, and API contracts:

| Identifier | Display Label | Target 3GPP Workload Profile |
| :--- | :--- | :--- |
| `eMBB` | Enhanced Mobile Broadband | High-bandwidth video streaming, AR/VR, bulk file transfer |
| `URLLC` | Ultra-Reliable Low-Latency Communication | Mission-critical factory automation, autonomous vehicle braking |
| `mURLLC` | Massive / Mixed Ultra-Reliable Low-Latency Communication | Massive sensor grids requiring ultra-reliability and bounded latency |

> **Architectural Note on `mURLLC`:**  
> The third workload is designated as `mURLLC` per requirements. It represents high-density, mission-critical IoT devices. It is explicitly kept distinct from standard 3GPP mMTC (which tolerates high delay), while allowing its throughput, latency, and priority parameters to be configured dynamically in scenarios without requiring code modifications.

---

## 2. Shared Data Models

### 2.1 `RunConfig` (`backend.app.schemas.config`)
Defines the parameters, capacity limits, and SLA targets for a simulation run.

| Field | Type | Required | Units / Range | Description |
| :--- | :--- | :--- | :--- | :--- |
| `scenario_id` | `str` | Yes | Non-empty string | Unique scenario identifier |
| `seed` | `int` | No (default: 42) | $\ge 0$ | PRNG seed for reproducible channels |
| `max_steps` | `int` | No (default: 1000) | $> 0$ | Maximum simulation steps |
| `step_duration_ms` | `float` | No (default: 10.0) | $> 0$ ms | Physical duration of one step |
| `total_radio_capacity` | `float` | Yes | $> 0$ PRB units | Total radio capacity available |
| `total_compute_capacity`| `float` | Yes | $> 0$ Compute units | Total edge compute capacity available |
| `sla_thresholds` | `Dict[SliceId, SliceSlaConfig]` | Yes | 3 canonical slices | Strict SLA latency, throughput, PDR limits |
| `minimum_reservations`| `Dict[SliceId, SliceReservationConfig]` | No | $\ge 0$ | Minimum baseline capacity per slice |
| `policy_id` | `str` | No (default: heuristic) | string | Policy algorithm identifier |
| `traffic_profile` | `str` | No (default: normal) | string | Traffic generator mode |

**Validation Rules:**
- `sla_thresholds` must contain exactly the keys `eMBB`, `URLLC`, `mURLLC`.
- $\sum \text{min\_radio\_capacity} \le \text{total\_radio\_capacity}$.
- $\sum \text{min\_compute\_capacity} \le \text{total\_compute\_capacity}$.

---

### 2.2 `SliceState` (`backend.app.schemas.state`)
Represents the observable telemetry of an individual slice at step $t$.

| Field | Type | Units / Range | Initialization Rule (Step 0) |
| :--- | :--- | :--- | :--- |
| `slice_id` | `SliceId` | Canonical Enum | Constant |
| `offered_demand_mbps` | `float` | $\ge 0.0$ Mbps | Initial traffic demand |
| `demand_growth_rate` | `float` | Normalized rate | $0.0$ |
| `queue_depth_packets` | `int` | $\ge 0$ packets | $0$ |
| `delivered_throughput_mbps`| `Optional[float]` | $\ge 0.0$ Mbps | **`None`** (No delivery measured before first step) |
| `p95_latency_ms` | `Optional[float]` | $\ge 0.0$ ms | **`None`** (No packet arrival delay recorded yet) |
| `packet_delivery_ratio` | `Optional[float]` | $0.0 \dots 1.0$ | **`None`** (No packets departed yet) |
| `current_radio_allocation` | `float` | $\ge 0.0$ PRB units | Initial allocation |
| `current_compute_allocation`| `float` | $\ge 0.0$ Compute units| Initial allocation |
| `sla_headroom` | `float` | $-\infty \dots +\infty$ | $1.0$ (Nominal safety buffer) |

---

### 2.3 `NetworkState` (`backend.app.schemas.state`)
The global multi-slice observation vector passed to policies.

| Field | Type | Units / Range | Description |
| :--- | :--- | :--- | :--- |
| `run_id` | `Optional[str]` | String | Identifier of executing run |
| `step` | `int` | $\ge 0$ | Discrete step index |
| `sim_time_sec` | `float` | $\ge 0.0$ seconds | Elapsed physical simulation time |
| `total_radio_capacity` | `float` | $> 0.0$ | Total capacity |
| `total_compute_capacity` | `float` | $> 0.0$ | Total compute |
| `slice_states` | `Dict[SliceId, SliceState]` | Exactly 3 slices | Granular per-slice telemetry |
| `is_congested` | `bool` | Boolean | True if aggregate demand > capacity |
| `congested_slices` | `List[SliceId]` | Slice IDs | Slices in active congestion |

**Validation Rules:**
- Must contain all three canonical slices.
- $\sum \text{current\_radio\_allocation} \le \text{total\_radio\_capacity} + \epsilon$.
- $\sum \text{current\_compute\_allocation} \le \text{total\_compute\_capacity} + \epsilon$.

---

### 2.4 `ProposedAction` & `ExecutedAction` (`backend.app.schemas.actions`)

#### `ProposedAction` (Policy Output):
- `radio_allocations: Dict[SliceId, float]` — Proposed radio capacity ($\ge 0$).
- `compute_allocations: Dict[SliceId, float]` — Proposed edge compute capacity ($\ge 0$).
- `priorities: Dict[SliceId, int]` — Scheduling priority ($1 = \text{Highest / Urgent}, 2, 3 = \text{Lower}$).
- `policy_id: Optional[str]` — Originating agent identifier.

#### `ExecutedAction` (Safety Shield Output):
- `radio_allocations: Dict[SliceId, float]` — Approved/clamped radio allocation.
- `compute_allocations: Dict[SliceId, float]` — Approved/clamped compute allocation.
- `priorities: Dict[SliceId, int]` — Approved scheduling priority.
- `is_modified_by_safety: bool` — True if Safety Shield clamped or overrode proposal.
- `proposal_reference: Optional[str]` — Audit traceability hash.

---

### 2.5 `SafetyResult` (`backend.app.schemas.actions`)
Combines proposed and executed actions for explainability and compliance auditing:
- `proposed_action: ProposedAction`
- `executed_action: ExecutedAction`
- `intervention_occurred: bool`
- `validation_status: SafetyValidationStatus` (`VALID`, `INTERVENED_CLAMPED`, `INTERVENED_FALLBACK`, `REJECTED`)
- `intervention_reasons: List[str]` (e.g. `["URLLC radio allocation below 25.0 PRB reservation; clamped."]`)
- `resource_budget_verified: bool`

---

### 2.6 `StepMetrics` (`backend.app.schemas.metrics`)
Emitted by the Evaluator after every simulation transition:
- `step: int`, `sim_time_sec: float`
- `throughput_mbps: Dict[SliceId, float]`
- `p95_latency_ms: Dict[SliceId, float]`
- `packet_delivery_ratio: Dict[SliceId, float]`
- `sla_status: Dict[SliceId, bool]` (True = compliant, False = breach)
- `sla_breach_count: int` (0 to 3)
- `radio_utilization_ratio: float` ($0.0 \dots 1.0$)
- `compute_utilization_ratio: float` ($0.0 \dots 1.0$)
- `allocation_churn: float` (L1 distance of resource change)
- `reward_components: Optional[Dict[str, float]]` (Decoupled RL rewards)

---

### 2.7 `RunResult` (`backend.app.schemas.results`)
Final execution summary artifact:
- `run_id`, `scenario_id`, `seed`, `policy_id`, `policy_version`
- `status: RunStatus` (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `TERMINATED`)
- `completed_steps: int`
- `metrics_history: List[StepMetrics]`
- `aggregate_metrics: Optional[Dict[str, float]]`
- `created_at`, `completed_at`, `error_message`
