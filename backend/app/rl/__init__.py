"""
SLA Guardian - Reinforcement Learning & Constrained Optimization Package
Exposes observation, action decoding, violation cost, Lagrangian multiplier,
and macro-control interval adapters.
"""

from .observation import ObservationAdapter, OBSERVATION_DIM
from .action_mapping import ActionMappingAdapter, ACTION_DIM, stable_softmax
from .cost import ViolationCostAdapter, CRITICAL_SLICES
from .lagrangian import LagrangianMultiplier
from .control_interval import MacroControlAdapter

__all__ = [
    "ObservationAdapter",
    "OBSERVATION_DIM",
    "ActionMappingAdapter",
    "ACTION_DIM",
    "stable_softmax",
    "ViolationCostAdapter",
    "CRITICAL_SLICES",
    "LagrangianMultiplier",
    "MacroControlAdapter",
]
