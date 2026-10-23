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
  - **eMBB (Enhanced Mobile Broadband):** 4K/8K streaming, high throughput demand.
  - **URLLC (Ultra-Reliable Low-Latency Communication):** Autonomous vehicles, industrial robotics, < 5 ms latency target.
  - **mURLLC (Medical URLLC):** Telesurgery, robotic vitals telemetry, zero packet-loss tolerance.
- **Problem Statement Callout:** *"Static slicing wastes expensive radio spectrum during quiet periods, while naive reactive heuristics suffer violent control thrashing."*

### Speaker Script:
> *"Good morning, judges. In 5G and future 6G networks, network slicing virtualizes shared physical infrastructure across diverse services—from high-bandwidth video to mission-critical autonomous vehicles and remote telesurgery.
>
> Today, telecom operators partition radio and compute resources statically. But network traffic is volatile. When video demand surges, static allocations artificially throttle throughput. When operators deploy reactive heuristics, the system suffers from violent control oscillations—thrashing physical base station schedulers.
>
> Our solution is **SLA Guardian**: an autonomous control pipeline that dynamically rebalances radio and edge-compute resources in real time, pairing a **Constrained PPO Agent** with a **Deterministic Safety Shield** that mathematically guarantees physical resource constraints."*

---

## Slide 2: System Architecture — The Dual-Control Plane (0:30 – 1:00)

### Slide Visuals:
- **Architecture Flow:**
  `Exogenous Traffic Arrivals` $\rightarrow$ `Dual-Queue Network Simulator (Radio + Compute)` $\rightarrow$ `12-Dim State Observation` $\rightarrow$ `Constrained PPO Policy` $\rightarrow$ `Raw 6-Dim Action Proposal` $\rightarrow$ **`[SAFETY SHIELD]`** $\rightarrow$ `Validated Physical Allocation` $\rightarrow$ `SLA Evaluator & Metrics Engine`
- **Key Highlight Box:** Decoupled Learning vs. Deterministic Enforcement.

### Speaker Script:
> *"Here is our core engineering contribution: **We do not trust unconstrained neural networks to directly control mission-critical physical infrastructure.**
>
> Instead, SLA Guardian establishes a decoupled two-tier control loop:
> 1. At Tier 1, an Actor-Critic PPO policy observes a 12-dimensional state vector—including per-slice radio queues, edge compute backlogs, and recent channel signal-to-noise ratios. It proposes continuous 6-dimensional allocations across radio bandwidth and edge compute.
> 2. At Tier 2, before any proposed action reaches the simulator, it passes through our deterministic **Safety Shield**. The Shield enforces hard invariant constraints: total allocations cannot exceed 100% capacity, and every slice is guaranteed a regulatory minimum survival reservation.
>
> If an exploratory RL action proposes invalid fractions, the Shield uses convex Euclidean projection to project it to the nearest valid simplex in under 0.1 milliseconds."*

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
> Under nominal load, notice how our PPO agent scavenges unutilized capacity and allocates surplus PRBs to eMBB, boosting throughput while preserving 100% URLLC delivery.
>
> When we trigger a sudden **URLLC Burst**:
> - Look at the **Static Baseline** on the left: URLLC queues back up, and packet delivery ratio drops to 80.9%.
> - In the center, the **Adaptive Heuristic** reacts to the queue surge by violently shifting capacity. But notice its fatal flaw: severe oscillation. It exhibits massive allocation churn—over 1,170 points of L1 reallocation variance—causing control thrashing.
> - On the right, our **PPO Agent** maintains remarkable stability, reducing churn to just 38.8—a 30-fold reduction in control variance.
> - And look at the Safety Shield indicator: during aggressive exploration, the Shield actively intervened across 9 to 13 steps per episode, clamping the boundary with zero capacity violations."*

---

## Slide 4: Empirical Benchmark Evidence & Real-World Honesty (1:45 – 2:25)

### Slide Visuals:
- **Summary Benchmark Table (from 45 reproducible trials):**
  - eMBB Throughput: PPO achieves **39.58 Mbps** vs Static **28.82 Mbps** (+37.3%).
  - Total Network Throughput: PPO achieves **62.15 Mbps** vs Static **51.65 Mbps** (+20.3%).
  - URLLC PDR in Normal / Surge: **1.0000 (100% Delivery)**.
  - Allocation Churn: Heuristic **182 – 1171** vs PPO **27 – 42** (up to 30x smoother).
  - Safety Shield Invariants: **0 physical capacity violations across 100% of tested runs**.
- **Scientific Honesty Callout:** Out-of-distribution burst behavior & latency floor explained.

### Speaker Script:
> *"We ground our presentation in transparent empirical evidence from 45 reproducible trials:
> - PPO boosts eMBB delivered throughput by 36% to 43% over static slicing, and total network throughput by 5% to 20%.
> - Under nominal load and eMBB video surges, PPO delivers 100% of URLLC packets with near-zero dropped packets.
> - Most importantly, PPO eliminates the control churn that makes traditional heuristics impractical in live cellular base stations.
>
> Now, as researchers, we believe in complete scientific integrity:
> First, our model was trained on nominal traffic, where critical drops were within budget, so lambda remained at zero. As a result, when exposed out-of-distribution to extreme URLLC bursts or mURLLC storms, the agent continues allocating surplus to eMBB rather than shedding load, dropping more critical packets than the reactive heuristic.
> Second, in our 10 millisecond discrete-event simulation, uniform packet arrivals create an inherent queuing delay floor of ~9.5 milliseconds, which causes the aggregate SLA evaluator to flag the aggressive 5.0 millisecond 3GPP target across all policies.
> Rather than fudging numbers or modifying thresholds, we expose these exact tradeoffs openly."*

---

## Slide 5: Core Contributions, Limitations & Next Validation Step (2:25 – 3:00)

### Slide Visuals:
- **Three Clear Claims:**
  1. *Hard physical constraints are deterministically enforced by the Safety Shield.*
  2. *The Constrained PPO agent learns efficient joint radio/compute sharing with superior stability.*
  3. *Performance SLA compliance is empirically measured and contextualized against simulation fidelity.*
- **Roadmap Graphic:** Python Abstracted Simulator (Completed) $\rightarrow$ FastAPI / Web Dashboard (Completed) $\rightarrow$ Multi-Scenario Curriculum Training & ns-3 / 5G-LENA (Next Milestones).

### Speaker Script:
> *"To summarize our achievements:
> 1. We built a fully reproducible, end-to-end autonomous network slicing testbed with zero external cloud dependencies.
> 2. We demonstrated that decoupling RL exploration from a deterministic Safety Shield enables mathematically safe cellular resource allocation.
> 3. We documented the real-world limitation of single-scenario training, establishing a clear research roadmap toward multi-scenario curriculum learning and ns-3 / 5G-LENA physical-layer validation.
>
> All contracts are standardized using Pydantic v2 schemas, and our benchmark data, checkpoints, and automated tests are fully open for review. Thank you, and we welcome your questions!"*
