import { getChannel, getChannelIndex, onChannelChange, setChannel } from "../state.js";
import {
  ACTIVE_COLOR,
  AXIS_COLOR,
  GRID_COLOR,
  MUTED_COLOR,
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
  resizeCanvas,
  scaleLinear,
} from "./chart-utils.js";

export function initCentroidView(data, tooltip) {
  const canvas = document.querySelector("#centroid-chart");
  const channels = data.meta.channels;
  const times = data.centroid.time_relative;
  const values = data.centroid.values;
  const margins = { left: 50, right: 18, top: 18, bottom: 42 };
  const [minY, maxY] = paddedExtent(values, 0.08);
  let hover = null;

  function geometry(width, height) {
    const plotX = margins.left;
    const plotY = margins.top;
    const plotW = width - margins.left - margins.right;
    const plotH = height - margins.top - margins.bottom;
    return {
      plotX,
      plotY,
      plotW,
      plotH,
      xScale: scaleLinear(times[0], times.at(-1), plotX, plotX + plotW),
      yScale: scaleLinear(minY, maxY, plotY + plotH, plotY),
    };
  }

  function pointsForChannel(channelIndex, g) {
    return times.map((time, index) => ({
      x: g.xScale(time),
      y: g.yScale(values[channelIndex][index]),
    }));
  }

  function draw() {
    const { ctx, width, height } = resizeCanvas(canvas);
    clear(ctx, width, height);
    const g = geometry(width, height);
    const selectedIndex = getChannelIndex();

    ctx.strokeStyle = "rgba(240,244,247,0.2)";
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

    channels.forEach((_, index) => {
      if (index !== selectedIndex) {
        drawLine(ctx, pointsForChannel(index, g), "rgb(150,150,150)", 1, 0.28);
      }
    });
    drawLine(ctx, pointsForChannel(selectedIndex, g), ACTIVE_COLOR, 2.4, 1);

    ctx.fillStyle = MUTED_COLOR;
    ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(`${formatNumber(maxY, 1)} Hz`, g.plotX - 7, g.plotY);
    ctx.fillText(`${formatNumber(minY, 1)} Hz`, g.plotX - 7, g.plotY + g.plotH);

    drawBottomAxis(ctx, [0, 20, 40, 60, 80, 100], g.xScale, g.plotY + g.plotH, "sec");

    if (hover) {
      const x = g.xScale(hover.time);
      ctx.strokeStyle = "rgba(119,215,200,0.55)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, g.plotY);
      ctx.lineTo(x, g.plotY + g.plotH);
      ctx.stroke();
      ctx.fillStyle = AXIS_COLOR;
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText(`${formatNumber(hover.value, 2)} Hz`, x + 8, g.plotY + 8);
    }
  }

  function selectedHover(event) {
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
      value: values[channelIndex][timeIndex],
    };
  }

  function nearestLine(event) {
    const point = canvasPoint(event, canvas);
    const rect = canvas.getBoundingClientRect();
    const g = geometry(rect.width, rect.height);
    let best = null;
    for (let channelIndex = 0; channelIndex < channels.length; channelIndex += 1) {
      const points = pointsForChannel(channelIndex, g);
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
      tooltip.hide();
      draw();
      return;
    }
    tooltip.show(event.clientX, event.clientY, `<strong>${getChannel()}</strong><br>${formatNumber(hover.time, 2)} sec<br>${formatNumber(hover.value, 2)} Hz`);
    draw();
  });

  canvas.addEventListener("mouseleave", () => {
    hover = null;
    tooltip.hide();
    draw();
  });

  canvas.addEventListener("click", (event) => {
    const channelIndex = nearestLine(event);
    if (channelIndex !== null) setChannel(channels[channelIndex]);
  });

  onChannelChange(draw);
  observeCanvas(canvas, draw);
}

