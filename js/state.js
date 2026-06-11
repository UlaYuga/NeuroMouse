import { createViewerState } from "./viewer-state.js";

export { createViewerState };

const defaultState = createViewerState();

export const configureChannels = defaultState.configureChannels;
export const configurePlayback = defaultState.configurePlayback;
export const getChannel = defaultState.getChannel;
export const getChannelIndex = defaultState.getChannelIndex;
export const setChannel = defaultState.setChannel;
export const onChannelChange = defaultState.onChannelChange;
export const getChannelFilter = defaultState.getChannelFilter;
export const setChannelFilter = defaultState.setChannelFilter;
export const getChannelSort = defaultState.getChannelSort;
export const setChannelSort = defaultState.setChannelSort;
export const getPsdScale = defaultState.getPsdScale;
export const setPsdScale = defaultState.setPsdScale;
export const getTimeHover = defaultState.getTimeHover;
export const setTimeHover = defaultState.setTimeHover;
export const onDisplayChange = defaultState.onDisplayChange;
export const onPsdScaleChange = defaultState.onPsdScaleChange;
export const onTimeHoverChange = defaultState.onTimeHoverChange;
export const getFrame = defaultState.getFrame;
export const getTotalFrames = defaultState.getTotalFrames;
export const getIsPlaying = defaultState.getIsPlaying;
export const getPlaybackSpeed = defaultState.getPlaybackSpeed;
export const setFrame = defaultState.setFrame;
export const setPlaying = defaultState.setPlaying;
export const setPlaybackSpeed = defaultState.setPlaybackSpeed;
export const onFrameChange = defaultState.onFrameChange;
export const getVisibleChannels = defaultState.getVisibleChannels;
export const getLiveState = defaultState.getLiveState;
export const updateLiveStatus = defaultState.updateLiveStatus;
export const pushLiveFrame = defaultState.pushLiveFrame;
export const clearLiveHistory = defaultState.clearLiveHistory;
export const onLiveChange = defaultState.onLiveChange;
export const liveMetric = defaultState.liveMetric;
