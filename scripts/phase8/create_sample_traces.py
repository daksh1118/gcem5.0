"""
SLA Guardian - Sample Trace Generator
Creates realistic 5G multi-slice trace fixtures in CSV, JSONL, and JSON formats for testing.
All generated data is clearly labeled as synthetic test trace data.
"""

import csv
import json
from pathlib import Path
import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TRACE_DIR = ROOT_DIR / "data" / "traces"
TRACE_DIR.mkdir(parents=True, exist_ok=True)


def generate_traces():
    rng = np.random.default_rng(42)

    # 1. Multi-slice CSV trace (10 seconds, ~1500 packets)
    csv_path = TRACE_DIR / "sample_5g_multi_slice_trace.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "size_bytes", "slice_id", "5qi", "flow_id", "ue_id", "direction"
        ])

        curr_time = 0.0
        pkt_id = 0
        while curr_time < 10.0:
            # Advance time by small delta (average arrival delta ~5ms)
            dt = float(rng.exponential(0.005))
            curr_time += dt
            if curr_time >= 10.0:
                break

            # Probabilistically select slice
            r = rng.random()
            if r < 0.65:
                # eMBB video stream
                s_id = "eMBB"
                q_tag = "5qi_9"
                size = int(rng.choice([1400, 1420, 1380, 1440]))
                flow = f"flow_embb_{rng.integers(1, 4)}"
                ue = f"ue_embb_{rng.integers(101, 110)}"
            elif r < 0.85:
                # URLLC tactile / vehicular control
                s_id = "URLLC"
                q_tag = "5qi_1"
                # Add burst between 3.0s and 5.0s
                if 3.0 <= curr_time <= 5.0:
                    burst_count = rng.integers(2, 6)
                else:
                    burst_count = 1

                for _ in range(burst_count):
                    pkt_id += 1
                    writer.writerow([
                        round(curr_time, 5),
                        250,
                        s_id,
                        q_tag,
                        f"flow_urllc_{rng.integers(1, 3)}",
                        f"ue_tactile_{rng.integers(201, 205)}",
                        "downlink",
                    ])
                continue
            else:
                # mURLLC industrial sensor aggregation
                s_id = "mURLLC"
                q_tag = "5qi_79"
                size = int(rng.choice([480, 500, 520]))
                flow = f"flow_sensor_{rng.integers(1, 5)}"
                ue = f"ue_sensor_{rng.integers(301, 320)}"

            pkt_id += 1
            writer.writerow([
                round(curr_time, 5),
                size,
                s_id,
                q_tag,
                flow,
                ue,
                "downlink",
            ])

    print(f"[+] Created CSV trace: {csv_path} ({pkt_id} packets)")

    # 2. JSONL trace with 5QI labels and source measurements
    jsonl_path = TRACE_DIR / "sample_5g_trace.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        curr_time = 0.0
        pkt_id = 0
        while curr_time < 8.0:
            dt = float(rng.exponential(0.006))
            curr_time += dt
            if curr_time >= 8.0:
                break

            r = rng.random()
            if r < 0.60:
                slice_label = "eMBB"
                qos = "5qi_9"
                size = 1400
                lat = round(float(rng.uniform(12.0, 18.0)), 2)
            elif r < 0.85:
                slice_label = "URLLC"
                qos = "5qi_1"
                size = 250
                lat = round(float(rng.uniform(1.5, 3.5)), 2)
            else:
                slice_label = "mURLLC"
                qos = "5qi_79"
                size = 500
                lat = round(float(rng.uniform(6.0, 10.0)), 2)

            pkt_id += 1
            record = {
                "packet_id": pkt_id,
                "timestamp": round(curr_time, 5),
                "size_bytes": size,
                "slice_id": slice_label,
                "qos_label": qos,
                "flow_id": f"flow_{slice_label.lower()}_stream",
                "ue_id": f"ue_anon_{rng.integers(1000, 9999)}",
                "direction": "downlink",
                "latency_ms": lat,
                "pdr": 1.0,
            }
            f.write(json.dumps(record) + "\n")

    print(f"[+] Created JSONL trace: {jsonl_path} ({pkt_id} packets)")

    # 3. Trace with unclassified traffic (test fixture)
    unclass_path = TRACE_DIR / "sample_with_unclassified.csv"
    with open(unclass_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "size_bytes", "slice_id", "qos_label", "flow_id"])
        writer.writerow([0.010, 1400, "eMBB", "5qi_9", "flow_1"])
        writer.writerow([0.020, 250, "URLLC", "5qi_1", "flow_2"])
        writer.writerow([0.030, 800, "UNKNOWN_SLICE", "unmapped_dscp_99", "flow_unknown_1"])
        writer.writerow([0.040, 500, "mURLLC", "5qi_79", "flow_3"])
        writer.writerow([0.050, 1200, "", "", "flow_unlabeled_2"])
    print(f"[+] Created unclassified fixture: {unclass_path}")

    # 4. Binary PCAP trace fixture
    pcap_path = TRACE_DIR / "sample_5g_trace.pcap"
    import struct
    with open(pcap_path, "wb") as f:
        # PCAP Global Header: magic (0xa1b2c3d4), v2.4, thiszone=0, sigfigs=0, snaplen=65535, network=1 (Ethernet)
        f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))

        curr_time = 0.0
        pkt_id = 0
        while curr_time < 5.0:
            dt = float(rng.exponential(0.005))
            curr_time += dt
            if curr_time >= 5.0:
                break

            r = rng.random()
            if r < 0.60:
                # eMBB (CS0 / Best Effort, DSCP 0)
                dscp = 0
                pkt_len = 1400
            elif r < 0.85:
                # URLLC (Expedited Forwarding, DSCP 46)
                dscp = 46
                pkt_len = 250
            else:
                # mURLLC (AF11, DSCP 10)
                dscp = 10
                pkt_len = 500

            tos = (dscp << 2) & 0xFF
            pkt_id += 1

            # Build minimal Ethernet (14B) + IPv4 (20B) header
            eth_hdr = b"\x00\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb\x08\x00"
            ip_hdr = bytearray(20)
            ip_hdr[0] = 0x45  # IPv4, 5 words (20 bytes)
            ip_hdr[1] = tos   # DSCP in ToS
            struct.pack_into("!H", ip_hdr, 2, min(pkt_len, 1500))  # Total length
            struct.pack_into("!H", ip_hdr, 4, pkt_id % 65535)      # Ident
            ip_hdr[8] = 64    # TTL
            ip_hdr[9] = 17    # UDP
            ip_hdr[12:16] = b"\x0a\x00\x00\x01" # 10.0.0.1
            ip_hdr[16:20] = b"\x0a\x00\x00\x02" # 10.0.0.2

            payload_len = max(0, min(pkt_len - 34, 100))
            frame_data = eth_hdr + bytes(ip_hdr) + (b"\x00" * payload_len)
            incl_len = len(frame_data)
            orig_len = pkt_len

            sec = int(curr_time)
            usec = int((curr_time - sec) * 1e6)
            f.write(struct.pack("<IIII", sec, usec, incl_len, orig_len))
            f.write(frame_data)

    print(f"[+] Created binary PCAP trace: {pcap_path} ({pkt_id} packets)")

    # 5. Live telemetry sample payload (for mock / integration tests)
    live_sample_path = TRACE_DIR / "sample_live_telemetry_payload.json"
    with open(live_sample_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": 1730000000.0,
            "core_network": {
                "active_upf_sessions": 42,
                "smf_status": "UP",
                "core_load_ratio": 0.45
            },
            "slices": {
                "eMBB": {"offered_demand_mbps": 52.4, "throughput_mbps": 48.1},
                "URLLC": {"offered_demand_mbps": 11.2, "throughput_mbps": 11.2},
                "mURLLC": {"offered_demand_mbps": 22.0, "throughput_mbps": 21.5}
            }
        }, f, indent=2)
    print(f"[+] Created sample live telemetry payload: {live_sample_path}")


if __name__ == "__main__":
    generate_traces()

