# Agent 6: Security & Privacy

## 1) Absolute paths
- Command: `grep -rn "/Users/\|/home/\|C:\\\\" js/ index.html style.css || true`
- Match count: 0
- Output:
```text
(no matches)
```

## 2) API keys, tokens
- Command: `grep -rn "api[_-]key\|apikey\|secret\|password\|token\|bearer" js/ --include="*.js" -i || true`
- Match count: 0
- Output:
```text
(no matches)
```

## 3) console.log with data
- Command: `grep -rn "console\.log" js/ --include="*.js" || true`
- Match count: 0
- Output:
```text
(no matches)
```

## 4) Hardcoded URLs except ws://localhost
- Command: `grep -rn "http://\|https://" js/ --include="*.js" | grep -v "cdnjs\|localhost\|127.0.0" || true`
- Match count: 1
- Output:
```text
js/views/channel-grid.js:229:  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
```
- Classification: OK. This is an SVG namespace URL string, not an external network endpoint.

## 5) source-data in .gitignore
- Command: `cat .gitignore | grep source-data || true`
- Match count: 1
- Output:
```text
source-data/
```

## 6) Files that should not be in repo
- Command: `ls source-data/ 2>/dev/null || echo "source-data/ absent — OK"`
- Match count: 2
- Output:
```text
eeg_welch_export.zip
spectral_centroid_export.zip
```
- Classification: Warning. The ignored `source-data/` directory exists in the workspace and contains export archives. A follow-up git tracking check returned no tracked entries, so this is a local workspace artifact rather than a committed repo exposure. It should still remain excluded from commits and release bundles.

## 7) PII in data.json
- Command: `grep -c "email\|phone\|address\|name\|dob\|ssn" data/data.json -i || true`
- Match count: 0
- Output:
```text
0
```

## 8) External resources in index.html
- Command: `grep -n "cdn\|external\|src=.http" index.html || true`
- Match count: 2
- Output:
```text
10:    <link rel="preconnect" href="https://cdnjs.cloudflare.com">
12:    <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
```
- Classification: Warning. These are non-sensitive external CDN resources. They are visible dependencies, not a data leak.

## Findings
- Warning: `source-data/` is present in the workspace and contains two ZIP exports. `.gitignore` already excludes the directory, and git does not currently track it, so this is a local workspace artifact rather than a committed repo exposure. It should still stay out of commits and release bundles.
- Warning: `index.html` loads JSZip from CDNJS and preconnects to the same domain. This is expected external dependency usage, but it does create a network dependency and should remain intentional.
- OK: No absolute local path leaks, no obvious API key/token/password strings, no `console.log` hits, and no PII keyword hits in `data/data.json`.
- OK: The only JavaScript URL-like string found is the SVG namespace constant in `js/views/channel-grid.js`, which is not a network URL.

## Summary
The audit did not find an obvious secret or PII exposure in the checked surfaces. The main privacy/security hygiene items are the local `source-data/` export archives and the external CDN dependency in `index.html`. Neither is automatically a release blocker from the evidence gathered here, but both deserve normal release discipline: keep `source-data/` out of commits and verify the CDN dependency is acceptable for the deployment model.

- Critical: 0
- Warning: 2
- OK: 6
