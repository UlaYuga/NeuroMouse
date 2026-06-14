import * as defaultState from "../state.js";
import { createDisposables } from "../disposables.js";
import { ACTIVE_COLOR, CHART_BACKGROUND, MUTED_COLOR, clamp, formatNumber } from "./chart-utils.js";
import { EEG_10_20 } from "./channel-grid.js";

export function initChannelNetwork(root, data, tooltip, context = {}) {
  const state = context.state ?? defaultState;
  const document = context.document ?? globalThis.document;
  const {
    getChannel,
    getFrame,
    onChannelChange,
    onFrameChange,
    setChannel,
  } = state;
  const section = root?.closest("section");
  if (!root || !data.channel_network) {
    if (section) section.hidden = true;
    return () => {};
  }
  section.hidden = false;

  const disposables = createDisposables();
  let threshold = Number(data.channel_network.threshold_strong ?? 0.7);
  let metric = "composite";
  let showWeak = false;

  function labelText(text) {
    const span = document.createElement("span");
    span.textContent = text;
    return span;
  }

  function option(value, text) {
    const node = document.createElement("option");
    node.value = value;
    node.textContent = text;
    return node;
  }

  function element(name, attrs = {}, text = "") {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (Array.isArray(text)) node.append(...text);
    else if (text) node.textContent = text;
    return node;
  }

  const controls = document.createElement("div");
  controls.className = "network-controls";
  const graphRoot = document.createElement("div");
  graphRoot.className = "network-graph";
  root.innerHTML = "";
  root.append(controls, graphRoot);
  renderControls();

  function renderControls() {
    controls.innerHTML = "";
    const metricLabel = document.createElement("label");
    metricLabel.className = "network-control";
    metricLabel.append(labelText("Metric"));
    const select = document.createElement("select");
    select.name = "network-metric";
    select.setAttribute("aria-label", "Network metric");
    select.append(option("composite", "Composite"));
    Object.keys(data.channel_network.per_metric ?? {}).forEach((key) => {
      select.append(option(key, metricLabelText(key)));
    });
    if (data.phase_synchrony?.plv_static) select.append(option("plv", "PLV alpha"));
    select.value = metric;
    metricLabel.append(select);

    const thresholdLabel = document.createElement("label");
    thresholdLabel.className = "network-control network-threshold";
    const thresholdText = labelText(`Threshold ${formatNumber(threshold, 2)}`);
    thresholdLabel.append(thresholdText);
    const slider = document.createElement("input");
    slider.type = "range";
    slider.name = "network-threshold";
    slider.min = "0.3";
    slider.max = "0.95";
    slider.step = "0.01";
    slider.value = String(threshold);
    slider.setAttribute("aria-label", "Network edge threshold");
    thresholdLabel.append(slider);

    const weakLabel = document.createElement("label");
    weakLabel.className = "network-toggle";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "network-show-weak";
    checkbox.checked = showWeak;
    weakLabel.append(checkbox, document.createTextNode("Show weak"));

    select.addEventListener("change", () => {
      metric = select.value;
      draw();
    });
    slider.addEventListener("input", () => {
      threshold = Number(slider.value);
      thresholdText.textContent = `Threshold ${formatNumber(threshold, 2)}`;
      draw();
    });
    checkbox.addEventListener("change", () => {
      showWeak = checkbox.checked;
      draw();
    });
    controls.append(metricLabel, thresholdLabel, weakLabel);
  }

  function draw() {
    const matrix = activeMatrix();
    const channels = data.channel_network.channels;
    const selected = getChannel();
    const degrees = channels.map((_, i) => (
      channels.reduce((count, __, j) => count + (i !== j && Math.abs(matrix[i]?.[j] ?? 0) >= threshold ? 1 : 0), 0)
    ));
    const maxDegree = Math.max(...degrees, 1);

    graphRoot.innerHTML = "";
    const svg = element("svg", {
      viewBox: "0 0 720 520",
      role: "group",
      "aria-label": "Channel correlation network",
      overflow: "hidden",
      style: `background:${CHART_BACKGROUND}`,
    });
    svg.append(
      element("ellipse", { cx: 360, cy: 228, rx: 250, ry: 205, fill: "none", stroke: "rgba(20,24,26,0.12)", "stroke-width": 1 }),
      element("path", { d: "M342 32 L360 10 L378 32", fill: "none", stroke: "rgba(20,24,26,0.12)", "stroke-width": 1, "stroke-linejoin": "round" }),
    );

    const edgeLayer = element("g", { class: "network-edges" });
    const nodeLayer = element("g", { class: "network-nodes" });
    for (let i = 0; i < channels.length; i += 1) {
      for (let j = i + 1; j < channels.length; j += 1) {
        const rawValue = matrix[i]?.[j] ?? 0;
        const strength = Math.abs(rawValue);
        const strong = strength >= threshold;
        if (!strong && (!showWeak || strength < 0.3)) continue;
        const a = coord(channels[i]);
        const b = coord(channels[j]);
        const selectedEdge = channels[i] === selected || channels[j] === selected;
        const opacity = strong ? (selectedEdge ? 0.88 : 0.52) : 0.12;
        edgeLayer.append(element("line", {
          x1: a.x,
          y1: a.y,
          x2: b.x,
          y2: b.y,
          stroke: edgeColor(strength),
          "stroke-width": strong ? 0.8 + strength * 3.4 : 0.6,
          opacity,
        }));
      }
    }

    channels.forEach((channel, index) => {
      const point = coord(channel);
      const degree = degrees[index];
      const active = channel === selected;
      const group = element("g", {
        class: "network-node",
        tabindex: "0",
        role: "button",
        "aria-label": `${channel}, degree ${degree}`,
      });
      group.append(
        element("circle", {
          cx: point.x,
          cy: point.y,
          r: active ? 13 : 10,
          fill: nodeColor(degree / maxDegree),
          stroke: active ? ACTIVE_COLOR : "rgba(20,24,26,0.22)",
          "stroke-width": active ? 2 : 0.8,
        }),
        element("text", { x: point.x, y: point.y + 23 }, channel),
      );
      group.addEventListener("click", () => setChannel(channel));
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          setChannel(channel);
        }
      });
      group.addEventListener("mouseenter", (event) => {
        tooltip.show(event.clientX, event.clientY, `<strong>${channel}</strong><br>strong degree ${degree}<br>${metricCaption()}`);
      });
      group.addEventListener("mouseleave", tooltip.hide);
      nodeLayer.append(group);
    });

    svg.append(edgeLayer, nodeLayer, legend(maxDegree));
    graphRoot.append(svg);
  }

  function activeMatrix() {
    if (metric === "plv") {
      const sliding = data.phase_synchrony?.plv_sliding;
      const slidingTime = data.phase_synchrony?.plv_sliding_time;
      const frameTime = data.geometry.time[Math.min(getFrame(), data.geometry.time.length - 1)] ?? 0;
      if (sliding?.length && slidingTime?.length && frameTime <= slidingTime.at(-1) + STEP_TOLERANCE) {
        let best = 0;
        let bestDistance = Infinity;
        slidingTime.forEach((time, index) => {
          const distance = Math.abs(time - frameTime);
          if (distance < bestDistance) {
            best = index;
            bestDistance = distance;
          }
        });
        return sliding[best];
      }
      return data.phase_synchrony?.plv_static ?? data.channel_network.composite_correlation;
    }
    if (metric === "composite") return data.channel_network.composite_correlation;
    return data.channel_network.per_metric?.[metric] ?? data.channel_network.composite_correlation;
  }

  function metricCaption() {
    if (metric === "plv") {
      const frame = getFrame();
      const time = data.geometry.time[Math.min(frame, data.geometry.time.length - 1)] ?? 0;
      return `PLV alpha @ t=${formatNumber(time, 2)}s`;
    }
    return metric === "composite" ? "composite correlation" : metricLabelText(metric);
  }

  function coord(channel) {
    const [nx, ny] = EEG_10_20[channel] ?? [0.5, 0.5];
    return {
      x: 56 + nx * 608,
      y: 36 + ny * 394,
    };
  }

  function legend(maxDegree) {
    const group = element("g", { class: "network-legend" });
    group.append(
      element("text", { x: 28, y: 470 }, `${metricCaption()} | edge = |value| >= ${formatNumber(threshold, 2)}`),
      element("text", { x: 28, y: 492 }, `node color = strong degree, max ${maxDegree}`),
    );
    return group;
  }

  disposables.add(onChannelChange(draw));
  disposables.add(onFrameChange(() => {
    if (metric === "plv") draw();
  }));
  draw();
  return disposables.dispose;
}

const STEP_TOLERANCE = 0.25;

function edgeColor(value) {
  const t = clamp((value - 0.3) / 0.7, 0, 1);
  const r = Math.round(90 - t * 90);
  const g = Math.round(94 + t * 118);
  const b = Math.round(100 + t * 60);
  return `rgb(${r},${g},${b})`;
}

function nodeColor(t) {
  const r = Math.round(24 + t * 12);
  const g = Math.round(58 + t * 154);
  const b = Math.round(70 + t * 90);
  return `rgb(${r},${g},${b})`;
}

function metricLabelText(key) {
  return key
    .replace(/_/g, " ")
    .replace("alpha relative power", "alpha power")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function labelText(text) {
  const span = document.createElement("span");
  span.textContent = text;
  return span;
}

function option(value, text) {
  const node = document.createElement("option");
  node.value = value;
  node.textContent = text;
  return node;
}

function element(name, attrs = {}, text = "") {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  if (Array.isArray(text)) node.append(...text);
  else if (text) node.textContent = text;
  return node;
}
