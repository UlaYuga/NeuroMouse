import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { buildViewerStructure, createViewerApp } from "../packages/web/viewer.js";
import baseline from "./fixtures/viewer-structure-baseline.json" with { type: "json" };

const goldenDataset = JSON.parse(await readFile(new URL("../datasets/golden/data.json", import.meta.url), "utf8"));

test("viewer exposes the extracted app API", () => {
  assert.equal(typeof createViewerApp, "function");
  assert.equal(typeof buildViewerStructure, "function");
});

test("viewer renders the golden dataset with the pre-refactor panel structure", () => {
  const snapshot = buildViewerStructure({
    dataset: goldenDataset,
    scenarioId: "trained-vs-naive",
  });

  assert.deepEqual(snapshot, baseline);
});
