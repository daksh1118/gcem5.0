"""
SLA Guardian Policies Package
Exports static slicing policy and adaptive demand-aware heuristic.
"""

from .static import StaticSlicingPolicy
from .heuristic import AdaptiveDemandHeuristicPolicy

__all__ = [
    "StaticSlicingPolicy",
    "AdaptiveDemandHeuristicPolicy",
]
