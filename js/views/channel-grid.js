import {
  getChannel,
  getChannelFilter,
  getFrame,
  getIsPlaying,
  getLiveState,
  getVisibleChannels,
  onChannelChange,
  onDisplayChange,
  onFrameChange,
  onLiveChange,
  setChannel,
} from "../state.js";
import { ACTIVE_COLOR, CHART_BACKGROUND, MUTED_COLOR, colorScale, extent, formatNumber } from "./chart-utils.js";

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
  const caption = document.querySelector("#grid-caption");
  const summary = data.channel_summary;
  const byChannel = new Map(summary.map((item) => [item.channel, item]));
  const channelIndexByName = new Map(data.meta.channels.map((channel, index) => [channel, index]));
  const frameTimes = data.geometry.time;
  const frameAlpha = data.geometry.alpha_relative_power;
  const [minPower, maxPower] = extent(summary.map((item) => item.alpha_relative_power));
  const [minFramePower, maxFramePower] = extent(frameAlpha);

  function render() {
    const selected = getChannel();
    const visible = new Set(getVisibleChannels(data));
    const filter = getChannelFilter();
    const frame = getFrame();
    const live = getLiveState();
    const liveFrame = live.history.at(-1);
    const useLive = live.connected && liveFrame?.metrics;
    const livePowers = useLive
      ? data.meta.channels.map((channel) => liveFrame.metrics[channel]?.alpha_relative_power).filter((value) => Number.isFinite(Number(value)))
      : [];
    const useFrame = !useLive && (getIsPlaying() || frame > 0);
    const [minLivePower, maxLivePower] = extent(livePowers);
    const rangeMin = useLive ? minLivePower : (useFrame ? minFramePower : minPower);
    const rangeMax = useLive ? maxLivePower : (useFrame ? maxFramePower : maxPower);
    const time = frameTimes[Math.min(frame, frameTimes.length - 1)] ?? 0;

    if (caption) {
      caption.textContent = useLive
        ? `live alpha power @ t=${formatNumber(liveFrame.time, 2)}s`
        : useFrame
        ? `alpha power @ t=${formatNumber(time, 2)}s`
        : "10-20 layout | color: alpha rel. power";
    }

    root.innerHTML = "";
    const svg = element("svg", {
      viewBox: "0 0 420 492",
      role: "group",
      "aria-label": "10-20 EEG channel map",
      overflow: "hidden",
      style: `background:${CHART_BACKGROUND}`,
    });

    svg.append(
      element("ellipse", {
        cx: 210,
        cy: 205,
        rx: 165,
        ry: 185,
        fill: "none",
        stroke: "rgba(255,255,255,0.12)",
        "stroke-width": 1,
      }),
      element("path", {
        d: "M196 25 L210 6 L224 25",
        fill: "none",
        stroke: "rgba(255,255,255,0.12)",
        "stroke-width": 1,
        "stroke-linejoin": "round",
      }),
      element("path", {
        d: "M46 185 C12 204 12 252 46 272",
        fill: "none",
        stroke: "rgba(255,255,255,0.12)",
        "stroke-width": 1,
      }),
      element("path", {
        d: "M374 185 C408 204 408 252 374 272",
        fill: "none",
        stroke: "rgba(255,255,255,0.12)",
        "stroke-width": 1,
      }),
    );

    for (const [channel, [nx, ny]] of Object.entries(EEG_10_20)) {
      const item = byChannel.get(channel);
      const channelIndex = channelIndexByName.get(channel);
      const framePower = frameAlpha[channelIndex]?.[frame];
      const livePower = liveFrame?.metrics?.[channel]?.alpha_relative_power;
      const power = useLive && Number.isFinite(Number(livePower))
        ? Number(livePower)
        : useFrame && Number.isFinite(framePower)
        ? framePower
        : item?.alpha_relative_power ?? 0;
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
          fill: colorScale(power, rangeMin, rangeMax),
          stroke: active ? ACTIVE_COLOR : "rgba(255,255,255,0.16)",
          "stroke-width": active ? 2 : 0.5,
          opacity: isVisible ? 1 : 0.22,
          style: item?.has_clear_alpha_peak && isVisible ? "filter:drop-shadow(0 0 4px rgba(0,212,160,0.6))" : "",
        }),
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
          `<strong>${channel}</strong><br>alpha rel. power ${formatNumber(power, 3)}<br>${useLive ? `live t=${formatNumber(liveFrame.time, 2)} sec<br>` : useFrame ? `t=${formatNumber(time, 2)} sec<br>` : ""}${item?.region ?? ""} · ${item?.hemisphere ?? ""}<br>${item?.has_clear_alpha_peak ? "alpha peak marker" : "no alpha peak marker"}`,
        );
      });
      group.addEventListener("mouseleave", tooltip.hide);
      svg.append(group);
    }

    svg.append(...colorbar(rangeMin, rangeMax));
    root.append(svg);
  }

  function colorbar(minPower, maxPower) {
    const parts = [
      element("defs", {}, [
        element("linearGradient", { id: "alpha-power-gradient", x1: "0%", x2: "100%", y1: "0%", y2: "0%" }, [
          element("stop", { offset: "0%", "stop-color": "#0a0a1a" }),
          element("stop", { offset: "55%", "stop-color": "#005e56" }),
          element("stop", { offset: "100%", "stop-color": ACTIVE_COLOR }),
        ]),
      ]),
      element("text", {
        x: 44,
        y: 425,
        fill: MUTED_COLOR,
        "font-size": 11,
        "font-weight": 600,
        "font-family": "\"SF Mono\", \"Menlo\", \"Monaco\", \"Courier New\", monospace",
      }, "alpha rel. power"),
      element("rect", {
        x: 154,
        y: 416,
        width: 180,
        height: 12,
        rx: 6,
        fill: "url(#alpha-power-gradient)",
      }),
    ];
    parts.push(
      element("text", { x: 154, y: 444, fill: MUTED_COLOR, "font-size": 10, "font-family": "\"SF Mono\", \"Menlo\", \"Monaco\", \"Courier New\", monospace", "text-anchor": "middle" }, formatNumber(minPower, 2)),
      element("text", { x: 334, y: 444, fill: MUTED_COLOR, "font-size": 10, "font-family": "\"SF Mono\", \"Menlo\", \"Monaco\", \"Courier New\", monospace", "text-anchor": "middle" }, formatNumber(maxPower, 2)),
      element("circle", { cx: 156, cy: 470, r: 6, fill: "none", stroke: ACTIVE_COLOR, "stroke-width": 2 }),
      element("text", { x: 170, y: 474, fill: MUTED_COLOR, "font-size": 10, "font-family": "\"SF Mono\", \"Menlo\", \"Monaco\", \"Courier New\", monospace" }, "selected"),
      element("circle", { cx: 264, cy: 470, r: 7, fill: ACTIVE_COLOR, opacity: 0.62, style: "filter:drop-shadow(0 0 4px rgba(0,212,160,0.6))" }),
      element("text", { x: 280, y: 474, fill: MUTED_COLOR, "font-size": 10, "font-family": "\"SF Mono\", \"Menlo\", \"Monaco\", \"Courier New\", monospace" }, "alpha peak"),
    );
    return parts;
  }

  onChannelChange(render);
  onDisplayChange(render);
  onFrameChange(render);
  onLiveChange(render);
  render();
}

function element(name, attrs = {}, text = "") {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  if (Array.isArray(text)) node.append(...text);
  else if (text) node.textContent = text;
  return node;
}
