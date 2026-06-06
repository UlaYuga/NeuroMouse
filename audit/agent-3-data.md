# Agent 3: Data Integrity

## Verification Script
- [OK] `tools/verify_data.mjs` exists.
- [OK] The script validates metadata, Welch PSD, centroid arrays, geometry metrics, area-normalized PSD, and channel summary coverage.

## Command

```bash
node tools/verify_data.mjs
```

## Output

```text
Data Integrity: 55 passed, 0 failed
```

## Summary
- Critical: 0
- Warning: 0
- OK: 55
