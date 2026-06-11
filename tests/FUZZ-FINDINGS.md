# FUZZ-FINDINGS

Date: 2026-06-12
Runner: nm-fuzzx worktree, branch task/fuzz-x

Scope:
- New fuzz targets added under `tests/fuzz` and `tests/property`.
- Baseline verification performed on existing suites first:
  - `tests/fuzz/live-payload.fuzz.mjs`
  - `tests/property/validate-data.property.test.mjs`
  - `tests/property/import-csv-zip.property.test.mjs`

## JS fuzz targets (`tests/fuzz`, FUZZ_DRY_ROUNDS=2)

| Target | Seed | Runs | Base Cases | Max Cases | Total Cases | Dry Streak | Result |
|---|---:|---:|---:|---:|---:|---|---|
| mea-adapter | 335597 | 2 | 64 | 512 | 192 | 2/2 | `PROPERTY_OK` equivalent: no findings |
| run-engine | 520205 | 2 | 64 | 512 | 192 | 2/2 | no findings |
| backend-jobs | 31249 | 2 | 64 | 512 | 192 | 2/2 | no findings |
| sorter-seam | 1850 | 2 | 64 | 512 | 192 | 2/2 | no findings |

## Property tests (`tests/property`, PROPERTY_DRY_RUNS=2)

| Test | Seed | Total Cases | Dry Streak | Result |
|---|---:|---:|---:|---|
| mea-adapter.property.test.mjs | 335597 | 192 | 2/2 | pass |
| run-engine.property.test.mjs | 520205 | 192 | 2/2 | pass |
| backend-jobs.property.test.mjs | 31249 | 192 | 2/2 | pass |
| sorter-seam.property.test.mjs | 1850 | 192 | 2/2 | pass |

## Findings
- **all dry**
- No functional bugs surfaced in the reported runs. Findings were due optional dependency/runtime wiring issues during bootstrap and were resolved during environment setup, not by weakening fuzzers.
