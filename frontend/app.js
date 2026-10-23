/**
 * SLA GUARDIAN - CLIENT APPLICATION LOGIC
 * Connects to FastAPI REST endpoints and WebSocket /ws.
 * Coordinates 3-policy live dashboard rendering, controls, Chart.js graphs,
 * and grounded decision explainability.
 */

// Global Application State
const state = {
  connected: false,
  modelLoaded: false,
  modelPath: "",
  activeScenario: "normal",
  seed: 42,
  currentMacroStep: 0,
  simTimeSec: 0.0,
  runStatus: "idle",
  lastSequenceNumber: -1,
  scenarios: [],
  activeSpike: null,

  // Historical series for charts (bounded to last 50 steps)
  history: {
    steps: [],
    embbTput: { static: [], heuristic: [], agent: [] },
    criticalDrops: { static: [], heuristic: [], agent: [] },
    radioUtil: { static: [], heuristic: [], agent: [] },
    lambda: [],
  },

  events: [],
  charts: {},
};

// Color Palette Constants
const COLORS = {
  embb: "#3B82F6",
  urllc: "#14B8A6",
  murllc: "#F59E0B",
  static: "#9CA3AF",
  heuristic: "#34D399",
  agent: "#60A5FA",
  breach: "#EF4444",
  pass: "#10B981",
  warn: "#F59E0B",
};

// API Base URL (auto-detects same origin or defaults to localhost:8000)
const API_BASE = window.location.origin.startsWith("http")
  ? window.location.origin
  : "http://127.0.0.1:8000";

const WS_BASE = API_BASE.replace(/^http/, "ws");

let ws = null;
let reconnectTimer = null;

// ==========================================================================
// Initialization
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
  initCharts();
  fetchHealth();
  fetchScenarios();
  connectWebSocket();
  setupEventListeners();
});

// ==========================================================================
// REST API Calls
// ==========================================================================
async function fetchHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    const data = await res.json();
    state.modelLoaded = data.model_loaded;
    state.modelPath = data.model_path || "";
    updateSystemStatus(data);
  } catch (err) {
    console.warn("Error fetching health:", err);
    updateConnectionIndicator(false);
  }
}

async function fetchScenarios() {
  try {
    const res = await fetch(`${API_BASE}/api/scenarios`);
    const data = await res.json();
    state.scenarios = data.scenarios || [];
    populateScenarioDropdown();
  } catch (err) {
    console.warn("Error fetching scenarios:", err);
  }
}

async function startRun() {
  const scenarioSelect = document.getElementById("scenarioSelect");
  const seedInput = document.getElementById("seedInput");
  const maxStepsInput = document.getElementById("maxStepsInput");

  const payload = {
    scenario: scenarioSelect ? scenarioSelect.value : state.activeScenario,
    seed: seedInput ? parseInt(seedInput.value, 10) : 42,
    max_macro_steps: maxStepsInput ? parseInt(maxStepsInput.value, 10) : 100,
    selected_policies: ["static", "heuristic", "agent"],
  };

  try {
    const res = await fetch(`${API_BASE}/api/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      alert(`Failed to start run: ${err.detail || res.statusText}`);
      return;
    }
    const data = await res.json();
    addEvent(`Experiment started: ${data.scenario} (seed=${data.seed})`, "info");
    resetChartHistory();
    fetchSummary();
  } catch (err) {
    console.error("Start run failed:", err);
  }
}

async function pauseRun() {
  try {
    const res = await fetch(`${API_BASE}/api/pause`, { method: "POST" });
    const data = await res.json();
    addEvent(`Simulation paused at macro-step ${data.macro_step}`, "warn");
  } catch (err) {
    console.error("Pause failed:", err);
  }
}

async function resumeRun() {
  try {
    const res = await fetch(`${API_BASE}/api/resume`, { method: "POST" });
    const data = await res.json();
    addEvent(`Simulation resumed`, "info");
  } catch (err) {
    console.error("Resume failed:", err);
  }
}

async function resetExperiment() {
  const scenarioSelect = document.getElementById("scenarioSelect");
  const seedInput = document.getElementById("seedInput");

  const payload = {
    scenario: scenarioSelect ? scenarioSelect.value : state.activeScenario,
    seed: seedInput ? parseInt(seedInput.value, 10) : 42,
  };

  try {
    const res = await fetch(`${API_BASE}/api/reset`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    resetChartHistory();
    addEvent(`Simulation reset to step 0`, "info");
    fetchSummary();
  } catch (err) {
    console.error("Reset failed:", err);
  }
}

async function triggerSpike(targetSlice, multiplier, durationSteps) {
  const payload = {
    target_slice: targetSlice,
    multiplier: parseFloat(multiplier),
    duration_steps: parseInt(durationSteps, 10),
  };

  try {
    const res = await fetch(`${API_BASE}/api/spike`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      alert(`Spike rejected: ${err.detail || res.statusText}`);
      return;
    }
    const data = await res.json();
    addEvent(
      `⚡ Spike Injected: ${data.target_slice} surge x${data.multiplier} for ${data.duration_steps} steps`,
      "warn"
    );
  } catch (err) {
    console.error("Spike injection failed:", err);
  }
}

async function triggerSingleStep() {
  try {
    const res = await fetch(`${API_BASE}/api/step`, { method: "POST" });
    const data = await res.json();
    handleTelemetryEvent(data);
  } catch (err) {
    console.error("Single step failed:", err);
  }
}

async function fetchSummary() {
  try {
    const res = await fetch(`${API_BASE}/api/summary`);
    if (!res.ok) return;
    const summary = await res.json();
    renderScoreboard(summary);
  } catch (err) {
    console.warn("Summary fetch error:", err);
  }
}

// ==========================================================================
// WebSocket Telemetry Streaming
// ==========================================================================
function connectWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const wsUrl = `${WS_BASE}/ws`;
  console.log(`Connecting to WebSocket: ${wsUrl}`);
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log("WebSocket connected.");
    updateConnectionIndicator(true);
    if (reconnectTimer) {
      clearInterval(reconnectTimer);
      reconnectTimer = null;
    }
  };

  ws.onmessage = (event) => {
    try {
      if (event.data === "pong") return;
      const data = JSON.parse(event.data);
      handleTelemetryEvent(data);
    } catch (e) {
      console.warn("Error parsing telemetry event:", e);
    }
  };

  ws.onerror = (err) => {
    console.warn("WebSocket error:", err);
    updateConnectionIndicator(false);
  };

  ws.onclose = () => {
    console.log("WebSocket disconnected. Reconnecting in 3s...");
    updateConnectionIndicator(false);
    if (!reconnectTimer) {
      reconnectTimer = setInterval(connectWebSocket, 3000);
    }
  };
}

// ==========================================================================
// Telemetry Event Handler
// ==========================================================================
function handleTelemetryEvent(evt) {
  if (!evt || !evt.policies) return;

  // Handle sequence ordering
  if (evt.sequence_number !== undefined && evt.sequence_number < state.lastSequenceNumber) {
    // Stale or duplicate packet; skip
    return;
  }
  state.lastSequenceNumber = evt.sequence_number || state.lastSequenceNumber + 1;

  state.currentMacroStep = evt.macro_step || 0;
  state.simTimeSec = evt.sim_time_sec || 0.0;
  state.runStatus = evt.run_status || "running";
  state.activeScenario = evt.active_scenario || state.activeScenario;

  updateRunStatusHeader();

  // Render the Three Policy Panels
  const policies = evt.policies;
  if (policies.static) renderPolicyPanel("static", policies.static);
  if (policies.heuristic) renderPolicyPanel("heuristic", policies.heuristic);
  if (policies.agent) renderPolicyPanel("agent", policies.agent);

  // Update Agent Explainability & Lambda
  if (policies.agent) {
    updateAgentInsights(policies.agent);
  }

  // Update Charts History
  updateChartData(evt);

  // Periodically update summary scoreboard
  if (state.currentMacroStep % 5 === 0) {
    fetchSummary();
  }
}

// ==========================================================================
// Policy Panel Rendering
// ==========================================================================
function renderPolicyPanel(key, pData) {
  const panel = document.getElementById(`panel-${key}`);
  if (!panel) return;

  // 1. Throughput & SLA Status
  const tput = pData.delivered_tput_mbps || {};
  const p95 = pData.p95_latency_ms || {};
  const slaStatus = pData.sla_status || {};
  const slaDetails = pData.sla_state_details || {};

  ["embb", "urllc", "murllc"].forEach((sLower) => {
    const sId = sLower === "embb" ? "eMBB" : sLower === "urllc" ? "URLLC" : "mURLLC";
    const tputEl = panel.querySelector(`[data-metric="tput-${sLower}"]`);
    if (tputEl) tputEl.textContent = `${(tput[sId] || 0.0).toFixed(1)} Mbps`;

    const latEl = panel.querySelector(`[data-metric="lat-${sLower}"]`);
    if (latEl) {
      const latVal = p95[sId];
      latEl.textContent = latVal !== null && latVal !== undefined ? `${latVal.toFixed(1)} ms` : "No data";
    }

    const slaPill = panel.querySelector(`[data-metric="sla-${sLower}"]`);
    if (slaPill) {
      const detail = slaDetails[sId] || "PASS";
      slaPill.className = "sla-pill";
      if (detail === "PASS") {
        slaPill.classList.add("pass");
        slaPill.textContent = "PASS";
      } else if (detail === "BREACH") {
        slaPill.classList.add("breach");
        slaPill.textContent = "BREACH";
      } else {
        slaPill.classList.add("insufficient");
        slaPill.textContent = "NO DATA";
      }
    }
  });

  // 2. Resource Allocations (Radio & Compute Stacked Bars)
  const rAlloc = pData.radio_allocations || {};
  const cAlloc = pData.compute_allocations || {};

  const rTotal = Math.max(1, (rAlloc.eMBB || 0) + (rAlloc.URLLC || 0) + (rAlloc.mURLLC || 0));
  const cTotal = Math.max(1, (cAlloc.eMBB || 0) + (cAlloc.URLLC || 0) + (cAlloc.mURLLC || 0));

  setBarWidth(panel, "radio-embb", ((rAlloc.eMBB || 0) / rTotal) * 100);
  setBarWidth(panel, "radio-urllc", ((rAlloc.URLLC || 0) / rTotal) * 100);
  setBarWidth(panel, "radio-murllc", ((rAlloc.mURLLC || 0) / rTotal) * 100);

  setBarWidth(panel, "compute-embb", ((cAlloc.eMBB || 0) / cTotal) * 100);
  setBarWidth(panel, "compute-urllc", ((cAlloc.URLLC || 0) / cTotal) * 100);
  setBarWidth(panel, "compute-murllc", ((cAlloc.mURLLC || 0) / cTotal) * 100);

  // Bar labels
  setText(panel, "r-embb-val", `${(rAlloc.eMBB || 0).toFixed(1)}%`);
  setText(panel, "r-urllc-val", `${(rAlloc.URLLC || 0).toFixed(1)}%`);
  setText(panel, "r-murllc-val", `${(rAlloc.mURLLC || 0).toFixed(1)}%`);

  setText(panel, "c-embb-val", `${(cAlloc.eMBB || 0).toFixed(1)}%`);
  setText(panel, "c-urllc-val", `${(cAlloc.URLLC || 0).toFixed(1)}%`);
  setText(panel, "c-murllc-val", `${(cAlloc.mURLLC || 0).toFixed(1)}%`);

  // 3. Diagnostics (Packets, Queues, Violations)
  const offered = pData.offered_packets || {};
  const delivered = pData.delivered_packets || {};
  const dropped = pData.dropped_packets || {};
  const pending = pData.pending_packets || {};

  const totOffered = (offered.eMBB || 0) + (offered.URLLC || 0) + (offered.mURLLC || 0);
  const totDelivered = (delivered.eMBB || 0) + (delivered.URLLC || 0) + (delivered.mURLLC || 0);
  const totDropped = (dropped.eMBB || 0) + (dropped.URLLC || 0) + (dropped.mURLLC || 0);
  const totPending = (pending.eMBB || 0) + (pending.URLLC || 0) + (pending.mURLLC || 0);

  setText(panel, "diag-offered", totOffered);
  setText(panel, "diag-delivered", totDelivered);
  setText(panel, "diag-dropped", totDropped);
  setText(panel, "diag-pending", totPending);

  // Critical Violations count
  const critViol = pData.critical_violations || 0;
  const critEl = panel.querySelector(`[data-metric="diag-critical"]`);
  if (critEl) {
    critEl.textContent = critViol;
    critEl.className = "diag-val" + (critViol > 0 ? " breach" : "");
  }

  // 4. Safety Shield Status
  const shieldBanner = panel.querySelector(".shield-banner");
  if (shieldBanner) {
    const sStat = (pData.shield_status || "PASSED").toLowerCase();
    shieldBanner.className = `shield-banner ${sStat}`;
    const txt = shieldBanner.querySelector(".shield-status-text");
    if (txt) {
      if (sStat === "corrected") {
        txt.textContent = "SHIELD INTERVENED (Corrected)";
      } else if (sStat === "rejected") {
        txt.textContent = "SHIELD BLOCKED (Rejected)";
      } else {
        txt.textContent = "SHIELD VERIFIED (Passed)";
      }
    }
  }
}

function setBarWidth(panel, attr, percent) {
  const el = panel.querySelector(`[data-bar="${attr}"]`);
  if (el) el.style.width = `${Math.max(0, Math.min(100, percent))}%`;
}

function setText(panel, attr, text) {
  const el = panel.querySelector(`[data-metric="${attr}"]`);
  if (el) el.textContent = text;
}

// ==========================================================================
// Agent Insights & Explainability
// ==========================================================================
function updateAgentInsights(agentData) {
  const lambdaEl = document.getElementById("agentLambdaVal");
  if (lambdaEl && agentData.lagrangian_lambda !== undefined && agentData.lagrangian_lambda !== null) {
    lambdaEl.textContent = `λ = ${agentData.lagrangian_lambda.toFixed(3)}`;
  }

  const costEl = document.getElementById("agentCostVal");
  if (costEl && agentData.critical_cost !== undefined && agentData.critical_cost !== null) {
    costEl.textContent = `Cost: ${agentData.critical_cost.toFixed(4)}`;
  }

  const explanationEl = document.getElementById("agentExplanationText");
  if (explanationEl && agentData.explanation) {
    explanationEl.textContent = `"${agentData.explanation}"`;
  }
}

// ==========================================================================
// Chart.js Live Synchronization
// ==========================================================================
function initCharts() {
  const commonOptions = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    scales: {
      x: {
        grid: { color: "#1F2E45" },
        ticks: { color: "#91A0B7", font: { size: 10 } },
      },
      y: {
        grid: { color: "#1F2E45" },
        ticks: { color: "#91A0B7", font: { size: 10 } },
      },
    },
    plugins: {
      legend: {
        position: "top",
        labels: { color: "#E5EDF7", font: { size: 10, weight: 600 }, boxWidth: 10 },
      },
    },
  };

  // 1. eMBB Throughput Chart
  const ctxTput = document.getElementById("chartEmbbTput");
  if (ctxTput && typeof Chart !== "undefined") {
    state.charts.tput = new Chart(ctxTput, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          { label: "Static", data: [], borderColor: COLORS.static, borderWidth: 1.5, pointRadius: 0 },
          { label: "Heuristic", data: [], borderColor: COLORS.heuristic, borderWidth: 1.5, pointRadius: 0 },
          { label: "PPO Agent", data: [], borderColor: COLORS.agent, borderWidth: 2.2, pointRadius: 0 },
        ],
      },
      options: {
        ...commonOptions,
        scales: {
          ...commonOptions.scales,
          y: { ...commonOptions.scales.y, title: { display: true, text: "Mbps", color: "#91A0B7", font: { size: 10 } } },
        },
      },
    });
  }

  // 2. Critical Packet Drops Chart
  const ctxDrops = document.getElementById("chartCriticalDrops");
  if (ctxDrops && typeof Chart !== "undefined") {
    state.charts.drops = new Chart(ctxDrops, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          { label: "Static", data: [], borderColor: COLORS.static, borderWidth: 1.5, pointRadius: 0 },
          { label: "Heuristic", data: [], borderColor: COLORS.heuristic, borderWidth: 1.5, pointRadius: 0 },
          { label: "PPO Agent", data: [], borderColor: COLORS.agent, borderWidth: 2.2, pointRadius: 0 },
        ],
      },
      options: {
        ...commonOptions,
        scales: {
          ...commonOptions.scales,
          y: { ...commonOptions.scales.y, title: { display: true, text: "Dropped Packets", color: "#91A0B7", font: { size: 10 } } },
        },
      },
    });
  }

  // 3. Resource Utilization Chart
  const ctxUtil = document.getElementById("chartUtil");
  if (ctxUtil && typeof Chart !== "undefined") {
    state.charts.util = new Chart(ctxUtil, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          { label: "Static Radio", data: [], borderColor: "#64748B", borderDash: [4, 4], borderWidth: 1.2, pointRadius: 0 },
          { label: "Heuristic Radio", data: [], borderColor: "#10B981", borderDash: [4, 4], borderWidth: 1.2, pointRadius: 0 },
          { label: "PPO Agent Radio", data: [], borderColor: "#3B82F6", borderWidth: 2.0, pointRadius: 0 },
        ],
      },
      options: {
        ...commonOptions,
        scales: {
          ...commonOptions.scales,
          y: {
            ...commonOptions.scales.y,
            min: 0,
            max: 100,
            title: { display: true, text: "% Utilized", color: "#91A0B7", font: { size: 10 } },
          },
        },
      },
    });
  }
}

function updateChartData(evt) {
  const step = evt.macro_step || 0;
  const p = evt.policies;
  if (!p) return;

  const MAX_HISTORY = 40;
  const labels = state.charts.tput ? state.charts.tput.data.labels : [];

  labels.push(`t=${step}`);
  if (labels.length > MAX_HISTORY) labels.shift();

  // 1. Throughput Chart
  if (state.charts.tput) {
    const sT = p.static ? p.static.delivered_tput_mbps.eMBB || 0 : 0;
    const hT = p.heuristic ? p.heuristic.delivered_tput_mbps.eMBB || 0 : 0;
    const aT = p.agent ? p.agent.delivered_tput_mbps.eMBB || 0 : 0;

    pushData(state.charts.tput, 0, sT, MAX_HISTORY);
    pushData(state.charts.tput, 1, hT, MAX_HISTORY);
    pushData(state.charts.tput, 2, aT, MAX_HISTORY);
    state.charts.tput.update();
  }

  // 2. Drops Chart
  if (state.charts.drops) {
    const sD = p.static ? (p.static.dropped_packets.URLLC || 0) + (p.static.dropped_packets.mURLLC || 0) : 0;
    const hD = p.heuristic ? (p.heuristic.dropped_packets.URLLC || 0) + (p.heuristic.dropped_packets.mURLLC || 0) : 0;
    const aD = p.agent ? (p.agent.dropped_packets.URLLC || 0) + (p.agent.dropped_packets.mURLLC || 0) : 0;

    pushData(state.charts.drops, 0, sD, MAX_HISTORY);
    pushData(state.charts.drops, 1, hD, MAX_HISTORY);
    pushData(state.charts.drops, 2, aD, MAX_HISTORY);
    state.charts.drops.update();
  }

  // 3. Utilization Chart
  if (state.charts.util) {
    const sR = p.static ? ((p.static.radio_allocations.eMBB || 0) + (p.static.radio_allocations.URLLC || 0) + (p.static.radio_allocations.mURLLC || 0)) : 0;
    const hR = p.heuristic ? ((p.heuristic.radio_allocations.eMBB || 0) + (p.heuristic.radio_allocations.URLLC || 0) + (p.heuristic.radio_allocations.mURLLC || 0)) : 0;
    const aR = p.agent ? ((p.agent.radio_allocations.eMBB || 0) + (p.agent.radio_allocations.URLLC || 0) + (p.agent.radio_allocations.mURLLC || 0)) : 0;

    pushData(state.charts.util, 0, sR, MAX_HISTORY);
    pushData(state.charts.util, 1, hR, MAX_HISTORY);
    pushData(state.charts.util, 2, aR, MAX_HISTORY);
    state.charts.util.update();
  }
}

function pushData(chart, datasetIdx, val, maxLen) {
  const d = chart.data.datasets[datasetIdx].data;
  d.push(val);
  if (d.length > maxLen) d.shift();
}

function resetChartHistory() {
  Object.values(state.charts).forEach((chart) => {
    chart.data.labels = [];
    chart.data.datasets.forEach((ds) => {
      ds.data = [];
    });
    chart.update();
  });
}

// ==========================================================================
// Scoreboard Rendering
// ==========================================================================
function renderScoreboard(summary) {
  if (!summary) return;

  const rows = [
    { key: "static", label: "Static Baseline", color: COLORS.static },
    { key: "heuristic", label: "Adaptive Heuristic", color: COLORS.heuristic },
    { key: "agent", label: "PPO SLA Guardian", color: COLORS.agent },
  ];

  const tbody = document.getElementById("scoreboardBody");
  if (!tbody) return;

  tbody.innerHTML = rows
    .map((r) => {
      const data = summary[r.key] || {};
      return `
      <tr>
        <td class="policy-cell" style="color: ${r.color}">${r.label}</td>
        <td>${(data.mean_embb_tput_mbps || 0).toFixed(1)}</td>
        <td class="${data.critical_violations > 0 ? 'text-breach' : ''}">${data.critical_violations || 0}</td>
        <td>${((data.mean_radio_utilization || 0) * 100).toFixed(1)}%</td>
        <td>${(data.total_churn || 0).toFixed(0)}</td>
        <td>${data.shield_interventions || 0}</td>
      </tr>
    `;
    })
    .join("");
}

// ==========================================================================
// UI Helpers & Event Listeners
// ==========================================================================
function updateConnectionIndicator(connected) {
  state.connected = connected;
  const beacon = document.getElementById("liveBeacon");
  const connText = document.getElementById("connStatusText");

  if (beacon) {
    beacon.className = "live-beacon" + (connected ? "" : " disconnected");
  }
  if (connText) {
    connText.textContent = connected ? "CONNECTED" : "DISCONNECTED";
  }
}

function updateSystemStatus(data) {
  const modelBadge = document.getElementById("modelBadge");
  if (modelBadge) {
    if (data.model_loaded) {
      modelBadge.className = "status-badge healthy";
      modelBadge.textContent = "PPO LOADED";
    } else {
      modelBadge.className = "status-badge degraded";
      modelBadge.textContent = "DEGRADED";
      addEvent(`Model degraded: ${data.model_error || "agent.zip missing"}`, "breach");
    }
  }
}

function updateRunStatusHeader() {
  const runBadge = document.getElementById("runStatusBadge");
  if (runBadge) {
    runBadge.className = `status-badge ${state.runStatus.toLowerCase()}`;
    runBadge.textContent = state.runStatus.toUpperCase();
  }

  const stepEl = document.getElementById("currentMacroStep");
  if (stepEl) stepEl.textContent = state.currentMacroStep;

  const timeEl = document.getElementById("simTimeSec");
  if (timeEl) timeEl.textContent = `${state.simTimeSec.toFixed(2)}s`;
}

function populateScenarioDropdown() {
  const sel = document.getElementById("scenarioSelect");
  if (!sel) return;
  sel.innerHTML = state.scenarios
    .map((sc) => `<option value="${sc.id}">${sc.id.toUpperCase()} - ${sc.description}</option>`)
    .join("");
}

function addEvent(msg, type = "info") {
  const list = document.getElementById("eventList");
  if (!list) return;

  const timeStr = new Date().toLocaleTimeString();
  const div = document.createElement("div");
  div.className = `event-item ${type}`;
  div.innerHTML = `
    <span class="event-time">[${timeStr}]</span>
    <span class="event-msg">${msg}</span>
  `;

  list.prepend(div);
  while (list.children.length > 30) {
    list.removeChild(list.lastChild);
  }
}

function setupEventListeners() {
  // Run Controls
  const btnStart = document.getElementById("btnStart");
  if (btnStart) btnStart.addEventListener("click", startRun);

  const btnPause = document.getElementById("btnPause");
  if (btnPause) btnPause.addEventListener("click", pauseRun);

  const btnResume = document.getElementById("btnResume");
  if (btnResume) btnResume.addEventListener("click", resumeRun);

  const btnReset = document.getElementById("btnReset");
  if (btnReset) btnReset.addEventListener("click", resetExperiment);

  const btnStep = document.getElementById("btnStep");
  if (btnStep) btnStep.addEventListener("click", triggerSingleStep);

  // Quick Spikes
  const btnSpikeEmbb = document.getElementById("btnSpikeEmbb");
  if (btnSpikeEmbb) {
    btnSpikeEmbb.addEventListener("click", () => triggerSpike("eMBB", 2.0, 20));
  }

  const btnSpikeUrllc = document.getElementById("btnSpikeUrllc");
  if (btnSpikeUrllc) {
    btnSpikeUrllc.addEventListener("click", () => triggerSpike("URLLC", 4.0, 20));
  }

  const btnSpikeMurllc = document.getElementById("btnSpikeMurllc");
  if (btnSpikeMurllc) {
    btnSpikeMurllc.addEventListener("click", () => triggerSpike("mURLLC", 3.0, 20));
  }

  // Chart Tabs Switching
  const tabTput = document.getElementById("tabTput");
  const tabDrops = document.getElementById("tabDrops");
  const tabUtil = document.getElementById("tabUtil");

  const wrapTput = document.getElementById("wrapTput");
  const wrapDrops = document.getElementById("wrapDrops");
  const wrapUtil = document.getElementById("wrapUtil");

  if (tabTput && tabDrops && tabUtil) {
    tabTput.addEventListener("click", () => {
      setActiveTab(tabTput, wrapTput, [tabDrops, tabUtil], [wrapDrops, wrapUtil]);
    });
    tabDrops.addEventListener("click", () => {
      setActiveTab(tabDrops, wrapDrops, [tabTput, tabUtil], [wrapTput, wrapUtil]);
    });
    tabUtil.addEventListener("click", () => {
      setActiveTab(tabUtil, wrapUtil, [tabTput, tabDrops], [wrapTput, wrapDrops]);
    });
  }
}

function setActiveTab(activeTab, activeWrap, otherTabs, otherWraps) {
  activeTab.classList.add("active");
  activeWrap.style.display = "block";
  otherTabs.forEach((t) => t.classList.remove("active"));
  otherWraps.forEach((w) => (w.style.display = "none"));
}
