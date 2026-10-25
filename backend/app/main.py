"""
SLA Guardian - FastAPI Application Entry Point
Exposes real-time telemetry streaming (WebSocket /ws), scenario orchestration,
runtime demand spike injection, and multi-policy comparative evaluation.
"""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .schemas.config import CANONICAL_SLICE_IDS, SLICE_DISPLAY_LABELS
from .schemas.telemetry import (
    RunStartRequest,
    SpikeRequest,
    ResetRequest,
    MultiPolicySummary,
    TraceValidationRequest,
    TraceValidationResponse,
    TrafficSourceSelectionRequest,
)
from .services.experiment_runner import ExperimentRunner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sla_guardian.api")

# Global singleton coordinator
runner: Optional[ExperimentRunner] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes long-lived experiment coordinator on startup and tears down on shutdown."""
    global runner
    root_dir = Path(__file__).resolve().parent.parent.parent
    scenario_path = root_dir / "scenarios" / "default.json"
    checkpoint_path = root_dir / "models" / "agent.zip"

    logger.info("Initializing SLA Guardian Experiment Runner...")
    runner = ExperimentRunner(
        scenario_file=scenario_path,
        checkpoint_path=checkpoint_path,
        steps_per_interval=10,
    )
    yield
    # Shutdown / cleanup
    if runner and runner.background_task and not runner.background_task.done():
        runner.background_task.cancel()
    logger.info("SLA Guardian Experiment Runner shutdown complete.")


app = FastAPI(
    title="SLA Guardian - 5G Network Slicing & Resource Allocation API",
    description="Backend service providing real-time telemetry, policy orchestration, and safety-shielded resource allocation for 5G network slices.",
    version="0.2.0",
    lifespan=lifespan,
)

# Enable CORS for dashboard web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_runner() -> ExperimentRunner:
    """Helper to ensure experiment runner is initialized."""
    global runner
    if runner is None:
        root_dir = Path(__file__).resolve().parent.parent.parent
        scenario_path = root_dir / "scenarios" / "default.json"
        checkpoint_path = root_dir / "models" / "agent.zip"
        runner = ExperimentRunner(
            scenario_file=scenario_path,
            checkpoint_path=checkpoint_path,
            steps_per_interval=10,
        )
    return runner


# ---------------------------------------------------------------------------
# System & Health Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
def health_check():
    """
    Returns service health status, model readiness, and active scenario state.
    Distinguishes a basic running server from a fully ready demo with a verified Agent.
    """
    r = _get_runner()
    demo_ready = r.model_loaded and (r.rl_policy_instance is not None)
    return {
        "status": "healthy" if demo_ready else "degraded",
        "service": "SLA Guardian",
        "version": "0.2.0",
        "phase": "Phase 6 - FastAPI Backend & Telemetry Streaming",
        "demo_ready": demo_ready,
        "model_loaded": r.model_loaded,
        "model_path": str(r.checkpoint_path),
        "model_error": r.model_error,
        "active_scenario": r.active_scenario,
        "macro_step": r.current_macro_step,
        "run_status": r.status,
    }


@app.get("/api/slices", tags=["Metadata"])
def get_canonical_slices():
    """Returns canonical slice identifiers and descriptive labels."""
    return {
        "canonical_slice_ids": [s.value for s in CANONICAL_SLICE_IDS],
        "display_labels": {s.value: label for s, label in SLICE_DISPLAY_LABELS.items()},
        "workload_notes": {
            "mURLLC": "Massive / Mixed Ultra-Reliable Low-Latency Communication workload profile. Distinct from standard mMTC."
        },
    }


# ---------------------------------------------------------------------------
# Scenarios Metadata
# ---------------------------------------------------------------------------

@app.get("/api/scenarios", tags=["Scenarios"])
@app.get("/scenarios", tags=["Scenarios"], include_in_schema=False)
def list_scenarios():
    """Returns available scenarios with real configuration metadata from scenarios/default.json."""
    r = _get_runner()
    profiles = r.raw_scenario_data.get("traffic_profiles", {})
    scenario_list = []
    for sc_id, sc_data in profiles.items():
        scenario_list.append({
            "id": sc_id,
            "description": sc_data.get("description", ""),
            "nominal_demand_mbps": sc_data.get("nominal_demand_mbps", {}),
            "burst_multiplier": sc_data.get("burst_multiplier")
            or sc_data.get("surge_multiplier")
            or sc_data.get("storm_multiplier"),
        })

    return {
        "scenario_id": r.raw_scenario_data.get("scenario_id", "default_three_slice_baseline"),
        "total_radio_capacity": r.base_config.total_radio_capacity,
        "total_compute_capacity": r.base_config.total_compute_capacity,
        "sla_thresholds": {
            s.value: thresh.model_dump() for s, thresh in r.base_config.sla_thresholds.items()
        },
        "minimum_reservations": {
            s.value: res.model_dump() for s, res in r.base_config.minimum_reservations.items()
        },
        "scenarios": scenario_list,
    }


# ---------------------------------------------------------------------------
# Experiment Lifecycle Control
# ---------------------------------------------------------------------------

@app.post("/api/runs", tags=["Experiment Control"], status_code=status.HTTP_201_CREATED)
@app.post("/runs", tags=["Experiment Control"], include_in_schema=False, status_code=status.HTTP_201_CREATED)
async def start_run(request: RunStartRequest):
    """
    Starts a new experiment with validated scenario, seed, macro-step budget, and traffic source.
    Cancels and replaces any currently active run.
    """
    r = _get_runner()
    # If synthetic, validate scenario exists in traffic_profiles
    if request.traffic_source_type == "synthetic":
        valid_scenarios = r.raw_scenario_data.get("traffic_profiles", {}).keys()
        if request.scenario not in valid_scenarios:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown scenario '{request.scenario}'. Valid scenarios: {list(valid_scenarios)}",
            )
    elif request.traffic_source_type == "trace_replay":
        # Validate trace file exists
        if not request.trace_file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="trace_file must be specified when traffic_source_type is 'trace_replay'.",
            )
        trace_path = r.traces_dir / request.trace_file
        if not trace_path.exists() and not Path(request.trace_file).exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Trace file '{request.trace_file}' not found in data/traces/.",
            )

    res = await r.start_run(
        scenario=request.scenario,
        seed=request.seed,
        max_macro_steps=request.max_macro_steps,
        selected_policies=request.selected_policies,
        traffic_source_type=request.traffic_source_type,
        trace_file=request.trace_file,
        telemetry_endpoint=request.telemetry_endpoint,
        replay_speed=request.replay_speed,
    )
    return res


@app.post("/api/pause", tags=["Experiment Control"])
async def pause_run():
    """Pauses the active experiment loop."""
    r = _get_runner()
    return await r.pause()


@app.post("/api/resume", tags=["Experiment Control"])
async def resume_run():
    """Resumes a paused experiment loop."""
    r = _get_runner()
    return await r.resume()


@app.post("/api/reset", tags=["Experiment Control"])
@app.post("/reset", tags=["Experiment Control"], include_in_schema=False)
async def reset_experiment(request: Optional[ResetRequest] = None):
    """
    Resets all three policy environments and accumulators to step 0.
    Ensures zero cross-run data contamination.
    """
    r = _get_runner()
    scen = request.scenario if request else None
    seed = request.seed if request else None
    ts_type = request.traffic_source_type if request else None
    t_file = request.trace_file if request else None
    return await r.reset(
        scenario=scen,
        seed=seed,
        traffic_source_type=ts_type,
        trace_file=t_file,
    )


# ---------------------------------------------------------------------------
# Model Checkpoint Management
# ---------------------------------------------------------------------------

@app.get("/api/models", tags=["Model Checkpoints"])
def list_available_models():
    """Lists available PPO checkpoints and active model state."""
    r = _get_runner()
    return {
        "active_checkpoint": r.checkpoint_path.name,
        "trained_lambda": r.trained_lambda,
        "available_models": [
            {
                "key": "frozen",
                "filename": "agent.zip",
                "label": "Frozen Baseline PPO (Single-Scenario, lambda=0.0)",
                "active": r.checkpoint_path.name == "agent.zip",
            },
            {
                "key": "candidate",
                "filename": "candidate_agent.zip",
                "label": "Candidate Remediated PPO (Multi-Scenario, lambda=1.1646)",
                "active": r.checkpoint_path.name == "candidate_agent.zip",
            },
        ],
    }


@app.post("/api/models/select", tags=["Model Checkpoints"])
def select_model_checkpoint(payload: Dict[str, str]):
    """Switches active PPO model checkpoint between 'frozen' and 'candidate'."""
    r = _get_runner()
    model_key = payload.get("model", "frozen")
    return r.switch_model_checkpoint(model_key)


# ---------------------------------------------------------------------------
# Traffic Sources & Trace Ingestion Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/traffic/sources", tags=["Traffic Sources"])
def list_traffic_sources():
    """Lists available synthetic scenarios, recorded traces in data/traces/, and live telemetry status."""
    r = _get_runner()
    return r.list_traffic_sources()


@app.get("/api/traffic/status", tags=["Traffic Sources"])
def get_traffic_status():
    """Returns metadata and health for the currently active traffic source."""
    r = _get_runner()
    return r.get_traffic_status()


@app.post("/api/traffic/validate-trace", tags=["Traffic Sources"], response_model=TraceValidationResponse)
def validate_trace(request: TraceValidationRequest):
    """Validates trace formatting, time range, sample count, and slice classification coverage."""
    r = _get_runner()
    try:
        res = r.validate_trace_file(request.file_name, request.qos_mapping)
        return TraceValidationResponse(**res)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.post("/api/traffic/upload-trace", tags=["Traffic Sources"])
async def upload_trace_file(file: UploadFile = File(...)):
    """Uploads a recorded trace file (CSV, JSONL, or PCAP) into data/traces/."""
    r = _get_runner()
    filename = Path(file.filename).name
    if not any(filename.lower().endswith(ext) for ext in (".csv", ".tsv", ".jsonl", ".ndjson", ".json", ".pcap")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format for '{filename}'. Supported: .csv, .jsonl, .json, .pcap",
        )

    out_path = r.traces_dir / filename
    content = await file.read()
    with open(out_path, "wb") as f:
        f.write(content)

    # Automatically validate uploaded file
    try:
        validation = r.validate_trace_file(filename)
        return {
            "status": "uploaded",
            "file_name": filename,
            "size_bytes": len(content),
            "valid": validation.get("valid", True),
            "validation": validation,
        }
    except Exception as e:
        return {
            "status": "uploaded_with_warnings",
            "file_name": filename,
            "size_bytes": len(content),
            "error": str(e),
        }


@app.post("/api/spike", tags=["Experiment Control"])
@app.post("/spike", tags=["Experiment Control"], include_in_schema=False)
async def trigger_spike(request: SpikeRequest):
    """
    Injects an instantaneous demand burst identically into all three policy simulators.
    """
    r = _get_runner()
    try:
        res = await r.inject_spike(
            target_slice=request.target_slice,
            multiplier=request.multiplier,
            duration_steps=request.duration_steps,
            start_step=request.start_step,
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.get("/api/status", tags=["Status"])
def get_run_status():
    """Returns real-time execution status and progress of the active experiment."""
    r = _get_runner()
    return r.get_status()


@app.get("/api/summary", tags=["Results"], response_model=MultiPolicySummary)
@app.get("/summary", tags=["Results"], include_in_schema=False, response_model=MultiPolicySummary)
def get_run_summary():
    """
    Returns cumulative and per-slice performance summaries for Static, Heuristic, and Agent.
    Strictly derives metrics from whole-run numerators and denominators.
    """
    r = _get_runner()
    return r.get_summary()


@app.post("/api/step", tags=["Experiment Control"])
async def trigger_single_step():
    """Manually triggers exactly one synchronized 100 ms macro-control interval."""
    r = _get_runner()
    evt = await r.step_once()
    return evt.model_dump()


# ---------------------------------------------------------------------------
# WebSocket Telemetry Stream
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_telemetry_stream(websocket: WebSocket):
    """
    Live real-time telemetry stream delivering synchronized 100 ms macro updates
    across Static, Heuristic, and PPO policies.
    """
    await websocket.accept()
    r = _get_runner()
    await r.add_subscriber(websocket)
    logger.info("WebSocket subscriber connected to live telemetry stream.")

    try:
        while True:
            # Keep connection open, handle incoming heartbeat or client messages
            msg = await websocket.receive_text()
            if msg == "step":
                await r.step_once()
            elif msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        r.remove_subscriber(websocket)
        logger.info("WebSocket subscriber disconnected.")
    except Exception as e:
        r.remove_subscriber(websocket)
        logger.warning(f"WebSocket client error: {e}")


# ---------------------------------------------------------------------------
# Frontend Static Mount (Dashboard Console)
# ---------------------------------------------------------------------------
frontend_path = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")

