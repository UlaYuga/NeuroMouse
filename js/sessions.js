import {
  MAX_SESSIONS,
  SESSION_COLORS,
  computeDelta,
  createSessionStore,
} from "./session-store.js";

export { MAX_SESSIONS, SESSION_COLORS, computeDelta, createSessionStore };

const defaultStore = createSessionStore();

export const addSession = defaultStore.addSession;
export const removeSession = defaultStore.removeSession;
export const toggleSession = defaultStore.toggleSession;
export const getActive = defaultStore.getActive;
export const getSessions = defaultStore.getSessions;
export const onSessionsChange = defaultStore.onSessionsChange;
export const getViewMode = defaultStore.getViewMode;
export const setViewMode = defaultStore.setViewMode;
export const getBaselineId = defaultStore.getBaselineId;
export const setBaseline = defaultStore.setBaseline;
export const getBaselineSession = defaultStore.getBaselineSession;
export const getComparisonSessions = defaultStore.getComparisonSessions;
export const getRenderSessions = defaultStore.getRenderSessions;
