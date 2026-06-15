import { loadData } from "./loader.js";
import { createViewerApp } from "./viewer.js";
import { resolveAppModes } from "./app-modes.js";

const params = new URLSearchParams(window.location.search);
const { backendMode, privateMethodsMode } = resolveAppModes(params);
const app = createViewerApp({
  document,
  window,
  backendMode,
  privateMethodsMode,
  backendBaseUrl: params.get("backendUrl") ?? "",
});

init();

async function init() {
  try {
    const dataset = await loadData();
    await app.mount(dataset);
  } catch (error) {
    const dashboard = document.querySelector("#dashboard");
    const loadStatus = document.querySelector("#load-status");
    dashboard?.setAttribute("aria-busy", "false");
    if (loadStatus) {
      loadStatus.textContent = error.message;
      loadStatus.style.color = "#b23b32";
    }
  }
}
