import { readFileSync } from 'fs';

const data = JSON.parse(readFileSync('data/data.json', 'utf8'));
const results = [];

function check(name, condition, detail = '') {
  const ok = !!condition;
  results.push({ name, ok, detail });
  if (!ok) console.error(`FAIL: ${name} — ${detail}`);
}

// Meta
check('meta.channels length', data.meta.channels.length === 32, `got ${data.meta.channels.length}`);
check('meta.n_channels', data.meta.n_channels === 32);

// Welch PSD
check('welch_psd.frequencies length', data.welch_psd.frequencies.length === 217,
  `got ${data.welch_psd.frequencies.length}`);
check('welch_psd.psd channels', data.welch_psd.psd.length === 32);
check('welch_psd.psd[0] length', data.welch_psd.psd[0].length === 217);
check('welch_psd freq range', data.welch_psd.frequencies[0] >= 0.9 && data.welch_psd.frequencies[0] <= 1.1);
check('welch_psd freq max', data.welch_psd.frequencies.at(-1) >= 54 && data.welch_psd.frequencies.at(-1) <= 56);

// NaN/Infinity in PSD
const psdFlat = data.welch_psd.psd.flat();
const psdBad = psdFlat.filter(v => !isFinite(v) || isNaN(v)).length;
check('welch_psd no NaN/Inf', psdBad === 0, `found ${psdBad} bad values`);
check('welch_psd all positive', psdFlat.every(v => v >= 0), 'negative PSD values');

// Centroid
check('centroid.time_relative length', data.centroid.time_relative.length === 210,
  `got ${data.centroid.time_relative.length}`);
check('centroid.values channels', data.centroid.values.length === 32);
check('centroid.values[0] length', data.centroid.values[0].length === 210);
const centroidFlat = data.centroid.values.flat();
check('centroid no NaN', centroidFlat.filter(v => isNaN(v)).length === 0);
check('centroid in Hz range', centroidFlat.every(v => v >= 0 && v <= 60), 'values outside 0-60 Hz');

// Geometry
const GEO_KEYS = ['centroid','spread','entropy','flatness','edge95','alpha_relative_power'];
for (const key of GEO_KEYS) {
  check(`geometry.${key} exists`, key in data.geometry);
  check(`geometry.${key} channels`, data.geometry[key]?.length === 32);
  check(`geometry.${key}[0] length`, data.geometry[key]?.[0]?.length === 420,
    `got ${data.geometry[key]?.[0]?.length}`);
  const flat = data.geometry[key]?.flat() ?? [];
  check(`geometry.${key} no NaN`, flat.filter(v => isNaN(v)).length === 0,
    `${flat.filter(v=>isNaN(v)).length} NaN`);
  check(`geometry.${key} no Inf`, flat.filter(v => !isFinite(v)).length === 0);
}
check('geometry.time length', data.geometry.time.length === 420);
check('geometry alpha_relative_power range',
  data.geometry.alpha_relative_power.flat().every(v => v >= -0.1 && v <= 1.1),
  'values outside [-0.1, 1.1]');

// Area normalized PSD
check('geometry.area_normalized_psd exists', 'area_normalized_psd' in data.geometry);
check('geometry.area_normalized_psd.psd channels',
  data.geometry.area_normalized_psd?.psd?.length === 32);

if (data.geometry.higuchi_fd) {
  check('geometry.higuchi_fd channels', data.geometry.higuchi_fd.length === 32);
  check('geometry.higuchi_fd[0] length', data.geometry.higuchi_fd[0]?.length === data.geometry.time.length,
    `got ${data.geometry.higuchi_fd[0]?.length}`);
  const hfdFlat = data.geometry.higuchi_fd.flat();
  check('geometry.higuchi_fd no NaN', hfdFlat.filter(v => isNaN(v)).length === 0);
  check('geometry.higuchi_fd finite', hfdFlat.every(v => isFinite(v)));
}

// Channel summary
check('channel_summary length', data.channel_summary.length === 32);
const REQUIRED_FIELDS = ['channel','hemisphere','region','has_clear_alpha_peak','alpha_relative_power'];
for (const field of REQUIRED_FIELDS) {
  const missing = data.channel_summary.filter(ch => !(field in ch)).length;
  check(`channel_summary.${field} present in all`, missing === 0, `missing in ${missing} channels`);
}
// All channels from meta.channels are in channel_summary
const summaryChannels = new Set(data.channel_summary.map(c => c.channel));
const metaChannels = data.meta.channels;
const missingInSummary = metaChannels.filter(c => !summaryChannels.has(c));
check('channel_summary covers all meta.channels', missingInSummary.length === 0,
  `missing: ${missingInSummary.join(', ')}`);

if (data.channel_summary.some(ch => ch.variability)) {
  const missingVariability = data.channel_summary.filter(ch => !ch.variability?.alpha_range).length;
  check('channel_summary variability alpha_range present', missingVariability === 0,
    `missing in ${missingVariability} channels`);
  const badVariability = data.channel_summary
    .flatMap(ch => Object.values(ch.variability ?? {}))
    .filter(v => !isFinite(v) || isNaN(v)).length;
  check('channel_summary variability finite', badVariability === 0, `found ${badVariability} bad values`);
}

if (data.channel_summary.some(ch => 'lyapunov_exponent' in ch)) {
  const missingLyapunov = data.channel_summary.filter(ch => !isFinite(ch.lyapunov_exponent)).length;
  check('channel_summary lyapunov_exponent finite', missingLyapunov === 0,
    `missing/bad in ${missingLyapunov} channels`);
}

// Phase 2 optional sections
if (data.polar_chronomap) {
  check('polar_chronomap.time length', data.polar_chronomap.time.length === data.geometry.time.length,
    `got ${data.polar_chronomap.time.length}`);
  check('polar_chronomap posterior_alpha length', data.polar_chronomap.posterior_alpha.length === data.geometry.time.length);
  check('polar_chronomap frontal_alpha length', data.polar_chronomap.frontal_alpha.length === data.geometry.time.length);
  check('polar_chronomap balance no NaN',
    data.polar_chronomap.balance.every(v => isFinite(v) && !isNaN(v)));
  check('polar_chronomap posterior channels present',
    Array.isArray(data.polar_chronomap.posterior_channels) && data.polar_chronomap.posterior_channels.length > 0);
  check('polar_chronomap frontal channels present',
    Array.isArray(data.polar_chronomap.frontal_channels) && data.polar_chronomap.frontal_channels.length > 0);
}

if (data.channel_network) {
  check('channel_network channels length', data.channel_network.channels?.length === 32);
  check('channel_network composite 32x32',
    data.channel_network.composite_correlation?.length === 32 &&
    data.channel_network.composite_correlation?.[0]?.length === 32);
  check('channel_network composite finite',
    data.channel_network.composite_correlation.flat().every(v => isFinite(v) && !isNaN(v)));
  check('channel_network per_metric includes alpha',
    Array.isArray(data.channel_network.per_metric?.alpha_relative_power));
}

// Phase 3 optional sections
if (data.kuramoto) {
  check('kuramoto.order_parameter_r length', data.kuramoto.order_parameter_r?.length === data.geometry.time.length);
  check('kuramoto.order_parameter_r range',
    data.kuramoto.order_parameter_r.every(v => v >= 0 && v <= 1));
  check('kuramoto.channel_phases 32 channels', data.kuramoto.channel_phases?.length === 32);
}

if (data.phase_synchrony) {
  check('plv_static 32x32',
    data.phase_synchrony.plv_static?.length === 32 &&
    data.phase_synchrony.plv_static?.[0]?.length === 32);
  check('plv_static range',
    data.phase_synchrony.plv_static.flat().every(v => v >= 0 && v <= 1));
  if (data.phase_synchrony.plv_sliding) {
    check('plv_sliding has time axis',
      data.phase_synchrony.plv_sliding_time?.length === data.phase_synchrony.plv_sliding.length);
    check('plv_sliding first matrix 32x32',
      data.phase_synchrony.plv_sliding[0]?.length === 32 &&
      data.phase_synchrony.plv_sliding[0]?.[0]?.length === 32);
  }
}

if (data.tda && data.tda.status === 'computed') {
  check('tda point_cloud 32 rows', data.tda.point_cloud?.length === 32);
  check('tda h0 finite', data.tda.h0.flat().every(v => isFinite(v) && !isNaN(v)));
  check('tda h1 finite', data.tda.h1.flat().every(v => isFinite(v) && !isNaN(v)));
}

// Summary
const passed = results.filter(r => r.ok).length;
const failed = results.filter(r => !r.ok).length;
console.log(`\nData Integrity: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
