// Plot colors resolve from CSS custom properties (defined in style.css :root)
// so a redesign can recolor every canvas/SVG view by editing tokens in one
// place. Each falls back to its original value if the token is absent, so
// rendering is unchanged when the stylesheet has not defined the token.
function token(name, fallback) {
  if (typeof document === "undefined" || !document.documentElement) return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export const ACTIVE_COLOR = token("--chart-active", "#c6f000");
export const SECONDARY_COLOR = token("--chart-secondary", "#c6f000");
export const GRID_COLOR = token("--chart-grid", "rgba(20,24,26,0.055)");
export const AXIS_COLOR = token("--chart-axis", "#91A2AD");
export const MUTED_COLOR = token("--chart-muted", "#737D88");
export const CHART_BACKGROUND = token("--chart-bg", "#0D1014");
export const PLOT_BORDER_COLOR = token("--chart-plot-border", "rgba(20,24,26,0.1)");
export const PLAYBACK_CURSOR_COLOR = token("--chart-cursor", "rgba(159,192,0,0.6)");
export const ACTIVE_GLOW_COLOR = token("--chart-active-glow", "rgba(159,192,0,0.4)");
export const MONO_FONT = "\"Geist Mono\", \"Spline Sans Mono\", \"IBM Plex Mono\", ui-monospace, \"SF Mono\", \"Menlo\", monospace";
export const FREQUENCY_BANDS = [
  { label: "delta", min: 1, max: 4, color: "rgba(20,24,26,0.035)" },
  { label: "theta", min: 4, max: 8, color: "rgba(20,24,26,0.02)" },
  { label: "alpha", min: 8, max: 13, color: "rgba(198,240,0,0.16)" },
  { label: "beta", min: 13, max: 30, color: "rgba(20,24,26,0.02)" },
  { label: "gamma", min: 30, max: 55, color: "rgba(20,24,26,0.035)" },
];

// milk → ink density ramp (light lab-plate heatmap)
const VIRIDIS = [
  [244, 243, 239],
  [206, 208, 203],
  [138, 142, 142],
  [58, 62, 64],
  [20, 24, 26],
];

// diverging: ink (negative) → milk (zero) → acid (positive)
const DELTA_PALETTE = [
  [-1.0, [20, 24, 26]],
  [-0.3, [120, 124, 124]],
  [0.0, [244, 243, 239]],
  [0.3, [176, 200, 40]],
  [1.0, [159, 192, 0]],
];

export function resizeCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(rect.width));
  const height = Math.max(1, Math.round(rect.height));
  const pixelWidth = Math.round(width * dpr);
  const pixelHeight = Math.round(height * dpr);

  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, width, height };
}

export function observeCanvas(canvas, render) {
  let frame = 0;
  const requestRender = () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(render);
  };

  const observer = new ResizeObserver(requestRender);
  observer.observe(canvas);
  requestRender();

  return () => {
    cancelAnimationFrame(frame);
    observer.disconnect();
  };
}

export function canvasPoint(event, canvas) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  };
}

export function clear(ctx, width, height, color = CHART_BACKGROUND) {
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, width, height);
}

export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export function extent(values) {
  let min = Infinity;
  let max = -Infinity;
  for (const value of values.flat(Infinity)) {
    if (value == null || Number.isNaN(value)) continue;
    min = Math.min(min, value);
    max = Math.max(max, value);
  }
  return min === Infinity ? [0, 1] : [min, max];
}

export function paddedExtent(values, pad = 0.08) {
  const [min, max] = extent(values);
  if (min === max) return [min - 1, max + 1];
  const delta = (max - min) * pad;
  return [min - delta, max + delta];
}

export function log10(value) {
  return Math.log10(Math.max(value ?? 0, 1e-12));
}

export function scaleLinear(domainMin, domainMax, rangeMin, rangeMax) {
  const span = domainMax - domainMin || 1;
  return (value) => rangeMin + ((value - domainMin) / span) * (rangeMax - rangeMin);
}

export function axisLabels(min, max, pixelWidth, minGapPx = 55) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) return [min];
  const reversed = min > max;
  const from = reversed ? max : min;
  const to = reversed ? min : max;
  const range = to - from;
  const maxLabels = Math.max(2, Math.floor(Math.max(1, pixelWidth) / minGapPx));
  const rawStep = range / maxLabels;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const step = Math.max(magnitude, Math.ceil(rawStep / magnitude) * magnitude);
  const start = Math.ceil(from / step) * step;
  const labels = [];

  for (let value = start; value <= to + step * 0.001; value += step) {
    labels.push(Math.round(value * 100) / 100);
  }

  return reversed ? labels.reverse() : labels;
}

export function invertLinear(domainMin, domainMax, rangeMin, rangeMax) {
  const span = rangeMax - rangeMin || 1;
  return (value) => domainMin + ((value - rangeMin) / span) * (domainMax - domainMin);
}

export function colorScale(value, min, max) {
  const t = clamp((value - min) / (max - min || 1), 0, 1);
  const scaled = t * (VIRIDIS.length - 1);
  const idx = Math.min(VIRIDIS.length - 2, Math.floor(scaled));
  const local = scaled - idx;
  const a = VIRIDIS[idx];
  const b = VIRIDIS[idx + 1];
  const rgb = a.map((start, i) => Math.round(start + (b[i] - start) * local));
  return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
}

export function deltaColorScale(value, min, max) {
  const extent = Math.max(Math.abs(min), Math.abs(max), 1e-9);
  const normalized = clamp(value / extent, -1, 1);
  for (let index = 1; index < DELTA_PALETTE.length; index += 1) {
    const [stop, color] = DELTA_PALETTE[index];
    const [prevStop, prevColor] = DELTA_PALETTE[index - 1];
    if (normalized <= stop) {
      const local = (normalized - prevStop) / (stop - prevStop || 1);
      const rgb = prevColor.map((start, channel) => Math.round(start + (color[channel] - start) * local));
      return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
    }
  }
  const last = DELTA_PALETTE.at(-1)[1];
  return `rgb(${last[0]},${last[1]},${last[2]})`;
}

export function nearestIndex(values, target) {
  let best = 0;
  let bestDistance = Infinity;
  values.forEach((value, index) => {
    const distance = Math.abs(value - target);
    if (distance < bestDistance) {
      best = index;
      bestDistance = distance;
    }
  });
  return best;
}

export function drawBottomAxis(ctx, ticks, xScale, y, label) {
  if (!ticks.length) return;
  ctx.strokeStyle = GRID_COLOR;
  ctx.fillStyle = AXIS_COLOR;
  ctx.lineWidth = 1;
  ctx.font = `10px ${MONO_FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";

  for (const tick of ticks) {
    const x = xScale(tick);
    ctx.beginPath();
    ctx.moveTo(x, y - 6);
    ctx.lineTo(x, y);
    ctx.stroke();
    ctx.fillText(String(tick), x, y + 6);
  }

  if (label) {
    ctx.fillStyle = MUTED_COLOR;
    ctx.fillText(label, (xScale(ticks[0]) + xScale(ticks[ticks.length - 1])) / 2, y + 22);
  }
}

export function drawFrequencyBands(ctx, xScale, y, height, options = {}) {
  const { labels = false } = options;
  ctx.save();
  for (const band of FREQUENCY_BANDS) {
    const x0 = xScale(band.min);
    const x1 = xScale(band.max);
    ctx.fillStyle = band.color;
    ctx.fillRect(x0, y, Math.max(1, x1 - x0), height);
    if (labels) {
      ctx.fillStyle = MUTED_COLOR;
      ctx.font = `10px ${MONO_FONT}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(band.label, x0 + (x1 - x0) / 2, y + 5);
    }
  }
  ctx.restore();
}

export function drawLine(ctx, points, color, width = 1.5, alpha = 1) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  if (color === ACTIVE_COLOR) {
    ctx.shadowColor = ACTIVE_GLOW_COLOR;
    ctx.shadowBlur = 6;
  }
  ctx.beginPath();
  let hasPoint = false;
  points.forEach((point, index) => {
    if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) {
      hasPoint = false;
      return;
    }
    if (index === 0 || !hasPoint) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
    hasPoint = true;
  });
  ctx.stroke();
  ctx.restore();
}

export function distanceToSegment(point, a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = dx * dx + dy * dy;
  if (len === 0) return Math.hypot(point.x - a.x, point.y - a.y);
  const t = clamp(((point.x - a.x) * dx + (point.y - a.y) * dy) / len, 0, 1);
  const x = a.x + t * dx;
  const y = a.y + t * dy;
  return Math.hypot(point.x - x, point.y - y);
}

export function formatNumber(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return "n/a";
  return Number(value).toFixed(digits);
}

export function rankAt(valuesByChannel, channels, index, limit = 3) {
  const rows = channels
    .map((channel, channelIndex) => ({
      channel,
      value: valuesByChannel[channelIndex]?.[index],
    }))
    .filter((row) => Number.isFinite(row.value));
  const high = rows.slice().sort((a, b) => b.value - a.value).slice(0, limit);
  const low = rows.slice().sort((a, b) => a.value - b.value).slice(0, limit);
  return { high, low };
}
