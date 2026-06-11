export const SESSION_COLORS = [
  "#00D4A0",
  "#0A84FF",
  "#FF9F0A",
  "#FF453A",
  "#BF5AF2",
  "#64D2FF",
  "#30D158",
  "#FF375F",
];

export const MAX_SESSIONS = 6;

export function createSessionStore({
  now = () => Date.now(),
  random = () => Math.random(),
} = {}) {
  const listeners = new Set();
  const sessions = [];
  const deltaCache = new WeakMap();
  let viewMode = "overlay";
  let baselineId = null;

  const api = {
    addSession(name, data) {
      if (sessions.some((session) => session.name === name)) {
        throw new Error(`${name} is already loaded`);
      }
      if (sessions.length >= MAX_SESSIONS) {
        throw new Error(`Maximum ${MAX_SESSIONS} sessions`);
      }

      const session = {
        id: `session_${now()}_${random().toString(36).slice(2, 8)}`,
        name,
        color: nextColor(sessions),
        data,
        active: true,
      };

      sessions.push(session);
      if (!baselineId) baselineId = session.id;
      emit(listeners);
      return session;
    },

    removeSession(id) {
      const index = sessions.findIndex((session) => session.id === id);
      if (index < 0) return;
      sessions.splice(index, 1);
      if (baselineId === id) {
        baselineId = sessions.find((session) => session.active)?.id ?? sessions[0]?.id ?? null;
      }
      emit(listeners);
    },

    toggleSession(id) {
      const session = sessions.find((item) => item.id === id);
      if (!session) return;
      session.active = !session.active;
      if (session.active && !baselineId) baselineId = session.id;
      if (!session.active && baselineId === id) {
        baselineId = sessions.find((item) => item.active)?.id ?? session.id;
      }
      emit(listeners);
    },

    getActive() {
      return sessions.filter((session) => session.active);
    },

    getSessions() {
      return sessions;
    },

    onSessionsChange(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },

    getViewMode() {
      return viewMode;
    },

    setViewMode(mode) {
      if (!["overlay", "split", "delta"].includes(mode) || mode === viewMode) return;
      viewMode = mode;
      emit(listeners);
    },

    getBaselineId() {
      return baselineId;
    },

    setBaseline(id) {
      if (!sessions.some((session) => session.id === id) || id === baselineId) return;
      baselineId = id;
      emit(listeners);
    },

    getBaselineSession(fallbackData = null) {
      const active = comparisonSessions(sessions, fallbackData);
      return active.find((session) => session.id === baselineId) ?? active[0] ?? null;
    },

    getComparisonSessions(fallbackData = null) {
      return comparisonSessions(sessions, fallbackData);
    },

    getRenderSessions(fallbackData = null) {
      const active = comparisonSessions(sessions, fallbackData);
      if (viewMode !== "delta") return active;

      const baseline = api.getBaselineSession(fallbackData);
      if (!baseline) return [];

      return active.map((session) => ({
        ...session,
        data: getDeltaData(deltaCache, session.data, baseline.data),
        deltaSource: session,
        baselineName: baseline.name,
        isDelta: true,
      }));
    },

    computeDelta,
  };

  return api;
}

export function computeDelta(sessionData, baselineData) {
  const geometryKeys = [
    "centroid",
    "spread",
    "entropy",
    "flatness",
    "edge95",
    "alpha_relative_power",
  ].filter((key) => sessionData.geometry[key] && baselineData.geometry[key]);
  if (sessionData.geometry.higuchi_fd && baselineData.geometry.higuchi_fd) {
    geometryKeys.push("higuchi_fd");
  }

  const geometry = {
    time: sessionData.geometry.time.slice(),
  };

  for (const key of geometryKeys) {
    geometry[key] = matrixDifference(sessionData.geometry[key], baselineData.geometry[key], 0);
  }

  if (sessionData.geometry.area_normalized_psd && baselineData.geometry.area_normalized_psd) {
    geometry.area_normalized_psd = {
      frequencies: sessionData.geometry.area_normalized_psd.frequencies.slice(),
      psd: ratioMatrix(sessionData.geometry.area_normalized_psd.psd, baselineData.geometry.area_normalized_psd.psd),
    };
  }

  return {
    meta: {
      ...sessionData.meta,
      delta_baseline: baselineData.meta?.source_files ?? null,
    },
    welch_psd: {
      frequencies: sessionData.welch_psd.frequencies.slice(),
      psd: ratioMatrix(sessionData.welch_psd.psd, baselineData.welch_psd.psd),
    },
    centroid: {
      time_relative: sessionData.centroid.time_relative.slice(),
      values: matrixDifference(sessionData.centroid.values, baselineData.centroid.values, 0),
    },
    geometry,
    channel_summary: sessionData.channel_summary.map((channel, index) => {
      const baseline = baselineData.channel_summary[index] ?? {};
      return {
        ...channel,
        alpha_relative_power: safeNumber(channel.alpha_relative_power) - safeNumber(baseline.alpha_relative_power),
        spectral_centroid_hz: safeNumber(channel.spectral_centroid_hz) - safeNumber(baseline.spectral_centroid_hz),
        spectral_spread_hz: safeNumber(channel.spectral_spread_hz) - safeNumber(baseline.spectral_spread_hz),
        spectral_entropy: safeNumber(channel.spectral_entropy) - safeNumber(baseline.spectral_entropy),
        spectral_flatness: safeNumber(channel.spectral_flatness) - safeNumber(baseline.spectral_flatness),
        edge95_hz: safeNumber(channel.edge95_hz) - safeNumber(baseline.edge95_hz),
        sliding_alpha_relative_mean: safeNumber(channel.sliding_alpha_relative_mean) - safeNumber(baseline.sliding_alpha_relative_mean),
      };
    }),
  };
}

function comparisonSessions(sessions, fallbackData) {
  const active = sessions.filter((session) => session.active);
  if (active.length) return active;
  if (sessions.length) return [];
  if (!fallbackData) return [];
  return [{
    id: "default",
    name: "data.json",
    color: SESSION_COLORS[0],
    data: fallbackData,
    active: true,
    isDefault: true,
  }];
}

function getDeltaData(deltaCache, sessionData, baselineData) {
  let byBaseline = deltaCache.get(sessionData);
  if (!byBaseline) {
    byBaseline = new WeakMap();
    deltaCache.set(sessionData, byBaseline);
  }
  if (!byBaseline.has(baselineData)) {
    byBaseline.set(baselineData, computeDelta(sessionData, baselineData));
  }
  return byBaseline.get(baselineData);
}

function matrixDifference(values, baselineValues, missingValue) {
  return values.map((row, rowIndex) => row.map((value, valueIndex) => (
    safeNumber(value, missingValue) - safeNumber(baselineValues?.[rowIndex]?.[valueIndex], missingValue)
  )));
}

function ratioMatrix(values, baselineValues) {
  return values.map((row, rowIndex) => row.map((value, valueIndex) => (
    Math.log10(Math.max(safeNumber(value, 1e-10), 1e-10) / Math.max(safeNumber(baselineValues?.[rowIndex]?.[valueIndex], 1e-10), 1e-10))
  )));
}

function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function nextColor(sessions) {
  const used = new Set(sessions.map((session) => session.color));
  return SESSION_COLORS.find((color) => !used.has(color)) ?? SESSION_COLORS[sessions.length % SESSION_COLORS.length];
}

function emit(listeners) {
  listeners.forEach((fn) => fn());
}
