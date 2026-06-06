import {
  getChannel,
  getChannelIndex,
  getFrame,
  getLiveState,
  getTimeHover,
  getVisibleChannels,
  onChannelChange,
  onDisplayChange,
  onFrameChange,
  onLiveChange,
  onTimeHoverChange,
  setChannel,
  setTimeHover,
} from "../state.js";
import { createDisposables } from "../disposables.js";
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
  distanceToSegment,
  drawBottomAxis,
  drawLine,
  formatNumber,
  invertLinear,
  nearestIndex,
  observeCanvas,
  paddedExtent,
  rankAt,
  resizeCanvas,
  scaleLinear,
} from "./chart-utils.js";
import { renderSessionLegend } from "./session-legend.js";

export function initCentroidView(data, tooltip) {
  const canvas = document.querySelector("#centroid-chart");
  const legend = document.querySelector("#centroid-legend");
  const disposables = createDisposables();
  const margins = { left: 50, right: 18, top: 18, bottom: 42 };
  let hover = null;

  function activeSeries() {
    const sourceData = singleSourceData();
    const channels = sourceData.meta.channels;
    const live = getLiveState();
    const allowLive = getComparisonSessions(data)[0]?.isDefault && getViewMode() === "overlay";
    if (allowLive && live.history.length > 1) {
      const liveTimes = live.history.map((frame) => frame.time);
      const liveValues = channels.map((channel) => live.history.map((frame) => frame.metrics[channel]?.centroid));
      return {
        mode: "live",
        data: sourceData,
        channels,
        channelIndexByName: new Map(channels.map((channel, index) => [channel, index])),
        times: liveTimes,
        values: liveValues,
        yExtent: paddedExtent(liveValues, 0.08),
      };
    }
    const values = sourceData.centroid.values;
    return {
      mode: "static",
      data: sourceData,
      channels,
      channelIndexByName: new Map(channels.map((channel, index) => [channel, index])),
      times: sourceData.centroid.time_relative,
      values,
      yExtent: paddedExtent(values, 0.08),
    };
  }

  function geometry(width, height, series) {
    const plotX = margins.left;
    const plotY = margins.top;
    const plotW = width - margins.left - margins.right;
    const plotH = height - margins.top - margins.bottom;
    const [seriesMinY, seriesMaxY] = series.yExtent;
    return {
      plotX,
      plotY,
      plotW,
      plotH,
      xScale: scaleLinear(series.times[0], series.times.at(-1), plotX, plotX + plotW),
      yScale: scaleLinear(seriesMinY, seriesMaxY, plotY + plotH, plotY),
      yMin: seriesMinY,
      yMax: seriesMaxY,
    };
  }

  function pointsForChannel(channelIndex, g, series) {
    return series.times.map((time, index) => ({
      x: g.xScale(time),
      y: g.yScale(series.values[channelIndex][index]),
    }));
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
    const selectedIndex = Math.max(0, series.channels.indexOf(getChannel()));
    const visibleChannels = getVisibleChannels(series.data);

    ctx.strokeStyle = PLOT_BORDER_COLOR;
    ctx.strokeRect(g.plotX, g.plotY, g.plotW, g.plotH);
    ctx.strokeStyle = GRID_COLOR;
    ctx.lineWidth = 1;
    for (let i = 1; i < 4; i += 1) {
      const y = g.plotY + (g.plotH * i) / 4;
      ctx.beginPath();
      ctx.moveTo(g.plotX, y);
      ctx.lineTo(g.plotX + g.plotW, y);
      ctx.stroke();
    }

    visibleChannels.forEach((channel) => {
      const index = series.channelIndexByName.get(channel);
      if (index !== selectedIndex) {
        drawLine(ctx, pointsForChannel(index, g, series), "rgba(255,255,255,0.12)", 1, 1);
      }
    });
    drawLine(ctx, pointsForChannel(selectedIndex, g, series), ACTIVE_COLOR, 2.4, 1);

    ctx.fillStyle = MUTED_COLOR;
    ctx.font = `10px ${MONO_FONT}`;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(`${formatNumber(g.yMax, 1)} Hz`, g.plotX - 7, g.plotY);
    ctx.fillText(`${formatNumber(g.yMin, 1)} Hz`, g.plotX - 7, g.plotY + g.plotH);

    const ticks = series.mode === "live"
      ? [series.times[0], series.times.at(-1)].filter((value, index, arr) => index === 0 || value !== arr[0])
      : [0, 20, 40, 60, 80, 100];
    drawBottomAxis(ctx, ticks.map((tick) => Number(tick.toFixed ? tick.toFixed(1) : tick)), g.xScale, g.plotY + g.plotH, series.mode === "live" ? "live sec" : "sec");

    if (series.mode === "static") {
      const frameIndex = Math.min(series.times.length - 1, Math.round(getFrame() / 2));
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
      ctx.fillStyle = AXIS_COLOR;
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      if (hover) ctx.fillText(`${formatNumber(hover.value, 2)} Hz`, x + 8, g.plotY + 8);
    }
  }

  function selectedHover(event) {
    const point = canvasPoint(event, canvas);
    const rect = canvas.getBoundingClientRect();
    const series = activeSeries();
    const g = geometry(rect.width, rect.height, series);
    if (point.x < g.plotX || point.x > g.plotX + g.plotW || point.y < g.plotY || point.y > g.plotY + g.plotH) {
      return null;
    }
    const time = invertLinear(series.times[0], series.times.at(-1), g.plotX, g.plotX + g.plotW)(point.x);
    const timeIndex = nearestIndex(series.times, time);
    const channelIndex = Math.max(0, series.channels.indexOf(getChannel()));
    return {
      mode: series.mode,
      time: series.times[timeIndex],
      timeIndex,
      value: series.values[channelIndex][timeIndex],
      rankings: rankingsFor(series, timeIndex),
    };
  }

  function rankingsFor(series, timeIndex) {
    const visibleChannels = getVisibleChannels(series.data);
    const visibleValues = visibleChannels.map((channel) => series.values[series.channelIndexByName.get(channel)]);
    return rankAt(visibleValues, visibleChannels, timeIndex, 3);
  }

  function nearestLine(event) {
    const point = canvasPoint(event, canvas);
    const rect = canvas.getBoundingClientRect();
    const series = activeSeries();
    const g = geometry(rect.width, rect.height, series);
    let best = null;
    for (const channel of getVisibleChannels(series.data)) {
      const channelIndex = series.channelIndexByName.get(channel);
      const points = pointsForChannel(channelIndex, g, series);
      for (let i = 1; i < points.length; i += 1) {
        const distance = distanceToSegment(point, points[i - 1], points[i]);
        if (distance <= 5 && (!best || distance < best.distance)) {
          best = { channelIndex, distance };
        }
      }
    }
    return best?.channelIndex ?? null;
  }

  disposables.listen(canvas, "mousemove", (event) => {
    hover = selectedHover(event);
    if (!hover) {
      setTimeHover(null);
      tooltip.hide();
      draw();
      return;
    }
    setTimeHover({ source: "centroid", mode: hover.mode, time: hover.time, timeIndex: hover.timeIndex });
    const high = hover.rankings.high.map((row) => `${row.channel} ${formatNumber(row.value, 1)}`).join(", ");
    const low = hover.rankings.low.map((row) => `${row.channel} ${formatNumber(row.value, 1)}`).join(", ");
    tooltip.show(event.clientX, event.clientY, `<strong>${getChannel()}</strong><br>${formatNumber(hover.time, 2)} sec · ${hover.mode}<br>${formatNumber(hover.value, 2)} Hz<br><span>High: ${high}</span><br><span>Low: ${low}</span>`);
    draw();
  });

  disposables.listen(canvas, "mouseleave", () => {
    hover = null;
    setTimeHover(null);
    tooltip.hide();
    draw();
  });

  disposables.listen(canvas, "click", (event) => {
    const channelIndex = nearestLine(event);
    if (channelIndex !== null) setChannel(activeSeries().channels[channelIndex]);
  });

  disposables.add(onChannelChange(draw));
  disposables.add(onDisplayChange(draw));
  disposables.add(onFrameChange(draw));
  disposables.add(onLiveChange(draw));
  disposables.add(onTimeHoverChange(draw));
  disposables.add(onSessionsChange(draw));
  disposables.add(observeCanvas(canvas, draw));

  function drawSessionOverlay(sessions, mode) {
    const { ctx, width, height } = resizeCanvas(canvas);
    clear(ctx, width, height);
    if (!sessions.length) {
      drawEmpty(ctx, width, height);
      return;
    }

    const channel = getChannel();
    const series = sessions
      .map((session) => {
        const channelIndex = session.data.meta.channels.indexOf(channel);
        if (channelIndex < 0) return null;
        return {
          session,
          times: session.data.centroid.time_relative,
          values: session.data.centroid.values[channelIndex],
        };
      })
      .filter(Boolean);
    const g = overlayGeometry(width, height, series, mode);

    drawPlotShell(ctx, g, mode);
    series.forEach((item) => {
      drawLine(
        ctx,
        item.times.map((time, index) => ({ x: g.xScale(time), y: g.yScale(item.values[index]) })),
        item.session.color,
        2,
      );
    });
    drawCentroidAxis(ctx, g, mode);
    drawHoverCursor(ctx, g);
  }

  function drawSplit(sessions) {
    const { ctx, width, height } = resizeCanvas(canvas);
    clear(ctx, width, height);
    if (!sessions.length) {
      drawEmpty(ctx, width, height);
      return;
    }

    const gap = 10;
    const columnW = (width - gap * (sessions.length - 1)) / sessions.length;
    sessions.forEach((session, index) => {
      const x0 = index * (columnW + gap);
      const localMargins = { left: index === 0 ? 50 : 28, right: 12, top: 32, bottom: 42 };
      const source = session.data;
      const times = source.centroid.time_relative;
      const selectedIndex = Math.max(0, source.meta.channels.indexOf(getChannel()));
      const yExtent = paddedExtent(source.centroid.values, 0.08);
      const g = {
        plotX: x0 + localMargins.left,
        plotY: localMargins.top,
        plotW: columnW - localMargins.left - localMargins.right,
        plotH: height - localMargins.top - localMargins.bottom,
        xScale: scaleLinear(times[0], times.at(-1), x0 + localMargins.left, x0 + columnW - localMargins.right),
        yScale: scaleLinear(yExtent[0], yExtent[1], height - localMargins.bottom, localMargins.top),
        yMin: yExtent[0],
        yMax: yExtent[1],
      };

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
      drawPlotShell(ctx, g, "split");
      source.meta.channels.forEach((channel, channelIndex) => {
        if (channelIndex === selectedIndex) return;
        drawLine(
          ctx,
          times.map((time, timeIndex) => ({ x: g.xScale(time), y: g.yScale(source.centroid.values[channelIndex][timeIndex]) })),
          "rgba(255,255,255,0.09)",
          1,
        );
      });
      drawLine(
        ctx,
        times.map((time, timeIndex) => ({ x: g.xScale(time), y: g.yScale(source.centroid.values[selectedIndex][timeIndex]) })),
        session.color,
        1.8,
      );
    });
  }

  function drawPlotShell(ctx, g, mode) {
    ctx.strokeStyle = PLOT_BORDER_COLOR;
    ctx.strokeRect(g.plotX, g.plotY, g.plotW, g.plotH);
    ctx.strokeStyle = GRID_COLOR;
    ctx.lineWidth = 1;
    for (let i = 1; i < 4; i += 1) {
      const y = g.plotY + (g.plotH * i) / 4;
      ctx.beginPath();
      ctx.moveTo(g.plotX, y);
      ctx.lineTo(g.plotX + g.plotW, y);
      ctx.stroke();
    }
    if (mode === "delta") {
      const y = g.yScale(0);
      ctx.strokeStyle = "rgba(255,255,255,0.18)";
      ctx.beginPath();
      ctx.moveTo(g.plotX, y);
      ctx.lineTo(g.plotX + g.plotW, y);
      ctx.stroke();
    }
  }

  function drawCentroidAxis(ctx, g, mode) {
    ctx.fillStyle = MUTED_COLOR;
    ctx.font = `10px ${MONO_FONT}`;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(`${formatNumber(g.yMax, 1)}${mode === "delta" ? "" : " Hz"}`, g.plotX - 7, g.plotY);
    ctx.fillText(`${formatNumber(g.yMin, 1)}${mode === "delta" ? "" : " Hz"}`, g.plotX - 7, g.plotY + g.plotH);
    drawBottomAxis(ctx, [0, 20, 40, 60, 80, 100], g.xScale, g.plotY + g.plotH, mode === "delta" ? "Δ sec" : "sec");
  }

  function drawHoverCursor(ctx, g) {
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

  function overlayGeometry(width, height, series, mode) {
    const plotX = margins.left;
    const plotY = margins.top;
    const plotW = width - margins.left - margins.right;
    const plotH = height - margins.top - margins.bottom;
    const values = series.flatMap((item) => mode === "delta" ? item.values.concat(0) : item.values);
    const [yMin, yMax] = paddedExtent([values], 0.08);
    return {
      plotX,
      plotY,
      plotW,
      plotH,
      xScale: scaleLinear(series[0].times[0], series[0].times.at(-1), plotX, plotX + plotW),
      yScale: scaleLinear(yMin, yMax, plotY + plotH, plotY),
      yMin,
      yMax,
    };
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

  return disposables.dispose;
}
