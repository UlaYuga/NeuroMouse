export const MONITOR_METRICS = [
  { key: "centroid", label: "Centroid" },
  { key: "spread", label: "Spread" },
  { key: "entropy", label: "Entropy" },
  { key: "flatness", label: "Flatness" },
  { key: "edge95", label: "Edge95" },
  { key: "alpha_relative_power", label: "Alpha Rel. Power" },
];

export const MONITOR_OPERATORS = [">", "<", ">=", "<="];

export function createDefaultCondition(channel = "Pz") {
  return {
    channel,
    metric: "alpha_relative_power",
    operator: ">",
    threshold: 0.5,
    duration_sec: 2,
    enabled: false,
  };
}

export class ConditionMonitor {
  constructor({ autoResetMs = 1000 } = {}) {
    this.state = "IDLE";
    this.buildStart = null;
    this.log = [];
    this.listeners = [];
    this.autoResetMs = autoResetMs;
    this.resetTimer = null;
  }

  update(value, timestampSec, condition) {
    if (!condition?.enabled) return;
    if (!Number.isFinite(Number(value)) || !Number.isFinite(Number(timestampSec))) {
      if (this.state === "BUILDING") this.reset();
      return;
    }

    const currentValue = Number(value);
    const currentTime = Number(timestampSec);
    const satisfied = evaluate(currentValue, condition.operator, condition.threshold);

    if (this.state === "IDLE") {
      if (satisfied) {
        this.state = "BUILDING";
        this.buildStart = currentTime;
      }
      return;
    }

    if (this.state === "BUILDING") {
      if (!satisfied) {
        this.reset();
        return;
      }

      if (currentTime - this.buildStart >= Number(condition.duration_sec)) {
        this.trigger(currentValue, currentTime, condition);
      }
    }
  }

  getProgress(timestampSec, condition) {
    const duration = Number(condition?.duration_sec);
    if (this.state !== "BUILDING" || this.buildStart == null || !Number.isFinite(duration) || duration <= 0) {
      return 0;
    }
    return Math.min(1, Math.max(0, (Number(timestampSec) - this.buildStart) / duration));
  }

  onTrigger(fn) {
    this.listeners.push(fn);
    return () => {
      this.listeners = this.listeners.filter((listener) => listener !== fn);
    };
  }

  clearLog() {
    this.log = [];
  }

  reset() {
    if (this.resetTimer) {
      clearTimeout(this.resetTimer);
      this.resetTimer = null;
    }
    this.state = "IDLE";
    this.buildStart = null;
  }

  trigger(value, timestampSec, condition) {
    this.state = "TRIGGERED";
    const event = {
      timestamp_sec: timestampSec,
      channel: condition.channel,
      metric: condition.metric,
      value: Math.round(Number(value) * 1000) / 1000,
      condition: `${condition.operator} ${condition.threshold} for ${condition.duration_sec}s`,
    };
    this.log.push(event);
    this.listeners.forEach((fn) => fn(event));

    if (this.autoResetMs > 0) {
      this.resetTimer = setTimeout(() => {
        this.reset();
      }, this.autoResetMs);
    }
  }
}

export function evaluate(value, op, threshold) {
  const currentValue = Number(value);
  const target = Number(threshold);
  if (!Number.isFinite(currentValue) || !Number.isFinite(target)) return false;
  if (op === ">") return currentValue > target;
  if (op === "<") return currentValue < target;
  if (op === ">=") return currentValue >= target;
  if (op === "<=") return currentValue <= target;
  return false;
}

export function latestMetricValue(liveData, condition) {
  const channels = liveData?.meta?.channels ?? liveData?.channel_names ?? [];
  const channelIndex = channels.indexOf(condition.channel);
  const metricSeries = liveData?.geometry?.[condition.metric]?.[channelIndex];
  if (!Array.isArray(metricSeries) || !metricSeries.length) return null;
  const value = Number(metricSeries[metricSeries.length - 1]);
  return Number.isFinite(value) ? value : null;
}

export function latestGeometryTime(liveData) {
  const time = liveData?.geometry?.time;
  if (!Array.isArray(time) || !time.length) return Number(liveData?.window_start_time_sec ?? 0);
  const value = Number(time[time.length - 1]);
  return Number.isFinite(value) ? value : 0;
}

export function serializeTriggerLogCSV(log) {
  const header = "timestamp_sec,channel,metric,value,condition\n";
  const rows = log.map((event) => [
    csvCell(event.timestamp_sec),
    csvCell(event.channel),
    csvCell(event.metric),
    csvCell(event.value),
    csvCell(event.condition, { forceQuote: true }),
  ].join(",")).join("\n");
  return header + rows;
}

function csvCell(value, { forceQuote = false } = {}) {
  const text = String(value ?? "");
  return forceQuote || /[",\n]/.test(text) ? `"${text.replaceAll("\"", "\"\"")}"` : text;
}
