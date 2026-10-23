# SLA Guardian — Phase 0 Operations Runbook
**Project:** SLA Guardian — Reinforcement Learning-Based Network Slicing and Resource Allocation for 5G  
**Document:** Phase 0 Verification and Environment Runbook  
**Target Audience:** DevOps, Simulation Engineers, RL Engineers  

---

## 1. Overview

This runbook contains exact, copy-pasteable instructions for:
1. Auditing the host operating system, hardware resources, and installed toolchains.
2. Validating Python dependencies without contaminating system state.
3. Executing simulator verification scripts (both on Windows and Linux/WSL2).
4. Inspecting output logs and diagnostic artifacts.
5. Provisioning the recommended Phase 1 development environment.

---

## 2. Environment Audit (Step-by-Step)

### Option A: Windows (PowerShell / Command Prompt)
Run the cross-platform audit script directly:
```powershell
# From the project root (c:\gcemhacks5.0)
python scripts\phase0\check_environment.py
```

To inspect raw hardware and WSL distribution details on Windows:
```powershell
# Query Windows version, CPU, and Memory
Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, OSArchitecture, TotalVisibleMemorySize, FreePhysicalMemory | Format-List
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors | Format-List
Get-PSDrive C | Select-Object Used, Free | Format-List

# Query WSL distributions
wsl --list --verbose
```

### Option B: Native Linux / macOS (Bash)
```bash
# From the project root
python3 scripts/phase0/check_environment.py

# Raw system inspection
uname -a
lscpu || sysctl -n machdep.cpu.brand_string
free -h || vm_stat
df -h .
```

---

## 3. Simulator Verification

### Option A: Windows Environment
Execute the PowerShell verification wrapper:
```powershell
# Safe wrapper that detects WSL and ns-3 availability without crashing
powershell -ExecutionPolicy Bypass -File scripts\phase0\check_ns3_lena.ps1
```
Expected output if 5G-LENA/WSL is unconfigured:
- Diagnostic indicating `Case C: Simulator Not Installed` (Exit code: 1).
- Log saved to `logs\phase0\ns3_lena_verification_win.log`.

### Option B: Linux / WSL2 Environment
```bash
# Make script executable
chmod +x scripts/phase0/check_ns3_lena.sh

# Run verification (auto-discovers NS3_HOME or candidate paths)
./scripts/phase0/check_ns3_lena.sh

# Alternatively, specify a custom simulator directory:
./scripts/phase0/check_ns3_lena.sh /path/to/ns-allinone-3.48/ns-3.48
```
Verification Exit Codes:
- `0`: Simulator and NR module verified; minimal simulation example ran successfully.
- `1`: Simulator directory not found (Case C).
- `2`: Missing launcher (`ns3` / `waf`) or missing 5G-LENA (`nr`) module.
- `3`: Source code present but unbuilt (Case B).
- `4`: Example simulation run failed or timed out.

---

## 4. Inspecting Logs and Results

Logs are stored in `logs/phase0/`:
```powershell
# View Windows verification log
Get-Content logs\phase0\ns3_lena_verification_win.log

# View Linux / WSL verification log
cat logs/phase0/ns3_lena_verification.log
```

---

## 5. Offline Setup Guide: Setting up ns-3 & 5G-LENA (Reference Only)

If a developer wishes to establish a dedicated Linux environment for real 5G-LENA simulations outside the Phase 0 hackathon gate:

### Step 1: Install Ubuntu 24.04 on WSL2
```powershell
wsl --install -d Ubuntu-24.04
```

### Step 2: Install Linux Build Dependencies
```bash
sudo apt update && sudo apt install -y \
    build-essential \
    cmake \
    ninja-build \
    git \
    python3 \
    python3-dev \
    python3-pip \
    g++ \
    pkg-config \
    sqlite3 \
    libsqlite3-dev
```

### Step 3: Clone ns-3.48 and 5G-LENA v5.1
```bash
# Clone ns-3.48
git clone https://gitlab.com/nsnam/ns-3-dev.git ns-3.48
cd ns-3.48
git checkout ns-3.48

# Clone 5G-LENA NR module into contrib/
git clone https://gitlab.com/cttc-lena/nr.git contrib/nr
cd contrib/nr
git checkout nr-v5.1
cd ../..
```

### Step 4: Configure and Build
```bash
# Configure with examples enabled
./ns3 configure -d optimized --enable-examples --enable-tests

# Build target (requires 20-45 minutes depending on CPU)
./ns3 build

# Test minimal example
./ns3 run "cttc-nr-demo --simTime=0.1"
```

---

## 6. Phase 1 Virtual Environment Activation

For Phase 1 fallback simulator and RL development:
```powershell
# Create an isolated Python virtual environment
python -m venv .venv

# Activate virtual environment (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Upgrade pip and install Phase 1 dependencies
pip install --upgrade pip
pip install numpy gymnasium pytest pydantic
```
