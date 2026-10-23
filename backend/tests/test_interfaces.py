"""
Unit tests for SLA Guardian component interfaces and dependency imports.
Verifies SimulatorInterface, PolicyInterface, EvaluatorInterface test doubles,
and confirms Gymnasium package readiness.
"""

from typing import Any, Dict, Optional, Tuple
import pytest

from backend.app.schemas.config import SliceId, RunConfig
from backend.app.schemas.state import SliceState, NetworkState
from backend.app.schemas.actions import ProposedAction, ExecutedAction
from backend.app.schemas.metrics import StepMetrics
from backend.app.interfaces.simulator import SimulatorInterface, SimulatorDiagnostics
from backend.app.interfaces.policy import PolicyInterface, EvaluatorInterface


def test_gymnasium_import_and_version():
    """Requirement 10: The Gymnasium dependency imports correctly in the project environment."""
    import gymnasium as gym
    assert gym is not None
    assert hasattr(gym, "Env")
    assert hasattr(gym, "spaces")
    assert gym.__version__ is not None


class DummySimulator(SimulatorInterface):
    """Minimal test double implementing SimulatorInterface."""

    def __init__(self):
        self._step_count = 0

    def reset(
        self,
        seed: Optional[int] = None,
        scenario: Optional[Dict[str, Any]] = None,
        config: Optional[RunConfig] = None,
    ) -> NetworkState:
        self._step_count = 0
        return self._make_state(0, 0.0)

    def step(
        self,
        executed_action: ExecutedAction,
    ) -> Tuple[NetworkState, SimulatorDiagnostics]:
        assert isinstance(executed_action, ExecutedAction), "Simulator must consume ExecutedAction"
        self._step_count += 1
        next_state = self._make_state(self._step_count, self._step_count * 0.01)
        diag = SimulatorDiagnostics(
            step=self._step_count,
            terminated=(self._step_count >= 10),
            truncated=False,
            active_flows=15,
            dropped_packets=0,
        )
        return next_state, diag

    def _make_state(self, step: int, sim_time: float) -> NetworkState:
        s_embb = SliceState(slice_id=SliceId.EMBB, offered_demand_mbps=40.0, current_radio_allocation=30.0, current_compute_allocation=30.0)
        s_urllc = SliceState(slice_id=SliceId.URLLC, offered_demand_mbps=8.0, current_radio_allocation=35.0, current_compute_allocation=35.0)
        s_murllc = SliceState(slice_id=SliceId.MURLLC, offered_demand_mbps=15.0, current_radio_allocation=30.0, current_compute_allocation=30.0)
        return NetworkState(
            step=step,
            sim_time_sec=sim_time,
            total_radio_capacity=100.0,
            total_compute_capacity=100.0,
            slice_states={
                SliceId.EMBB: s_embb,
                SliceId.URLLC: s_urllc,
                SliceId.MURLLC: s_murllc,
            }
        )


class DummyPolicy(PolicyInterface):
    """Minimal test double implementing PolicyInterface."""

    @property
    def policy_id(self) -> str:
        return "dummy_equal_share"

    @property
    def policy_version(self) -> str:
        return "0.1.0"

    def predict(self, observation: NetworkState) -> ProposedAction:
        assert isinstance(observation, NetworkState)
        return ProposedAction(
            radio_allocations={SliceId.EMBB: 33.3, SliceId.URLLC: 33.4, SliceId.MURLLC: 33.3},
            compute_allocations={SliceId.EMBB: 33.3, SliceId.URLLC: 33.4, SliceId.MURLLC: 33.3},
            priorities={SliceId.EMBB: 2, SliceId.URLLC: 1, SliceId.MURLLC: 3},
            policy_id=self.policy_id,
        )


class DummyEvaluator(EvaluatorInterface):
    """Minimal test double implementing EvaluatorInterface."""

    def evaluate_transition(
        self,
        current_state: NetworkState,
        executed_action: ExecutedAction,
        next_state: NetworkState,
        config: Optional[RunConfig] = None,
    ) -> StepMetrics:
        return StepMetrics(
            step=next_state.step,
            sim_time_sec=next_state.sim_time_sec,
            throughput_mbps={SliceId.EMBB: 40.0, SliceId.URLLC: 8.0, SliceId.MURLLC: 15.0},
            p95_latency_ms={SliceId.EMBB: 18.0, SliceId.URLLC: 3.5, SliceId.MURLLC: 10.0},
            packet_delivery_ratio={SliceId.EMBB: 0.99, SliceId.URLLC: 1.0, SliceId.MURLLC: 0.999},
            sla_status={SliceId.EMBB: True, SliceId.URLLC: True, SliceId.MURLLC: True},
            sla_breach_count=0,
            radio_utilization_ratio=0.75,
            compute_utilization_ratio=0.70,
        )


def test_interfaces_can_be_implemented_by_test_doubles():
    """Requirement 9: The declared simulator and policy interfaces can be implemented by test doubles."""
    sim = DummySimulator()
    policy = DummyPolicy()
    evaluator = DummyEvaluator()

    # Test reset
    state_0 = sim.reset(seed=42)
    assert state_0.step == 0
    assert len(state_0.slice_states) == 3

    # Test policy proposal
    proposal = policy.predict(state_0)
    assert isinstance(proposal, ProposedAction)
    assert proposal.policy_id == "dummy_equal_share"

    # Convert to executed action (mocking safety passthrough)
    executed = ExecutedAction(
        radio_allocations=proposal.radio_allocations,
        compute_allocations=proposal.compute_allocations,
        priorities=proposal.priorities,
        is_modified_by_safety=False,
    )

    # Test simulator step
    next_state, diag = sim.step(executed)
    assert next_state.step == 1
    assert diag.step == 1
    assert diag.active_flows == 15
    assert diag.terminated is False

    # Test evaluator
    metrics = evaluator.evaluate_transition(state_0, executed, next_state)
    assert metrics.step == 1
    assert metrics.sla_breach_count == 0
    assert metrics.radio_utilization_ratio == 0.75
