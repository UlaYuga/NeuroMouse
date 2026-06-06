import { getBaselineSession, getComparisonSessions, getViewMode } from "../sessions.js";

export function renderSessionLegend(node, fallbackData, options = {}) {
  if (!node) return;
  const sessions = getComparisonSessions(fallbackData);
  const mode = getViewMode();
  const shouldShow = sessions.length > 1 || mode === "delta" || options.force;
  node.hidden = !shouldShow;
  if (!shouldShow) {
    node.innerHTML = "";
    return;
  }

  const baseline = getBaselineSession(fallbackData);
  const suffix = mode === "delta" && baseline ? ` Δ vs ${baseline.name}` : "";
  node.innerHTML = "";
  sessions.forEach((session) => {
    const item = document.createElement("span");
    item.className = "legend-item";
    item.style.setProperty("--session-color", session.color);
    const dot = document.createElement("span");
    dot.className = "legend-dot";
    const name = document.createElement("span");
    name.className = "legend-name";
    name.textContent = `${session.name}${suffix && session.id !== baseline?.id ? suffix : ""}`;
    item.append(dot, name);
    node.append(item);
  });
}
