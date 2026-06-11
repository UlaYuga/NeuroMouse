import { loadData } from "./loader.js";
import { createViewerApp } from "./viewer.js";

const app = createViewerApp({ document, window });

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
      loadStatus.style.color = "#ff786d";
    }
  }
}
