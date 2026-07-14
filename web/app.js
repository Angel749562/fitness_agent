const state = {
  sessionId: null,
  socket: null,
  workoutStartedAt: null,
  workoutFinishedAt: null,
  durationTimer: null,
  hrSeries: [],
};

const reasonLabels = {
  heart_rate_high: "心率过高",
  heart_rate_low: "心率偏低",
  cadence_low: "步频偏低",
  session_stopped: "训练已停止",
  stop_requested: "正在结束训练",
  stopping: "正在结束训练",
  stopped: "训练已停止",
  running: "训练中",
  completed: "已完成",
};

const reasonTones = {
  heart_rate_high: "danger",
  heart_rate_low: "warn",
  cadence_low: "warn",
};

const eventLabels = {
  session_snapshot: "会话快照",
  session_started: "会话开始",
  step_started: "步骤开始",
  llm_output: "训练后解释",
  action: "动作",
  observation: "观察结果",
  heart_rate_sample: "实时指标",
  advice_event: "实时建议",
  session_summary: "训练总结",
  final: "训练完成",
  error: "错误",
  stopped: "已停止",
  websocket: "实时连接",
  stop: "结束训练",
};

function labelReason(reason, fallback = "实时建议") {
  return reasonLabels[reason] || reason || fallback;
}

function labelEvent(type) {
  return eventLabels[type] || type;
}

function sessionLabel(id) {
  return id ? `训练会话：${id}` : "尚未创建会话";
}

const elements = {
  statusBadge: document.getElementById("statusBadge"),
  statusText: document.getElementById("statusText"),
  sessionId: document.getElementById("sessionId"),
  promptInput: document.getElementById("promptInput"),
  demoInput: document.getElementById("demoInput"),
  ticksInput: document.getElementById("ticksInput"),
  delayInput: document.getElementById("delayInput"),
  startButton: document.getElementById("startButton"),
  stopButton: document.getElementById("stopButton"),
  heartRateCard: document.getElementById("heartRateCard"),
  heartRate: document.getElementById("heartRate"),
  targetRange: document.getElementById("targetRange"),
  trainingZone: document.getElementById("trainingZone"),
  zoneState: document.getElementById("zoneState"),
  pace: document.getElementById("pace"),
  cadence: document.getElementById("cadence"),
  duration: document.getElementById("duration"),
  adviceReason: document.getElementById("adviceReason"),
  latestAdvice: document.getElementById("latestAdvice"),
  progressText: document.getElementById("progressText"),
  progressBar: document.getElementById("progressBar"),
  progressPct: document.getElementById("progressPct"),
  summaryStatus: document.getElementById("summaryStatus"),
  summaryText: document.getElementById("summaryText"),
  averageHr: document.getElementById("averageHr"),
  peakHr: document.getElementById("peakHr"),
  inZonePct: document.getElementById("inZonePct"),
  corrections: document.getElementById("corrections"),
  samples: document.getElementById("samples"),
  eventLog: document.getElementById("eventLog"),
  eventLogEmpty: document.getElementById("eventLogEmpty"),
  eventCount: document.getElementById("eventCount"),
  clearLogButton: document.getElementById("clearLogButton"),
  hrChart: document.getElementById("hrChart"),
  chartWrap: document.getElementById("chartWrap"),
  chartEmpty: document.getElementById("chartEmpty"),
  chartTooltip: document.getElementById("chartTooltip"),
};

function setStatus(text, variant = "idle") {
  elements.statusText.textContent = text;
  elements.statusBadge.className = `status-badge ${variant}`;
  elements.heartRateCard.classList.toggle("live", variant === "running");
  document.body.dataset.sessionState = variant;
  document.title = variant === "running" ? `训练中 · Fitness Agent` : "Fitness Agent · 智能训练看板";
}

function setChip(el, text, tone = "") {
  el.textContent = text;
  el.className = `chip${tone ? ` ${tone}` : ""}`;
}

function appendLog(type, text = "") {
  const item = document.createElement("li");

  const time = document.createElement("span");
  time.className = "log-time";
  time.textContent = new Date().toLocaleTimeString();

  const kind = document.createElement("span");
  kind.className = "log-type";
  kind.textContent = labelEvent(type);

  item.append(time, kind);

  if (text) {
    const body = document.createElement("span");
    body.textContent = labelReason(text, text);
    item.append(body);
  }

  elements.eventLog.prepend(item);
  elements.eventLogEmpty.style.display = "none";

  while (elements.eventLog.children.length > 60) {
    elements.eventLog.lastElementChild.remove();
  }
  if (elements.eventCount) {
    elements.eventCount.textContent = elements.eventLog.children.length;
  }
}

function formatDuration(ms) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
  const remainder = String(seconds % 60).padStart(2, "0");
  return `${minutes}:${remainder}`;
}

function renderDuration() {
  if (!state.workoutStartedAt) {
    elements.duration.textContent = "00:00";
    return;
  }

  const end = state.workoutFinishedAt || new Date();
  elements.duration.textContent = formatDuration(end - state.workoutStartedAt);
}

function startDurationTimer() {
  if (state.durationTimer) {
    return;
  }
  state.durationTimer = window.setInterval(renderDuration, 1000);
}

function stopDurationTimer() {
  if (state.durationTimer) {
    window.clearInterval(state.durationTimer);
    state.durationTimer = null;
  }
  renderDuration();
}

/* ---------- heart-rate chart ---------- */

const chart = {
  width: 720,
  height: 200,
  pad: {top: 16, right: 12, bottom: 22, left: 40},
};

const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(name, attrs = {}) {
  const el = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    el.setAttribute(key, value);
  }
  return el;
}

function chartScales() {
  const points = state.hrSeries;
  const values = points.map((p) => p.hr);
  for (const p of points) {
    if (p.low) values.push(p.low);
    if (p.high) values.push(p.high);
  }
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    min = 60;
    max = 180;
  }
  const span = Math.max(10, max - min);
  min = Math.floor((min - span * 0.12) / 10) * 10;
  max = Math.ceil((max + span * 0.12) / 10) * 10;

  const innerW = chart.width - chart.pad.left - chart.pad.right;
  const innerH = chart.height - chart.pad.top - chart.pad.bottom;
  const denom = Math.max(1, points.length - 1);

  return {
    x: (i) => chart.pad.left + (i / denom) * innerW,
    y: (v) => chart.pad.top + (1 - (v - min) / (max - min)) * innerH,
    min,
    max,
  };
}

function renderChart() {
  const svg = elements.hrChart;
  svg.textContent = "";
  const points = state.hrSeries;

  elements.chartEmpty.style.display = points.length ? "none" : "flex";
  if (!points.length) {
    return;
  }

  const {x, y, min, max} = chartScales();

  const gridSteps = 4;
  for (let i = 0; i <= gridSteps; i += 1) {
    const value = min + ((max - min) / gridSteps) * i;
    const gy = y(value);
    svg.append(svgEl("line", {
      x1: chart.pad.left,
      x2: chart.width - chart.pad.right,
      y1: gy,
      y2: gy,
      stroke: "#e5e5ea",
      "stroke-width": 1,
    }));
    const tick = svgEl("text", {
      x: chart.pad.left - 8,
      y: gy + 3.5,
      "text-anchor": "end",
      fill: "#8e8e93",
      "font-size": 10,
      "font-family": "system-ui, sans-serif",
    });
    tick.textContent = Math.round(value);
    svg.append(tick);
  }

  const banded = points.filter((p) => p.low && p.high);
  if (banded.length > 1) {
    const upper = points.map((p, i) => `${x(i)},${y(p.high || p.hr)}`);
    const lower = points.map((p, i) => `${x(i)},${y(p.low || p.hr)}`).reverse();
    svg.append(svgEl("polygon", {
      points: [...upper, ...lower].join(" "),
      fill: "rgba(48, 209, 88, 0.10)",
    }));
  }

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p.hr)}`)
    .join(" ");
  svg.append(svgEl("path", {
    d: linePath,
    fill: "none",
    stroke: "#ff375f",
    "stroke-width": 2.6,
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  }));

  const last = points[points.length - 1];
  const lastIdx = points.length - 1;
  svg.append(svgEl("circle", {
    cx: x(lastIdx),
    cy: y(last.hr),
    r: 4.5,
    fill: "#ff375f",
    stroke: "#ffffff",
    "stroke-width": 2,
  }));

  const crosshair = svgEl("line", {
    y1: chart.pad.top,
    y2: chart.height - chart.pad.bottom,
    stroke: "#c7c7cc",
    "stroke-width": 1,
    visibility: "hidden",
  });
  crosshair.id = "chartCrosshair";
  svg.append(crosshair);

  const hoverDot = svgEl("circle", {
    r: 4.5,
    fill: "#ff375f",
    stroke: "#ffffff",
    "stroke-width": 2,
    visibility: "hidden",
  });
  hoverDot.id = "chartHoverDot";
  svg.append(hoverDot);
}

function hideTooltip() {
  elements.chartTooltip.style.display = "none";
  const crosshair = document.getElementById("chartCrosshair");
  const hoverDot = document.getElementById("chartHoverDot");
  if (crosshair) crosshair.setAttribute("visibility", "hidden");
  if (hoverDot) hoverDot.setAttribute("visibility", "hidden");
}

function handleChartHover(event) {
  const points = state.hrSeries;
  if (points.length < 2) {
    return;
  }

  const rect = elements.hrChart.getBoundingClientRect();
  const relX = ((event.clientX - rect.left) / rect.width) * chart.width;
  const {x, y} = chartScales();
  const innerW = chart.width - chart.pad.left - chart.pad.right;
  const idx = Math.round(((relX - chart.pad.left) / innerW) * (points.length - 1));
  const clamped = Math.max(0, Math.min(points.length - 1, idx));
  const point = points[clamped];

  const crosshair = document.getElementById("chartCrosshair");
  const hoverDot = document.getElementById("chartHoverDot");
  if (!crosshair || !hoverDot) {
    return;
  }
  const px = x(clamped);
  crosshair.setAttribute("x1", px);
  crosshair.setAttribute("x2", px);
  crosshair.setAttribute("visibility", "visible");
  hoverDot.setAttribute("cx", px);
  hoverDot.setAttribute("cy", y(point.hr));
  hoverDot.setAttribute("visibility", "visible");

  const tt = elements.chartTooltip;
  tt.textContent = "";

  const value = document.createElement("div");
  value.className = "tt-value";
  value.textContent = `${point.hr} 次/分`;
  tt.append(value);

  if (point.low && point.high) {
    const row = document.createElement("div");
    row.className = "tt-row";
    const key = document.createElement("span");
    key.className = "tt-key band";
    row.append(key, document.createTextNode(`目标 ${point.low}-${point.high}`));
    tt.append(row);
  }

  const idxRow = document.createElement("div");
  idxRow.className = "tt-row";
  idxRow.textContent = `采样 #${point.index}`;
  tt.append(idxRow);

  tt.style.display = "block";
  const wrapRect = elements.chartWrap.getBoundingClientRect();
  const pxScreen = (px / chart.width) * rect.width + (rect.left - wrapRect.left);
  const flip = pxScreen > wrapRect.width - 150;
  tt.style.left = flip ? `${pxScreen - tt.offsetWidth - 12}px` : `${pxScreen + 12}px`;
  tt.style.top = "14px";
}

elements.chartWrap.addEventListener("pointermove", handleChartHover);
elements.chartWrap.addEventListener("pointerleave", hideTooltip);

/* ---------- dashboard rendering ---------- */

function resetDashboard() {
  state.workoutStartedAt = null;
  state.workoutFinishedAt = null;
  state.hrSeries = [];
  stopDurationTimer();
  renderChart();
  hideTooltip();
  elements.heartRate.textContent = "--";
  elements.targetRange.textContent = "--";
  elements.trainingZone.textContent = "--";
  elements.zoneState.textContent = "等待数据";
  elements.zoneState.className = "metric-unit";
  elements.pace.textContent = "--";
  elements.cadence.textContent = "--";
  elements.duration.textContent = "00:00";
  setChip(elements.adviceReason, "等待训练数据");
  elements.latestAdvice.textContent = "暂无建议，开始训练后我会陪你调整节奏。";
  elements.progressText.textContent = "0 / 0";
  elements.progressBar.style.width = "0%";
  elements.progressBar.parentElement.setAttribute("aria-valuenow", "0");
  elements.progressPct.textContent = "等待开始";
  setChip(elements.summaryStatus, "未完成");
  elements.summaryText.textContent = "训练完成后，这里会生成你的专属总结与关键数据。";
  elements.averageHr.textContent = "--";
  elements.peakHr.textContent = "--";
  elements.inZonePct.textContent = "--";
  elements.corrections.textContent = "--";
  elements.samples.textContent = "--";
}

function setRunningControls(isRunning) {
  const isCreating = isRunning && !state.sessionId;
  elements.startButton.disabled = isRunning;
  elements.stopButton.disabled = !isRunning || !state.sessionId;
  elements.startButton.setAttribute("aria-busy", String(isCreating));
  const label = elements.startButton.querySelector(".button-label");
  if (label) {
    label.textContent = isCreating ? "正在创建" : isRunning ? "训练进行中" : "开始训练";
  }
  [elements.promptInput, elements.demoInput, elements.ticksInput, elements.delayInput].forEach((control) => {
    control.disabled = isRunning;
  });
}

function renderSample(data, timestamp) {
  if (!state.workoutStartedAt) {
    state.workoutStartedAt = new Date(timestamp);
    startDurationTimer();
  }

  elements.heartRate.textContent = data.heart_rate ?? "--";
  if (Number.isFinite(data.heart_rate)) {
    const beatSpeed = Math.max(0.46, Math.min(1.15, 60 / data.heart_rate));
    elements.heartRateCard.style.setProperty("--beat-speed", `${beatSpeed.toFixed(2)}s`);
    elements.heartRateCard.setAttribute("aria-label", `当前心率 ${data.heart_rate} 次每分钟`);
  }
  elements.targetRange.textContent = data.target_low && data.target_high ? `${data.target_low}-${data.target_high}` : "--";
  elements.trainingZone.textContent = data.training_zone || "--";
  elements.zoneState.textContent = data.in_target_zone ? "当前在目标区间" : "当前偏离目标区间";
  elements.zoneState.className = `metric-unit ${data.in_target_zone ? "in-zone" : "off-zone"}`;
  elements.pace.textContent = data.pace ?? "--";
  elements.cadence.textContent = data.cadence ?? "--";

  if (Number.isFinite(data.heart_rate)) {
    state.hrSeries.push({
      hr: data.heart_rate,
      low: data.target_low || null,
      high: data.target_high || null,
      index: data.sample_index || state.hrSeries.length + 1,
    });
    if (state.hrSeries.length > 300) {
      state.hrSeries.shift();
    }
    renderChart();
  }

  const current = data.sample_index || 0;
  const total = data.total_samples || 0;
  const pct = total ? Math.min(100, Math.round((current / total) * 100)) : 0;
  elements.progressText.textContent = `${current} / ${total}`;
  elements.progressBar.style.width = `${pct}%`;
  elements.progressBar.parentElement.setAttribute("aria-valuenow", String(pct));
  elements.progressPct.textContent = total ? `已完成 ${pct}%` : "等待开始";
  renderDuration();
}

function renderAdvice(data) {
  elements.latestAdvice.textContent = data.message || "暂无建议";
  setChip(elements.adviceReason, labelReason(data.reason), reasonTones[data.reason] || "accent");
}

function renderSummary(data, timestamp) {
  state.workoutFinishedAt = new Date(timestamp);
  setChip(elements.summaryStatus, "已完成", "good");
  elements.summaryText.textContent = data.summary || "训练已完成。";
  elements.averageHr.textContent = data.average_heart_rate ? `${data.average_heart_rate}` : "--";
  elements.peakHr.textContent = data.peak_heart_rate ? `${data.peak_heart_rate}` : "--";
  elements.inZonePct.textContent = Number.isFinite(data.in_zone_pct) ? `${data.in_zone_pct}%` : "--";
  elements.corrections.textContent = Number.isFinite(data.corrections) ? `${data.corrections}` : "--";
  elements.samples.textContent = Number.isFinite(data.samples) ? `${data.samples}` : "--";
  stopDurationTimer();
}

function hydrateSnapshot(snapshot) {
  if (!snapshot) {
    return;
  }

  state.sessionId = snapshot.id || state.sessionId;
  elements.sessionId.textContent = sessionLabel(state.sessionId);
  const dashboard = snapshot.dashboard || {};

  if (dashboard.workout_started_at) {
    state.workoutStartedAt = new Date(dashboard.workout_started_at);
    startDurationTimer();
  }
  if (dashboard.workout_finished_at) {
    state.workoutFinishedAt = new Date(dashboard.workout_finished_at);
    stopDurationTimer();
  }
  if (dashboard.last_sample) {
    renderSample(dashboard.last_sample, dashboard.last_sample_at || dashboard.workout_started_at || snapshot.updated_at);
  }
  if (dashboard.last_advice) {
    renderAdvice(dashboard.last_advice);
  }
  if (dashboard.summary) {
    renderSummary(dashboard.summary, dashboard.summary_at || dashboard.workout_finished_at || snapshot.updated_at);
  }
}

function handleEvent(event) {
  const data = event.data || {};

  if (event.type === "session_snapshot") {
    hydrateSnapshot(data);
    appendLog(event.type, data.status || "snapshot received");
    return;
  }

  if (event.type === "heart_rate_sample") {
    renderSample(data, event.timestamp);
  } else if (event.type === "advice_event") {
    renderAdvice(data);
  } else if (event.type === "session_summary") {
    renderSummary(data, event.timestamp);
  } else if (event.type === "final") {
    setStatus("已完成", "done");
    setRunningControls(false);
    stopDurationTimer();
  } else if (event.type === "error") {
    setStatus("错误", "error");
    setChip(elements.summaryStatus, "失败", "danger");
    elements.summaryText.textContent = data.message || "会话失败。";
    setRunningControls(false);
    state.workoutFinishedAt = new Date(event.timestamp);
    stopDurationTimer();
  } else if (event.type === "stopped") {
    setStatus("已停止", "done");
    setChip(elements.summaryStatus, "已停止", "warn");
    if (elements.summaryText.textContent === "训练完成后，这里会生成你的专属总结与关键数据。") {
      elements.summaryText.textContent = data.reason ? labelReason(data.reason, "训练已停止。") : "训练已停止。";
    }
    setRunningControls(false);
    state.workoutFinishedAt = new Date(event.timestamp);
    stopDurationTimer();
  }

  if (["session_started", "llm_output", "action", "observation", "heart_rate_sample", "advice_event", "session_summary", "final", "error", "stopped"].includes(event.type)) {
    appendLog(event.type, data.message || data.reason || data.summary || data.final_answer || "");
  }
}

function connectStream(sessionId) {
  if (state.socket) {
    state.socket.close();
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${window.location.host}/sessions/${sessionId}/stream`);
  state.socket = socket;

  socket.addEventListener("open", () => {
    setStatus("训练中", "running");
    appendLog("websocket", "已连接");
  });

  socket.addEventListener("message", (message) => {
    handleEvent(JSON.parse(message.data));
  });

  socket.addEventListener("close", () => {
    appendLog("websocket", "已关闭");
    if (elements.statusBadge.classList.contains("running")) {
      setStatus("连接已关闭", "done");
      setRunningControls(false);
      stopDurationTimer();
    }
  });

  socket.addEventListener("error", () => {
    setStatus("连接错误", "error");
    appendLog("websocket", "连接错误");
    setRunningControls(false);
  });
}

async function startSession() {
  const prompt = elements.promptInput.value.trim();
  if (!prompt) {
    elements.promptInput.classList.add("input-error");
    elements.promptInput.focus();
    setStatus("请输入训练目标", "error");
    return;
  }

  if (state.socket) {
    state.socket.close();
    state.socket = null;
  }
  state.sessionId = null;
  elements.sessionId.textContent = "正在创建训练";
  resetDashboard();
  setStatus("创建中", "idle");
  setRunningControls(true);
  savePreferences();

  try {
    const response = await fetch("/sessions", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        prompt,
        demo: elements.demoInput.checked,
        workout_ticks: Number(elements.ticksInput.value),
        workout_tick_delay: Number(elements.delayInput.value),
      }),
    });

    const payload = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(payload.detail)
        ? payload.detail.map((item) => item.msg || String(item)).join("; ")
        : payload.detail;
      throw new Error(typeof detail === "string" ? detail : "创建会话失败");
    }

    state.sessionId = payload.id;
    elements.sessionId.textContent = sessionLabel(payload.id);
    setRunningControls(true);
    hydrateSnapshot(payload);
    connectStream(payload.id);
  } catch (error) {
    setStatus("创建失败", "error");
    setRunningControls(false);
    setChip(elements.summaryStatus, "失败", "danger");
    elements.summaryText.textContent = error.message;
    appendLog("error", error.message);
  }
}

async function stopSession() {
  if (!state.sessionId) {
    return;
  }

  elements.stopButton.disabled = true;
  try {
    const response = await fetch(`/sessions/${state.sessionId}/stop`, {method: "POST"});
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "停止会话失败");
    }
    setStatus("停止中", "done");
    appendLog("stop", labelReason(payload.status, payload.status));
  } catch (error) {
    setStatus("停止失败", "error");
    appendLog("error", error.message);
  }
}

elements.startButton.addEventListener("click", startSession);
elements.stopButton.addEventListener("click", stopSession);
elements.clearLogButton.addEventListener("click", () => {
  elements.eventLog.innerHTML = "";
  elements.eventLogEmpty.style.display = "block";
  if (elements.eventCount) elements.eventCount.textContent = "0";
});

const preferenceKey = "fitness-agent-dashboard-preferences";

function savePreferences() {
  try {
    localStorage.setItem(preferenceKey, JSON.stringify({
      prompt: elements.promptInput.value,
      demo: elements.demoInput.checked,
      ticks: elements.ticksInput.value,
      delay: elements.delayInput.value,
    }));
  } catch (_) {
    // Storage may be unavailable in private browsing; the dashboard still works.
  }
}

function loadPreferences() {
  try {
    const saved = JSON.parse(localStorage.getItem(preferenceKey) || "null");
    if (!saved) return;
    if (typeof saved.prompt === "string" && saved.prompt.trim()) elements.promptInput.value = saved.prompt;
    if (typeof saved.demo === "boolean") elements.demoInput.checked = saved.demo;
    if (saved.ticks !== undefined) elements.ticksInput.value = saved.ticks;
    if (saved.delay !== undefined) elements.delayInput.value = saved.delay;
  } catch (_) {
    // Ignore malformed or unavailable local preferences.
  }
}

document.querySelectorAll(".preset-chip").forEach((button) => {
  button.addEventListener("click", () => {
    elements.promptInput.value = button.dataset.prompt || "";
    elements.promptInput.classList.remove("input-error");
    elements.promptInput.focus();
    savePreferences();
  });
});

elements.promptInput.addEventListener("input", () => {
  elements.promptInput.classList.remove("input-error");
});
elements.promptInput.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !elements.startButton.disabled) {
    event.preventDefault();
    startSession();
  }
});
[elements.demoInput, elements.ticksInput, elements.delayInput].forEach((control) => {
  control.addEventListener("change", savePreferences);
});

loadPreferences();
setRunningControls(false);
resetDashboard();
