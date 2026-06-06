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
  getComparisonSessions,
  getRenderSessions,
  getViewMode,
  onSessionsChange,
} from "../sessions.js";
import {
  ACTIVE_COLOR,
  AXIS_COLOR,
  GRID_COLOR,
  MONO_FONT,
  MUTED_COLOR,
  PLAYBACK_CURSOR_COLOR,
  PLOT_BORDER_COLOR,
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
import { renderSessionLegend } from "./session-legend.js";

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
  const legend = document.querySelector("#geometry-legend");
  const margins = { left: 158, right: 18, top: 14, bottom: 30 };
  let hover = null;

  function activeSeries() {
    const sourceData = singleSourceData();
    const live = getLiveState();
    const allowLive = getComparisonSessions(data)[0]?.isDefault && getViewMode() === "overlay";
    if (allowLive && live.history.length > 1) {
      return {
        mode: "live",
        data: sourceData,
        times: live.history.map((frame) => frame.time),
        metric(key, channel) {
          return live.history.map((frame) => frame.metrics[channel]?.[key]);
        },
      };
    }
    return {
      mode: "static",
      data: sourceData,
      times: sourceData.geometry.time,
      metric(key, channel) {
        return sourceData.geometry[key][sourceData.meta.channels.indexOf(channel)];
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
    renderSessionLegend(legend, data);
    const mode = getViewMode();
    const sessions = getRenderSessions(data);
    if (mode === "split" && sessions.length > 1) {
      drawSplit(sessions);
      return;
    }
    if ((mode === "overlay" && sessions.length > 1) || mode === "delta") {
      drawSessionOverlay(sessions, mode);
      return;
    }

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

      ctx.strokeStyle = metricIndex === METRICS.length - 1 ? PLOT_BORDER_COLOR : GRID_COLOR;
      ctx.beginPath();
      ctx.moveTo(g.plotX, y0 + g.panelH);
      ctx.lineTo(g.plotX + g.plotW, y0 + g.panelH);
      ctx.stroke();

      ctx.fillStyle = AXIS_COLOR;
      ctx.font = `600 10px ${MONO_FONT}`;
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText(label, 14, panelTop - 1);
      ctx.fillStyle = MUTED_COLOR;
      ctx.font = `10px ${MONO_FONT}`;
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
        ACTIVE_COLOR,
        1.8,
      );
    });

    ctx.strokeStyle = PLOT_BORDER_COLOR;
    ctx.strokeRect(g.plotX, g.plotY, g.plotW, g.plotH);

    if (series.mode === "static") {
      const frameIndex = Math.min(series.times.length - 1, getFrame());
      const x = g.xScale(series.times[frameIndex]);
      ctx.save();
      ctx.strokeStyle = PLAYBACK_CURSOR_COLOR;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 5]);
      ctx.beginPath();
      ctx.moveTo(x, g.plotY);
      ctx.lineTo(x, g.plotY + g.plotH);
      ctx.stroke();
      ctx.restore();
    }

    ctx.fillStyle = MUTED_COLOR;
    ctx.font = `10px ${MONO_FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const ticks = series.mode === "live"
      ? [series.times[0], series.times.at(-1)].filter((value, index, arr) => index === 0 || value !== arr[0])
      : [0, 20, 40, 60, 80, 100];
    ticks.forEach((tick) => {
      const x = g.xScale(tick);
      ctx.strokeStyle = PLOT_BORDER_COLOR;
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
      ctx.strokeStyle = PLAYBACK_CURSOR_COLOR;
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
  onSessionsChange(draw);
  observeCanvas(canvas, draw);

  function drawSessionOverlay(sessions, mode) {
    const { ctx, width, height } = resizeCanvas(canvas);
    clear(ctx, width, height);
    if (!sessions.length) {
      drawEmpty(ctx, width, height);
      return;
    }
    const g = geometry(width, height, {
      times: sessions[0].data.geometry.time,
    });
    const channel = getChannel();
    caption.textContent = `Sliding spectral geometry | channel: ${channel} | ${mode === "delta" ? `Δ vs ${sessions[0].baselineName}` : "overlay"}`;

    METRICS.forEach(([key, label, unit], metricIndex) => {
      const y0 = g.plotY + metricIndex * g.panelH;
      const panelTop = y0 + 8;
      const panelBottom = y0 + g.panelH - 12;
      const rows = sessions
        .map((session) => {
          const channelIndex = session.data.meta.channels.indexOf(channel);
          if (channelIndex < 0) return null;
          return {
            session,
            values: session.data.geometry[key][channelIndex],
          };
        })
        .filter(Boolean);
      const [minY, maxY] = paddedExtent([rows.flatMap((row) => mode === "delta" ? row.values.concat(0) : row.values)], 0.1);
      const yScale = scaleLinear(minY, maxY, panelBottom, panelTop);

      drawMetricShell(ctx, g, y0, panelTop, panelBottom, metricIndex, label, unit, minY, maxY, key, mode, yScale);
      rows.forEach((row) => {
        drawLine(
          ctx,
          sessions[0].data.geometry.time.map((time, index) => ({
            x: g.xScale(time),
            y: yScale(row.values[index]),
          })),
          row.session.color,
          1.8,
        );
      });
    });

    drawFrameAndAxis(ctx, g, mode);
  }

  function drawSplit(sessions) {
    const { ctx, width, height } = resizeCanvas(canvas);
    clear(ctx, width, height);
    if (!sessions.length) {
      drawEmpty(ctx, width, height);
      return;
    }

    caption.textContent = `Sliding spectral geometry | channel: ${getChannel()} | split`;
    const gap = 10;
    const columnW = (width - gap * (sessions.length - 1)) / sessions.length;
    sessions.forEach((session, columnIndex) => {
      const x0 = columnIndex * (columnW + gap);
      const localMargins = { left: columnIndex === 0 ? 118 : 36, right: 10, top: 34, bottom: 28 };
      const times = session.data.geometry.time;
      const plotX = x0 + localMargins.left;
      const plotY = localMargins.top;
      const plotW = columnW - localMargins.left - localMargins.right;
      const plotH = height - localMargins.top - localMargins.bottom;
      const panelH = plotH / METRICS.length;
      const xScale = scaleLinear(times[0], times.at(-1), plotX, plotX + plotW);
      const channelIndex = Math.max(0, session.data.meta.channels.indexOf(getChannel()));

      ctx.strokeStyle = session.color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x0 + 1, 0);
      ctx.lineTo(x0 + 1, height);
      ctx.stroke();
      ctx.fillStyle = session.color;
      ctx.font = `600 10px ${MONO_FONT}`;
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText(session.name, x0 + 8, 10, Math.max(40, columnW - 16));

      METRICS.forEach(([key, label, unit], metricIndex) => {
        const y0 = plotY + metricIndex * panelH;
        const panelTop = y0 + 8;
        const panelBottom = y0 + panelH - 12;
        const values = session.data.geometry[key][channelIndex];
        const [minY, maxY] = paddedExtent([values], 0.1);
        const yScale = scaleLinear(minY, maxY, panelBottom, panelTop);
        const g = { plotX, plotY, plotW, plotH, panelH, xScale };
        drawMetricShell(ctx, g, y0, panelTop, panelBottom, metricIndex, columnIndex === 0 ? label : "", columnIndex === 0 ? unit : "", minY, maxY, key, "split", yScale);
        drawLine(
          ctx,
          times.map((time, index) => ({
            x: xScale(time),
            y: yScale(values[index]),
          })),
          session.color,
          1.5,
        );
      });
    });
  }

  function drawMetricShell(ctx, g, y0, panelTop, panelBottom, metricIndex, label, unit, minY, maxY, key, mode, yScale) {
    ctx.strokeStyle = metricIndex === METRICS.length - 1 ? PLOT_BORDER_COLOR : GRID_COLOR;
    ctx.beginPath();
    ctx.moveTo(g.plotX, y0 + g.panelH);
    ctx.lineTo(g.plotX + g.plotW, y0 + g.panelH);
    ctx.stroke();

    if (mode === "delta") {
      const zeroY = yScale(0);
      ctx.strokeStyle = "rgba(255,255,255,0.18)";
      ctx.beginPath();
      ctx.moveTo(g.plotX, zeroY);
      ctx.lineTo(g.plotX + g.plotW, zeroY);
      ctx.stroke();
    }

    if (label) {
      ctx.fillStyle = AXIS_COLOR;
      ctx.font = `600 10px ${MONO_FONT}`;
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText(label, 14, panelTop - 1);
      ctx.fillStyle = MUTED_COLOR;
      ctx.font = `10px ${MONO_FONT}`;
      ctx.fillText(unit || "—", 14, panelTop + 15);
    }
    ctx.fillStyle = MUTED_COLOR;
    ctx.font = `10px ${MONO_FONT}`;
    ctx.textAlign = "right";
    ctx.fillText(formatNumber(maxY, key.includes("alpha") || key === "flatness" || key === "entropy" ? 2 : 1), g.plotX - 8, panelTop - 2);
    ctx.fillText(formatNumber(minY, key.includes("alpha") || key === "flatness" || key === "entropy" ? 2 : 1), g.plotX - 8, panelBottom - 9);
  }

  function drawFrameAndAxis(ctx, g, mode) {
    ctx.strokeStyle = PLOT_BORDER_COLOR;
    ctx.strokeRect(g.plotX, g.plotY, g.plotW, g.plotH);
    ctx.fillStyle = MUTED_COLOR;
    ctx.font = `10px ${MONO_FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    [0, 20, 40, 60, 80, 100].forEach((tick) => {
      const x = g.xScale(tick);
      ctx.strokeStyle = PLOT_BORDER_COLOR;
      ctx.beginPath();
      ctx.moveTo(x, g.plotY + g.plotH - 6);
      ctx.lineTo(x, g.plotY + g.plotH);
      ctx.stroke();
      ctx.fillText(String(tick), x, g.plotY + g.plotH + 8);
    });
    ctx.fillText(mode === "delta" ? "Δ sec" : "sec", g.plotX + g.plotW / 2, g.plotY + g.plotH + 22);

    const sharedHover = getTimeHover();
    if (!sharedHover) return;
    const x = g.xScale(sharedHover.time);
    ctx.strokeStyle = PLAYBACK_CURSOR_COLOR;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, g.plotY);
    ctx.lineTo(x, g.plotY + g.plotH);
    ctx.stroke();
  }

  function drawEmpty(ctx, width, height) {
    ctx.fillStyle = MUTED_COLOR;
    ctx.font = `12px ${MONO_FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("No active sessions", width / 2, height / 2);
  }

  function singleSourceData() {
    return getComparisonSessions(data)[0]?.data ?? data;
  }
}
