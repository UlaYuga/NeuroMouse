import {
  getFrame,
  getIsPlaying,
  getPlaybackSpeed,
  getTotalFrames,
  onFrameChange,
  setFrame,
  setPlaybackSpeed,
  setPlaying,
} from "../state.js";
import { formatNumber } from "./chart-utils.js";

const BASE_FPS = 8;
const SPEEDS = [1, 2, 4];

export function initPlaybackBar(root, data) {
  if (!root) return;

  const times = data.geometry.time;
  root.innerHTML = "";

  const playButton = element("button", {
    type: "button",
    className: "playback-toggle",
    "aria-label": "Play playback",
  }, "Play");
  const speedGroup = element("div", {
    className: "playback-speeds segmented",
    role: "group",
    "aria-label": "Playback speed",
  });
  const speedButtons = SPEEDS.map((speed) => {
    const button = element("button", {
      type: "button",
      "data-speed": String(speed),
    }, `${speed}x`);
    speedGroup.append(button);
    return button;
  });
  const scrubber = element("input", {
    id: "playback-frame",
    name: "playback-frame",
    className: "playback-range",
    type: "range",
    min: "0",
    max: String(getTotalFrames() - 1),
    step: "1",
    value: String(getFrame()),
    "aria-label": "Playback frame",
  });
  const timeLabel = element("output", {
    className: "playback-time",
    htmlFor: scrubber.id,
    "aria-live": "polite",
  });

  root.append(
    element("div", { className: "playback-shell" },
      element("div", { className: "playback-actions" }, playButton, speedGroup),
      scrubber,
      timeLabel,
    ),
  );

  let animationFrame = 0;
  let lastTimestamp = null;

  function stopLoop() {
    if (animationFrame) {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = 0;
    }
    lastTimestamp = null;
  }

  function startLoop() {
    if (animationFrame) return;
    lastTimestamp = null;
    animationFrame = window.requestAnimationFrame(tick);
  }

  function tick(timestamp) {
    if (!getIsPlaying()) {
      stopLoop();
      sync();
      return;
    }

    const speed = getPlaybackSpeed();
    const stepMs = 1000 / (BASE_FPS * speed);
    if (lastTimestamp == null) lastTimestamp = timestamp;
    const elapsed = timestamp - lastTimestamp;

    if (elapsed >= stepMs) {
      const framesToAdvance = Math.max(1, Math.floor(elapsed / stepMs));
      lastTimestamp += framesToAdvance * stepMs;
      const nextFrame = getFrame() + framesToAdvance;
      if (nextFrame >= getTotalFrames() - 1) {
        setFrame(getTotalFrames() - 1);
        setPlaying(false);
        stopLoop();
        sync();
        return;
      }
      setFrame(nextFrame);
    }

    animationFrame = window.requestAnimationFrame(tick);
  }

  playButton.addEventListener("click", () => {
    if (getIsPlaying()) {
      setPlaying(false);
      return;
    }
    if (getFrame() >= getTotalFrames() - 1) setFrame(0);
    setPlaying(true);
    startLoop();
  });

  speedButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setPlaybackSpeed(button.dataset.speed);
    });
  });

  scrubber.addEventListener("input", () => {
    setPlaying(false);
    setFrame(scrubber.value);
  });

  function sync() {
    const frame = getFrame();
    const time = times[Math.min(frame, times.length - 1)] ?? 0;
    scrubber.max = String(getTotalFrames() - 1);
    scrubber.value = String(frame);
    scrubber.style.setProperty("--progress", `${(frame / Math.max(1, getTotalFrames() - 1)) * 100}%`);
    const label = `t = ${formatNumber(time, 2)} s`;
    timeLabel.value = label;
    timeLabel.textContent = label;
    playButton.textContent = getIsPlaying() ? "Pause" : "Play";
    playButton.setAttribute("aria-label", getIsPlaying() ? "Pause playback" : "Play playback");
    speedButtons.forEach((button) => {
      button.classList.toggle("is-active", Number(button.dataset.speed) === getPlaybackSpeed());
    });
  }

  onFrameChange(() => {
    sync();
    if (getIsPlaying()) startLoop();
    else stopLoop();
  });
  sync();
}

function element(name, attrs = {}, ...children) {
  const node = document.createElement(name);
  Object.entries(attrs).forEach(([key, value]) => {
    if (key === "className") node.className = value;
    else if (key === "htmlFor") node.htmlFor = value;
    else node.setAttribute(key, value);
  });
  children.flat().forEach((child) => {
    if (child == null) return;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  });
  return node;
}
