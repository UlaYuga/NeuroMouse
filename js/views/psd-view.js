import * as defaultState from "../state.js";
import { createDisposables } from "../disposables.js";
import * as defaultSessions from "../sessions.js";
import {
  ACTIVE_COLOR,
  AXIS_COLOR,
  MONO_FONT,
  MUTED_COLOR,
  PLOT_BORDER_COLOR,
  axisLabels,
  clear,
  deltaColorScale,
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
import { renderSessionLegend } from "./session-legend.js";

const HEATMAP_PALETTE = [
  [5, 13, 18],
  [10, 42, 61],
  [13, 107, 94],
  [13, 168, 130],
  [0, 212, 160],
];

export function initPsdView(data, tooltip, context = {}) {
  const state = context.state ?? defaultState;
  const sessionStore = context.sessions ?? defaultSessions;
  const document = context.document ?? globalThis.document;
  const window = context.window ?? globalThis.window;
  const {
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
  } = state;
  const {
    getBaselineSession,
    getComparisonSessions,
    getRenderSessions,
    getViewMode,
    onSessionsChange,
  } = sessionStore;
  const heatmap = document.querySelector("#psd-heatmap");
  const overlay = document.querySelector("#psd-overlay");
  const legend = document.querySelector("#psd-legend");
  const disposables = createDisposables();
  const channels = data.meta.channels;
  const frequencies = data.welch_psd.frequencies;
  const psd = data.welch_psd.psd;
  const logMatrix = psd.map((row) => row.map(log10));
  const [logMin, logMax] = extent(logMatrix);
  let heatHover = null;
  let heatmapCache = document.createElement("canvas");
  let heatmapCacheKey = "";

  const heatMargins = { left: 70, right: 12, top: 18, bottom: 44 };
  const overlayMargins = { left: 46, right: 16, top: 42, bottom: 40 };

  function activeHeatmap() {
    const sessions = getComparisonSessions(data);
    const hasSessionComparison = sessions.length > 1 || !sessions[0]?.isDefault || getViewMode() === "delta";
    if (hasSessionComparison) {
      const mode = getViewMode();
      const sourceSession = heatmapSession();
      const matrix = sourceSession?.data?.welch_psd?.psd ?? psd;
      const sourceChannels = sourceSession?.data?.meta?.channels ?? channels;
      const sourceFrequencies = sourceSession?.data?.welch_psd?.frequencies ?? frequencies;
      const sourceLogMatrix = mode === "delta" ? matrix : matrix.map((row) => row.map(log10));
      const [sourceMin, sourceMax] = extent(sourceLogMatrix);
      return {
        mode,
        session: sourceSession,
        channels: sourceChannels,
        frequencies: sourceFrequencies,
        matrix,
        logMatrix: sourceLogMatrix,
        logMin: sourceMin,
        logMax: sourceMax,
        delta: mode === "delta",
      };
    }

    return {
      mode: "static",
      channels,
      frequencies,
      matrix: psd,
      logMatrix,
      logMin,
      logMax,
    };
  }

  function drawHeatmap() {
    const { ctx, width, height } = resizeCanvas(heatmap);
    clear(ctx, width, height);
    const source = activeHeatmap();

    const plotX = heatMargins.left;
    const plotY = heatMargins.top;
    const plotW = width - heatMargins.left - heatMargins.right;
    const plotH = height - heatMargins.top - heatMargins.bottom;
    const visibleChannels = getVisibleChannels(data);
    const selectedChannel = getChannel();
    const selectedVisibleIndex = visibleChannels.indexOf(selectedChannel);
    const xScale = scaleLinear(source.frequencies[0], source.frequencies.at(-1), plotX, plotX + plotW);
    const channelH = plotH / Math.max(1, visibleChannels.length);
    renderHeatmapCache(width, height, source, visibleChannels);
    ctx.drawImage(heatmapCache, 0, 0, width, height);

    ctx.font = `600 11px ${MONO_FONT}`;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    visibleChannels.forEach((channel, index) => {
      ctx.fillStyle = channel === selectedChannel ? ACTIVE_COLOR : MUTED_COLOR;
      ctx.fillText(channel, plotX - 12, plotY + index * channelH + channelH / 2);
    });

    if (heatHover) {
      ctx.fillStyle = "rgba(255,255,255,0.05)";
      ctx.fillRect(plotX, plotY + heatHover.channelIndex * channelH, plotW, channelH);
    }

    ctx.strokeStyle = ACTIVE_COLOR;
    ctx.lineWidth = 2;
    if (selectedVisibleIndex >= 0) {
      ctx.strokeRect(plotX, plotY + selectedVisibleIndex * channelH + 1, plotW, Math.max(1, channelH - 2));
    }

    ctx.strokeStyle = PLOT_BORDER_COLOR;
    ctx.strokeRect(plotX, plotY, plotW, plotH);
    drawBottomAxis(ctx, frequencyTicks(plotW, source.frequencies), xScale, plotY + plotH, "Hz");
  }

  function drawOverlay() {
    const { ctx, width, height } = resizeCanvas(overlay);
    clear(ctx, width, height);

    const channel = getChannel();
    const sessions = getRenderSessions(data);
    const rawSessions = getComparisonSessions(data);
    const compareMode = getViewMode();
    const hasSessionComparison = rawSessions.length > 1 || !rawSessions[0]?.isDefault || compareMode === "delta";
    if (hasSessionComparison) {
      drawSessionOverlay(ctx, width, height, sessions, channel, compareMode);
      return;
    }

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
    ctx.font = `600 11px ${MONO_FONT}`;
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    const sourceLabel = Array.isArray(livePsd) ? "Live PSD" : "Static PSD";
    ctx.fillText(`${sourceLabel} · ${channel}`, plotX, 14);

    drawFrequencyBands(ctx, xScale, plotY, plotH, { labels: false });
    ctx.strokeStyle = PLOT_BORDER_COLOR;
    ctx.strokeRect(plotX, plotY, plotW, plotH);
    ctx.fillStyle = MUTED_COLOR;
    ctx.font = `10px ${MONO_FONT}`;
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
    drawBottomAxis(ctx, frequencyTicks(plotW, sourceFrequencies), xScale, plotY + plotH, `${scale} · Hz`);
  }

  function render() {
    renderSessionLegend(legend, data, { sessions: sessionStore });
    drawHeatmap();
    drawOverlay();
  }

  function renderHeatmapCache(width, height, source, visibleChannels) {
    const dpr = window.devicePixelRatio || 1;
    const pixelWidth = Math.round(width * dpr);
    const pixelHeight = Math.round(height * dpr);
    const cacheKey = [
      source.mode,
      source.session?.id ?? "default",
      source.delta ? "delta" : "power",
      visibleChannels.join(","),
      pixelWidth,
      pixelHeight,
    ].join("|");
    if (cacheKey === heatmapCacheKey && heatmapCache.width === pixelWidth && heatmapCache.height === pixelHeight) return;

    heatmapCacheKey = cacheKey;
    heatmapCache.width = pixelWidth;
    heatmapCache.height = pixelHeight;
    const cacheCtx = heatmapCache.getContext("2d");
    cacheCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    clear(cacheCtx, width, height);

    const plotX = heatMargins.left;
    const plotY = heatMargins.top;
    const plotW = width - heatMargins.left - heatMargins.right;
    const plotH = height - heatMargins.top - heatMargins.bottom;
    const xScale = scaleLinear(source.frequencies[0], source.frequencies.at(-1), plotX, plotX + plotW);
    const channelH = plotH / Math.max(1, visibleChannels.length);
    const sourceChannelIndexByName = new Map(source.channels.map((channel, index) => [channel, index]));

    drawFrequencyBands(cacheCtx, xScale, plotY, plotH, { labels: true });
    for (let visibleIndex = 0; visibleIndex < visibleChannels.length; visibleIndex += 1) {
      const channelIndex = sourceChannelIndexByName.get(visibleChannels[visibleIndex]);
      if (channelIndex == null) continue;
      for (let freqIndex = 0; freqIndex < source.frequencies.length; freqIndex += 1) {
        const f0 = freqIndex === 0
          ? source.frequencies[freqIndex]
          : (source.frequencies[freqIndex - 1] + source.frequencies[freqIndex]) / 2;
        const f1 = freqIndex === source.frequencies.length - 1
          ? source.frequencies[freqIndex]
          : (source.frequencies[freqIndex] + source.frequencies[freqIndex + 1]) / 2;
        const x0 = xScale(f0);
        const x1 = xScale(f1);
        const value = source.logMatrix[channelIndex][freqIndex];
        cacheCtx.fillStyle = source.delta
          ? deltaColorScale(value, source.logMin, source.logMax)
          : heatmapColor(value, source.logMin, source.logMax);
        cacheCtx.fillRect(x0, plotY + visibleIndex * channelH, Math.max(1, x1 - x0 + 0.5), Math.ceil(channelH) + 0.5);
      }
    }
  }

  function hitTest(event) {
    const source = activeHeatmap();
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
    const frequency = invertLinear(source.frequencies[0], source.frequencies.at(-1), plotX, plotX + plotW)(point.x);
    const freqIndex = nearestIndex(source.frequencies, frequency);
    return { channelIndex, freqIndex };
  }

  disposables.listen(heatmap, "mousemove", (event) => {
    const hit = hitTest(event);
    heatHover = hit;
    if (!hit) {
      tooltip.hide();
      drawHeatmap();
      return;
    }
    const visibleChannels = getVisibleChannels(data);
    const source = activeHeatmap();
    const channel = visibleChannels[hit.channelIndex];
    const sourceIndex = new Map(source.channels.map((item, index) => [item, index])).get(channel);
    if (sourceIndex == null) {
      tooltip.hide();
      drawHeatmap();
      return;
    }
    const frequency = source.frequencies[hit.freqIndex];
    const label = source.delta ? "Δ log PSD" : "log PSD";
    tooltip.show(event.clientX, event.clientY, `<strong>${channel}</strong><br>${formatNumber(frequency, 2)} Hz · ${source.mode}<br>${label} ${formatNumber(source.logMatrix[sourceIndex][hit.freqIndex], 2)}`);
    drawHeatmap();
  });

  disposables.listen(heatmap, "mouseleave", () => {
    heatHover = null;
    tooltip.hide();
    drawHeatmap();
  });

  disposables.listen(heatmap, "click", (event) => {
    const hit = hitTest(event);
    if (hit) setChannel(getVisibleChannels(data)[hit.channelIndex]);
  });

  disposables.add(onChannelChange(render));
  disposables.add(onDisplayChange(() => {
    heatmapCacheKey = "";
    render();
  }));
  disposables.add(onPsdScaleChange(drawOverlay));
  disposables.add(onLiveChange(drawOverlay));
  disposables.add(onSessionsChange(() => {
    heatmapCacheKey = "";
    render();
  }));
  disposables.add(observeCanvas(heatmap, () => {
    heatmapCacheKey = "";
    drawHeatmap();
  }));
  disposables.add(observeCanvas(overlay, drawOverlay));

  function drawSessionOverlay(ctx, width, height, sessions, channel, mode) {
    const plotX = overlayMargins.left;
    const plotY = overlayMargins.top;
    const plotW = width - overlayMargins.left - overlayMargins.right;
    const plotH = height - overlayMargins.top - overlayMargins.bottom;
    const scale = getPsdScale();
    const series = sessions
      .map((session) => {
        const channelIndex = session.data.meta.channels.indexOf(channel);
        if (channelIndex < 0) return null;
        const sourceValues = session.data.welch_psd.psd[channelIndex] ?? [];
        return {
          session,
          frequencies: session.data.welch_psd.frequencies,
          values: mode === "delta" ? sourceValues : scale === "log" ? sourceValues.map(log10) : sourceValues,
        };
      })
      .filter(Boolean);

    if (!series.length) {
      ctx.fillStyle = MUTED_COLOR;
      ctx.font = `11px ${MONO_FONT}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("No active sessions", width / 2, height / 2);
      return;
    }

    const [minY, maxY] = mode === "delta"
      ? extent(series.flatMap((item) => item.values.concat(0)))
      : extent(series.map((item) => item.values));
    const xScale = scaleLinear(series[0].frequencies[0], series[0].frequencies.at(-1), plotX, plotX + plotW);
    const yScale = scaleLinear(minY, maxY, plotY + plotH, plotY);

    ctx.fillStyle = AXIS_COLOR;
    ctx.font = `600 11px ${MONO_FONT}`;
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(`${mode === "delta" ? "PSD Δ" : "PSD overlay"} · ${channel}`, plotX, 14);

    drawFrequencyBands(ctx, xScale, plotY, plotH, { labels: false });
    ctx.strokeStyle = PLOT_BORDER_COLOR;
    ctx.strokeRect(plotX, plotY, plotW, plotH);
    if (mode === "delta") {
      const zeroY = yScale(0);
      ctx.strokeStyle = "rgba(255,255,255,0.18)";
      ctx.beginPath();
      ctx.moveTo(plotX, zeroY);
      ctx.lineTo(plotX + plotW, zeroY);
      ctx.stroke();
    }
    ctx.fillStyle = MUTED_COLOR;
    ctx.font = `10px ${MONO_FONT}`;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(formatNumber(maxY, 1), plotX - 6, plotY);
    ctx.fillText(formatNumber(minY, 1), plotX - 6, plotY + plotH);

    series.forEach((item) => {
      drawLine(
        ctx,
        item.frequencies.map((frequency, index) => ({
          x: xScale(frequency),
          y: yScale(item.values[index]),
        })),
        item.session.color,
        1.8,
      );
    });
    drawBottomAxis(ctx, frequencyTicks(plotW, series[0].frequencies), xScale, plotY + plotH, `${mode === "delta" ? "delta" : scale} · Hz`);
  }

  function heatmapSession() {
    if (getViewMode() === "delta") {
      const baseline = getBaselineSession(data);
      return getRenderSessions(data).find((session) => session.deltaSource?.id !== baseline?.id) ?? getRenderSessions(data)[0];
    }
    return getBaselineSession(data) ?? getComparisonSessions(data)[0];
  }

  return () => {
    heatmapCacheKey = "";
    heatmapCache = null;
    disposables.dispose();
  };
}

function heatmapColor(value, min, max) {
  return rgbString(paletteColor((value - min) / (max - min || 1)));
}

function frequencyTicks(plotW, frequencies) {
  const min = frequencies[0];
  const max = frequencies.at(-1);
  return plotW < 380 ? axisLabels(min, max, plotW, 56) : [1, 10, 20, 30, 40, 50, 55];
}

function paletteColor(t) {
  const nextT = Math.max(0, Math.min(1, t));
  const n = HEATMAP_PALETTE.length - 1;
  const i = Math.floor(nextT * n);
  const f = nextT * n - i;
  const a = HEATMAP_PALETTE[Math.min(i, n)];
  const b = HEATMAP_PALETTE[Math.min(i + 1, n)];
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
  ];
}

function rgbString(rgb) {
  return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
}
