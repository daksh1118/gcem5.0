"""
SLA Guardian - Phase 5 Gymnasium Environment & RL Policy Integration Tests
Tests environment lifecycle, observation/action bounds, reward calculations,
Lagrangian updates, Safety Shield integration, and checkpoint round-trip.
"""

import json
from pathlib import Path
import numpy as np
import pytest
from stable_baselines3.common.env_checker import check_env
from stable_baselines3 import PPO

from backend.app.schemas.config import RunConfig, SliceId, CANONICAL_SLICE_IDS
from backend.app.schemas.actions import ExecutedAction, ProposedAction
from backend.app.simulator.fallback import FallbackNetworkSimulator
from backend.app.control.safety_shield import SafetyShield
from backend.app.control.pipeline import PolicyExecutionPipeline
from backend.app.rl.environment import SliceGymnasiumEnv
from backend.app.rl.reward import LagrangianRewardEngine
from backend.app.rl.lagrangian import LagrangianMultiplier
from backend.app.policies.rl_policy import RLPolicy


@pytest.fixture
def test_config() -> RunConfig:
    scen_path = Path(__file__).resolve().parent.parent.parent / "scenarios" / "default.json"
    with open(scen_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return RunConfig(**data)


# ---------------------------------------------------------------------------
# 1. Gymnasium Environment Contract & CheckEnv
# ---------------------------------------------------------------------------

def test_gymnasium_env_checker():
    """Confirms SliceGymnasiumEnv satisfies official SB3 environment contracts."""
    env = SliceGymnasiumEnv(scenario_name="normal", max_macro_steps=50)
    check_env(env)


def test_environment_reset_contract():
    env = SliceGymnasiumEnv(seed=42)
    obs, info = env.reset(seed=42)

    assert isinstance(obs, np.ndarray)
    assert obs.shape == (12,)
    assert obs.dtype == np.float32
    assert np.all(np.isfinite(obs))
    assert env.observation_space.contains(obs)
    assert "macro_step" in info
    assert info["macro_step"] == 0


def test_environment_five_element_step():
    env = SliceGymnasiumEnv(seed=42, max_macro_steps=5)
    env.reset(seed=42)

    action = np.zeros(6, dtype=np.float32)
    obs, reward, terminated, truncated, info = env.step(action)

    assert isinstance(obs, np.ndarray)
    assert obs.shape == (12,)
    assert np.all(np.isfinite(obs))
    assert isinstance(reward, float)
    assert np.isfinite(reward)
    assert isinstance(terminated, bool)
    assert isinstance(truncated, bool)
    assert isinstance(info, dict)
    assert "critical_cost" in info
    assert "service_reward" in info


def test_environment_truncation():
    max_steps = 3
    env = SliceGymnasiumEnv(seed=42, max_macro_steps=max_steps)
    env.reset(seed=42)

    action = np.zeros(6, dtype=np.float32)
    for _ in range(max_steps - 1):
        _, _, _, truncated, _ = env.step(action)
        assert not truncated

    # Last step should truncate
    _, _, _, truncated, _ = env.step(action)
    assert truncated


# ---------------------------------------------------------------------------
# 2. Reward & Lagrangian Logic
# ---------------------------------------------------------------------------

def test_lagrangian_reward_engine():
    engine = LagrangianRewardEngine(cost_limit=0.01)

    # 1. Test rejection penalty
    penalty, info = engine.compute_reward(
        step_metrics=None,
        diagnostics=None,
        lambda_val=1.5,
        is_rejected=True,
    )
    assert penalty == -1.0
    assert info["is_rejected"] is True


def test_lagrangian_multiplier_state():
    lag = LagrangianMultiplier(init_lambda=1.0, lr=0.1, cost_limit=0.01)
    assert lag.value == 1.0

    # Increase when cost > limit (0.05 - 0.01 = 0.04 -> +0.004)
    new_val = lag.update(0.05)
    assert np.isclose(new_val, 1.004)

    # Reset
    lag.reset()
    assert lag.value == 1.0


# ---------------------------------------------------------------------------
# 3. PPO Training Smoke Test & Checkpoint Round-Trip
# ---------------------------------------------------------------------------

def test_ppo_short_train_and_checkpoint_roundtrip(tmp_path):
    env = SliceGymnasiumEnv(scenario_name="normal", max_macro_steps=10)

    # Run tiny 64-step PPO training
    model = PPO(
        policy="MlpPolicy",
        env=env,
        n_steps=64,
        batch_size=32,
        n_epochs=1,
        device="cpu",
        seed=42,
    )
    model.learn(total_timesteps=64)

    checkpoint_path = tmp_path / "test_agent.zip"
    model.save(str(checkpoint_path))
    assert checkpoint_path.exists()

    # Reload model
    loaded_model = PPO.load(str(checkpoint_path), device="cpu")

    # Verify deterministic prediction consistency
    dummy_obs = np.ones(12, dtype=np.float32) * 0.5
    pred1, _ = model.predict(dummy_obs, deterministic=True)
    pred2, _ = loaded_model.predict(dummy_obs, deterministic=True)
    np.testing.assert_array_almost_equal(pred1, pred2)


def test_rl_policy_pipeline_integration(test_config):
    """Verifies RLPolicy interacts cleanly through PolicyExecutionPipeline."""
    model_path = Path(__file__).resolve().parent.parent.parent / "models" / "agent.zip"
    if not model_path.exists():
        pytest.skip("Canonical models/agent.zip not yet generated.")

    policy = RLPolicy(checkpoint_path=model_path, config=test_config)
    sim = FallbackNetworkSimulator(config=test_config)
    shield = SafetyShield()
    pipeline = PolicyExecutionPipeline(
        simulator=sim,
        safety_shield=shield,
        config=test_config,
    )

    curr_state = sim.reset(seed=42)
    next_state, record = pipeline.execute_step(curr_state, policy)

    assert record.accepted is True
    assert record.executed_action is not None
    assert next_state.step == 1
    assert next_state.sim_time_sec == 0.010
