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
import { createLiveSource, createStaticSource, loadData, setSource } from "./loader.js";
import { initPsdView } from "./views/psd-view.js?v=psd-axis-20260606";
import { initCentroidView } from "./views/centroid-view.js";
import { initGeometryView } from "./views/geometry-view.js";
import { initChannelGrid } from "./views/channel-grid.js?v=grid-legend-20260606";
import { initPlaybackBar } from "./views/playback-bar.js";
import { initPhaseSpace } from "./views/phase-space.js";

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
let liveConnection = null;
let activeData = null;

init();

async function init() {
  try {
    const data = await loadData();
    activeData = data;
    configureChannels(data.meta.channels);
    configurePlayback(data.geometry.time.length);
    if (selectedChannel) selectedChannel.textContent = getChannel();
    if (loadStatus) loadStatus.textContent = "Ready";
    dashboard.setAttribute("aria-busy", "false");

    initPsdView(data, tooltip);
    initCentroidView(data, tooltip);
    initPlaybackBar(document.querySelector("#playback-bar"), data);
    initGeometryView(data, tooltip);
    initChannelGrid(data, tooltip);
    initPhaseSpace(document.querySelector("#phase-space"), data);

    onChannelChange((channel) => {
      if (selectedChannel) selectedChannel.textContent = channel;
      updateLiveMetrics(getLiveState());
    });
    bindControls();
    onLiveChange(updateLiveMetrics);
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
    button.addEventListener("click", () => {
      setActiveButton("[data-control='filter'] button", button);
      setChannelFilter(button.dataset.filter);
    });
  });

  document.querySelector("#channel-sort").addEventListener("change", (event) => {
    setChannelSort(event.target.value);
  });

  document.querySelectorAll("[data-control='psd-scale'] button").forEach((button) => {
    button.addEventListener("click", () => {
      setActiveButton("[data-control='psd-scale'] button", button);
      setPsdScale(button.dataset.scale);
    });
  });

  liveConnect.addEventListener("click", () => {
    startLive(liveUrl.value.trim() || "ws://127.0.0.1:8766");
  });
  liveDisconnect.addEventListener("click", stopLive);
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
