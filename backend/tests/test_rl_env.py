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


# ---------------------------------------------------------------------------
# 4. Corrective-Training Regression Tests
# ---------------------------------------------------------------------------

def test_multi_scenario_gymnasium_cycling():
    """Verifies that SliceGymnasiumEnv properly rotates through all configured scenarios."""
    scenarios = ["normal", "embb_surge", "urllc_burst", "murllc_storm", "mixed_stress"]
    env = SliceGymnasiumEnv(scenario_name=scenarios, max_macro_steps=10)

    visited = []
    for _ in range(len(scenarios) * 2):
        env.reset()
        visited.append(env.scenario_name)

    expected = scenarios * 2
    assert visited == expected, f"Expected scenario cycle {expected}, got {visited}"


def test_episodic_lagrangian_dual_update_with_cost():
    """Verifies that the Lagrangian multiplier updates exactly once per episode using actual cost."""
    env = SliceGymnasiumEnv(scenario_name="normal", max_macro_steps=10, cost_limit=0.01, lagrange_lr=0.05)
    assert env.active_lambda == 0.0

    # Step through a fake episode and verify last_completed_episode_cost is preserved on reset
    env.episode_costs = [0.15, 0.25]
    env.reset()
    assert np.isclose(env.last_completed_episode_cost, 0.20)

    # Calling update_lagrangian_multiplier without args uses last_completed_episode_cost
    new_lambda = env.update_lagrangian_multiplier()
    # Delta: 0.05 * (0.20 - 0.01) = 0.0095
    assert np.isclose(new_lambda, 0.0095)
    assert np.isclose(env.active_lambda, 0.0095)

    # Explicit cost update
    new_lambda2 = env.update_lagrangian_multiplier(cost=0.51)
    # Delta: 0.05 * (0.51 - 0.01) = 0.0250 -> 0.0095 + 0.0250 = 0.0345
    assert np.isclose(new_lambda2, 0.0345)


def test_critical_cost_and_pdr_consistency():
    """Verifies mathematical consistency between critical violation cost and PDR."""
    from backend.app.rl.cost import ViolationCostAdapter
    from backend.app.schemas.metrics import StepMetrics

    adapter = ViolationCostAdapter(cost_limit=0.01)

    # 80 delivered, 20 dropped on URLLC/mURLLC
    metrics = StepMetrics(
        step=1, sim_time_sec=0.1,
        throughput_mbps={s: 10.0 for s in CANONICAL_SLICE_IDS},
        p95_latency_ms={s: 5.0 for s in CANONICAL_SLICE_IDS},
        packet_delivery_ratio={SliceId.URLLC: 0.80, SliceId.MURLLC: 0.80, SliceId.EMBB: 1.0},
        sla_status={s: True for s in CANONICAL_SLICE_IDS},
        sla_breach_count=0,
        radio_utilization_ratio=0.5,
        compute_utilization_ratio=0.5,
        allocation_churn=0.0,
        safety_intervention=False,
        reward_components=None,
        offered_packets={SliceId.EMBB: 100, SliceId.URLLC: 50, SliceId.MURLLC: 50},
        delivered_packets={SliceId.EMBB: 100, SliceId.URLLC: 40, SliceId.MURLLC: 40},
        dropped_packets={SliceId.EMBB: 0, SliceId.URLLC: 10, SliceId.MURLLC: 10},
        pending_packets={s: 0 for s in CANONICAL_SLICE_IDS},
        sla_state_details={s: "PASS" for s in CANONICAL_SLICE_IDS},
    )

    cost = adapter.compute_step_cost(metrics)
    # Delivered critical = 80, dropped critical = 20, offered critical = 100
    # Cost = 20 / 100 = 0.20
    # PDR_critical = 80 / 100 = 0.80 -> Cost + PDR == 1.0
    assert np.isclose(cost, 0.20)
    crit_pdr = (metrics.delivered_packets[SliceId.URLLC] + metrics.delivered_packets[SliceId.MURLLC]) / 100.0
    assert np.isclose(cost + crit_pdr, 1.0)


def test_candidate_checkpoint_and_frozen_hash_integrity():
    """Verifies frozen PPO checkpoint SHA-256 is unchanged and candidate model loads properly."""
    import hashlib
    root = Path(__file__).resolve().parent.parent.parent

    # 1. Verify frozen model hash
    frozen_path = root / "models" / "agent.zip"
    assert frozen_path.exists(), "Frozen models/agent.zip must exist"
    h = hashlib.sha256()
    with open(frozen_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    assert h.hexdigest() == "1d21d58fe672530a1f15ad4232ca7acc5c2a2373edafe8675ee4fe39cc963e78"

    # 2. Verify candidate model exists and loads into RLPolicy
    candidate_path = root / "models" / "candidate_agent.zip"
    assert candidate_path.exists(), "Candidate models/candidate_agent.zip must exist"
    candidate_policy = RLPolicy(checkpoint_path=candidate_path)
    assert candidate_policy.model is not None

    # 3. Verify candidate metadata
    meta_path = root / "models" / "candidate_metadata.json"
    assert meta_path.exists()
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["final_lambda"] > 0.0
    assert len(meta["scenario"]) == 5
    assert meta["total_timesteps"] == 15000
