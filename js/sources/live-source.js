const DEFAULT_CHANNELS = [
  "Fp1", "Fpz", "Fp2", "F7", "F3", "Fz", "F4", "F8",
  "FC5", "FC1", "FC2", "FC6", "M1", "T7", "C3", "Cz",
  "C4", "T8", "M2", "CP5", "CP1", "CP2", "CP6", "P7",
  "P3", "Pz", "P4", "P8", "POz", "O1", "Oz", "O2",
];

const DEFAULT_SAMPLE_RATE = 256;
const WINDOW_SEC = 4;
const OVERLAP = 0.5;
const UPDATE_MS = 250;
const HISTORY_STEPS = 420;

/*
 * Live backend wire-contract note, 2026-06-06:
 * The requested authoritative backend folder `source-data/live-backend/` is not
 * present in this workspace, so the soulsyrup1 raw-frame contract could not be
 * verified from source. This adapter therefore uses the inferred endpoint
 * `ws://127.0.0.1:8766` / `ws://localhost:8766`, defaults to 32 10-20 channels
 * at 256 Hz, and prefers any handshake metadata fields the backend sends:
 * `channel_names`/`channels`, `n_channels`, and `sampling_rate(_hz)`/`sample_rate_hz`.
 *
 * Accepted raw payloads are intentionally tolerant until the real backend files
 * are available:
 * - Float32 binary frames, interleaved by channel.
 * - JSON one-sample arrays: `[ch0, ch1, ...]`.
 * - JSON sample-major chunks: `samples`/`data`/`values` as
 *   `[[ch0, ch1, ...], ...]`.
 * - JSON channel-major chunks: `samples_by_channel` as `{ Cz: [..], ... }` or
 *   a 2D array with one row per channel.
 */
export function createLiveSource(wsUrl, options = {}) {
  const referenceData = options.referenceData ?? null;
  const summaryByChannel = new Map((referenceData?.channel_summary ?? []).map((item) => [item.channel, item]));
  let channels = normalizeChannels(options.channels ?? referenceData?.meta?.channels) ?? DEFAULT_CHANNELS.slice();
  let nChannels = channels.length;
  let samplingRate = positiveNumber(options.samplingRate ?? options.sampleRate) ?? DEFAULT_SAMPLE_RATE;
  let ws = null;
  let worker = null;
  let intervalId = 0;
  let ringBuffer = createRingBuffer();
  let history = createHistory(channels);
  let manuallyStopped = false;
  let sampleCount = 0;
  let sequence = 0;
  let computePending = false;
  let startedAt = 0;

  function createRingBuffer() {
    return new RingBuffer(nChannels, nextPow2(Math.round(WINDOW_SEC * samplingRate)));
  }

  function applyMetadata(metadata) {
    let changed = false;
    if (metadata.channels?.length && metadata.channels.join("\u0000") !== channels.join("\u0000")) {
      channels = metadata.channels.slice();
      nChannels = channels.length;
      history = createHistory(channels);
      changed = true;
    } else if (metadata.nChannels && metadata.nChannels !== nChannels) {
      nChannels = metadata.nChannels;
      channels = channels.length === nChannels
        ? channels
        : Array.from({ length: nChannels }, (_, index) => `Ch${index + 1}`);
      history = createHistory(channels);
      changed = true;
    }
    if (metadata.samplingRate && metadata.samplingRate !== samplingRate) {
      samplingRate = metadata.samplingRate;
      changed = true;
    }
    if (changed) ringBuffer = createRingBuffer();
  }

  function emitStatus(onStatus, status, detail = {}) {
    onStatus?.(status, {
      url: wsUrl,
      channels,
      n_channels: nChannels,
      sampling_rate: samplingRate,
      ...detail,
    });
  }

  return {
    meta() {
      return {
        channels: channels.slice(),
        n_channels: nChannels,
        sampling_rate: samplingRate,
      };
    },

    start(onFrame, onStatus) {
      this.stop();
      manuallyStopped = false;
      sampleCount = 0;
      sequence = 0;
      computePending = false;
      ringBuffer = createRingBuffer();
      history = createHistory(channels);
      startedAt = performance.now();
      emitStatus(onStatus, "connecting");

      worker = new Worker(new URL("../workers/dsp-worker.js", import.meta.url));
      worker.addEventListener("message", ({ data }) => {
        computePending = false;
        if (data?.type === "error") {
          emitStatus(onStatus, "error", { message: data.message });
          return;
        }
        if (data?.type !== "result") return;
        sequence += 1;
        const liveData = buildLiveData(data, sequence, performance.now() - startedAt);
        onFrame?.(liveData);
      });
      worker.addEventListener("error", (event) => {
        computePending = false;
        emitStatus(onStatus, "error", { message: `DSP worker error: ${event.message}` });
      });

      ws = new WebSocket(wsUrl);
      ws.binaryType = "arraybuffer";

      ws.addEventListener("open", () => {
        emitStatus(onStatus, "live");
      });

      ws.addEventListener("message", (event) => {
        try {
          const parsed = parseFrame(event.data, { channels, nChannels });
          applyMetadata(parsed);
          for (const sample of parsed.samples) {
            ringBuffer.push(sample);
            sampleCount += 1;
          }
        } catch (error) {
          emitStatus(onStatus, "error", { message: error.message });
        }
      });

      ws.addEventListener("error", () => {
        emitStatus(onStatus, "error", {
          message: "WebSocket error; check that the raw EEG backend is running on port 8766.",
        });
      });

      ws.addEventListener("close", () => {
        if (!manuallyStopped) emitStatus(onStatus, "disconnected");
      });

      intervalId = window.setInterval(() => {
        if (!ringBuffer.filled || computePending || !worker) return;
        computePending = true;
        const buffers = Array.from({ length: nChannels }, (_, channelIndex) => ringBuffer.getChannel(channelIndex));
        worker.postMessage({
          type: "compute",
          buffers,
          sampling_rate: samplingRate,
          window_sec: WINDOW_SEC,
          overlap: OVERLAP,
        }, buffers.map((buffer) => buffer.buffer));
      }, UPDATE_MS);
    },

    stop() {
      manuallyStopped = true;
      if (intervalId) {
        window.clearInterval(intervalId);
        intervalId = 0;
      }
      if (ws) {
        ws.close();
        ws = null;
      }
      if (worker) {
        worker.terminate();
        worker = null;
      }
      computePending = false;
    },
  };

  function buildLiveData(result, frameSequence, elapsedMs) {
    const frequencies = Array.from(result.frequencies, Number);
    const psdRows = result.psd.map((row) => Array.from(row, Number));
    const metricRows = result.metrics.map((metrics) => ({
      centroid: finite(metrics.centroid),
      spread: finite(metrics.spread),
      entropy: finite(metrics.entropy_normalized),
      flatness: finite(metrics.flatness),
      edge95: finite(metrics.edge95),
      alpha_relative_power: finite(metrics.alpha_relative_power),
    }));
    const timeSec = elapsedMs / 1000;
    appendHistory(history, timeSec, metricRows);

    const metricsByChannel = {};
    const psdByChannel = {};
    channels.forEach((channel, index) => {
      const metrics = metricRows[index];
      metricsByChannel[channel] = {
        centroid: metrics.centroid,
        spread: metrics.spread,
        entropy: metrics.entropy,
        flatness: metrics.flatness,
        edge95: metrics.edge95,
        alpha_relative_power: metrics.alpha_relative_power,
        spectral_centroid_hz: metrics.centroid,
        spectral_spread_hz: metrics.spread,
        spectral_entropy_normalized: metrics.entropy,
        spectral_flatness: metrics.flatness,
        spectral_edge_95_hz: metrics.edge95,
      };
      psdByChannel[channel] = psdRows[index] ?? [];
    });

    const channelSummary = channels.map((channel, index) => {
      const reference = summaryByChannel.get(channel) ?? {};
      const metrics = metricRows[index];
      return {
        channel,
        hemisphere: reference.hemisphere ?? "",
        region: reference.region ?? "",
        has_clear_alpha_peak: reference.has_clear_alpha_peak ?? false,
        alpha_relative_power: metrics.alpha_relative_power,
        spectral_centroid_hz: metrics.centroid,
        spectral_spread_hz: metrics.spread,
        spectral_entropy: metrics.entropy,
        spectral_flatness: metrics.flatness,
        edge95_hz: metrics.edge95,
        alpha_peak_frequency_hz: reference.alpha_peak_frequency_hz ?? null,
        sliding_alpha_relative_mean: metrics.alpha_relative_power,
      };
    });

    return {
      type: "live_analysis",
      meta: {
        channels: channels.slice(),
        n_channels: nChannels,
        sampling_rate: samplingRate,
        sampling_rate_hz: samplingRate,
        welch_window_sec: WINDOW_SEC,
        welch_overlap_fraction: OVERLAP,
        samples_received: sampleCount,
      },
      welch_psd: {
        frequencies,
        psd: psdRows,
      },
      centroid: {
        time_relative: history.time.slice(),
        values: cloneMetric(history.centroid),
      },
      geometry: {
        time: history.time.slice(),
        centroid: cloneMetric(history.centroid),
        spread: cloneMetric(history.spread),
        entropy: cloneMetric(history.entropy),
        flatness: cloneMetric(history.flatness),
        edge95: cloneMetric(history.edge95),
        alpha_relative_power: cloneMetric(history.alpha_relative_power),
      },
      channel_summary: channelSummary,
      channel_names: channels.slice(),
      frequency_hz: frequencies,
      psd_by_channel: psdByChannel,
      metrics_by_channel: metricsByChannel,
      window_start_time_sec: timeSec,
      analysis_sequence_number: frameSequence,
      compute_ms: finite(result.compute_ms),
      update_interval_sec: UPDATE_MS / 1000,
    };
  }
}

export class RingBuffer {
  constructor(nChannels, capacity) {
    this.buf = new Float32Array(nChannels * capacity);
    this.capacity = capacity;
    this.nChannels = nChannels;
    this.writePos = 0;
    this.count = 0;
    this.filled = false;
  }

  push(frame) {
    for (let channel = 0; channel < this.nChannels; channel += 1) {
      this.buf[channel * this.capacity + this.writePos] = Number(frame[channel]) || 0;
    }
    this.writePos = (this.writePos + 1) % this.capacity;
    this.count = Math.min(this.count + 1, this.capacity);
    this.filled = this.count >= this.capacity;
  }

  getChannel(channel) {
    const out = new Float32Array(this.capacity);
    const start = this.filled ? this.writePos : 0;
    for (let index = 0; index < this.capacity; index += 1) {
      out[index] = this.buf[channel * this.capacity + ((start + index) % this.capacity)];
    }
    return out;
  }
}

function parseFrame(payload, context) {
  if (payload instanceof ArrayBuffer) {
    return {
      samples: parseFlatSamples(new Float32Array(payload), context.nChannels),
    };
  }

  if (typeof payload !== "string") {
    throw new Error("Unsupported live payload type");
  }

  const message = JSON.parse(payload);
  const metadata = extractMetadata(message);
  const nChannels = metadata.nChannels ?? metadata.channels?.length ?? context.nChannels;
  const samplePayload = extractSamplePayload(message);
  return {
    ...metadata,
    samples: samplePayload == null ? [] : normalizeSamplePayload(samplePayload, nChannels, metadata.channels ?? context.channels),
  };
}

function extractMetadata(message) {
  const source = message?.meta && typeof message.meta === "object" ? { ...message, ...message.meta } : message;
  const channels = normalizeChannels(source?.channel_names ?? source?.channels);
  const nChannels = positiveInteger(source?.n_channels ?? source?.nChannels ?? source?.channel_count);
  const samplingRate = positiveNumber(
    source?.sampling_rate_hz ??
    source?.sample_rate_hz ??
    source?.sampling_rate ??
    source?.sample_rate ??
    source?.sr ??
    source?.fs,
  );

  return {
    ...(channels ? { channels } : {}),
    ...(nChannels ? { nChannels } : {}),
    ...(samplingRate ? { samplingRate } : {}),
  };
}

function extractSamplePayload(message) {
  if (Array.isArray(message)) return message;
  if (!message || typeof message !== "object") return null;
  return (
    message.samples ??
    message.sample ??
    message.frame ??
    message.frames ??
    message.data ??
    message.values ??
    message.raw ??
    message.eeg ??
    message.eeg_data ??
    message.samples_by_channel ??
    message.data_by_channel ??
    null
  );
}

function normalizeSamplePayload(payload, nChannels, channels) {
  if (ArrayBuffer.isView(payload)) return parseFlatSamples(payload, nChannels);

  if (Array.isArray(payload)) {
    if (!Array.isArray(payload[0])) {
      return parseFlatSamples(payload, nChannels);
    }
    const rows = payload.map((row) => row.map(Number));
    if (rows.length === nChannels && rows.some((row) => row.length !== nChannels)) {
      return transposeChannelMajor(rows);
    }
    if (rows.every((row) => row.length === nChannels)) {
      return rows;
    }
    throw new Error(`Live JSON sample chunk does not match ${nChannels} channels`);
  }

  if (payload && typeof payload === "object") {
    const channelRows = channels.map((channel) => payload[channel]);
    if (channelRows.every(Array.isArray)) return transposeChannelMajor(channelRows.map((row) => row.map(Number)));
  }

  throw new Error("Live JSON frame has no supported raw samples");
}

function parseFlatSamples(values, nChannels) {
  const numeric = Array.from(values, Number);
  if (numeric.length % nChannels !== 0) {
    throw new Error(`Live sample count ${numeric.length} is not divisible by ${nChannels} channels`);
  }
  const samples = [];
  for (let offset = 0; offset < numeric.length; offset += nChannels) {
    samples.push(numeric.slice(offset, offset + nChannels));
  }
  return samples;
}

function transposeChannelMajor(rows) {
  const sampleCount = Math.min(...rows.map((row) => row.length));
  const samples = [];
  for (let sampleIndex = 0; sampleIndex < sampleCount; sampleIndex += 1) {
    samples.push(rows.map((row) => Number(row[sampleIndex]) || 0));
  }
  return samples;
}

function createHistory(channels) {
  const rows = () => channels.map(() => []);
  return {
    time: [],
    centroid: rows(),
    spread: rows(),
    entropy: rows(),
    flatness: rows(),
    edge95: rows(),
    alpha_relative_power: rows(),
  };
}

function appendHistory(history, time, metrics) {
  history.time.push(time);
  if (history.time.length > HISTORY_STEPS) history.time.shift();
  for (const [channelIndex, row] of metrics.entries()) {
    for (const key of ["centroid", "spread", "entropy", "flatness", "edge95", "alpha_relative_power"]) {
      history[key][channelIndex].push(row[key]);
      if (history[key][channelIndex].length > HISTORY_STEPS) history[key][channelIndex].shift();
    }
  }
}

function cloneMetric(rows) {
  return rows.map((row) => row.slice());
}

function normalizeChannels(value) {
  if (!Array.isArray(value) || !value.length || !value.every((item) => typeof item === "string")) return null;
  return value.slice();
}

function positiveNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function positiveInteger(value) {
  const number = Math.round(Number(value));
  return Number.isFinite(number) && number > 0 ? number : null;
}

function finite(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function nextPow2(value) {
  return 2 ** Math.ceil(Math.log2(Math.max(2, value)));
}
