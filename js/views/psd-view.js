import {
  getChannel,
  getChannelIndex,
  getLiveState,
  getPsdScale,
  getVisibleChannels,
  onChannelChange,
  onDisplayChange,
  onLiveChange,
  onPsdScaleChange,
  setChannel,
} from "../state.js";
import {
  ACTIVE_COLOR,
  AXIS_COLOR,
  MUTED_COLOR,
  clear,
  colorScale,
  drawBottomAxis,
  drawFrequencyBands,
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
  const channelIndexByName = new Map(channels.map((channel, index) => [channel, index]));
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
    const visibleChannels = getVisibleChannels(data);
    const selectedChannel = getChannel();
    const selectedVisibleIndex = visibleChannels.indexOf(selectedChannel);
    const xScale = scaleLinear(frequencies[0], frequencies.at(-1), plotX, plotX + plotW);
    const channelH = plotH / Math.max(1, visibleChannels.length);

    drawFrequencyBands(ctx, xScale, plotY, plotH, { labels: true });

    for (let visibleIndex = 0; visibleIndex < visibleChannels.length; visibleIndex += 1) {
      const channelIndex = channelIndexByName.get(visibleChannels[visibleIndex]);
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
        ctx.fillRect(x0, plotY + visibleIndex * channelH, Math.max(1, x1 - x0 + 0.5), Math.ceil(channelH) + 0.5);
      }
    }

    ctx.font = "10px SFMono-Regular, Roboto Mono, Cascadia Mono, ui-monospace, monospace";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    visibleChannels.forEach((channel, index) => {
      ctx.fillStyle = channel === selectedChannel ? ACTIVE_COLOR : MUTED_COLOR;
      ctx.fillText(channel, plotX - 8, plotY + index * channelH + channelH / 2);
    });

    if (heatHover) {
      ctx.fillStyle = "rgba(241,235,217,0.08)";
      ctx.fillRect(plotX, plotY + heatHover.channelIndex * channelH, plotW, channelH);
    }

    ctx.strokeStyle = ACTIVE_COLOR;
    ctx.lineWidth = 2;
    if (selectedVisibleIndex >= 0) {
      ctx.strokeRect(plotX, plotY + selectedVisibleIndex * channelH + 1, plotW, Math.max(1, channelH - 2));
    }

    ctx.strokeStyle = "rgba(241,235,217,0.28)";
    ctx.strokeRect(plotX, plotY, plotW, plotH);
    drawBottomAxis(ctx, [1, 10, 20, 30, 40, 50, 55], xScale, plotY + plotH, "Hz");
  }

  function drawOverlay() {
    const { ctx, width, height } = resizeCanvas(overlay);
    clear(ctx, width, height);

    const channel = getChannel();
    const channelIndex = getChannelIndex();
    const live = getLiveState();
    const livePsd = live.latestFrame?.psd_by_channel?.[channel];
    const liveFreq = live.latestFrame?.frequency_hz;
    const sourceFrequencies = Array.isArray(livePsd) && Array.isArray(liveFreq) ? liveFreq.map(Number) : frequencies;
    const sourceValues = Array.isArray(livePsd) ? livePsd.map(Number) : psd[channelIndex];
    const scale = getPsdScale();
    const values = scale === "log" ? sourceValues.map(log10) : sourceValues;
    const [minY, maxY] = extent([values]);
    const plotX = overlayMargins.left;
    const plotY = overlayMargins.top;
    const plotW = width - overlayMargins.left - overlayMargins.right;
    const plotH = height - overlayMargins.top - overlayMargins.bottom;
    const xScale = scaleLinear(sourceFrequencies[0], sourceFrequencies.at(-1), plotX, plotX + plotW);
    const yScale = scaleLinear(minY, maxY, plotY + plotH, plotY);

    ctx.fillStyle = AXIS_COLOR;
    ctx.font = "700 13px SFMono-Regular, Roboto Mono, Cascadia Mono, ui-monospace, monospace";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    const sourceLabel = Array.isArray(livePsd) ? "Live PSD" : "Static PSD";
    ctx.fillText(`${sourceLabel} · ${channel}`, plotX, 14);

    drawFrequencyBands(ctx, xScale, plotY, plotH, { labels: false });
    ctx.strokeStyle = "rgba(241,235,217,0.22)";
    ctx.strokeRect(plotX, plotY, plotW, plotH);
    ctx.fillStyle = MUTED_COLOR;
    ctx.font = "10px SFMono-Regular, Roboto Mono, Cascadia Mono, ui-monospace, monospace";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(formatNumber(maxY, 1), plotX - 6, plotY);
    ctx.fillText(formatNumber(minY, 1), plotX - 6, plotY + plotH);

    drawLine(
      ctx,
      sourceFrequencies.map((frequency, index) => ({
        x: xScale(frequency),
        y: yScale(values[index]),
      })),
      ACTIVE_COLOR,
      2,
    );
    drawBottomAxis(ctx, [1, 10, 20, 30, 40, 50, 55], xScale, plotY + plotH, `${scale} · Hz`);
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
    const visibleChannels = getVisibleChannels(data);
    const channelIndex = Math.min(visibleChannels.length - 1, Math.floor(((point.y - plotY) / plotH) * visibleChannels.length));
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
    const visibleChannels = getVisibleChannels(data);
    const channel = visibleChannels[hit.channelIndex];
    const sourceIndex = channelIndexByName.get(channel);
    const frequency = frequencies[hit.freqIndex];
    tooltip.show(event.clientX, event.clientY, `<strong>${channel}</strong><br>${formatNumber(frequency, 2)} Hz<br>log PSD ${formatNumber(logMatrix[sourceIndex][hit.freqIndex], 2)}`);
    drawHeatmap();
  });

  heatmap.addEventListener("mouseleave", () => {
    heatHover = null;
    tooltip.hide();
    drawHeatmap();
  });

  heatmap.addEventListener("click", (event) => {
    const hit = hitTest(event);
    if (hit) setChannel(getVisibleChannels(data)[hit.channelIndex]);
  });

  onChannelChange(render);
  onDisplayChange(render);
  onPsdScaleChange(render);
  onLiveChange(drawOverlay);
  observeCanvas(heatmap, render);
  observeCanvas(overlay, render);
}
