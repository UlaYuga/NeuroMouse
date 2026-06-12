from __future__ import annotations

import json


def test_method_benchmark_default_grid_targets_full_golden_mea() -> None:
    from bench import perf_harness

    assert perf_harness.METHOD_TARGETS == (
        "spike_detect",
        "network_burst",
        "electrode_connectivity",
    )
    # The golden MEA fixture is the full 1024-channel raw-trace workload.
    assert perf_harness.GOLDEN_MEA_CHANNELS == 1024


def test_method_benchmark_runs_three_methods_and_reports_p95(tmp_path) -> None:
    from bench.perf_harness import run_method_benchmarks

    result_path = tmp_path / "method-perf-results.json"
    markdown_path = tmp_path / "method-perf-report.md"
    report = run_method_benchmarks(
        iterations=3,
        warmups=1,
        channel_limit=64,
        output_json=result_path,
        output_markdown=markdown_path,
    )

    assert result_path.exists()
    assert markdown_path.exists()

    targets = {row.target for row in report.results}
    assert targets == {"spike_detect", "network_burst", "electrode_connectivity"}
    for row in report.results:
        assert row.p95_ms >= 0.0
        assert row.p50_ms >= 0.0
        assert row.iterations == 3
        assert row.channels == 64
        assert row.error is None

    stored = json.loads(result_path.read_text(encoding="utf-8"))
    assert {row["target"] for row in stored["results"]} == targets


def test_method_benchmark_verifies_spike_detect_ground_truth_at_full_scale() -> None:
    from bench.perf_harness import run_method_benchmarks

    report = run_method_benchmarks(
        iterations=3,
        warmups=0,
        methods=("spike_detect",),
        output_markdown=None,
        # Large multiplier removes the latency budget from the verdict so `passed`
        # isolates the ground-truth gate.
        budget_multiplier=1000.0,
    )

    spike_row = next(row for row in report.results if row.target == "spike_detect")
    # Full 1024-channel golden: detector must recover all 57 injected spikes.
    assert spike_row.ground_truth_expected == 57
    assert spike_row.ground_truth_recovered == 57
    assert spike_row.passed is True
    assert report.budgets["spike_detect_ground_truth"] == {"recovered": 57, "expected": 57}
