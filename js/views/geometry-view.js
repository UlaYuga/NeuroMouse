import {
  getChannel,
  getFrame,
  getLiveState,
  getTimeHover,
  onChannelChange,
  onFrameChange,
  onLiveChange,
  onTimeHoverChange,
  setTimeHover,
} from "../state.js";
import {
  ACTIVE_COLOR,
  AXIS_COLOR,
  GRID_COLOR,
  MUTED_COLOR,
  SECONDARY_COLOR,
  canvasPoint,
  clear,
  drawLine,
  formatNumber,
  invertLinear,
  nearestIndex,
  observeCanvas,
  paddedExtent,
  resizeCanvas,
  scaleLinear,
} from "./chart-utils.js";

const METRICS = [
  ["centroid", "Spectral Centroid", "Hz"],
  ["spread", "Spectral Spread", "Hz"],
  ["entropy", "Spectral Entropy", "bits"],
  ["flatness", "Spectral Flatness", "ratio"],
  ["edge95", "Edge Frequency 95%", "Hz"],
  ["alpha_relative_power", "Alpha Rel. Power", ""],
];

export function initGeometryView(data, tooltip) {
  const canvas = document.querySelector("#geometry-chart");
  const caption = document.querySelector("#geometry-caption");
  const times = data.geometry.time;
  const margins = { left: 158, right: 18, top: 14, bottom: 30 };
  let hover = null;

  function activeSeries() {
    const live = getLiveState();
    if (live.history.length > 1) {
      return {
        mode: "live",
        times: live.history.map((frame) => frame.time),
        metric(key, channel) {
          return live.history.map((frame) => frame.metrics[channel]?.[key]);
        },
      };
    }
    return {
      mode: "static",
      times,
      metric(key, channel) {
        return data.geometry[key][data.meta.channels.indexOf(channel)];
      },
    };
  }

  function geometry(width, height, series) {
    const plotX = margins.left;
    const plotY = margins.top;
    const plotW = width - margins.left - margins.right;
    const plotH = height - margins.top - margins.bottom;
    const panelH = plotH / METRICS.length;
    return {
      plotX,
      plotY,
      plotW,
      plotH,
      panelH,
      xScale: scaleLinear(series.times[0], series.times.at(-1), plotX, plotX + plotW),
    };
  }

  function draw() {
    const { ctx, width, height } = resizeCanvas(canvas);
    clear(ctx, width, height);
    const series = activeSeries();
    const g = geometry(width, height, series);
    const channel = getChannel();
    caption.textContent = `Sliding spectral geometry | channel: ${channel} | ${series.mode}`;

    METRICS.forEach(([key, label, unit], metricIndex) => {
      const y0 = g.plotY + metricIndex * g.panelH;
      const panelTop = y0 + 8;
      const panelBottom = y0 + g.panelH - 12;
      const values = series.metric(key, channel);
      const [minY, maxY] = paddedExtent([values], 0.1);
      const yScale = scaleLinear(minY, maxY, panelBottom, panelTop);

      ctx.strokeStyle = metricIndex === METRICS.length - 1 ? "rgba(241,235,217,0.22)" : GRID_COLOR;
      ctx.beginPath();
      ctx.moveTo(g.plotX, y0 + g.panelH);
      ctx.lineTo(g.plotX + g.plotW, y0 + g.panelH);
      ctx.stroke();

      ctx.fillStyle = AXIS_COLOR;
      ctx.font = "700 11px SFMono-Regular, Roboto Mono, Cascadia Mono, ui-monospace, monospace";
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText(label, 14, panelTop - 1);
      ctx.fillStyle = MUTED_COLOR;
      ctx.font = "10px SFMono-Regular, Roboto Mono, Cascadia Mono, ui-monospace, monospace";
      ctx.fillText(unit || "—", 14, panelTop + 15);
      ctx.textAlign = "right";
      ctx.fillText(formatNumber(maxY, key.includes("alpha") || key === "flatness" || key === "entropy" ? 2 : 1), g.plotX - 8, panelTop - 2);
      ctx.fillText(formatNumber(minY, key.includes("alpha") || key === "flatness" || key === "entropy" ? 2 : 1), g.plotX - 8, panelBottom - 9);

      drawLine(
        ctx,
        series.times.map((time, index) => ({
          x: g.xScale(time),
          y: yScale(values[index]),
        })),
        metricIndex === 5 ? SECONDARY_COLOR : ACTIVE_COLOR,
        1.8,
      );
    });

    ctx.strokeStyle = "rgba(241,235,217,0.22)";
    ctx.strokeRect(g.plotX, g.plotY, g.plotW, g.plotH);

    if (series.mode === "static") {
      const frameIndex = Math.min(series.times.length - 1, getFrame());
      const x = g.xScale(series.times[frameIndex]);
      ctx.save();
      ctx.strokeStyle = SECONDARY_COLOR;
      ctx.globalAlpha = 0.72;
      ctx.lineWidth = 1.2;
      ctx.setLineDash([4, 5]);
      ctx.beginPath();
      ctx.moveTo(x, g.plotY);
      ctx.lineTo(x, g.plotY + g.plotH);
      ctx.stroke();
      ctx.restore();
    }

    ctx.fillStyle = MUTED_COLOR;
    ctx.font = "10px SFMono-Regular, Roboto Mono, Cascadia Mono, ui-monospace, monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const ticks = series.mode === "live"
      ? [series.times[0], series.times.at(-1)].filter((value, index, arr) => index === 0 || value !== arr[0])
      : [0, 20, 40, 60, 80, 100];
    ticks.forEach((tick) => {
      const x = g.xScale(tick);
      ctx.strokeStyle = "rgba(241,235,217,0.12)";
      ctx.beginPath();
      ctx.moveTo(x, g.plotY + g.plotH - 6);
      ctx.lineTo(x, g.plotY + g.plotH);
      ctx.stroke();
      ctx.fillText(series.mode === "live" ? formatNumber(tick, 1) : String(tick), x, g.plotY + g.plotH + 8);
    });
    ctx.fillText(series.mode === "live" ? "live sec" : "sec", g.plotX + g.plotW / 2, g.plotY + g.plotH + 22);

    const sharedHover = getTimeHover();
    if (hover || sharedHover) {
      const hoverPoint = hover || sharedHover;
      const x = g.xScale(hoverPoint.time);
      ctx.strokeStyle = "rgba(229,170,47,0.78)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, g.plotY);
      ctx.lineTo(x, g.plotY + g.plotH);
      ctx.stroke();
    }
  }

  function hit(event) {
    const point = canvasPoint(event, canvas);
    const rect = canvas.getBoundingClientRect();
    const series = activeSeries();
    const g = geometry(rect.width, rect.height, series);
    if (point.x < g.plotX || point.x > g.plotX + g.plotW || point.y < g.plotY || point.y > g.plotY + g.plotH) {
      return null;
    }
    const time = invertLinear(series.times[0], series.times.at(-1), g.plotX, g.plotX + g.plotW)(point.x);
    const timeIndex = nearestIndex(series.times, time);
    const channel = getChannel();
    return {
      mode: series.mode,
      time: series.times[timeIndex],
      timeIndex,
      values: Object.fromEntries(METRICS.map(([key]) => [key, series.metric(key, channel)[timeIndex]])),
    };
  }

  canvas.addEventListener("mousemove", (event) => {
    hover = hit(event);
    if (!hover) {
      setTimeHover(null);
      tooltip.hide();
      draw();
      return;
    }
    setTimeHover({ source: "geometry", mode: hover.mode, time: hover.time, timeIndex: hover.timeIndex });
    const rows = METRICS.map(([key, label, unit]) => {
      const suffix = unit ? ` ${unit}` : "";
      const digits = key.includes("alpha") || key === "flatness" || key === "entropy" ? 3 : 2;
      return `${label}: ${formatNumber(hover.values[key], digits)}${suffix}`;
    }).join("<br>");
    tooltip.show(event.clientX, event.clientY, `<strong>${getChannel()} · ${formatNumber(hover.time, 2)} sec · ${hover.mode}</strong><br>${rows}`);
    draw();
  });

  canvas.addEventListener("mouseleave", () => {
    hover = null;
    setTimeHover(null);
    tooltip.hide();
    draw();
  });

  onChannelChange(draw);
  onFrameChange(draw);
  onLiveChange(draw);
  onTimeHoverChange(draw);
  observeCanvas(canvas, draw);
}
