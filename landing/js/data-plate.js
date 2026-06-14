// ============================================================================
// data-plate.js — the Swiss instrument (IMG-3 language) on REAL data.
//  · PSD spectral fan      — real Welch PSD, log-y, frequency bands
//  · alpha density map     — real alpha relative power over the 10-20 montage
// Hairline grid, coordinate ticks, crosshair markers, numbered tags, mono labels.
// ============================================================================

const D = () => window.NEURO || {};

// approximate 10-20 head positions: x −1(L)…+1(R), y +1(front)…−1(back)
const HEAD = {
  Fp1:[-0.27,0.92], Fpz:[0,0.97], Fp2:[0.27,0.92],
  F7:[-0.80,0.52], F3:[-0.40,0.54], Fz:[0,0.55], F4:[0.40,0.54], F8:[0.80,0.52],
  FC5:[-0.60,0.28], FC1:[-0.21,0.29], FC2:[0.21,0.29], FC6:[0.60,0.28],
  M1:[-0.96,-0.02], T7:[-0.90,0.02], C3:[-0.45,0.02], Cz:[0,0.02], C4:[0.45,0.02], T8:[0.90,0.02], M2:[0.96,-0.02],
  CP5:[-0.60,-0.26], CP1:[-0.21,-0.27], CP2:[0.21,-0.27], CP6:[0.60,-0.26],
  P7:[-0.80,-0.52], P3:[-0.40,-0.52], Pz:[0,-0.54], P4:[0.40,-0.52], P8:[0.80,-0.52],
  POz:[0,-0.72],
  O1:[-0.27,-0.90], Oz:[0,-0.96], O2:[0.27,-0.90],
};

const BANDS = [
  { k:"δ", a:1,  b:4  }, { k:"θ", a:4,  b:8 },
  { k:"α", a:8,  b:12, live:true }, { k:"β", a:12, b:30 }, { k:"γ", a:30, b:45 },
];

const INK = "#14181a", RULE = "rgba(20,24,26,0.16)", RULE2 = "rgba(20,24,26,0.07)";
const MUTE = "rgba(20,24,26,0.42)", LIVE = "#c6f000";

// ─────────────────────────────────────────────────────────────────────────────
// 1) PSD SPECTRAL FAN  (canvas)
// ─────────────────────────────────────────────────────────────────────────────
export function drawPSDFan(canvas) {
  const d = D(); if (!d.freqs) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const W = canvas.clientWidth, H = canvas.clientHeight;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d"); ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);

  const m = { l: 52, r: 18, t: 22, b: 40 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const fMin = 1, fMax = 45;
  const x = (f) => m.l + ((f - fMin) / (fMax - fMin)) * pw;
  // log-y over psd value range
  const yMin = 0.02, yMax = 100;
  const ly = (v) => {
    const t = (Math.log10(Math.max(v, yMin)) - Math.log10(yMin)) / (Math.log10(yMax) - Math.log10(yMin));
    return m.t + (1 - t) * ph;
  };

  // band regions
  BANDS.forEach((bd) => {
    const x0 = x(Math.max(bd.a, fMin)), x1 = x(Math.min(bd.b, fMax));
    ctx.fillStyle = bd.live ? "rgba(198,240,0,0.10)" : "rgba(20,24,26,0.028)";
    ctx.fillRect(x0, m.t, x1 - x0, ph);
    ctx.fillStyle = bd.live ? "#7e9a00" : MUTE;
    ctx.font = "600 11px 'Geist Mono', monospace";
    ctx.textAlign = "center";
    ctx.fillText(bd.k, (x0 + x1) / 2, m.t + 13);
  });

  // grid + ticks
  ctx.strokeStyle = RULE2; ctx.lineWidth = 1;
  ctx.fillStyle = MUTE; ctx.font = "10px 'Geist Mono', monospace";
  [1,5,10,15,20,25,30,35,40,45].forEach((f) => {
    ctx.beginPath(); ctx.moveTo(x(f), m.t); ctx.lineTo(x(f), m.t + ph); ctx.stroke();
    ctx.textAlign = "center"; ctx.fillText(String(f), x(f), H - m.b + 16);
  });
  ctx.textAlign = "right";
  [0.1, 1, 10, 100].forEach((v) => {
    ctx.strokeStyle = RULE2; ctx.beginPath(); ctx.moveTo(m.l, ly(v)); ctx.lineTo(m.l + pw, ly(v)); ctx.stroke();
    ctx.fillStyle = MUTE; ctx.fillText(v < 1 ? v.toFixed(1) : String(v), m.l - 8, ly(v) + 3);
  });

  // axis frame
  ctx.strokeStyle = RULE; ctx.strokeRect(m.l, m.t, pw, ph);

  // fan of real channel curves
  const fanIdx = d.fanIdx && d.fanIdx.length ? d.fanIdx : d.psd.map((_, i) => i).slice(0, 10);
  fanIdx.forEach((ci, k) => {
    const arr = d.psd[ci]; if (!arr) return;
    const isAlphaLead = d.meta.channels[ci] === "POz";
    ctx.beginPath();
    for (let i = 0; i < d.freqs.length; i++) {
      const f = d.freqs[i]; if (f < fMin || f > fMax) continue;
      const px = x(f), py = ly(arr[i]);
      i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
    }
    if (isAlphaLead) { ctx.strokeStyle = LIVE; ctx.lineWidth = 1.8; ctx.globalAlpha = 1; }
    else { ctx.strokeStyle = INK; ctx.lineWidth = 1; ctx.globalAlpha = 0.16 + k * 0.015; }
    ctx.stroke();
  });
  ctx.globalAlpha = 1;

  // y-axis caption
  ctx.save();
  ctx.translate(13, m.t + ph / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillStyle = MUTE; ctx.font = "9px 'Geist Mono', monospace"; ctx.textAlign = "center";
  ctx.fillText("PSD · a.u. (log)", 0, 0);
  ctx.restore();
  ctx.textAlign = "left";
  ctx.fillText("frequency · Hz", m.l, H - 6);
}

// ─────────────────────────────────────────────────────────────────────────────
// 2) ALPHA DENSITY MAP  (SVG, IMG-3 density plate over the montage)
// ─────────────────────────────────────────────────────────────────────────────
export function buildDensityMap(host) {
  const d = D(); if (!d.meta) return;
  const W = 1000, H = 720, cx = W * 0.46, cy = H * 0.5, R = 300;
  const px = (hx) => cx + hx * R;
  const py = (hy) => cy - hy * R;

  const channels = d.meta.channels;
  const alpha = d.alphaNorm;
  const ranked = channels.map((c, i) => ({ c, i, a: alpha[i], ar: d.alphaRel[i] })).sort((a, b) => b.a - a.a);
  const rankNum = new Map(); ranked.slice(0, 6).forEach((r, k) => rankNum.set(r.c, k + 1));
  const tagged = new Set(rankNum.keys());

  let blobs = "", marks = "", tags = "";
  channels.forEach((c, i) => {
    const p = HEAD[c]; if (!p) return;
    const X = px(p[0]), Y = py(p[1]);
    const a = alpha[i];
    const rad = 38 + a * 150;
    const isLead = ranked[0].c === c;
    const grad = isLead ? "url(#gLive)" : a > 0.45 ? "url(#gHot)" : "url(#gCool)";
    const op = 0.28 + a * 0.62;
    blobs += `<circle cx="${X.toFixed(1)}" cy="${Y.toFixed(1)}" r="${rad.toFixed(1)}" fill="${grad}" opacity="${op.toFixed(2)}"/>`;
    // crosshair marker
    const mc = isLead ? LIVE : INK;
    marks += `<g stroke="${mc}" stroke-width="${isLead ? 1.4 : 1}" opacity="${isLead ? 1 : 0.5}">`
      + `<line x1="${X - 6}" y1="${Y}" x2="${X + 6}" y2="${Y}"/><line x1="${X}" y1="${Y - 6}" x2="${X}" y2="${Y + 6}"/></g>`;
    if (tagged.has(c)) {
      const num = rankNum.get(c);
      const tx = X + 9, ty = Y - 9;
      tags += `<g font-family="'Geist Mono',monospace">`
        + `<rect x="${tx}" y="${ty - 13}" width="${10 + num.toString().length * 7}" height="16" fill="${isLead ? LIVE : "#14181a"}" rx="1"/>`
        + `<text x="${tx + 5}" y="${ty - 1}" font-size="11" font-weight="600" fill="${isLead ? "#14181a" : "#f4f3ef"}">${num}</text>`
        + `<text x="${tx + 16 + num.toString().length * 7}" y="${ty - 1}" font-size="11" fill="#14181a">${c} · α ${d.alphaRel[i].toFixed(3)}</text></g>`;
    }
  });

  // grid + coordinate ticks
  let grid = "";
  for (let gx = 0; gx <= W; gx += 100) grid += `<line x1="${gx}" y1="0" x2="${gx}" y2="${H}" stroke="${RULE2}"/>`;
  for (let gy = 0; gy <= H; gy += 100) grid += `<line x1="0" y1="${gy}" x2="${W}" y2="${gy}" stroke="${RULE2}"/>`;
  // center crosshair axes
  grid += `<line x1="${cx}" y1="0" x2="${cx}" y2="${H}" stroke="${RULE}" stroke-dasharray="2 4"/>`;
  grid += `<line x1="0" y1="${cy}" x2="${W}" y2="${cy}" stroke="${RULE}" stroke-dasharray="2 4"/>`;
  // head outline (montage boundary)
  grid += `<circle cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="${RULE}" stroke-dasharray="1 5"/>`;
  // nose
  grid += `<path d="M ${cx - 14} ${cy - R + 2} Q ${cx} ${cy - R - 22} ${cx + 14} ${cy - R + 2}" fill="none" stroke="${RULE}"/>`;

  // micro instrument furniture
  const furniture =
    `<g font-family="'Geist Mono',monospace" fill="${MUTE}" font-size="11" letter-spacing="1">`
    + `<text x="14" y="22">α · 8–12 Hz</text>`
    + `<text x="14" y="38" fill="#7e9a00">■ lead</text>`
    + `<g transform="translate(${W - 34},${H - 64})"><line x1="0" y1="20" x2="0" y2="-12" stroke="${INK}"/><path d="M -4 -6 L 0 -14 L 4 -6 Z" fill="${INK}"/><text x="6" y="-8" font-size="10">A</text><text x="6" y="24" font-size="10">P</text></g>`
    + `</g>`;

  host.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Alpha relative power density over the 10-20 montage">`
    + `<defs>`
    + `<radialGradient id="gCool"><stop offset="0%" stop-color="#3a4750" stop-opacity="0.5"/><stop offset="100%" stop-color="#3a4750" stop-opacity="0"/></radialGradient>`
    + `<radialGradient id="gHot"><stop offset="0%" stop-color="#1d2429" stop-opacity="0.62"/><stop offset="100%" stop-color="#1d2429" stop-opacity="0"/></radialGradient>`
    + `<radialGradient id="gLive"><stop offset="0%" stop-color="${LIVE}" stop-opacity="0.85"/><stop offset="45%" stop-color="${LIVE}" stop-opacity="0.32"/><stop offset="100%" stop-color="${LIVE}" stop-opacity="0"/></radialGradient>`
    + `</defs>`
    + grid + blobs + marks + tags + furniture
    + `</svg>`;
}

export function initInstrument() {
  const ready = (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();
  const run = () => {
    const fan = document.getElementById("psd-fan");
    if (fan) drawPSDFan(fan);
    const dens = document.getElementById("density-map");
    if (dens) buildDensityMap(dens);
  };
  ready.then(run);
  let to; window.addEventListener("resize", () => { clearTimeout(to); to = setTimeout(run, 180); });
}
