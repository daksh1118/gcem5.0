#!/usr/bin/env python3
"""
SLA Guardian - Phase 1 Environment & Scaffolding Verification Script
Runs inside or checks the virtual environment, verifies imports, scenario parsing,
and interface instantiations.
"""

import sys
import os
import json
from pathlib import Path

# Ensure repository root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def check_virtualenv():
    in_venv = sys.prefix != sys.base_prefix
    print(f"[*] Python Executable : {sys.executable}")
    print(f"[*] Python Version    : {sys.version.split()[0]}")
    print(f"[*] Virtualenv Active : {'YES' if in_venv else 'NO (Recommended: run with .venv/Scripts/python)'}")
    return in_venv


def check_dependencies():
    required = [
        ("numpy", "NumPy"),
        ("gymnasium", "Gymnasium"),
        ("pydantic", "Pydantic"),
        ("fastapi", "FastAPI"),
        ("uvicorn", "Uvicorn"),
        ("pytest", "Pytest"),
    ]
    all_ok = True
    print("\n[+] DEPENDENCY IMPORT CHECK:")
    for mod_name, label in required:
        try:
            mod = __import__(mod_name)
            ver = getattr(mod, "__version__", "Available")
            print(f"  [PASS] {label:<12} : v{ver}")
        except ImportError as e:
            print(f"  [FAIL] {label:<12} : Missing ({e})")
            all_ok = False
    return all_ok


def check_scenario_loading():
    print("\n[+] SCENARIO & SCHEMA VALIDATION:")
    try:
        from backend.app.schemas.config import RunConfig, CANONICAL_SLICE_IDS
        root = Path(__file__).resolve().parent.parent.parent
        scenario_file = root / "scenarios" / "default.json"
        
        if not scenario_file.exists():
            print(f"  [FAIL] Default scenario not found at {scenario_file}")
            return False

        with open(scenario_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        config = RunConfig(**data)
        print(f"  [PASS] Successfully loaded scenario : {config.scenario_id}")
        print(f"  [PASS] Canonical slices configured  : {[s.value for s in CANONICAL_SLICE_IDS]}")
        print(f"  [PASS] Total Radio Capacity        : {config.total_radio_capacity} PRB units")
        print(f"  [PASS] Total Compute Capacity      : {config.total_compute_capacity} Compute units")
        return True
    except Exception as e:
        print(f"  [FAIL] Scenario loading error: {e}")
        return False


def check_interfaces():
    print("\n[+] INTERFACE TEST DOUBLE VERIFICATION:")
    try:
        from backend.app.interfaces.simulator import SimulatorInterface
        from backend.app.interfaces.policy import PolicyInterface, EvaluatorInterface
        print("  [PASS] SimulatorInterface, PolicyInterface, EvaluatorInterface imported successfully.")
        return True
    except Exception as e:
        print(f"  [FAIL] Interface import error: {e}")
        return False


def main():
    print("=" * 65)
    print("   SLA GUARDIAN - PHASE 1 ENVIRONMENT & DATA CONTRACT CHECK")
    print("=" * 65)

    check_virtualenv()
    dep_ok = check_dependencies()
    scen_ok = check_scenario_loading()
    iface_ok = check_interfaces()

    print("\n" + "=" * 65)
    if dep_ok and scen_ok and iface_ok:
        print("VERDICT: PHASE 1 ENVIRONMENT & DATA CONTRACTS VERIFIED [OK]")
        sys.exit(0)
    else:
        print("VERDICT: VERIFICATION FAILED - REVIEW LOGS ABOVE [FAIL]")
        sys.exit(1)


if __name__ == "__main__":
    main()
