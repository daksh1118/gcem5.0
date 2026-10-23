"""
SLA Guardian - Run Results Schema
Defines RunStatus enum and RunResult contract for scenario execution summaries.
"""

from enum import Enum
from typing import Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from .metrics import StepMetrics


class RunStatus(str, Enum):
    """Execution lifecycle status of an experiment or simulation run."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TERMINATED = "TERMINATED"


class RunResult(BaseModel):
    """
    Complete summary record of an executed scenario run.
    Stores metadata, time-series StepMetrics telemetry, and summary statistics.
    """
    run_id: str = Field(
        ...,
        min_length=1,
        description="Unique execution run identifier."
    )
    scenario_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of scenario configuration executed."
    )
    seed: int = Field(
        ...,
        description="Pseudorandom generator seed used for this run."
    )
    policy_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of resource allocation policy executed."
    )
    policy_version: str = Field(
        default="1.0",
        description="Version string of the policy logic."
    )
    status: RunStatus = Field(
        default=RunStatus.PENDING,
        description="Final execution lifecycle status."
    )
    completed_steps: int = Field(
        default=0,
        ge=0,
        description="Total discrete simulation steps completed."
    )
    metrics_history: List[StepMetrics] = Field(
        default_factory=list,
        description="Chronological step-by-step metrics log."
    )
    aggregate_metrics: Optional[Dict[str, float]] = Field(
        default=None,
        description="High-level summary KPIs (e.g. mean SLA breach rate, mean throughput, churn)."
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp of run initialization."
    )
    completed_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 UTC timestamp of run completion."
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error description if status is FAILED."
    )
