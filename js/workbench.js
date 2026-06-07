export const SCENARIOS = [
  {
    id: "trained-vs-naive",
    label: "Trained vs untrained",
    baselineLabel: "Untrained baseline",
    targetLabel: "Trained cohort",
    focus: "learning evidence",
    description: "Compare trained neural cultures against untrained controls using spectral geometry and synchrony markers.",
  },
  {
    id: "healthy-vs-diagnosed",
    label: "Healthy vs diagnosed",
    baselineLabel: "Healthy reference",
    targetLabel: "Diagnosed cohort",
    focus: "phenotype separation",
    description: "Summarize cohort-level differences for clinical or translational EEG review.",
  },
  {
    id: "baseline-vs-treatment",
    label: "Baseline vs treatment",
    baselineLabel: "Pre-intervention",
    targetLabel: "Post-intervention",
    focus: "treatment response",
    description: "Track whether a stimulation, drug, or protocol changed spectral activity after intervention.",
  },
  {
    id: "session-repeatability",
    label: "Repeatability check",
    baselineLabel: "Reference run",
    targetLabel: "Repeat run",
    focus: "stability and drift",
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
    source: data?.meta?.source ?? "SpeedMouse dataset",
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
      return compareSummaries(session, sessionSummary, baseline, baselineSummary);
    })
    : [];

  return {
    scenario,
    baseline,
    baselineSummary,
    datasets,
    comparisons,
    metrics: buildMetricTiles(datasets, fallbackData, baselineSummary, comparisons),
    status: comparisonStatus(datasets, baseline, comparisons, scenario),
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
    "# SpeedMouse Neural Signal Analysis Report",
    "",
    `Generated: ${date}`,
    `Workflow: ${state.scenario.label}`,
    `Purpose: ${state.scenario.focus}`,
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
      lines.push(`| ${escapePipe(row.name)} | ${escapePipe(row.baselineName)} | ${formatSignedPercent(row.alphaChange)} | ${formatSignedNumber(row.centroidShiftHz, 2)} Hz | ${formatSignedNumber(row.entropyShift, 4)} | ${row.separationScore}/100 |`);
    });
  }

  lines.push(
    "",
    "## Toolbox Coverage",
    "",
    "- Offline file import: SpeedMouse data.json, combined CSV export ZIP, or paired Welch + geometry ZIP.",
    "- Live monitoring: WebSocket raw EEG source remains available for real-time checks.",
    "- Comparative analysis: overlay, split, and delta modes use the selected baseline.",
    "- Export: this report preserves the dataset names, comparison goal, and numeric readout.",
  );

  return `${lines.join("\n")}\n`;
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

function buildMetricTiles(datasets, fallbackData, baselineSummary, comparisons) {
  const loadedSummary = baselineSummary ?? (fallbackData ? summarizeDataset(fallbackData) : null);
  const topComparison = comparisons[0] ?? null;
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
      label: "Separation",
      value: topComparison ? `${topComparison.separationScore}` : "--",
      detail: topComparison ? `${topComparison.name} vs baseline` : "needs two datasets",
    },
  ];
}

function compareSummaries(session, summary, baseline, baselineSummary) {
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
  };
}

function comparisonStatus(datasets, baseline, comparisons, scenario) {
  if (!datasets.length) return "Drop saved neural data to start offline analysis.";
  if (!baseline) return "Choose a baseline dataset before comparing cohorts.";
  if (!comparisons.length) {
    return `Loaded ${baseline.name}. Add a ${scenario.targetLabel.toLowerCase()} dataset to calculate deltas.`;
  }
  const top = comparisons.slice().sort((a, b) => b.separationScore - a.separationScore)[0];
  return `${top.name} is ${top.separationScore}/100 separated from ${top.baselineName} for ${scenario.focus}.`;
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
