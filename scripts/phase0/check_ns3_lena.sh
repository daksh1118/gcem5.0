#!/usr/bin/env bash
# ==============================================================================
# SLA Guardian - Phase 0 ns-3 & 5G-LENA Simulator Verification Script
# Target Environment: Linux / WSL2 (Ubuntu 22.04 or 24.04 LTS)
# ==============================================================================

set -uo pipefail

LOG_DIR="${PROJECT_ROOT:-$(pwd)}/logs/phase0"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/ns3_lena_verification.log"

echo "=================================================================" | tee "$LOG_FILE"
echo "   SLA GUARDIAN - 5G-LENA / ns-3 SIMULATOR VERIFICATION SCRIPT   " | tee -a "$LOG_FILE"
echo "=================================================================" | tee -a "$LOG_FILE"
echo "Timestamp: $(date -u)" | tee -a "$LOG_FILE"

# Determine simulator path
CANDIDATE_PATHS=(
    "${NS3_HOME:-}"
    "${LENA_HOME:-}"
    "$HOME/ns-allinone-3.48/ns-3.48"
    "$HOME/ns-3.48"
    "/opt/ns-3.48"
    "$1:-"
)

SIM_DIR=""
for p in "${CANDIDATE_PATHS[@]}"; do
    if [ -n "$p" ] && [ -d "$p" ]; then
        SIM_DIR="$p"
        break
    fi
done

echo "[*] Step 1: Simulator Directory Discovery..." | tee -a "$LOG_FILE"
if [ -z "$SIM_DIR" ]; then
    echo "[-] FAILED: No ns-3 / 5G-LENA directory located in candidate search paths." | tee -a "$LOG_FILE"
    echo "    Candidate paths searched:" | tee -a "$LOG_FILE"
    for p in "${CANDIDATE_PATHS[@]}"; do
        [ -n "$p" ] && echo "      - $p" | tee -a "$LOG_FILE"
    done
    echo "[!] VERDICT: SIMULATOR NOT INSTALLED (Case C). Exit code: 1" | tee -a "$LOG_FILE"
    exit 1
fi

echo "[+] FOUND Simulator Directory: $SIM_DIR" | tee -a "$LOG_FILE"

echo "[*] Step 2: Validating ns-3 Launcher and 5G-LENA Module..." | tee -a "$LOG_FILE"
LAUNCHER=""
if [ -x "$SIM_DIR/ns3" ]; then
    LAUNCHER="$SIM_DIR/ns3"
elif [ -x "$SIM_DIR/waf" ]; then
    LAUNCHER="$SIM_DIR/waf"
else
    echo "[-] FAILED: Neither 'ns3' (CMake) nor 'waf' launcher executable found in $SIM_DIR" | tee -a "$LOG_FILE"
    exit 2
fi
echo "[+] Launcher identified: $LAUNCHER" | tee -a "$LOG_FILE"

NR_DIR=""
if [ -d "$SIM_DIR/contrib/nr" ]; then
    NR_DIR="$SIM_DIR/contrib/nr"
elif [ -d "$SIM_DIR/src/nr" ]; then
    NR_DIR="$SIM_DIR/src/nr"
else
    echo "[-] FAILED: 5G-LENA 'nr' module directory not detected under contrib/nr or src/nr" | tee -a "$LOG_FILE"
    exit 2
fi
echo "[+] 5G-LENA NR Module located at: $NR_DIR" | tee -a "$LOG_FILE"

echo "[*] Step 3: Checking Build Status..." | tee -a "$LOG_FILE"
# Check if build directory has compiled nr libraries
BUILT=0
if [ -d "$SIM_DIR/build" ]; then
    if find "$SIM_DIR/build" -name "libns3*-nr*" 2>/dev/null | grep -q .; then
        BUILT=1
    fi
fi

if [ "$BUILT" -eq 0 ]; then
    echo "[-] WARNING: 5G-LENA is present as source code but has NOT been compiled." | tee -a "$LOG_FILE"
    echo "    Compile using: cd $SIM_DIR && ./ns3 configure -d optimized --enable-examples && ./ns3 build" | tee -a "$LOG_FILE"
    echo "[!] VERDICT: SIMULATOR SOURCE PRESENT BUT UNBUILT (Case B). Exit code: 3" | tee -a "$LOG_FILE"
    exit 3
fi

echo "[+] Simulator build artifacts detected." | tee -a "$LOG_FILE"

echo "[*] Step 4: Running Minimal 5G NR Simulation Example..." | tee -a "$LOG_FILE"
EXAMPLE_NAME="cttc-nr-demo"
RUN_CMD="$LAUNCHER run \"$EXAMPLE_NAME --simTime=0.1\""

echo "Executing: $RUN_CMD" | tee -a "$LOG_FILE"
START_TIME=$(date +%s)

cd "$SIM_DIR" || exit 1
if timeout 90s $LAUNCHER run "$EXAMPLE_NAME --simTime=0.1" >> "$LOG_FILE" 2>&1; then
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    echo "[+] SUCCESS: Simulation example executed cleanly in ${DURATION}s." | tee -a "$LOG_FILE"
    echo "[!] VERDICT: SIMULATOR VERIFIED AND OPERATIONAL (Case A). Exit code: 0" | tee -a "$LOG_FILE"
    exit 0
else
    RC=$?
    echo "[-] FAILED: Simulation example failed with exit code $RC." | tee -a "$LOG_FILE"
    echo "    Check output details in $LOG_FILE" | tee -a "$LOG_FILE"
    exit 4
fi
