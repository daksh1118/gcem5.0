"""
SLA Guardian - Corrective Multi-Policy Macro-Control Benchmark
Evaluates four policies under identical 100 ms macro-control intervals:
1. Static Baseline Policy
2. Adaptive Demand Heuristic Policy
3. Frozen Constrained PPO Agent (models/agent.zip)
4. Candidate Multi-Scenario PPO Agent (models/candidate_agent.zip)

Evaluated across:
- 5 scenarios: normal, embb_surge, urllc_burst, murllc_storm, mixed_stress
- 3 seeds: 42, 101, 202
- 50 macro-steps per trial (10 sub-steps x 10 ms = 100 ms per macro-step, 5.0s sim time)
Total trials: 4 policies x 5 scenarios x 3 seeds = 60 trials.
"""

import sys
import os
import json
import csv
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import numpy as np

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.app.schemas.config import RunConfig, SliceId, CANONICAL_SLICE_IDS
from backend.app.schemas.state import NetworkState
from backend.app.interfaces.policy import PolicyInterface
from backend.app.policies import (
    StaticSlicingPolicy,
    AdaptiveDemandHeuristicPolicy,
    RLPolicy,
)
from backend.app.simulator.fallback import FallbackNetworkSimulator
from backend.app.control.safety_shield import SafetyShield
from backend.app.rl.control_interval import MacroControlAdapter
from backend.app.rl.cost import ViolationCostAdapter


def compute_sha256(filepath: Path) -> str:
    if not filepath.exists():
        return "NOT_FOUND"
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def evaluate_macro_trial(
    policy_name: str,
    policy_instance: PolicyInterface,
    scenario_name: str,
    raw_scenario_config: dict,
    num_macro_steps: int = 50,
    seed: int = 42,
    steps_per_interval: int = 10,
) -> Dict[str, Any]:
    """
    Executes a single benchmark trial at the 100 ms macro-control interval.
    """
    config = RunConfig(**raw_scenario_config).model_copy(
        update={"traffic_profile": scenario_name, "seed": seed}
    )

    simulator = FallbackNetworkSimulator(config=config)
    shield = SafetyShield()
    macro_adapter = MacroControlAdapter(
        simulator=simulator,
        config=config,
        steps_per_interval=steps_per_interval,
    )
    cost_adapter = ViolationCostAdapter(cost_limit=0.01)

    current_state = simulator.reset(seed=seed, config=config)

    # Accumulators
    total_offered = {s: 0 for s in CANONICAL_SLICE_IDS}
    total_delivered = {s: 0 for s in CANONICAL_SLICE_IDS}
    total_dropped = {s: 0 for s in CANONICAL_SLICE_IDS}
    step_tputs = {s: [] for s in CANONICAL_SLICE_IDS}
    step_lats = {s: [] for s in CANONICAL_SLICE_IDS}
    step_costs: List[float] = []
    radio_utils: List[float] = []
    compute_utils: List[float] = []
    total_churn = 0.0
    shield_interventions = 0
    sla_breach_steps = 0
    prev_executed = None

    for _ in range(num_macro_steps):
        # 1. Propose action
        proposed = policy_instance.predict(current_state)

        # 2. Safety Shield projection
        shield_res = shield.validate(proposed, current_state, config)
        executed = shield_res.executed_action
        if shield_res.intervention_occurred:
            shield_interventions += 1

        # 3. Churn tracking
        if prev_executed is not None:
            for s in CANONICAL_SLICE_IDS:
                total_churn += abs(executed.radio_allocations[s] - prev_executed.radio_allocations[s])
                total_churn += abs(executed.compute_allocations[s] - prev_executed.compute_allocations[s])
        prev_executed = executed

        # 4. Macro step execution (100 ms)
        next_state, step_metrics, diag = macro_adapter.execute_macro_step(current_state, executed)

        # 5. Accumulate metrics
        for s in CANONICAL_SLICE_IDS:
            total_offered[s] += step_metrics.offered_packets.get(s, 0)
            total_delivered[s] += step_metrics.delivered_packets.get(s, 0)
            total_dropped[s] += step_metrics.dropped_packets.get(s, 0)
            step_tputs[s].append(step_metrics.throughput_mbps.get(s, 0.0))
            lat = step_metrics.p95_latency_ms.get(s)
            if lat is not None:
                step_lats[s].append(lat)

        step_cost = cost_adapter.compute_step_cost(step_metrics, diag)
        step_costs.append(step_cost)

        radio_utils.append(step_metrics.radio_utilization_ratio)
        compute_utils.append(step_metrics.compute_utilization_ratio)

        if step_metrics.sla_breach_count > 0:
            sla_breach_steps += 1

        current_state = next_state

    # Post-trial calculations
    pdr = {}
    for s in CANONICAL_SLICE_IDS:
        finished = total_delivered[s] + total_dropped[s]
        pdr[s] = float(total_delivered[s] / finished) if finished > 0 else 1.0

    crit_offered = total_offered[SliceId.URLLC] + total_offered[SliceId.MURLLC]
    crit_deliv = total_delivered[SliceId.URLLC] + total_delivered[SliceId.MURLLC]
    crit_drop = total_dropped[SliceId.URLLC] + total_dropped[SliceId.MURLLC]
    crit_denom = max(crit_offered, crit_deliv + crit_drop)
    crit_cost = float(crit_drop / crit_denom) if crit_denom > 0 else 0.0

    mean_tput = {s: float(np.mean(step_tputs[s])) for s in CANONICAL_SLICE_IDS}
    total_tput = sum(mean_tput.values())

    p95_lat = {}
    for s in CANONICAL_SLICE_IDS:
        p95_lat[s] = float(np.percentile(step_lats[s], 95)) if step_lats[s] else None

    return {
        "scenario": scenario_name,
        "seed": seed,
        "policy": policy_name,
        "embb_tput_mbps": round(mean_tput[SliceId.EMBB], 2),
        "urllc_tput_mbps": round(mean_tput[SliceId.URLLC], 2),
        "murllc_tput_mbps": round(mean_tput[SliceId.MURLLC], 2),
        "total_tput_mbps": round(total_tput, 2),
        "embb_pdr": round(pdr[SliceId.EMBB], 4),
        "urllc_pdr": round(pdr[SliceId.URLLC], 4),
        "murllc_pdr": round(pdr[SliceId.MURLLC], 4),
        "critical_cost": round(crit_cost, 4),
        "mean_step_cost": round(float(np.mean(step_costs)), 4),
        "urllc_p95_lat_ms": round(p95_lat[SliceId.URLLC], 2) if p95_lat[SliceId.URLLC] is not None else None,
        "radio_util": round(float(np.mean(radio_utils)), 4),
        "compute_util": round(float(np.mean(compute_utils)), 4),
        "allocation_churn": round(total_churn, 2),
        "shield_interventions": shield_interventions,
        "sla_breach_ratio": round(sla_breach_steps / num_macro_steps, 4),
        "delivered_packets": {s.value: total_delivered[s] for s in CANONICAL_SLICE_IDS},
        "dropped_packets": {s.value: total_dropped[s] for s in CANONICAL_SLICE_IDS},
    }


def main():
    print("=" * 90)
    print("   SLA GUARDIAN - CORRECTIVE MULTI-POLICY BENCHMARK (100 ms MACRO-INTERVAL)")
    print("   Comparing: Static vs Adaptive Heuristic vs Frozen PPO vs Candidate PPO")
    print("=" * 90)

    scenario_file = ROOT_DIR / "scenarios" / "default.json"
    with open(scenario_file, "r", encoding="utf-8") as f:
        raw_scen = json.load(f)

    base_config = RunConfig(**raw_scen)
    frozen_path = ROOT_DIR / "models" / "agent.zip"
    candidate_path = ROOT_DIR / "models" / "candidate_agent.zip"

    frozen_hash = compute_sha256(frozen_path)
    candidate_hash = compute_sha256(candidate_path)

    print(f"[*] Frozen PPO Checkpoint   : {frozen_path} | SHA-256: {frozen_hash}")
    print(f"[*] Candidate PPO Checkpoint: {candidate_path} | SHA-256: {candidate_hash}")

    if not candidate_path.exists():
        raise FileNotFoundError(f"Candidate model not found at {candidate_path}. Training must finish first.")

    scenarios = ["normal", "embb_surge", "urllc_burst", "murllc_storm", "mixed_stress"]
    seeds = [42, 101, 202]
    num_macro_steps = 50  # 50 x 100 ms = 5.0 seconds

    out_dir = ROOT_DIR / "backend" / "artifacts" / "phase8"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Initialize policies
    policies = {
        "static": StaticSlicingPolicy(config=base_config),
        "heuristic": AdaptiveDemandHeuristicPolicy(config=base_config, smoothing_factor=0.20),
        "frozen_ppo": RLPolicy(checkpoint_path=frozen_path, config=base_config, deterministic=True),
        "candidate_ppo": RLPolicy(checkpoint_path=candidate_path, config=base_config, deterministic=True),
    }

    records = []
    summary_by_scenario = {scen: {p: [] for p in policies} for scen in scenarios}

    start_time = time.time()

    for scen in scenarios:
        print(f"\n[*] Evaluating Scenario: '{scen.upper()}' across {len(seeds)} seeds...")
        for seed in seeds:
            for p_key, p_inst in policies.items():
                rec = evaluate_macro_trial(
                    policy_name=p_key,
                    policy_instance=p_inst,
                    scenario_name=scen,
                    raw_scenario_config=raw_scen,
                    num_macro_steps=num_macro_steps,
                    seed=seed,
                )
                records.append(rec)
                summary_by_scenario[scen][p_key].append(rec)

    duration = time.time() - start_time
    print(f"\n[+] Completed all {len(records)} trials in {duration:.2f} seconds.")

    # 1. Save JSON
    json_path = out_dir / "corrective_benchmark.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "control_interval_ms": 100,
                "macro_steps_per_trial": num_macro_steps,
                "frozen_model_sha256": frozen_hash,
                "candidate_model_sha256": candidate_hash,
                "scenarios": scenarios,
                "seeds": seeds,
                "policies": list(policies.keys()),
                "records": records,
            },
            f,
            indent=2,
        )
    print(f"[+] Saved JSON benchmark to: {json_path}")

    # 2. Save CSV
    csv_path = out_dir / "corrective_benchmark.csv"
    if records:
        # Exclude dict fields from CSV
        flat_records = []
        for r in records:
            item = {k: v for k, v in r.items() if not isinstance(v, dict)}
            flat_records.append(item)
        keys = flat_records[0].keys()
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(flat_records)
    print(f"[+] Saved CSV benchmark to: {csv_path}")

    # 3. Compute Averages and Save Markdown Report
    md_path = out_dir / "corrective_results.md"
    policy_labels = {
        "static": "Static",
        "heuristic": "Heuristic",
        "frozen_ppo": "Frozen PPO",
        "candidate_ppo": "**Candidate PPO**",
    }

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# SLA Guardian: Phase 8 Corrective Benchmark Results\n\n")
        f.write(f"- **Generated At:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        f.write(f"- **Control Interval:** 100 ms Macro-Control Interval (MacroControlAdapter, 10 sub-steps/interval)\n")
        f.write(f"- **Frozen PPO Checkpoint SHA-256:** `{frozen_hash}`\n")
        f.write(f"- **Candidate PPO Checkpoint SHA-256:** `{candidate_hash}`\n")
        f.write(f"- **Scenarios:** 5 (`{', '.join(scenarios)}`)\n")
        f.write(f"- **Seeds per Scenario:** {seeds} (4 policies x 5 scenarios x 3 seeds = 60 trials)\n")
        f.write(f"- **Simulated Duration per Trial:** 5.0 seconds (50 macro-steps x 100 ms)\n\n")

        f.write("## Mean Performance Across Evaluated Scenarios\n\n")
        f.write("| Scenario | Policy | eMBB Tput (Mbps) | Total Tput (Mbps) | eMBB PDR | URLLC PDR | mURLLC PDR | Critical Cost | Churn (L1) | Breach Ratio |\n")
        f.write("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")

        for scen in scenarios:
            for p_key, p_label in policy_labels.items():
                recs = summary_by_scenario[scen][p_key]
                mean_embb = float(np.mean([r["embb_tput_mbps"] for r in recs]))
                mean_tot = float(np.mean([r["total_tput_mbps"] for r in recs]))
                mean_embb_pdr = float(np.mean([r["embb_pdr"] for r in recs]))
                mean_urllc_pdr = float(np.mean([r["urllc_pdr"] for r in recs]))
                mean_murllc_pdr = float(np.mean([r["murllc_pdr"] for r in recs]))
                mean_crit_cost = float(np.mean([r["critical_cost"] for r in recs]))
                mean_churn = float(np.mean([r["allocation_churn"] for r in recs]))
                mean_breach = float(np.mean([r["sla_breach_ratio"] for r in recs]))

                f.write(
                    f"| {scen} | {p_label} | {mean_embb:.2f} | {mean_tot:.2f} | {mean_embb_pdr:.4f} | {mean_urllc_pdr:.4f} | {mean_murllc_pdr:.4f} | {mean_crit_cost:.4f} | {mean_churn:.1f} | {mean_breach:.2f} |\n"
                )

    print(f"[+] Saved Markdown results report to: {md_path}")


if __name__ == "__main__":
    main()
