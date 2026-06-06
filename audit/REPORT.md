# SpeedMouse — Audit Report

Generated: 2026-06-06 21:14:23 MSK  
Commit: 442ab09155e75fd01ce9259cc0613a9f3d18f941

## Executive Summary

| Domain | Status | Critical | Warning | OK |
|--------|--------|----------|---------|----|
| Code Quality | 🟡 WARN | 0 | 6 | 13 |
| Memory & Performance | 🟡 WARN | 0 | 3 | 4 |
| Data Integrity | 🟢 PASS | 0 | 0 | 55 |
| Functional Coverage | 🟢 PASS | 0 | 0 | 35 |
| Integration | 🟡 WARN | 0 | 1 | 4 |
| Security & Privacy | 🟡 WARN | 0 | 2 | 6 |
| UX & Accessibility | 🟡 WARN | 0 | 5 | 8 |
| Regression | 🟡 WARN | 0 | 5 | 7 |

Overall: WARN

Scope note: Agents 1-6 completed through mini subagents. Agents 7-8 were attempted through mini subagents after slots freed, but both hit the account usage limit; the main agent completed those two static audits from the same command checklist so the required files are still present.

---

## Critical Issues

None found.

Critical-fix pass result: no runtime code changes were required because all agent reports recorded `Critical: 0`. The specific requested critical classes were checked:

- RAF loops: no uncancelled critical RAF loop found.
- Canvas shadow state: no leaking `shadowBlur` path found.
- Division-by-zero guards: requested DSP/session paths were guarded.
- Live history arrays: both live-source and UI live history are capped at 420.

---

## Warnings

### Agent 1: Code Quality

- `js/views/chart-utils.js:53-67`, `js/views/centroid-view.js:262-268`, `js/views/geometry-view.js:244-249`, `js/views/phase-space.js:196-199`, `js/views/psd-view.js:299-305` — `observeCanvas()` cleanup is returned but not retained by callers; remount/reinit would leave resize observers and RAF bookkeeping alive.
- `js/views/playback-bar.js:148-152` — `onFrameChange()` subscription has no unsubscribe path; repeated initialization would stack RAF starters.
- `js/layout.js:82-95,105-128,229-255,321-322`, `js/views/centroid-view.js:235-268`, `js/views/geometry-view.js:219-249`, `js/views/phase-space.js:97-123,196-199`, `js/views/psd-view.js:265-305`, `js/views/channel-grid.js:149-163,212-216`, `js/views/monitor-view.js:118-129,163-194` — long-lived listeners/subscriptions have no paired dispose path.
- `js/views/centroid-view.js:82-97,363-423`, `js/views/geometry-view.js:79-92,333-415`, `js/views/psd-view.js:120-239,307-376`, `js/views/phase-space.js:133-193,232-372` — scale/tick/axis logic is duplicated across canvas views.
- `js/views/centroid-view.js:270-360` and `js/views/geometry-view.js:251-352` — split/overlay multi-session rendering patterns are duplicated.
- `js/views/psd-view.js:60` — `channelIndexByName` is declared and never read.

### Agent 2: Memory & Performance

- `js/views/psd-view.js:120-180,241-245,265-292,299-305`, `js/layout.js:141-147`, `js/state.js:198-208` — PSD heatmap redraws fully on render, live updates, and hover; no offscreen/dirty cache exists.
- `index.html:10-12`, `js/loader.js:165-171` — JSZip loads eagerly from CDNJS, even when ZIP session import is never used.
- `js/sources/live-source.js:152-162,278-304`, `js/workers/dsp-worker.js:25-31` — live worker payload is about 128 KiB every 250 ms at default 32 channels and uses structured clone rather than Transferable/shared memory.

### Agent 5: Integration

- `js/views/monitor-view.js:17-20,163-186,202-209` — monitor condition channel is local/fixed and does not follow global `setChannel('Oz')`; other views do sync.

### Agent 6: Security & Privacy

- `source-data/` exists locally with `eeg_welch_export.zip` and `spectral_centroid_export.zip`. It is ignored and not tracked, but should stay out of commits and release bundles.
- `index.html:10-12` loads CDNJS resources. This is non-sensitive but remains an external network dependency.

### Agent 7: UX & Accessibility

- `index.html:28-34`, `index.html:50-51`, `index.html:93-95` — segmented controls use visible text buttons, but filter/PSD groups should expose explicit group labels like the session mode group.
- `index.html:161`, `js/views/channel-grid.js:142-143,204-205` — channel grid has visual and legend indication for selection, but no live selected-channel status near the grid container.
- `style.css:970`, `style.css:1151` — 9px uppercase mono labels are below comfortable readable UI size.
- `style.css:1211` — 8px electrode labels are a mobile/low-DPI legibility risk.
- `style.css:193,340,353,428,647,968,1149,1235` — `--text-tertiary` is used for readable text at roughly 2.1:1 contrast on `--bg-1`.

### Agent 8: Regression

- CSS variable check command needs `grep --` or `grep -e` on macOS BSD grep when the pattern starts with `--`; portable rerun found no undefined CSS variables.
- `index.html:12` external JSZip URL is reported as `MISSING` by the local-path HTML import check; expected for CDN, but it is an external runtime dependency.
- `.gitignore` does not include `node_modules/`.
- `.gitignore` does not include `.env`; no current `.env` usage was found.

---

## Verification Snapshot

- `node tools/verify_data.mjs` → `Data Integrity: 55 passed, 0 failed`
- `find js/ -name "*.js" | xargs -n1 node --check` → `ALL OK`
- `node --test tests/*.test.mjs` → `7/7 pass`
- `python3 -c "import json; ..."` → `data.json OK, channels: 32`
- `wc -c data/data.json` → `880679 data/data.json`

---

## Full Agent Reports

- [Agent 1: Code Quality](agent-1-quality.md)
- [Agent 2: Memory & Performance](agent-2-perf.md)
- [Agent 3: Data Integrity](agent-3-data.md)
- [Agent 4: Functional Coverage](agent-4-functional.md)
- [Agent 5: Integration](agent-5-integration.md)
- [Agent 6: Security & Privacy](agent-6-security.md)
- [Agent 7: UX & Accessibility](agent-7-ux.md)
- [Agent 8: Regression](agent-8-regression.md)
