# Phase 0: Environment & Infrastructure Audit Report
**Project:** SLA Guardian — Reinforcement Learning-Based Network Slicing and Resource Allocation for 5G  
**Phase:** Phase 0 — Environment and Simulator Validation  
**Date & Timestamp:** 2026-10-23T11:38:30+05:30  
**Evaluator:** Senior Network Simulation Engineer & Technical Lead  
**Audit Status:** Complete & Verified  

---

## 1. Executive Summary

This document presents the empirical audit of the host development environment for **SLA Guardian**. The audit was conducted using direct system inspection, non-destructive toolchain detection, and execution of automated verification scripts. 

The primary finding is that the host machine is running **native Windows 11 with Python 3.13**, equipped with modern multi-core hardware and abundant storage. However, **ns-3 with 5G-LENA is not installed**, and the native environment lacks the required Linux toolchains (GCC/Clang, CMake, Make/Ninja) and an operational Linux distribution in WSL2 (`wsl -l -v` confirmed only stopped `docker-desktop`). Setting up a full Linux environment, downloading ns-3.48 and 5G-LENA v5.1, and executing a complete C++ compilation would far exceed the 45-minute Phase 0 gate.

Therefore, an evidence-based **NO-GO** decision is made for real 5G-LENA execution during Phase 0. Development will proceed in Phase 1 with an explicitly labelled, high-fidelity discrete-event fallback simulator modeling 3GPP TS 23.501 5QIs and OFDMA slicing, while preserving full architectural interfaces for later 5G-LENA deployment.

---

## 2. Host Operating System and Hardware Architecture

| Parameter | Observed Value | Verification Status | Verification Command / Evidence |
| :--- | :--- | :--- | :--- |
| **Operating System** | Microsoft Windows 11 Home Single Language | **[VERIFIED]** | `Get-CimInstance Win32_OperatingSystem` (Build 10.0.26300) |
| **OS Architecture** | 64-bit (x86_64 / AMD64) | **[VERIFIED]** | `platform.machine() == 'AMD64'` |
| **CPU Model** | 12th Gen Intel(R) Core(TM) i5-1235U | **[VERIFIED]** | `Get-CimInstance Win32_Processor` |
| **CPU Cores / Threads** | 10 Physical Cores (2P + 8E), 12 Logical Processors | **[VERIFIED]** | `NumberOfCores: 10, NumberOfLogicalProcessors: 12` |
| **Total Physical RAM** | 15.69 GB (16,454,388 KB) | **[VERIFIED]** | `GlobalMemoryStatusEx` & `Win32_OperatingSystem` |
| **Available RAM** | 2.45 GB to 2.59 GB free | **[VERIFIED]** | Empirical reading under running IDE background tasks |
| **Primary Storage (C:)** | 454.61 GB Total, **197.42 GB Free** | **[VERIFIED]** | `Get-PSDrive C` (211.9 GB unallocated) |

---

## 3. Development Toolchains & Build Utilities

| Tool | Status | Version / Path | Verification Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Git** | Available | `git version 2.55.0.windows.5` | **[VERIFIED]** | Host Windows CLI |
| **CMake** | Not Installed | `Not found in PATH` | **[VERIFIED]** | Command failure: `The term 'cmake' is not recognized` |
| **GCC (gcc)** | Not Installed | `Not found in PATH` | **[VERIFIED]** | `where.exe gcc` returned code 1 |
| **G++ (g++)** | Not Installed | `Not found in PATH` | **[VERIFIED]** | `where.exe g++` returned code 1 |
| **Clang** | Not Installed | `Not found in PATH` | **[VERIFIED]** | `where.exe clang` returned code 1 |
| **MSVC (cl)** | Not Installed | `Not found in PATH` | **[VERIFIED]** | `where.exe cl` returned code 1 |
| **Ninja / Make** | Not Installed | `Not found in PATH` | **[VERIFIED]** | `where.exe ninja` returned code 1 |
| **WSL2 Subsystem** | Installed | WSL v2.6.3.0 | **[VERIFIED]** | `wsl --version` returned active kernel |
| **WSL Linux Distro** | **MISSING** | No Ubuntu/Debian registered | **[VERIFIED]** | `wsl -l -v` returned only `docker-desktop (Stopped)` |
| **Docker Engine** | Installed | Docker version 29.2.1 | **[VERIFIED]** | Docker daemon currently stopped |

---

## 4. Python Environment & Package Audit

### 4.1 Python Runtimes
- **Active Interpreter:** `Python 3.13.3 (64-bit)`
- **Path:** `C:\Users\Daksh\AppData\Local\Programs\Python\Python313\python.exe`
- **Secondary Interpreters:** Python 3.11 (Windows Store installed)
- **Virtual Environment:** None active in `c:\gcemhacks5.0` (clean workspace)

### 4.2 Candidate Package Availability

| Package | Status | Version | Target Phase | Verification Status | Functional Role in SLA Guardian |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **NumPy** | **Installed** | `2.5.3` | Phase 0 / 1 / 2 | **[VERIFIED]** | State array math, matrix transformations, KPI calculations |
| **Pydantic** | **Installed** | `2.12.5` | Phase 0 / 1 / 2 / 3 | **[VERIFIED]** | SLA schemas, validation, strict configuration typing |
| **FastAPI** | **Installed** | `0.141.1` | Phase 3 | **[VERIFIED]** | REST API endpoints for telemetry and controller policies |
| **Uvicorn** | **Installed** | `0.53.0` | Phase 3 | **[VERIFIED]** | ASGI server for real-time dashboard |
| **Pytest** | **Installed** | `9.1.1` | Phase 0 / 1 / 2 / 3 | **[VERIFIED]** | Automated test suite and validation gates |
| **Gymnasium** | *Missing* | None | Phase 1 | **[VERIFIED MISSING]** | Standard RL environment interface (`gymnasium.Env`) |
| **Stable-Baselines3** | *Missing* | None | Phase 2 | **[VERIFIED MISSING]** | PPO, DQN, Maskable-PPO RL training algorithms |

> **Audit Observation:**  
> The core foundational packages for data modeling, APIs, and testing (`numpy`, `pydantic`, `fastapi`, `uvicorn`, `pytest`) are already verified and functional.  
> As instructed, large ML dependencies (`gymnasium`, `stable-baselines3`, `torch`) were deliberately **not** installed globally in Phase 0; they are slated for an isolated virtual environment (`.venv`) in Phase 1 and Phase 2.

---

## 5. Network Simulator Status (ns-3 & 5G-LENA)

- **Search Scope:** `C:\`, `C:\Users\Daksh`, system environment variables (`$env:NS3_HOME`, `$env:LENA_HOME`), WSL filesystem mounts.
- **Result:** **No existing ns-3 or 5G-LENA installation exists on the machine.**
- **Classification:** **Case C: Simulator is not installed.**
- **Platform Compatibility Check:**
  - Official 5G-LENA v5.1 documentation confirms compatibility with `ns-3.48`.
  - ns-3 and 5G-LENA are designed and officially supported on POSIX Linux environments (Ubuntu 22.04 / 24.04 LTS).
  - Native Windows compilation requires non-standard MSVC ports or heavy MinGW/Cygwin layers that do not reliably support the NR module.
  - WSL2 is present, but lacks an installed Ubuntu distribution (`docker-desktop` is the sole registered distro and is stopped).
  - Attempting to install WSL Ubuntu 24.04, configure build tools (`g++`, `cmake`, `ninja`), clone ns-3.48 and 5G-LENA (~1.5 GB), and run a full optimized compilation of ~2,000 translation units on an Intel i5-1235U with ~2.5 GB available RAM would require 45–75 minutes, violating the 45-minute Phase 0 time gate.

---

## 6. Commands Executed and Empirical Results

| Command | Working Dir | Exit Code | Empirical Result |
| :--- | :--- | :--- | :--- |
| `git status; Get-ChildItem -Force` | `c:\gcemhacks5.0` | 0 | Empty project folder, no Git repo initialized |
| `wsl -l -v` | Host | 0 | `docker-desktop Stopped 2` (No Linux distros) |
| `python -c "..."` (import check) | Host | 0 | NumPy, FastAPI, Pydantic, Uvicorn, Pytest imported cleanly |
| `python scripts/phase0/check_environment.py` | `c:\gcemhacks5.0` | 0 | Clean audit report output to terminal |
| `powershell -ExecutionPolicy Bypass -File scripts/phase0/check_ns3_lena.ps1` | `c:\gcemhacks5.0` | 1 | Correctly detected Case C and missing WSL Linux distribution |

---

## 7. Known Risks & Recommended Next Actions

1. **Risk:** Attempting native Windows C++ compilation of ns-3 / 5G-LENA will fail due to missing toolchains and POSIX system call dependencies.
   - **Mitigation:** Adhere strictly to the dual-track architecture: implement a high-fidelity discrete-event fallback simulator in pure Python/Gymnasium for immediate Phase 1–3 hackathon progress, while providing a standardized WSL2 Ubuntu setup recipe for offline/future 5G-LENA benchmarking.
2. **Risk:** Python 3.13 is newer than some pre-built PyTorch / Stable-Baselines3 binary wheels.
   - **Mitigation:** In Phase 1, create an isolated virtual environment (`.venv`). If Python 3.13 lacks compatible wheels for SB3/Torch, use Python 3.11 (which is already installed on the machine at `py -0 -> -V:3.11`) to ensure instant wheel installation without C++ source compilation.

---

## 8. Observation Verification Matrix

| Observation | Status |
| :--- | :--- |
| Windows 11 x86_64 Host OS | **Verified** |
| Intel i5-1235U (10 cores, 12 threads) | **Verified** |
| 15.69 GB Total RAM, ~2.5 GB free | **Verified** |
| 197.4 GB Free Disk on C: | **Verified** |
| Python 3.13.3 & 3.11 installed | **Verified** |
| NumPy 2.5.3, FastAPI 0.141.1, Pydantic 2.12.5, Pytest 9.1.1 | **Verified** |
| Gymnasium & Stable-Baselines3 not present in current env | **Verified** |
| Host C++ compilers and CMake absent | **Verified** |
| WSL installed without active Linux distribution | **Verified** |
| ns-3 and 5G-LENA absent from filesystem | **Verified** |
