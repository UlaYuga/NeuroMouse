# Agent 1: Code Quality

## RAF Loops
- [OK] `js/views/chart-utils.js:53-67` `observeCanvas()` cancels the pending frame before re-requesting and cancels again in its teardown path.
- [OK] `js/views/playback-bar.js:68-109` the playback RAF stops on pause, on reaching the end, and when frame state changes.
- [WARN] `js/views/chart-utils.js:53-67`, `js/views/centroid-view.js:262-268`, `js/views/geometry-view.js:244-249`, `js/views/phase-space.js:196-199`, `js/views/psd-view.js:299-305` the cleanup returned by `observeCanvas()` is never retained by callers, so a remount/reinit path would leave the observer and its RAF bookkeeping alive.
- [WARN] `js/views/playback-bar.js:148-152` the `onFrameChange()` subscription is never unsubscribed, so repeated initialization would stack more RAF starters.
- [OK] `js/sources/live-source.js:152-181` the polling interval is cleared in `stop()`, alongside websocket close and worker termination.

## Event Listeners
- [WARN] `js/layout.js:82-95,105-128,229-255,321-322`, `js/views/centroid-view.js:235-268`, `js/views/geometry-view.js:219-249`, `js/views/phase-space.js:97-123,196-199`, `js/views/psd-view.js:265-305`, `js/views/channel-grid.js:149-163,212-216`, `js/views/monitor-view.js:118-129,163-194` register long-lived listeners/subscriptions without any paired unsubscribe or dispose path. That is fine for the current one-time bootstrap, but it is duplicate-risk if any of these modules are reinitialized.
- [OK] The per-node DOM listeners inside the init functions are attached to freshly created elements, so they are not a leak on their own as long as the view is mounted once.

## setInterval / setTimeout
- [OK] `js/sources/live-source.js:152-181` clears the recurring `setInterval()` before stopping the source.
- [OK] `js/monitor.js:104-108` clears the auto-reset timeout in `reset()`, so the monitor timer cannot outlive the state machine.
- [OK] `js/views/monitor-view.js:118-129` uses a one-shot UI timeout under 2s for the trigger highlight; that fits the requested exception scope.

## Canvas Shadow State
- [OK] `js/views/chart-utils.js:202-224` restores context state after the active glow stroke, so `shadowColor`/`shadowBlur` do not leak.
- [OK] `js/views/phase-space.js:291-330` resets `shadowBlur` before restore on both glow dots.

## ctx.save / ctx.restore Balance
- [OK] `js/views/chart-utils.js:184-225`, `js/views/centroid-view.js:162-170`, `js/views/geometry-view.js:158-166`, `js/views/phase-space.js:251-371` are balanced in the inspected canvas paths.

## Duplicated Logic
- [WARN] `js/views/centroid-view.js:82-97,363-423`, `js/views/geometry-view.js:79-92,333-415`, `js/views/psd-view.js:120-239,307-376`, `js/views/phase-space.js:133-193,232-372` each reimplement scale construction, tick drawing, and axis shell logic in slightly different forms.
- [WARN] `js/views/centroid-view.js:270-360` and `js/views/geometry-view.js:251-352` duplicate the split/overlay multi-session rendering pattern, which makes future changes easy to drift.

## Dead Code
- [WARN] `js/views/psd-view.js:60` `channelIndexByName` is declared and never read after initialization.

## Potential NaN Paths
- [OK] `js/workers/dsp-worker.js:74-108` guards the Welch PSD accumulation with a positive sample check and a `count` floor.
- [OK] `js/workers/dsp-worker.js:125-153` guards `sumPower` and uses the normalized spectrum safely for centroid/spread/entropy/flatness.
- [OK] `js/sessions.js:119-210` protects delta math with `safeNumber()` and guarded baseline lookup.
- [OK] `js/sources/live-source.js:278-305` keeps `RingBuffer` capacity positive and modulo math bounded under normal creation.

## Module Sizes
- `js/layout.js` 379
- `js/loader.js` 391
- `js/monitor.js` 154
- `js/sessions.js` 225
- `js/sources/live-source.js` 463 *split candidate*
- `js/sources/static-source.js` 44
- `js/state.js` 267
- `js/views/centroid-view.js` 437 *split candidate*
- `js/views/channel-grid.js` 234
- `js/views/chart-utils.js` 253
- `js/views/geometry-view.js` 428 *split candidate*
- `js/views/monitor-view.js` 337
- `js/views/phase-space.js` 413 *split candidate*
- `js/views/playback-bar.js` 168
- `js/views/psd-view.js` 408 *split candidate*
- `js/views/session-legend.js` 29
- `js/workers/dsp-worker.js` 167

## Summary
- Critical: 0
- Warning: 6
- OK: 13

Commands used: `rg --files js`, `rg -n` over listener/RAF/shadow/math patterns, and `nl -ba` on the relevant modules.
