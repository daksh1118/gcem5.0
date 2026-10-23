"""
SLA Guardian - Gymnasium Environment Adapter
Wraps FallbackNetworkSimulator into a standard Gymnasium environment adhering to the
merged 100 ms macro-control interval and 6D continuous action space.
"""

from typing import Optional, Dict, Any, Tuple
import json
from pathlib import Path
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from ..schemas.config import RunConfig, CANONICAL_SLICE_IDS, SliceId
from ..schemas.state import NetworkState
from ..schemas.actions import ExecutedAction
from ..simulator.fallback import FallbackNetworkSimulator
from ..control.safety_shield import SafetyShield
from .observation import ObservationAdapter, OBSERVATION_DIM
from .action_mapping import ActionMappingAdapter, ACTION_DIM
from .control_interval import MacroControlAdapter
from .reward import LagrangianRewardEngine
from .lagrangian import LagrangianMultiplier


class SliceGymnasiumEnv(gym.Env):
    """
    Gymnasium-compliant environment for 5G Slicing Resource Allocation.
    Action: Box(-1.0, 1.0, shape=(6,)) -> [3 radio logits, 3 compute logits]
    Observation: Box(0.0, 2.0, shape=(12,)) -> [4 features x 3 canonical slices]
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        config: Optional[RunConfig] = None,
        scenario_name: str = "normal",
        seed: int = 42,
        steps_per_interval: int = 10,
        max_macro_steps: int = 200,
        cost_limit: float = 0.01,
        lagrange_lr: float = 0.05,
    ):
        super().__init__()
        self.scenario_name = scenario_name
        self.seed_val = seed
        self.steps_per_interval = max(1, steps_per_interval)
        self.max_macro_steps = max(1, max_macro_steps)
        self.cost_limit = cost_limit

        # Load or use config
        if config is None:
            scen_path = Path(__file__).resolve().parent.parent.parent.parent / "scenarios" / "default.json"
            if scen_path.exists():
                with open(scen_path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                self.config = RunConfig(**raw_data).model_copy(
                    update={"traffic_profile": self.scenario_name, "seed": self.seed_val}
                )
            else:
                raise FileNotFoundError("Default scenario file not found and no config provided.")
        else:
            self.config = config.model_copy(
                update={"traffic_profile": self.scenario_name, "seed": self.seed_val}
            )

        # Action Space: 6 continuous values in [-1.0, 1.0]
        self.action_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(ACTION_DIM,),
            dtype=np.float32,
        )

        # Observation Space: 12 continuous values in [0.0, 2.0]
        self.observation_space = spaces.Box(
            low=0.0,
            high=2.0,
            shape=(OBSERVATION_DIM,),
            dtype=np.float32,
        )

        # Adapters and sub-modules
        self.simulator = FallbackNetworkSimulator(config=self.config)
        self.obs_adapter = ObservationAdapter(queue_scale=1000.0)
        self.action_adapter = ActionMappingAdapter(policy_id="constrained_ppo")
        self.shield = SafetyShield()
        self.macro_adapter = MacroControlAdapter(
            simulator=self.simulator,
            config=self.config,
            steps_per_interval=self.steps_per_interval,
        )
        self.reward_engine = LagrangianRewardEngine(cost_limit=self.cost_limit)
        self.lagrangian = LagrangianMultiplier(
            init_lambda=0.0,
            lr=lagrange_lr,
            cost_limit=self.cost_limit,
            max_lambda=50.0,
        )

        # Tracking variables
        self.current_state: Optional[NetworkState] = None
        self.current_macro_step: int = 0
        self.episode_costs: list[float] = []
        self.last_obs: Optional[np.ndarray] = None
        self.active_lambda: float = 0.0

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Resets the environment for a new episode.
        Preserves the persistent Lagrangian multiplier across episodes.
        """
        super().reset(seed=seed)
        if seed is not None:
            self.seed_val = seed

        self.current_state = self.simulator.reset(seed=self.seed_val)
        self.current_macro_step = 0
        self.episode_costs.clear()
        self.active_lambda = self.lagrangian.value

        obs = self.obs_adapter.build_observation(self.current_state, self.config)
        self.last_obs = obs

        info = {
            "macro_step": 0,
            "sim_time_sec": self.current_state.sim_time_sec,
            "lambda_val": self.active_lambda,
            "scenario": self.scenario_name,
        }
        return obs, info

    def step(
        self,
        action: np.ndarray,
    ) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """
        Executes one 100 ms macro-control interval using the given action vector.
        """
        self.current_macro_step += 1

        # 1. Action decode
        try:
            proposal = self.action_adapter.decode_action(action, self.config)
        except Exception as e:
            # Malformed action: terminate with penalty
            penalty = -10.0
            return self.last_obs, penalty, True, False, {"error": str(e), "is_rejected": True}

        # 2. Safety Shield validation
        safety_result = self.shield.validate(proposal, self.current_state, self.config)

        if not safety_result.is_accepted or safety_result.executed_action is None:
            # Rejection halts simulation advance
            reward, r_info = self.reward_engine.compute_reward(
                step_metrics=None,
                diagnostics=None,
                lambda_val=self.active_lambda,
                is_rejected=True,
            )
            r_info.update({
                "macro_step": self.current_macro_step,
                "rejection_reasons": safety_result.reasons,
                "safety_status": safety_result.validation_status.value,
            })
            return self.last_obs, reward, True, False, r_info

        # 3. Execute 10 internal steps with validated ExecutedAction
        executed_action = safety_result.executed_action
        next_state, step_metrics, diagnostics = self.macro_adapter.execute_macro_step(
            current_state=self.current_state,
            executed_action=executed_action,
        )
        self.current_state = next_state

        # 4. Compute reward and track violation cost
        reward, r_info = self.reward_engine.compute_reward(
            step_metrics=step_metrics,
            diagnostics=diagnostics,
            lambda_val=self.active_lambda,
            is_rejected=False,
        )
        self.episode_costs.append(r_info["critical_cost"])

        # 5. Build next observation
        obs = self.obs_adapter.build_observation(self.current_state, self.config)
        self.last_obs = obs

        # 6. Truncation and termination
        truncated = (self.current_macro_step >= self.max_macro_steps)
        terminated = False

        # 7. Rich diagnostic info
        info = {
            **r_info,
            "macro_step": self.current_macro_step,
            "sim_time_sec": next_state.sim_time_sec,
            "shield_intervention": executed_action.is_modified_by_safety,
            "shield_reasons": safety_result.reasons,
            "throughput_embb_mbps": step_metrics.throughput_mbps.get(SliceId.EMBB, 0.0),
            "throughput_urllc_mbps": step_metrics.throughput_mbps.get(SliceId.URLLC, 0.0),
            "throughput_murllc_mbps": step_metrics.throughput_mbps.get(SliceId.MURLLC, 0.0),
            "p95_latency_urllc_ms": step_metrics.p95_latency_ms.get(SliceId.URLLC),
            "radio_utilization": step_metrics.radio_utilization_ratio,
            "compute_utilization": step_metrics.compute_utilization_ratio,
            "sla_breach_count": step_metrics.sla_breach_count,
        }

        return obs, reward, terminated, truncated, info

    def get_mean_episode_cost(self) -> float:
        """Returns the mean critical-slice violation cost across the current episode."""
        if not self.episode_costs:
            return 0.0
        return float(np.mean(self.episode_costs))

    def update_lagrangian_multiplier(self) -> float:
        """Updates the multiplier at the end of a completed episode."""
        mean_cost = self.get_mean_episode_cost()
        new_lambda = self.lagrangian.update(mean_cost)
        self.active_lambda = new_lambda
        return new_lambda
