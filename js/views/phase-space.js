import * as defaultState from "../state.js";
import { createDisposables } from "../disposables.js";
import {
  ACTIVE_COLOR,
  CHART_BACKGROUND,
  GRID_COLOR,
  MONO_FONT,
  MUTED_COLOR,
  axisLabels,
  clamp,
  clear,
  formatNumber,
  observeCanvas,
  paddedExtent,
  PLOT_BORDER_COLOR,
  resizeCanvas,
  scaleLinear,
} from "./chart-utils.js";

const METRICS = [
  ["centroid", "Spectral Centroid", "Hz"],
  ["spread", "Spectral Spread", "Hz"],
  ["entropy", "Spectral Entropy", ""],
  ["flatness", "Spectral Flatness", ""],
  ["edge95", "Edge Frequency 95%", "Hz"],
  ["alpha_relative_power", "Alpha Relative Power", ""],
];

const MODE_DELAY = "delay";
const MODE_SCATTER = "scatter";

export function initPhaseSpace(root, data, context = {}) {
  if (!root) return;

  const state = context.state ?? defaultState;
  const document = context.document ?? globalThis.document;
  const window = context.window ?? globalThis.window;
  const {
    getChannel,
    getChannelIndex,
    getFrame,
    getLiveState,
    onChannelChange,
    onFrameChange,
    onLiveChange,
  } = state;
  const disposables = createDisposables();
  function element(name, attrs = {}, ...children) {
    const node = document.createElement(name);
    Object.entries(attrs).forEach(([key, value]) => {
      if (key === "className") node.className = value;
      else if (key === "htmlFor") node.htmlFor = value;
      else node.setAttribute(key, value);
    });
    children.flat().forEach((child) => {
      if (child == null) return;
      node.append(child instanceof window.Node ? child : document.createTextNode(String(child)));
    });
    return node;
  }
  const canvas = element("canvas", {
    id: "phase-space-chart",
    className: "chart chart-phase",
    width: "620",
    height: "400",
    role: "img",
    "aria-label": "Phase space trajectory for the selected channel",
  });
  const title = element("div", { className: "phase-title-line", "aria-live": "polite" });
  const modeGroup = element("div", {
    className: "phase-mode segmented",
    role: "group",
    "aria-label": "Phase space mode",
  });
  const delayButton = element("button", {
    type: "button",
    className: "is-active",
    "aria-label": "Use delay embedding phase space mode",
  }, "Delay Embedding");
  const scatterButton = element("button", {
    type: "button",
    "aria-label": "Use two-metric scatter phase space mode",
  }, "2-Metric Scatter");
  modeGroup.append(delayButton, scatterButton);

  const primarySelect = metricSelect("centroid", "phase-primary-metric", "Phase metric", element);
  const xSelect = metricSelect("centroid", "phase-x-metric", "Phase X metric", element);
  const ySelect = metricSelect("spread", "phase-y-metric", "Phase Y metric", element);
  const tauInput = element("input", {
    type: "number",
    name: "phase-tau",
    inputmode: "numeric",
    min: "1",
    max: "20",
    step: "1",
    value: "5",
    className: "phase-tau",
    "aria-label": "Delay tau",
  });

  const primaryControl = labeledControl("Metric", primarySelect, element);
  const xControl = labeledControl("X metric", xSelect, element);
  const yControl = labeledControl("Y metric", ySelect, element);
  const tauControl = labeledControl("Tau", tauInput, element);
  const controls = element(
    "div",
    { className: "phase-controls" },
    element("div", { className: "phase-control phase-control-mode" }, element("span", {}, "Mode"), modeGroup),
    primaryControl,
    xControl,
    yControl,
    tauControl,
  );

  root.innerHTML = "";
  root.append(controls, title, canvas);

  let mode = MODE_DELAY;
  let metric = "centroid";
  let xMetric = "centroid";
  let yMetric = "spread";
  let tau = 5;

  disposables.listen(delayButton, "click", () => {
    mode = MODE_DELAY;
    updateControls();
    draw();
  });
  disposables.listen(scatterButton, "click", () => {
    mode = MODE_SCATTER;
    updateControls();
    draw();
  });
  disposables.listen(primarySelect, "change", () => {
    metric = primarySelect.value;
    draw();
  });
  disposables.listen(xSelect, "change", () => {
    xMetric = xSelect.value;
    draw();
  });
  disposables.listen(ySelect, "change", () => {
    yMetric = ySelect.value;
    draw();
  });
  disposables.listen(tauInput, "input", () => {
    tau = clamp(Math.round(Number(tauInput.value) || 1), 1, 20);
    tauInput.value = String(tau);
    draw();
  });

  function updateControls() {
    delayButton.classList.toggle("is-active", mode === MODE_DELAY);
    scatterButton.classList.toggle("is-active", mode === MODE_SCATTER);
    primaryControl.hidden = mode !== MODE_DELAY;
    xControl.hidden = mode !== MODE_SCATTER;
    yControl.hidden = mode !== MODE_SCATTER;
  }

  function draw() {
    const { ctx, width, height } = resizeCanvas(canvas);
    clear(ctx, width, height);
    drawDotGrid(ctx, width, height);

    const channel = getChannel();
    const channelIndex = getChannelIndex();
    const selectedMetric = metricLabel(metric);
    const selectedXMetric = metricLabel(xMetric);
    const selectedYMetric = metricLabel(yMetric);
    const xKey = mode === MODE_DELAY ? metric : xMetric;
    const yKey = mode === MODE_DELAY ? metric : yMetric;
    const series = activeSeries(xKey, yKey, channelIndex);
    const xValues = series.xValues;
    const yValues = series.yValues;
    const points = phasePoints(xValues, yValues, tau);
    const displayTitle = mode === MODE_DELAY
      ? `Delay Embedding - ${channel} - ${selectedMetric.label}`
      : `Phase Space - ${channel} - ${selectedXMetric.label} vs ${selectedYMetric.label}`;
    const compactTitle = mode === MODE_DELAY
      ? `${channel} | ${selectedMetric.label} | tau ${tau} | ${series.mode}`
      : `${channel} | ${selectedXMetric.label} vs ${selectedYMetric.label} | tau ${tau} | ${series.mode}`;

    title.textContent = compactTitle;
    canvas.setAttribute("aria-label", `${displayTitle}, tau ${tau}`);

    const margins = { left: 58, right: 18, top: 34, bottom: 48 };
    const plotX = margins.left;
    const plotY = margins.top;
    const plotW = Math.max(80, width - margins.left - margins.right);
    const plotH = Math.max(80, height - margins.top - margins.bottom);

    if (points.length < 2) {
      ctx.fillStyle = MUTED_COLOR;
      ctx.font = `12px ${MONO_FONT}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("Not enough finite points", width / 2, height / 2);
      return;
    }

    const [minX, maxX] = paddedExtent([points.map((point) => point.xValue)], 0.08);
    const [minY, maxY] = paddedExtent([points.map((point) => point.yValue)], 0.08);
    const xScale = scaleLinear(minX, maxX, plotX, plotX + plotW);
    const yScale = scaleLinear(minY, maxY, plotY + plotH, plotY);

    drawGrid(ctx, plotX, plotY, plotW, plotH);
    drawTrajectory(ctx, points, xScale, yScale);
    drawStartDot(ctx, points[0], xScale, yScale);
    drawEndDot(ctx, points.at(-1), xScale, yScale);
    drawPlaybackDot(ctx, points, xScale, yScale, series.mode === "live");
    drawAxes(ctx, {
      plotX,
      plotY,
      plotW,
      plotH,
      minX,
      maxX,
      minY,
      maxY,
      xLabel: mode === MODE_DELAY ? "X(t)" : selectedXMetric.label,
      yLabel: mode === MODE_DELAY ? `Y(t+${tau})` : `${selectedYMetric.label}(t+${tau})`,
    });
  }

  updateControls();
  disposables.add(onChannelChange(draw));
  disposables.add(onFrameChange(draw));
  disposables.add(onLiveChange(draw));
  disposables.add(observeCanvas(canvas, draw));

  function activeSeries(xKey, yKey, channelIndex) {
    const live = getLiveState();
    if (live.history.length > tau + 1) {
      const channel = data.meta.channels[channelIndex];
      return {
        mode: "live",
        xValues: live.history.map((frame) => frame.metrics[channel]?.[xKey]),
        yValues: live.history.map((frame) => frame.metrics[channel]?.[yKey]),
      };
    }
    return {
      mode: "static",
      xValues: data.geometry[xKey]?.[channelIndex] ?? [],
      yValues: data.geometry[yKey]?.[channelIndex] ?? [],
    };
  }

  return disposables.dispose;
}

function phasePoints(xValues, yValues, tau) {
  const count = Math.max(0, Math.min(xValues.length, yValues.length) - tau);
  const points = [];
  for (let index = 0; index < count; index += 1) {
    const xValue = Number(xValues[index]);
    const yValue = Number(yValues[index + tau]);
    if (Number.isFinite(xValue) && Number.isFinite(yValue)) {
      points.push({ index, xValue, yValue });
    }
  }
  return points;
}

function drawGrid(ctx, plotX, plotY, plotW, plotH) {
  ctx.strokeStyle = PLOT_BORDER_COLOR;
  ctx.lineWidth = 1;
  ctx.strokeRect(plotX, plotY, plotW, plotH);

  ctx.strokeStyle = GRID_COLOR;
  for (let i = 1; i < 4; i += 1) {
    const x = plotX + (plotW * i) / 4;
    const y = plotY + (plotH * i) / 4;
    ctx.beginPath();
    ctx.moveTo(x, plotY);
    ctx.lineTo(x, plotY + plotH);
    ctx.moveTo(plotX, y);
    ctx.lineTo(plotX + plotW, y);
    ctx.stroke();
  }
}

function drawDotGrid(ctx, width, height) {
  ctx.save();
  ctx.fillStyle = "rgba(255,255,255,0.03)";
  for (let x = 0; x < width; x += 20) {
    for (let y = 0; y < height; y += 20) {
      ctx.fillRect(x, y, 1, 1);
    }
  }
  ctx.restore();
}

function drawTrajectory(ctx, points, xScale, yScale) {
  ctx.save();
  ctx.lineWidth = 1;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  for (let index = 0; index < points.length - 1; index += 1) {
    const previous = points[index];
    const current = points[index + 1];
    const t = index / Math.max(1, points.length - 1);
    ctx.strokeStyle = phaseColor(t);
    ctx.beginPath();
    ctx.moveTo(xScale(previous.xValue), yScale(previous.yValue));
    ctx.lineTo(xScale(current.xValue), yScale(current.yValue));
    ctx.stroke();
  }
  ctx.restore();
}

function drawStartDot(ctx, point, xScale, yScale) {
  const x = xScale(point.xValue);
  const y = yScale(point.yValue);
  ctx.save();
  ctx.fillStyle = "rgba(0,160,110,0.8)";
  ctx.shadowColor = "transparent";
  ctx.beginPath();
  ctx.arc(x, y, 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawEndDot(ctx, point, xScale, yScale) {
  const x = xScale(point.xValue);
  const y = yScale(point.yValue);
  ctx.save();
  ctx.fillStyle = "#00D4A0";
  ctx.shadowColor = "rgba(0,212,160,0.8)";
  ctx.shadowBlur = 10;
  ctx.beginPath();
  ctx.arc(x, y, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.restore();
}

function drawPlaybackDot(ctx, points, xScale, yScale, isLive) {
  const frame = isLive ? points.at(-1).index : getFrame();
  let nearest = points[0];
  let distance = Math.abs(frame - nearest.index);
  for (const point of points) {
    const nextDistance = Math.abs(frame - point.index);
    if (nextDistance < distance) {
      nearest = point;
      distance = nextDistance;
    }
  }

  const x = xScale(nearest.xValue);
  const y = yScale(nearest.yValue);
  ctx.save();
  ctx.fillStyle = ACTIVE_COLOR;
  ctx.strokeStyle = CHART_BACKGROUND;
  ctx.shadowColor = "rgba(0,212,160,0.8)";
  ctx.shadowBlur = 12;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(x, y, 7, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.shadowBlur = 0;
  ctx.restore();
}

function drawAxes(ctx, g) {
  ctx.save();
  ctx.fillStyle = MUTED_COLOR;
  ctx.font = `10px ${MONO_FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";

  const xTicks = axisLabels(g.minX, g.maxX, g.plotW, 72);
  xTicks.forEach((tick) => {
    const x = scaleLinear(g.minX, g.maxX, g.plotX, g.plotX + g.plotW)(tick);
    ctx.strokeStyle = PLOT_BORDER_COLOR;
    ctx.beginPath();
    ctx.moveTo(x, g.plotY + g.plotH);
    ctx.lineTo(x, g.plotY + g.plotH + 5);
    ctx.stroke();
    ctx.fillText(formatNumber(tick, 2), x, g.plotY + g.plotH + 9);
  });
  ctx.fillText(g.xLabel, g.plotX + g.plotW / 2, g.plotY + g.plotH + 30, g.plotW);

  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  const yTicks = axisLabels(g.minY, g.maxY, g.plotH, 52);
  yTicks.forEach((tick) => {
    const y = scaleLinear(g.minY, g.maxY, g.plotY + g.plotH, g.plotY)(tick);
    ctx.strokeStyle = PLOT_BORDER_COLOR;
    ctx.beginPath();
    ctx.moveTo(g.plotX - 5, y);
    ctx.lineTo(g.plotX, y);
    ctx.stroke();
    ctx.fillText(formatNumber(tick, 2), g.plotX - 8, y);
  });

  ctx.save();
  ctx.translate(15, g.plotY + g.plotH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center";
  ctx.fillText(g.yLabel, 0, 0, g.plotH);
  ctx.restore();
  ctx.restore();
}

function phaseColor(t) {
  const nextT = Math.max(0, Math.min(1, t));
  const r = 0;
  const g = Math.round(100 + nextT * 112);
  const b = Math.round(80 + nextT * 80);
  const a = 0.25 + nextT * 0.75;
  return `rgba(${r},${g},${b},${a})`;
}

function metricLabel(key) {
  const row = METRICS.find(([metric]) => metric === key) ?? METRICS[0];
  return { key: row[0], label: row[1], unit: row[2] };
}

function metricSelect(value, id, label, element) {
  const select = element("select", { id, name: id, "aria-label": label });
  METRICS.forEach(([key, label]) => {
    select.append(element("option", { value: key }, label));
  });
  select.value = value;
  return select;
}

function labeledControl(label, control, element) {
  return element("label", { className: "phase-control" }, element("span", {}, label), control);
}

function element(name, attrs = {}, ...children) {
  const node = document.createElement(name);
  Object.entries(attrs).forEach(([key, value]) => {
    if (key === "className") node.className = value;
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false && value != null) node.setAttribute(key, value);
  });
  children.flat().forEach((child) => {
    if (child == null) return;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  });
  return node;
}
