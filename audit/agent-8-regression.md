# Agent 8: Regression

## 8.1 Node syntax check — all JS files

Command:
```bash
find js/ -name "*.js" | xargs -n1 node --check && echo "ALL OK" || echo "SYNTAX ERROR"
```

Output:
```text
ALL OK
```

Finding:
- [OK] All JavaScript files parse successfully under `node --check`.

## 8.2 CSS variables — all defined

Original command:
```bash
grep -oh "var(--[a-z0-9-]*)" style.css | sort | uniq > /tmp/used_vars.txt
grep -oh "--[a-z0-9-]*:" style.css | sort | uniq | sed 's/://' > /tmp/defined_vars.txt
comm -23 <(sort /tmp/used_vars.txt | sed 's/var(//;s/)//') <(sort /tmp/defined_vars.txt) > /tmp/undefined_vars.txt
cat /tmp/undefined_vars.txt
```

Original output on macOS BSD grep:
```text
grep: unrecognized option `--[a-z0-9-]*:'
usage: grep [-abcdDEFGHhIiJLlMmnOopqRSsUVvwXxZz] [-A num] [-B num] [-C[num]]
	[-e pattern] [-f file] [--binary-files=value] [--color=when]
	[--context[=num]] [--directories=action] [--label] [--line-buffered]
	[--null] [pattern] [file ...]
--accent
--accent-blue
--accent-blue-dim
--accent-bright
--accent-dim
--accent-glow
--bg-0
--bg-1
--bg-2
--bg-3
--bg-vibrancy
--border
--border-accent
--border-strong
--danger
--ease
--font
--font-mono
--r-btn
--r-card
--r-pill
--r-tag
--s1
--s2
--s3
--s4
--s5
--shadow-lg
--shadow-md
--shadow-sm
--shadow-xs
--t-fast
--t-normal
--text-mono
--text-primary
--text-secondary
--text-tertiary
```

Portable rerun:
```bash
grep -oh -- "var(--[a-z0-9-]*)" style.css | sort | uniq > /tmp/used_vars.txt
grep -oh -- "--[a-z0-9-]*:" style.css | sort | uniq | sed 's/://' > /tmp/defined_vars.txt
comm -23 <(sort /tmp/used_vars.txt | sed 's/var(//;s/)//') <(sort /tmp/defined_vars.txt) > /tmp/undefined_vars.txt
cat /tmp/undefined_vars.txt
```

Portable rerun output:
```text
(no undefined variables)
```

Finding:
- [OK] No undefined CSS variables after rerunning with `grep --` to avoid BSD grep treating `--...` as an option.
- [WARN] The original command is not portable on this macOS host without `grep --` or `grep -e`.

## 8.3 HTML imports — all paths exist

Command:
```bash
grep -oh 'src="[^"]*\.js"' index.html | sed 's/src="//;s/"//' | while read f; do
  [ -f "$f" ] && echo "OK: $f" || echo "MISSING: $f"
done
```

Output:
```text
MISSING: https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js
```

Finding:
- [WARN] `index.html:12` loads JSZip from CDNJS. The check reports it as `MISSING` because it tests URLs as local file paths. This is expected for an external script, but it is still an external runtime dependency.
- [OK] The module entrypoint `index.html:187` is `type="module"` and therefore is not matched by this classic `src="*.js"` grep; it exists at `js/layout.js`.

## 8.4 data.json доступен

Command:
```bash
python3 -c "import json; d=json.load(open('data/data.json')); print('data.json OK, channels:', len(d['meta']['channels']))"
```

Output:
```text
data.json OK, channels: 32
```

Finding:
- [OK] `data/data.json` parses and contains 32 channels.

## 8.5 Tests

Command:
```bash
node --test tests/*.test.mjs 2>&1
```

Output:
```text
✔ evaluate supports threshold comparison operators (0.405959ms)
✔ monitor builds progress, triggers after duration, and logs event (0.408542ms)
✔ monitor resets to idle when condition breaks before duration (0.065667ms)
✔ disabled monitor does not change state or log (0.048416ms)
✔ serializeTriggerLogCSV emits header and escaped trigger rows (0.142333ms)
✔ computeDelta returns zero arrays for identical datasets (5.642958ms)
✔ session store caps datasets at six with unique colors (0.253833ms)
ℹ tests 7
ℹ suites 0
ℹ pass 7
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 47.976625
```

Finding:
- [OK] Current test suite passes: 7/7.

## 8.6 Оригинальные 4 вью — код присутствует

Command:
```bash
grep -l "welch_psd\|PSD" js/views/psd-view.js && echo "psd-view OK"
grep -l "centroid" js/views/centroid-view.js && echo "centroid-view OK"
grep -l "geometry" js/views/geometry-view.js && echo "geometry-view OK"
grep -l "electrode\|EEG_10_20" js/views/channel-grid.js && echo "channel-grid OK"
```

Output:
```text
js/views/psd-view.js
psd-view OK
js/views/centroid-view.js
centroid-view OK
js/views/geometry-view.js
geometry-view OK
js/views/channel-grid.js
channel-grid OK
```

Finding:
- [OK] The original four view modules still contain their expected key code.

## 8.7 ATTRIBUTION.md корректен

Command:
```bash
cat ATTRIBUTION.md
```

Output:
```text
# Attribution

EEG data: GX dataset by Gebodh/CCNY (CC BY-SA 4.0)  
https://zenodo.org/records/15572614

Spectral analysis: soulsyrup1/Complete-Neural-Signal-Analysis  
CC BY-SA 4.0, Synthetic Intelligence Labs  
https://github.com/soulsyrup1/Complete-Neural-Signal-Analysis

Visualization: MikMikMiller/SpeedMouse  
CC BY-SA 4.0  
https://github.com/MikMikMiller/SpeedMouse
```

Finding:
- [OK] GX dataset, `soulsyrup1/Complete-Neural-Signal-Analysis`, and `MikMikMiller/SpeedMouse` links are present.

## 8.8 .gitignore корректен

Command:
```bash
cat .gitignore
```

Output:
```text
source-data/
.DS_Store
__pycache__/
*.pyc
```

Finding:
- [OK] `source-data/` is ignored.
- [WARN] `.gitignore` does not include `node_modules/`.
- [WARN] `.gitignore` does not include `.env`; no current `.env` usage was found in the searched repo surfaces, so this is hygiene rather than an active leak.

## Summary
- Critical: 0
- Warning: 5
- OK: 7
