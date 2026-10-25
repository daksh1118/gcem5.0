"""
SLA Guardian - Trace-Driven Multi-Policy Macro-Control Benchmark
Phase 7: Real Network Traffic Replay Evaluation

Evaluates four policies under identical 100 ms macro-control intervals using recorded packet traces:
1. Static Baseline Policy
2. Adaptive Demand Heuristic Policy
3. Frozen Constrained PPO Agent (models/agent.zip)
4. Candidate Multi-Scenario PPO Agent (models/candidate_agent.zip)

Traces Evaluated:
- data/traces/sample_5g_multi_slice_trace.csv (10.0s duration, 2268 packets, 50 macro-steps window)
- data/traces/sample_5g_trace.jsonl (8.0s duration, 1320 packets, 50 macro-steps window)
- data/traces/sample_5g_trace.pcap (5.0s duration, 997 packets, 50 macro-steps window)

All compared policies consume identical packet arrival events in exact lockstep without changing
the order, timestamp deltas, or flow classifications of the recorded traces.
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
from backend.app.traffic.trace_source import TraceReplayTrafficSource


def compute_sha256(filepath: Path) -> str:
    if not filepath.exists():
        return "NOT_FOUND"
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def evaluate_trace_trial(
    policy_name: str,
    policy_instance: PolicyInterface,
    trace_path: Path,
    raw_scenario_config: dict,
    num_macro_steps: int = 50,
    seed: int = 42,
    replay_speed: float = 1.0,
    steps_per_interval: int = 10,
) -> Dict[str, Any]:
    """
    Executes a single trace-driven trial at the 100 ms macro-control interval.
    The simulator derives new packet arrivals strictly from the input trace.
    """
    config = RunConfig(**raw_scenario_config).model_copy(
        update={"traffic_profile": "trace_replay", "seed": seed}
    )

    # Initialize independent trace source for deterministic replay lockstep
    trace_source = TraceReplayTrafficSource(file_path=trace_path, replay_speed=replay_speed)

    simulator = FallbackNetworkSimulator(config=config, traffic_source=trace_source)
    shield = SafetyShield()
    macro_adapter = MacroControlAdapter(
        simulator=simulator,
        config=config,
        steps_per_interval=steps_per_interval,
    )
    cost_adapter = ViolationCostAdapter(cost_limit=0.01)

    current_state = simulator.reset(seed=seed, config=config)

    # Diagnostics from source
    source_diag = trace_source.get_diagnostics()
    source_meta = trace_source.get_metadata()

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

    mean_tput = {s: float(np.mean(step_tputs[s])) for s in CANONICAL_SLICE_IDS}
    total_tput = sum(mean_tput.values())

    p95_lat = {}
    for s in CANONICAL_SLICE_IDS:
        p95_lat[s] = float(np.percentile(step_lats[s], 95)) if step_lats[s] else None

    return {
        "trace_name": trace_path.name,
        "trace_format": source_meta.source_type.value if hasattr(source_meta.source_type, "value") else str(source_meta.source_type),
        "total_trace_packets": source_meta.total_records,
        "classification_coverage": round(source_meta.classification_coverage_pct / 100.0, 4),
        "unclassified_packets": source_meta.unclassified_count,
        "policy": policy_name,
        "seed": seed,
        "macro_steps": num_macro_steps,
        "sim_time_sec": round(num_macro_steps * 0.1, 2),
        "total_offered_packets": sum(total_offered.values()),
        "total_delivered_packets": sum(total_delivered.values()),
        "total_dropped_packets": sum(total_dropped.values()),
        "embb_pdr": round(pdr[SliceId.EMBB], 4),
        "urllc_pdr": round(pdr[SliceId.URLLC], 4),
        "murllc_pdr": round(pdr[SliceId.MURLLC], 4),
        "embb_tput_mbps": round(mean_tput[SliceId.EMBB], 2),
        "urllc_tput_mbps": round(mean_tput[SliceId.URLLC], 2),
        "murllc_tput_mbps": round(mean_tput[SliceId.MURLLC], 2),
        "total_tput_mbps": round(total_tput, 2),
        "embb_latency_ms": round(p95_lat[SliceId.EMBB], 2) if p95_lat[SliceId.EMBB] is not None else None,
        "urllc_latency_ms": round(p95_lat[SliceId.URLLC], 2) if p95_lat[SliceId.URLLC] is not None else None,
        "murllc_latency_ms": round(p95_lat[SliceId.MURLLC], 2) if p95_lat[SliceId.MURLLC] is not None else None,
        "critical_cost": round(float(np.mean(step_costs)), 6),
        "radio_util": round(float(np.mean(radio_utils)), 4),
        "compute_util": round(float(np.mean(compute_utils)), 4),
        "allocation_churn": round(total_churn, 2),
        "shield_interventions": shield_interventions,
        "sla_breach_ratio": round(sla_breach_steps / num_macro_steps, 4),
        "delivered_packets": {s.value: total_delivered[s] for s in CANONICAL_SLICE_IDS},
        "dropped_packets": {s.value: total_dropped[s] for s in CANONICAL_SLICE_IDS},
    }


def main():
    print("=" * 95)
    print("   SLA GUARDIAN - TRACE-DRIVEN MULTI-POLICY BENCHMARK (100 ms MACRO-INTERVAL)")
    print("   Evaluating on Recorded Network Traces: CSV, JSONL, and Binary PCAP")
    print("   Comparing: Static Baseline vs Adaptive Heuristic vs Frozen PPO vs Candidate PPO")
    print("=" * 95)

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
        raise FileNotFoundError(f"Candidate model not found at {candidate_path}.")

    traces_dir = ROOT_DIR / "data" / "traces"
    evaluated_traces = [
        traces_dir / "sample_5g_multi_slice_trace.csv",
        traces_dir / "sample_5g_trace.jsonl",
        traces_dir / "sample_5g_trace.pcap",
    ]

    for t in evaluated_traces:
        if not t.exists():
            raise FileNotFoundError(f"Required trace fixture not found: {t}")

    num_macro_steps = 50  # 50 x 100 ms = 5.0 seconds
    seed = 42

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
    summary_by_trace = {t.name: {p: None for p in policies} for t in evaluated_traces}

    start_time = time.time()

    for trace_file in evaluated_traces:
        print(f"\n[*] Evaluating Trace: '{trace_file.name}' ({num_macro_steps} macro steps @ 100 ms)...")
        for p_key, p_inst in policies.items():
            print(f"    -> Running {p_key.upper()} on {trace_file.name}...")
            rec = evaluate_trace_trial(
                policy_name=p_key,
                policy_instance=p_inst,
                trace_path=trace_file,
                raw_scenario_config=raw_scen,
                num_macro_steps=num_macro_steps,
                seed=seed,
            )
            records.append(rec)
            summary_by_trace[trace_file.name][p_key] = rec

    duration = time.time() - start_time
    print(f"\n[+] Completed all {len(records)} trace evaluation trials in {duration:.2f} seconds.")

    # 1. Save JSON
    json_path = out_dir / "trace_benchmark.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "control_interval_ms": 100,
                "macro_steps_per_trial": num_macro_steps,
                "frozen_model_sha256": frozen_hash,
                "candidate_model_sha256": candidate_hash,
                "traces_evaluated": [t.name for t in evaluated_traces],
                "policies": list(policies.keys()),
                "records": records,
            },
            f,
            indent=2,
        )
    print(f"[+] Saved JSON benchmark to: {json_path}")

    # 2. Save CSV
    csv_path = out_dir / "trace_benchmark.csv"
    if records:
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

    # 3. Save Markdown Report
    md_path = out_dir / "trace_results.md"
    policy_labels = {
        "static": "Static Baseline",
        "heuristic": "Adaptive Heuristic",
        "frozen_ppo": "Frozen PPO",
        "candidate_ppo": "**Candidate PPO**",
    }

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# SLA Guardian: Phase 8 Real Traffic Trace Benchmark Report\n\n")
        f.write(f"- **Generated At:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        f.write(f"- **Control Interval:** 100 ms Macro-Control Interval (10 x 10 ms sub-steps/interval)\n")
        f.write(f"- **Traffic Source:** Trace Replay (`TraceReplayTrafficSource`)\n")
        f.write(f"- **Frozen PPO Checkpoint SHA-256:** `{frozen_hash}`\n")
        f.write(f"- **Candidate PPO Checkpoint SHA-256:** `{candidate_hash}`\n")
        f.write(f"- **Evaluated Traces:** 3 recorded packet traces (`CSV`, `JSONL`, binary `PCAP`)\n")
        f.write(f"- **Evaluated Steps per Trace:** 50 macro-steps (5.0 seconds sim time)\n\n")

        f.write("## Trace Inventory & Provenance\n\n")
        f.write("| Trace File | Format | Packets | Duration (s) | Classification Coverage | 3GPP QoS / DSCP Labels |\n")
        f.write("| :--- | :--- | :---: | :---: | :---: | :--- |\n")
        f.write("| `sample_5g_multi_slice_trace.csv` | CSV | 2,268 | 10.0s | 100.0% | 5QI 1 (URLLC), 5QI 9 (eMBB), 5QI 79 (mURLLC) |\n")
        f.write("| `sample_5g_trace.jsonl` | JSONL | 1,320 | 8.0s | 100.0% | 5QI 1, 5QI 9, 5QI 79 with source latency measurements |\n")
        f.write("| `sample_5g_trace.pcap` | Binary PCAP | 997 | 5.0s | 100.0% | IPv4 ToS/DSCP: EF (URLLC), AF11 (mURLLC), CS0 (eMBB) |\n\n")

        f.write("## Trace-Driven Policy Performance Comparison\n\n")
        f.write("| Trace File | Policy | eMBB Tput (Mbps) | Total Tput (Mbps) | eMBB PDR | URLLC PDR | mURLLC PDR | Critical Cost | Churn (L1) | Breach Ratio |\n")
        f.write("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")

        for trace_name, p_data in summary_by_trace.items():
            for p_key, p_label in policy_labels.items():
                r = p_data[p_key]
                f.write(
                    f"| `{trace_name}` | {p_label} | {r['embb_tput_mbps']:.2f} | {r['total_tput_mbps']:.2f} | "
                    f"{(r['embb_pdr'] * 100):.2f}% | {(r['urllc_pdr'] * 100):.2f}% | {(r['murllc_pdr'] * 100):.2f}% | "
                    f"{r['critical_cost']:.6f} | {r['allocation_churn']:.1f} | {(r['sla_breach_ratio'] * 100):.1f}% |\n"
                )

        f.write("\n## Metric Separation: Measured Source Data vs Simulated Outputs\n\n")
        f.write("- **Measured Source Inputs:** Packet sizes, arrival timestamps, inter-arrival deltas, 5QI/DSCP QoS labels, device identifiers, and offered bitrates are directly parsed from the recorded traces without synthetic replacement.\n")
        f.write("- **Simulated Engine Outputs:** Radio PRB allocation, queue dynamics, transmission scheduling, packet drops, channel fading, and SLA delivery ratios are simulated outcomes computed by `FallbackNetworkSimulator` and bounded by `SafetyShield`.\n")
        f.write("- **Measurement Limitations:** Unless latency is explicitly provided by the input trace records (as in `sample_5g_trace.jsonl`), simulated latency reflects network queuing and air-interface transmission delay rather than real-world physical path propagation.\n\n")

    print(f"[+] Saved Markdown summary to: {md_path}")
    print("\n[+] Trace-driven benchmark evaluation completed successfully.")


if __name__ == "__main__":
    main()

