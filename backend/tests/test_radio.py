"""
Unit tests for SLA Guardian RadioModel.
Verifies OFDMA service rates, budget constraint enforcement, queue draining,
and channel fading bounds.
"""

import pytest
from backend.app.schemas.config import SliceId, CANONICAL_SLICE_IDS
from backend.app.simulator.radio import RadioModel
from backend.app.simulator.queues import Packet, PacketQueue


def test_zero_radio_allocation_yields_zero_service():
    """Zero allocation should not service any packets."""
    radio = RadioModel(total_radio_capacity=100.0, seed=42)
    queues = {s: PacketQueue(s, "radio") for s in CANONICAL_SLICE_IDS}

    # Put a packet in eMBB queue
    pkt = Packet(packet_id=1, slice_id=SliceId.EMBB, size_bytes=1000, arrival_time=0.0)
    queues[SliceId.EMBB].enqueue(pkt)

    allocations = {SliceId.EMBB: 0.0, SliceId.URLLC: 0.0, SliceId.MURLLC: 0.0}
    serviced, caps = radio.service_queues(queues, allocations, sim_time_sec=0.0, step_duration_sec=0.01)

    assert len(serviced[SliceId.EMBB]) == 0
    assert queues[SliceId.EMBB].size() == 1
    assert caps[SliceId.EMBB] == 0.0


def test_increasing_allocation_increases_capacity():
    """Higher allocation yields higher achievable service capacity."""
    radio = RadioModel(total_radio_capacity=100.0, enable_channel_fading=False)
    queues = {s: PacketQueue(s, "radio") for s in CANONICAL_SLICE_IDS}

    alloc_low = {SliceId.EMBB: 10.0, SliceId.URLLC: 10.0, SliceId.MURLLC: 10.0}
    _, caps_low = radio.service_queues(queues, alloc_low, sim_time_sec=0.0, step_duration_sec=0.01)

    alloc_high = {SliceId.EMBB: 50.0, SliceId.URLLC: 10.0, SliceId.MURLLC: 10.0}
    _, caps_high = radio.service_queues(queues, alloc_high, sim_time_sec=0.0, step_duration_sec=0.01)

    assert caps_high[SliceId.EMBB] > caps_low[SliceId.EMBB]


def test_budget_violation_raises_error():
    """Radio allocation exceeding total capacity must be rejected with ValueError."""
    radio = RadioModel(total_radio_capacity=100.0)
    queues = {s: PacketQueue(s, "radio") for s in CANONICAL_SLICE_IDS}

    # Sum = 60 + 30 + 20 = 110 > 100
    invalid_alloc = {SliceId.EMBB: 60.0, SliceId.URLLC: 30.0, SliceId.MURLLC: 20.0}
    with pytest.raises(ValueError) as exc:
        radio.service_queues(queues, invalid_alloc, sim_time_sec=0.0, step_duration_sec=0.01)
    assert "exceeds total radio capacity" in str(exc.value)

    # Negative allocation
    neg_alloc = {SliceId.EMBB: -5.0, SliceId.URLLC: 50.0, SliceId.MURLLC: 20.0}
    with pytest.raises(ValueError):
        radio.service_queues(queues, neg_alloc, sim_time_sec=0.0, step_duration_sec=0.01)


def test_radio_queue_accumulation_under_insufficient_service():
    """Queues grow when arrival rate consistently exceeds service rate."""
    radio = RadioModel(total_radio_capacity=100.0, enable_channel_fading=False)
    queues = {s: PacketQueue(s, "radio") for s in CANONICAL_SLICE_IDS}

    # Allocate tiny service: 1 PRB = 1 Mbps = 1,250 bytes per 0.01s step
    alloc = {SliceId.EMBB: 1.0, SliceId.URLLC: 10.0, SliceId.MURLLC: 10.0}

    # Enqueue 10 packets of 1400 bytes each = 14,000 bytes
    for i in range(10):
        queues[SliceId.EMBB].enqueue(Packet(packet_id=i, slice_id=SliceId.EMBB, size_bytes=1400, arrival_time=0.0))

    initial_size = queues[SliceId.EMBB].size()
    assert initial_size == 10

    serviced, _ = radio.service_queues(queues, alloc, sim_time_sec=0.0, step_duration_sec=0.01)
    # Service can only fit 0 packets (1400 > 1250 bytes)
    assert len(serviced[SliceId.EMBB]) == 0
    assert queues[SliceId.EMBB].size() == 10
    assert queues[SliceId.EMBB].queued_bytes() > 0
