"""
SLA Guardian - Corrective Candidate Training Script
Trains a candidate PPO checkpoint across all five scenarios using multi-scenario rotation.
Enforces episodic Lagrangian dual updates on critical-slice violation cost.
Ensures frozen model 'models/agent.zip' is preserved without modification.
"""

import sys
import hashlib
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.app.rl.train import train_ppo


def get_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main():
    frozen_model_path = ROOT_DIR / "models" / "agent.zip"
    if not frozen_model_path.exists():
        raise FileNotFoundError(f"Frozen baseline model not found at: {frozen_model_path}")

    frozen_hash_before = get_sha256(frozen_model_path)
    print(f"[*] Verified Frozen PPO Model SHA-256 Before Training: {frozen_hash_before}")

    scenarios = ["normal", "embb_surge", "urllc_burst", "murllc_storm", "mixed_stress"]
    total_timesteps = 15000
    seed = 42

    print("\n" + "=" * 75)
    print("   STARTING MULTI-SCENARIO CORRECTIVE PPO TRAINING RUN")
    print(f"   Timesteps : {total_timesteps} (~150 episodes, 30 per scenario)")
    print(f"   Scenarios : {scenarios}")
    print(f"   Output    : models/candidate_agent.zip")
    print(f"   Metadata  : models/candidate_metadata.json")
    print(f"   Logs      : runs/candidate_log.csv")
    print("=" * 75 + "\n")

    model, metadata = train_ppo(
        total_timesteps=total_timesteps,
        seed=seed,
        scenario_name=scenarios,
        max_macro_steps_per_episode=100,
        cost_limit=0.01,
        lagrange_lr=0.05,
        output_dir=ROOT_DIR / "models",
        checkpoint_filename="candidate_agent.zip",
        metadata_filename="candidate_metadata.json",
        log_csv_filename="candidate_log.csv",
        artifact_filename="candidate_agent.zip",
    )

    frozen_hash_after = get_sha256(frozen_model_path)
    assert frozen_hash_before == frozen_hash_after, "FATAL: Frozen model was modified!"
    print(f"\n[+] Verified Frozen Model Preserved: {frozen_hash_after}")

    candidate_path = ROOT_DIR / "models" / "candidate_agent.zip"
    candidate_hash = get_sha256(candidate_path)
    print(f"[+] Candidate Model Created: {candidate_path}")
    print(f"[+] Candidate Model SHA-256: {candidate_hash}")
    print(f"[+] Final Lambda Multiplier: {metadata['final_lambda']}")
    print(f"[+] Training Duration      : {metadata['training_duration_sec']}s")


if __name__ == "__main__":
    main()
