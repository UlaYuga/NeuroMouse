import { getChannel, getChannelIndex, onChannelChange } from "../state.js";
import {
  ACTIVE_COLOR,
  AXIS_COLOR,
  GRID_COLOR,
  MUTED_COLOR,
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

  function geometry(width, height) {
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
      xScale: scaleLinear(times[0], times.at(-1), plotX, plotX + plotW),
    };
  }

  function draw() {
    const { ctx, width, height } = resizeCanvas(canvas);
    clear(ctx, width, height);
    const g = geometry(width, height);
    const channelIndex = getChannelIndex();
    const channel = getChannel();
    caption.textContent = `Sliding spectral geometry | channel: ${channel}`;

    METRICS.forEach(([key, label, unit], metricIndex) => {
      const y0 = g.plotY + metricIndex * g.panelH;
      const panelTop = y0 + 8;
      const panelBottom = y0 + g.panelH - 12;
      const values = data.geometry[key][channelIndex];
      const [minY, maxY] = paddedExtent([values], 0.1);
      const yScale = scaleLinear(minY, maxY, panelBottom, panelTop);

      ctx.strokeStyle = metricIndex === METRICS.length - 1 ? "rgba(240,244,247,0.2)" : GRID_COLOR;
      ctx.beginPath();
      ctx.moveTo(g.plotX, y0 + g.panelH);
      ctx.lineTo(g.plotX + g.plotW, y0 + g.panelH);
      ctx.stroke();

      ctx.fillStyle = AXIS_COLOR;
      ctx.font = "700 11px ui-sans-serif, system-ui, sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText(label, 14, panelTop - 1);
      ctx.fillStyle = MUTED_COLOR;
      ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
      ctx.fillText(unit || "—", 14, panelTop + 15);
      ctx.textAlign = "right";
      ctx.fillText(formatNumber(maxY, key.includes("alpha") || key === "flatness" || key === "entropy" ? 2 : 1), g.plotX - 8, panelTop - 2);
      ctx.fillText(formatNumber(minY, key.includes("alpha") || key === "flatness" || key === "entropy" ? 2 : 1), g.plotX - 8, panelBottom - 9);

      drawLine(
        ctx,
        times.map((time, index) => ({
          x: g.xScale(time),
          y: yScale(values[index]),
        })),
        metricIndex === 5 ? "#f2c86d" : ACTIVE_COLOR,
        1.8,
      );
    });

    ctx.strokeStyle = "rgba(240,244,247,0.22)";
    ctx.strokeRect(g.plotX, g.plotY, g.plotW, g.plotH);

    ctx.fillStyle = MUTED_COLOR;
    ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    [0, 20, 40, 60, 80, 100].forEach((tick) => {
      const x = g.xScale(tick);
      ctx.strokeStyle = "rgba(240,244,247,0.12)";
      ctx.beginPath();
      ctx.moveTo(x, g.plotY + g.plotH - 6);
      ctx.lineTo(x, g.plotY + g.plotH);
      ctx.stroke();
      ctx.fillText(String(tick), x, g.plotY + g.plotH + 8);
    });
    ctx.fillText("sec", g.plotX + g.plotW / 2, g.plotY + g.plotH + 22);

    if (hover) {
      const x = g.xScale(hover.time);
      ctx.strokeStyle = "rgba(242,200,109,0.72)";
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
    const g = geometry(rect.width, rect.height);
    if (point.x < g.plotX || point.x > g.plotX + g.plotW || point.y < g.plotY || point.y > g.plotY + g.plotH) {
      return null;
    }
    const time = invertLinear(times[0], times.at(-1), g.plotX, g.plotX + g.plotW)(point.x);
    const timeIndex = nearestIndex(times, time);
    const channelIndex = getChannelIndex();
    return {
      time: times[timeIndex],
      timeIndex,
      values: Object.fromEntries(METRICS.map(([key]) => [key, data.geometry[key][channelIndex][timeIndex]])),
    };
  }

  canvas.addEventListener("mousemove", (event) => {
    hover = hit(event);
    if (!hover) {
      tooltip.hide();
      draw();
      return;
    }
    const rows = METRICS.map(([key, label, unit]) => {
      const suffix = unit ? ` ${unit}` : "";
      const digits = key.includes("alpha") || key === "flatness" || key === "entropy" ? 3 : 2;
      return `${label}: ${formatNumber(hover.values[key], digits)}${suffix}`;
    }).join("<br>");
    tooltip.show(event.clientX, event.clientY, `<strong>${getChannel()} · ${formatNumber(hover.time, 2)} sec</strong><br>${rows}`);
    draw();
  });

  canvas.addEventListener("mouseleave", () => {
    hover = null;
    tooltip.hide();
    draw();
  });

  onChannelChange(draw);
  observeCanvas(canvas, draw);
}
