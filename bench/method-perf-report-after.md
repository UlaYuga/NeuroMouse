# NeuroMouse MEA-Method Performance Bench

Workload: 1024 channels x 64 samples (golden raw traces).
Iterations: 7 measured, 1 warmups.
spike_detect ground truth: 57/57 spikes recovered.

## Results

| Method | p50 ms | p95 ms | Peak MB | Budget p95 ms | Ground truth | Status |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| spike_detect | 12.01 | 13.94 | 1.17 | 8.00 | 57/57 | FAIL |
| network_burst | 0.27 | 0.32 | 0.09 | 5.00 | n/a | PASS |
| electrode_connectivity | 193.39 | 198.82 | 287.64 | 300.00 | n/a | PASS |
