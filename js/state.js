const listeners = new Set();
const displayListeners = new Set();
const psdScaleListeners = new Set();
const timeHoverListeners = new Set();
const liveListeners = new Set();
const frameListeners = new Set();
let selectedChannel = "Cz";
let availableChannels = [];
let channelFilter = "all";
let channelSort = "layout";
let psdScale = "log";
let timeHover = null;
let currentFrame = 0;
let totalFrames = 420;
let isPlaying = false;
let playbackSpeed = 1;
let liveState = {
  connected: false,
  status: "Static replay",
  url: "",
  frameCount: 0,
  latestFrame: null,
  history: [],
};

const MAX_LIVE_HISTORY = 420;

export function configureChannels(channels) {
  availableChannels = channels.slice();
  if (!availableChannels.includes(selectedChannel)) {
    selectedChannel = availableChannels[0] || "Cz";
  }
}

export function configurePlayback(total) {
  totalFrames = Math.max(1, Math.round(Number(total) || 420));
  currentFrame = Math.min(currentFrame, totalFrames - 1);
  frameListeners.forEach((fn) => fn(currentFrame));
}

export function getChannel() {
  return selectedChannel;
}

export function getChannelIndex() {
  return Math.max(0, availableChannels.indexOf(selectedChannel));
}

export function setChannel(name) {
  if (!availableChannels.includes(name) || name === selectedChannel) return;
  selectedChannel = name;
  listeners.forEach((fn) => fn(name));
}

export function onChannelChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getChannelFilter() {
  return channelFilter;
}

export function setChannelFilter(filter) {
  if (filter === channelFilter) return;
  channelFilter = filter;
  displayListeners.forEach((fn) => fn());
}

export function getChannelSort() {
  return channelSort;
}

export function setChannelSort(sort) {
  if (sort === channelSort) return;
  channelSort = sort;
  displayListeners.forEach((fn) => fn());
}

export function getPsdScale() {
  return psdScale;
}

export function setPsdScale(scale) {
  if (scale === psdScale) return;
  psdScale = scale;
  psdScaleListeners.forEach((fn) => fn(scale));
}

export function getTimeHover() {
  return timeHover;
}

export function setTimeHover(nextHover) {
  const next = nextHover ? { ...nextHover } : null;
  if (timeHover?.source === next?.source && timeHover?.timeIndex === next?.timeIndex) return;
  timeHover = next;
  timeHoverListeners.forEach((fn) => fn(timeHover));
}

export function onDisplayChange(fn) {
  displayListeners.add(fn);
  return () => displayListeners.delete(fn);
}

export function onPsdScaleChange(fn) {
  psdScaleListeners.add(fn);
  return () => psdScaleListeners.delete(fn);
}

export function onTimeHoverChange(fn) {
  timeHoverListeners.add(fn);
  return () => timeHoverListeners.delete(fn);
}

export function getFrame() {
  return currentFrame;
}

export function getTotalFrames() {
  return totalFrames;
}

export function getIsPlaying() {
  return isPlaying;
}

export function getPlaybackSpeed() {
  return playbackSpeed;
}

export function setFrame(frame) {
  const nextFrame = Math.max(0, Math.min(totalFrames - 1, Math.round(Number(frame) || 0)));
  if (nextFrame === currentFrame) return;
  currentFrame = nextFrame;
  frameListeners.forEach((fn) => fn(currentFrame));
}

export function setPlaying(nextPlaying) {
  const playing = Boolean(nextPlaying);
  if (playing === isPlaying) return;
  isPlaying = playing;
  frameListeners.forEach((fn) => fn(currentFrame));
}

export function setPlaybackSpeed(speed) {
  const nextSpeed = [1, 2, 4].includes(Number(speed)) ? Number(speed) : 1;
  if (nextSpeed === playbackSpeed) return;
  playbackSpeed = nextSpeed;
  frameListeners.forEach((fn) => fn(currentFrame));
}

export function onFrameChange(fn) {
  frameListeners.add(fn);
  return () => frameListeners.delete(fn);
}

export function getVisibleChannels(data) {
  const summaryByChannel = new Map(data.channel_summary.map((item) => [item.channel, item]));
  let channels = availableChannels.filter((channel) => {
    const item = summaryByChannel.get(channel);
    if (!item || channelFilter === "all") return true;
    if (["L", "R", "M"].includes(channelFilter)) return item.hemisphere === channelFilter;
    if (channelFilter === "frontal") return item.region.startsWith("frontal");
    return item.region === channelFilter;
  });

  if (channelSort === "alpha") {
    channels = channels.slice().sort((a, b) => (
      (summaryByChannel.get(b)?.alpha_relative_power ?? 0) -
      (summaryByChannel.get(a)?.alpha_relative_power ?? 0)
    ));
  } else if (channelSort === "centroid") {
    channels = channels.slice().sort((a, b) => (
      (summaryByChannel.get(b)?.spectral_centroid_hz ?? 0) -
      (summaryByChannel.get(a)?.spectral_centroid_hz ?? 0)
    ));
  }

  return channels;
}

export function getLiveState() {
  return {
    ...liveState,
    history: liveState.history.slice(),
  };
}

export function updateLiveStatus(patch) {
  liveState = {
    ...liveState,
    ...patch,
  };
  liveListeners.forEach((fn) => fn(getLiveState()));
}

export function pushLiveFrame(frame) {
  const nextHistory = liveState.history.concat(normalizeLiveFrame(frame)).slice(-MAX_LIVE_HISTORY);
  liveState = {
    ...liveState,
    connected: true,
    status: "Live stream",
    frameCount: liveState.frameCount + 1,
    latestFrame: frame,
    history: nextHistory,
  };
  liveListeners.forEach((fn) => fn(getLiveState()));
}

export function clearLiveHistory() {
  liveState = {
    ...liveState,
    frameCount: 0,
    latestFrame: null,
    history: [],
  };
  liveListeners.forEach((fn) => fn(getLiveState()));
}

export function onLiveChange(fn) {
  liveListeners.add(fn);
  return () => liveListeners.delete(fn);
}

export function liveMetric(frame, channel, key) {
  const metrics = frame?.metrics_by_channel?.[channel];
  const value = metrics?.[key];
  return Number.isFinite(Number(value)) ? Number(value) : null;
}

function normalizeLiveFrame(frame) {
  const channels = Array.isArray(frame.channel_names) && frame.channel_names.length
    ? frame.channel_names
    : availableChannels;
  const metrics = {};
  for (const channel of channels) {
    metrics[channel] = {
      centroid: liveMetric(frame, channel, "spectral_centroid_hz"),
      spread: liveMetric(frame, channel, "spectral_spread_hz"),
      entropy: liveMetric(frame, channel, "spectral_entropy_normalized"),
      flatness: liveMetric(frame, channel, "spectral_flatness"),
      edge95: liveMetric(frame, channel, "spectral_edge_95_hz"),
      alpha_relative_power: liveMetric(frame, channel, "alpha_relative_power"),
    };
  }

  return {
    time: Number(frame.window_start_time_sec ?? liveState.frameCount),
    sequence: frame.analysis_sequence_number ?? liveState.frameCount + 1,
    computeMs: Number(frame.compute_ms ?? NaN),
    updateIntervalSec: Number(frame.update_interval_sec ?? NaN),
    channels,
    metrics,
    frequency_hz: Array.isArray(frame.frequency_hz) ? frame.frequency_hz.map(Number) : null,
    psd_by_channel: frame.psd_by_channel || null,
  };
}
