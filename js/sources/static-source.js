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

export function validateData(data) {
  const channels = data?.meta?.channels;
  if (!Array.isArray(channels) || channels.length === 0) {
    throw new Error("data.json must contain a non-empty meta.channels array");
  }
  const channelCount = channels.length;

  if (!Array.isArray(data?.welch_psd?.frequencies) || !Array.isArray(data?.welch_psd?.psd)) {
    throw new Error("data.json is missing welch_psd arrays");
  }
  if (data.welch_psd.psd.length !== channelCount) {
    throw new Error(`welch_psd.psd has ${data.welch_psd.psd.length} channel rows but meta.channels lists ${channelCount}`);
  }

  if (!Array.isArray(data?.centroid?.time_relative) || !Array.isArray(data?.centroid?.values)) {
    throw new Error("data.json is missing centroid arrays");
  }
  if (data.centroid.values.length !== channelCount) {
    throw new Error(`centroid.values has ${data.centroid.values.length} channel rows but meta.channels lists ${channelCount}`);
  }

  if (!Array.isArray(data?.geometry?.time)) {
    throw new Error("data.json is missing geometry.time");
  }
}
