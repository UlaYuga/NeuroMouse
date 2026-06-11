import fc from "fast-check";
import JSZip from "jszip";

import { makeCanonicalData, shapeArb, shapeRepro } from "./data-fixtures.mjs";

const GEOMETRY_FILES = {
  centroid: "sliding_spectral_centroid_wide.csv",
  spread: "sliding_spectral_spread_wide.csv",
  entropy: "sliding_spectral_entropy_wide.csv",
  flatness: "sliding_spectral_flatness_wide.csv",
  edge95: "sliding_spectral_edge95_wide.csv",
  alpha_relative_power: "sliding_alpha_relative_power_wide.csv",
};

export const malformedZipMutations = [
  "empty-zip",
  "random-member-only",
  "zipped-data-json-invalid-shape",
  "zipped-data-json-null-numeric",
  "combined-missing-welch-member",
  "combined-invalid-welch-json",
  "combined-invalid-geometry-json",
  "combined-empty-wide-csv",
  "combined-missing-axis-column",
  "combined-missing-channel-column",
  "combined-mismatched-sliding-time-axis",
  "combined-summary-missing-channel",
  "combined-nan-csv-value",
  "combined-infinity-axis-value",
  "paired-welch-only",
  "paired-geometry-only",
  "paired-mismatched-sliding-time-axis",
];

export const validZipArb = fc.record({
  shape: shapeArb,
  mode: fc.constantFrom("combined", "paired"),
});

export const malformedZipArb = fc.record({
  shape: shapeArb,
  mutation: fc.constantFrom(...malformedZipMutations),
});

export function installJSZipGlobal() {
  globalThis.JSZip = JSZip;
}

export async function makeValidZipFiles({ shape, mode }) {
  const data = makeCanonicalData(shape);
  if (mode === "paired") {
    return [
      await zipToFile(addWelchMembers(new JSZip(), data), "welch.zip"),
      await zipToFile(addGeometryMembers(new JSZip(), data), "geometry.zip"),
    ];
  }
  return [await zipToFile(addGeometryMembers(addWelchMembers(new JSZip(), data), data), "combined.zip")];
}

export async function makeMalformedZipFiles({ shape, mutation }) {
  const data = makeCanonicalData(shape);
  const zip = addGeometryMembers(addWelchMembers(new JSZip(), data), data);

  switch (mutation) {
    case "empty-zip":
      return {
        files: [await zipToFile(new JSZip(), "empty.zip")],
        repro: { mutation },
      };
    case "random-member-only": {
      const random = new JSZip();
      random.file("notes.txt", "not a NeuroMouse archive");
      return {
        files: [await zipToFile(random, "random.zip")],
        repro: { mutation },
      };
    }
    case "zipped-data-json-invalid-shape": {
      const dataZip = new JSZip();
      dataZip.file("nested/data.json", JSON.stringify({ meta: {}, welch_psd: {}, centroid: {}, geometry: {} }));
      return {
        files: [await zipToFile(dataZip, "bad-data-json.zip")],
        repro: { mutation },
      };
    }
    case "zipped-data-json-null-numeric": {
      const dataJson = structuredClone(data);
      dataJson.welch_psd.psd[0][0] = null;
      dataJson.centroid.values[0][0] = null;
      dataJson.geometry.time[0] = null;
      const dataZip = new JSZip();
      dataZip.file("data/data.json", JSON.stringify(dataJson));
      return {
        files: [await zipToFile(dataZip, "null-data-json.zip")],
        repro: { mutation, shape: shapeRepro(shape) },
      };
    }
    case "combined-missing-welch-member":
      zip.remove("welch_psd_wide.csv");
      break;
    case "combined-invalid-welch-json":
      zip.file("eeg_welch_centroid_export.json", "{");
      break;
    case "combined-invalid-geometry-json":
      zip.file("spectral_centroid_geometry_metadata.json", "{");
      break;
    case "combined-empty-wide-csv":
      zip.file("welch_psd_wide.csv", wideCsv("frequency_hz", [], data.meta.channels, []));
      break;
    case "combined-missing-axis-column":
      zip.file("welch_psd_wide.csv", wideCsv("wrong_axis", data.welch_psd.frequencies, data.meta.channels, data.welch_psd.psd));
      break;
    case "combined-missing-channel-column":
      zip.file(
        "spectral_centroid_wide.csv",
        wideCsv("time_relative_sec", data.centroid.time_relative, data.meta.channels.slice(1), data.centroid.values.slice(1)),
      );
      break;
    case "combined-mismatched-sliding-time-axis":
      zip.file(
        GEOMETRY_FILES.spread,
        wideCsv("time_relative_sec", shiftedAxis(data.geometry.time), data.meta.channels, data.geometry.spread),
      );
      break;
    case "combined-summary-missing-channel":
      zip.file("spectral_centroid_channel_summary.csv", channelSummaryCsv(data.channel_summary.slice(1)));
      break;
    case "combined-nan-csv-value": {
      const psd = cloneMatrix(data.welch_psd.psd);
      psd[0][0] = "NaN";
      zip.file("welch_psd_wide.csv", wideCsv("frequency_hz", data.welch_psd.frequencies, data.meta.channels, psd));
      break;
    }
    case "combined-infinity-axis-value": {
      const axis = [...data.geometry.time];
      axis[0] = "Infinity";
      zip.file(GEOMETRY_FILES.centroid, wideCsv("time_relative_sec", axis, data.meta.channels, data.geometry.centroid));
      break;
    }
    case "paired-welch-only":
      return {
        files: [await zipToFile(addWelchMembers(new JSZip(), data), "welch-only.zip")],
        repro: { mutation, shape: shapeRepro(shape) },
      };
    case "paired-geometry-only":
      return {
        files: [await zipToFile(addGeometryMembers(new JSZip(), data), "geometry-only.zip")],
        repro: { mutation, shape: shapeRepro(shape) },
      };
    case "paired-mismatched-sliding-time-axis": {
      const geometryZip = addGeometryMembers(new JSZip(), data);
      geometryZip.file(
        GEOMETRY_FILES.spread,
        wideCsv("time_relative_sec", shiftedAxis(data.geometry.time), data.meta.channels, data.geometry.spread),
      );
      return {
        files: [
          await zipToFile(addWelchMembers(new JSZip(), data), "welch.zip"),
          await zipToFile(geometryZip, "geometry-bad-axis.zip"),
        ],
        repro: { mutation, shape: shapeRepro(shape) },
      };
    }
    default:
      throw new Error(`Unhandled ZIP mutation: ${mutation}`);
  }

  return {
    files: [await zipToFile(zip, `${mutation}.zip`)],
    repro: { mutation, shape: shapeRepro(shape) },
  };
}

function addWelchMembers(zip, data) {
  zip.file("nested/eeg_welch_centroid_export.json", JSON.stringify({
    metadata: {
      channel_names: data.meta.channels,
    },
  }));
  zip.file("welch_psd_wide.csv", wideCsv("frequency_hz", data.welch_psd.frequencies, data.meta.channels, data.welch_psd.psd));
  zip.file("spectral_centroid_wide.csv", wideCsv("time_relative_sec", data.centroid.time_relative, data.meta.channels, data.centroid.values));
  return zip;
}

function addGeometryMembers(zip, data) {
  zip.file("spectral_centroid_geometry_metadata.json", JSON.stringify({
    segment_start_sec: 0,
    segment_end_sec: data.meta.segment_duration_sec,
    analysis_sample_rate_hz: data.meta.sampling_rate_analysis_hz,
    welch_window_sec: data.meta.welch_window_sec,
    welch_overlap: data.meta.welch_overlap_fraction,
    sliding_window_sec: data.meta.sliding_window_sec,
    sliding_step_sec: data.meta.sliding_step_sec,
  }));
  zip.file("spectral_centroid_channel_summary.csv", channelSummaryCsv(data.channel_summary));
  zip.file("mean_psd_area_normalized_wide.csv", wideCsv(
    "frequency_hz",
    data.geometry.area_normalized_psd.frequencies,
    data.meta.channels,
    data.geometry.area_normalized_psd.psd,
  ));

  for (const [key, member] of Object.entries(GEOMETRY_FILES)) {
    zip.file(member, wideCsv("time_relative_sec", data.geometry.time, data.meta.channels, data.geometry[key]));
  }

  return zip;
}

async function zipToFile(zip, name) {
  const bytes = await zip.generateAsync({ type: "uint8array" });
  Object.defineProperties(bytes, {
    name: {
      value: name,
      enumerable: true,
    },
    type: {
      value: "application/zip",
      enumerable: true,
    },
  });
  return bytes;
}

function wideCsv(axisKey, axisValues, channels, rowsByChannel) {
  const lines = [[axisKey, ...channels].map(csvCell).join(",")];
  for (let rowIndex = 0; rowIndex < axisValues.length; rowIndex += 1) {
    const row = [
      axisValues[rowIndex],
      ...channels.map((_, channelIndex) => rowsByChannel[channelIndex]?.[rowIndex] ?? ""),
    ];
    lines.push(row.map(csvCell).join(","));
  }
  return `${lines.join("\n")}\n`;
}

function channelSummaryCsv(rows) {
  const headers = [
    "channel",
    "hemisphere",
    "region",
    "has_clear_alpha_peak",
    "alpha_relative_power",
    "spectral_centroid_hz",
    "spectral_spread_hz",
    "spectral_entropy",
    "spectral_flatness",
    "edge95_hz",
    "alpha_peak_frequency_hz",
    "sliding_alpha_relative_mean",
  ];
  const lines = [headers.join(",")];
  for (const row of rows) {
    lines.push(headers.map((header) => csvCell(row[header])).join(","));
  }
  return `${lines.join("\n")}\n`;
}

function csvCell(value) {
  const text = String(value ?? "");
  if (/[",\n\r]/.test(text)) {
    return `"${text.replaceAll("\"", "\"\"")}"`;
  }
  return text;
}

function shiftedAxis(axis) {
  const copy = [...axis];
  copy[copy.length - 1] += 0.125;
  return copy;
}

function cloneMatrix(matrix) {
  return matrix.map((row) => [...row]);
}
