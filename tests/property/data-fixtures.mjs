import fc from "fast-check";

export const shapeArb = fc.record({
  channelCount: fc.integer({ min: 1, max: 48 }),
  freqCount: fc.integer({ min: 1, max: 24 }),
  centroidCount: fc.integer({ min: 1, max: 24 }),
  geometryCount: fc.integer({ min: 1, max: 24 }),
});

export const malformedDataMutations = [
  "missing-meta",
  "missing-channels",
  "empty-channels",
  "channels-not-array",
  "n-channels-mismatch",
  "missing-welch",
  "welch-frequencies-not-array",
  "welch-frequencies-empty",
  "welch-frequency-nan",
  "welch-psd-not-array",
  "welch-row-count-too-few",
  "welch-row-count-too-many",
  "welch-row-not-array",
  "welch-row-empty",
  "welch-row-length-mismatch",
  "welch-value-infinity",
  "missing-centroid",
  "centroid-time-not-array",
  "centroid-time-empty",
  "centroid-values-not-array",
  "centroid-row-count-too-few",
  "centroid-row-not-array",
  "centroid-row-length-mismatch",
  "centroid-value-nan",
  "missing-geometry",
  "geometry-time-not-array",
  "geometry-time-empty",
  "geometry-time-infinity",
  "mea-is-null",
  "mea-trace-row-count-too-few",
  "mea-trace-row-count-too-many",
  "mea-trace-row-not-array",
  "mea-trace-row-empty",
  "mea-trace-row-length-mismatch",
  "mea-trace-value-infinity",
  "oversized-channel-count",
];

export const malformedDataArb = fc.record({
  shape: shapeArb,
  mutation: fc.constantFrom(...malformedDataMutations),
});

export function makeCanonicalData({
  channelCount,
  freqCount,
  centroidCount,
  geometryCount,
}) {
  const channels = Array.from({ length: channelCount }, (_, index) => `C${index + 1}`);
  const frequencies = series(freqCount, 1, 0.25);
  const centroidTime = series(centroidCount, 0, 0.5);
  const geometryTime = series(geometryCount, 0, 0.25);

  return {
    meta: {
      channels,
      n_channels: channelCount,
      segment_duration_sec: round(geometryCount * 0.25),
      sampling_rate_analysis_hz: 256,
      welch_window_sec: 4,
      welch_overlap_fraction: 0.5,
      sliding_window_sec: 2,
      sliding_step_sec: 0.25,
      source: "property fixture",
      analysis_by: "tests/property",
    },
    welch_psd: {
      frequencies,
      psd: matrix(channelCount, freqCount, 0.1),
    },
    centroid: {
      time_relative: centroidTime,
      values: matrix(channelCount, centroidCount, 8),
    },
    geometry: {
      time: geometryTime,
      centroid: matrix(channelCount, geometryCount, 8),
      spread: matrix(channelCount, geometryCount, 1),
      entropy: matrix(channelCount, geometryCount, 0.4),
      flatness: matrix(channelCount, geometryCount, 0.1),
      edge95: matrix(channelCount, geometryCount, 20),
      alpha_relative_power: matrix(channelCount, geometryCount, 0.2),
      area_normalized_psd: {
        frequencies,
        psd: matrix(channelCount, freqCount, 0.01),
      },
    },
    mea: {
      sampling_rate_hz: 1000.0,
      traces: matrix(channelCount, 32, 0.0),
    },
    channel_summary: channels.map((channel, index) => ({
      channel,
      hemisphere: index % 2 === 0 ? "L" : "R",
      region: "property",
      has_clear_alpha_peak: index % 3 === 0,
      alpha_relative_power: round(0.2 + index * 0.001),
      spectral_centroid_hz: round(8 + index * 0.01),
      spectral_spread_hz: round(2 + index * 0.01),
      spectral_entropy: round(0.5 + index * 0.001),
      spectral_flatness: round(0.1 + index * 0.001),
      edge95_hz: round(20 + index * 0.01),
      alpha_peak_frequency_hz: 10,
      sliding_alpha_relative_mean: round(0.2 + index * 0.001),
    })),
  };
}

export function makeMalformedData({ shape, mutation }) {
  if (mutation === "oversized-channel-count") {
    return makeCanonicalData({
      channelCount: 4097,
      freqCount: 1,
      centroidCount: 1,
      geometryCount: 1,
    });
  }

  const data = structuredClone(makeCanonicalData(shape));

  switch (mutation) {
    case "missing-meta":
      delete data.meta;
      break;
    case "missing-channels":
      delete data.meta.channels;
      break;
    case "empty-channels":
      data.meta.channels = [];
      data.meta.n_channels = 0;
      data.welch_psd.psd = [];
      data.centroid.values = [];
      break;
    case "channels-not-array":
      data.meta.channels = "C1,C2";
      break;
    case "n-channels-mismatch":
      data.meta.n_channels = data.meta.channels.length + 1;
      break;
    case "missing-welch":
      delete data.welch_psd;
      break;
    case "welch-frequencies-not-array":
      data.welch_psd.frequencies = { 0: 1 };
      break;
    case "welch-frequencies-empty":
      data.welch_psd.frequencies = [];
      break;
    case "welch-frequency-nan":
      data.welch_psd.frequencies[0] = Number.NaN;
      break;
    case "welch-psd-not-array":
      data.welch_psd.psd = { rows: data.welch_psd.psd };
      break;
    case "welch-row-count-too-few":
      data.welch_psd.psd.pop();
      break;
    case "welch-row-count-too-many":
      data.welch_psd.psd.push([...data.welch_psd.psd[0]]);
      break;
    case "welch-row-not-array":
      data.welch_psd.psd[0] = { value: data.welch_psd.psd[0][0] };
      break;
    case "welch-row-empty":
      data.welch_psd.psd[0] = [];
      break;
    case "welch-row-length-mismatch":
      data.welch_psd.psd[0] = data.welch_psd.psd[0].slice(0, -1);
      break;
    case "welch-value-infinity":
      data.welch_psd.psd[0][0] = Number.POSITIVE_INFINITY;
      break;
    case "missing-centroid":
      delete data.centroid;
      break;
    case "centroid-time-not-array":
      data.centroid.time_relative = "0,1";
      break;
    case "centroid-time-empty":
      data.centroid.time_relative = [];
      break;
    case "centroid-values-not-array":
      data.centroid.values = { rows: data.centroid.values };
      break;
    case "centroid-row-count-too-few":
      data.centroid.values.pop();
      break;
    case "centroid-row-not-array":
      data.centroid.values[0] = { value: data.centroid.values[0][0] };
      break;
    case "centroid-row-length-mismatch":
      data.centroid.values[0] = data.centroid.values[0].slice(0, -1);
      break;
    case "centroid-value-nan":
      data.centroid.values[0][0] = Number.NaN;
      break;
    case "missing-geometry":
      delete data.geometry;
      break;
    case "geometry-time-not-array":
      data.geometry.time = { values: data.geometry.time };
      break;
    case "geometry-time-empty":
      data.geometry.time = [];
      break;
    case "geometry-time-infinity":
      data.geometry.time[0] = Number.POSITIVE_INFINITY;
      break;
    case "mea-is-null":
      data.mea = null;
      break;
    case "mea-trace-row-count-too-few":
      data.mea.traces.pop();
      break;
    case "mea-trace-row-count-too-many":
      data.mea.traces.push([...data.mea.traces[0]]);
      break;
    case "mea-trace-row-not-array":
      data.mea.traces[0] = { value: data.mea.traces[0][0] };
      break;
    case "mea-trace-row-empty":
      data.mea.traces[0] = [];
      break;
    case "mea-trace-row-length-mismatch":
      data.mea.traces[0] = data.mea.traces[0].slice(1);
      break;
    case "mea-trace-value-infinity":
      data.mea.traces[0][0] = Number.POSITIVE_INFINITY;
      break;
    default:
      throw new Error(`Unhandled mutation: ${mutation}`);
  }

  return data;
}

export function shapeRepro(shape) {
  return {
    channelCount: shape.channelCount,
    freqCount: shape.freqCount,
    centroidCount: shape.centroidCount,
    geometryCount: shape.geometryCount,
  };
}

function series(length, start, step) {
  return Array.from({ length }, (_, index) => round(start + index * step));
}

function matrix(rows, columns, base) {
  return Array.from({ length: rows }, (_, row) => (
    Array.from({ length: columns }, (_, column) => round(base + row * 0.01 + column * 0.001))
  ));
}

function round(value) {
  return Math.round(value * 1_000_000) / 1_000_000;
}
