export const ACTIVE_COLOR = "#77d7c8";
export const SECONDARY_COLOR = "#f2c86d";
export const GRID_COLOR = "rgba(255,255,255,0.08)";
export const AXIS_COLOR = "rgba(240,244,247,0.68)";
export const MUTED_COLOR = "rgba(155,168,181,0.78)";

const VIRIDIS = [
  [68, 1, 84],
  [59, 82, 139],
  [33, 145, 140],
  [94, 201, 98],
  [253, 231, 37],
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

export function clear(ctx, width, height, color = "#171a1f") {
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
  ctx.strokeStyle = GRID_COLOR;
  ctx.fillStyle = AXIS_COLOR;
  ctx.lineWidth = 1;
  ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
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

export function drawLine(ctx, points, color, width = 1.5, alpha = 1) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  points.forEach((point, index) => {
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
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

