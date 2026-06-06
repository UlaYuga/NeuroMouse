import { configureChannels, getChannel, onChannelChange } from "./state.js";
import { loadData } from "./loader.js";
import { initPsdView } from "./views/psd-view.js";
import { initCentroidView } from "./views/centroid-view.js";
import { initGeometryView } from "./views/geometry-view.js";
import { initChannelGrid } from "./views/channel-grid.js";

const dashboard = document.querySelector("#dashboard");
const loadStatus = document.querySelector("#load-status");
const selectedChannel = document.querySelector("#selected-channel");
const tooltip = createTooltip(document.querySelector("#tooltip"));

init();

async function init() {
  try {
    const data = await loadData();
    configureChannels(data.meta.channels);
    selectedChannel.textContent = getChannel();
    loadStatus.textContent = `${data.meta.n_channels} channels · ${data.meta.segment_duration_sec} sec · static JSON`;
    dashboard.setAttribute("aria-busy", "false");

    initPsdView(data, tooltip);
    initCentroidView(data, tooltip);
    initGeometryView(data, tooltip);
    initChannelGrid(data, tooltip);

    onChannelChange((channel) => {
      selectedChannel.textContent = channel;
    });
  } catch (error) {
    dashboard.setAttribute("aria-busy", "false");
    loadStatus.textContent = error.message;
    loadStatus.style.color = "#ff786d";
  }
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

