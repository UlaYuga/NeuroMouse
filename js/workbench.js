export const SCENARIOS = [
  {
    id: "trained-vs-naive",
    label: "Trained vs untrained",
    baselineLabel: "Untrained baseline",
    targetLabel: "Trained cohort",
    focus: "learning evidence",
    scoreLabel: "Separation",
    primaryLabel: "Alpha gain",
    primaryMetric: "alphaChange",
    goodThreshold: 28,
    description: "Compare trained neural cultures against untrained controls using spectral geometry and synchrony markers.",
  },
  {
    id: "healthy-vs-diagnosed",
    label: "Healthy vs diagnosed",
    baselineLabel: "Healthy reference",
    targetLabel: "Diagnosed cohort",
    focus: "phenotype separation",
    scoreLabel: "Phenotype distance",
    primaryLabel: "Entropy shift",
    primaryMetric: "entropyShift",
    goodThreshold: 24,
    description: "Summarize cohort-level differences for clinical or translational EEG review.",
  },
  {
    id: "baseline-vs-treatment",
    label: "Baseline vs treatment",
    baselineLabel: "Pre-intervention",
    targetLabel: "Post-intervention",
    focus: "treatment response",
    scoreLabel: "Response",
    primaryLabel: "Alpha response",
    primaryMetric: "alphaChange",
    goodThreshold: 18,
    description: "Track whether a stimulation, drug, or protocol changed spectral activity after intervention.",
  },
  {
    id: "session-repeatability",
    label: "Repeatability check",
    baselineLabel: "Reference run",
    targetLabel: "Repeat run",
    focus: "stability and drift",
    scoreLabel: "Stability",
    primaryLabel: "Drift",
    primaryMetric: "driftScore",
    goodThreshold: 74,
    scoreMode: "stability",
    description: "Check whether repeated recordings preserve expected spectral geometry and signal shape.",
  },
];

const DEFAULT_SCENARIO_ID = SCENARIOS[0].id;

export function getScenario(id) {
  return SCENARIOS.find((scenario) => scenario.id === id) ?? SCENARIOS[0];
}

export function summarizeDataset(data) {
  const channels = data?.meta?.channels ?? [];
  const summary = Array.isArray(data?.channel_summary) ? data.channel_summary : [];
  const geometryTime = Array.isArray(data?.geometry?.time) ? data.geometry.time : [];
  const centroidTime = Array.isArray(data?.centroid?.time_relative) ? data.centroid.time_relative : [];
  const timeAxis = geometryTime.length ? geometryTime : centroidTime;
  const duration = durationSeconds(data, timeAxis);

  return {
    channels: Number(data?.meta?.n_channels ?? channels.length ?? summary.length ?? 0),
    frames: timeAxis.length,
    durationSec: duration,
    samplingRateHz: finiteNumber(data?.meta?.sampling_rate_analysis_hz),
    alphaMean: mean(summary.map((item) => firstFinite(
      item.sliding_alpha_relative_mean,
      item.alpha_relative_power,
    ))),
    centroidMeanHz: mean(summary.map((item) => item.spectral_centroid_hz)),
    entropyMean: mean(summary.map((item) => item.spectral_entropy)),
    flatnessMean: mean(summary.map((item) => item.spectral_flatness)),
    clearAlphaRatio: ratio(
      summary.filter((item) => item.has_clear_alpha_peak).length,
      summary.length,
    ),
    source: data?.meta?.source ?? "NeuroMouse dataset",
  };
}

export function buildWorkbenchState({
  sessions = [],
  fallbackData = null,
  baselineId = null,
  scenarioId = DEFAULT_SCENARIO_ID,
} = {}) {
  const scenario = getScenario(scenarioId);
  const activeSessions = sessions.filter((session) => session.active !== false);
  const datasets = activeSessions.length
    ? activeSessions
    : fallbackData
      ? [{
        id: "default",
        name: "Demo dataset",
        data: fallbackData,
        active: true,
        isDefault: true,
      }]
      : [];
  const baseline = datasets.find((session) => session.id === baselineId) ?? datasets[0] ?? null;
  const baselineSummary = baseline ? summarizeDataset(baseline.data) : null;
  const comparisons = baseline && datasets.length > 1
    ? datasets.filter((session) => session.id !== baseline.id).map((session) => {
      const sessionSummary = summarizeDataset(session.data);
      return compareSummaries(session, sessionSummary, baseline, baselineSummary, scenario);
    })
    : [];
  const topComparison = rankComparisons(comparisons, scenario)[0] ?? null;
  const qualityFlags = buildQualityFlags(datasets, baselineSummary, comparisons);
  const reportReadiness = buildReportReadiness(datasets, comparisons, qualityFlags);

  return {
    scenario,
    baseline,
    baselineSummary,
    datasets,
    comparisons,
    topComparison,
    qualityFlags,
    reportReadiness,
    metrics: buildMetricTiles(datasets, fallbackData, baselineSummary, comparisons, reportReadiness, scenario),
    status: comparisonStatus(datasets, baseline, comparisons, scenario, topComparison),
  };
}

export function generateWorkbenchReport({
  sessions = [],
  fallbackData = null,
  baselineId = null,
  scenarioId = DEFAULT_SCENARIO_ID,
  generatedAt = new Date(),
} = {}) {
  const state = buildWorkbenchState({ sessions, fallbackData, baselineId, scenarioId });
  const date = generatedAt instanceof Date ? generatedAt.toISOString() : String(generatedAt);
  const lines = [
    "# NeuroMouse Neural Signal Analysis Report",
    "",
    `Generated: ${date}`,
    `Workflow: ${state.scenario.label}`,
    `Purpose: ${state.scenario.focus}`,
    "",
    "## Executive Readout",
    "",
    `- Baseline: ${state.baseline ? escapePipe(state.baseline.name) : "not selected"}`,
    `- Dataset count: ${state.datasets.length}`,
    `- Report readiness: ${state.reportReadiness.ready ? "ready" : state.reportReadiness.message}`,
    `- Scenario interpretation: ${state.topComparison ? state.topComparison.interpretation : state.status}`,
    "",
    "## Dataset Summary",
    "",
    "| Dataset | Channels | Frames | Duration | Mean alpha | Mean centroid | Clear alpha |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
  ];

  state.datasets.forEach((session) => {
    const summary = summarizeDataset(session.data);
    lines.push(`| ${escapePipe(session.name)} | ${summary.channels} | ${summary.frames} | ${formatDuration(summary.durationSec)} | ${formatNumber(summary.alphaMean, 4)} | ${formatNumber(summary.centroidMeanHz, 2)} Hz | ${formatPercent(summary.clearAlphaRatio)} |`);
  });

  lines.push("", "## Comparison Readout", "");
  if (!state.comparisons.length) {
    lines.push(state.status);
  } else {
    lines.push("| Target | Baseline | Alpha change | Centroid shift | Entropy shift | Separation |");
    lines.push("| --- | --- | ---: | ---: | ---: | ---: |");
    state.comparisons.forEach((row) => {
      lines.push(`| ${escapePipe(row.name)} | ${escapePipe(row.baselineName)} | ${formatSignedPercent(row.alphaChange)} | ${formatSignedNumber(row.centroidShiftHz, 2)} Hz | ${formatSignedNumber(row.entropyShift, 4)} | ${row.scoreLabel}: ${row.score}/100 |`);
    });
    lines.push(
      "",
      `> The ${state.scenario.scoreLabel.toLowerCase()} score (0-100) is a heuristic indicator that weights the absolute alpha, centroid, entropy, and flatness deltas above. It is a triage aid for ranking datasets, not a statistical test: it carries no significance value, confidence interval, or sample size. Treat the underlying deltas and the detailed plots as the evidence before drawing conclusions.`,
    );
  }

  lines.push("", "## Data Quality", "");
  state.qualityFlags.forEach((flag) => {
    lines.push(`- ${flag.label}: ${flag.message}`);
  });

  lines.push(
    "",
    "## Toolbox Coverage",
    "",
    "- Offline file import: NeuroMouse data.json, combined CSV export ZIP, or paired Welch + geometry ZIP.",
    "- Live monitoring: WebSocket raw EEG source remains available for real-time checks.",
    "- Comparative analysis: overlay, split, and delta modes use the selected baseline.",
    "- Export: this report preserves the dataset names, comparison goal, and numeric readout.",
    "",
    "## Reproducibility",
    "",
    "- Source files: NeuroMouse data.json, combined CSV ZIP, or paired Welch + geometry ZIP.",
    "- Baseline rule: active baseline selected in the comparison suite at export time.",
    "- Browser runtime: static HTML, CSS, and vanilla ES modules; no server-side computation is required for saved datasets.",
    "- Numeric readout: alpha change is relative to baseline; centroid, entropy, and flatness shifts are absolute deltas.",
  );

  return `${lines.join("\n")}\n`;
}

export function generateWorkbenchReportPreview(options = {}) {
  const state = buildWorkbenchState(options);
  return {
    title: "NeuroMouse Neural Signal Analysis Report",
    ready: state.reportReadiness.ready,
    status: state.status,
    scenario: state.scenario,
    baseline: state.baseline && state.baselineSummary
      ? {
        id: state.baseline.id,
        name: state.baseline.name,
        ...state.baselineSummary,
      }
      : null,
    datasets: state.datasets,
    comparisons: state.comparisons,
    qualityFlags: state.qualityFlags,
    markdown: generateWorkbenchReport(options),
  };
}

export function createDemoDatasetPair(data) {
  if (!data) return [];
  return [
    {
      id: "demo-baseline",
      name: "Demo baseline",
      data: cloneDataset(data),
      active: true,
    },
    {
      id: "demo-target",
      name: "Demo trained response",
      data: shiftDemoDataset(data),
      active: true,
    },
  ];
}

export function buildImportReceipt({ accepted = [], skipped = [], rejected = [] } = {}) {
  const rows = [
    ...accepted.map((message) => ({ status: "accepted", message })),
    ...skipped.map((message) => ({ status: "skipped", message })),
    ...rejected.map((message) => ({ status: "rejected", message })),
  ];
  const acceptedCount = accepted.length;
  const skippedCount = skipped.length;
  const rejectedCount = rejected.length;
  const parts = [];
  if (acceptedCount) parts.push(`${acceptedCount} accepted`);
  if (skippedCount) parts.push(`${skippedCount} skipped`);
  if (rejectedCount) parts.push(`${rejectedCount} rejected`);

  return {
    acceptedCount,
    skippedCount,
    rejectedCount,
    hasProblems: skippedCount > 0 || rejectedCount > 0,
    headline: parts.length ? parts.join(" · ") : "No files processed",
    rows,
  };
}

export function formatNumber(value, digits = 2) {
  const number = finiteNumber(value);
  return number == null ? "--" : numberFormatter(digits).format(number);
}

export function formatSignedNumber(value, digits = 2) {
  const number = finiteNumber(value);
  if (number == null) return "--";
  const sign = number > 0 ? "+" : "";
  return `${sign}${numberFormatter(digits).format(number)}`;
}

export function formatPercent(value) {
  const number = finiteNumber(value);
  return number == null ? "--" : `${Math.round(number * 100)}%`;
}

export function formatSignedPercent(value) {
  const number = finiteNumber(value);
  if (number == null) return "--";
  const sign = number > 0 ? "+" : "";
  return `${sign}${Math.round(number * 100)}%`;
}

export function formatDuration(seconds) {
  const value = finiteNumber(seconds);
  if (value == null) return "--";
  if (value < 60) return `${formatNumber(value, 1)}s`;
  const minutes = Math.floor(value / 60);
  const remainder = Math.round(value % 60);
  return `${minutes}m ${remainder}s`;
}

function buildMetricTiles(datasets, fallbackData, baselineSummary, comparisons, reportReadiness, scenario) {
  const loadedSummary = baselineSummary ?? (fallbackData ? summarizeDataset(fallbackData) : null);
  const topComparison = rankComparisons(comparisons, scenario)[0] ?? null;
  return [
    {
      label: "Datasets",
      value: String(datasets.length),
      detail: datasets.length > 1 ? "comparison ready" : "load another file",
    },
    {
      label: "Channels",
      value: loadedSummary ? String(loadedSummary.channels) : "--",
      detail: loadedSummary ? `${loadedSummary.frames} analysis frames` : "waiting for data",
    },
    {
      label: "Alpha clarity",
      value: loadedSummary ? formatPercent(loadedSummary.clearAlphaRatio) : "--",
      detail: loadedSummary ? `mean ${formatNumber(loadedSummary.alphaMean, 4)}` : "no summary",
    },
    {
      label: topComparison?.scoreLabel ?? scenario.scoreLabel,
      value: topComparison ? `${topComparison.score}` : "--",
      detail: topComparison ? `${topComparison.name} vs baseline · heuristic 0-100` : "needs two datasets",
    },
    {
      label: "Report",
      value: reportReadiness.ready ? "Ready" : "Draft",
      detail: reportReadiness.message,
    },
  ];
}

function compareSummaries(session, summary, baseline, baselineSummary, scenario) {
  const alphaChange = relativeChange(summary.alphaMean, baselineSummary.alphaMean);
  const centroidShiftHz = nullableDiff(summary.centroidMeanHz, baselineSummary.centroidMeanHz);
  const entropyShift = nullableDiff(summary.entropyMean, baselineSummary.entropyMean);
  const flatnessShift = nullableDiff(summary.flatnessMean, baselineSummary.flatnessMean);
  const separationScore = Math.min(100, Math.round(
    Math.abs(alphaChange ?? 0) * 120 +
    Math.abs(centroidShiftHz ?? 0) * 1.8 +
    Math.abs(entropyShift ?? 0) * 140 +
    Math.abs(flatnessShift ?? 0) * 90,
  ));
  const driftScore = Math.max(0, 100 - separationScore);
  const score = scenario.scoreMode === "stability" ? driftScore : separationScore;
  const primaryValue = scenario.primaryMetric === "driftScore"
    ? 100 - driftScore
    : {
      alphaChange,
      centroidShiftHz,
      entropyShift,
      flatnessShift,
    }[scenario.primaryMetric];

  return {
    id: session.id,
    name: session.name,
    baselineName: baseline.name,
    summary,
    alphaChange,
    centroidShiftHz,
    entropyShift,
    flatnessShift,
    separationScore,
    driftScore,
    score,
    scoreLabel: scenario.scoreLabel,
    primaryLabel: scenario.primaryLabel,
    primaryMetric: scenario.primaryMetric,
    primaryValue,
    interpretation: interpretationText(scenario, session.name, baseline.name, score, primaryValue),
  };
}

function comparisonStatus(datasets, baseline, comparisons, scenario, topComparison) {
  if (!datasets.length) return "Drop saved neural data to start offline analysis.";
  if (!baseline) return "Choose a baseline dataset before comparing cohorts.";
  if (!comparisons.length) {
    return `Loaded ${baseline.name}. Add a ${scenario.targetLabel.toLowerCase()} dataset to calculate deltas.`;
  }
  const top = topComparison ?? rankComparisons(comparisons, scenario)[0];
  return `${top.name}: ${top.scoreLabel.toLowerCase()} ${top.score}/100 for ${scenario.focus}. ${top.interpretation}`;
}

function buildQualityFlags(datasets, baselineSummary, comparisons) {
  return [
    {
      level: datasets.length > 1 ? "ready" : "waiting",
      label: "Cohort depth",
      message: datasets.length > 1 ? `${datasets.length} active datasets` : "Add a second dataset for cohort deltas",
    },
    {
      level: baselineSummary?.channels >= 16 ? "ready" : "warn",
      label: "Channel coverage",
      message: baselineSummary ? `${baselineSummary.channels} channels, ${baselineSummary.frames} frames` : "No baseline summary available",
    },
    {
      level: baselineSummary?.clearAlphaRatio >= 0.5 ? "ready" : "warn",
      label: "Alpha markers",
      message: baselineSummary ? `${formatPercent(baselineSummary.clearAlphaRatio)} channels with clear alpha peak` : "Alpha markers not available",
    },
    {
      level: comparisons.length ? "ready" : "waiting",
      label: "Comparison",
      message: comparisons.length ? `${comparisons.length} target readout${comparisons.length === 1 ? "" : "s"}` : "Waiting for target dataset",
    },
  ];
}

function buildReportReadiness(datasets, comparisons, qualityFlags) {
  if (!datasets.length) {
    return { ready: false, message: "waiting for saved data" };
  }
  if (!comparisons.length) {
    return { ready: false, message: "needs target dataset" };
  }
  const warnCount = qualityFlags.filter((flag) => flag.level === "warn").length;
  return {
    ready: true,
    message: warnCount ? `${warnCount} quality warning${warnCount === 1 ? "" : "s"}` : "ready for export",
  };
}

function rankComparisons(comparisons, scenario) {
  return comparisons.slice().sort((a, b) => {
    if (scenario.scoreMode === "stability") return b.score - a.score;
    return b.separationScore - a.separationScore;
  });
}

function interpretationText(scenario, name, baselineName, score, primaryValue) {
  if (scenario.scoreMode === "stability") {
    if (score >= scenario.goodThreshold) {
      return `${name} is stable against ${baselineName}; drift stays in the expected repeatability band.`;
    }
    return `${name} shows drift against ${baselineName}; review channel alignment and acquisition conditions before pooling.`;
  }

  const primary = Math.abs(finiteNumber(primaryValue) ?? 0);
  if (score >= scenario.goodThreshold && primary > 0) {
    return `${name} carries measurable ${scenario.focus}; promote it to the detailed overlay and delta views.`;
  }
  return `${name} is close to ${baselineName}; use the detailed plots before treating this as a separated cohort.`;
}

function shiftDemoDataset(data) {
  const shifted = cloneDataset(data);
  shifted.meta = {
    ...shifted.meta,
    source: `${shifted.meta?.source ?? "NeuroMouse dataset"} · demo comparison target`,
    source_files: {
      ...(shifted.meta?.source_files ?? {}),
      demo_pair: "synthetic browser demo target",
    },
  };

  shifted.channel_summary = shifted.channel_summary.map((channel, index) => ({
    ...channel,
    alpha_relative_power: scaleByIndex(channel.alpha_relative_power, 1.14, index),
    sliding_alpha_relative_mean: scaleByIndex(channel.sliding_alpha_relative_mean, 1.16, index),
    spectral_centroid_hz: addByIndex(channel.spectral_centroid_hz, 1.15, index),
    spectral_entropy: addByIndex(channel.spectral_entropy, 0.018, index, 0.2, 1),
    spectral_flatness: addByIndex(channel.spectral_flatness, 0.012, index, 0, 1),
  }));

  if (shifted.geometry?.alpha_relative_power) {
    shifted.geometry.alpha_relative_power = shifted.geometry.alpha_relative_power.map((row, channelIndex) => (
      row.map((value, timeIndex) => scaleByIndex(value, 1.1 + (timeIndex % 5) * 0.004, channelIndex))
    ));
  }
  if (shifted.geometry?.centroid) {
    shifted.geometry.centroid = shifted.geometry.centroid.map((row, channelIndex) => (
      row.map((value, timeIndex) => addByIndex(value, 0.75 + (timeIndex % 4) * 0.05, channelIndex))
    ));
  }
  if (shifted.geometry?.entropy) {
    shifted.geometry.entropy = shifted.geometry.entropy.map((row, channelIndex) => (
      row.map((value) => addByIndex(value, 0.012, channelIndex, 0, 1))
    ));
  }
  if (shifted.centroid?.values) {
    shifted.centroid.values = shifted.centroid.values.map((row, channelIndex) => (
      row.map((value, timeIndex) => addByIndex(value, 0.75 + (timeIndex % 4) * 0.05, channelIndex))
    ));
  }

  return shifted;
}

function cloneDataset(data) {
  return JSON.parse(JSON.stringify(data));
}

function scaleByIndex(value, multiplier, index) {
  const number = finiteNumber(value);
  if (number == null) return value;
  return round(number * (multiplier + (index % 4) * 0.012), 6);
}

function addByIndex(value, amount, index, min = -Infinity, max = Infinity) {
  const number = finiteNumber(value);
  if (number == null) return value;
  const next = number + amount + (index % 5) * amount * 0.08;
  return round(Math.min(max, Math.max(min, next)), 6);
}

function durationSeconds(data, timeAxis) {
  const metaDuration = finiteNumber(data?.meta?.segment_duration_sec);
  if (metaDuration != null && metaDuration > 0) return metaDuration;
  if (!timeAxis.length) return null;
  const first = finiteNumber(timeAxis[0]);
  const last = finiteNumber(timeAxis[timeAxis.length - 1]);
  if (first == null || last == null) return null;
  return Math.max(0, last - first);
}

function mean(values) {
  const numbers = values.map(finiteNumber).filter((value) => value != null);
  if (!numbers.length) return null;
  return numbers.reduce((sum, value) => sum + value, 0) / numbers.length;
}

function ratio(count, total) {
  const denominator = finiteNumber(total);
  if (!denominator) return null;
  return count / denominator;
}

function nullableDiff(value, baseline) {
  const next = finiteNumber(value);
  const base = finiteNumber(baseline);
  if (next == null || base == null) return null;
  return next - base;
}

function relativeChange(value, baseline) {
  const next = finiteNumber(value);
  const base = finiteNumber(baseline);
  if (next == null || base == null || Math.abs(base) < 1e-9) return null;
  return (next - base) / Math.abs(base);
}

function firstFinite(...values) {
  return values.find((value) => finiteNumber(value) != null) ?? null;
}

function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function escapePipe(value) {
  return String(value ?? "").replace(/\|/g, "\\|");
}

function numberFormatter(digits) {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function round(value, digits) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}
