# Agent 7: UX & Accessibility

## Interactive Labels
- [WARN] `index.html:28-34`, `index.html:50-51`, `index.html:93-95` — segmented text buttons are native `<button>` elements and have visible labels, but the groups are labelled by adjacent `<span>` text rather than explicit ARIA relationships. This is usable, but the filter and PSD overlay segmented groups would be clearer with `role="group"` plus `aria-label` like the session mode group.

Command:
```bash
grep -n "<button\|<select\|<input" index.html | grep -v "aria-label\|id=\|placeholder" || true
```

Output:
```text
28:              <button type="button" class="is-active" data-filter="all">All</button>
29:              <button type="button" data-filter="frontal">Frontal</button>
30:              <button type="button" data-filter="central_temporal">Central</button>
31:              <button type="button" data-filter="parietal">Parietal</button>
32:              <button type="button" data-filter="occipital">Occipital</button>
33:              <button type="button" data-filter="L">L</button>
34:              <button type="button" data-filter="R">R</button>
50:              <button type="button" class="is-active" data-scale="log">Log</button>
51:              <button type="button" data-scale="linear">Linear</button>
93:                <button type="button" class="is-active" data-view-mode="overlay">Overlay</button>
94:                <button type="button" data-view-mode="split">Split</button>
95:                <button type="button" data-view-mode="delta">Delta</button>
```

## Canvas Accessibility
- [OK] `index.html:115-116`, `index.html:128`, `index.html:151` — static canvas elements have `role="img"` and `aria-label`.
- [OK] `js/views/phase-space.js:41-48` — dynamically-created phase-space canvas has `role="img"` and `aria-label`, updated at render time in `js/views/phase-space.js:154`.

Command:
```bash
grep -n "<canvas" index.html
```

Output:
```text
115:            <canvas id="psd-heatmap" class="chart chart-heatmap" width="760" height="420" role="img" aria-label="Welch PSD heatmap by frequency and channel"></canvas>
116:            <canvas id="psd-overlay" class="chart chart-overlay" width="320" height="420" role="img" aria-label="PSD line for the selected channel"></canvas>
128:          <canvas id="centroid-chart" class="chart chart-wide" width="1120" height="300" role="img" aria-label="Spectral centroid lines over time"></canvas>
151:          <canvas id="geometry-chart" class="chart chart-stack" width="820" height="520" role="img" aria-label="Sliding spectral geometry for the selected channel"></canvas>
```

## Keyboard Navigation
- [OK] No `div`/`span` click handlers were found by the requested grep.
- [OK] `js/views/channel-grid.js:127-155` uses SVG groups with `role="button"`, `tabindex="0"`, and Enter/Space keyboard activation for electrode selection.
- [OK] `style.css:264-270` defines visible focus states for native buttons, selects, and inputs; `style.css:1224-1225` adds focus styling for electrodes.

Command:
```bash
grep -rn "onclick\|addEventListener.*click" js/ --include="*.js" | grep "div\|span" || true
```

Output:
```text
(no matches)
```

## Color-only Information
- [OK] `js/views/channel-grid.js:142-143` uses a white/bright ring for the active channel, but `js/views/channel-grid.js:204-205` also includes a legend marker labelled `selected`.
- [OK] `index.html:147` and `js/layout.js:68,83,291` keep selected-channel text in the geometry caption path.
- [WARN] `index.html:161` gives the channel grid only a generic static `aria-label`; it does not expose the currently selected channel as live text near the grid container. Keyboard users still get per-electrode labels, but a nearby `Selected: Cz` style status would make the color/ring state more explicit.

## Mobile / Responsive
- [OK] `style.css:1277` adds a tablet breakpoint.
- [OK] `style.css:1340` adds a mobile breakpoint below 768px.
- [OK] `style.css:1443` honors `prefers-reduced-motion`.

Command:
```bash
grep -n "@media" style.css
```

Output:
```text
1277:@media (max-width: 1120px) {
1340:@media (max-width: 720px) {
1443:@media (prefers-reduced-motion: reduce) {
```

## Font Sizes
- [WARN] `style.css:970` and `style.css:1151` use 9px uppercase mono labels for monitor/phase controls; this is dense but below a comfortable minimum for readable UI text.
- [WARN] `style.css:1211` uses 8px electrode labels in the channel-grid SVG; that is a legibility risk on mobile or lower-DPI displays.

Command:
```bash
grep -n "font-size" style.css | grep -E "[0-9]px" || true
```

Output:
```text
80:  font-size: 13px;
165:  font-size: 19px;
173:  font-size: 11px;
195:  font-size: 11px;
242:  font-size: 12px;
284:  font-size: 12px;
316:  font-size: 12px;
342:  font-size: 10px;
430:  font-size: 10px;
450:  font-size: 12px;
457:  font-size: 10px;
525:  font-size: 11px;
538:  font-size: 16px;
567:  font-size: 11px;
580:  font-size: 10px;
649:  font-size: 10px;
718:  font-size: 12px;
754:  font-size: 11px;
832:  font-size: 11px;
860:  font-size: 10px;
904:  font-size: 11px;
970:  font-size: 9px;
983:  font-size: 11px;
1000:  font-size: 10px;
1026:  font-size: 11px;
1065:  font-size: 10px;
1087:  font-size: 10px;
1123:  font-size: 10px;
1151:  font-size: 9px;
1164:  font-size: 11px;
1179:  font-size: 10px;
1211:  font-size: 8px;
1237:  font-size: 10px;
1251:  font-size: 11px;
1358:    font-size: 18px;
```

## Contrast
- [WARN] `style.css:193`, `style.css:340`, `style.css:353`, `style.css:428`, `style.css:647`, `style.css:968`, `style.css:1149`, `style.css:1235` use `var(--text-tertiary)` for readable labels/captions/readouts. Against `--bg-1: #1C1C1E`, `--text-tertiary: #56565A` is roughly 2.1:1, below WCAG AA for normal text.
- [OK] `style.css:932` uses `--text-tertiary` as a background/decorative value, which is not a readable-text contrast issue.

Command:
```bash
grep -n "text-tertiary" style.css | head -30
```

Output:
```text
12:  --text-tertiary: #56565a;
193:  color: var(--text-tertiary);
340:  color: var(--text-tertiary);
353:  color: var(--text-tertiary);
428:  color: var(--text-tertiary);
455:  color: var(--text-tertiary);
537:  color: var(--text-tertiary);
647:  color: var(--text-tertiary);
858:  color: var(--text-tertiary);
932:  background: var(--text-tertiary);
968:  color: var(--text-tertiary);
998:  color: var(--text-tertiary);
1104:  color: var(--text-tertiary);
1121:  color: var(--text-tertiary);
1149:  color: var(--text-tertiary);
1235:  color: var(--text-tertiary);
```

## Summary
- Critical: 0
- Warning: 5
- OK: 8
