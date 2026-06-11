import { buildElectrodeLayout } from "./views/channel-grid.js";
import { MONITOR_METRICS } from "./monitor.js";
import {
  buildWorkbenchState,
  formatNumber,
  formatPercent,
} from "./workbench.js";

const FILTERS = ["all", "frontal", "central_temporal", "parietal", "occipital", "L", "R"];
const COLOR_MODES = ["alpha_relative_power", "lyapunov_exponent", "variability.alpha_range"];
const SPEEDS = [1, 2, 4];

export function buildViewerStructure({
  dataset,
  sessions = [],
  baselineId = null,
  scenarioId = "trained-vs-naive",
  channel = "Cz",
  viewMode = "overlay",
  channelSort = "layout",
  psdScale = "log",
} = {}) {
  if (!dataset) throw new Error("buildViewerStructure requires dataset");
  const state = buildWorkbenchState({
    sessions,
    fallbackData: dataset,
    baselineId,
    scenarioId,
  });
  const channels = dataset?.meta?.channels ?? [];
  const frames = dataset?.geometry?.time?.length ?? 0;
  const baselineFacts = state.baselineSummary
    ? [
      `${state.baselineSummary.channels} ch`,
      `${state.baselineSummary.frames} frames`,
      `${formatNumber(state.baselineSummary.centroidMeanHz, 1)} Hz centroid`,
      `${formatPercent(state.baselineSummary.clearAlphaRatio)} alpha clear`,
    ]
    : [];
  const hasImportedSessions = sessions.length > 0;

  return {
    dataset: {
      channels: channels.length,
      frames,
      source: dataset?.meta?.source ?? "NeuroMouse dataset",
    },
    controls: {
      filters: FILTERS,
      channelSort,
      psdScale,
      viewMode,
    },
    workbench: {
      pipeline: buildPipeline(state),
      scenario: {
        id: state.scenario.id,
        label: state.scenario.label,
        baselineLabel: state.scenario.baselineLabel,
        targetLabel: state.scenario.targetLabel,
        detail: state.scenario.description,
      },
      baseline: {
        label: state.scenario.baselineLabel,
        name: state.baseline?.name ?? "Demo dataset",
        facts: baselineFacts,
        select: {
          disabled: !hasImportedSessions,
          options: hasImportedSessions ? sessions.map((session) => session.name) : ["Demo dataset"],
        },
      },
      status: {
        className: `workbench-status ${state.reportReadiness.ready ? "is-ready" : "is-draft"}`,
        text: state.status,
      },
      comparisons: state.comparisons.length
        ? state.comparisons.slice(0, 3).map((row) => ({
          type: "comparison",
          name: row.name,
          primaryLabel: row.primaryLabel,
          scoreLabel: row.scoreLabel,
          score: row.score,
          interpretation: row.interpretation,
        }))
        : [{
          type: "empty",
          text: `${state.scenario.baselineLabel} -> ${state.scenario.targetLabel}`,
        }],
      readiness: {
        className: `readiness-panel ${state.reportReadiness.ready ? "is-ready" : "is-draft"}`,
        text: `${state.reportReadiness.ready ? "Report ready" : "Report draft"} ${state.reportReadiness.message}`,
      },
      qualityFlags: state.qualityFlags.map((flag) => ({
        className: `quality-item is-${flag.level}`,
        label: flag.label,
        message: flag.message,
      })),
      metrics: state.metrics,
    },
    panels: buildPanelStructure(dataset),
    widgets: {
      playback: {
        speeds: SPEEDS,
        maxFrame: Math.max(0, frames - 1),
        initialTimeLabel: `t = ${formatNumber(dataset.geometry.time?.[0] ?? 0, 2)} s`,
      },
      channelGrid: {
        selectedChannel: channels.includes(channel) ? channel : channels[0] ?? "Cz",
        layout: buildElectrodeLayout(channels).mode,
        electrodeCount: buildElectrodeLayout(channels).nodes.length,
        colorModes: COLOR_MODES.filter((mode) => hasColorMode(dataset, mode)),
      },
      monitor: {
        mode: "static",
        defaultChannel: channels.includes(channel) ? channel : channels[0] ?? "Cz",
        metrics: MONITOR_METRICS.map((metric) => metric.key),
      },
      sessions: {
        count: `${sessions.length}/6`,
        message: "Add sessions to compare",
        baselineOptions: hasImportedSessions ? sessions.map((session) => session.name) : ["No imported baselines"],
      },
    },
  };
}

function buildPipeline(state) {
  return [
    "ingest:ready",
    "normalize:ready",
    `compare:${state.comparisons.length > 0 ? "ready" : "waiting"}`,
    `report:${state.reportReadiness.ready ? "ready" : "waiting"}`,
  ];
}

function buildPanelStructure(dataset) {
  return [
    panel("psd", "PSD Heatmap", true, false, ["psd-legend", "psd-heatmap", "psd-overlay"]),
    panel("playback", "Playback", true, false, ["playback-bar"]),
    panel("centroid", "Centroid Over Time", false, false, ["centroid-legend", "centroid-chart"]),
    panel("geometry", "Geometry Stack", true, false, ["geometry-legend", "geometry-chart"]),
    panel("grid", "Channel Grid", true, false, ["selected-channel", "channel-grid"]),
    panel("phase", "Phase Space", false, false, ["phase-space"]),
    panel("polar", "Polar Alpha Chronomap", false, !dataset.polar_chronomap, ["polar-chronomap"]),
    panel("kuramoto", "Kuramoto Animation", false, !dataset.kuramoto, ["kuramoto-view"]),
    panel("network", "Channel Network", false, !dataset.channel_network, ["channel-network"]),
    panel("tda", "TDA View", false, dataset.tda?.status !== "computed", ["tda-view"]),
    panel("monitor", "Closed-Loop Monitor", true, false, ["monitor-panel"]),
  ];
}

function panel(key, title, expanded, hidden, regions) {
  return { key, title, expanded, hidden, regions };
}

function hasColorMode(dataset, mode) {
  if (mode === "alpha_relative_power") return true;
  if (mode === "lyapunov_exponent") {
    return dataset.channel_summary?.some((item) => Number.isFinite(Number(item.lyapunov_exponent)));
  }
  if (mode === "variability.alpha_range") {
    return dataset.channel_summary?.some((item) => Number.isFinite(Number(item.variability?.alpha_range)));
  }
  return false;
}
