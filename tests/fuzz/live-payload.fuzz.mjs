import fc from "fast-check";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import vm from "node:vm";

const repoRoot = resolve(import.meta.dirname, "../..");
const liveSourcePath = resolve(repoRoot, "js/sources/live-source.js");
const dspWorkerPath = resolve(repoRoot, "js/workers/dsp-worker.js");

const seed = Number(process.env.FUZZ_SEED ?? 0x51eed);
const liveRuns = Number(process.env.FUZZ_RUNS ?? 100_000);
const dspRuns = Number(process.env.DSP_FUZZ_RUNS ?? 10_000);

const live = loadLiveSourceHarness();
const dsp = loadDspWorkerHarness();
const summary = createSummary(seed, liveRuns, dspRuns);

console.log(`[fuzz] seed=${seed} liveRuns=${liveRuns} dspRuns=${dspRuns}`);

runKnownRepros();
runLiveFuzz();
runDspFuzz();
printSummary();

if (summary.violations.size > 0) {
  process.exitCode = 1;
}

function loadLiveSourceHarness() {
  let source = readFileSync(liveSourcePath, "utf8");
  source = source
    .replace("export function createLiveSource", "function createLiveSource")
    .replace("export class RingBuffer", "class RingBuffer")
    .replace(
      "new Worker(new URL(\"../workers/dsp-worker.js\", import.meta.url))",
      "new Worker(\"../workers/dsp-worker.js\")",
    );

  const webSockets = [];
  const workerPosts = [];

  class MockWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;

    constructor(url) {
      this.url = url;
      this.binaryType = "blob";
      this.listeners = new Map();
      this.readyState = MockWebSocket.OPEN;
      webSockets.push(this);
    }

    addEventListener(type, listener) {
      const listeners = this.listeners.get(type) ?? [];
      listeners.push(listener);
      this.listeners.set(type, listeners);
    }

    emit(type, event = {}) {
      for (const listener of this.listeners.get(type) ?? []) {
        listener(event);
      }
    }

    close() {
      this.readyState = MockWebSocket.CLOSED;
      this.emit("close", {});
    }
  }

  class MockWorker {
    constructor(url) {
      this.url = url;
      this.listeners = new Map();
    }

    addEventListener(type, listener) {
      const listeners = this.listeners.get(type) ?? [];
      listeners.push(listener);
      this.listeners.set(type, listeners);
    }

    postMessage(message) {
      workerPosts.push(message);
    }

    terminate() {}
  }

  const context = {
    Array,
    ArrayBuffer,
    console,
    Error,
    Float32Array,
    Map,
    Math,
    Number,
    Object,
    performance: { now: () => 0 },
    URL,
    WebSocket: MockWebSocket,
    Worker: MockWorker,
    window: {
      clearInterval() {},
      setInterval() {
        return 1;
      },
    },
    __exports: {},
  };

  vm.createContext(context);
  vm.runInContext(
    `${source}
__exports.createLiveSource = createLiveSource;
__exports.parseFrame = parseFrame;
__exports.RingBuffer = RingBuffer;`,
    context,
    { filename: liveSourcePath },
  );

  return {
    createLiveSource: context.__exports.createLiveSource,
    parseFrame: context.__exports.parseFrame,
    webSockets,
    workerPosts,
  };
}

function loadDspWorkerHarness() {
  const source = readFileSync(dspWorkerPath, "utf8");
  const handlers = new Map();
  const posts = [];
  const context = {
    console,
    performance: { now: () => 0 },
    self: {
      addEventListener(type, listener) {
        handlers.set(type, listener);
      },
      postMessage(message) {
        posts.push(message);
      },
    },
  };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: dspWorkerPath });
  const messageHandler = handlers.get("message");
  if (typeof messageHandler !== "function") {
    throw new Error("DSP worker message handler was not registered");
  }
  return {
    compute(message) {
      posts.length = 0;
      let uncaught = null;
      try {
        messageHandler({ data: message });
      } catch (error) {
        uncaught = error;
      }
      return { uncaught, posts: posts.slice() };
    },
  };
}

function runKnownRepros() {
  const repros = [
    {
      label: "metadata channel-count conflict truncates after applyMetadata",
      case: {
        kind: "metadataConflict",
        state: { nChannels: 2, channels: ["A", "B"] },
        payload: JSON.stringify({ channels: ["A", "B"], n_channels: 3, samples: [1, 2, 3] }),
      },
    },
    {
      label: "changed channel names with conflicting n_channels misalign sample width",
      case: {
        kind: "metadataConflict",
        state: { nChannels: 2, channels: ["A", "B"] },
        payload: JSON.stringify({ channels: ["C", "D"], n_channels: 3, samples: [1, 2, 3] }),
      },
    },
    {
      label: "square 2D data_by_channel is treated as sample-major",
      case: {
        kind: "validChannelMajorArray",
        state: { nChannels: 2, channels: ["A", "B"] },
        payload: JSON.stringify({ channels: ["A", "B"], data_by_channel: [[1, 2], [100, 200]] }),
        expectedSamples: [[1, 100], [2, 200]],
      },
    },
    {
      label: "non-finite Float32 samples pass through parser",
      case: {
        kind: "nonFiniteBinary",
        state: { nChannels: 2, channels: ["A", "B"] },
        payload: new Float32Array([Infinity, 0]).buffer,
      },
    },
    {
      label: "fractional n_channels is rounded and accepted",
      case: {
        kind: "malformedMetadata",
        state: { nChannels: 2, channels: ["A", "B"] },
        payload: JSON.stringify({ n_channels: 1.5, samples: [1, 2] }),
      },
    },
  ];

  for (const { label, case: fuzzCase } of repros) {
    const result = inspectLiveCase(fuzzCase);
    for (const violation of result.violations) {
      recordViolation(violation, {
        source: "known-live-repro",
        label,
        repro: liveRepro(fuzzCase),
      });
    }
  }

  const dspCase = {
    kind: "nonFiniteDsp",
    message: {
      type: "compute",
      sampling_rate: 64,
      window_sec: 0.125,
      overlap: 0.5,
      buffers: [new Float32Array([Infinity, 0, 1, 0, -1, 0, 1, 0])],
    },
  };
  const dspResult = inspectDspCase(dspCase);
  for (const violation of dspResult.violations) {
    recordViolation(violation, {
      source: "known-dsp-repro",
      label: "non-finite DSP input produces non-finite output",
      repro: dspRepro(dspCase),
    });
  }

  const emptyBandDspCase = {
    kind: "validDsp",
    message: {
      type: "compute",
      sampling_rate: 1024,
      window_sec: 0.0078125,
      overlap: 0.5,
      buffers: [new Float32Array([1, 0, -1, 0, 1, 0, -1, 0])],
    },
    expectResult: true,
  };
  const emptyBandResult = inspectDspCase(emptyBandDspCase);
  for (const violation of emptyBandResult.violations) {
    recordViolation(violation, {
      source: "known-dsp-repro",
      label: "DSP trim band can be empty at high sample rate and short window",
      repro: dspRepro(emptyBandDspCase),
    });
  }
}

function runLiveFuzz() {
  fc.assert(
    fc.property(liveCaseArbitrary(), (spec) => {
      const fuzzCase = buildLiveCase(spec);
      const result = inspectLiveCase(fuzzCase);
      summary.live.accepted += result.accepted ? 1 : 0;
      summary.live.rejected += result.rejected ? 1 : 0;
      summary.live.cases += 1;
      for (const violation of result.violations) {
        recordViolation(violation, {
          source: "live-fuzz",
          repro: () => liveRepro(fuzzCase),
        });
      }
      return true;
    }),
    { seed, numRuns: liveRuns },
  );
}

function runDspFuzz() {
  fc.assert(
    fc.property(dspCaseArbitrary(), (spec) => {
      const dspCase = buildDspCase(spec);
      const result = inspectDspCase(dspCase);
      summary.dsp.results += result.resultCount;
      summary.dsp.errors += result.errorCount;
      summary.dsp.cases += 1;
      for (const violation of result.violations) {
        recordViolation(violation, {
          source: "dsp-fuzz",
          repro: () => dspRepro(dspCase),
        });
      }
      return true;
    }),
    { seed: seed ^ 0xd5f, numRuns: dspRuns },
  );
}

function liveCaseArbitrary() {
  return fc.record({
    kind: fc.constantFrom(
      "validBinary",
      "validJsonOneSample",
      "validSampleMajor",
      "validChannelMajorObject",
      "validChannelMajorArray",
      "handshake",
      "misalignedBinary",
      "byteMisalignedBinary",
      "mixedTypes",
      "nonFiniteBinary",
      "emptyChunk",
      "oversizedSampleMajor",
      "malformedMetadata",
      "metadataConflict",
    ),
    initialN: fc.integer({ min: 1, max: 64 }),
    nextN: fc.integer({ min: 1, max: 64 }),
    sampleCount: fc.integer({ min: 0, max: 8 }),
    sampleRate: fc.integer({ min: 1, max: 4096 }),
    keyIndex: fc.integer({ min: 0, max: 8 }),
    seed: fc.integer(),
  });
}

function dspCaseArbitrary() {
  return fc.record({
    kind: fc.constantFrom(
      "validDsp",
      "multiChannelDsp",
      "invalidSamplingRate",
      "missingBuffers",
      "nonArrayBuffers",
      "emptyDsp",
      "shortDsp",
      "nonFiniteDsp",
    ),
    channels: fc.integer({ min: 0, max: 16 }),
    length: fc.integer({ min: 0, max: 64 }),
    sampleRate: fc.integer({ min: -128, max: 1024 }),
    seed: fc.integer(),
  });
}

function buildLiveCase(spec) {
  const state = {
    nChannels: spec.initialN,
    channels: names(spec.initialN, "S"),
  };
  const n = spec.nextN;
  const channels = names(n, "C");
  const sampleCount = Math.max(0, spec.sampleCount);
  const key = sampleKey(spec.keyIndex);

  switch (spec.kind) {
    case "validBinary": {
      const values = finiteValues(state.nChannels * Math.max(1, sampleCount), spec.seed);
      const float32Values = Array.from(new Float32Array(values));
      return {
        kind: spec.kind,
        state,
        payload: new Float32Array(float32Values).buffer,
        expectedSamples: chunk(float32Values, state.nChannels),
      };
    }
    case "validJsonOneSample": {
      const sample = finiteValues(state.nChannels, spec.seed);
      return {
        kind: spec.kind,
        state,
        payload: JSON.stringify(sample),
        expectedSamples: [sample],
      };
    }
    case "validSampleMajor": {
      const rows = sampleMajorRows(n, Math.max(1, sampleCount), spec.seed);
      return {
        kind: spec.kind,
        state,
        payload: JSON.stringify({ channels, sampling_rate_hz: spec.sampleRate, [key]: rows }),
        expectedSamples: rows,
      };
    }
    case "validChannelMajorObject": {
      const byChannel = channelMajorObject(channels, Math.max(1, sampleCount), spec.seed);
      return {
        kind: spec.kind,
        state,
        payload: JSON.stringify({ meta: { channels, sampling_rate_hz: spec.sampleRate }, samples_by_channel: byChannel }),
        expectedSamples: transpose(Object.values(byChannel)),
      };
    }
    case "validChannelMajorArray": {
      const rows = channelMajorRows(n, Math.max(1, sampleCount), spec.seed);
      return {
        kind: spec.kind,
        state,
        payload: JSON.stringify({ meta: { channels }, data_by_channel: rows }),
        expectedSamples: transpose(rows),
      };
    }
    case "handshake":
      return {
        kind: spec.kind,
        state,
        payload: JSON.stringify({ meta: { channel_names: channels, sampling_rate_hz: spec.sampleRate } }),
        expectedSamples: [],
      };
    case "misalignedBinary": {
      if (state.nChannels === 1) {
        return {
          kind: spec.kind,
          state,
          payload: new ArrayBuffer(2),
          expectReject: true,
        };
      }
      const extra = 1 + Math.abs(spec.seed % (state.nChannels - 1));
      const values = finiteValues((state.nChannels * Math.max(1, sampleCount)) + extra, spec.seed);
      return {
        kind: spec.kind,
        state,
        payload: new Float32Array(values).buffer,
        expectReject: true,
      };
    }
    case "byteMisalignedBinary":
      return {
        kind: spec.kind,
        state,
        payload: new ArrayBuffer(1 + Math.abs(spec.seed % 3)),
        expectReject: true,
      };
    case "mixedTypes":
      return {
        kind: spec.kind,
        state,
        payload: JSON.stringify({ samples: [1, "Infinity", null, {}, []].slice(0, state.nChannels) }),
      };
    case "nonFiniteBinary": {
      const values = finiteValues(state.nChannels * Math.max(1, sampleCount), spec.seed);
      values[0] = spec.seed % 2 === 0 ? Infinity : NaN;
      return {
        kind: spec.kind,
        state,
        payload: new Float32Array(values).buffer,
      };
    }
    case "emptyChunk":
      return {
        kind: spec.kind,
        state,
        payload: JSON.stringify({ samples: [] }),
        expectedSamples: [],
      };
    case "oversizedSampleMajor": {
      const rows = sampleMajorRows(state.nChannels, 256 + Math.abs(spec.seed % 256), spec.seed);
      return {
        kind: spec.kind,
        state,
        payload: JSON.stringify({ samples: rows }),
        expectedSamples: rows,
      };
    }
    case "malformedMetadata":
      return {
        kind: spec.kind,
        state,
        payload: JSON.stringify({ meta: { channels: [1, null, "C"], n_channels: 1.5, sampling_rate_hz: "bad" }, samples: [1, 2] }),
      };
    case "metadataConflict": {
      const conflictN = Math.max(1, n + 1);
      const values = finiteValues(conflictN, spec.seed);
      return {
        kind: spec.kind,
        state,
        payload: JSON.stringify({ channels, n_channels: conflictN, samples: values }),
      };
    }
    default:
      throw new Error(`Unhandled live fuzz kind ${spec.kind}`);
  }
}

function buildDspCase(spec) {
  const signalLength = Math.max(8, spec.length);
  const sampleRate = spec.sampleRate || 64;
  switch (spec.kind) {
    case "validDsp":
      return {
        kind: spec.kind,
        message: {
          type: "compute",
          sampling_rate: Math.max(8, Math.abs(sampleRate)),
          window_sec: signalLength / Math.max(8, Math.abs(sampleRate)),
          overlap: 0.5,
          buffers: [new Float32Array(finiteValues(signalLength, spec.seed))],
        },
        expectResult: true,
      };
    case "multiChannelDsp":
      return {
        kind: spec.kind,
        message: {
          type: "compute",
          sampling_rate: 128,
          window_sec: signalLength / 128,
          overlap: 0.25,
          buffers: Array.from({ length: Math.max(1, spec.channels) }, (_, index) => (
            new Float32Array(finiteValues(signalLength, spec.seed + index))
          )),
        },
        expectResult: true,
      };
    case "invalidSamplingRate":
      return {
        kind: spec.kind,
        message: { type: "compute", sampling_rate: -Math.max(1, Math.abs(spec.sampleRate)), buffers: [new Float32Array(finiteValues(8, spec.seed))] },
        expectError: true,
      };
    case "missingBuffers":
      return {
        kind: spec.kind,
        message: { type: "compute", sampling_rate: 64 },
        expectError: true,
      };
    case "nonArrayBuffers":
      return {
        kind: spec.kind,
        message: { type: "compute", sampling_rate: 64, buffers: { bad: true } },
        expectError: true,
      };
    case "emptyDsp":
      return {
        kind: spec.kind,
        message: { type: "compute", sampling_rate: 64, window_sec: 0.125, buffers: [new Float32Array()] },
        expectError: true,
      };
    case "shortDsp":
      return {
        kind: spec.kind,
        message: { type: "compute", sampling_rate: 64, window_sec: 0.125, buffers: [new Float32Array(finiteValues(Math.max(0, spec.length % 8), spec.seed))] },
        expectError: true,
      };
    case "nonFiniteDsp": {
      const values = finiteValues(signalLength, spec.seed);
      values[0] = spec.seed % 2 === 0 ? Infinity : NaN;
      return {
        kind: spec.kind,
        message: {
          type: "compute",
          sampling_rate: 64,
          window_sec: signalLength / 64,
          overlap: 0.5,
          buffers: [new Float32Array(values)],
        },
      };
    }
    default:
      throw new Error(`Unhandled DSP fuzz kind ${spec.kind}`);
  }
}

function inspectLiveCase(fuzzCase) {
  const result = parseLivePayload(fuzzCase.payload, fuzzCase.state);
  const violations = [];

  if (result.uncaught) {
    violations.push({
      code: "live_uncaught_throw",
      detail: String(result.uncaught?.message ?? result.uncaught),
    });
    return { ...result, violations };
  }

  if (fuzzCase.expectReject && result.accepted) {
    violations.push({
      code: "expected_reject_was_accepted",
      detail: `${fuzzCase.kind} parsed ${result.samples.length} samples`,
    });
  }

  if (!fuzzCase.expectReject && fuzzCase.expectedSamples && result.rejected) {
    violations.push({
      code: "valid_payload_rejected",
      detail: result.error.message,
    });
  }

  if (result.accepted) {
    const badWidth = result.samples.find((sample) => !Array.isArray(sample) || sample.length !== result.nextState.nChannels);
    if (badWidth) {
      violations.push({
        code: "channel_width_misalignment_after_metadata",
        detail: `sample width ${badWidth?.length ?? "non-array"} after state n=${result.nextState.nChannels}`,
      });
    }

    if (result.parsed.channels?.length && result.parsed.nChannels && result.parsed.channels.length !== result.parsed.nChannels) {
      violations.push({
        code: "conflicting_channel_metadata_accepted",
        detail: `channels.length=${result.parsed.channels.length}, nChannels=${result.parsed.nChannels}`,
      });
    }

    if (containsNonFinite(result.samples)) {
      violations.push({
        code: "non_finite_samples_accepted_by_parser",
        detail: "NaN or Infinity reached parsed sample rows",
      });
    }

    if (fuzzCase.kind === "malformedMetadata" && result.parsed.nChannels) {
      violations.push({
        code: "malformed_fractional_channel_count_accepted",
        detail: `rounded nChannels=${result.parsed.nChannels}`,
      });
    }

    if (fuzzCase.expectedSamples && !same2d(result.samples, fuzzCase.expectedSamples)) {
      violations.push({
        code: fuzzCase.kind === "validChannelMajorArray"
          ? "channel_major_square_array_misaligned"
          : "accepted_samples_do_not_match_contract_shape",
        detail: `expected ${preview(fuzzCase.expectedSamples)} got ${preview(result.samples)}`,
      });
    }
  }

  return { ...result, violations };
}

function parseLivePayload(payload, state) {
  try {
    const parsed = live.parseFrame(payload, { channels: state.channels, nChannels: state.nChannels });
    const nextState = applyMetadataLikeLiveSource(state, parsed);
    return {
      accepted: true,
      rejected: false,
      parsed,
      samples: parsed.samples ?? [],
      nextState,
    };
  } catch (error) {
    return {
      accepted: false,
      rejected: true,
      error,
      samples: [],
      nextState: state,
    };
  }
}

function applyMetadataLikeLiveSource(state, metadata) {
  let channels = state.channels.slice();
  let nChannels = state.nChannels;
  if (metadata.channels?.length && metadata.channels.join("\u0000") !== channels.join("\u0000")) {
    channels = metadata.channels.slice();
    nChannels = channels.length;
  } else if (metadata.nChannels && metadata.nChannels !== nChannels) {
    nChannels = metadata.nChannels;
    channels = channels.length === nChannels
      ? channels
      : Array.from({ length: nChannels }, (_, index) => `Ch${index + 1}`);
  }
  return { channels, nChannels };
}

function inspectDspCase(dspCase) {
  const result = dsp.compute(dspCase.message);
  const violations = [];
  const resultPosts = result.posts.filter((post) => post?.type === "result");
  const errorPosts = result.posts.filter((post) => post?.type === "error");

  if (result.uncaught) {
    violations.push({
      code: "dsp_uncaught_throw",
      detail: String(result.uncaught?.message ?? result.uncaught),
    });
  }

  if (dspCase.message?.type === "compute" && result.posts.length === 0 && !result.uncaught) {
    violations.push({
      code: "dsp_compute_no_response",
      detail: "compute message produced neither result nor error",
    });
  }

  if (dspCase.expectResult && errorPosts.length > 0) {
    violations.push({
      code: "valid_dsp_payload_rejected",
      detail: errorPosts[0].message,
    });
  }

  if (dspCase.expectError && resultPosts.length > 0) {
    violations.push({
      code: "invalid_dsp_payload_returned_result",
      detail: "invalid DSP input returned a result",
    });
  }

  for (const post of resultPosts) {
    const expectedRows = Array.isArray(dspCase.message.buffers) ? dspCase.message.buffers.length : 0;
    if (!Array.isArray(post.psd) || post.psd.length !== expectedRows) {
      violations.push({
        code: "dsp_channel_result_count_mismatch",
        detail: `expected ${expectedRows} PSD rows, got ${post.psd?.length ?? "non-array"}`,
      });
    }
    if (containsNonFinite([Array.from(post.frequencies ?? []), ...post.psd.map((row) => Array.from(row ?? []))])) {
      violations.push({
        code: "dsp_non_finite_result_values",
        detail: "DSP result contains NaN or Infinity frequencies/PSD",
      });
    }
    if (containsNonFinite(post.metrics.map((metrics) => Object.values(metrics ?? {})))) {
      violations.push({
        code: "dsp_non_finite_metric_values",
        detail: "DSP result contains NaN or Infinity metrics",
      });
    }
  }

  return {
    case: dspCase,
    resultCount: resultPosts.length,
    errorCount: errorPosts.length,
    violations,
  };
}

function exerciseLiveSourcePayload(payload) {
  const statuses = [];
  const source = live.createLiveSource("ws://127.0.0.1:8766", { channels: ["A", "B"], samplingRate: 64 });
  source.start(null, (status, detail) => statuses.push({ status, detail }));
  const ws = live.webSockets.at(-1);
  let uncaught = null;
  try {
    ws.emit("message", { data: payload });
  } catch (error) {
    uncaught = error;
  } finally {
    source.stop();
  }
  return { uncaught, statuses };
}

function createSummary(seedValue, configuredLiveRuns, configuredDspRuns) {
  return {
    seed: seedValue,
    configuredLiveRuns,
    configuredDspRuns,
    live: { cases: 0, accepted: 0, rejected: 0 },
    dsp: { cases: 0, results: 0, errors: 0 },
    violations: new Map(),
    firstNewAt: new Map(),
  };
}

function recordViolation(violation, evidence) {
  const materializeEvidence = () => ({
    ...evidence,
    repro: typeof evidence.repro === "function" ? evidence.repro() : evidence.repro,
  });
  const current = summary.violations.get(violation.code) ?? {
    code: violation.code,
    count: 0,
    detail: violation.detail,
    evidence: materializeEvidence(),
  };
  current.count += 1;
  if (evidence.source.startsWith("known-")) {
    current.evidence = materializeEvidence();
    current.detail = violation.detail;
  }
  summary.violations.set(violation.code, current);
  if (!summary.firstNewAt.has(violation.code)) {
    summary.firstNewAt.set(violation.code, summary.live.cases + summary.dsp.cases);
  }
}

function printSummary() {
  const liveSafe = exerciseLiveSourcePayload(new ArrayBuffer(1));
  if (liveSafe.uncaught) {
    recordViolation({
      code: "live_websocket_handler_uncaught_throw",
      detail: String(liveSafe.uncaught?.message ?? liveSafe.uncaught),
    }, {
      source: "known-live-source-repro",
      label: "byte-misaligned WebSocket ArrayBuffer",
      repro: "new ArrayBuffer(1)",
    });
  }

  console.log(`[fuzz] live accepted=${summary.live.accepted} rejected=${summary.live.rejected} total=${summary.live.cases}`);
  console.log(`[fuzz] dsp results=${summary.dsp.results} errors=${summary.dsp.errors} total=${summary.dsp.cases}`);

  if (summary.violations.size === 0) {
    console.log(`[fuzz] robust over ${summary.live.cases + summary.dsp.cases} cases`);
    return;
  }

  console.log(`[fuzz] distinct violation classes=${summary.violations.size}`);
  for (const item of [...summary.violations.values()].sort((a, b) => a.code.localeCompare(b.code))) {
    const firstAt = summary.firstNewAt.get(item.code) ?? 0;
    const dryTail = summary.live.cases + summary.dsp.cases - firstAt;
    console.log(`[violation] ${item.code} count=${item.count} dryTail=${dryTail}`);
    console.log(`  detail: ${item.detail}`);
    console.log(`  source: ${item.evidence.source}`);
    if (item.evidence.label) console.log(`  label: ${item.evidence.label}`);
    console.log(`  minimal_repro: ${item.evidence.repro}`);
  }
}

function names(count, prefix) {
  return Array.from({ length: count }, (_, index) => `${prefix}${index + 1}`);
}

function sampleKey(index) {
  return ["samples", "data", "values", "frame", "frames", "raw", "eeg", "eeg_data"][Math.abs(index) % 8];
}

function finiteValues(length, seedValue) {
  return Array.from({ length }, (_, index) => {
    const value = Math.sin((seedValue + index + 1) * 0.017) * 100;
    return Number(value.toFixed(6));
  });
}

function sampleMajorRows(nChannels, sampleCount, seedValue) {
  return Array.from({ length: sampleCount }, (_, sampleIndex) => (
    Array.from({ length: nChannels }, (_, channelIndex) => sampleIndex * 10_000 + channelIndex + (seedValue % 7))
  ));
}

function channelMajorRows(nChannels, sampleCount, seedValue) {
  return Array.from({ length: nChannels }, (_, channelIndex) => (
    Array.from({ length: sampleCount }, (_, sampleIndex) => channelIndex * 10_000 + sampleIndex + (seedValue % 7))
  ));
}

function channelMajorObject(channels, sampleCount, seedValue) {
  return Object.fromEntries(channels.map((channel, channelIndex) => [
    channel,
    Array.from({ length: sampleCount }, (_, sampleIndex) => channelIndex * 10_000 + sampleIndex + (seedValue % 7)),
  ]));
}

function transpose(rows) {
  if (rows.length === 0) return [];
  const sampleCount = Math.min(...rows.map((row) => row.length));
  return Array.from({ length: sampleCount }, (_, sampleIndex) => rows.map((row) => Number(row[sampleIndex]) || 0));
}

function chunk(values, width) {
  const rows = [];
  for (let offset = 0; offset < values.length; offset += width) {
    rows.push(values.slice(offset, offset + width));
  }
  return rows;
}

function containsNonFinite(rows) {
  return rows.some((row) => row.some((value) => !Number.isFinite(Number(value))));
}

function same2d(actual, expected) {
  if (actual.length !== expected.length) return false;
  return actual.every((row, rowIndex) => (
    row.length === expected[rowIndex].length &&
    row.every((value, columnIndex) => Object.is(Number(value), Number(expected[rowIndex][columnIndex])))
  ));
}

function preview(value) {
  return JSON.stringify(value).slice(0, 240);
}

function liveRepro(fuzzCase) {
  return JSON.stringify({
    kind: fuzzCase.kind,
    state: fuzzCase.state,
    payload: payloadPreview(fuzzCase.payload),
  });
}

function dspRepro(dspCase) {
  return JSON.stringify({
    kind: dspCase.kind,
    message: dspMessagePreview(dspCase.message),
  });
}

function payloadPreview(payload) {
  if (payload instanceof ArrayBuffer) {
    if (payload.byteLength % 4 !== 0) return { arrayBufferByteLength: payload.byteLength };
    return { float32: Array.from(new Float32Array(payload)).map(jsonNumber) };
  }
  return payload;
}

function dspMessagePreview(message) {
  if (!message || typeof message !== "object") return message;
  return {
    ...message,
    buffers: Array.isArray(message.buffers)
      ? message.buffers.map((buffer) => (
        ArrayBuffer.isView(buffer)
          ? { type: buffer.constructor.name, values: Array.from(buffer).map(jsonNumber) }
          : buffer
      ))
      : message.buffers,
  };
}

function jsonNumber(value) {
  if (Number.isNaN(value)) return "NaN";
  if (value === Infinity) return "Infinity";
  if (value === -Infinity) return "-Infinity";
  return value;
}
