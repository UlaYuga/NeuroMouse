import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import fc from "fast-check";

import { validateDataset, type ValidateDatasetResult } from "../src/index.js";

type DatasetObject = Record<string, any>;

const repoRoot = resolve(process.cwd(), "..", "..");
const goldenPath = resolve(repoRoot, "datasets", "golden", "data.json");

function loadGolden(): DatasetObject {
  return JSON.parse(readFileSync(goldenPath, "utf8")) as DatasetObject;
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function assertValid(result: ValidateDatasetResult, message?: string): void {
  assert.equal(
    result.valid,
    true,
    message ?? result.errors.map((error) => error.message).join("\n"),
  );
  assert.deepEqual(result.errors, []);
}

function assertInvalid(
  result: ValidateDatasetResult,
  expectedPattern: RegExp,
  message?: string,
): void {
  assert.equal(result.valid, false, message ?? "expected validation to reject dataset");
  assert.match(
    result.errors.map((error) => `${error.path}: ${error.message}`).join("\n"),
    expectedPattern,
  );
}

function resizeGoldenChannels(data: DatasetObject, channelCount: number): DatasetObject {
  const firstPsdRow = data.welch_psd.psd[0];
  const firstCentroidRow = data.centroid.values[0];
  const channels = Array.from({ length: channelCount }, (_, index) => `CH${index + 1}`);

  data.meta.channels = channels;
  data.meta.n_channels = channelCount;
  data.welch_psd.psd = channels.map(() => [...firstPsdRow]);
  data.centroid.values = channels.map(() => [...firstCentroidRow]);
  return data;
}

const mutationCases: Array<{
  name: string;
  mutate: (data: DatasetObject) => void;
  expected: RegExp;
}> = [
  {
    name: "NaN in welch_psd.frequencies",
    mutate: (data) => {
      data.welch_psd.frequencies[0] = Number.NaN;
    },
    expected: /welch_psd\.frequencies\[0\].*finite number/,
  },
  {
    name: "+Infinity in welch_psd.psd",
    mutate: (data) => {
      data.welch_psd.psd[0][0] = Number.POSITIVE_INFINITY;
    },
    expected: /welch_psd\.psd\[0\]\[0\].*finite number/,
  },
  {
    name: "-Infinity in centroid.values",
    mutate: (data) => {
      data.centroid.values[0][0] = Number.NEGATIVE_INFINITY;
    },
    expected: /centroid\.values\[0\]\[0\].*finite number/,
  },
  {
    name: "NaN in geometry.time",
    mutate: (data) => {
      data.geometry.time[0] = Number.NaN;
    },
    expected: /geometry\.time\[0\].*finite number/,
  },
  {
    name: "meta.n_channels mismatch",
    mutate: (data) => {
      data.meta.n_channels = data.meta.channels.length + 1;
    },
    expected: /meta\.n_channels.*must equal meta\.channels\.length/,
  },
  {
    name: "meta.n_channels is not an integer",
    mutate: (data) => {
      data.meta.n_channels = 32.5;
    },
    expected: /meta\.n_channels.*positive integer/,
  },
  {
    name: "wrong-length PSD row",
    mutate: (data) => {
      data.welch_psd.psd[0] = data.welch_psd.psd[0].slice(1);
    },
    expected: /welch_psd\.psd\[0\].*must contain .* values/,
  },
  {
    name: "PSD row is not an array",
    mutate: (data) => {
      data.welch_psd.psd[0] = "not a row";
    },
    expected: /welch_psd\.psd\[0\].*must be an array/,
  },
  {
    name: "wrong-length centroid row",
    mutate: (data) => {
      data.centroid.values[0] = data.centroid.values[0].slice(1);
    },
    expected: /centroid\.values\[0\].*must contain .* values/,
  },
  {
    name: "centroid row is not an array",
    mutate: (data) => {
      data.centroid.values[0] = "not a row";
    },
    expected: /centroid\.values\[0\].*must be an array/,
  },
  {
    name: "empty welch frequency axis",
    mutate: (data) => {
      data.welch_psd.frequencies = [];
      data.welch_psd.psd = data.welch_psd.psd.map(() => []);
    },
    expected: /welch_psd\.frequencies.*non-empty/,
  },
  {
    name: "empty centroid time axis",
    mutate: (data) => {
      data.centroid.time_relative = [];
      data.centroid.values = data.centroid.values.map(() => []);
    },
    expected: /centroid\.time_relative.*non-empty/,
  },
  {
    name: "empty geometry time axis",
    mutate: (data) => {
      data.geometry.time = [];
    },
    expected: /geometry\.time.*non-empty/,
  },
  {
    name: "4097 channels exceed default ceiling",
    mutate: (data) => {
      resizeGoldenChannels(data, 4097);
    },
    expected: /meta\.channels.*at most 4096/,
  },
];

test("golden data.json validates with zero errors", () => {
  assertValid(validateDataset(loadGolden()));
});

test("golden-derived mutation fixtures reject with clear errors", async (t) => {
  for (const { name, mutate, expected } of mutationCases) {
    await t.test(name, () => {
      const data = clone(loadGolden());
      mutate(data);
      assertInvalid(validateDataset(data), expected);
    });
  }
});

test("channel ceiling accepts 1024 channels by default", () => {
  const data = resizeGoldenChannels(clone(loadGolden()), 1024);
  assertValid(validateDataset(data));
});

test("channel ceiling is configurable", () => {
  const data = resizeGoldenChannels(clone(loadGolden()), 1024);
  assertInvalid(validateDataset(data, { maxChannels: 512 }), /meta\.channels.*at most 512/);
  assertValid(validateDataset(data, { maxChannels: 1024 }));
});

const finiteNumber = fc.double({
  noNaN: true,
  noDefaultInfinity: true,
  min: -1_000_000,
  max: 1_000_000,
});

function fixedRows(channelCount: number, width: number): fc.Arbitrary<number[][]> {
  return fc.array(fc.array(finiteNumber, { minLength: width, maxLength: width }), {
    minLength: channelCount,
    maxLength: channelCount,
  });
}

const validDatasetArbitrary = fc
  .record({
    channelCount: fc.integer({ min: 1, max: 24 }),
    frequencyCount: fc.integer({ min: 1, max: 12 }),
    centroidPointCount: fc.integer({ min: 1, max: 12 }),
    geometryPointCount: fc.integer({ min: 1, max: 12 }),
  })
  .chain(({ channelCount, frequencyCount, centroidPointCount, geometryPointCount }) => {
    const channels = Array.from({ length: channelCount }, (_, index) => `CH${index + 1}`);
    return fc.record({
      welch_psd: fc.record({
        frequencies: fc.array(finiteNumber, {
          minLength: frequencyCount,
          maxLength: frequencyCount,
        }),
        psd: fixedRows(channelCount, frequencyCount),
      }),
      centroid: fc.record({
        time_relative: fc.array(finiteNumber, {
          minLength: centroidPointCount,
          maxLength: centroidPointCount,
        }),
        values: fixedRows(channelCount, centroidPointCount),
      }),
      geometry: fc.record({
        time: fc.array(finiteNumber, {
          minLength: geometryPointCount,
          maxLength: geometryPointCount,
        }),
      }),
    }).map((parts) => ({
      meta: { channels, n_channels: channelCount },
      ...parts,
    }));
  });

const invalidMutatorArbitrary = fc.constantFrom<(data: DatasetObject) => void>(
  (data) => {
    data.welch_psd.frequencies[0] = Number.NaN;
  },
  (data) => {
    data.welch_psd.psd[0] = data.welch_psd.psd[0].slice(1);
  },
  (data) => {
    data.centroid.values[0] = data.centroid.values[0].slice(1);
  },
  (data) => {
    data.geometry.time = [];
  },
  (data) => {
    data.meta.n_channels = data.meta.channels.length + 1;
  },
);

test("fast-check: generated valid datasets pass", () => {
  fc.assert(
    fc.property(validDatasetArbitrary, (data) => {
      const result = validateDataset(data);
      assert.equal(result.valid, true, JSON.stringify(result.errors));
    }),
    { numRuns: 1500 },
  );
});

test("fast-check: targeted invalid mutations reject", () => {
  fc.assert(
    fc.property(validDatasetArbitrary, invalidMutatorArbitrary, (data, mutate) => {
      const invalid = clone(data);
      mutate(invalid);
      const result = validateDataset(invalid);
      assert.equal(result.valid, false, "targeted invalid mutation unexpectedly passed");
      assert.ok(result.errors.length > 0);
    }),
    { numRuns: 1500 },
  );
});
