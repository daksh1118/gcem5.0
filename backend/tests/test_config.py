"""
Unit tests for SLA Guardian configuration parsing and validation.
Verifies loading scenarios/default.json, field validations, and error boundaries.
"""

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from backend.app.schemas.config import (
    SliceId,
    CANONICAL_SLICE_IDS,
    SliceSlaConfig,
    SliceReservationConfig,
    RunConfig,
)


def get_default_scenario_path() -> Path:
    # Locate scenarios/default.json relative to repository root
    root = Path(__file__).resolve().parent.parent.parent
    return root / "scenarios" / "default.json"


def test_canonical_slice_ids_definition():
    """Verify exactly the three canonical slice IDs are defined."""
    assert len(CANONICAL_SLICE_IDS) == 3
    assert SliceId.EMBB in CANONICAL_SLICE_IDS
    assert SliceId.URLLC in CANONICAL_SLICE_IDS
    assert SliceId.MURLLC in CANONICAL_SLICE_IDS
    assert SliceId.EMBB.value == "eMBB"
    assert SliceId.URLLC.value == "URLLC"
    assert SliceId.MURLLC.value == "mURLLC"


def test_load_default_scenario():
    """Requirement 1: Valid configurations can be loaded and validated."""
    scenario_path = get_default_scenario_path()
    assert scenario_path.exists(), f"Scenario file not found at {scenario_path}"

    with open(scenario_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    config = RunConfig(**raw_data)
    assert config.scenario_id == "default_three_slice_baseline"
    assert config.total_radio_capacity == 100.0
    assert config.total_compute_capacity == 100.0
    assert config.max_steps == 1000
    assert set(config.sla_thresholds.keys()) == set(CANONICAL_SLICE_IDS)
    assert config.minimum_reservations is not None
    assert set(config.minimum_reservations.keys()) == set(CANONICAL_SLICE_IDS)


def test_missing_required_fields_fail_validation():
    """Requirement 2: Missing required fields fail validation."""
    # Omitting scenario_id, total_radio_capacity, total_compute_capacity, sla_thresholds
    with pytest.raises(ValidationError) as exc_info:
        RunConfig()  # type: ignore

    errors = exc_info.value.errors()
    missing_fields = {err["loc"][0] for err in errors if err["type"] == "missing"}
    assert "scenario_id" in missing_fields
    assert "total_radio_capacity" in missing_fields
    assert "total_compute_capacity" in missing_fields
    assert "sla_thresholds" in missing_fields


def test_negative_capacities_and_step_counts_fail():
    """Requirement 3: Negative capacities and invalid step counts fail validation."""
    valid_sla = {
        SliceId.EMBB: SliceSlaConfig(max_latency_ms=20.0, min_throughput_mbps=50.0, min_packet_delivery_ratio=0.99),
        SliceId.URLLC: SliceSlaConfig(max_latency_ms=5.0, min_throughput_mbps=10.0, min_packet_delivery_ratio=0.9999),
        SliceId.MURLLC: SliceSlaConfig(max_latency_ms=15.0, min_throughput_mbps=20.0, min_packet_delivery_ratio=0.999),
    }

    # Test negative radio capacity
    with pytest.raises(ValidationError):
        RunConfig(
            scenario_id="invalid_neg_radio",
            total_radio_capacity=-10.0,
            total_compute_capacity=100.0,
            sla_thresholds=valid_sla,
        )

    # Test zero radio capacity (must be > 0.0)
    with pytest.raises(ValidationError):
        RunConfig(
            scenario_id="invalid_zero_radio",
            total_radio_capacity=0.0,
            total_compute_capacity=100.0,
            sla_thresholds=valid_sla,
        )

    # Test invalid step count (<= 0)
    with pytest.raises(ValidationError):
        RunConfig(
            scenario_id="invalid_zero_steps",
            max_steps=0,
            total_radio_capacity=100.0,
            total_compute_capacity=100.0,
            sla_thresholds=valid_sla,
        )


def test_excessive_reservations_fail():
    """Validates that sum of reservations cannot exceed total capacities."""
    valid_sla = {
        SliceId.EMBB: SliceSlaConfig(max_latency_ms=20.0, min_throughput_mbps=50.0, min_packet_delivery_ratio=0.99),
        SliceId.URLLC: SliceSlaConfig(max_latency_ms=5.0, min_throughput_mbps=10.0, min_packet_delivery_ratio=0.9999),
        SliceId.MURLLC: SliceSlaConfig(max_latency_ms=15.0, min_throughput_mbps=20.0, min_packet_delivery_ratio=0.999),
    }

    # Reservations summing to 120 on a 100 capacity
    excessive_res = {
        SliceId.EMBB: SliceReservationConfig(min_radio_capacity=50.0, min_compute_capacity=10.0),
        SliceId.URLLC: SliceReservationConfig(min_radio_capacity=50.0, min_compute_capacity=10.0),
        SliceId.MURLLC: SliceReservationConfig(min_radio_capacity=25.0, min_compute_capacity=10.0),
    }

    with pytest.raises(ValidationError) as exc_info:
        RunConfig(
            scenario_id="excessive_res",
            total_radio_capacity=100.0,
            total_compute_capacity=100.0,
            sla_thresholds=valid_sla,
            minimum_reservations=excessive_res,
        )
    assert "exceeds total radio capacity" in str(exc_info.value)
