# NeuroMouse Performance Bench

## Budget Policy

| Target | Budget |
| --- | --- |
| validator | p95 <= max(75 ms, 0.0020 ms * channels * (frequency_bins + 7 * time_points) + 0.20 ms * channels); peak <= max(96 MB, 2.75 * input_peak + 64 MB) |
| dsp | p95 <= max(100 ms, 0.0012 ms * channels * record_samples + 0.30 ms * channels); peak <= max(128 MB, 2.0 * input_peak + 96 MB) |

Iterations: 21 measured, 3 warmups.

## Results

| Target | Channels | Samples | Shape | p50 ms | p95 ms | Peak MB | Budget p95 ms | Budget MB | Status |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| validator | 32 | 1024 | 65 freq / 8 time | 0.56 | 0.63 | 0.25 | 75.00 | 96.00 | PASS |
| dsp | 32 | 1024 | 513 freq / 1024 time | 20000.00 | 20000.00 | 0.12 | 100.00 | 128.00 | FAIL |
| validator | 32 | 4096 | 257 freq / 32 time | 1.40 | 1.71 | 0.70 | 75.00 | 96.00 | PASS |
| dsp | 32 | 4096 | 513 freq / 4096 time | 20000.00 | 20000.00 | 0.50 | 166.89 | 128.00 | FAIL |
| validator | 32 | 8192 | 513 freq / 64 time | 2.33 | 2.40 | 1.29 | 75.00 | 96.00 | PASS |
| dsp | 32 | 8192 | 513 freq / 8192 time | 20000.00 | 20000.00 | 1.00 | 324.17 | 128.00 | FAIL |
| validator | 32 | 16384 | 1025 freq / 128 time | 4.62 | 9.35 | 2.50 | 129.34 | 96.00 | PASS |
| dsp | 32 | 16384 | 513 freq / 16384 time | 20000.00 | 20000.00 | 2.00 | 638.75 | 128.00 | FAIL |
| validator | 256 | 1024 | 65 freq / 8 time | 4.27 | 4.46 | 1.92 | 113.15 | 96.00 | PASS |
| dsp | 256 | 1024 | 513 freq / 1024 time | 20000.00 | 20000.00 | 1.00 | 391.37 | 128.00 | FAIL |
| validator | 256 | 4096 | 257 freq / 32 time | 11.13 | 12.67 | 5.44 | 297.47 | 96.00 | PASS |
| dsp | 256 | 4096 | 513 freq / 4096 time | 20000.00 | 20000.00 | 4.00 | 1335.09 | 128.00 | FAIL |
| validator | 256 | 8192 | 513 freq / 64 time | 18.86 | 20.24 | 10.14 | 543.23 | 96.00 | PASS |
| dsp | 256 | 8192 | 513 freq / 8192 time | 20000.00 | 20000.00 | 8.00 | 2593.38 | 128.00 | FAIL |
| validator | 256 | 16384 | 1025 freq / 128 time | 35.03 | 35.30 | 19.67 | 1034.75 | 106.48 | PASS |
| dsp | 256 | 16384 | 513 freq / 16384 time | 20000.00 | 20000.00 | 16.00 | 5109.96 | 128.00 | FAIL |
| validator | 1024 | 1024 | 65 freq / 8 time | 16.64 | 19.62 | 7.66 | 452.61 | 96.00 | PASS |
| dsp | 1024 | 1024 | 513 freq / 1024 time | 20000.00 | 20000.00 | 4.00 | 1565.49 | 128.00 | FAIL |
| validator | 1024 | 4096 | 257 freq / 32 time | 42.34 | 45.32 | 21.73 | 1189.89 | 108.41 | PASS |
| dsp | 1024 | 4096 | 513 freq / 4096 time | 20000.00 | 20000.00 | 16.00 | 5340.36 | 128.00 | FAIL |
| validator | 1024 | 8192 | 513 freq / 64 time | 74.70 | 77.29 | 40.46 | 2172.93 | 149.60 | PASS |
| dsp | 1024 | 8192 | 513 freq / 8192 time | 20000.00 | 20000.00 | 32.00 | 10373.53 | 160.00 | FAIL |
| validator | 1024 | 16384 | 1025 freq / 128 time | 141.68 | 148.67 | 78.51 | 4139.01 | 233.61 | PASS |
| dsp | 1024 | 16384 | 513 freq / 16384 time | 20000.00 | 20000.00 | 64.00 | 20439.86 | 224.00 | FAIL |
| validator | 2048 | 1024 | 65 freq / 8 time | 34.37 | 35.26 | 15.31 | 905.22 | 96.00 | PASS |
| dsp | 2048 | 1024 | 513 freq / 1024 time | 20000.00 | 20000.00 | 8.00 | 3130.98 | 128.00 | FAIL |
| validator | 2048 | 4096 | 257 freq / 32 time | 86.80 | 88.04 | 43.44 | 2379.78 | 152.80 | PASS |
| dsp | 2048 | 4096 | 513 freq / 4096 time | 20000.00 | 20000.00 | 32.00 | 10680.73 | 160.00 | FAIL |
| validator | 2048 | 8192 | 513 freq / 64 time | 155.41 | 156.94 | 80.89 | 4345.86 | 235.15 | PASS |
| dsp | 2048 | 8192 | 513 freq / 8192 time | 20000.00 | 20000.00 | 64.00 | 20747.06 | 224.00 | FAIL |
| validator | 2048 | 16384 | 1025 freq / 128 time | 289.94 | 324.70 | 156.97 | 8278.02 | 403.12 | PASS |
| dsp | 2048 | 16384 | 513 freq / 16384 time | 20000.00 | 20000.00 | 128.00 | 40879.72 | 352.00 | FAIL |

## Hotspots

| Rank | Target | Location | Cost | Budget Ratio | Reason |
| ---: | --- | --- | --- | ---: | --- |
| 1 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s; p95 20000.00 ms > 100.00 ms | 200.00 | benchmark error: DSP dependency import timed out after 20s and latency budget exceeded |
| 2 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s; p95 20000.00 ms > 166.89 ms | 119.84 | benchmark error: DSP dependency import timed out after 20s and latency budget exceeded |
| 3 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s; p95 20000.00 ms > 324.17 ms | 61.70 | benchmark error: DSP dependency import timed out after 20s and latency budget exceeded |
| 4 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s; p95 20000.00 ms > 391.37 ms | 51.10 | benchmark error: DSP dependency import timed out after 20s and latency budget exceeded |
| 5 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s; p95 20000.00 ms > 638.75 ms | 31.31 | benchmark error: DSP dependency import timed out after 20s and latency budget exceeded |
| 6 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s; p95 20000.00 ms > 1335.09 ms | 14.98 | benchmark error: DSP dependency import timed out after 20s and latency budget exceeded |
| 7 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s; p95 20000.00 ms > 1565.49 ms | 12.78 | benchmark error: DSP dependency import timed out after 20s and latency budget exceeded |
| 8 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s; p95 20000.00 ms > 2593.38 ms | 7.71 | benchmark error: DSP dependency import timed out after 20s and latency budget exceeded |
| 9 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s; p95 20000.00 ms > 3130.98 ms | 6.39 | benchmark error: DSP dependency import timed out after 20s and latency budget exceeded |
| 10 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s; p95 20000.00 ms > 5109.96 ms | 3.91 | benchmark error: DSP dependency import timed out after 20s and latency budget exceeded |
| 11 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s; p95 20000.00 ms > 5340.36 ms | 3.75 | benchmark error: DSP dependency import timed out after 20s and latency budget exceeded |
| 12 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s; p95 20000.00 ms > 10373.53 ms | 1.93 | benchmark error: DSP dependency import timed out after 20s and latency budget exceeded |
| 13 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s; p95 20000.00 ms > 10680.73 ms | 1.87 | benchmark error: DSP dependency import timed out after 20s and latency budget exceeded |
| 14 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s | 0.98 | benchmark error: DSP dependency import timed out after 20s |
| 15 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s | 0.96 | benchmark error: DSP dependency import timed out after 20s |
| 16 | dsp | `packages/core/src/neuromouse_core/dsp.py::compute_channels` | DSP dependency import timed out after 20s | 0.49 | benchmark error: DSP dependency import timed out after 20s |
