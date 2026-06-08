import { createLiveSource } from "./sources/live-source.js";
import { createStaticSource, loadStaticData, validateData } from "./sources/static-source.js";

let activeSource = createStaticSource();
let jsZipPromise = null;

const JSZIP_URL = "https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js";

export { createLiveSource, createStaticSource };

const CHANNELS = [
  "Fp1",
  "Fpz",
  "Fp2",
  "F7",
  "F3",
  "Fz",
  "F4",
  "F8",
  "FC5",
  "FC1",
  "FC2",
  "FC6",
  "M1",
  "T7",
  "C3",
  "Cz",
  "C4",
  "T8",
  "M2",
  "CP5",
  "CP1",
  "CP2",
  "CP6",
  "P7",
  "P3",
  "Pz",
  "P4",
  "P8",
  "POz",
  "O1",
  "Oz",
  "O2",
];

const GEOMETRY_FILES = {
  centroid: "sliding_spectral_centroid_wide.csv",
  spread: "sliding_spectral_spread_wide.csv",
  entropy: "sliding_spectral_entropy_wide.csv",
  flatness: "sliding_spectral_flatness_wide.csv",
  edge95: "sliding_spectral_edge95_wide.csv",
  alpha_relative_power: "sliding_alpha_relative_power_wide.csv",
};

export async function loadData() {
  return loadStaticData();
}

export async function loadZip(file) {
  const { zip } = await readZip(file);
  const dataJson = findDataJson(zip);
  if (dataJson) {
    const data = JSON.parse(await dataJson.async("string"));
    validateData(data);
    return data;
  }

  const kind = classifyZip(zip);
  if (kind === "combined-csv") {
    return buildDataFromCsvArchives(zip, zip, file.name);
  }

  throw new Error(`${file.name} is not a complete NeuroMouse dataset ZIP`);
}

export async function loadDatasetFiles(files) {
  const datasets = [];
  const errors = [];
  const welchArchives = [];
  const geometryArchives = [];

  for (const file of files) {
    try {
      if (file.name.toLowerCase().endsWith(".json")) {
        const data = JSON.parse(await file.text());
        validateData(data);
        datasets.push({ name: file.name, data });
        continue;
      }

      if (!file.name.toLowerCase().endsWith(".zip")) {
        errors.push(`${file.name}: drop NeuroMouse data.json or ZIP exports`);
        continue;
      }

      const archive = await readZip(file);
      const dataJson = findDataJson(archive.zip);
      if (dataJson) {
        const data = JSON.parse(await dataJson.async("string"));
        validateData(data);
        datasets.push({ name: file.name, data });
        continue;
      }

      const kind = classifyZip(archive.zip);
      if (kind === "combined-csv") {
        datasets.push({
          name: file.name,
          data: await buildDataFromCsvArchives(archive.zip, archive.zip, file.name),
        });
      } else if (kind === "welch") {
        welchArchives.push(archive);
      } else if (kind === "geometry") {
        geometryArchives.push(archive);
      } else {
        errors.push(`${file.name}: unsupported ZIP format`);
      }
    } catch (error) {
      errors.push(`${file.name}: ${error.message}`);
    }
  }

  const pairCount = Math.min(welchArchives.length, geometryArchives.length);
  for (let index = 0; index < pairCount; index += 1) {
    const welch = welchArchives[index];
    const geometry = geometryArchives[index];
    try {
      datasets.push({
        name: pairedName(welch.file.name, geometry.file.name),
        data: await buildDataFromCsvArchives(welch.zip, geometry.zip, pairedName(welch.file.name, geometry.file.name)),
      });
    } catch (error) {
      errors.push(`${welch.file.name} + ${geometry.file.name}: ${error.message}`);
    }
  }

  welchArchives.slice(pairCount).forEach((archive) => {
    errors.push(`${archive.file.name}: drop a matching geometry ZIP with this Welch export`);
  });
  geometryArchives.slice(pairCount).forEach((archive) => {
    errors.push(`${archive.file.name}: drop a matching Welch ZIP with this geometry export`);
  });

  return { datasets, errors };
}

export async function loadZipFiles(files) {
  return loadDatasetFiles(files);
}

export function setSource(source) {
  activeSource?.stop?.();
  activeSource = source ?? createStaticSource();
  return activeSource;
}

export function getSource() {
  return activeSource;
}

export function connectLive(
  url = "ws://127.0.0.1:8766",
  { onFrame, onStatus, onError } = {},
) {
  const source = setSource(createLiveSource(url));
  source.start(onFrame, (status, detail = {}) => {
    onStatus?.({
      message: status,
      connected: status === "live",
      url,
      ...detail,
    });
    if (status === "error") onError?.(detail.message ?? "Live source error");
  });

  return {
    close() {
      source.stop();
    },
    source,
  };
}

async function readZip(file) {
  const Zip = await loadJSZip();
  return {
    file,
    zip: await Zip.loadAsync(file),
  };
}

async function loadJSZip() {
  if (globalThis.JSZip) return globalThis.JSZip;
  if (!jsZipPromise) {
    jsZipPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = JSZIP_URL;
      script.async = true;
      script.crossOrigin = "anonymous";
      script.onload = () => {
        if (globalThis.JSZip) resolve(globalThis.JSZip);
        else reject(new Error("JSZip failed to initialize"));
      };
      script.onerror = () => reject(new Error("Failed to load JSZip"));
      document.head.append(script);
    });
  }
  return jsZipPromise;
}

function classifyZip(zip) {
  const hasWelch = Boolean(
    findMember(zip, "eeg_welch_centroid_export.json") &&
    findMember(zip, "welch_psd_wide.csv") &&
    findMember(zip, "spectral_centroid_wide.csv"),
  );
  const hasGeometry = Boolean(
    findMember(zip, "spectral_centroid_channel_summary.csv") &&
    findMember(zip, "spectral_centroid_geometry_metadata.json") &&
    findMember(zip, "mean_psd_area_normalized_wide.csv") &&
    Object.values(GEOMETRY_FILES).every((member) => findMember(zip, member)),
  );

  if (hasWelch && hasGeometry) return "combined-csv";
  if (hasWelch) return "welch";
  if (hasGeometry) return "geometry";
  return "unsupported";
}

async function buildDataFromCsvArchives(welchZip, geometryZip, sourceName) {
  const welchJson = await readZipJson(welchZip, "eeg_welch_centroid_export.json");
  const geometryMeta = await readZipJson(geometryZip, "spectral_centroid_geometry_metadata.json");
  const channels = welchJson.metadata?.channel_names ?? CHANNELS;

  const [welchFreq, welchPsd] = await readWideMatrix(welchZip, "welch_psd_wide.csv", "frequency_hz", channels);
  const [centroidTime, centroidValues] = await readWideMatrix(welchZip, "spectral_centroid_wide.csv", "time_relative_sec", channels);
  const [geometryTime, geometryCentroid] = await readWideMatrix(geometryZip, GEOMETRY_FILES.centroid, "time_relative_sec", channels);

  const geometry = {
    time: geometryTime,
    centroid: geometryCentroid,
  };

  for (const [key, member] of Object.entries(GEOMETRY_FILES)) {
    if (key === "centroid") continue;
    const [time, values] = await readWideMatrix(geometryZip, member, "time_relative_sec", channels);
    if (!sameAxis(time, geometryTime)) throw new Error(`${member} has a different time axis`);
    geometry[key] = values;
  }

  const [areaFreq, areaPsd] = await readWideMatrix(geometryZip, "mean_psd_area_normalized_wide.csv", "frequency_hz", channels);
  geometry.area_normalized_psd = {
    frequencies: areaFreq,
    psd: areaPsd,
  };

  const segmentStart = Number(geometryMeta.segment_start_sec ?? 0);
  const segmentEnd = Number(geometryMeta.segment_end_sec ?? segmentStart);
  const data = {
    meta: {
      channels,
      n_channels: channels.length,
      segment_duration_sec: round(segmentEnd - segmentStart, 3),
      sampling_rate_analysis_hz: Number(geometryMeta.analysis_sample_rate_hz ?? 0),
      welch_window_sec: Number(geometryMeta.welch_window_sec ?? 0),
      welch_overlap_fraction: Number(geometryMeta.welch_overlap ?? 0),
      sliding_window_sec: Number(geometryMeta.sliding_window_sec ?? 0),
      sliding_step_sec: Number(geometryMeta.sliding_step_sec ?? 0),
      source: "GX dataset (Gebodh/CCNY), CC BY-SA 4.0",
      analysis_by: "soulsyrup1/Complete-Neural-Signal-Analysis",
      source_files: {
        browser_zip: sourceName,
      },
    },
    welch_psd: {
      frequencies: welchFreq,
      psd: welchPsd,
    },
    centroid: {
      time_relative: centroidTime,
      values: centroidValues,
    },
    geometry,
    channel_summary: await buildChannelSummary(geometryZip, channels),
  };

  validateData(data);
  return data;
}

async function readWideMatrix(zip, member, axisKey, channels) {
  const rows = await readZipCsv(zip, member);
  if (!rows.length) throw new Error(`${member} has no rows`);

  const missing = channels.filter((channel) => !(channel in rows[0]));
  if (missing.length) {
    throw new Error(`${member} is missing channel columns: ${missing.join(", ")}`);
  }

  return [
    rows.map((row) => toFloat(row[axisKey])),
    channels.map((channel) => rows.map((row) => toFloat(row[channel]))),
  ];
}

async function buildChannelSummary(zip, channels) {
  const rows = await readZipCsv(zip, "spectral_centroid_channel_summary.csv");
  const byChannel = new Map(rows.map((row) => [row.channel, row]));
  return channels.map((channel) => {
    const row = byChannel.get(channel);
    if (!row) throw new Error(`spectral_centroid_channel_summary.csv is missing ${channel}`);
    return {
      channel,
      hemisphere: shortHemisphere(row.hemisphere ?? ""),
      region: row.region,
      has_clear_alpha_peak: boolFromCsv(row.has_clear_alpha_peak ?? ""),
      alpha_relative_power: firstFloat(row, ["alpha_relative_power_2_45Hz", "alpha_relative_power"]),
      spectral_centroid_hz: firstFloat(row, ["spectral_centroid_Hz_2_45Hz", "spectral_centroid_hz"]),
      spectral_spread_hz: firstFloat(row, ["spectral_spread_Hz_2_45Hz", "spectral_spread_hz"]),
      spectral_entropy: firstFloat(row, ["spectral_entropy_normalized_2_45Hz", "spectral_entropy"]),
      spectral_flatness: firstFloat(row, ["spectral_flatness_2_45Hz", "spectral_flatness"]),
      edge95_hz: firstFloat(row, ["spectral_edge_95Hz", "edge95_hz"]),
      alpha_peak_frequency_hz: firstFloat(row, ["alpha_peak_frequency_Hz", "alpha_peak_frequency_hz"]),
      sliding_alpha_relative_mean: firstFloat(row, ["sliding_alpha_relative_mean"]),
    };
  });
}

async function readZipJson(zip, member) {
  const file = findMember(zip, member);
  if (!file) throw new Error(`Missing ${member}`);
  return JSON.parse(await file.async("string"));
}

async function readZipCsv(zip, member) {
  const file = findMember(zip, member);
  if (!file) throw new Error(`Missing ${member}`);
  const text = await file.async("string");
  return parseCsv(text);
}

function findMember(zip, member) {
  if (zip.files[member]) return zip.files[member];
  const normalized = member.replace(/^\/+/, "");
  const entry = Object.values(zip.files).find((file) => (
    !file.dir && file.name.replace(/^\/+/, "").endsWith(normalized)
  ));
  return entry ?? null;
}

function findDataJson(zip) {
  if (zip.files["data/data.json"]) return zip.files["data/data.json"];
  return Object.values(zip.files).find((file) => (
    !file.dir && file.name.replace(/^\/+/, "").split("/").at(-1) === "data.json"
  )) ?? null;
}

function parseCsv(text) {
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).filter((line) => line.length);
  if (!lines.length) return [];
  const headers = parseCsvLine(lines[0]);
  return lines.slice(1).map((line) => {
    const values = parseCsvLine(line);
    return Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""]));
  });
}

function parseCsvLine(line) {
  const cells = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    const next = line[index + 1];
    if (char === "\"" && quoted && next === "\"") {
      cell += "\"";
      index += 1;
    } else if (char === "\"") {
      quoted = !quoted;
    } else if (char === "," && !quoted) {
      cells.push(cell);
      cell = "";
    } else {
      cell += char;
    }
  }
  cells.push(cell);
  return cells;
}

function toFloat(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return round(number, 6);
}

function firstFloat(row, keys) {
  for (const key of keys) {
    if (key in row) return toFloat(row[key]);
  }
  return null;
}

function boolFromCsv(value) {
  return String(value).trim().toLowerCase() === "true" || String(value).trim() === "1";
}

function shortHemisphere(value) {
  const normalized = String(value).trim().toLowerCase();
  if (normalized.startsWith("left")) return "L";
  if (normalized.startsWith("right")) return "R";
  if (normalized.startsWith("mid")) return "M";
  return value;
}

function sameAxis(a, b) {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

function pairedName(welchName, geometryName) {
  return `${welchName.replace(/\.zip$/i, "")} + ${geometryName.replace(/\.zip$/i, "")}.zip`;
}

function round(value, digits) {
  const factor = 10 ** digits;
  return Math.round(Number(value) * factor) / factor;
}
