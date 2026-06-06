import { createLiveSource } from "./sources/live-source.js";
import { createStaticSource, loadStaticData } from "./sources/static-source.js";

let activeSource = createStaticSource();

export { createLiveSource, createStaticSource };

export async function loadData() {
  return loadStaticData();
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
