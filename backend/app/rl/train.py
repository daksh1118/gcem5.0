"""
SLA Guardian - Constrained PPO Training Pipeline
Trains an agent using Stable-Baselines3 PPO on the SliceGymnasiumEnv.
Features:
- Lagrangian dual update per episode for critical-slice constraint satisfaction.
- Single-environment CPU execution optimized for laptop performance.
- Saves model to models/agent.zip and metadata to models/agent_metadata.json.
- Logs training progress to runs/log.csv.
"""

import os
import csv
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import numpy as np

import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback

from ..schemas.config import RunConfig
from .environment import SliceGymnasiumEnv


class LagrangianCallback(BaseCallback):
    """
    Episodic callback for Lagrangian multiplier updates and structured logging.
    Updates the dual multiplier lambda once per completed episode.
    """

    def __init__(self, log_csv_path: Optional[Path] = None, verbose: int = 1):
        super().__init__(verbose=verbose)
        self.log_csv_path = log_csv_path
        self.episode_count = 0
        self.episode_rewards: List[float] = []
        self.episode_costs: List[float] = []
        self.episode_embb_tputs: List[float] = []
        self.csv_file = None
        self.csv_writer = None

        if self.log_csv_path:
            self.log_csv_path.parent.mkdir(parents=True, exist_ok=True)
            self.csv_file = open(self.log_csv_path, "w", newline="", encoding="utf-8")
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow([
                "episode", "step", "episode_reward", "mean_critical_cost",
                "lambda_val", "mean_embb_tput_mbps"
            ])
            self.csv_file.flush()

    def _on_step(self) -> bool:
        infos = self.locals.get("infos", [])
        rewards = self.locals.get("rewards", [0.0])
        dones = self.locals.get("dones", [False])

        if infos:
            info = infos[0]
            self.episode_rewards.append(float(rewards[0]))
            self.episode_costs.append(float(info.get("critical_cost", 0.0)))
            self.episode_embb_tputs.append(float(info.get("throughput_embb_mbps", 0.0)))

        # When episode finishes (done or truncated)
        if dones and dones[0]:
            self.episode_count += 1
            env = self.training_env.envs[0]
            old_lambda = env.active_lambda
            new_lambda = env.update_lagrangian_multiplier()

            ep_rew = float(np.sum(self.episode_rewards))
            mean_cost = float(np.mean(self.episode_costs)) if self.episode_costs else 0.0
            mean_tput = float(np.mean(self.episode_embb_tputs)) if self.episode_embb_tputs else 0.0

            if self.verbose > 0 and self.episode_count % 5 == 0:
                print(
                    f"[*] Ep {self.episode_count:3d} | Steps: {self.num_timesteps:5d} | "
                    f"Reward: {ep_rew:6.2f} | Mean Crit Cost: {mean_cost:.4f} | "
                    f"Lambda: {old_lambda:.4f} -> {new_lambda:.4f} | eMBB: {mean_tput:.1f} Mbps"
                )

            if self.csv_writer:
                self.csv_writer.writerow([
                    self.episode_count,
                    self.num_timesteps,
                    round(ep_rew, 3),
                    round(mean_cost, 4),
                    round(new_lambda, 4),
                    round(mean_tput, 2),
                ])
                self.csv_file.flush()

            self.episode_rewards.clear()
            self.episode_costs.clear()
            self.episode_embb_tputs.clear()

        return True

    def _on_training_end(self):
        if self.csv_file:
            self.csv_file.close()


def train_ppo(
    total_timesteps: int = 10000,
    seed: int = 42,
    scenario_name: str = "normal",
    max_macro_steps_per_episode: int = 100,
    cost_limit: float = 0.01,
    lagrange_lr: float = 0.05,
    output_dir: Optional[Path] = None,
) -> Tuple[PPO, Dict[str, Any]]:
    """
    Executes a CPU-based Constrained PPO training run.

    Args:
        total_timesteps: Number of macro-control steps to train.
        seed: Random seed for reproducibility.
        scenario_name: Name of traffic profile to train on.
        max_macro_steps_per_episode: Episode length in macro-steps (100 ms each).
        cost_limit: Maximum allowed critical packet violation rate.
        lagrange_lr: Learning rate for dual multiplier.
        output_dir: Directory where models/agent.zip will be saved.

    Returns:
        Tuple of (trained PPO model, training metadata dict).
    """
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    if output_dir is None:
        output_dir = root_dir / "models"
    output_dir.mkdir(parents=True, exist_ok=True)

    log_csv_path = root_dir / "runs" / "log.csv"

    # Set seeds
    torch.manual_seed(seed)
    np.random.seed(seed)

    print("=" * 70)
    print("   SLA GUARDIAN - CONSTRAINED PPO TRAINING")
    print(f"   Target Timesteps: {total_timesteps} | Scenario: {scenario_name} | Seed: {seed}")
    print(f"   Hardware Device : CPU | Cost Limit: {cost_limit} | Dual LR: {lagrange_lr}")
    print("=" * 70)

    # 1. Instantiate environment
    env = SliceGymnasiumEnv(
        scenario_name=scenario_name,
        seed=seed,
        steps_per_interval=10,  # 100 ms macro-interval
        max_macro_steps=max_macro_steps_per_episode,
        cost_limit=cost_limit,
        lagrange_lr=lagrange_lr,
    )

    # 2. Configure PPO
    policy_kwargs = dict(
        net_arch=dict(pi=[64, 64], vf=[64, 64]),
        activation_fn=torch.nn.Tanh,
    )

    model = PPO(
        policy="MlpPolicy",
        env=env,
        learning_rate=3e-4,
        n_steps=256,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        policy_kwargs=policy_kwargs,
        device="cpu",
        seed=seed,
        verbose=0,
    )

    # 3. Setup callback
    callback = LagrangianCallback(log_csv_path=log_csv_path, verbose=1)

    start_time = time.time()
    model.learn(total_timesteps=total_timesteps, callback=callback)
    duration = time.time() - start_time

    # 4. Save checkpoint to models/agent.zip
    model_path = output_dir / "agent.zip"
    model.save(str(model_path))

    # Also save artifact copy in backend/artifacts/rl/
    artifacts_dir = root_dir / "backend" / "artifacts" / "rl"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_model_path = artifacts_dir / "ppo_sla_guardian.zip"
    model.save(str(artifact_model_path))

    # 5. Metadata
    metadata = {
        "model_name": "constrained_ppo_sla_guardian",
        "saved_path": str(model_path),
        "artifact_path": str(artifact_model_path),
        "total_timesteps": total_timesteps,
        "completed_episodes": callback.episode_count,
        "training_duration_sec": round(duration, 2),
        "seed": seed,
        "scenario": scenario_name,
        "cost_limit": cost_limit,
        "lagrange_lr": lagrange_lr,
        "final_lambda": round(env.lagrangian.value, 4),
        "observation_dim": 12,
        "action_dim": 6,
        "device": "cpu",
        "library_versions": {
            "torch": str(torch.__version__),
            "stable_baselines3": "2.9.0",
            "gymnasium": "0.29.1",
        },
    }

    meta_path = output_dir / "agent_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print("\n" + "=" * 70)
    print(f"[+] Training completed in {duration:.1f} seconds ({callback.episode_count} episodes)")
    print(f"[+] Canonical checkpoint saved to: {model_path}")
    print(f"[+] Metadata saved to           : {meta_path}")
    print(f"[+] Training log CSV saved to   : {log_csv_path}")
    print(f"[+] Final Lagrangian Lambda    : {env.lagrangian.value:.4f}")
    print("=" * 70)

    return model, metadata


if __name__ == "__main__":
    train_ppo(total_timesteps=10000, seed=42)
