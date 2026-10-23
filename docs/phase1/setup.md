# SLA Guardian — Phase 1 Setup & Developer Guide
**Project:** SLA Guardian — Reinforcement Learning-Based Network Slicing and Resource Allocation for 5G  
**Phase:** Phase 1 — Project Scaffolding, Virtual Environment and Shared Data Contracts  

---

## 1. Prerequisites

- **Python Interpreter:** Python 3.11 (tested on Python 3.11.9).
  * *Rationale:* Python 3.11 provides immediate, pre-built binary wheel compatibility for scientific and RL libraries (such as Gymnasium, NumPy, and future PyTorch/Stable-Baselines3) without requiring native C++ build tools.
- **Operating System:** Windows 11, Linux (Ubuntu 22.04+), or macOS.

---

## 2. Quickstart: Virtual Environment Setup

### On Windows (PowerShell):
```powershell
# 1. Verify Python 3.11 is installed
py -3.11 --version

# 2. Create the virtual environment
py -3.11 -m venv .venv

# 3. Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# 4. Install backend dependencies
pip install --upgrade pip
pip install -r backend\requirements.txt
```

### On Linux / macOS (Bash):
```bash
# 1. Create the virtual environment
python3.11 -m venv .venv

# 2. Activate the virtual environment
source .venv/bin/activate

# 3. Install backend dependencies
pip install --upgrade pip
pip install -r backend/requirements.txt
```

---

## 3. Verifying the Setup

Run the automated verification script:
```powershell
# Windows
.\.venv\Scripts\python.exe scripts\phase1\verify_environment.py

# Linux / macOS
python scripts/phase1/verify_environment.py
```
Expected output:
```
=================================================================
   SLA GUARDIAN - PHASE 1 ENVIRONMENT & DATA CONTRACT CHECK
=================================================================
[*] Python Executable : ...\.venv\Scripts\python.exe
[*] Python Version    : 3.11.9
[*] Virtualenv Active : YES

[+] DEPENDENCY IMPORT CHECK:
  [PASS] NumPy        : v1.26.4
  [PASS] Gymnasium    : v0.29.1
  [PASS] Pydantic     : v2.14.1
  [PASS] FastAPI      : v0.161.1
  [PASS] Uvicorn      : v0.54.0
  [PASS] Pytest       : v8.4.2

[+] SCENARIO & SCHEMA VALIDATION:
  [PASS] Successfully loaded scenario : default_three_slice_baseline
  [PASS] Canonical slices configured  : ['eMBB', 'URLLC', 'mURLLC']
  [PASS] Total Radio Capacity        : 100.0 PRB units
  [PASS] Total Compute Capacity      : 100.0 Compute units

[+] INTERFACE TEST DOUBLE VERIFICATION:
  [PASS] SimulatorInterface, PolicyInterface, EvaluatorInterface imported successfully.

=================================================================
VERDICT: PHASE 1 ENVIRONMENT & DATA CONTRACTS VERIFIED [OK]
```

---

## 4. Running the Test Suite

Execute the full pytest suite inside the virtual environment:
```powershell
# Windows
.\.venv\Scripts\python.exe -m pytest backend\tests -v

# Linux / macOS
pytest backend/tests -v
```

All 14 unit tests must pass without requiring network connectivity.

---

## 5. Launching the Backend API (Local Development)

```powershell
# Run the FastAPI server via Uvicorn
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

- Health Endpoint: `http://127.0.0.1:8000/health`
- Slices Metadata: `http://127.0.0.1:8000/api/slices`
- Interactive OpenAPI Docs: `http://127.0.0.1:8000/docs`

---

## 6. Known Setup Issues & Mitigations

1. **PowerShell Script Execution Policy (`PSSecurityException`):**  
   If PowerShell blocks activating the venv, run:
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```
   Or invoke the venv's Python interpreter directly: `.\.venv\Scripts\python.exe`.
2. **Global Python 3.13 vs Virtualenv Python 3.11:**  
   The host machine has Python 3.13 as the default Windows path. Always ensure commands use `.\.venv\Scripts\...` to prevent running against global Python packages.
