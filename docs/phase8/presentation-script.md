# SLA Guardian — Final Presentation Script & Technical Pitch Deck

**Project Title:** SLA Guardian: Autonomous 5G Network Slicing via Constrained Reinforcement Learning & Deterministic Safety Shield  
**Event:** GCEM Hacks 5.0 — Autonomous Systems & Telecommunications Track  
**Role:** Technical Lead & Presenter  
**Total Duration:** 3 minutes (180 seconds) + 2 minutes Q&A  

---

## Slide 1: Title & The Core Network Slicing Dilemma (0:00 – 0:30)

### Slide Visuals:
- **Title:** SLA Guardian: Autonomous 5G Network Slicing
- **Subtitle:** Joint Radio & Edge-Compute Resource Allocation under Hard Safety Constraints
- **Graphic:** Diagram showing physical 5G base station + Edge Multi-Access Compute (MEC) partitioned into 3 slices:
  - **eMBB (Enhanced Mobile Broadband):** 4K/8K streaming, AR/VR, high throughput demand.
  - **URLLC (Ultra-Reliable Low-Latency Communication):** Autonomous vehicles, industrial robotics, < 5 ms latency.
  - **mURLLC (Medical URLLC):** Telesurgery, robotic vitals telemetry, zero packet-loss tolerance.
- **Problem Statement Callout:** *"Static slicing wastes up to 40% capacity during lulls and crashes during demand surges."*

### Speaker Script:
> *"Good morning, judges. In 5G and future 6G networks, network slicing allows operators to virtualize a single physical infrastructure for wildly diverse services—from massive video streaming to mission-critical autonomous vehicles and remote telesurgery.
>
> Today, telecom operators partition radio and compute resources statically. But network traffic is inherently volatile. When an autonomous vehicle fleet triggers an emergency URLLC burst, static allocations overflow buffers, dropping critical safety packets. Conversely, when URLLC traffic is quiet, expensive radio spectrum and edge CPU cycles sit completely idle.
>
> Our solution is **SLA Guardian**: an autonomous control pipeline that dynamically rebalances radio and edge-compute resources in real time, pairing a **Constrained PPO Agent** with a **Deterministic Safety Shield** that mathematically guarantees physical resource constraints."*

---

## Slide 2: System Architecture — The Dual-Control Plane (0:30 – 1:00)

### Slide Visuals:
- **Architecture Flow:**
  `Exogenous Traffic Arrivals` $\rightarrow$ `Dual-Queue Network Simulator (Radio + Compute)` $\rightarrow$ `12-Dim State Observation` $\rightarrow$ `Constrained PPO Policy` $\rightarrow$ `Raw 6-Dim Action Proposal` $\rightarrow$ **`[SAFETY SHIELD]`** $\rightarrow$ `Validated Physical Allocation` $\rightarrow$ `SLA Evaluator & Reward Engine`
- **Key Highlight Box:** Decoupled Learning vs. Deterministic Enforcement.

### Speaker Script:
> *"Here is our core engineering contribution: **We do not trust unconstrained neural networks to directly control mission-critical physical infrastructure.**
>
> Instead, SLA Guardian establishes a decoupled two-tier control loop:
> 1. At Tier 1, an Actor-Critic PPO policy observes a 12-dimensional state vector—including per-slice radio queues, edge compute backlogs, and recent channel signal-to-noise ratios. It proposes a continuous 6-dimensional resource allocation spanning both radio bandwidth fractions and edge compute shares.
> 2. At Tier 2, before any proposed action reaches the simulator, it passes through our deterministic **Safety Shield**. The Shield enforces hard invariant constraints: total allocations cannot exceed 100% capacity, and every slice is guaranteed a regulatory minimum 10% survival reservation.
>
> If an exploratory RL action proposes invalid fractions, the Shield uses convex projection to project it to the nearest valid simplex in under 0.1 milliseconds."*

---

## Slide 3: Live Demonstration — Three-Policy Synchronized Benchmark (1:00 – 1:45)

### Slide Visuals:
- **Live UI Split-Screen:** 
  - Panel 1: Static Baseline (33/33/33 fixed)
  - Panel 2: Adaptive Heuristic (queue-proportional reactive allocation)
  - Panel 3: PPO Agent + Safety Shield (proactive joint allocation)
- **Action Highlight:** Triggering `urllc_burst` live on the dashboard.

### Speaker Script:
> *"Let's look at the live operator dashboard. We run all three policies concurrently against identical, synchronized traffic realizations.
>
> When we trigger a sudden **URLLC Burst**:
> - Look at the **Static Baseline** on the left: URLLC queues immediately back up, packet delivery ratio drops to 80.9%, and delay spikes. Capacity cannot shift.
> - In the center, the **Adaptive Heuristic** detects the queue surge and shifts resources. But notice its fatal flaw: severe oscillation. It exhibits massive allocation churn—over 1,170 points of L1 reallocation variance—causing control instability.
> - On the right, our **PPO Agent** smoothly increases URLLC radio and compute shares while preserving eMBB connectivity. Its churn is just 38.8—a 30-fold reduction in control thrashing compared to heuristic re-allocation.
> - And look at the Safety Shield indicator: during aggressive exploration, the Shield actively intervened across 9 to 13 steps per episode, clamping the boundary without degrading throughput."*

---

## Slide 4: Empirical Benchmark Evidence & Real-World Honesty (1:45 – 2:25)

### Slide Visuals:
- **Summary Benchmark Table (from 45 reproducible trials):**
  - eMBB Throughput: PPO achieves **39.58 Mbps** vs Static **28.82 Mbps** (+37.3%).
  - eMBB PDR: PPO achieves **86.5%** vs Static **63.5%**.
  - URLLC PDR in Normal / Surge: **1.0000 (100% Delivery)**.
  - Allocation Churn: Heuristic **538 – 1171** vs PPO **27 – 42** (up to 30x smoother).
  - Safety Shield Invariants: **0 capacity violations across 100% of tested runs**.
- **Honest Evaluation Callout:** Latency target caveat explained openly.

### Speaker Script:
> *"We do not present hand-picked cherry runs. Across 45 systematic evaluations spanning five stress scenarios and multiple randomized seeds:
> - PPO boosts eMBB delivered throughput by 37% to 45% over static slicing.
> - Under normal and eMBB surge conditions, PPO delivers 100% of URLLC packets.
> - Most importantly, PPO eliminates the violent control churn that makes traditional heuristics impractical in live cellular base stations.
>
> Now, as researchers, we believe in scientific honesty:
> In our discrete-event simulation, uniform packet arrivals across 10 millisecond steps create an inherent queuing delay floor of approximately 9.5 milliseconds. Consequently, our evaluator reports an aggregate SLA breach against the hyper-aggressive 5.0 millisecond 3GPP URLLC target across all policies.
> Rather than fudging simulator time-steps or softening SLA thresholds to manufacture a green dashboard, we expose the exact per-slice packet delivery ratios and latency distributions directly to the operator."*

---

## Slide 5: Core Contributions, Limitations & Next Validation Step (2:25 – 3:00)

### Slide Visuals:
- **Three Clear Claims:**
  1. *Hard physical constraints are deterministically enforced by the Safety Shield.*
  2. *The Constrained PPO agent learns efficient joint radio/compute sharing with superior stability.*
  3. *Performance SLA compliance is empirically measured and contextualized against simulation fidelity.*
- **Roadmap Graphic:** Python Abstracted Simulator (Completed) $\rightarrow$ FastAPI / Web Dashboard (Completed) $\rightarrow$ ns-3 / 5G-LENA Physical Layer Simulator (Architecture-Ready).

### Speaker Script:
> *"To summarize our hackathon achievements:
> 1. We built a fully reproducible, end-to-end autonomous network slicing testbed with zero external database or cloud dependencies.
> 2. We developed a Constrained PPO agent using a Lagrangian multiplier formulation that learns to jointly optimize continuous radio bandwidth and edge CPU allocation.
> 3. We proved that decoupling learning from a deterministic Safety Shield enables safe, zero-violation autonomous telecom operations.
>
> All contracts are standardized using Pydantic v2 schemas, meaning this identical control loop can interface with an ns-3 / 5G-LENA C++ simulation backend without modifying a single line of policy code.
>
> The code, checkpoints, and automated benchmarks are fully open and ready for inspection. Thank you, and we welcome your questions!"*
