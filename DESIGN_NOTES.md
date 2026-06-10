# Redesign Notes

Hand-off guide for restyling NeuroMouse. The functionality is locked and
test-guarded; this doc says **what is safe to change**, **where the visual layer
actually lives**, and **what not to touch**.

## Run & verify

```bash
npm start            # node server.mjs → http://localhost:8080
node --test tests/*.test.mjs   # 20 tests guard the data/logic layer
```

After any change, load the page, open panels, click **Load Demo Pair**, open
**Preview Report**, and toggle **Advanced Analysis** to confirm nothing broke.

## Safe to restyle (this is the redesign surface)

- **`index.html`** — markup/structure. Two script modules at the end
  (`js/layout.js`, `js/ui-panels.js`) must stay; everything else is layout.
- **`style.css`** — ~2900 lines, fully token-driven from the `:root` block
  (colors, spacing `--s1..`, radii, fonts, shadows). Restyle by editing tokens
  first, then component rules. There is no framework; it is hand-written CSS.

## Visual layer that is NOT in CSS — read this

The canvas/SVG charts draw with values from JavaScript, not CSS:

- **`js/views/chart-utils.js`** is the central plot palette. The 9 main colors
  now resolve from CSS tokens (`--chart-active`, `--chart-grid`, `--chart-bg`,
  …, defined in `style.css :root`). **Change those tokens to recolor every
  chart** — DOM and canvas then share one source of truth.
- Still hardcoded in `chart-utils.js` (data-semantic, change here if needed):
  `FREQUENCY_BANDS` (delta/theta/alpha/beta/gamma fills), `VIRIDIS` (heatmap
  ramp), `DELTA_PALETTE` (diverging delta ramp), `MONO_FONT`.
- Individual view files (`js/views/*.js`) carry some local literals — stroke
  opacities, the channel-grid head-map geometry (`viewBox`/coordinates),
  electrode radii. A full visual overhaul includes a pass over these; grep
  `js/views` for `rgba(` and `#`.

## Do NOT touch (logic/data layer — a redesign should not need to)

- `js/state.js`, `js/sessions.js`, `js/loader.js`, `js/workbench.js`,
  `js/sources/*`, `js/workers/dsp-worker.js` — state, comparison math, import,
  and DSP. Covered by tests. Restyling should not require edits here.
- `server.mjs` — static server + `/api/explain` (Claude integration). Backend
  only.
- `DATA_CONTRACT.md` — the data interface with the Python backend.

## Structure worth reconsidering during the redesign

- **Two import drop zones** exist (`#workbench-drop-zone` and the sidebar
  `#session-drop-zone`); a redesign is a good moment to consolidate to one.
- **Cohort comparison** (the session sidebar: overlay/split/delta) currently
  lives inside the collapsed **Advanced Analysis** section. It is the core
  research value — consider promoting it to a first-class, always-visible mode.
- The **channel grid** renders a 10-20 head map when names match, otherwise a
  generic grid (montage-agnostic) — keep both paths styled.
