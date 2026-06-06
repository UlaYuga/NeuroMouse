# Agent 2: Memory & Performance

## Heatmap Redraws
Warning.
- `drawHeatmap()` is the full redraw path (`js/views/psd-view.js:120-180`), and `render()` calls it every time the view renders (`js/views/psd-view.js:241-245`).
- `psd-view.js` does **not** register `onFrameChange`; the redraw hooks are `onChannelChange`, `onDisplayChange`, `onPsdScaleChange`, `onLiveChange`, `onSessionsChange`, and `observeCanvas` (`js/views/psd-view.js:299-305`).
- Live frames still force redraws because `layout.js` pushes each frame into live state (`js/layout.js:141-147`), and `pushLiveFrame()` notifies `onLiveChange` listeners (`js/state.js:198-208`).
- Hover movement also redraws the entire heatmap (`js/views/psd-view.js:265-292`).
- I did not find any `heatmapDirty`, offscreen canvas, or cached-bitmap path in `js/`; redraws are always immediate and full-canvas.

## JSZip Loading
Warning.
- `index.html` loads JSZip eagerly from the CDN with a classic `<script>` tag in `<head>` (`index.html:10-12`).
- `loader.js` reads `globalThis.JSZip` and throws if it is missing (`js/loader.js:165-171`), so ZIP support is not lazy-loaded.
- Functionally this works, but it makes ZIP parsing part of startup even for users who never import a ZIP.

## History Arrays
OK.
- Live-source history is bounded by `HISTORY_STEPS = 420` (`js/sources/live-source.js:11-12, 413-433`).
- UI live history is also bounded by `MAX_LIVE_HISTORY = 420` (`js/state.js:17-27, 198-207`).
- I do not see an unbounded growth path here; the remaining cost is bounded copy churn from `concat(...).slice(...)` and `shift()` on each frame.

## Worker postMessage Payload
Warning.
- The live source sends `buffers` to the worker every `UPDATE_MS = 250` ms (`js/sources/live-source.js:11-12, 152-162`).
- Each channel buffer is a fresh `Float32Array(this.capacity)` (`js/sources/live-source.js:278-304`), and capacity is `nextPow2(WINDOW_SEC * samplingRate)`; with the defaults that is `1024` samples.
- At 32 channels, the raw request payload is `32 * 1024 * 4 = 131072` bytes, about 128 KiB, per worker update before object overhead.
- No Transferable list is used, so structured clone copies those arrays into the worker instead of transferring ownership.
- The worker response back to main is also clone-heavy because it posts plain arrays/objects (`js/workers/dsp-worker.js:25-31`).

## Session Data Memory
OK.
- Session count is hard-capped at 6 (`js/sessions.js:12-16`).
- `addSession()` stores the parsed dataset directly on the session object (`js/sessions.js:21-38`), so the upper bound is about `6 * 880,679 = 5,284,074` bytes, or about 5.04 MiB, of serialized JSON-equivalent data before parse/heap overhead.
- `removeSession()` splices the session out of the array and updates baseline state (`js/sessions.js:40-47`).
- The delta cache is a `WeakMap` (`js/sessions.js:16, 189-198`), so removed sessions can be garbage-collected once no other references remain.

## Canvas Size vs CSS Size
OK.
- Canvas backing-store sizing is done through `resizeCanvas()`, which reads the CSS box, multiplies by `devicePixelRatio`, and resets `canvas.width`/`canvas.height` when needed (`js/views/chart-utils.js:35-50`).
- The chart canvases have CSS widths/heights defined in the stylesheet (`style.css:660-683`, `1327-1439`), so the logical size and CSS size are intentionally aligned.
- The HTML `width`/`height` attributes are just starting values (`index.html:115-116, 128, 151`); the JS resize path takes over on first render and resize.
- I do not see a steady-state blur problem in the current canvas pipeline.

## data.json Size
OK.
- `wc -c data/data.json` => `880679 data/data.json`
- That is under the 2 MB threshold, so I would not recommend compression or lazy loading for the current file size.

## Summary
- Critical: 0
- Warning: 3
- OK: 4
