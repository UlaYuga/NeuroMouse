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

function validateData(data) {
  const channels = data?.meta?.channels;
  if (!Array.isArray(channels) || channels.length !== 32) {
    throw new Error("data.json must contain 32 meta.channels entries");
  }
  if (!Array.isArray(data?.welch_psd?.frequencies) || !Array.isArray(data?.welch_psd?.psd)) {
    throw new Error("data.json is missing welch_psd arrays");
  }
  if (!Array.isArray(data?.centroid?.time_relative) || !Array.isArray(data?.centroid?.values)) {
    throw new Error("data.json is missing centroid arrays");
  }
  if (!Array.isArray(data?.geometry?.time)) {
    throw new Error("data.json is missing geometry.time");
  }
}
