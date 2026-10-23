"""
Unit tests for SLA Guardian EdgeComputeModel.
Verifies compute capacity allocation, budget enforcement, and queue draining.
"""

import pytest
from backend.app.schemas.config import SliceId, CANONICAL_SLICE_IDS
from backend.app.simulator.compute import EdgeComputeModel
from backend.app.simulator.queues import Packet, PacketQueue


def test_zero_compute_allocation_leaves_queue_unprocessed():
    """Zero compute allocation must not deliver queued packets."""
    compute = EdgeComputeModel(total_compute_capacity=100.0)
    queues = {s: PacketQueue(s, "compute") for s in CANONICAL_SLICE_IDS}

    pkt = Packet(packet_id=1, slice_id=SliceId.URLLC, size_bytes=250, arrival_time=0.0)
    queues[SliceId.URLLC].enqueue(pkt)

    alloc = {SliceId.EMBB: 0.0, SliceId.URLLC: 0.0, SliceId.MURLLC: 0.0}
    delivered, caps = compute.service_queues(queues, alloc, sim_time_sec=0.01, step_duration_sec=0.01)

    assert len(delivered[SliceId.URLLC]) == 0
    assert queues[SliceId.URLLC].size() == 1
    assert caps[SliceId.URLLC] == 0.0


def test_increasing_compute_allocation_increases_processing():
    """Higher compute allocation drains queue faster."""
    compute = EdgeComputeModel(total_compute_capacity=100.0)
    queues = {s: PacketQueue(s, "compute") for s in CANONICAL_SLICE_IDS}

    # Low allocation: 2 compute units = 2 Mbps = 2,500 bytes per 0.01s
    alloc_low = {SliceId.EMBB: 2.0, SliceId.URLLC: 10.0, SliceId.MURLLC: 10.0}
    # Enqueue 10 packets of 1000 bytes = 10,000 bytes
    for i in range(10):
        queues[SliceId.EMBB].enqueue(Packet(packet_id=i, slice_id=SliceId.EMBB, size_bytes=1000, arrival_time=0.0))

    delivered_low, _ = compute.service_queues(queues, alloc_low, sim_time_sec=0.01, step_duration_sec=0.01)
    # 2,500 bytes fits exactly 2 packets
    assert len(delivered_low[SliceId.EMBB]) == 2
    assert queues[SliceId.EMBB].size() == 8

    # High allocation on remaining: 80 compute units = 80 Mbps = 100,000 bytes
    alloc_high = {SliceId.EMBB: 80.0, SliceId.URLLC: 10.0, SliceId.MURLLC: 10.0}
    delivered_high, _ = compute.service_queues(queues, alloc_high, sim_time_sec=0.02, step_duration_sec=0.01)
    # Drains all remaining 8 packets
    assert len(delivered_high[SliceId.EMBB]) == 8
    assert queues[SliceId.EMBB].size() == 0


def test_compute_budget_violations():
    """Excess compute allocations raise ValueError."""
    compute = EdgeComputeModel(total_compute_capacity=100.0)
    queues = {s: PacketQueue(s, "compute") for s in CANONICAL_SLICE_IDS}

    # Sum = 70 + 20 + 20 = 110 > 100
    invalid_alloc = {SliceId.EMBB: 70.0, SliceId.URLLC: 20.0, SliceId.MURLLC: 20.0}
    with pytest.raises(ValueError):
        compute.service_queues(queues, invalid_alloc, sim_time_sec=0.01, step_duration_sec=0.01)

    neg_alloc = {SliceId.EMBB: -1.0, SliceId.URLLC: 50.0, SliceId.MURLLC: 10.0}
    with pytest.raises(ValueError):
        compute.service_queues(queues, neg_alloc, sim_time_sec=0.01, step_duration_sec=0.01)
