import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import {
  buildWorkbenchState,
  generateWorkbenchReport,
  summarizeDataset,
} from "../js/workbench.js";

const data = JSON.parse(await readFile(new URL("../data/data.json", import.meta.url), "utf8"));

function shiftedData() {
  return {
    ...data,
    channel_summary: data.channel_summary.map((channel) => ({
      ...channel,
      alpha_relative_power: channel.alpha_relative_power * 1.2,
      sliding_alpha_relative_mean: channel.sliding_alpha_relative_mean * 1.2,
      spectral_centroid_hz: channel.spectral_centroid_hz + 2,
      spectral_entropy: channel.spectral_entropy + 0.02,
    })),
  };
}

test("summarizeDataset extracts research dashboard metrics", () => {
  const summary = summarizeDataset(data);

  assert.equal(summary.channels, 32);
  assert.equal(summary.frames, 420);
  assert.equal(summary.clearAlphaRatio > 0, true);
  assert.equal(summary.alphaMean > 0, true);
  assert.equal(summary.centroidMeanHz > 0, true);
});

test("buildWorkbenchState compares active sessions against baseline", () => {
  const sessions = [
    { id: "baseline", name: "untrained.zip", data, active: true },
    { id: "target", name: "trained.zip", data: shiftedData(), active: true },
  ];
  const state = buildWorkbenchState({
    sessions,
    baselineId: "baseline",
    scenarioId: "trained-vs-naive",
  });

  assert.equal(state.datasets.length, 2);
  assert.equal(state.comparisons.length, 1);
  assert.equal(state.comparisons[0].name, "trained.zip");
  assert.equal(state.comparisons[0].alphaChange > 0, true);
  assert.equal(state.comparisons[0].centroidShiftHz > 0, true);
  assert.equal(state.comparisons[0].separationScore > 0, true);
});

test("buildWorkbenchState applies scenario-specific scoring and readiness", () => {
  const sessions = [
    { id: "baseline", name: "run-a.json", data, active: true },
    { id: "target", name: "run-b.json", data: shiftedData(), active: true },
  ];
  const state = buildWorkbenchState({
    sessions,
    baselineId: "baseline",
    scenarioId: "session-repeatability",
  });

  assert.equal(state.scenario.id, "session-repeatability");
  assert.equal(state.comparisons[0].scoreLabel, "Stability");
  assert.equal(state.comparisons[0].primaryLabel, "Drift");
  assert.match(state.comparisons[0].interpretation, /drift|stable/i);
  assert.equal(state.reportReadiness.ready, true);
  assert.equal(state.qualityFlags.some((flag) => flag.level === "ready"), true);
});

test("generateWorkbenchReport emits a reusable markdown report", () => {
  const report = generateWorkbenchReport({
    sessions: [
      { id: "baseline", name: "healthy.zip", data, active: true },
      { id: "target", name: "diagnosed.zip", data: shiftedData(), active: true },
    ],
    baselineId: "baseline",
    scenarioId: "healthy-vs-diagnosed",
    generatedAt: new Date("2026-06-07T17:30:00.000Z"),
  });

  assert.match(report, /# SpeedMouse Neural Signal Analysis Report/);
  assert.match(report, /Workflow: Healthy vs diagnosed/);
  assert.match(report, /diagnosed\.zip/);
  assert.match(report, /Toolbox Coverage/);
  assert.match(report, /## Executive Readout/);
  assert.match(report, /## Data Quality/);
  assert.match(report, /## Reproducibility/);
  assert.match(report, /Scenario interpretation/);
});
