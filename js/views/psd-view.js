import { getChannel, getChannelIndex, onChannelChange, setChannel } from "../state.js";
import {
  ACTIVE_COLOR,
  AXIS_COLOR,
  MUTED_COLOR,
  clear,
  colorScale,
  drawBottomAxis,
  drawLine,
  extent,
  formatNumber,
  invertLinear,
  log10,
  nearestIndex,
  observeCanvas,
  resizeCanvas,
  scaleLinear,
  canvasPoint,
} from "./chart-utils.js";

export function initPsdView(data, tooltip) {
  const heatmap = document.querySelector("#psd-heatmap");
  const overlay = document.querySelector("#psd-overlay");
  const channels = data.meta.channels;
  const frequencies = data.welch_psd.frequencies;
  const psd = data.welch_psd.psd;
  const logMatrix = psd.map((row) => row.map(log10));
  const [logMin, logMax] = extent(logMatrix);
  let heatHover = null;

  const heatMargins = { left: 58, right: 12, top: 14, bottom: 40 };
  const overlayMargins = { left: 46, right: 16, top: 42, bottom: 40 };

  function drawHeatmap() {
    const { ctx, width, height } = resizeCanvas(heatmap);
    clear(ctx, width, height);

    const plotX = heatMargins.left;
    const plotY = heatMargins.top;
    const plotW = width - heatMargins.left - heatMargins.right;
    const plotH = height - heatMargins.top - heatMargins.bottom;
    const selectedIndex = getChannelIndex();
    const xScale = scaleLinear(frequencies[0], frequencies.at(-1), plotX, plotX + plotW);
    const channelH = plotH / channels.length;

    for (let channelIndex = 0; channelIndex < channels.length; channelIndex += 1) {
      for (let freqIndex = 0; freqIndex < frequencies.length; freqIndex += 1) {
        const f0 = freqIndex === 0
          ? frequencies[freqIndex]
          : (frequencies[freqIndex - 1] + frequencies[freqIndex]) / 2;
        const f1 = freqIndex === frequencies.length - 1
          ? frequencies[freqIndex]
          : (frequencies[freqIndex] + frequencies[freqIndex + 1]) / 2;
        const x0 = xScale(f0);
        const x1 = xScale(f1);
        ctx.fillStyle = colorScale(logMatrix[channelIndex][freqIndex], logMin, logMax);
        ctx.fillRect(x0, plotY + channelIndex * channelH, Math.max(1, x1 - x0 + 0.5), Math.ceil(channelH) + 0.5);
      }
    }

    ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    channels.forEach((channel, index) => {
      ctx.fillStyle = index === selectedIndex ? ACTIVE_COLOR : MUTED_COLOR;
      ctx.fillText(channel, plotX - 8, plotY + index * channelH + channelH / 2);
    });

    if (heatHover) {
      ctx.fillStyle = "rgba(255,255,255,0.08)";
      ctx.fillRect(plotX, plotY + heatHover.channelIndex * channelH, plotW, channelH);
    }

    ctx.strokeStyle = ACTIVE_COLOR;
    ctx.lineWidth = 2;
    ctx.strokeRect(plotX, plotY + selectedIndex * channelH + 1, plotW, Math.max(1, channelH - 2));

    ctx.strokeStyle = "rgba(240,244,247,0.32)";
    ctx.strokeRect(plotX, plotY, plotW, plotH);
    drawBottomAxis(ctx, [1, 10, 20, 30, 40, 50, 55], xScale, plotY + plotH, "Hz");
  }

  function drawOverlay() {
    const { ctx, width, height } = resizeCanvas(overlay);
    clear(ctx, width, height);

    const channel = getChannel();
    const channelIndex = getChannelIndex();
    const values = logMatrix[channelIndex];
    const [minY, maxY] = extent([values]);
    const plotX = overlayMargins.left;
    const plotY = overlayMargins.top;
    const plotW = width - overlayMargins.left - overlayMargins.right;
    const plotH = height - overlayMargins.top - overlayMargins.bottom;
    const xScale = scaleLinear(frequencies[0], frequencies.at(-1), plotX, plotX + plotW);
    const yScale = scaleLinear(minY, maxY, plotY + plotH, plotY);

    ctx.fillStyle = AXIS_COLOR;
    ctx.font = "700 13px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(`Channel ${channel}`, plotX, 14);

    ctx.strokeStyle = "rgba(240,244,247,0.22)";
    ctx.strokeRect(plotX, plotY, plotW, plotH);
    ctx.fillStyle = MUTED_COLOR;
    ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(formatNumber(maxY, 1), plotX - 6, plotY);
    ctx.fillText(formatNumber(minY, 1), plotX - 6, plotY + plotH);

    drawLine(
      ctx,
      frequencies.map((frequency, index) => ({
        x: xScale(frequency),
        y: yScale(values[index]),
      })),
      ACTIVE_COLOR,
      2,
    );
    drawBottomAxis(ctx, [1, 10, 20, 30, 40, 50, 55], xScale, plotY + plotH, "Hz");
  }

  function render() {
    drawHeatmap();
    drawOverlay();
  }

  function hitTest(event) {
    const point = canvasPoint(event, heatmap);
    const { width, height } = heatmap.getBoundingClientRect();
    const plotX = heatMargins.left;
    const plotY = heatMargins.top;
    const plotW = width - heatMargins.left - heatMargins.right;
    const plotH = height - heatMargins.top - heatMargins.bottom;
    if (point.x < plotX || point.x > plotX + plotW || point.y < plotY || point.y > plotY + plotH) {
      return null;
    }
    const channelIndex = Math.min(channels.length - 1, Math.floor(((point.y - plotY) / plotH) * channels.length));
    const frequency = invertLinear(frequencies[0], frequencies.at(-1), plotX, plotX + plotW)(point.x);
    const freqIndex = nearestIndex(frequencies, frequency);
    return { channelIndex, freqIndex };
  }

  heatmap.addEventListener("mousemove", (event) => {
    const hit = hitTest(event);
    heatHover = hit;
    if (!hit) {
      tooltip.hide();
      drawHeatmap();
      return;
    }
    const channel = channels[hit.channelIndex];
    const frequency = frequencies[hit.freqIndex];
    tooltip.show(event.clientX, event.clientY, `<strong>${channel}</strong><br>${formatNumber(frequency, 2)} Hz<br>log PSD ${formatNumber(logMatrix[hit.channelIndex][hit.freqIndex], 2)}`);
    drawHeatmap();
  });

  heatmap.addEventListener("mouseleave", () => {
    heatHover = null;
    tooltip.hide();
    drawHeatmap();
  });

  heatmap.addEventListener("click", (event) => {
    const hit = hitTest(event);
    if (hit) setChannel(channels[hit.channelIndex]);
  });

  onChannelChange(render);
  observeCanvas(heatmap, render);
  observeCanvas(overlay, render);
}

