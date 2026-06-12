let dataCache = null;

export function createStaticSource() {
  return {
    meta() {
      return dataCache?.meta ?? null;
    },
    async start(onFrame, onStatus) {
      onStatus?.("static");
      onFrame?.(await loadStaticData());
    },
    stop() {},
  };
}

export async function loadStaticData() {
  if (dataCache) return dataCache;

  const response = await fetch(new URL("../../data/data.json", import.meta.url));
  if (!response.ok) {
    throw new Error(`Failed to load data.json: HTTP ${response.status}`);
  }

  const data = await response.json();
  validateData(data);
  dataCache = data;
  return dataCache;
}

export function validateData(data, { maxChannels = 4096 } = {}) {
  const isPositiveInteger = (value) => Number.isInteger(value) && value > 0;
  const requireFiniteNumbers = (values, message) => {
    for (const value of values) {
      if (!Number.isFinite(value)) {
        throw new Error(message);
      }
    }
  };
  const requireMatrixRows = (rows, expectedWidth, label, widthLabel) => {
    rows.forEach((row, index) => {
      if (!Array.isArray(row)) {
        throw new Error(`${label} row ${index} must be an array`);
      }
      if (row.length !== expectedWidth) {
        throw new Error(`${label} row ${index} length must equal ${widthLabel}`);
      }
      requireFiniteNumbers(row, `${label} row ${index} must contain only finite numbers`);
    });
  };

  if (!isPositiveInteger(maxChannels)) {
    throw new Error("maxChannels must be a positive integer");
  }

  const channels = data?.meta?.channels;
  if (!Array.isArray(channels) || channels.length === 0) {
    throw new Error("data.json must contain a non-empty meta.channels array");
  }
  const channelCount = channels.length;
  if (channelCount > maxChannels) {
    throw new Error(`meta.channels length must be at most ${maxChannels}`);
  }

  if (Object.hasOwn(data.meta, "n_channels")) {
    const declaredChannelCount = data.meta.n_channels;
    if (!isPositiveInteger(declaredChannelCount)) {
      throw new Error("meta.n_channels must be a positive integer");
    }
    if (declaredChannelCount !== channelCount) {
      throw new Error("meta.n_channels must equal meta.channels length");
    }
  }

  if (!Array.isArray(data?.welch_psd?.frequencies) || !Array.isArray(data?.welch_psd?.psd)) {
    throw new Error("data.json is missing welch_psd arrays");
  }
  if (data.welch_psd.frequencies.length === 0) {
    throw new Error("welch_psd.frequencies must be a non-empty array");
  }
  requireFiniteNumbers(
    data.welch_psd.frequencies,
    "welch_psd.frequencies must contain only finite numbers",
  );
  if (data.welch_psd.psd.length !== channelCount) {
    throw new Error(`welch_psd.psd has ${data.welch_psd.psd.length} channel rows but meta.channels lists ${channelCount}`);
  }
  requireMatrixRows(
    data.welch_psd.psd,
    data.welch_psd.frequencies.length,
    "welch_psd.psd",
    "welch_psd.frequencies length",
  );

  if (!Array.isArray(data?.centroid?.time_relative) || !Array.isArray(data?.centroid?.values)) {
    throw new Error("data.json is missing centroid arrays");
  }
  if (data.centroid.time_relative.length === 0) {
    throw new Error("centroid.time_relative must be a non-empty array");
  }
  if (data.centroid.values.length !== channelCount) {
    throw new Error(`centroid.values has ${data.centroid.values.length} channel rows but meta.channels lists ${channelCount}`);
  }
  requireMatrixRows(
    data.centroid.values,
    data.centroid.time_relative.length,
    "centroid.values",
    "centroid.time_relative length",
  );

  if (!Array.isArray(data?.geometry?.time)) {
    throw new Error("data.json is missing geometry.time");
  }
  if (data.geometry.time.length === 0) {
    throw new Error("geometry.time must be a non-empty array");
  }
  requireFiniteNumbers(
    data.geometry.time,
    "geometry.time must contain only finite numbers",
  );

  if (Object.hasOwn(data, "mea")) {
    if (!data.mea || typeof data.mea !== "object") {
      throw new Error("mea must be an object when present");
    }
    if (typeof data.mea.sampling_rate_hz !== "number" || !Number.isFinite(data.mea.sampling_rate_hz) || data.mea.sampling_rate_hz <= 0) {
      throw new Error("mea.sampling_rate_hz must be a positive number");
    }
    if (!Array.isArray(data.mea.traces) || data.mea.traces.length === 0) {
      throw new Error("mea.traces must be a non-empty array when present");
    }
    if (!Array.isArray(data.mea.traces[0]) || data.mea.traces[0].length === 0) {
      throw new Error("mea.traces[0] must be a non-empty array");
    }
    const meaHasSamples = Object.hasOwn(data.mea, "n_samples");
    let expectedTraceWidth = data.mea.traces[0]?.length;
    if (meaHasSamples) {
      if (!isPositiveInteger(data.mea.n_samples)) {
        throw new Error("mea.n_samples must be a positive integer");
      }
      expectedTraceWidth = data.mea.n_samples;
    }
    requireMatrixRows(
      data.mea.traces,
      expectedTraceWidth,
      "mea.traces",
      meaHasSamples ? "mea.n_samples" : "trace length",
    );
    if (data.mea.traces.length !== channelCount) {
      throw new Error(`mea.traces has ${data.mea.traces.length} channel rows but meta.channels lists ${channelCount}`);
    }
  }
}
