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
import {
  ACTIVE_COLOR,
  AXIS_COLOR,
  GRID_COLOR,
  MUTED_COLOR,
  SECONDARY_COLOR,
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

export function initCentroidView(data, tooltip) {
  const canvas = document.querySelector("#centroid-chart");
  const channels = data.meta.channels;
  const times = data.centroid.time_relative;
  const values = data.centroid.values;
  const channelIndexByName = new Map(channels.map((channel, index) => [channel, index]));
  const margins = { left: 50, right: 18, top: 18, bottom: 42 };
  const [minY, maxY] = paddedExtent(values, 0.08);
  let hover = null;

  function activeSeries() {
    const live = getLiveState();
    if (live.history.length > 1) {
      const liveTimes = live.history.map((frame) => frame.time);
      const liveValues = channels.map((channel) => live.history.map((frame) => frame.metrics[channel]?.centroid));
      return {
        mode: "live",
        times: liveTimes,
        values: liveValues,
        yExtent: paddedExtent(liveValues, 0.08),
      };
    }
    return {
      mode: "static",
      times,
      values,
      yExtent: [minY, maxY],
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
    const { ctx, width, height } = resizeCanvas(canvas);
    clear(ctx, width, height);
    const series = activeSeries();
    const g = geometry(width, height, series);
    const selectedIndex = getChannelIndex();
    const visibleChannels = getVisibleChannels(data);

    ctx.strokeStyle = "rgba(241,235,217,0.22)";
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
      const index = channelIndexByName.get(channel);
      if (index !== selectedIndex) {
        drawLine(ctx, pointsForChannel(index, g, series), "rgb(158,154,141)", 1, 0.28);
      }
    });
    drawLine(ctx, pointsForChannel(selectedIndex, g, series), ACTIVE_COLOR, 2.4, 1);

    ctx.fillStyle = MUTED_COLOR;
    ctx.font = "10px SFMono-Regular, Roboto Mono, Cascadia Mono, ui-monospace, monospace";
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

    const sharedHover = getTimeHover();
    if (hover || sharedHover) {
      const hoverPoint = hover || sharedHover;
      const x = g.xScale(hoverPoint.time);
      ctx.strokeStyle = "rgba(51,222,192,0.62)";
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
    const channelIndex = getChannelIndex();
    return {
      mode: series.mode,
      time: series.times[timeIndex],
      timeIndex,
      value: series.values[channelIndex][timeIndex],
      rankings: rankingsFor(series, timeIndex),
    };
  }

  function rankingsFor(series, timeIndex) {
    const visibleChannels = getVisibleChannels(data);
    const visibleValues = visibleChannels.map((channel) => series.values[channelIndexByName.get(channel)]);
    return rankAt(visibleValues, visibleChannels, timeIndex, 3);
  }

  function nearestLine(event) {
    const point = canvasPoint(event, canvas);
    const rect = canvas.getBoundingClientRect();
    const series = activeSeries();
    const g = geometry(rect.width, rect.height, series);
    let best = null;
    for (const channel of getVisibleChannels(data)) {
      const channelIndex = channelIndexByName.get(channel);
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

  canvas.addEventListener("mousemove", (event) => {
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

  canvas.addEventListener("mouseleave", () => {
    hover = null;
    setTimeHover(null);
    tooltip.hide();
    draw();
  });

  canvas.addEventListener("click", (event) => {
    const channelIndex = nearestLine(event);
    if (channelIndex !== null) setChannel(channels[channelIndex]);
  });

  onChannelChange(draw);
  onDisplayChange(draw);
  onFrameChange(draw);
  onLiveChange(draw);
  onTimeHoverChange(draw);
  observeCanvas(canvas, draw);
}
