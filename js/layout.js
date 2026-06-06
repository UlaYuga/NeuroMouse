import {
  clearLiveHistory,
  configureChannels,
  configurePlayback,
  getChannel,
  getLiveState,
  liveMetric,
  onChannelChange,
  onLiveChange,
  pushLiveFrame,
  setChannelFilter,
  setChannelSort,
  setPsdScale,
  updateLiveStatus,
} from "./state.js";
import { createDisposables } from "./disposables.js";
import { createLiveSource, createStaticSource, loadData, loadZipFiles, setSource } from "./loader.js";
import {
  MAX_SESSIONS,
  addSession,
  getBaselineId,
  getBaselineSession,
  getSessions,
  getViewMode,
  onSessionsChange,
  removeSession,
  setBaseline,
  setViewMode,
  toggleSession,
} from "./sessions.js";
import { initPsdView } from "./views/psd-view.js";
import { initCentroidView } from "./views/centroid-view.js";
import { initGeometryView } from "./views/geometry-view.js";
import { initChannelGrid } from "./views/channel-grid.js";
import { initPlaybackBar } from "./views/playback-bar.js";
import { initPhaseSpace } from "./views/phase-space.js";
import { initMonitorView } from "./views/monitor-view.js";
import { initPolarChronomap } from "./views/polar-chronomap.js";
import { initKuramotoView } from "./views/kuramoto.js";
import { initChannelNetwork } from "./views/channel-network.js";
import { initTdaView } from "./views/tda-view.js";

const dashboard = document.querySelector("#dashboard");
const loadStatus = document.querySelector("#load-status");
const selectedChannel = document.querySelector("#selected-channel");
const tooltip = createTooltip(document.querySelector("#tooltip"));
const liveUrl = document.querySelector("#live-url");
const liveConnect = document.querySelector("#live-connect");
const liveDisconnect = document.querySelector("#live-disconnect");
const liveStatus = document.querySelector("#live-status");
const liveFrames = document.querySelector("#live-frames");
const liveTime = document.querySelector("#live-time");
const liveCompute = document.querySelector("#live-compute");
const liveAlpha = document.querySelector("#live-alpha");
const sessionDropZone = document.querySelector("#session-drop-zone");
const sessionFileInput = document.querySelector("#session-file-input");
const sessionList = document.querySelector("#session-list");
const sessionMessage = document.querySelector("#session-message");
const sessionCount = document.querySelector("#session-count");
const baselineSelect = document.querySelector("#baseline-select");
let liveConnection = null;
let activeData = null;
let monitorView = null;
const appDisposables = createDisposables();

init();

async function init() {
  try {
    const data = await loadData();
    activeData = data;
    configureChannels(data.meta.channels);
    configurePlayback(data.geometry.time.length);
    updateSelectedChannelLabel(getChannel());
    if (loadStatus) loadStatus.textContent = "Ready";
    dashboard.setAttribute("aria-busy", "false");

    bindSessionControls();
    renderSessionSidebar();
    appDisposables.add(initPsdView(data, tooltip));
    appDisposables.add(initCentroidView(data, tooltip));
    appDisposables.add(initPlaybackBar(document.querySelector("#playback-bar"), data));
    monitorView = initMonitorView(document.querySelector("#monitor-panel"), data);
    appDisposables.add(monitorView?.dispose);
    appDisposables.add(initGeometryView(data, tooltip));
    appDisposables.add(initChannelGrid(data, tooltip));
    appDisposables.add(initPhaseSpace(document.querySelector("#phase-space"), data));
    appDisposables.add(initPolarChronomap(document.querySelector("#polar-chronomap"), data, tooltip));
    appDisposables.add(initKuramotoView(document.querySelector("#kuramoto-view"), data));
    appDisposables.add(initChannelNetwork(document.querySelector("#channel-network"), data, tooltip));
    appDisposables.add(initTdaView(document.querySelector("#tda-view"), data, tooltip));

    appDisposables.add(onChannelChange((channel) => {
      updateSelectedChannelLabel(channel);
      updateLiveMetrics(getLiveState());
    }));
    bindControls();
    appDisposables.add(onLiveChange((state) => {
      updateLiveMetrics(state);
      monitorView?.setLiveState(state);
    }));
    appDisposables.add(onSessionsChange(() => {
      syncSessionState();
      renderSessionSidebar();
      updateLiveMetrics(getLiveState());
    }));
    appDisposables.listen(window, "pagehide", () => appDisposables.dispose(), { once: true });
  } catch (error) {
    dashboard.setAttribute("aria-busy", "false");
    if (loadStatus) {
      loadStatus.textContent = error.message;
      loadStatus.style.color = "#ff786d";
    }
  }
}

function bindControls() {
  document.querySelectorAll("[data-control='filter'] button").forEach((button) => {
    appDisposables.listen(button, "click", () => {
      setActiveButton("[data-control='filter'] button", button);
      setChannelFilter(button.dataset.filter);
    });
  });

  appDisposables.listen(document.querySelector("#channel-sort"), "change", (event) => {
    setChannelSort(event.target.value);
  });

  document.querySelectorAll("[data-control='psd-scale'] button").forEach((button) => {
    appDisposables.listen(button, "click", () => {
      setActiveButton("[data-control='psd-scale'] button", button);
      setPsdScale(button.dataset.scale);
    });
  });

  appDisposables.listen(liveConnect, "click", () => {
    startLive(liveUrl.value.trim() || "ws://127.0.0.1:8766");
  });
  appDisposables.listen(liveDisconnect, "click", stopLive);
}

function startLive(url) {
  if (liveConnection) liveConnection.stop();
  clearLiveHistory();
  updateLiveStatus({ connected: false, status: "connecting", url });
  liveConnect.disabled = true;
  liveDisconnect.disabled = false;
  if (liveStatus) {
    liveStatus.className = "live-status is-connecting";
    liveStatus.textContent = `connecting... ${url}`;
  }

  liveConnection = setSource(createLiveSource(url, { referenceData: activeData }));
  liveConnection.start(
    (frame) => {
      pushLiveFrame(frame);
      monitorView?.handleFrame(frame);
      updateLiveStatus({ connected: true, status: "live", url });
    },
    (status, detail = {}) => {
      const connected = status === "live";
      updateLiveStatus({
        connected,
        status,
        url,
        detail,
      });
      if (status === "error") {
        liveConnection?.stop();
        liveConnection = null;
        setSource(createStaticSource());
        clearLiveHistory();
        liveConnect.disabled = false;
        liveDisconnect.disabled = true;
      } else if (status === "disconnected") {
        liveConnection = null;
        setSource(createStaticSource());
        clearLiveHistory();
        liveConnect.disabled = false;
        liveDisconnect.disabled = true;
      }
    },
  );
}

function stopLive() {
  if (liveConnection) {
    liveConnection.stop();
    liveConnection = null;
  }
  setSource(createStaticSource());
  clearLiveHistory();
  updateLiveStatus({ connected: false, status: "static replay", url: liveUrl.value.trim() });
  liveConnect.disabled = false;
  liveDisconnect.disabled = true;
}

function updateLiveMetrics(state) {
  const frame = state.latestFrame;
  const channel = getChannel();
  if (liveFrames) liveFrames.textContent = String(state.frameCount);
  if (liveTime) liveTime.textContent = frame?.window_start_time_sec == null ? "—" : `${Number(frame.window_start_time_sec).toFixed(2)}s`;
  if (liveCompute) liveCompute.textContent = frame?.compute_ms == null ? "—" : `${Number(frame.compute_ms).toFixed(1)}ms`;
  const alpha = liveMetric(frame, channel, "alpha_relative_power");
  if (liveAlpha) liveAlpha.textContent = alpha == null ? "—" : alpha.toFixed(4);

  if (liveStatus) {
    liveStatus.className = `live-status ${statusClass(state)}`.trim();
    liveStatus.textContent = statusText(state);
  }
  if (loadStatus) {
    loadStatus.textContent = state.connected ? "Live" : "Ready";
  }
  liveConnect.disabled = state.connected;
  liveDisconnect.disabled = !state.connected && !liveConnection;
}

function statusClass(state) {
  if (state.status === "live" || state.connected) return "is-live";
  if (state.status === "connecting") return "is-connecting";
  if (state.status === "error") return "is-error";
  return "";
}

function statusText(state) {
  if (state.status === "live" || state.connected) return `● live · ${state.url || liveUrl.value}`;
  if (state.status === "connecting") return `connecting... ${state.url || liveUrl.value}`;
  if (state.status === "error") {
    return state.detail?.message ? `connection error · ${state.detail.message}` : "connection error";
  }
  if (state.status === "disconnected") return "static replay";
  return "static replay";
}

function setActiveButton(selector, active) {
  document.querySelectorAll(selector).forEach((button) => {
    button.classList.toggle("is-active", button === active);
  });
}

function bindSessionControls() {
  appDisposables.listen(sessionDropZone, "click", () => sessionFileInput?.click());
  appDisposables.listen(sessionDropZone, "dragover", (event) => {
    event.preventDefault();
    sessionDropZone.classList.add("drag-over");
  });
  appDisposables.listen(sessionDropZone, "dragleave", () => {
    sessionDropZone.classList.remove("drag-over");
  });
  appDisposables.listen(sessionDropZone, "drop", async (event) => {
    event.preventDefault();
    sessionDropZone.classList.remove("drag-over");
    await handleSessionFiles(Array.from(event.dataTransfer.files));
  });
  appDisposables.listen(sessionFileInput, "change", async () => {
    await handleSessionFiles(Array.from(sessionFileInput.files ?? []));
    sessionFileInput.value = "";
  });
  document.querySelectorAll("[data-control='view-mode'] button").forEach((button) => {
    appDisposables.listen(button, "click", () => {
      setViewMode(button.dataset.viewMode);
    });
  });
  appDisposables.listen(baselineSelect, "change", () => {
    setBaseline(baselineSelect.value);
  });
}

async function handleSessionFiles(files) {
  const zipFiles = files.filter((file) => file.name.toLowerCase().endsWith(".zip"));
  if (!zipFiles.length) {
    setSessionMessage("Drop ZIP files only", true);
    return;
  }

  setSessionMessage("Loading ZIP…");
  const { datasets, errors } = await loadZipFiles(zipFiles);
  let added = 0;
  for (const dataset of datasets) {
    try {
      addSession(dataset.name, dataset.data);
      added += 1;
    } catch (error) {
      errors.push(error.message);
      break;
    }
  }

  if (added > 0 && errors.length) {
    setSessionMessage(`Added ${added}; ${errors[0]}`, true);
  } else if (added > 0) {
    setSessionMessage(`Added ${added} session${added === 1 ? "" : "s"}`);
  } else {
    setSessionMessage(errors[0] ?? "No datasets found", true);
  }
}

function syncSessionState() {
  const primary = getBaselineSession(activeData);
  if (!primary?.data) return;
  configureChannels(primary.data.meta.channels);
  configurePlayback(primary.data.geometry.time.length);
  updateSelectedChannelLabel(getChannel());
}

function updateSelectedChannelLabel(channel) {
  if (selectedChannel) selectedChannel.textContent = `Selected channel: ${channel}`;
}

function renderSessionSidebar() {
  const sessions = getSessions();
  const mode = getViewMode();
  if (sessionCount) sessionCount.textContent = `${sessions.length}/${MAX_SESSIONS}`;

  document.querySelectorAll("[data-control='view-mode'] button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.viewMode === mode);
  });

  if (sessionList) {
    sessionList.innerHTML = "";
    sessions.forEach((session) => {
      const row = element("div", {
        className: `session-item${session.active ? "" : " is-inactive"}`,
        style: `--session-color:${session.color}`,
      });
      const toggle = element("button", {
        type: "button",
        className: "session-toggle",
        title: session.active ? "Hide session" : "Show session",
        "aria-pressed": String(session.active),
      }, element("span", { className: "session-dot" }), element("span", { className: "session-name" }, session.name));
      const remove = element("button", {
        type: "button",
        className: "session-remove",
        "aria-label": `Remove ${session.name}`,
      }, "×");
      toggle.addEventListener("click", () => toggleSession(session.id));
      remove.addEventListener("click", () => removeSession(session.id));
      row.append(toggle, remove);
      sessionList.append(row);
    });
  }

  if (baselineSelect) {
    baselineSelect.innerHTML = "";
    const baselineId = getBaselineId();
    sessions.forEach((session) => {
      baselineSelect.append(element("option", {
        value: session.id,
        selected: session.id === baselineId,
      }, session.name));
    });
    baselineSelect.disabled = sessions.length === 0;
  }

  if (!sessions.length) setSessionMessage("Add sessions to compare");
}

function setSessionMessage(message, isError = false) {
  if (!sessionMessage) return;
  sessionMessage.textContent = message;
  sessionMessage.classList.toggle("is-error", isError);
}

function createTooltip(node) {
  return {
    show(x, y, html) {
      node.innerHTML = html;
      node.hidden = false;
      const rect = node.getBoundingClientRect();
      const left = Math.min(window.innerWidth - rect.width - 12, x + 14);
      const top = Math.min(window.innerHeight - rect.height - 12, y + 14);
      node.style.left = `${Math.max(8, left)}px`;
      node.style.top = `${Math.max(8, top)}px`;
    },
    hide() {
      node.hidden = true;
    },
  };
}

function element(name, attrs = {}, ...children) {
  const node = document.createElement(name);
  Object.entries(attrs).forEach(([key, value]) => {
    if (key === "className") node.className = value;
    else if (key === "htmlFor") node.htmlFor = value;
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false && value != null) node.setAttribute(key, value);
  });
  children.flat().forEach((child) => {
    if (child == null) return;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  });
  return node;
}
