# Agent 8: Regression

Post-fix regression audit.

## Node Syntax Check

```bash
find js/ -name "*.js" | sort | xargs -n1 node --check && echo "ALL OK"
```

Result: `ALL OK`

## CSS Variables
- [OK] Portable CSS variable check returned no undefined variables.

## HTML Imports

```bash
grep -oh 'src="[^"]*\.js"' index.html | sed 's/src="//;s/"//' | while read f; do
  [ -f "$f" ] && echo "OK: $f" || echo "MISSING: $f"
done
```

Result: `OK: ./js/layout.js`

## data.json

```bash
python3 -c "import json; d=json.load(open('data/data.json')); print('data.json OK, channels:', len(d['meta']['channels']))"
```

Result: `data.json OK, channels: 32`

## Tests

```bash
node --test tests/*.test.mjs 2>&1
```

Result: all 7 tests passed.

## Original Views
- [OK] `js/views/psd-view.js` still contains PSD/Welch rendering.
- [OK] `js/views/centroid-view.js` still contains centroid rendering.
- [OK] `js/views/geometry-view.js` still contains geometry rendering.
- [OK] `js/views/channel-grid.js` still contains electrode/10-20 grid rendering.

## ATTRIBUTION.md
- [OK] GX dataset attribution present.
- [OK] soulsyrup1 attribution present.
- [OK] MikMikMiller/NeuroMouse attribution present.

## .gitignore
- [OK] `source-data/` present.
- [OK] `node_modules/` present.
- [OK] `.env` and `.env.*` present.

## Browser Smoke
- [OK] Local browser smoke test at `http://127.0.0.1:8777/` returned no console error/warn entries.
- [OK] Initial page load did not load JSZip.
- [OK] No horizontal page overflow after shell sizing fix.

## Summary
- Critical: 0
- Warning: 0
- OK: 8
