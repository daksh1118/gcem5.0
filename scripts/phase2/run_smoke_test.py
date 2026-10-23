#!/usr/bin/env python3
"""
SLA Guardian - Phase 2 Simulation Smoke Test
Executes FallbackNetworkSimulator across all three scenarios:
  1. normal
  2. urllc_burst
  3. mixed_stress
Validates queue dynamics, telemetry emission, and failure-free execution.
"""

import sys
import json
from pathlib import Path

# Ensure repository root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig
from backend.app.schemas.actions import ExecutedAction
from backend.app.simulator.fallback import FallbackNetworkSimulator


def load_scenario(scen_path: Path) -> dict:
    if not scen_path.exists():
        raise FileNotFoundError(f"Scenario configuration not found: {scen_path}")
    with open(scen_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_scenario_test(scenario_name: str, num_steps: int = 50) -> dict:
    scen_path = ROOT_DIR / "scenarios" / "default.json"
    raw_scen = load_scenario(scen_path)

    # Instantiate config with specific scenario profile
    config = RunConfig(**raw_scen).model_copy(update={"traffic_profile": scenario_name, "max_steps": num_steps})
    sim = FallbackNetworkSimulator(config=config, scenario_data=raw_scen)

    # Reset simulator
    state = sim.reset(seed=42)
    assert state.step == 0, "Initial state step must be 0"

    # Define a documented valid balanced executed allocation
    # Total Radio: 45 + 25 + 30 = 100 PRB units
    # Total Compute: 45 + 25 + 30 = 100 Compute units
    action = ExecutedAction(
        radio_allocations={SliceId.EMBB: 45.0, SliceId.URLLC: 25.0, SliceId.MURLLC: 30.0},
        compute_allocations={SliceId.EMBB: 45.0, SliceId.URLLC: 25.0, SliceId.MURLLC: 30.0},
        priorities={SliceId.EMBB: 3, SliceId.URLLC: 1, SliceId.MURLLC: 2},
    )

    tot_offered = 0
    tot_delivered = 0
    tot_dropped = 0

    for step_idx in range(num_steps):
        next_state, diag = sim.step(action)
        assert next_state.step == step_idx + 1

        extra = diag.extra_info
        tot_offered += extra.get("total_offered_packets", 0)
        tot_delivered += extra.get("total_delivered_packets", 0)
        tot_dropped += diag.dropped_packets

    # Final summary snapshot
    final_queues = {s.value: sim.radio_queues[s].size() + sim.compute_queues[s].size() for s in CANONICAL_SLICE_IDS}
    latencies = {
        s.value: next_state.slice_states[s].p95_latency_ms
        for s in CANONICAL_SLICE_IDS
    }
    throughputs = {
        s.value: next_state.slice_states[s].delivered_throughput_mbps
        for s in CANONICAL_SLICE_IDS
    }

    return {
        "scenario": scenario_name,
        "steps_completed": num_steps,
        "total_offered_packets": tot_offered,
        "total_delivered_packets": tot_delivered,
        "total_dropped_packets": tot_dropped,
        "final_queues": final_queues,
        "p95_latencies_ms": latencies,
        "delivered_throughput_mbps": throughputs,
    }


def main():
    print("=" * 70)
    print("   SLA GUARDIAN - PHASE 2 FALLBACK SIMULATOR SMOKE TEST")
    print("   [NOTE: Fallback Python simulation output - not ns-3/5G-LENA]")
    print("=" * 70)

    scenarios = ["normal", "urllc_burst", "mixed_stress"]
    all_passed = True

    for scen in scenarios:
        try:
            res = run_scenario_test(scen, num_steps=50)
            print(f"\n[+] SCENARIO: '{res['scenario']}' ({res['steps_completed']} steps executed)")
            print(f"    Packets Offered   : {res['total_offered_packets']}")
            print(f"    Packets Delivered : {res['total_delivered_packets']}")
            print(f"    Packets Dropped   : {res['total_dropped_packets']}")
            print(f"    Final Queues      : {res['final_queues']}")
            print(f"    p95 Latency (ms)  : {res['p95_latencies_ms']}")
            print(f"    Throughput (Mbps) : {res['delivered_throughput_mbps']}")
            print(f"    Status            : [PASS]")
        except Exception as e:
            print(f"\n[-] SCENARIO '{scen}' FAILED: {e}")
            all_passed = False

    print("\n" + "=" * 70)
    if all_passed:
        print("VERDICT: ALL SCENARIOS COMPLETED SUCCESSFULLY [SMOKE TEST PASSED]")
        sys.exit(0)
    else:
        print("VERDICT: SMOKE TEST FAILED - CHECK ERRORS ABOVE")
        sys.exit(1)


if __name__ == "__main__":
    main()
