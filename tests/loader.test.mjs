import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { loadDatasetFiles } from "../js/loader.js";

const dataText = await readFile(new URL("../data/data.json", import.meta.url), "utf8");

test("loadDatasetFiles accepts direct NeuroMouse data.json files", async () => {
  const file = new File([dataText], "data.json", { type: "application/json" });

  const { datasets, errors } = await loadDatasetFiles([file]);

  assert.deepEqual(errors, []);
  assert.equal(datasets.length, 1);
  assert.equal(datasets[0].name, "data.json");
  assert.equal(datasets[0].data.meta.channels.length, 32);
});

test("loadDatasetFiles reports unsupported saved-data formats", async () => {
  const file = new File(["not a dataset"], "notes.txt", { type: "text/plain" });

  const { datasets, errors } = await loadDatasetFiles([file]);

  assert.deepEqual(datasets, []);
  assert.equal(errors.length, 1);
  assert.match(errors[0], /drop NeuroMouse data\.json or ZIP exports/);
});
