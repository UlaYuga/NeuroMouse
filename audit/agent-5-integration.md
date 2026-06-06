# Agent 5: Integration

## Import Graph
- I built the graph from `js/**/*.js` with relative-path resolution and query-string normalization.
- Result: no missing relative import paths, no cycles, and no orphaned app modules.
- `js/layout.js` is the only `js/` node with no inbound static imports, which is expected because it is loaded from the HTML entrypoint at `index.html:187`.
- The worker is not a dead file: `js/sources/live-source.js:105` reaches `js/workers/dsp-worker.js` through `new Worker(new URL(...))`, so it is a dynamic runtime entrypoint rather than an orphan.

Evidence:
- `index.html:187` loads `./js/layout.js?v=grid-legend-20260606`
- `js/layout.js:1-36` imports the full app graph
- `js/sources/live-source.js:105` binds the DSP worker

## Live -> Monitor Pipeline
- The live ingest path is intact:
  - `js/sources/live-source.js:129-140` parses each WebSocket payload and pushes every sample into `ringBuffer`.
  - `js/sources/live-source.js:152-163` posts a compute job to the worker every 250 ms when the buffer is ready and no compute is pending.
  - `js/workers/dsp-worker.js:1-38` receives the job and returns the PSD/metrics result.
  - `js/sources/live-source.js:184-196` builds `liveData`, appends it to history, and then returns it to the callback.
  - `js/sources/live-source.js:237-274` includes the live geometry, channel summary, PSD, and timestamps that downstream views need.
- Layout forwards that frame correctly:
  - `js/layout.js:141-147` calls `pushLiveFrame(frame)` and `monitorView?.handleFrame(frame)` on every frame.
  - `js/state.js:198-224` stores live state and notifies live listeners.
- The monitor itself is wired:
  - `js/views/monitor-view.js:146-152` extracts the current metric/time from the frame and calls `monitor.update(...)`.
  - `js/monitor.js:33-62` is the condition state machine.
  - `js/monitor.js:92-109` emits trigger events to listeners.
  - `js/views/monitor-view.js:118-129` listens for those trigger events and rerenders the log/status.
- No runtime break found in this pipeline.

## Sessions -> Views Pipeline
- Session creation and fanout are correct:
  - `js/layout.js:267-275` calls `addSession(...)` for each uploaded dataset.
  - `js/sessions.js:21-38` pushes the session into the store and emits change notifications.
  - `js/layout.js:91-95` subscribes to session changes and reruns sidebar/state sync.
- The view layer consumes active sessions through the comparison helpers:
  - `js/sessions.js:61-63` defines the active-session filter.
  - `js/sessions.js:99-117` and `js/sessions.js:174-187` route renderers through `getActive()` and the fallback baseline session.
  - `js/views/centroid-view.js:107-117` and `js/views/centroid-view.js:270-303` draw session overlays from the active comparison set.
  - `js/views/geometry-view.js:95-106` and `js/views/geometry-view.js:251-296` do the same for geometry overlays.
  - `js/views/psd-view.js:241-245` and `js/views/psd-view.js:307-345` redraw the PSD overlay from the active sessions.
  - `js/views/session-legend.js:3-28` renders the same comparison set and baseline suffix.
- No break found in the session fanout path.

## State Channel Sync
- Global channel changes propagate where expected:
  - `js/state.js:49-57` updates the selected channel and notifies `onChannelChange` listeners.
  - `js/views/geometry-view.js:244-249`, `js/views/centroid-view.js:262-268`, `js/views/channel-grid.js:212-217`, and `js/views/phase-space.js:196-199` all subscribe and rerender on channel change.
  - `js/views/channel-grid.js:38-75` and `js/views/channel-grid.js:116-165` highlight the current channel and redraw the grid from `getChannel()`.
- The monitor condition channel is fixed/local, not globally synced:
  - `js/views/monitor-view.js:17-20` seeds its own condition channel.
  - `js/views/monitor-view.js:163-186` only changes that channel from the monitor dropdown.
  - `js/views/monitor-view.js:202-209` only repairs invalid channels after a data-channel change; it does not listen to `onChannelChange`.
- Result: `setChannel('Oz')` will rerender geometry, centroid, phase space, and channel grid for Oz, but the monitor condition channel stays on whatever the monitor UI last selected. That is a fixed/local control, not a global sync.

## layout.js Initialization
- `js/layout.js:74-80` initializes every requested view module:
  - `initPsdView`
  - `initCentroidView`
  - `initPlaybackBar`
  - `initMonitorView`
  - `initGeometryView`
  - `initChannelGrid`
  - `initPhaseSpace`
- `js/layout.js:91-95` also attaches the session-change listener that keeps the sidebar and playback/channel state coherent.
- The modules that do not expose `init*` exports are helper/store modules by design: `state.js`, `sessions.js`, `loader.js`, `monitor.js`, `chart-utils.js`, `session-legend.js`, and the worker.

## Summary
- Critical: 0
- Warning: 1
- OK: 4
