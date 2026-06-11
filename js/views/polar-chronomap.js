import * as defaultState from "../state.js";
import { createDisposables } from "../disposables.js";
import {
  ACTIVE_COLOR,
  CHART_BACKGROUND,
  MONO_FONT,
  MUTED_COLOR,
  canvasPoint,
  clamp,
  clear,
  formatNumber,
  observeCanvas,
  resizeCanvas,
} from "./chart-utils.js";

export function initPolarChronomap(root, data, tooltip, context = {}) {
  const state = context.state ?? defaultState;
  const document = context.document ?? globalThis.document;
  const { getFrame, onFrameChange } = state;
  const section = root?.closest("section");
  if (!root || !data.polar_chronomap) {
    if (section) section.hidden = true;
    return () => {};
  }
  section.hidden = false;

  const disposables = createDisposables();
  const canvas = document.createElement("canvas");
  canvas.className = "chart chart-polar";
  canvas.width = 500;
  canvas.height = 500;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "Polar Alpha Chronomap");
  root.innerHTML = "";
  root.append(canvas);

  let hoverIndex = null;

  function draw() {
    const { ctx, width, height } = resizeCanvas(canvas);
    clear(ctx, width, height);

    const chronomap = data.polar_chronomap;
    const time = chronomap.time;
    const posterior = chronomap.posterior_alpha;
    const balance = chronomap.balance;
    const count = time.length;
    const cx = width / 2;
    const cy = height / 2;
    const outer = Math.min(cx, cy) * 0.84;
    const inner = outer * 0.24;
    const maxAlpha = Math.max(...posterior, 1e-9);
    const minBalance = Math.min(...balance);
    const maxBalance = Math.max(...balance);
    const lineWidth = Math.max(1.2, (2 * Math.PI * inner / count) * 0.9);

    ctx.save();
    ctx.translate(cx, cy);
    for (let index = 0; index < count; index += 1) {
      const angle = (index / count) * Math.PI * 2 - Math.PI / 2;
      const barHeight = (posterior[index] / maxAlpha) * (outer - inner);
      const t = clamp((balance[index] - minBalance) / (maxBalance - minBalance || 1), 0, 1);
      const r = 8 + Math.round(t * 20);
      const g = 74 + Math.round(t * 138);
      const b = 86 + Math.round(t * 74);
      ctx.strokeStyle = `rgba(${r},${g},${b},${index === hoverIndex ? 1 : 0.78})`;
      ctx.lineWidth = index === hoverIndex ? lineWidth * 1.8 : lineWidth;
      ctx.beginPath();
      ctx.moveTo(inner * Math.cos(angle), inner * Math.sin(angle));
      ctx.lineTo((inner + barHeight) * Math.cos(angle), (inner + barHeight) * Math.sin(angle));
      ctx.stroke();
    }

    ctx.strokeStyle = "rgba(255,255,255,0.11)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(0, 0, outer, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, 0, inner, 0, Math.PI * 2);
    ctx.stroke();

    const frame = Math.min(count - 1, getFrame());
    const cursor = (frame / count) * Math.PI * 2 - Math.PI / 2;
    ctx.strokeStyle = ACTIVE_COLOR;
    ctx.lineWidth = 1.2;
    ctx.shadowColor = "rgba(0,212,160,0.55)";
    ctx.shadowBlur = 10;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(outer * Math.cos(cursor), outer * Math.sin(cursor));
    ctx.stroke();
    ctx.shadowBlur = 0;

    drawLabels(ctx, time, outer, count);
    ctx.restore();

    ctx.fillStyle = MUTED_COLOR;
    ctx.font = `10px ${MONO_FONT}`;
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText("posterior alpha", 14, 14);
    ctx.fillStyle = ACTIVE_COLOR;
    ctx.fillText(`t=${formatNumber(time[frame], 2)}s`, 14, 30);
  }

  function drawLabels(ctx, time, outer, count) {
    ctx.fillStyle = MUTED_COLOR;
    ctx.font = `10px ${MONO_FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    [0, 0.25, 0.5, 0.75].forEach((fraction) => {
      const index = Math.floor(count * fraction);
      const angle = fraction * Math.PI * 2 - Math.PI / 2;
      ctx.fillText(`${formatNumber(time[index], 0)}s`, (outer + 18) * Math.cos(angle), (outer + 18) * Math.sin(angle));
    });
  }

  function hit(event) {
    const point = canvasPoint(event, canvas);
    const rect = canvas.getBoundingClientRect();
    const x = point.x - rect.width / 2;
    const y = point.y - rect.height / 2;
    const radius = Math.hypot(x, y);
    if (radius < rect.width * 0.1 || radius > rect.width * 0.44) return null;
    const angle = (Math.atan2(y, x) + Math.PI / 2 + Math.PI * 2) % (Math.PI * 2);
    return Math.min(data.polar_chronomap.time.length - 1, Math.floor((angle / (Math.PI * 2)) * data.polar_chronomap.time.length));
  }

  disposables.listen(canvas, "mousemove", (event) => {
    hoverIndex = hit(event);
    if (hoverIndex == null) {
      tooltip.hide();
      draw();
      return;
    }
    const chronomap = data.polar_chronomap;
    tooltip.show(
      event.clientX,
      event.clientY,
      `<strong>t=${formatNumber(chronomap.time[hoverIndex], 2)} sec</strong><br>posterior alpha ${formatNumber(chronomap.posterior_alpha[hoverIndex], 4)}<br>frontal alpha ${formatNumber(chronomap.frontal_alpha[hoverIndex], 4)}<br>balance ${formatNumber(chronomap.balance[hoverIndex], 4)}`,
    );
    draw();
  });
  disposables.listen(canvas, "mouseleave", () => {
    hoverIndex = null;
    tooltip.hide();
    draw();
  });
  disposables.add(onFrameChange(draw));
  disposables.add(observeCanvas(canvas, draw));
  return disposables.dispose;
}
