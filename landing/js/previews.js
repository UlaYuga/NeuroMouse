// ============================================================================
// previews.js — detailed, real-data instrument previews (data-plate quality).
// Workbench marquee: PSD heatmap · band power · alpha ranking.
// Capability cards: cohort overlay · replay scrubber.
// All from window.NEURO. Static, redrawn on resize.
// ============================================================================

const D = () => window.NEURO || {};
const INK = "#14181a", RULE = "rgba(20,24,26,0.16)", RULE2 = "rgba(20,24,26,0.07)";
const MUTE = "rgba(20,24,26,0.42)", LIVE = "#c6f000", LIVE_DK = "#7e9a00";
const MONO = "'Geist Mono', monospace";

const BANDS = [
  { k: "δ", a: 1, b: 4 }, { k: "θ", a: 4, b: 8 },
  { k: "α", a: 8, b: 12, live: true }, { k: "β", a: 12, b: 30 }, { k: "γ", a: 30, b: 45 },
];

function hexRgb(h) { h = h.replace("#", ""); return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)]; }
function mix(c1, c2, t) { const a = hexRgb(c1), b = hexRgb(c2); return `rgb(${Math.round(a[0]+(b[0]-a[0])*t)},${Math.round(a[1]+(b[1]-a[1])*t)},${Math.round(a[2]+(b[2]-a[2])*t)})`; }
function fit(cv) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  return { ctx, W, H };
}
function bandSum(arr, freqs, lo, hi) { let s = 0; for (let i = 0; i < freqs.length; i++) if (freqs[i] >= lo && freqs[i] < hi) s += arr[i]; return s; }

// ── PSD heatmap · channels × frequency, with axes + labels ───────────────────
function heatmap(cv) {
  const d = D(); if (!d.psd) return;
  const { ctx, W, H } = fit(cv);
  ctx.fillStyle = "#f4f3ef"; ctx.fillRect(0, 0, W, H);
  const m = { l: 40, r: 10, t: 14, b: 26 }, pw = W - m.l - m.r, ph = H - m.t - m.b;
  const fi = []; d.freqs.forEach((f, i) => { if (f >= 1 && f <= 45) fi.push(i); });
  const rows = d.psd.length, cols = fi.length;
  let lo = Infinity, hi = -Infinity;
  d.psd.forEach(arr => fi.forEach(i => { const v = Math.log10(Math.max(arr[i], 0.01)); if (v < lo) lo = v; if (v > hi) hi = v; }));
  const cw = pw / cols, chh = ph / rows;
  for (let r = 0; r < rows; r++) {
    const arr = d.psd[r];
    for (let c = 0; c < cols; c++) {
      const v = Math.log10(Math.max(arr[fi[c]], 0.01)), t = (v - lo) / (hi - lo);
      ctx.fillStyle = mix("#f4f3ef", "#14181a", t);
      ctx.fillRect(m.l + c * cw, m.t + r * chh, cw + 0.6, chh + 0.6);
    }
  }
  // alpha band outline (acid)
  const fx = f => m.l + ((f - 1) / 44) * pw;
  ctx.strokeStyle = LIVE; ctx.lineWidth = 1.5; ctx.strokeRect(fx(8), m.t, fx(12) - fx(8), ph);
  // frame
  ctx.strokeStyle = RULE; ctx.lineWidth = 1; ctx.strokeRect(m.l, m.t, pw, ph);
  // freq ticks
  ctx.fillStyle = MUTE; ctx.font = `9px ${MONO}`; ctx.textAlign = "center";
  [1, 10, 20, 30, 40].forEach(f => ctx.fillText(String(f), fx(f), H - m.b + 14));
  ctx.fillText("frequency · Hz", m.l + pw / 2, H - 4);
  // channel y labels (a few)
  ctx.textAlign = "right";
  d.meta.channels.forEach((c, r) => { if (r % 6 === 0) ctx.fillText(c, m.l - 6, m.t + r * chh + chh + 2); });
}

// ── band power · δ θ α β γ bars for the lead channel ─────────────────────────
function bands(cv) {
  const d = D(); if (!d.psd) return;
  const { ctx, W, H } = fit(cv);
  ctx.fillStyle = "#f4f3ef"; ctx.fillRect(0, 0, W, H);
  const m = { l: 12, r: 12, t: 16, b: 28 }, pw = W - m.l - m.r, ph = H - m.t - m.b;
  const ci = d.meta.channels.indexOf("POz"); const arr = d.psd[ci >= 0 ? ci : 0];
  const vals = BANDS.map(bd => bandSum(arr, d.freqs, bd.a, bd.b));
  const max = Math.max(...vals);
  const gap = 14, bw = (pw - gap * (BANDS.length - 1)) / BANDS.length;
  // baseline grid
  ctx.strokeStyle = RULE2; ctx.lineWidth = 1;
  for (let g = 0; g <= 3; g++) { const y = m.t + (ph * g / 3); ctx.beginPath(); ctx.moveTo(m.l, y); ctx.lineTo(m.l + pw, y); ctx.stroke(); }
  BANDS.forEach((bd, i) => {
    const x = m.l + i * (bw + gap), h = (vals[i] / max) * ph, y = m.t + ph - h;
    ctx.fillStyle = bd.live ? LIVE : "rgba(20,24,26,0.82)";
    ctx.fillRect(x, y, bw, h);
    ctx.fillStyle = bd.live ? LIVE_DK : MUTE; ctx.font = `600 12px ${MONO}`; ctx.textAlign = "center";
    ctx.fillText(bd.k, x + bw / 2, H - 10);
  });
  ctx.strokeStyle = RULE; ctx.beginPath(); ctx.moveTo(m.l, m.t + ph); ctx.lineTo(m.l + pw, m.t + ph); ctx.stroke();
}

// ── alpha ranking · horizontal bars of alpha rel. power per channel ──────────
function rank(cv) {
  const d = D(); if (!d.alphaRel) return;
  const { ctx, W, H } = fit(cv);
  ctx.fillStyle = "#f4f3ef"; ctx.fillRect(0, 0, W, H);
  const m = { l: 42, r: 36, t: 12, b: 12 }, pw = W - m.l - m.r, ph = H - m.t - m.b;
  const ranked = d.meta.channels.map((c, i) => ({ c, v: d.alphaRel[i] })).sort((a, b) => b.v - a.v);
  const N = Math.min(8, ranked.length), max = ranked[0].v;
  const rowH = ph / N;
  ctx.font = `9px ${MONO}`;
  for (let i = 0; i < N; i++) {
    const r = ranked[i], y = m.t + i * rowH + rowH * 0.18, bh = rowH * 0.62;
    const bw = (r.v / max) * pw, lead = i === 0;
    ctx.fillStyle = lead ? LIVE : "rgba(20,24,26,0.7)";
    ctx.fillRect(m.l, y, bw, bh);
    ctx.fillStyle = INK; ctx.textAlign = "right"; ctx.fillText(r.c, m.l - 6, y + bh - 1);
    ctx.fillStyle = lead ? LIVE_DK : MUTE; ctx.textAlign = "left"; ctx.fillText(r.v.toFixed(3), m.l + bw + 5, y + bh - 1);
  }
}

// ── cohort overlay · three PSD curves ────────────────────────────────────────
function compare(cv) {
  const d = D(); if (!d.psd) return;
  const { ctx, W, H } = fit(cv);
  const m = { l: 8, r: 8, t: 12, b: 12 }, pw = W - m.l - m.r, ph = H - m.t - m.b;
  const fMin = 1, fMax = 40, fx = f => m.l + ((f - fMin) / (fMax - fMin)) * pw;
  const yMin = 0.05, yMax = 100, ly = v => { const t = (Math.log10(Math.max(v, yMin)) - Math.log10(yMin)) / (Math.log10(yMax) - Math.log10(yMin)); return m.t + (1 - t) * ph; };
  [["F3", "rgba(20,24,26,0.26)", 1.4], ["C4", "rgba(20,24,26,0.5)", 1.4], ["POz", LIVE, 2.2]].forEach(([ch, col, lw]) => {
    const ci = d.meta.channels.indexOf(ch); if (ci < 0) return;
    const arr = d.psd[ci]; let started = false; ctx.beginPath();
    for (let i = 0; i < d.freqs.length; i++) {
      const f = d.freqs[i]; if (f < fMin || f > fMax) continue;
      const x = fx(f), y = ly(arr[i]);
      started ? ctx.lineTo(x, y) : (ctx.moveTo(x, y), started = true);
    }
    ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.stroke();
  });
}

// ── replay · waveform + scrubber ─────────────────────────────────────────────
function replay(cv) {
  const { ctx, W, H } = fit(cv);
  const midY = H * 0.40;
  for (let line = 0; line < 3; line++) {
    ctx.beginPath();
    for (let x = 0; x <= W; x += 2) {
      const y = midY + Math.sin(x * 0.05 + line * 1.3) * (9 - line * 2) * Math.sin(x * 0.012 + 0.4);
      x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.strokeStyle = "rgba(20,24,26,0.34)"; ctx.lineWidth = 1; ctx.globalAlpha = 0.5 - line * 0.12; ctx.stroke();
  }
  ctx.globalAlpha = 1;
  const ty = H - 13, px = W * 0.46;
  ctx.strokeStyle = "rgba(20,24,26,0.18)"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(8, ty); ctx.lineTo(W - 8, ty); ctx.stroke();
  ctx.strokeStyle = LIVE_DK; ctx.beginPath(); ctx.moveTo(8, ty); ctx.lineTo(px, ty); ctx.stroke();
  ctx.strokeStyle = LIVE; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(px, 8); ctx.lineTo(px, H - 7); ctx.stroke();
  ctx.fillStyle = LIVE; ctx.beginPath(); ctx.arc(px, ty, 5, 0, 7); ctx.fill();
  ctx.strokeStyle = INK; ctx.lineWidth = 1; ctx.stroke();
}

export function initPreviews() {
  const ready = (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();
  const map = { "pv-heatmap": heatmap, "pv-bands": bands, "pv-rank": rank, "cap-compare": compare, "cap-replay": replay };
  const run = () => Object.entries(map).forEach(([id, fn]) => { const el = document.getElementById(id); if (el) fn(el); });
  ready.then(run);
  let to; window.addEventListener("resize", () => { clearTimeout(to); to = setTimeout(run, 200); });
}
