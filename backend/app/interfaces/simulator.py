"""
SLA Guardian - Simulator Interface Specification
Defines abstract contracts for 5G network slicing simulators (both Fallback and 5G-LENA adapters).
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple
from pydantic import BaseModel, Field

from ..schemas.config import RunConfig
from ..schemas.state import NetworkState
from ..schemas.actions import ExecutedAction


class SimulatorDiagnostics(BaseModel):
    """Diagnostic telemetry emitted by the simulator at each step."""
    step: int = Field(..., ge=0)
    terminated: bool = Field(default=False, description="True if episode completed naturally.")
    truncated: bool = Field(default=False, description="True if maximum step limit reached.")
    active_flows: int = Field(default=0, ge=0)
    dropped_packets: int = Field(default=0, ge=0)
    extra_info: Dict[str, Any] = Field(default_factory=dict)


class SimulatorInterface(ABC):
    """
    Abstract Protocol / Base Class for Network Simulators.
    
    Guarantees:
    1. The simulator ONLY consumes validated `ExecutedAction` commands, never raw `ProposedAction`.
    2. Step Advancement: Each invocation of `step()` advances simulation time by `config.step_duration_ms`.
    3. Termination: Handled via the returned `SimulatorDiagnostics.terminated` and `truncated` flags,
       adhering to the standard Gymnasium `step()` lifecycle.
    """

    @abstractmethod
    def reset(
        self,
        seed: Optional[int] = None,
        scenario: Optional[Dict[str, Any]] = None,
        config: Optional[RunConfig] = None,
    ) -> NetworkState:
        """
        Resets simulator state and initializes traffic generators.
        
        Args:
            seed: Pseudorandom seed for reproducible channels and traffic.
            scenario: Optional raw scenario dictionary.
            config: Optional validated RunConfig specification.
            
        Returns:
            NetworkState: Initial state observation at step 0 (before packet transmissions).
        """
        pass

    @abstractmethod
    def step(
        self,
        executed_action: ExecutedAction,
    ) -> Tuple[NetworkState, SimulatorDiagnostics]:
        """
        Applies verified radio and compute resource allocations and advances simulation by one interval.
        
        Args:
            executed_action: The post-safety, validated resource allocation.
            
        Returns:
            Tuple[NetworkState, SimulatorDiagnostics]: The resulting network observation
            and step diagnostic metadata (including termination and truncation flags).
        """
        pass
