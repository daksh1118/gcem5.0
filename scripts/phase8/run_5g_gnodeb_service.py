"""
SLA Guardian - Standalone 5G gNodeB & RAN Telemetry Service
Emulates a 3GPP Release 16 5G NR gNodeB (Cell n78, 100 MHz, 273 PRBs, 30 kHz SCS).
Streams real-time physical-layer and slice-level radio telemetry via HTTP on port 9090.

Supported telemetry formats:
1. Generic JSON: GET /telemetry or GET /
2. Prometheus: GET /api/v1/query
3. Open5GS: GET /open5gs/api/v1/subscribers
4. Health: GET /health
"""

import math
import time
import json
import random
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [5G-gNodeB] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("5g_gnodeb")


class GNodeBState:
    """Simulates internal 5G gNodeB radio scheduler and channel conditions."""

    def __init__(self):
        self.gnb_id = "gnb-nr-5g-001"
        self.cell_id = "cell-01-band-n78"
        self.frequency_ghz = 3.5
        self.total_prbs = 273
        self.scs_khz = 30
        self.start_time = time.time()

        # Connected UE populations
        self.ue_counts = {
            "eMBB": 32,
            "URLLC": 8,
            "mURLLC": 12,
        }

    def get_snapshot(self):
        """Generates real-time 5G radio measurements with Rayleigh fading noise."""
        elapsed = time.time() - self.start_time

        # Sinusoidal diurnal wave + stochastic burstiness
        embb_wave = 45.0 + 12.0 * math.sin(elapsed * 0.15) + random.gauss(0, 3.0)
        urllc_wave = 9.0 + 3.0 * math.cos(elapsed * 0.25) + (15.0 if random.random() < 0.08 else 0.0) + random.gauss(0, 0.8)
        murllc_wave = 15.0 + 5.0 * math.sin(elapsed * 0.1) + (20.0 if random.random() < 0.05 else 0.0) + random.gauss(0, 1.2)

        embb_mbps = max(5.0, round(embb_wave, 2))
        urllc_mbps = max(1.0, round(urllc_wave, 2))
        murllc_mbps = max(2.0, round(murllc_wave, 2))

        # PRB consumption estimate (spectral efficiency ~4.5 bps/Hz eMBB, ~2.0 bps/Hz URLLC)
        prb_embb = min(160, int(embb_mbps * 2.2))
        prb_urllc = min(70, int(urllc_mbps * 5.0))
        prb_murllc = min(60, int(murllc_mbps * 3.5))
        total_used_prbs = min(self.total_prbs, prb_embb + prb_urllc + prb_murllc)
        prb_util = round((total_used_prbs / self.total_prbs) * 100.0, 1)

        total_ues = sum(self.ue_counts.values())

        return {
            "timestamp": time.time(),
            "elapsed_sec": round(elapsed, 2),
            "gnodeb": {
                "id": self.gnb_id,
                "cell_id": self.cell_id,
                "carrier_freq_ghz": self.frequency_ghz,
                "total_prbs": self.total_prbs,
                "allocated_prbs": total_used_prbs,
                "prb_utilization_pct": prb_util,
                "active_ues": total_ues,
                "status": "OPERATIONAL_ACTIVE",
            },
            "slices": {
                "eMBB": {
                    "offered_demand_mbps": embb_mbps,
                    "prb_allocation": prb_embb,
                    "active_ues": self.ue_counts["eMBB"],
                    "snr_db": round(24.5 + random.gauss(0, 1.5), 1),
                },
                "URLLC": {
                    "offered_demand_mbps": urllc_mbps,
                    "prb_allocation": prb_urllc,
                    "active_ues": self.ue_counts["URLLC"],
                    "snr_db": round(28.0 + random.gauss(0, 1.0), 1),
                },
                "mURLLC": {
                    "offered_demand_mbps": murllc_mbps,
                    "prb_allocation": prb_murllc,
                    "active_ues": self.ue_counts["mURLLC"],
                    "snr_db": round(22.0 + random.gauss(0, 2.0), 1),
                },
            },
            "core_network": {
                "amf_connection": "CONNECTED",
                "upf_active_sessions": total_ues,
                "upf_gtp_tunnel_status": "UP",
            },
        }


g_state = GNodeBState()


class GNodeBTelemetryHandler(BaseHTTPRequestHandler):
    """HTTP handler responding to SLA Guardian live telemetry queries."""

    def log_message(self, format, *args):
        # Suppress routine 200 logging to keep terminal tidy
        pass

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/health", "/healthz"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"status": "UP", "gnb": g_state.gnb_id}).encode("utf-8"))
            return

        snapshot = g_state.get_snapshot()

        if path == "/api/v1/query":
            # Prometheus vector format
            now_ts = snapshot["timestamp"]
            resp = {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {
                            "metric": {"__name__": "gnb_slice_throughput_bytes_sec", "slice": "eMBB"},
                            "value": [now_ts, str(int((snapshot["slices"]["eMBB"]["offered_demand_mbps"] * 1e6) / 8.0))],
                        },
                        {
                            "metric": {"__name__": "gnb_slice_throughput_bytes_sec", "slice": "URLLC"},
                            "value": [now_ts, str(int((snapshot["slices"]["URLLC"]["offered_demand_mbps"] * 1e6) / 8.0))],
                        },
                        {
                            "metric": {"__name__": "gnb_slice_throughput_bytes_sec", "slice": "mURLLC"},
                            "value": [now_ts, str(int((snapshot["slices"]["mURLLC"]["offered_demand_mbps"] * 1e6) / 8.0))],
                        },
                        {
                            "metric": {"__name__": "gnb_upf_bytes_total"},
                            "value": [now_ts, "1048576000"],
                        },
                    ],
                },
            }
            body = json.dumps(resp).encode("utf-8")
        elif path.startswith("/open5gs"):
            # Open5GS schema
            resp = {
                "active_sessions": snapshot["gnodeb"]["active_ues"],
                "slice_rates_mbps": {
                    "eMBB": snapshot["slices"]["eMBB"]["offered_demand_mbps"],
                    "URLLC": snapshot["slices"]["URLLC"]["offered_demand_mbps"],
                    "mURLLC": snapshot["slices"]["mURLLC"]["offered_demand_mbps"],
                },
                "subscribers": [],
            }
            body = json.dumps(resp).encode("utf-8")
        else:
            # Default Generic JSON schema
            body = json.dumps(snapshot, indent=2).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)


def main():
    port = 9090
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, GNodeBTelemetryHandler)
    logger.info("=================================================================")
    logger.info("📡 5G NR gNodeB Radio Access Network Telemetry Service Started")
    logger.info(f"   Cell ID: {g_state.cell_id} | Band: n78 (3.5 GHz) | 273 PRBs")
    logger.info(f"   Listening on: http://127.0.0.1:{port}/telemetry")
    logger.info("   Prometheus Vector Endpoint: http://127.0.0.1:9090/api/v1/query")
    logger.info("=================================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("5G gNodeB service stopping...")
        httpd.server_close()


if __name__ == "__main__":
    main()
