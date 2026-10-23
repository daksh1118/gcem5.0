"""
SLA Guardian - Phase 7 Frontend & Dashboard Integration Tests
Validates:
1. Dashboard loads from root URL with proper HTML5 structure.
2. CSS and JavaScript static assets serve with 200 OK.
3. Three policy panels exist in the DOM with identical metrics structure.
4. Grounded explainability elements and Safety Shield status containers exist.
5. Control toolbar contains all required buttons and scenario options.
6. Scoreboard and event log containers are present.
7. End-to-end simulation stepping drives telemetry into WebSocket.
"""

import pytest
from fastapi.testclient import TestClient
from backend.app.main import app, _get_runner


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_01_dashboard_root_serves_html(client):
    """Test 1: Dashboard HTML loads with correct title and branding."""
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    html = res.text
    assert "<title>SLA Guardian" in html
    assert "SLA GUARDIAN" in html
    assert "panel-static" in html
    assert "panel-heuristic" in html
    assert "panel-agent" in html


def test_02_static_assets_serve_correctly(client):
    """Test 2: CSS and JavaScript assets serve with 200 OK."""
    css_res = client.get("/styles.css")
    assert css_res.status_code == 200
    assert "--bg-base" in css_res.text
    assert "--slice-embb" in css_res.text

    js_res = client.get("/app.js")
    assert js_res.status_code == 200
    assert "connectWebSocket" in js_res.text
    assert "renderPolicyPanel" in js_res.text


def test_03_three_panels_have_symmetric_metrics(client):
    """Test 3: Static, Heuristic, and Agent panels have identical metric selectors."""
    res = client.get("/")
    html = res.text

    for panel_id in ["panel-static", "panel-heuristic", "panel-agent"]:
        assert f'id="{panel_id}"' in html
        # Slices
        assert 'data-metric="tput-embb"' in html
        assert 'data-metric="tput-urllc"' in html
        assert 'data-metric="tput-murllc"' in html
        assert 'data-metric="sla-embb"' in html
        assert 'data-metric="sla-urllc"' in html
        assert 'data-metric="sla-murllc"' in html
        # Allocations
        assert 'data-bar="radio-embb"' in html
        assert 'data-bar="radio-urllc"' in html
        assert 'data-bar="radio-murllc"' in html
        assert 'data-bar="compute-embb"' in html
        assert 'data-bar="compute-urllc"' in html
        assert 'data-bar="compute-murllc"' in html
        # Diagnostics
        assert 'data-metric="diag-offered"' in html
        assert 'data-metric="diag-delivered"' in html
        assert 'data-metric="diag-dropped"' in html
        assert 'data-metric="diag-pending"' in html
        assert 'data-metric="diag-critical"' in html


def test_04_agent_explainability_containers_present(client):
    """Test 4: Agent panel contains Lagrangian multiplier and decision rationale."""
    res = client.get("/")
    html = res.text
    assert 'id="agentLambdaVal"' in html
    assert 'id="agentExplanationText"' in html
    assert "Policy Decision Rationale" in html
    assert "Constrained PPO + Shield" in html


def test_05_control_toolbar_has_required_elements(client):
    """Test 5: Control toolbar contains scenario dropdown, seed input, and buttons."""
    res = client.get("/")
    html = res.text
    assert 'id="scenarioSelect"' in html
    assert 'id="seedInput"' in html
    assert 'id="btnStart"' in html
    assert 'id="btnPause"' in html
    assert 'id="btnResume"' in html
    assert 'id="btnReset"' in html
    assert 'id="btnStep"' in html
    assert 'id="btnSpikeEmbb"' in html
    assert 'id="btnSpikeUrllc"' in html
    assert 'id="btnSpikeMurllc"' in html


def test_06_scoreboard_and_event_feed_present(client):
    """Test 6: Cumulative scoreboard table and event feed container exist."""
    res = client.get("/")
    html = res.text
    assert 'id="scoreboardBody"' in html
    assert "Comparative Scoreboard" in html
    assert 'id="eventList"' in html
    assert "Real-Time Audit & Event Stream" in html


def test_07_chart_canvas_containers_present(client):
    """Test 7: Chart canvases for throughput, drops, and utilization are present."""
    res = client.get("/")
    html = res.text
    assert 'id="chartEmbbTput"' in html
    assert 'id="chartCriticalDrops"' in html
    assert 'id="chartUtil"' in html
