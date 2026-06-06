import {
  ConditionMonitor,
  MONITOR_METRICS,
  MONITOR_OPERATORS,
  createDefaultCondition,
  latestGeometryTime,
  latestMetricValue,
  serializeTriggerLogCSV,
} from "../monitor.js";
import { formatNumber } from "./chart-utils.js";

const LOG_LIMIT = 50;

export function initMonitorView(root, data) {
  if (!root) return null;

  let channels = channelsFromData(data);
  const condition = createDefaultCondition(defaultChannel(channels));
  const monitor = new ConditionMonitor();
  let lastValue = null;
  let lastTime = 0;
  let isLive = false;
  let highlightedEvent = null;

  root.innerHTML = "";

  const staticMessage = element("div", { className: "monitor-static", role: "status" }, "Monitor available in live mode");
  const liveShell = element("div", { className: "monitor-live" });

  const title = element("h2", { id: "monitor-title" }, "Closed-Loop Monitor");
  const builder = element("div", { className: "monitor-builder" });
  const channelSelect = createLabeledSelect("monitor-channel", "Channel");
  const metricSelect = createLabeledSelect("monitor-metric", "Metric");
  const operatorSelect = createLabeledSelect("monitor-operator", "Op");
  const thresholdInput = createLabeledInput("monitor-threshold", "Threshold", {
    type: "number",
    step: "0.01",
    value: Number(condition.threshold).toFixed(2),
  });
  const durationInput = createLabeledInput("monitor-duration", "Duration", {
    type: "number",
    step: "0.5",
    min: "0.5",
    value: Number(condition.duration_sec).toFixed(1),
  }, "s");

  builder.append(
    channelSelect.wrapper,
    metricSelect.wrapper,
    operatorSelect.wrapper,
    thresholdInput.wrapper,
    durationInput.wrapper,
  );

  const enabledInput = element("input", {
    id: "monitor-enabled",
    name: "monitor-enabled",
    type: "checkbox",
    "aria-label": "Enable closed-loop monitor",
  });
  const enabledToggle = element("label", { className: "monitor-toggle", htmlFor: "monitor-enabled" },
    enabledInput,
    element("span", { className: "monitor-led", "aria-hidden": "true" }),
    "Enable",
  );
  const clearButton = element("button", { type: "button" }, "Clear Log");
  const exportButton = element("button", { type: "button" }, "Export CSV");
  const actions = element("div", { className: "monitor-actions" }, enabledToggle, clearButton, exportButton);

  const stateText = element("strong", { className: "monitor-state is-idle" }, "● IDLE");
  const progressFill = element("div", { className: "progress-fill" });
  const progressTrack = element("div", { className: "progress-track", "aria-hidden": "true" }, progressFill);
  const progressText = element("span", { className: "monitor-progress-text" }, "Waiting...");
  const currentText = element("div", { className: "monitor-current" }, "Current metric unavailable");
  const status = element("div", { className: "monitor-status", "aria-live": "polite" },
    element("div", { className: "monitor-status-row" },
      element("span", { className: "monitor-kicker" }, "Status"),
      stateText,
      progressTrack,
      progressText,
    ),
    element("div", { className: "monitor-status-row monitor-status-current" },
      element("span", { className: "monitor-kicker" }, "Current"),
      currentText,
    ),
  );

  const logBody = element("tbody");
  const logTable = element("table", { className: "monitor-log-table" },
    element("thead", {},
      element("tr", {},
        element("th", { scope: "col" }, "Time (s)"),
        element("th", { scope: "col" }, "Channel"),
        element("th", { scope: "col" }, "Metric"),
        element("th", { scope: "col" }, "Value"),
        element("th", { scope: "col" }, "Condition"),
      ),
    ),
    logBody,
  );
  const logEmpty = element("div", { className: "monitor-log-empty" }, "No triggers yet");
  const logWrap = element("div", { className: "monitor-log", role: "region", "aria-label": "Trigger log" }, logTable, logEmpty);

  liveShell.append(
    element("div", { className: "monitor-head" }, title, actions),
    builder,
    status,
    logWrap,
  );
  root.append(staticMessage, liveShell);

  populateControls();
  bindEvents();
  renderMode();
  renderStatus();
  renderLog();

  monitor.onTrigger((event) => {
    highlightedEvent = event;
    renderLog();
    renderStatus();
    window.setTimeout(() => {
      if (highlightedEvent === event) {
        highlightedEvent = null;
        renderLog();
      }
      renderStatus();
    }, monitor.autoResetMs + 20);
  });

  return {
    condition,
    monitor,
    setLiveState(state) {
      const nextLive = Boolean(state?.connected || state?.status === "live");
      if (nextLive === isLive) return;
      isLive = nextLive;
      if (!isLive) {
        lastValue = null;
        lastTime = 0;
        monitor.reset();
      }
      renderMode();
      renderStatus();
    },
    handleFrame(frame) {
      syncChannels(frame?.meta?.channels ?? frame?.channel_names);
      lastValue = latestMetricValue(frame, condition);
      lastTime = latestGeometryTime(frame);
      monitor.update(lastValue, lastTime, condition);
      renderStatus();
    },
  };

  function populateControls() {
    populateSelect(channelSelect.select, channels.map((channel) => ({ value: channel, label: channel })), condition.channel);
    populateSelect(metricSelect.select, MONITOR_METRICS.map((metric) => ({ value: metric.key, label: metric.label })), condition.metric);
    populateSelect(operatorSelect.select, MONITOR_OPERATORS.map((operator) => ({ value: operator, label: operator })), condition.operator);
    enabledInput.checked = condition.enabled;
  }

  function bindEvents() {
    channelSelect.select.addEventListener("change", () => {
      condition.channel = channelSelect.select.value;
      resetConditionProgress();
    });
    metricSelect.select.addEventListener("change", () => {
      condition.metric = metricSelect.select.value;
      resetConditionProgress();
    });
    operatorSelect.select.addEventListener("change", () => {
      condition.operator = operatorSelect.select.value;
      resetConditionProgress();
    });
    thresholdInput.input.addEventListener("input", () => {
      condition.threshold = Number(thresholdInput.input.value);
      resetConditionProgress();
    });
    durationInput.input.addEventListener("input", () => {
      condition.duration_sec = Math.max(0.5, Number(durationInput.input.value) || 0.5);
      resetConditionProgress();
    });
    enabledInput.addEventListener("change", () => {
      condition.enabled = enabledInput.checked;
      resetConditionProgress();
    });
    clearButton.addEventListener("click", () => {
      monitor.clearLog();
      highlightedEvent = null;
      renderLog();
    });
    exportButton.addEventListener("click", () => {
      exportCSV(monitor.log);
    });
  }

  function resetConditionProgress() {
    monitor.reset();
    renderStatus();
  }

  function syncChannels(nextChannels) {
    if (!Array.isArray(nextChannels) || !nextChannels.length || nextChannels.join("\u0000") === channels.join("\u0000")) {
      return;
    }
    channels = nextChannels.slice();
    if (!channels.includes(condition.channel)) condition.channel = defaultChannel(channels);
    populateSelect(channelSelect.select, channels.map((channel) => ({ value: channel, label: channel })), condition.channel);
  }

  function renderMode() {
    root.classList.toggle("live-mode", isLive);
    root.classList.toggle("static-mode", !isLive);
  }

  function renderStatus() {
    const state = condition.enabled ? monitor.state : "IDLE";
    const metric = metricLabel(condition.metric);
    const valueLabel = lastValue == null ? "n/a" : formatNumber(lastValue, 3);
    const duration = Number(condition.duration_sec) || 0.5;
    const elapsed = monitor.state === "BUILDING" && monitor.buildStart != null
      ? Math.max(0, lastTime - monitor.buildStart)
      : 0;
    const progress = condition.enabled ? monitor.getProgress(lastTime, condition) : 0;

    stateText.className = `monitor-state is-${state.toLowerCase()}`;
    stateText.textContent = state === "TRIGGERED" ? "✓ TRIGGERED" : `● ${state}`;
    progressFill.style.width = `${progress * 100}%`;

    if (!condition.enabled) {
      progressText.textContent = "Disabled";
    } else if (state === "BUILDING") {
      progressText.textContent = `${formatNumber(elapsed, 1)} / ${formatNumber(duration, 1)} s`;
    } else if (state === "TRIGGERED") {
      progressText.textContent = `${formatNumber(duration, 1)} s condition met`;
    } else {
      progressText.textContent = "Waiting...";
    }

    currentText.textContent = `${metric} · ${condition.channel} = ${valueLabel}`;
  }

  function renderLog() {
    const events = monitor.log.slice(-LOG_LIMIT).reverse();
    logBody.innerHTML = "";
    for (const event of events) {
      const row = element("tr", { className: event === highlightedEvent ? "is-new" : "" },
        element("td", {}, formatNumber(event.timestamp_sec, 2)),
        element("td", {}, event.channel),
        element("td", {}, metricLabel(event.metric)),
        element("td", {}, formatNumber(event.value, 3)),
        element("td", {}, event.condition),
      );
      logBody.append(row);
    }
    logEmpty.hidden = events.length > 0;
    logTable.hidden = events.length === 0;
  }
}

function channelsFromData(data) {
  return Array.isArray(data?.meta?.channels) ? data.meta.channels.slice() : [];
}

function defaultChannel(channels) {
  return channels.includes("Pz") ? "Pz" : (channels[0] ?? "Cz");
}

function metricLabel(key) {
  return MONITOR_METRICS.find((metric) => metric.key === key)?.label ?? key;
}

function createLabeledSelect(id, label) {
  const select = element("select", { id, name: id });
  return {
    select,
    wrapper: element("label", { className: "monitor-field", htmlFor: id },
      element("span", {}, label),
      select,
    ),
  };
}

function createLabeledInput(id, label, attrs, suffix = "") {
  const input = element("input", {
    id,
    name: id,
    autocomplete: "off",
    ...attrs,
  });
  const control = suffix
    ? element("div", { className: "monitor-input-suffix" }, input, element("span", {}, suffix))
    : input;
  return {
    input,
    wrapper: element("label", { className: "monitor-field", htmlFor: id },
      element("span", {}, label),
      control,
    ),
  };
}

function populateSelect(select, rows, selectedValue) {
  select.innerHTML = "";
  rows.forEach((row) => {
    const option = element("option", { value: row.value }, row.label);
    option.selected = row.value === selectedValue;
    select.append(option);
  });
}

function exportCSV(log) {
  const blob = new Blob([serializeTriggerLogCSV(log)], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement("a"), {
    href: url,
    download: `speedmouse-triggers-${Date.now()}.csv`,
  });
  link.click();
  URL.revokeObjectURL(url);
}

function element(name, attrs = {}, ...children) {
  const node = document.createElement(name);
  Object.entries(attrs).forEach(([key, value]) => {
    if (value == null) return;
    if (key === "className") node.className = value;
    else if (key === "htmlFor") node.htmlFor = value;
    else if (key === "hidden") node.hidden = Boolean(value);
    else node.setAttribute(key, value);
  });
  children.flat().forEach((child) => {
    if (child == null) return;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  });
  return node;
}
