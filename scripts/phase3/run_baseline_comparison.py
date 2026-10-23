#!/usr/bin/env python3
"""
SLA Guardian - Phase 3 Baseline Comparison Runner
Executes StaticSlicingPolicy vs AdaptiveDemandHeuristicPolicy
across all three standard scenarios ('normal', 'urllc_burst', 'mixed_stress').
Evaluates SLA compliance, latency, throughput, and churn, saving JSON artifacts and printing a summary.
"""

import sys
import json
from pathlib import Path
from typing import Dict, Any, List

# Ensure repository root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.schemas.config import SliceId, CANONICAL_SLICE_IDS, RunConfig
from backend.app.schemas.actions import ExecutedAction
from backend.app.simulator.fallback import FallbackNetworkSimulator
from backend.app.policies.static import StaticSlicingPolicy
from backend.app.policies.heuristic import AdaptiveDemandHeuristicPolicy
from backend.app.evaluation.metrics import SlaMetricEvaluator


from backend.app.control.safety_shield import SafetyShield
from backend.app.control.pipeline import PolicyExecutionPipeline


def run_single_experiment(
    policy_name: str,
    policy_instance: Any,
    scenario_name: str,
    raw_scenario_data: dict,
    num_steps: int = 50,
    seed: int = 42,
) -> dict:
    """Runs a single policy against a fresh simulator instance for num_steps via SafetyShield."""
    config = RunConfig(**raw_scenario_data).model_copy(
        update={"traffic_profile": scenario_name, "max_steps": num_steps, "seed": seed}
    )

    sim = FallbackNetworkSimulator(config=config, scenario_data=raw_scenario_data)
    evaluator = SlaMetricEvaluator()
    evaluator.reset_accumulator()
    shield = SafetyShield()

    pipeline = PolicyExecutionPipeline(
        simulator=sim,
        evaluator=evaluator,
        safety_shield=shield,
        config=config,
    )

    # Reset policy internal state if applicable
    if hasattr(policy_instance, "reset_state"):
        policy_instance.reset_state()

    current_state = sim.reset(seed=seed)
    interventions = 0

    for step_idx in range(num_steps):
        next_state, record = pipeline.execute_step(current_state, policy_instance)
        if record.safety_result.intervention_occurred:
            interventions += 1
        current_state = next_state

    # Build final run summary
    run_res = evaluator.build_run_result(
        run_id=f"{policy_name}_{scenario_name}_s{seed}",
        scenario_id=scenario_name,
        seed=seed,
        policy_id=policy_instance.policy_id,
        policy_version=policy_instance.policy_version,
        config=config,
    )

    result_dict = run_res.model_dump()
    if result_dict.get("aggregate_metrics") is not None:
        result_dict["aggregate_metrics"]["shield_interventions"] = float(interventions)
    return result_dict


def main():
    print("=" * 75)
    print("   SLA GUARDIAN - PHASE 3 BASELINE COMPARISON ROLLOUT")
    print("   Evaluating StaticSlicingPolicy vs AdaptiveDemandHeuristicPolicy")
    print("=" * 75)

    scenario_file = ROOT_DIR / "scenarios" / "default.json"
    with open(scenario_file, "r", encoding="utf-8") as f:
        raw_scen = json.load(f)

    base_config = RunConfig(**raw_scen)

    scenarios = ["normal", "urllc_burst", "mixed_stress"]
    comparison_results: List[Dict[str, Any]] = []

    # Output directory
    artifacts_dir = ROOT_DIR / "backend" / "artifacts" / "phase3"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    for scen in scenarios:
        print(f"\n" + "-" * 75)
        print(f"[*] RUNNING SCENARIO: '{scen.upper()}' (50 steps, seed=42)")
        print("-" * 75)

        # 1. Run Static Baseline
        p_static = StaticSlicingPolicy(config=base_config)
        res_static = run_single_experiment(
            policy_name="static",
            policy_instance=p_static,
            scenario_name=scen,
            raw_scenario_data=raw_scen,
            num_steps=50,
            seed=42,
        )

        # 2. Run Adaptive Heuristic Baseline
        p_heuristic = AdaptiveDemandHeuristicPolicy(config=base_config, smoothing_factor=0.20)
        res_heuristic = run_single_experiment(
            policy_name="heuristic",
            policy_instance=p_heuristic,
            scenario_name=scen,
            raw_scenario_data=raw_scen,
            num_steps=50,
            seed=42,
        )

        # Print comparison metrics
        agg_s = res_static["aggregate_metrics"]
        agg_h = res_heuristic["aggregate_metrics"]

        print(f"  {'Metric':<32} | {'Static Baseline':<18} | {'Adaptive Heuristic':<18}")
        print(f"  {'-'*32}-+-{'-'*18}-+-{'-'*18}")
        print(f"  {'Shield Interventions':<32} | {int(agg_s.get('shield_interventions', 0)):<18} | {int(agg_h.get('shield_interventions', 0)):<18}")
        print(f"  {'SLA Breach Step Ratio':<32} | {agg_s.get('sla_breach_step_ratio', 0.0):<18.2%} | {agg_h.get('sla_breach_step_ratio', 0.0):<18.2%}")
        print(f"  {'Mean Radio Utilization':<32} | {agg_s.get('mean_radio_utilization', 0.0):<18.2%} | {agg_h.get('mean_radio_utilization', 0.0):<18.2%}")
        print(f"  {'Mean Compute Utilization':<32} | {agg_s.get('mean_compute_utilization', 0.0):<18.2%} | {agg_h.get('mean_compute_utilization', 0.0):<18.2%}")
        print(f"  {'Allocation Churn (L1)':<32} | {agg_s.get('total_churn', 0.0):<18.2f} | {agg_h.get('total_churn', 0.0):<18.2f}")
        for s in CANONICAL_SLICE_IDS:
            s_val = s.value
            t_s = agg_s.get(f'mean_throughput_mbps_{s_val}', 0.0)
            t_h = agg_h.get(f'mean_throughput_mbps_{s_val}', 0.0)
            print(f"  {f'Mean Throughput {s_val} (Mbps)':<32} | {t_s:<18.2f} | {t_h:<18.2f}")
            p_s = agg_s.get(f'overall_pdr_{s_val}', 0.0)
            p_h = agg_h.get(f'overall_pdr_{s_val}', 0.0)
            print(f"  {f'Overall PDR {s_val}':<32} | {p_s:<18.4f} | {p_h:<18.4f}")

        comparison_results.append({
            "scenario": scen,
            "static_summary": agg_s,
            "heuristic_summary": agg_h,
        })

    # Save artifact
    output_path = artifacts_dir / "baseline_comparison_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(comparison_results, f, indent=2)

    print(f"\n" + "=" * 75)
    print(f"[+] Complete experiment comparison artifact saved to:\n    {output_path}")
    print("=" * 75)


if __name__ == "__main__":
    main()
