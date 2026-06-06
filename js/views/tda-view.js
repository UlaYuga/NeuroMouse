import { createDisposables } from "../disposables.js";
import {
  ACTIVE_COLOR,
  AXIS_COLOR,
  CHART_BACKGROUND,
  GRID_COLOR,
  MONO_FONT,
  MUTED_COLOR,
  canvasPoint,
  clear,
  formatNumber,
  observeCanvas,
  paddedExtent,
  resizeCanvas,
  scaleLinear,
} from "./chart-utils.js";

export function initTdaView(root, data, tooltip) {
  const section = root?.closest("section");
  if (!root || data.tda?.status !== "computed") {
    if (section) section.hidden = true;
    return () => {};
  }
  section.hidden = false;

  const disposables = createDisposables();
  const points = buildPersistencePoints(data);
  const scatter = document.createElement("canvas");
  const barcode = document.createElement("canvas");
  scatter.className = "chart chart-tda-scatter";
  barcode.className = "chart chart-tda-barcode";
  scatter.width = 420;
  scatter.height = 320;
  barcode.width = 420;
  barcode.height = 320;
  scatter.setAttribute("role", "img");
  scatter.setAttribute("aria-label", "TDA persistence scatter");
  barcode.setAttribute("role", "img");
  barcode.setAttribute("aria-label", "TDA persistence barcode");
  root.innerHTML = "";
  root.append(
    panel("Persistence", scatter),
    panel("Barcode", barcode),
  );

  let hover = null;

  function draw() {
    drawScatter();
    drawBarcode();
  }

  function drawScatter() {
    const { ctx, width, height } = resizeCanvas(scatter);
    clear(ctx, width, height);
    const margins = { left: 52, right: 18, top: 22, bottom: 44 };
    const plotX = margins.left;
    const plotY = margins.top;
    const plotW = width - margins.left - margins.right;
    const plotH = height - margins.top - margins.bottom;
    const values = points.flatMap((point) => [point.birth, point.death]);
    const [minValue, maxValue] = paddedExtent([values], 0.08);
    const xScale = scaleLinear(minValue, maxValue, plotX, plotX + plotW);
    const yScale = scaleLinear(minValue, maxValue, plotY + plotH, plotY);

    drawFrame(ctx, plotX, plotY, plotW, plotH);
    ctx.strokeStyle = "rgba(255,255,255,0.18)";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(xScale(minValue), yScale(minValue));
    ctx.lineTo(xScale(maxValue), yScale(maxValue));
    ctx.stroke();
    ctx.setLineDash([]);

    points.forEach((point, index) => {
      const x = xScale(point.birth);
      const y = yScale(point.death);
      const active = hover?.index === index;
      ctx.fillStyle = point.kind === "H1" ? "rgba(255,159,10,0.82)" : "rgba(0,212,160,0.78)";
      ctx.strokeStyle = active ? "#fff" : CHART_BACKGROUND;
      ctx.lineWidth = active ? 2 : 1;
      ctx.beginPath();
      ctx.arc(x, y, active ? 5.5 : 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });
    drawAxisLabels(ctx, plotX, plotY, plotW, plotH, "birth", "death");
  }

  function drawBarcode() {
    const { ctx, width, height } = resizeCanvas(barcode);
    clear(ctx, width, height);
    const sortedPoints = points.slice().sort((a, b) => b.lifetime - a.lifetime);
    const margins = { left: 54, right: 20, top: 24, bottom: 42 };
    const plotX = margins.left;
    const plotY = margins.top;
    const plotW = width - margins.left - margins.right;
    const plotH = height - margins.top - margins.bottom;
    const values = sortedPoints.flatMap((point) => [point.birth, point.death]);
    const [minValue, maxValue] = paddedExtent([values], 0.08);
    const xScale = scaleLinear(minValue, maxValue, plotX, plotX + plotW);
    const rowH = plotH / Math.max(1, sortedPoints.length);
    const maxLifetime = Math.max(...sortedPoints.map((point) => point.lifetime), 1e-9);

    drawFrame(ctx, plotX, plotY, plotW, plotH);
    sortedPoints.forEach((point, index) => {
      const y = plotY + rowH * index + rowH / 2;
      const t = point.lifetime / maxLifetime;
      ctx.strokeStyle = point.kind === "H1"
        ? `rgba(255,159,10,${0.28 + t * 0.72})`
        : `rgba(0,212,160,${0.22 + t * 0.78})`;
      ctx.lineWidth = Math.max(1, Math.min(4, rowH * 0.42));
      ctx.beginPath();
      ctx.moveTo(xScale(point.birth), y);
      ctx.lineTo(xScale(point.death), y);
      ctx.stroke();
    });
    drawAxisLabels(ctx, plotX, plotY, plotW, plotH, "filtration value", "");
  }

  function hit(event) {
    const rect = scatter.getBoundingClientRect();
    const point = canvasPoint(event, scatter);
    const margins = { left: 52, right: 18, top: 22, bottom: 44 };
    const plotX = margins.left;
    const plotY = margins.top;
    const plotW = rect.width - margins.left - margins.right;
    const plotH = rect.height - margins.top - margins.bottom;
    const values = points.flatMap((item) => [item.birth, item.death]);
    const [minValue, maxValue] = paddedExtent([values], 0.08);
    const xScale = scaleLinear(minValue, maxValue, plotX, plotX + plotW);
    const yScale = scaleLinear(minValue, maxValue, plotY + plotH, plotY);
    let best = null;
    let bestDistance = Infinity;
    points.forEach((item, index) => {
      const distance = Math.hypot(point.x - xScale(item.birth), point.y - yScale(item.death));
      if (distance < bestDistance) {
        best = { ...item, index };
        bestDistance = distance;
      }
    });
    return bestDistance <= 10 ? best : null;
  }

  disposables.listen(scatter, "mousemove", (event) => {
    hover = hit(event);
    if (!hover) {
      tooltip.hide();
      drawScatter();
      return;
    }
    tooltip.show(
      event.clientX,
      event.clientY,
      `<strong>${hover.kind}</strong><br>birth ${formatNumber(hover.birth, 3)}<br>death ${formatNumber(hover.death, 3)}<br>lifetime ${formatNumber(hover.lifetime, 3)}`,
    );
    drawScatter();
  });
  disposables.listen(scatter, "mouseleave", () => {
    hover = null;
    tooltip.hide();
    drawScatter();
  });
  disposables.add(observeCanvas(scatter, draw));
  disposables.add(observeCanvas(barcode, draw));
  return disposables.dispose;
}

function panel(title, canvas) {
  const wrapper = document.createElement("div");
  wrapper.className = "tda-panel";
  const heading = document.createElement("div");
  heading.className = "tda-subtitle";
  heading.textContent = title;
  wrapper.append(heading, canvas);
  return wrapper;
}

function drawFrame(ctx, x, y, width, height) {
  ctx.strokeStyle = "rgba(255,255,255,0.09)";
  ctx.strokeRect(x, y, width, height);
  ctx.strokeStyle = GRID_COLOR;
  for (let index = 1; index < 4; index += 1) {
    const gx = x + (width * index) / 4;
    const gy = y + (height * index) / 4;
    ctx.beginPath();
    ctx.moveTo(gx, y);
    ctx.lineTo(gx, y + height);
    ctx.moveTo(x, gy);
    ctx.lineTo(x + width, gy);
    ctx.stroke();
  }
}

function drawAxisLabels(ctx, x, y, width, height, xLabel, yLabel) {
  ctx.fillStyle = AXIS_COLOR;
  ctx.font = `10px ${MONO_FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText(xLabel, x + width / 2, y + height + 20, width);
  if (yLabel) {
    ctx.save();
    ctx.translate(16, y + height / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(yLabel, 0, 0, height);
    ctx.restore();
  }
  ctx.fillStyle = MUTED_COLOR;
  ctx.textAlign = "left";
  ctx.fillText("H0", x + 8, y + 8);
  ctx.fillStyle = "rgba(255,159,10,0.9)";
  ctx.fillText("H1", x + 34, y + 8);
  ctx.fillStyle = ACTIVE_COLOR;
}

function buildPersistencePoints(data) {
  return [
    ...(data.tda?.h0 ?? []).map(([birth, death]) => ({
      kind: "H0",
      birth,
      death,
      lifetime: death - birth,
    })),
    ...(data.tda?.h1 ?? []).map(([birth, death]) => ({
      kind: "H1",
      birth,
      death,
      lifetime: death - birth,
    })),
  ];
}
