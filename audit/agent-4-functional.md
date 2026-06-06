# Agent 4: Functional Coverage

## 4.1 Playback
- [OK] `state.js` exports the playback API: `getFrame`, `setFrame`, `getIsPlaying`, `setPlaying`, `getPlaybackSpeed`, `setPlaybackSpeed`, `onFrameChange` (`/Users/axel/Documents/SpeedMouse/js/state.js:116-155`).
- [OK] `playback-bar.js` exists and contains a `requestAnimationFrame` loop with start/stop/tick behavior (`/Users/axel/Documents/SpeedMouse/js/views/playback-bar.js:13-15`, `/Users/axel/Documents/SpeedMouse/js/views/playback-bar.js:65-109`).
- [OK] `channel-grid.js` subscribes to `onFrameChange` (`/Users/axel/Documents/SpeedMouse/js/views/channel-grid.js:212-215`).
- [OK] `centroid-view.js` subscribes to `onFrameChange` and draws the playback cursor from the current frame/time (`/Users/axel/Documents/SpeedMouse/js/views/centroid-view.js:159-170`, `/Users/axel/Documents/SpeedMouse/js/views/centroid-view.js:262-268`).
- [OK] `geometry-view.js` subscribes to `onFrameChange` and draws the playback cursor from the current frame/time (`/Users/axel/Documents/SpeedMouse/js/views/geometry-view.js:155-167`, `/Users/axel/Documents/SpeedMouse/js/views/geometry-view.js:244-249`).
- [OK] Speed buttons `1x`, `2x`, `4x` are rendered and handled, and `setPlaybackSpeed` accepts only those values (`/Users/axel/Documents/SpeedMouse/js/views/playback-bar.js:13-15`, `/Users/axel/Documents/SpeedMouse/js/views/playback-bar.js:32-39`, `/Users/axel/Documents/SpeedMouse/js/views/playback-bar.js:121-125`, `/Users/axel/Documents/SpeedMouse/js/state.js:146-150`).

## 4.2 Phase Space
- [OK] `phase-space.js` exists and builds the phase-space panel (`/Users/axel/Documents/SpeedMouse/js/views/phase-space.js:38-89`).
- [OK] Delay Embedding uses the same metric on both axes and pairs `xValues[index]` with `yValues[index + tau]`, which matches `metric[ch][t]` and `metric[ch][t+tau]` (`/Users/axel/Documents/SpeedMouse/js/views/phase-space.js:143-149`, `/Users/axel/Documents/SpeedMouse/js/views/phase-space.js:201-215`, `/Users/axel/Documents/SpeedMouse/js/views/phase-space.js:219-229`).
- [OK] 2-Metric Scatter uses different X/Y metrics when mode is scatter (`/Users/axel/Documents/SpeedMouse/js/views/phase-space.js:111-117`, `/Users/axel/Documents/SpeedMouse/js/views/phase-space.js:143-151`).
- [OK] Tau slider is bounded `min=1`, `max=20`, with default `5` (`/Users/axel/Documents/SpeedMouse/js/views/phase-space.js:62-72`, `/Users/axel/Documents/SpeedMouse/js/views/phase-space.js:91-95`, `/Users/axel/Documents/SpeedMouse/js/views/phase-space.js:119-123`).
- [OK] Playback dot updates through `onFrameChange` and is rendered from `getFrame()` in static mode (`/Users/axel/Documents/SpeedMouse/js/views/phase-space.js:180-199`, `/Users/axel/Documents/SpeedMouse/js/views/phase-space.js:305-330`).
- [OK] `onChannelChange` listener exists (`/Users/axel/Documents/SpeedMouse/js/views/phase-space.js:195-199`).

## 4.3 Monitor
- [OK] `monitor.js` implements the `IDLE -> BUILDING -> TRIGGERED` state machine and reset path (`/Users/axel/Documents/SpeedMouse/js/monitor.js:23-31`, `/Users/axel/Documents/SpeedMouse/js/monitor.js:44-61`, `/Users/axel/Documents/SpeedMouse/js/monitor.js:92-109`).
- [OK] `monitor-view.js` exposes condition builder controls for channel, metric, operator, threshold, and duration (`/Users/axel/Documents/SpeedMouse/js/views/monitor-view.js:31-68`, `/Users/axel/Documents/SpeedMouse/js/views/monitor-view.js:155-186`).
- [OK] CSV export exists via `serializeTriggerLogCSV()` and the export button (`/Users/axel/Documents/SpeedMouse/js/monitor.js:139-149`, `/Users/axel/Documents/SpeedMouse/js/views/monitor-view.js:66-67`, `/Users/axel/Documents/SpeedMouse/js/views/monitor-view.js:192-194`, `/Users/axel/Documents/SpeedMouse/js/views/monitor-view.js:312-320`).
- [OK] Clear Log exists and calls `monitor.clearLog()` (`/Users/axel/Documents/SpeedMouse/js/monitor.js:79-81`, `/Users/axel/Documents/SpeedMouse/js/views/monitor-view.js:66-67`, `/Users/axel/Documents/SpeedMouse/js/views/monitor-view.js:187-191`).
- [OK] Static mode panel state is implemented: the panel starts in `static-mode`, shows a static placeholder, and swaps to the live controls only when live (`/Users/axel/Documents/SpeedMouse/index.html:141-141`, `/Users/axel/Documents/SpeedMouse/js/views/monitor-view.js:27-28`, `/Users/axel/Documents/SpeedMouse/js/views/monitor-view.js:211-214`, `/Users/axel/Documents/SpeedMouse/style.css:838-875`).
- [OK] Trigger log is capped at 50 rows in the rendered view (`/Users/axel/Documents/SpeedMouse/js/views/monitor-view.js:12-13`, `/Users/axel/Documents/SpeedMouse/js/views/monitor-view.js:243-257`).

## 4.4 Multi-Session
- [OK] `sessions.js` exports `addSession`, `removeSession`, `toggleSession`, and `getActive` (`/Users/axel/Documents/SpeedMouse/js/sessions.js:21-63`).
- [OK] Max 6 sessions is enforced by `MAX_SESSIONS` and the add guard (`/Users/axel/Documents/SpeedMouse/js/sessions.js:12-24`).
- [OK] Overlay mode for centroid view is implemented (`/Users/axel/Documents/SpeedMouse/js/views/centroid-view.js:107-117`, `/Users/axel/Documents/SpeedMouse/js/views/centroid-view.js:270-303`).
- [OK] Split mode is implemented for centroid view (`/Users/axel/Documents/SpeedMouse/js/views/centroid-view.js:111-113`, `/Users/axel/Documents/SpeedMouse/js/views/centroid-view.js:305-361`).
- [OK] Delta mode uses `computeDelta()` (`/Users/axel/Documents/SpeedMouse/js/sessions.js:119-172`).
- [OK] Baseline selector exists in the sidebar and is wired to `setBaseline()` (`/Users/axel/Documents/SpeedMouse/index.html:98-101`, `/Users/axel/Documents/SpeedMouse/js/layout.js:252-254`, `/Users/axel/Documents/SpeedMouse/js/layout.js:328-338`).
- [OK] `SESSION_COLORS` has more than 6 colors (`/Users/axel/Documents/SpeedMouse/js/sessions.js:1-10`).
- [OK] Drop zone drag/drop handlers exist for session import (`/Users/axel/Documents/SpeedMouse/js/layout.js:229-246`, `/Users/axel/Documents/SpeedMouse/style.css:434-465`).

## 4.5 Live Engine
- [OK] `js/sources/live-source.js` exists and defines the live source adapter (`/Users/axel/Documents/SpeedMouse/js/sources/live-source.js:32-182`).
- [OK] `js/workers/dsp-worker.js` exists and defines the DSP worker (`/Users/axel/Documents/SpeedMouse/js/workers/dsp-worker.js:1-38`).
- [OK] `RingBuffer` provides both `push()` and `getChannel()` (`/Users/axel/Documents/SpeedMouse/js/sources/live-source.js:278-305`).
- [OK] `fft`, `welchPSD`, and `spectralMetrics` are present, and `spectralMetrics` returns 6 metrics (`/Users/axel/Documents/SpeedMouse/js/workers/dsp-worker.js:40-167`).
- [OK] `onStatus` emits `connecting`, `live`, `error`, and `disconnected` statuses (`/Users/axel/Documents/SpeedMouse/js/sources/live-source.js:75-83`, `/Users/axel/Documents/SpeedMouse/js/sources/live-source.js:103-150`).
- [OK] Connection errors fall back to static replay in `layout.js` (`/Users/axel/Documents/SpeedMouse/js/layout.js:148-166`).

## 4.6 Filter/Sort Controls
- [OK] Frontal/Central/Parietal/Occipital/L/R filter controls are present and wired into `setChannelFilter()`, with the filtered result consumed by both channel grid and centroid view (`/Users/axel/Documents/SpeedMouse/index.html:23-35`, `/Users/axel/Documents/SpeedMouse/js/layout.js:105-111`, `/Users/axel/Documents/SpeedMouse/js/state.js:60-67`, `/Users/axel/Documents/SpeedMouse/js/state.js:158-180`, `/Users/axel/Documents/SpeedMouse/js/views/channel-grid.js:51-53`, `/Users/axel/Documents/SpeedMouse/js/views/centroid-view.js:124-125`).
- [OK] Heatmap sort dropdown includes 10-20 order and alpha power (`/Users/axel/Documents/SpeedMouse/index.html:38-44`, `/Users/axel/Documents/SpeedMouse/js/layout.js:113-115`, `/Users/axel/Documents/SpeedMouse/js/state.js:70-78`).
- [OK] PSD overlay has Log/Linear toggle and the plot respects `getPsdScale()` (`/Users/axel/Documents/SpeedMouse/index.html:47-52`, `/Users/axel/Documents/SpeedMouse/js/state.js:80-88`, `/Users/axel/Documents/SpeedMouse/js/state.js:106-109`, `/Users/axel/Documents/SpeedMouse/js/views/psd-view.js:202-204`, `/Users/axel/Documents/SpeedMouse/js/views/psd-view.js:299-303`, `/Users/axel/Documents/SpeedMouse/js/views/psd-view.js:312-321`).

## Summary
- Critical: 0
- Warning: 0
- OK: 35
