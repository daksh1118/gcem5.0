"""
SLA Guardian - Lagrangian Multiplier Utility
Implements the episodic dual multiplier update for Constrained RL.
Objective:
    lambda_{k+1} = clip(lambda_k + lr * (mean_cost - cost_limit), 0.0, max_lambda)
"""

from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class LagrangianMultiplier:
    """
    Stateful Lagrangian multiplier for dual constraint optimization.
    Updates once per completed episode based on mean critical slice violation cost.
    """

    def __init__(
        self,
        init_lambda: float = 0.0,
        lr: float = 0.05,
        cost_limit: float = 0.01,
        max_lambda: float = 100.0,
    ):
        self.init_lambda = float(max(0.0, init_lambda))
        self.lr = float(max(1e-6, lr))
        self.cost_limit = float(max(0.0, cost_limit))
        self.max_lambda = float(max(self.cost_limit, max_lambda))
        self.current_lambda = self.init_lambda
        self.update_count = 0

    @property
    def value(self) -> float:
        """Returns the active non-negative multiplier value."""
        return self.current_lambda

    def update(self, episode_mean_cost: float) -> float:
        """
        Updates the multiplier based on the mean violation cost of the completed episode.

        Args:
            episode_mean_cost: Mean critical slice packet violation rate in [0.0, 1.0].

        Returns:
            float: Updated non-negative multiplier value.
        """
        cost = float(episode_mean_cost)
        prev_lambda = self.current_lambda

        # Gradient ascent step on dual variable
        delta = self.lr * (cost - self.cost_limit)
        updated = prev_lambda + delta

        # Project onto feasible dual set [0, max_lambda]
        self.current_lambda = float(min(self.max_lambda, max(0.0, updated)))
        self.update_count += 1

        logger.debug(
            "Lagrangian update #%d: cost=%.4f (limit=%.4f) | lambda: %.4f -> %.4f",
            self.update_count, cost, self.cost_limit, prev_lambda, self.current_lambda
        )
        return self.current_lambda

    def reset(self):
        """Resets the multiplier to its initial configuration."""
        self.current_lambda = self.init_lambda
        self.update_count = 0

    def get_state(self) -> Dict[str, Any]:
        """Returns the serialization dictionary for checkpointing."""
        return {
            "current_lambda": self.current_lambda,
            "update_count": self.update_count,
            "lr": self.lr,
            "cost_limit": self.cost_limit,
            "max_lambda": self.max_lambda,
        }

    def load_state(self, state: Dict[str, Any]):
        """Restores state from a checkpoint dictionary."""
        self.current_lambda = float(state.get("current_lambda", self.init_lambda))
        self.update_count = int(state.get("update_count", 0))
        self.lr = float(state.get("lr", self.lr))
        self.cost_limit = float(state.get("cost_limit", self.cost_limit))
        self.max_lambda = float(state.get("max_lambda", self.max_lambda))
