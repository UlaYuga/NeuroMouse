import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import {
  buildWorkbenchState,
  buildImportReceipt,
  createDemoDatasetPair,
  generateWorkbenchReport,
  generateWorkbenchReportPreview,
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

test("buildImportReceipt summarizes accepted, skipped, and rejected files", () => {
  const receipt = buildImportReceipt({
    accepted: ["baseline.json", "target.zip"],
    skipped: ["baseline.json: already loaded"],
    rejected: ["notes.txt: unsupported format"],
  });

  assert.equal(receipt.acceptedCount, 2);
  assert.equal(receipt.skippedCount, 1);
  assert.equal(receipt.rejectedCount, 1);
  assert.equal(receipt.hasProblems, true);
  assert.match(receipt.headline, /2 accepted/);
  assert.equal(receipt.rows[0].status, "accepted");
});

test("createDemoDatasetPair returns comparison-ready baseline and target data", () => {
  const sessions = createDemoDatasetPair(data);
  const state = buildWorkbenchState({
    sessions,
    baselineId: "demo-baseline",
    scenarioId: "trained-vs-naive",
  });

  assert.equal(sessions.length, 2);
  assert.equal(sessions[0].name, "Demo baseline");
  assert.equal(sessions[1].name, "Demo trained response");
  assert.equal(state.comparisons.length, 1);
  assert.equal(state.reportReadiness.ready, true);
  assert.equal(state.comparisons[0].score > 0, true);
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

  assert.match(report, /# NeuroMouse Neural Signal Analysis Report/);
  assert.match(report, /Workflow: Healthy vs diagnosed/);
  assert.match(report, /diagnosed\.zip/);
  assert.match(report, /Toolbox Coverage/);
  assert.match(report, /## Executive Readout/);
  assert.match(report, /## Data Quality/);
  assert.match(report, /## Reproducibility/);
  assert.match(report, /Scenario interpretation/);
});

test("generateWorkbenchReportPreview exposes executive and quality sections", () => {
  const preview = generateWorkbenchReportPreview({
    sessions: createDemoDatasetPair(data),
    baselineId: "demo-baseline",
    scenarioId: "baseline-vs-treatment",
    generatedAt: new Date("2026-06-08T18:00:00.000Z"),
  });

  assert.equal(preview.ready, true);
  assert.match(preview.title, /NeuroMouse/);
  assert.equal(preview.baseline.name, "Demo baseline");
  assert.equal(preview.baseline.channels, 32);
  assert.equal(preview.baseline.frames, 420);
  assert.equal(preview.datasets.length, 2);
  assert.equal(preview.comparisons.length, 1);
  assert.equal(preview.qualityFlags.length >= 4, true);
  assert.match(preview.markdown, /## Executive Readout/);
});
