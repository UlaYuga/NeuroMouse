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
import { connectLive, loadData } from "./loader.js";
import { initPsdView } from "./views/psd-view.js?v=psd-axis-20260606";
import { initCentroidView } from "./views/centroid-view.js";
import { initGeometryView } from "./views/geometry-view.js";
import { initChannelGrid } from "./views/channel-grid.js";
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
  if (liveConnection) liveConnection.close();
  clearLiveHistory();
  updateLiveStatus({ connected: false, status: "Connecting", url });
  liveConnect.disabled = true;
  liveDisconnect.disabled = false;
  if (liveStatus) {
    liveStatus.className = "live-status";
    liveStatus.textContent = `Connecting ${url}`;
  }

  liveConnection = connectLive(url, {
    onFrame(frame) {
      pushLiveFrame(frame);
      updateLiveStatus({ connected: true, status: "Live stream", url });
    },
    onStatus(status) {
      updateLiveStatus({
        connected: status.connected,
        status: status.message,
        url,
        bridge: status.bridge,
      });
    },
    onError(message) {
      updateLiveStatus({ connected: false, status: message, url });
      if (liveStatus) {
        liveStatus.className = "live-status is-error";
        liveStatus.textContent = message;
      }
      liveConnect.disabled = false;
      liveDisconnect.disabled = false;
    },
  });
}

function stopLive() {
  if (liveConnection) {
    liveConnection.close();
    liveConnection = null;
  }
  clearLiveHistory();
  updateLiveStatus({ connected: false, status: "Ready", url: liveUrl.value.trim() });
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

  const liveText = state.connected ? "is-live" : "";
  if (liveStatus && !liveStatus.classList.contains("is-error")) {
    liveStatus.className = `live-status ${liveText}`.trim();
  }
  const psdNote = state.latestFrame && !state.latestFrame.psd_by_channel
    ? " · PSD frame not included"
    : "";
  if (liveStatus) {
    liveStatus.textContent = state.connected
      ? `${state.status} · ${state.url || liveUrl.value}${psdNote}`
      : state.status;
  }
  if (loadStatus) {
    loadStatus.textContent = state.connected ? "Live" : "Ready";
  }
  liveConnect.disabled = state.connected;
  liveDisconnect.disabled = !state.connected && !liveConnection;
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
