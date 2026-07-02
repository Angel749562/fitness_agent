const state = {
  sessionId: null,
  socket: null,
  workoutStartedAt: null,
  workoutFinishedAt: null,
  durationTimer: null,
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
  sessionId: document.getElementById("sessionId"),
  promptInput: document.getElementById("promptInput"),
  demoInput: document.getElementById("demoInput"),
  ticksInput: document.getElementById("ticksInput"),
  delayInput: document.getElementById("delayInput"),
  startButton: document.getElementById("startButton"),
  stopButton: document.getElementById("stopButton"),
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
  summaryStatus: document.getElementById("summaryStatus"),
  summaryText: document.getElementById("summaryText"),
  averageHr: document.getElementById("averageHr"),
  peakHr: document.getElementById("peakHr"),
  inZonePct: document.getElementById("inZonePct"),
  corrections: document.getElementById("corrections"),
  samples: document.getElementById("samples"),
  eventLog: document.getElementById("eventLog"),
  clearLogButton: document.getElementById("clearLogButton"),
};

function setStatus(text, variant = "idle") {
  elements.statusBadge.textContent = text;
  elements.statusBadge.className = `status-badge ${variant}`;
}

function appendLog(type, text = "") {
  const item = document.createElement("li");
  const time = new Date().toLocaleTimeString();
  item.textContent = `[${time}] ${labelEvent(type)}${text ? `: ${labelReason(text, text)}` : ""}`;
  elements.eventLog.prepend(item);

  while (elements.eventLog.children.length > 60) {
    elements.eventLog.lastElementChild.remove();
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

function resetDashboard() {
  state.workoutStartedAt = null;
  state.workoutFinishedAt = null;
  stopDurationTimer();
  elements.heartRate.textContent = "--";
  elements.targetRange.textContent = "--";
  elements.trainingZone.textContent = "--";
  elements.zoneState.textContent = "等待数据";
  elements.pace.textContent = "--";
  elements.cadence.textContent = "--";
  elements.duration.textContent = "00:00";
  elements.adviceReason.textContent = "等待训练数据";
  elements.latestAdvice.textContent = "暂无建议，等待训练数据...";
  elements.progressText.textContent = "0 / 0";
  elements.progressBar.style.width = "0%";
  elements.summaryStatus.textContent = "未完成";
  elements.summaryText.textContent = "训练完成后会显示总结。";
  elements.averageHr.textContent = "--";
  elements.peakHr.textContent = "--";
  elements.inZonePct.textContent = "--";
  elements.corrections.textContent = "--";
  elements.samples.textContent = "--";
}

function setRunningControls(isRunning) {
  elements.startButton.disabled = isRunning;
  elements.stopButton.disabled = !isRunning || !state.sessionId;
}

function renderSample(data, timestamp) {
  if (!state.workoutStartedAt) {
    state.workoutStartedAt = new Date(timestamp);
    startDurationTimer();
  }

  elements.heartRate.textContent = data.heart_rate ?? "--";
  elements.targetRange.textContent = data.target_low && data.target_high ? `${data.target_low}-${data.target_high}` : "--";
  elements.trainingZone.textContent = data.training_zone || "--";
  elements.zoneState.textContent = data.in_target_zone ? "当前在目标区间" : "当前偏离目标区间";
  elements.zoneState.style.color = data.in_target_zone ? "var(--success)" : "var(--warning)";
  elements.pace.textContent = data.pace ?? "--";
  elements.cadence.textContent = data.cadence ?? "--";

  const current = data.sample_index || 0;
  const total = data.total_samples || 0;
  elements.progressText.textContent = `${current} / ${total}`;
  elements.progressBar.style.width = total ? `${Math.min(100, Math.round((current / total) * 100))}%` : "0%";
  renderDuration();
}

function renderAdvice(data) {
  elements.latestAdvice.textContent = data.message || "暂无建议";
  elements.adviceReason.textContent = labelReason(data.reason);
}

function renderSummary(data, timestamp) {
  state.workoutFinishedAt = new Date(timestamp);
  elements.summaryStatus.textContent = "已完成";
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
    elements.summaryStatus.textContent = "失败";
    elements.summaryText.textContent = data.message || "会话失败。";
    setRunningControls(false);
    state.workoutFinishedAt = new Date(event.timestamp);
    stopDurationTimer();
  } else if (event.type === "stopped") {
    setStatus("已停止", "done");
    elements.summaryStatus.textContent = "已停止";
    if (elements.summaryText.textContent === "训练完成后会显示总结。") {
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
  resetDashboard();
  setStatus("创建中", "idle");
  setRunningControls(true);

  try {
    const response = await fetch("/sessions", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        prompt: elements.promptInput.value.trim(),
        demo: elements.demoInput.checked,
        workout_ticks: Number(elements.ticksInput.value),
        workout_tick_delay: Number(elements.delayInput.value),
      }),
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "创建会话失败");
    }

    state.sessionId = payload.id;
    elements.sessionId.textContent = sessionLabel(payload.id);
    hydrateSnapshot(payload);
    connectStream(payload.id);
  } catch (error) {
    setStatus("创建失败", "error");
    setRunningControls(false);
    elements.summaryStatus.textContent = "失败";
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
});

setRunningControls(false);
resetDashboard();
