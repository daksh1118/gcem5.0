"""
SLA Guardian - Reloadable Reinforcement Learning Policy
Loads trained Stable-Baselines3 PPO checkpoint and performs deterministic inference.
Conforms strictly to PolicyInterface.
"""

from typing import Optional, Union
from pathlib import Path
import json
import numpy as np

from stable_baselines3 import PPO

from ..interfaces.policy import PolicyInterface
from ..schemas.config import RunConfig
from ..schemas.state import NetworkState
from ..schemas.actions import ProposedAction
from ..rl.observation import ObservationAdapter
from ..rl.action_mapping import ActionMappingAdapter


class RLPolicy(PolicyInterface):
    """
    Trained PPO agent inference policy.
    Converts NetworkState -> 12D observation -> PPO deterministic prediction -> ProposedAction.
    """

    def __init__(
        self,
        checkpoint_path: Optional[Union[str, Path]] = None,
        config: Optional[RunConfig] = None,
        deterministic: bool = True,
    ):
        self._policy_id = "constrained_ppo"
        self._policy_version = "1.0.0"
        self.deterministic = deterministic
        root = Path(__file__).resolve().parent.parent.parent.parent

        if config is None:
            scen_path = root / "scenarios" / "default.json"
            if scen_path.exists():
                with open(scen_path, "r", encoding="utf-8") as f:
                    self.config = RunConfig(**json.load(f))
            else:
                self.config = None
        else:
            self.config = config

        # Locate checkpoint
        if checkpoint_path is None:
            default_path = root / "models" / "agent.zip"
            if not default_path.exists():
                # Fallback to backend/artifacts/rl/
                default_path = root / "backend" / "artifacts" / "rl" / "ppo_sla_guardian.zip"
            self.checkpoint_path = default_path
        else:
            self.checkpoint_path = Path(checkpoint_path)

        if not self.checkpoint_path.exists():
            raise FileNotFoundError(
                f"PPO checkpoint not found at: {self.checkpoint_path}. "
                "Ensure training has completed and saved models/agent.zip."
            )

        # Load PPO model on CPU
        try:
            self.model = PPO.load(str(self.checkpoint_path), device="cpu")
        except Exception as e:
            raise RuntimeError(f"Failed to load PPO checkpoint from {self.checkpoint_path}: {e}")

        # Adapters
        self.obs_adapter = ObservationAdapter(queue_scale=1000.0)
        self.action_adapter = ActionMappingAdapter(policy_id=self._policy_id)

    @property
    def policy_id(self) -> str:
        return self._policy_id

    @property
    def policy_version(self) -> str:
        return self._policy_version

    def predict(self, observation: NetworkState) -> ProposedAction:
        """
        Translates NetworkState to 12D observation vector, runs PPO forward pass,
        and decodes the 6D output into a ProposedAction.
        """
        # 1. Build observation
        obs_vec = self.obs_adapter.build_observation(observation, self.config)

        # 2. Predict action logits
        action_logits, _ = self.model.predict(obs_vec, deterministic=self.deterministic)

        # 3. Decode into ProposedAction
        cfg = self.config
        if cfg is None:
            # Construct minimal config from network_state capacities
            cfg = RunConfig(
                scenario_id="runtime_inference",
                total_radio_capacity=observation.total_radio_capacity,
                total_compute_capacity=observation.total_compute_capacity,
                sla_thresholds={},
            )

        proposal = self.action_adapter.decode_action(action_logits, cfg)
        return proposal

    def reset_state(self):
        """Optional policy state reset between runs."""
        pass
