"""
SLA Guardian - Policy & Evaluator Interface Specifications
Defines abstract contracts for decision policies (RL/Heuristic/Static) and evaluation engines.
"""

from abc import ABC, abstractmethod
from typing import Optional, Any

from ..schemas.config import RunConfig
from ..schemas.state import NetworkState
from ..schemas.actions import ProposedAction, ExecutedAction
from ..schemas.metrics import StepMetrics


class PolicyInterface(ABC):
    """
    Abstract Protocol / Base Class for Network Slicing Resource Allocation Policies.
    
    Compatible with:
    - Static equal/proportional slicing
    - Classical heuristics (e.g. queue-proportional, deficit round-robin)
    - Optimization-based solvers (e.g. convex/linear programming)
    - Reinforcement Learning agents (e.g. PPO, DQN, MaskablePPO)
    """

    @property
    @abstractmethod
    def policy_id(self) -> str:
        """Unique identifier of the policy algorithm."""
        pass

    @property
    @abstractmethod
    def policy_version(self) -> str:
        """Semantic version of the policy implementation."""
        pass

    @abstractmethod
    def predict(self, observation: NetworkState) -> ProposedAction:
        """
        Observes current multi-slice network state and outputs an unvalidated proposed allocation.
        
        Args:
            observation: Current NetworkState.
            
        Returns:
            ProposedAction: Suggested radio/compute allocations and priorities.
        """
        pass


class EvaluatorInterface(ABC):
    """
    Abstract Protocol / Base Class for Transition Evaluation and Telemetry Computation.
    """

    @abstractmethod
    def evaluate_transition(
        self,
        current_state: NetworkState,
        executed_action: ExecutedAction,
        next_state: NetworkState,
        config: Optional[RunConfig] = None,
        diagnostics: Optional[Any] = None,
    ) -> StepMetrics:
        """
        Computes SLA compliance, resource utilization, and telemetry metrics from a state transition.
        
        Args:
            current_state: State observation at step t.
            executed_action: Verified allocation executed between step t and t+1.
            next_state: Resulting state observation at step t+1.
            config: Optional RunConfig containing SLA thresholds.
            diagnostics: Optional SimulatorDiagnostics from the simulation step.
            
        Returns:
            StepMetrics: Telemetry record for step t+1.
        """
        pass
