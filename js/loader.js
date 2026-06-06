let dataCache = null;

export async function loadData() {
  if (dataCache) return dataCache;

  const response = await fetch(new URL("../data/data.json", import.meta.url));
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

export function connectLive(
  url = "ws://127.0.0.1:8766",
  { onFrame, onStatus, onError } = {},
) {
  const ws = new WebSocket(url);

  const status = (message, patch = {}) => {
    onStatus?.({ message, url, ...patch });
  };

  status("Connecting", { connected: false });

  ws.addEventListener("open", () => {
    status("Connected", { connected: true });
    ws.send(JSON.stringify({ type: "get_status" }));
    ws.send(JSON.stringify({ type: "get_latest" }));
  });

  ws.addEventListener("message", (event) => {
    let frame;
    try {
      frame = JSON.parse(event.data);
    } catch (error) {
      onError?.(`Bad live JSON: ${error.message}`);
      return;
    }

    if (frame.type === "bridge_status") {
      status("Bridge status", {
        connected: true,
        bridge: frame,
      });
      return;
    }

    if (frame.type === "bridge_hello") {
      status("Bridge hello", {
        connected: true,
        bridge: frame,
      });
      return;
    }

    if (frame.type === "spectral_analysis") {
      onFrame?.(frame);
      return;
    }

    status(`Ignored ${frame.type || "unknown frame"}`, { connected: true });
  });

  ws.addEventListener("error", () => {
    onError?.("WebSocket error; check that the spectral backend is running on port 8766.");
  });

  ws.addEventListener("close", (event) => {
    status(`Closed code=${event.code}`, { connected: false });
  });

  return {
    close() {
      ws.close();
    },
    socket: ws,
  };
}
