"""
SLA Guardian - FastAPI Application Entry Point
Exposes health checks and system metadata endpoints for the research prototype.
"""

from fastapi import FastAPI
from .schemas.config import CANONICAL_SLICE_IDS, SLICE_DISPLAY_LABELS

app = FastAPI(
    title="SLA Guardian - 5G Network Slicing & Resource Allocation API",
    description="Backend service providing real-time telemetry, policy orchestration, and safety-shielded resource allocation for 5G network slices.",
    version="0.1.0",
)


@app.get("/health", tags=["System"])
def health_check():
    """Returns service health status and active API version."""
    return {
        "status": "healthy",
        "service": "SLA Guardian",
        "version": "0.1.0",
        "phase": "Phase 1 - Project Scaffolding & Shared Data Contracts",
    }


@app.get("/api/slices", tags=["Metadata"])
def get_canonical_slices():
    """Returns canonical slice identifiers and descriptive labels."""
    return {
        "canonical_slice_ids": [s.value for s in CANONICAL_SLICE_IDS],
        "display_labels": {s.value: label for s, label in SLICE_DISPLAY_LABELS.items()},
        "workload_notes": {
            "mURLLC": "Massive / Mixed Ultra-Reliable Low-Latency Communication workload profile. Distinct from standard mMTC."
        }
    }
