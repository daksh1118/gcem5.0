# Simulator Feasibility & Architectural Decision Report
**Project:** SLA Guardian — Reinforcement Learning-Based Network Slicing and Resource Allocation for 5G  
**Phase:** Phase 0 — Environment and Simulator Validation  
**Date:** 2026-10-23  
**Status:** **NO-GO FOR REAL 5G-LENA IN-PROCESS INTEGRATION; GO FOR HIGH-FIDELITY FALLBACK SIMULATOR**  

---

## 1. Decision Summary

| Decision Item | Verdict | Rationale |
| :--- | :--- | :--- |
| **Real 5G-LENA Integration in Phase 0/1** | **NO-GO** | ns-3/5G-LENA is absent from the host (Case C). Host OS is native Windows 11 without C++ compilers or CMake. WSL2 is present but has no Linux distribution registered. Provisioning WSL2 Ubuntu, build dependencies, cloning ns-3.48 and 5G-LENA v5.1, and executing a full C++ build exceeds the 45-minute Phase 0 budget. |
| **High-Fidelity Discrete-Event Fallback Simulator** | **GO (ACTIVATED)** | Pure Python/Gymnasium discrete-event simulation modeling 3GPP TS 23.501 5QIs, OFDMA Resource Block Group (RBG) partitioning across eMBB/URLLC/mMTC slices, queuing delays, and edge-compute latency. Allows immediate RL training and dashboard integration without stalling the 15-hour hackathon. |
| **5G-LENA Long-Term Interface Compatibility** | **PRESERVED** | The observation space, action space, and KPI telemetry of the fallback simulator will mirror the exact control points of 5G-LENA's `NrMacSchedulerOfdma` and `FlowMonitor`. |

---

## 2. Tested Environment & Attempted Execution Details

- **Host Environment:** Windows 11 Home Single Language (Build 10.0.26300, x86_64, Intel i5-1235U, ~2.5 GB free RAM).
- **Simulator Version Under Evaluation:** 5G-LENA NR v5.1 compatible with ns-3.48 (released August 2026).
- **Execution Script:** `scripts/phase0/check_ns3_lena.ps1` (delegating to `scripts/phase0/check_ns3_lena.sh`).
- **Target Example Attempted:** `cttc-nr-demo` / `cttc-nr-simple-qos-sched` (evaluation of candidate runners).
- **Actual Execution Result:**
  - `check_ns3_lena.ps1` terminated with **Exit Code 1**.
  - Output captured in `logs/phase0/ns3_lena_verification_win.log`:
    `VERDICT: SIMULATOR NOT INSTALLED (Case C). No Linux distribution registered in WSL.`
  - No synthetic simulator was falsely reported as a working 5G NR installation.

---

## 3. Analysis of 5G-LENA Metrics, Control Points & Architecture

Based on official 5G-LENA v5.1 documentation and architectural review of the 3GPP NR ns-3 module:

### 3.1 Traffic Generation Mechanisms
In 5G-LENA, realistic multi-slice traffic is driven by:
- **`ns3::OnOffApplication`**: Used for Poisson/exponential bursty traffic patterns characteristic of IoT/mMTC and web browsing.
- **`ns3::PacketSink`**: Ingests packets at the UE/remote host.
- **`ns3::ThreeGppHttpVariables` / 3GPP Traffic Models**: Generates standardized HTTP/FTP (eMBB) and VoIP/periodic tactile packets (URLLC).
- **Configurable Parameters**: Data rate, packet size, burst interval, inter-arrival time distribution.

### 3.2 Available Flow Measurements & Trace Outputs
5G-LENA provides rich packet-level and radio-level telemetry that directly map to SLA metrics:
1. **`ns3::FlowMonitor`**:
   - `delaySum`, `rxPackets`, `txPackets`, `lostPackets`, `jitterSum`.
   - Direct calculation of **Packet Loss Ratio (PLR)**, **Mean End-to-End Latency**, and **Average Throughput (Mbps)** per 5-tuple flow.
2. **`NrBearerStatsCalculator` / RLC Traces**:
   - Tracks RLC buffer occupancy (bytes queued), queue delay, and drop count per Data Radio Bearer (DRB).
3. **`NrMacStatsCalculator` / `DlSchedulingTrace`**:
   - Granular slot-by-slot metrics: allocated Resource Block Groups (RBGs), MCS (Modulation and Coding Scheme), Transport Block Size (TBS), and SINR.

### 3.3 Radio Resource Representation & Scheduling Control Points
Radio resources in 5G-LENA are partitioned across:
- **Numerology ($\mu = 0, 1, 2, 3$)**: Subcarrier spacing ($15 \times 2^\mu \text{ kHz}$) defining slot duration ($1 \text{ ms}$ down to $125\ \mu\text{s}$).
- **Bandwidth Parts (BWPs)**: Contiguous subsets of physical resource blocks (PRBs).
- **MAC Schedulers**:
  - `ns3::NrMacSchedulerOfdma`: Base class managing time-frequency RBG grids.
  - `ns3::NrMacSchedulerOfdmaQos`: Slices mapped to 3GPP 5QIs (Quality of Service Identifiers).
  - Control Knobs:
    * Slice-level PRB share / weight quotas (e.g. allocating 50% to eMBB, 30% to URLLC, 20% to mMTC).
    * Guaranteed Bit Rate (GBR) vs. Non-GBR priority weights.
    * Maximum latency thresholds triggering urgent slot preemption.

### 3.4 Dynamic Stepping & External Interfacing Feasibility
To control 5G-LENA dynamically from an external Python RL agent:
- ns-3 executes in an event-driven discrete simulation loop (`Simulator::Run()`).
- Controlling it dynamically requires either:
  1. **`ns3-ai` or `ns3-gym` (OpenGym)**: Inter-process shared memory IPC passing observation vectors at fixed intervals $\Delta t$ (e.g. every 10 ms or 100 ms) and pausing simulation until Python returns an action vector.
  2. **Socket/ZeroMQ Bridge**: Custom C++ helper bound to `Simulator::Schedule(MilliSeconds(100), &PeriodicControlCallback)` which serializes metrics to JSON over TCP/IPC.
- **Feasibility Assessment**: Implementing and validating an inter-process IPC bridge with C++ compilation in Phase 0 is impossible within the 45-minute window and requires a full Linux build toolchain.

---

## 4. Requirement for a Distinct Edge-Compute Model

> **Critical Architectural Finding:**  
> **5G-LENA models only the Radio Access Network (gNodeB, UE, PHY/MAC/RLC/PDCP) and core packet forwarding (UPF/PGW). It DOES NOT simulate edge server compute execution.**

In an end-to-end 5G slicing SLA:
$$\text{Total Latency} = \text{Radio Transmission Delay} + \text{RAN Queuing Delay} + \text{Transport Delay} + \text{Edge Compute Processing Delay}$$

1. **Why Radio Slicing Alone Is Insufficient:**  
   Even if the radio scheduler delivers packets within $1\text{ ms}$ for URLLC, if the edge compute server (container/VM instances, CPU cores) is saturated, the edge processing queue delay will cause catastrophic SLA violations.
2. **Coupled Resource Allocation:**  
   The RL agent ("SLA Guardian") must dynamically allocate **both**:
   - **Radio Resources**: Fraction of PRBs / RBGs allocated to each slice.
   - **Edge Compute Resources**: Fraction of CPU cores / processing capacity allocated to the microservice/slice.
3. **Modeling Approach:**  
   The simulation must implement an explicit edge-compute queueing model ($M/M/c$ or discrete-event task processor) that consumes packets egressing from the UPF/RAN, applies compute workload, and computes total end-to-end latency.

---

## 5. Phase 1 High-Fidelity Fallback Simulator Specification

Because of the Case C finding, the **High-Fidelity Discrete-Event Fallback Simulator** is officially activated for Phase 1. 

### Specifications:
1. **Gymnasium-Compliant (`gymnasium.Env`)**:
   - `step(action) -> observation, reward, terminated, truncated, info`
   - Deterministic seed support for reproducible benchmarking.
2. **Standard 3GPP Slices Modeled**:
   - **Slice 1: eMBB (Enhanced Mobile Broadband)** — High throughput (Target: $>50 \text{ Mbps}$), relaxed latency ($<25 \text{ ms}$), 5QI 6/8.
   - **Slice 2: URLLC (Ultra-Reliable Low-Latency Communication)** — Strict latency ($<5 \text{ ms}$), $99.999\%$ delivery, 5QI 1/82.
   - **Slice 3: mMTC (Massive Machine-Type Communication)** — High connection density, bursty packets, moderate latency ($<100 \text{ ms}$), 5QI 9.
3. **Underlying Physics & Traffic Model**:
   - OFDMA frame structure with discrete time stepping ($10\text{ ms}$ slots).
   - Time-varying channel condition (Rayleigh/Rician fading and path loss).
   - Traffic generation with Poisson burstiness and step changes to test SLA resilience.
   - Coupled edge-compute processing queue.
4. **Reward & Safety Shield Hooks**:
   - Multi-objective reward balancing throughput, latency adherence, and compute efficiency.
   - Strict penalization for SLA violations to train the Phase 2 RL agent and trigger the Phase 3 Safety Shield.

---

## 6. Outstanding Work & Phase 1 Readiness

### Immediate Phase 1 Next Steps:
1. **Virtual Environment Setup**:
   Create a local `.venv` using Python 3.11/3.13 and install `gymnasium`, `numpy`, `pytest`, `pydantic`.
2. **Build Simulator Module (`sla_guardian/simulator/`)**:
   - Implement `SliceType`, `QoSSpec`, `TrafficGenerator`.
   - Implement `OFDMARadioModel` and `EdgeComputeModel`.
   - Implement `NetworkSlicingEnv` inheriting from `gymnasium.Env`.
3. **Comprehensive Pytest Suite (`tests/test_simulator.py`)**:
   - Verify deterministic resets, action clipping, PRB conservation ($\sum \text{PRB} = 100\%$), SLA violation tracking, and step dynamics.
4. **Offline 5G-LENA Deployment Guide**:
   Maintain clear WSL2 Ubuntu documentation for teams wishing to run the native C++ simulator in post-hackathon cycles.
