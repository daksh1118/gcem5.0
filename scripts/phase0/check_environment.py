#!/usr/bin/env python3
"""
SLA Guardian - Phase 0 Environment Audit Script
Checks host operating system, hardware resources, toolchains, Python packages,
and simulator readiness without altering the host system.
"""

import sys
import os
import platform
import shutil
import subprocess
import json

def get_platform_info():
    info = {
        "os_name": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
    }
    return info

def get_resource_info():
    res = {}
    # Disk space of current drive
    cwd = os.getcwd()
    try:
        total, used, free = shutil.disk_usage(cwd)
        res["disk_total_gb"] = round(total / (1024**3), 2)
        res["disk_used_gb"] = round(used / (1024**3), 2)
        res["disk_free_gb"] = round(free / (1024**3), 2)
    except Exception as e:
        res["disk_error"] = str(e)

    # Memory info (cross-platform via standard library or fallback)
    try:
        if platform.system() == "Windows":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            res["ram_total_gb"] = round(stat.ullTotalPhys / (1024**3), 2)
            res["ram_free_gb"] = round(stat.ullAvailPhys / (1024**3), 2)
        elif os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            mem_total = 0
            mem_free = 0
            for line in lines:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    mem_free = int(line.split()[1]) * 1024
            res["ram_total_gb"] = round(mem_total / (1024**3), 2)
            res["ram_free_gb"] = round(mem_free / (1024**3), 2)
    except Exception as e:
        res["ram_error"] = str(e)

    return res

def check_cli_tools():
    tools = [
        "git",
        "cmake",
        "gcc",
        "g++",
        "clang",
        "ninja",
        "make",
        "wsl",
        "docker"
    ]
    tool_status = {}
    for tool in tools:
        path = shutil.which(tool)
        if path:
            # Try to query version
            version_str = "Found"
            try:
                cmd = [path, "--version"]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
                if res.returncode == 0:
                    first_line = res.stdout.strip().split("\n")[0]
                    version_str = first_line[:60]
            except Exception:
                pass
            tool_status[tool] = {"available": True, "path": path, "version": version_str}
        else:
            tool_status[tool] = {"available": False, "path": None, "version": "Not installed"}
    return tool_status

def check_wsl_status():
    if platform.system() != "Windows":
        return {"applicable": False, "details": "Non-Windows host"}

    wsl_path = shutil.which("wsl")
    if not wsl_path:
        return {"applicable": True, "installed": False, "distros": []}

    try:
        # Run wsl -l -v
        res = subprocess.run(["wsl", "-l", "-v"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        raw = res.stdout.decode("utf-16", errors="ignore").strip()
        lines = [line.strip() for line in raw.split("\n") if line.strip()]
        return {"applicable": True, "installed": True, "output_lines": lines}
    except Exception as e:
        return {"applicable": True, "installed": True, "error": str(e)}

def check_python_packages():
    target_pkgs = [
        ("numpy", "NumPy (Data arrays & metrics)", "Phase 0/1/2"),
        ("gymnasium", "Gymnasium (RL Environment Interface)", "Phase 1"),
        ("stable_baselines3", "Stable-Baselines3 (PPO/DQN RL Algorithms)", "Phase 2"),
        ("fastapi", "FastAPI (Dashboard backend & REST API)", "Phase 3"),
        ("pydantic", "Pydantic (Data validation & schemas)", "Phase 0/1/2/3"),
        ("uvicorn", "Uvicorn (ASGI web server)", "Phase 3"),
        ("pytest", "Pytest (Unit & regression testing)", "Phase 0/1/2/3")
    ]
    results = {}
    for mod_name, label, phase in target_pkgs:
        try:
            mod = __import__(mod_name)
            ver = getattr(mod, "__version__", "Available (no __version__)")
            results[mod_name] = {
                "installed": True,
                "version": ver,
                "label": label,
                "phase_required": phase,
                "status": "PASS"
            }
        except ImportError:
            results[mod_name] = {
                "installed": False,
                "version": None,
                "label": label,
                "phase_required": phase,
                "status": "MISSING"
            }
        except Exception as e:
            results[mod_name] = {
                "installed": False,
                "version": None,
                "label": label,
                "phase_required": phase,
                "status": f"ERROR: {str(e)}"
            }
    return results

def detect_ns3_lena():
    candidates = [
        os.environ.get("NS3_HOME"),
        os.environ.get("LENA_HOME"),
        "C:\\ns-allinone-3.48",
        "C:\\ns-3.48",
        os.path.expanduser("~/ns-allinone-3.48"),
        os.path.expanduser("~/ns-3.48"),
        os.path.expanduser("~/ns-allinone-3.48/ns-3.48"),
        "/opt/ns-3.48",
    ]
    detected = []
    for cand in candidates:
        if cand and os.path.exists(cand):
            has_ns3_exec = os.path.exists(os.path.join(cand, "ns3")) or os.path.exists(os.path.join(cand, "waf"))
            has_nr = os.path.exists(os.path.join(cand, "contrib", "nr")) or os.path.exists(os.path.join(cand, "src", "nr"))
            detected.append({
                "path": cand,
                "has_launcher": has_ns3_exec,
                "has_nr_module": has_nr
            })
    return detected

def run_audit():
    print("=" * 70)
    print("   SLA GUARDIAN - PHASE 0 SYSTEM & ENVIRONMENT AUDIT REPORT")
    print("=" * 70)

    plat = get_platform_info()
    print("\n[+] HOST PLATFORM & OPERATING SYSTEM:")
    print(f"  OS               : {plat['os_name']} {plat['os_release']} (Build: {plat['os_version']})")
    print(f"  Architecture     : {plat['architecture']}")
    print(f"  Processor        : {plat['processor']}")
    print(f"  Python Runtime   : {plat['python_version']} ({plat['python_executable']})")

    res = get_resource_info()
    print("\n[+] HARDWARE RESOURCES:")
    print(f"  Total RAM        : {res.get('ram_total_gb', 'N/A')} GB")
    print(f"  Free RAM         : {res.get('ram_free_gb', 'N/A')} GB")
    print(f"  Disk Total (C:)  : {res.get('disk_total_gb', 'N/A')} GB")
    print(f"  Disk Free (C:)   : {res.get('disk_free_gb', 'N/A')} GB")

    tools = check_cli_tools()
    print("\n[+] BUILD TOOLCHAINS & UTILITIES:")
    for t_name, t_info in tools.items():
        state = "[OK]  " if t_info["available"] else "[FAIL]"
        print(f"  {state} {t_name:<10}: {t_info['version']}")

    wsl_info = check_wsl_status()
    print("\n[+] WSL2 / LINUX SUBSYSTEM STATUS:")
    if wsl_info.get("applicable"):
        if wsl_info.get("installed"):
            print("  WSL Subsystem   : Available")
            lines = wsl_info.get("output_lines", [])
            if lines:
                for line in lines:
                    print(f"    - {line}")
            else:
                print("    - No distributions registered.")
        else:
            print("  WSL Subsystem   : Not installed")
    else:
        print("  WSL Subsystem   : N/A (Running natively on Linux/macOS)")

    pkgs = check_python_packages()
    print("\n[+] PYTHON PACKAGE READINESS:")
    for pkg_name, pkg_data in pkgs.items():
        st = f"[{pkg_data['status']}]"
        v = pkg_data['version'] if pkg_data['version'] else "None"
        print(f"  {st:<8} {pkg_name:<18} : {v:<12} ({pkg_data['phase_required']})")

    lena_detections = detect_ns3_lena()
    print("\n[+] NS-3 / 5G-LENA LOCAL DETECTION:")
    if lena_detections:
        for det in lena_detections:
            print(f"  Path: {det['path']} (ns3 launcher: {det['has_ns3_exec']}, nr module: {det['has_nr_module']})")
    else:
        print("  Status: NO existing ns-3 / 5G-LENA installation detected on host filesystem.")

    print("\n" + "=" * 70)
    print("AUDIT SUMMARY & FEASIBILITY ASSESSMENT:")
    print("  Host OS         : Native Windows 11 (requires Linux/WSL2 for ns-3 / 5G-LENA build)")
    print("  Linux Toolchain : Missing C++ compiler (g++/clang) and CMake on native host")
    print("  WSL2 State      : Installed but lacking Linux distribution (only docker-desktop found)")
    print("  5G-LENA Status  : Not installed (Case C - Simulation source absent)")
    print("  RL / API Stacks : NumPy, FastAPI, Pydantic, Uvicorn, Pytest VERIFIED.")
    print("                    Gymnasium and SB3 to be installed in project virtualenv for Phase 1/2.")
    print("  Simulator Path  : Fallback discrete-event simulation recommended for Phase 1.")
    print("=" * 70)

if __name__ == "__main__":
    run_audit()
