import { test } from "node:test";
import assert from "node:assert/strict";

import { validateData } from "../js/sources/static-source.js";

function makeData(channelCount, withMea = false) {
  const channels = Array.from({ length: channelCount }, (_, i) => `CH${i + 1}`);
  const data = {
    meta: { channels, n_channels: channelCount },
    welch_psd: {
      frequencies: [1, 2, 3],
      psd: channels.map(() => [0.1, 0.2, 0.3]),
    },
    centroid: {
      time_relative: [0, 1],
      values: channels.map(() => [10, 11]),
    },
    geometry: { time: [0, 1] },
  };

  if (withMea) {
    data.mea = {
      sampling_rate_hz: 1000,
      traces: channels.map(() => [0.1, 0.2]),
    };
  }

  return data;
}

test("validateData accepts a non-32 channel count", () => {
  assert.doesNotThrow(() => validateData(makeData(8)));
  assert.doesNotThrow(() => validateData(makeData(60)));
  assert.doesNotThrow(() => validateData(makeData(32)));
  assert.doesNotThrow(() => validateData(makeData(8, true)));
});

test("validateData rejects an empty or missing channel list", () => {
  assert.throws(() => validateData(makeData(0)), /non-empty meta\.channels/);
  assert.throws(() => validateData({ meta: {} }), /non-empty meta\.channels/);
});

test("validateData rejects channel-major arrays that disagree with meta.channels", () => {
  const data = makeData(8);
  data.welch_psd.psd = data.welch_psd.psd.slice(0, 6);
  assert.throws(() => validateData(data), /welch_psd\.psd/);

  const data2 = makeData(8);
  data2.centroid.values = data2.centroid.values.slice(0, 7);
  assert.throws(() => validateData(data2), /centroid\.values/);
});

test("validateData accepts and validates optional top-level mea traces", () => {
  const data = makeData(8, true);
  data.mea.traces = data.mea.traces.slice(0, 7);
  assert.throws(() => validateData(data), /mea.traces.*meta.channels/);

  data.mea = {
    sampling_rate_hz: 1000,
    traces: Array.from({ length: 8 }, () => []),
  };
  assert.throws(() => validateData(data), /mea.traces\[0\].*non-empty/);

  data.mea = {
    sampling_rate_hz: Number.POSITIVE_INFINITY,
    traces: Array.from({ length: 8 }, () => [0.1, 0.2]),
  };
  assert.throws(() => validateData(data), /mea\.sampling_rate_hz/);

  data.mea = {
    sampling_rate_hz: 1000,
    traces: Array.from({ length: 8 }, () => [0.1, 0.2]),
  };
  data.mea.traces[0][0] = Number.NaN;
  assert.throws(() => validateData(data), /mea.traces.*finite/);

  delete data.mea;
  assert.doesNotThrow(() => validateData(data));
});
