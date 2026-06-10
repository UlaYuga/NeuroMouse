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
import { createLiveSource, createStaticSource, loadData, loadDatasetFiles, setSource } from "./loader.js";
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
import {
  buildImportReceipt,
  buildWorkbenchState,
  createDemoDatasetPair,
  formatNumber,
  formatPercent,
  formatSignedNumber,
  formatSignedPercent,
  generateWorkbenchReportPreview,
  generateWorkbenchReport,
} from "./workbench.js";

const dashboard = document.querySelector("#dashboard");
const loadStatus = document.querySelector("#load-status");
const selectedChannel = document.querySelector("#selected-channel");
const tooltip = createTooltip(document.querySelector("#tooltip"));
const liveUrl = document.querySelector("#live-url");
const liveConnect = document.querySelector("#live-connect");
const liveDisconnect = document.querySelector("#live-disconnect");
const liveStatus = document.querySelector("#live-status");
const liveFrames = document.querySelector("#live-frames");
const headerChannels = document.querySelector("#header-channels");
const headerFrames = document.querySelector("#header-frames");
const liveTime = document.querySelector("#live-time");
const liveCompute = document.querySelector("#live-compute");
const liveAlpha = document.querySelector("#live-alpha");
const sessionDropZone = document.querySelector("#session-drop-zone");
const sessionFileInput = document.querySelector("#session-file-input");
const sessionList = document.querySelector("#session-list");
const sessionMessage = document.querySelector("#session-message");
const sessionCount = document.querySelector("#session-count");
const baselineSelect = document.querySelector("#baseline-select");
const workbenchImport = document.querySelector("#workbench-import");
const workbenchDemo = document.querySelector("#workbench-demo");
const workbenchReport = document.querySelector("#workbench-report");
const workbenchDropZone = document.querySelector("#workbench-drop-zone");
const workbenchImportLog = document.querySelector("#workbench-import-log");
const workbenchScenario = document.querySelector("#workbench-scenario");
const workbenchStatus = document.querySelector("#workbench-status");
const workbenchComparisons = document.querySelector("#workbench-comparisons");
const workbenchMetrics = document.querySelector("#workbench-metrics");
const workbenchOpenComparison = document.querySelector("#workbench-open-comparison");
const workbenchScenarioDetail = document.querySelector("#workbench-scenario-detail");
const workbenchBaselineSummary = document.querySelector("#workbench-baseline-summary");
const workbenchBaselineSelect = document.querySelector("#workbench-baseline-select");
const workbenchReadiness = document.querySelector("#workbench-readiness");
const workbenchQuality = document.querySelector("#workbench-quality");
const workbenchReportDialog = document.querySelector("#workbench-report-dialog");
const workbenchReportPreview = document.querySelector("#workbench-report-preview");
const workbenchReportDownload = document.querySelector("#workbench-report-download");
const workbenchReportClose = document.querySelector("#workbench-report-close");
const workbenchReportDismiss = document.querySelector("#workbench-report-dismiss");
const workbenchExplainBtn = document.querySelector("#workbench-explain-btn");
const workbenchExplain = document.querySelector("#workbench-explain");
const workbenchExplainQuestion = document.querySelector("#workbench-explain-q");
let lastReportMarkdown = "";
let liveConnection = null;
let activeData = null;
let monitorView = null;
let activeScenarioId = workbenchScenario?.value ?? "trained-vs-naive";
const appDisposables = createDisposables();

init();

async function init() {
  try {
    const data = await loadData();
    activeData = data;
    configureChannels(data.meta.channels);
    configurePlayback(data.geometry.time.length);
    updateHeaderStatus(data);
    updateSelectedChannelLabel(getChannel());
    await waitForFonts();
    if (loadStatus) loadStatus.textContent = "Ready";
    dashboard.setAttribute("aria-busy", "false");

    bindSessionControls();
    renderSessionSidebar();
    renderWorkbench();
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
      renderWorkbench();
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
    liveStatus.textContent = `connecting… ${url}`;
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
  if (state.status === "connecting") return `connecting… ${state.url || liveUrl.value}`;
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

async function waitForFonts() {
  if (!document.fonts?.ready) return;
  await Promise.race([
    document.fonts.ready,
    new Promise((resolve) => setTimeout(resolve, 1500)),
  ]);
}

function bindSessionControls() {
  appDisposables.listen(workbenchImport, "click", () => sessionFileInput?.click());
  appDisposables.listen(workbenchDemo, "click", loadDemoPair);
  appDisposables.listen(workbenchReport, "click", openReportPreview);
  appDisposables.listen(workbenchOpenComparison, "click", openComparisonSuite);
  appDisposables.listen(workbenchScenario, "change", () => {
    activeScenarioId = workbenchScenario.value;
    renderWorkbench();
  });
  appDisposables.listen(workbenchDropZone, "click", () => sessionFileInput?.click());
  appDisposables.listen(workbenchDropZone, "dragover", (event) => {
    event.preventDefault();
    workbenchDropZone.classList.add("drag-over");
  });
  appDisposables.listen(workbenchDropZone, "dragleave", () => {
    workbenchDropZone.classList.remove("drag-over");
  });
  appDisposables.listen(workbenchDropZone, "drop", async (event) => {
    event.preventDefault();
    workbenchDropZone.classList.remove("drag-over");
    await handleSessionFiles(Array.from(event.dataTransfer.files));
  });

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
  appDisposables.listen(workbenchBaselineSelect, "change", () => {
    setBaseline(workbenchBaselineSelect.value);
  });
  appDisposables.listen(workbenchReportDownload, "click", downloadWorkbenchReport);
  appDisposables.listen(workbenchExplainBtn, "click", requestExplanation);
  appDisposables.listen(workbenchReportClose, "click", closeReportPreview);
  appDisposables.listen(workbenchReportDismiss, "click", closeReportPreview);
  appDisposables.listen(workbenchReportDialog, "click", (event) => {
    if (event.target === workbenchReportDialog) closeReportPreview();
  });
}

async function handleSessionFiles(files) {
  const supportedFiles = files.filter((file) => /\.(json|zip)$/i.test(file.name));
  if (!supportedFiles.length) {
    renderImportReceipt(buildImportReceipt({
      rejected: files.length
        ? files.map((file) => `${file.name}: unsupported format`)
        : ["No file selected"],
    }));
    setSessionMessage("Drop NeuroMouse data.json or ZIP exports", true);
    return;
  }

  setSessionMessage("Loading datasets…");
  const { datasets, errors } = await loadDatasetFiles(supportedFiles);
  const accepted = [];
  const skipped = [];
  const rejected = [...errors];

  for (const dataset of datasets) {
    try {
      addSession(dataset.name, dataset.data);
      accepted.push(`${dataset.name}: added · ${describeMontage(dataset.data)}`);
    } catch (error) {
      const message = `${dataset.name}: ${error.message}`;
      if (/already loaded|Maximum \d+ sessions/i.test(error.message)) {
        skipped.push(message);
      } else {
        rejected.push(message);
      }
      if (/Maximum \d+ sessions/i.test(error.message)) break;
    }
  }

  const receipt = buildImportReceipt({ accepted, skipped, rejected });
  renderImportReceipt(receipt);

  if (receipt.acceptedCount > 0) {
    setSessionMessage(receipt.headline, receipt.rejectedCount > 0);
  } else {
    setSessionMessage(receipt.rows[0]?.message ?? "No datasets found", true);
  }
}

function loadDemoPair() {
  if (!activeData) return;
  const accepted = [];
  const skipped = [];
  const rejected = [];
  let baselineId = null;

  createDemoDatasetPair(activeData).forEach((session) => {
    try {
      const added = addSession(session.name, session.data);
      accepted.push(`${session.name}: added · ${describeMontage(session.data)}`);
      if (!baselineId) baselineId = added.id;
    } catch (error) {
      const message = `${session.name}: ${error.message}`;
      if (/already loaded|Maximum \d+ sessions/i.test(error.message)) {
        skipped.push(message);
      } else {
        rejected.push(message);
      }
    }
  });

  if (baselineId) {
    setBaseline(baselineId);
    setViewMode("overlay");
  }

  const receipt = buildImportReceipt({ accepted, skipped, rejected });
  renderImportReceipt(receipt);
  setSessionMessage(receipt.headline, receipt.rejectedCount > 0 && receipt.acceptedCount === 0);
}

function renderWorkbench() {
  if (!workbenchMetrics || !activeData) return;
  const state = buildWorkbenchState({
    sessions: getSessions(),
    fallbackData: activeData,
    baselineId: getBaselineId(),
    scenarioId: activeScenarioId,
  });

  renderPipelineState(state);
  renderScenarioSummary(state);
  renderBaselineSummary(state);
  renderReadiness(state);
  renderQualityFlags(state);

  if (workbenchStatus) {
    workbenchStatus.textContent = state.status;
    workbenchStatus.className = `workbench-status ${state.reportReadiness.ready ? "is-ready" : "is-draft"}`;
  }

  workbenchMetrics.innerHTML = "";
  state.metrics.forEach((metric) => {
    workbenchMetrics.append(element("div", { className: "metric-tile" },
      element("span", {}, metric.label),
      element("strong", {}, metric.value),
      element("small", {}, metric.detail),
    ));
  });

  if (workbenchComparisons) {
    workbenchComparisons.innerHTML = "";
    if (!state.comparisons.length) {
      workbenchComparisons.append(element("p", { className: "empty-comparison" },
        `${state.scenario.baselineLabel} -> ${state.scenario.targetLabel}`,
      ));
    } else {
      state.comparisons.slice(0, 3).forEach((row) => {
        workbenchComparisons.append(element("div", { className: "comparison-row" },
          element("span", { className: "comparison-name" }, row.name),
          element("span", {}, `${row.primaryLabel} ${formatPrimaryValue(row)}`),
          element("span", {}, `${row.scoreLabel} ${row.score}/100`),
          element("strong", {}, row.interpretation),
        ));
      });
      workbenchComparisons.append(element("p", { className: "comparison-disclaimer" },
        "Score is a heuristic ranking aid (0-100), not a statistical test. Read the deltas and detailed plots as the evidence.",
      ));
    }
  }
}

function renderPipelineState(state) {
  document.querySelectorAll("[data-pipeline-step]").forEach((step) => {
    const key = step.dataset.pipelineStep;
    const ready = key === "ingest" ||
      key === "normalize" ||
      (key === "compare" && state.comparisons.length > 0) ||
      (key === "report" && state.reportReadiness.ready);
    step.classList.toggle("is-ready", ready);
  });
}

function renderScenarioSummary(state) {
  if (workbenchScenarioDetail) {
    workbenchScenarioDetail.textContent = state.scenario.description;
  }
}

function renderBaselineSummary(state) {
  if (!workbenchBaselineSummary) return;
  workbenchBaselineSummary.innerHTML = "";
  if (!state.baseline || !state.baselineSummary) {
    workbenchBaselineSummary.append(element("span", {}, "No baseline selected"));
    return;
  }

  workbenchBaselineSummary.append(
    element("span", { className: "baseline-label" }, state.scenario.baselineLabel),
    element("strong", {}, state.baseline.name),
    element("div", { className: "baseline-facts" },
      element("span", {}, `${state.baselineSummary.channels} ch`),
      element("span", {}, `${state.baselineSummary.frames} frames`),
      element("span", {}, `${formatNumber(state.baselineSummary.centroidMeanHz, 1)} Hz centroid`),
      element("span", {}, `${formatPercent(state.baselineSummary.clearAlphaRatio)} alpha clear`),
    ),
  );
}

function renderReadiness(state) {
  if (!workbenchReadiness) return;
  workbenchReadiness.innerHTML = "";
  workbenchReadiness.className = `readiness-panel ${state.reportReadiness.ready ? "is-ready" : "is-draft"}`;
  workbenchReadiness.append(
    element("span", {}, state.reportReadiness.ready ? "Report ready" : "Report draft"),
    element("strong", {}, state.reportReadiness.message),
  );
}

function renderQualityFlags(state) {
  if (!workbenchQuality) return;
  workbenchQuality.innerHTML = "";
  state.qualityFlags.forEach((flag) => {
    workbenchQuality.append(element("div", { className: `quality-item is-${flag.level}` },
      element("span", {}, flag.label),
      element("strong", {}, flag.message),
    ));
  });
}

function renderImportReceipt(receipt) {
  if (!workbenchImportLog || !workbenchDropZone) return;
  workbenchImportLog.innerHTML = "";
  workbenchDropZone.classList.toggle("has-import-log", receipt.rows.length > 0);
  if (!receipt.rows.length) return;

  workbenchImportLog.append(element("span", { className: "import-headline" }, receipt.headline));
  receipt.rows.slice(0, 4).forEach((row) => {
    workbenchImportLog.append(element("span", { className: `import-row is-${row.status}` },
      element("strong", {}, row.status),
      element("span", {}, row.message),
    ));
  });
  if (receipt.rows.length > 4) {
    workbenchImportLog.append(element("span", { className: "import-row is-more" },
      element("strong", {}, `+${receipt.rows.length - 4}`),
      element("span", {}, "more import events"),
    ));
  }
}

function formatPrimaryValue(row) {
  if (row.primaryMetric === "alphaChange") return formatSignedPercent(row.primaryValue);
  if (row.primaryMetric === "centroidShiftHz") return `${formatSignedNumber(row.primaryValue, 2)} Hz`;
  if (row.primaryMetric === "entropyShift" || row.primaryMetric === "flatnessShift") return formatSignedNumber(row.primaryValue, 4);
  if (row.primaryMetric === "driftScore") return `${Math.round(Number(row.primaryValue) || 0)}/100`;
  return formatSignedNumber(row.primaryValue, 2);
}

function openReportPreview() {
  if (!workbenchReportPreview || !workbenchReportDialog) return;
  const preview = generateWorkbenchReportPreview({
    sessions: getSessions(),
    fallbackData: activeData,
    baselineId: getBaselineId(),
    scenarioId: activeScenarioId,
    generatedAt: new Date(),
  });
  renderReportPreview(preview);
  lastReportMarkdown = preview.markdown ?? "";
  resetExplain();
  if (typeof workbenchReportDialog.showModal === "function") {
    workbenchReportDialog.showModal();
  } else {
    workbenchReportDialog.setAttribute("open", "");
  }
  workbenchReportDownload?.focus();
}

function resetExplain() {
  if (!workbenchExplain) return;
  workbenchExplain.hidden = true;
  workbenchExplain.textContent = "";
  workbenchExplain.classList.remove("is-error");
  if (workbenchExplainBtn) workbenchExplainBtn.disabled = false;
  if (workbenchExplainQuestion) workbenchExplainQuestion.value = "";
}

async function requestExplanation() {
  if (!workbenchExplain || !workbenchExplainBtn) return;
  if (!lastReportMarkdown) {
    workbenchExplain.hidden = false;
    workbenchExplain.classList.add("is-error");
    workbenchExplain.textContent = "Load datasets and a comparison first.";
    return;
  }
  const question = workbenchExplainQuestion?.value.trim() ?? "";
  workbenchExplainBtn.disabled = true;
  workbenchExplain.hidden = false;
  workbenchExplain.classList.remove("is-error");
  workbenchExplain.textContent = question
    ? "Answering your question… this can take up to a minute."
    : "Generating a plain-language explanation… this can take up to a minute.";
  try {
    const result = await fetch("/api/explain", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ context: { report: lastReportMarkdown }, question }),
    });
    const data = await result.json().catch(() => ({}));
    if (!result.ok) {
      throw new Error(data.error ?? `Request failed (${result.status})`);
    }
    workbenchExplain.textContent = data.text ?? "No explanation returned.";
  } catch (error) {
    workbenchExplain.classList.add("is-error");
    workbenchExplain.textContent = `Could not generate explanation: ${error.message}`;
  } finally {
    workbenchExplainBtn.disabled = false;
  }
}

function closeReportPreview() {
  if (!workbenchReportDialog) return;
  if (typeof workbenchReportDialog.close === "function") {
    workbenchReportDialog.close();
  } else {
    workbenchReportDialog.removeAttribute("open");
  }
}

function renderReportPreview(preview) {
  if (!workbenchReportPreview) return;
  workbenchReportPreview.innerHTML = "";
  workbenchReportPreview.append(
    element("div", { className: `report-preview-status ${preview.ready ? "is-ready" : "is-draft"}` },
      element("span", {}, preview.ready ? "Ready for export" : "Draft"),
      element("strong", {}, preview.status),
    ),
    element("div", { className: "report-preview-grid" },
      element("section", { className: "report-preview-section" },
        element("span", {}, "Scenario"),
        element("strong", {}, preview.scenario.label),
        element("p", {}, preview.scenario.description),
      ),
      element("section", { className: "report-preview-section" },
        element("span", {}, "Baseline"),
        element("strong", {}, preview.baseline?.name ?? "Static demo dataset"),
        element("p", {}, preview.baseline
          ? `${preview.baseline.channels} channels · ${preview.baseline.frames} frames`
          : "Import a baseline to compare saved sessions."),
      ),
      element("section", { className: "report-preview-section" },
        element("span", {}, "Datasets"),
        element("strong", {}, String(preview.datasets.length)),
        element("p", {}, `${preview.comparisons.length} comparison${preview.comparisons.length === 1 ? "" : "s"} in scope`),
      ),
      element("section", { className: "report-preview-section" },
        element("span", {}, "Quality checks"),
        element("strong", {}, String(preview.qualityFlags.length)),
        element("p", {}, preview.qualityFlags.slice(0, 2).map((flag) => flag.message).join(" · ") || "No flags"),
      ),
    ),
    element("pre", { className: "report-markdown", tabIndex: 0 }, preview.markdown),
  );
}

function downloadWorkbenchReport() {
  const report = generateWorkbenchReport({
    sessions: getSessions(),
    fallbackData: activeData,
    baselineId: getBaselineId(),
    scenarioId: activeScenarioId,
    generatedAt: new Date(),
  });
  const blob = new Blob([report], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = element("a", {
    href: url,
    download: `neuromouse-analysis-report-${new Date().toISOString().slice(0, 10)}.md`,
  });
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function openComparisonSuite() {
  const advancedButton = document.querySelector("#advanced-toggle");
  const advancedViews = document.querySelector("#advanced-views");
  if (advancedButton?.getAttribute("aria-expanded") !== "true") {
    advancedButton?.click();
  } else if (advancedViews) {
    advancedViews.style.display = "grid";
  }
  document.querySelector(".session-sidebar")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function syncSessionState() {
  const primary = getBaselineSession(activeData);
  if (!primary?.data) return;
  configureChannels(primary.data.meta.channels);
  configurePlayback(primary.data.geometry.time.length);
  updateHeaderStatus(primary.data);
  updateSelectedChannelLabel(getChannel());
}

function updateHeaderStatus(data) {
  const channelCount = data?.meta?.channels?.length ?? 0;
  const frameCount = data?.geometry?.time?.length ?? 0;
  if (headerChannels) headerChannels.textContent = channelCount ? String(channelCount) : "--";
  if (headerFrames) headerFrames.textContent = frameCount ? String(frameCount) : "--";
}

function describeMontage(data) {
  const channelCount = data?.meta?.channels?.length ?? 0;
  const frameCount = data?.geometry?.time?.length ?? 0;
  return `${channelCount} ch, ${frameCount} frames`;
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

  renderBaselineOptions(baselineSelect, sessions, "No imported baselines");
  renderBaselineOptions(workbenchBaselineSelect, sessions, "Demo dataset");

  if (!sessions.length) setSessionMessage("Add sessions to compare");
}

function renderBaselineOptions(select, sessions, emptyLabel) {
  if (!select) return;
  select.innerHTML = "";
  const baselineId = getBaselineId();

  if (!sessions.length) {
    select.append(element("option", { value: "", selected: true }, emptyLabel));
    select.disabled = true;
    return;
  }

  sessions.forEach((session) => {
    select.append(element("option", {
      value: session.id,
      selected: session.id === baselineId,
    }, session.name));
  });
  select.disabled = false;
}

function setSessionMessage(message, isError = false) {
  if (!sessionMessage) return;
  sessionMessage.textContent = message;
  sessionMessage.classList.toggle("is-error", isError);
}

function createTooltip(node) {
  return {
    show(x, y, html) {
      node.replaceChildren(sanitizeTooltipHtml(html));
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

function sanitizeTooltipHtml(html) {
  const template = document.createElement("template");
  template.innerHTML = html;
  const allowedTags = new Set(["BR", "SPAN", "STRONG"]);
  const elements = Array.from(template.content.querySelectorAll("*"));

  elements.forEach((elementNode) => {
    if (!allowedTags.has(elementNode.nodeName)) {
      elementNode.replaceWith(document.createTextNode(elementNode.textContent ?? ""));
      return;
    }

    Array.from(elementNode.attributes).forEach((attribute) => {
      elementNode.removeAttribute(attribute.name);
    });
  });

  return template.content;
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
