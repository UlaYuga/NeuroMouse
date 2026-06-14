import { loadData } from "./loader.js";
import { createViewerApp } from "./viewer.js";

const params = new URLSearchParams(window.location.search);
const backendMode = params.has("backend") && params.get("backend") !== "0";
const app = createViewerApp({
  document,
  window,
  backendMode,
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
