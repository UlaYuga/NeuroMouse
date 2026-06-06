import {
  getChannel,
  getChannelFilter,
  getVisibleChannels,
  onChannelChange,
  onDisplayChange,
  setChannel,
} from "../state.js";
import { ACTIVE_COLOR, SECONDARY_COLOR, colorScale, extent, formatNumber } from "./chart-utils.js";

const EEG_10_20 = {
  Fp1: [0.35, 0.05], Fpz: [0.5, 0.04], Fp2: [0.65, 0.05],
  F7: [0.17, 0.25], F3: [0.35, 0.22], Fz: [0.5, 0.21], F4: [0.65, 0.22], F8: [0.83, 0.25],
  FC5: [0.24, 0.35], FC1: [0.41, 0.33], FC2: [0.59, 0.33], FC6: [0.76, 0.35],
  M1: [0.04, 0.5], T7: [0.12, 0.5], C3: [0.33, 0.5], Cz: [0.5, 0.5], C4: [0.67, 0.5], T8: [0.88, 0.5], M2: [0.96, 0.5],
  CP5: [0.24, 0.65], CP1: [0.41, 0.67], CP2: [0.59, 0.67], CP6: [0.76, 0.65],
  P7: [0.17, 0.75], P3: [0.35, 0.78], Pz: [0.5, 0.79], P4: [0.65, 0.78], P8: [0.83, 0.75],
  POz: [0.5, 0.87],
  O1: [0.38, 0.93], Oz: [0.5, 0.95], O2: [0.62, 0.93],
};

export function initChannelGrid(data, tooltip) {
  const root = document.querySelector("#channel-grid");
  const summary = data.channel_summary;
  const byChannel = new Map(summary.map((item) => [item.channel, item]));
  const [minPower, maxPower] = extent(summary.map((item) => item.alpha_relative_power));

  function render() {
    const selected = getChannel();
    const visible = new Set(getVisibleChannels(data));
    const filter = getChannelFilter();
    root.innerHTML = "";
    const svg = element("svg", {
      viewBox: "0 0 420 460",
      role: "group",
      "aria-label": "10-20 EEG channel map",
      overflow: "hidden",
    });

    svg.append(
      element("ellipse", {
        cx: 210,
        cy: 205,
        rx: 165,
        ry: 185,
        fill: "none",
        stroke: "rgba(241,235,217,0.58)",
        "stroke-width": 2,
      }),
      element("path", {
        d: "M196 25 L210 6 L224 25",
        fill: "none",
        stroke: "rgba(241,235,217,0.58)",
        "stroke-width": 2,
        "stroke-linejoin": "round",
      }),
      element("path", {
        d: "M46 185 C12 204 12 252 46 272",
        fill: "none",
        stroke: "rgba(241,235,217,0.46)",
        "stroke-width": 2,
      }),
      element("path", {
        d: "M374 185 C408 204 408 252 374 272",
        fill: "none",
        stroke: "rgba(241,235,217,0.46)",
        "stroke-width": 2,
      }),
    );

    for (const [channel, [nx, ny]] of Object.entries(EEG_10_20)) {
      const item = byChannel.get(channel);
      const power = item?.alpha_relative_power ?? 0;
      const isVisible = visible.has(channel);
      const group = element("g", {
        class: `electrode${isVisible ? "" : " is-muted"}`,
        tabindex: "0",
        role: "button",
        "aria-label": `${channel}, alpha rel. power ${formatNumber(power, 3)}${filter === "all" || isVisible ? "" : ", filtered out"}`,
      });
      const x = 28 + nx * 364;
      const y = 22 + ny * 360;
      const active = channel === selected;
      group.append(
        element("circle", {
          cx: x,
          cy: y,
          r: 14,
          fill: colorScale(power, minPower, maxPower),
          stroke: active ? "#ffffff" : "rgba(12,15,18,0.72)",
          "stroke-width": active ? 3 : 1.2,
          opacity: isVisible ? 1 : 0.22,
        }),
        ...(item?.has_clear_alpha_peak ? [
          element("circle", {
            cx: x,
            cy: y,
            r: 18,
            fill: "none",
            stroke: SECONDARY_COLOR,
            "stroke-width": 1.5,
            "stroke-dasharray": "2 3",
            opacity: isVisible ? 0.9 : 0.22,
          }),
        ] : []),
        element("text", { x, y: y + 0.5 }, channel),
      );
      group.addEventListener("click", () => setChannel(channel));
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          setChannel(channel);
        }
      });
      group.addEventListener("mouseenter", (event) => {
        tooltip.show(
          event.clientX,
          event.clientY,
          `<strong>${channel}</strong><br>alpha rel. power ${formatNumber(power, 3)}<br>${item?.region ?? ""} · ${item?.hemisphere ?? ""}<br>${item?.has_clear_alpha_peak ? "alpha peak marker" : "no alpha peak marker"}`,
        );
      });
      group.addEventListener("mouseleave", tooltip.hide);
      svg.append(group);
    }

    svg.append(...colorbar(minPower, maxPower));
    root.append(svg);
  }

  function colorbar(minPower, maxPower) {
    const parts = [
      element("text", {
        x: 44,
        y: 425,
        fill: "rgba(205,199,181,0.86)",
        "font-size": 11,
        "font-weight": 700,
        "font-family": "SFMono-Regular, Roboto Mono, Cascadia Mono, ui-monospace, monospace",
      }, "alpha rel. power"),
    ];
    for (let i = 0; i < 36; i += 1) {
      const value = minPower + ((maxPower - minPower) * i) / 35;
      parts.push(element("rect", {
        x: 154 + i * 5,
        y: 416,
        width: 5,
        height: 12,
        fill: colorScale(value, minPower, maxPower),
      }));
    }
    parts.push(
      element("text", { x: 154, y: 444, fill: "rgba(205,199,181,0.86)", "font-size": 10, "font-family": "SFMono-Regular, Roboto Mono, Cascadia Mono, ui-monospace, monospace", "text-anchor": "middle" }, formatNumber(minPower, 2)),
      element("text", { x: 334, y: 444, fill: "rgba(205,199,181,0.86)", "font-size": 10, "font-family": "SFMono-Regular, Roboto Mono, Cascadia Mono, ui-monospace, monospace", "text-anchor": "middle" }, formatNumber(maxPower, 2)),
      element("circle", { cx: 346, cy: 422, r: 6, fill: "none", stroke: ACTIVE_COLOR, "stroke-width": 2 }),
      element("text", { x: 358, y: 426, fill: "rgba(205,199,181,0.86)", "font-size": 10, "font-family": "SFMono-Regular, Roboto Mono, Cascadia Mono, ui-monospace, monospace" }, "selected"),
      element("circle", { cx: 346, cy: 444, r: 7, fill: "none", stroke: SECONDARY_COLOR, "stroke-width": 1.5, "stroke-dasharray": "2 3" }),
      element("text", { x: 358, y: 448, fill: "rgba(205,199,181,0.86)", "font-size": 10, "font-family": "SFMono-Regular, Roboto Mono, Cascadia Mono, ui-monospace, monospace" }, "alpha peak"),
    );
    return parts;
  }

  onChannelChange(render);
  onDisplayChange(render);
  render();
}

function element(name, attrs = {}, text = "") {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  if (text) node.textContent = text;
  return node;
}
