"""
SLA Guardian - Phase 5 Three-Policy Benchmark Evaluation
Fair, matched evaluation of:
1. Static Baseline (StaticSlicingPolicy)
2. Adaptive Heuristic Baseline (AdaptiveDemandHeuristicPolicy)
3. Constrained PPO Agent (RLPolicy loading models/agent.zip)

Across all five merged scenarios:
- normal
- embb_surge
- urllc_burst
- murllc_storm
- mixed_stress

Saves structured results to: backend/artifacts/phase5/baseline_comparison_results.json
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, List

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.app.schemas.config import RunConfig, CANONICAL_SLICE_IDS
from backend.app.simulator.fallback import FallbackNetworkSimulator
from backend.app.control.safety_shield import SafetyShield
from backend.app.control.pipeline import PolicyExecutionPipeline
from backend.app.evaluation.metrics import SlaMetricEvaluator
from backend.app.policies.static import StaticSlicingPolicy
from backend.app.policies.heuristic import AdaptiveDemandHeuristicPolicy
from backend.app.policies.rl_policy import RLPolicy


def run_single_evaluation(
    policy_name: str,
    policy_instance: Any,
    scenario_name: str,
    raw_scenario_data: Dict[str, Any],
    num_steps: int = 50,
    seed: int = 42,
) -> Dict[str, Any]:
    """Runs a single policy against a single scenario through the safety pipeline."""
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

    if hasattr(policy_instance, "reset_state"):
        policy_instance.reset_state()

    current_state = sim.reset(seed=seed)
    interventions = 0

    for _ in range(num_steps):
        next_state, record = pipeline.execute_step(current_state, policy_instance)
        if record.safety_result.intervention_occurred:
            interventions += 1
        current_state = next_state

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
    print("=" * 85)
    print("   SLA GUARDIAN - PHASE 5 COMPREHENSIVE THREE-POLICY BENCHMARK")
    print("   Comparing Static Baseline vs Adaptive Heuristic vs Constrained PPO Agent")
    print("=" * 85)

    scenario_file = ROOT_DIR / "scenarios" / "default.json"
    with open(scenario_file, "r", encoding="utf-8") as f:
        raw_scen = json.load(f)

    base_config = RunConfig(**raw_scen)
    scenarios = ["normal", "embb_surge", "urllc_burst", "murllc_storm", "mixed_stress"]
    all_comparison_results: List[Dict[str, Any]] = []

    artifacts_dir = ROOT_DIR / "backend" / "artifacts" / "phase5"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Initialize RL Policy once
    model_path = ROOT_DIR / "models" / "agent.zip"
    rl_policy = RLPolicy(checkpoint_path=model_path, config=base_config)

    for scen in scenarios:
        print(f"\n" + "-" * 85)
        print(f"[*] EVALUATING SCENARIO: '{scen.upper()}' (50 steps, seed=42)")
        print("-" * 85)

        # 1. Static
        p_static = StaticSlicingPolicy(config=base_config)
        res_static = run_single_evaluation("static", p_static, scen, raw_scen, num_steps=50, seed=42)

        # 2. Heuristic
        p_heuristic = AdaptiveDemandHeuristicPolicy(config=base_config, smoothing_factor=0.20)
        res_heuristic = run_single_evaluation("heuristic", p_heuristic, scen, raw_scen, num_steps=50, seed=42)

        # 3. Constrained PPO
        res_ppo = run_single_evaluation("constrained_ppo", rl_policy, scen, raw_scen, num_steps=50, seed=42)

        agg_s = res_static["aggregate_metrics"]
        agg_h = res_heuristic["aggregate_metrics"]
        agg_p = res_ppo["aggregate_metrics"]

        print(f"  {'Metric':<28} | {'Static':<15} | {'Heuristic':<15} | {'PPO Agent':<15}")
        print(f"  {'-'*28}-+-{'-'*15}-+-{'-'*15}-+-{'-'*15}")
        print(f"  {'Shield Interventions':<28} | {int(agg_s.get('shield_interventions', 0)):<15} | {int(agg_h.get('shield_interventions', 0)):<15} | {int(agg_p.get('shield_interventions', 0)):<15}")
        print(f"  {'SLA Breach Step Ratio':<28} | {agg_s.get('sla_breach_step_ratio', 0.0):<15.2%} | {agg_h.get('sla_breach_step_ratio', 0.0):<15.2%} | {agg_p.get('sla_breach_step_ratio', 0.0):<15.2%}")
        print(f"  {'Mean Radio Util':<28} | {agg_s.get('mean_radio_utilization', 0.0):<15.2%} | {agg_h.get('mean_radio_utilization', 0.0):<15.2%} | {agg_p.get('mean_radio_utilization', 0.0):<15.2%}")
        print(f"  {'Mean Compute Util':<28} | {agg_s.get('mean_compute_utilization', 0.0):<15.2%} | {agg_h.get('mean_compute_utilization', 0.0):<15.2%} | {agg_p.get('mean_compute_utilization', 0.0):<15.2%}")
        print(f"  {'Allocation Churn (L1)':<28} | {agg_s.get('total_churn', 0.0):<15.2f} | {agg_h.get('total_churn', 0.0):<15.2f} | {agg_p.get('total_churn', 0.0):<15.2f}")
        for s in CANONICAL_SLICE_IDS:
            s_val = s.value
            t_s = agg_s.get(f'mean_throughput_mbps_{s_val}', 0.0)
            t_h = agg_h.get(f'mean_throughput_mbps_{s_val}', 0.0)
            t_p = agg_p.get(f'mean_throughput_mbps_{s_val}', 0.0)
            print(f"  {f'Throughput {s_val} (Mbps)':<28} | {t_s:<15.2f} | {t_h:<15.2f} | {t_p:<15.2f}")
            p_s = agg_s.get(f'overall_pdr_{s_val}', 0.0)
            p_h = agg_h.get(f'overall_pdr_{s_val}', 0.0)
            p_p = agg_p.get(f'overall_pdr_{s_val}', 0.0)
            print(f"  {f'Overall PDR {s_val}':<28} | {p_s:<15.4f} | {p_h:<15.4f} | {p_p:<15.4f}")

        all_comparison_results.append({
            "scenario": scen,
            "static": agg_s,
            "heuristic": agg_h,
            "constrained_ppo": agg_p,
        })

    # Save output artifact
    out_file = artifacts_dir / "baseline_comparison_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_comparison_results, f, indent=2)

    print("\n" + "=" * 85)
    print(f"[+] Multi-policy evaluation artifact saved to:\n    {out_file}")
    print("=" * 85)


if __name__ == "__main__":
    main()
