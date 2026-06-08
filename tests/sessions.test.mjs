import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { addSession, computeDelta, getSessions } from "../js/sessions.js";

const data = JSON.parse(await readFile(new URL("../data/data.json", import.meta.url), "utf8"));

test("computeDelta returns zero arrays for identical datasets", () => {
  const delta = computeDelta(data, data);

  assert.equal(delta.welch_psd.psd[0][0], 0);
  assert.equal(delta.centroid.values[0][0], 0);
  assert.equal(delta.geometry.alpha_relative_power[0][0], 0);
  assert.equal(delta.channel_summary[0].alpha_relative_power, 0);
});

test("session store caps datasets at six with unique colors", () => {
  for (let index = getSessions().length; index < 6; index += 1) {
    addSession(`session_${index}.zip`, data);
  }

  assert.equal(getSessions().length, 6);
  assert.equal(new Set(getSessions().map((session) => session.color)).size, 6);
  assert.throws(() => addSession("session_7.zip", data), /Maximum 6 sessions/);
});

test("session store rejects duplicate dataset names", () => {
  assert.throws(() => addSession("session_0.zip", data), /already loaded/);
});
