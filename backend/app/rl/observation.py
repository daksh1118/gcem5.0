"""
SLA Guardian - RL Observation Adapter
Translates NetworkState and RunConfig into a compact, normalized 12-feature NumPy vector
compatible with RL observation spaces.
Feature ordering per slice (eMBB, URLLC, mURLLC):
1. Normalized queue depth (in [0.0, 1.0])
2. Normalized offered demand ratio (in [0.0, 2.0])
3. Current radio allocation share (in [0.0, 1.0])
4. Current compute allocation share (in [0.0, 1.0])
"""

from typing import Optional
import numpy as np

from ..schemas.config import RunConfig, CANONICAL_SLICE_IDS
from ..schemas.state import NetworkState


OBSERVATION_DIM: int = 12  # 3 slices x 4 features


class ObservationAdapter:
    """
    Deterministic builder for RL observation vectors from NetworkState telemetry.
    """

    def __init__(self, queue_scale: float = 1000.0):
        self.queue_scale = max(1.0, queue_scale)

    def build_observation(
        self,
        network_state: NetworkState,
        config: Optional[RunConfig] = None,
    ) -> np.ndarray:
        """
        Constructs a normalized 12-dimensional observation vector.

        Args:
            network_state: Current active NetworkState.
            config: Active RunConfig with total capacities.

        Returns:
            np.ndarray: float32 array of shape (12,), all values finite and bounded.
        """
        total_radio = config.total_radio_capacity if config else network_state.total_radio_capacity
        total_compute = config.total_compute_capacity if config else network_state.total_compute_capacity

        total_radio = max(1.0, float(total_radio))
        total_compute = max(1.0, float(total_compute))

        features = []

        for slice_id in CANONICAL_SLICE_IDS:
            sstate = network_state.slice_states[slice_id]

            # 1. Normalized queue depth
            q_depth = float(sstate.queue_depth_packets) if sstate.queue_depth_packets is not None else 0.0
            norm_q = np.clip(q_depth / self.queue_scale, 0.0, 1.0)

            # 2. Normalized offered load ratio
            demand = float(sstate.offered_demand_mbps) if sstate.offered_demand_mbps is not None else 0.0
            norm_demand = np.clip(demand / total_radio, 0.0, 2.0)

            # 3. Current radio allocation share
            r_alloc = float(sstate.current_radio_allocation) if sstate.current_radio_allocation is not None else 0.0
            norm_r_share = np.clip(r_alloc / total_radio, 0.0, 1.0)

            # 4. Current compute allocation share
            c_alloc = float(sstate.current_compute_allocation) if sstate.current_compute_allocation is not None else 0.0
            norm_c_share = np.clip(c_alloc / total_compute, 0.0, 1.0)

            features.extend([norm_q, norm_demand, norm_r_share, norm_c_share])

        obs = np.array(features, dtype=np.float32)

        # Assert finite
        if not np.all(np.isfinite(obs)):
            obs = np.nan_to_num(obs, nan=0.0, posinf=1.0, neginf=0.0)

        return obs
