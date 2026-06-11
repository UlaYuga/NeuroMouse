from __future__ import annotations

import json


def test_default_scale_grid_covers_mea_sizes_and_increasing_lengths() -> None:
    from bench import perf_harness

    assert perf_harness.CHANNEL_COUNTS == (32, 256, 1024, 2048)
    assert perf_harness.RECORD_LENGTHS == (1024, 4096, 8192, 16384)
    assert perf_harness.RECORD_LENGTHS == tuple(sorted(perf_harness.RECORD_LENGTHS))


def test_budget_evaluation_fails_rows_and_ranks_hotspots() -> None:
    from bench.perf_harness import BenchmarkRow, evaluate_budget_results

    rows = [
        BenchmarkRow(
            target="dsp",
            channels=1024,
            record_samples=8192,
            iterations=21,
            p50_ms=900.0,
            p95_ms=2400.0,
            peak_mb=180.0,
            budget_p95_ms=1200.0,
            budget_peak_mb=512.0,
            file="packages/core/src/neuromouse_core/dsp.py",
            function="compute_channels",
        ),
        BenchmarkRow(
            target="validator",
            channels=1024,
            record_samples=8192,
            iterations=21,
            p50_ms=80.0,
            p95_ms=120.0,
            peak_mb=96.0,
            budget_p95_ms=500.0,
            budget_peak_mb=256.0,
            file="contracts/src/neuromouse_contract/dataset.py",
            function="validate_dataset",
        ),
        BenchmarkRow(
            target="validator",
            channels=2048,
            record_samples=16384,
            iterations=21,
            p50_ms=1300.0,
            p95_ms=1800.0,
            peak_mb=420.0,
            budget_p95_ms=3000.0,
            budget_peak_mb=256.0,
            file="contracts/src/neuromouse_contract/dataset.py",
            function="validate_dataset",
        ),
    ]

    evaluated, hotspots = evaluate_budget_results(rows)

    assert [row.passed for row in evaluated] == [False, True, False]
    assert [hotspot["target"] for hotspot in hotspots] == ["dsp", "validator"]
    assert hotspots[0]["budget_ratio"] > hotspots[1]["budget_ratio"]
    assert hotspots[0]["file"] == "packages/core/src/neuromouse_core/dsp.py"
    assert hotspots[0]["function"] == "compute_channels"
    assert "latency" in hotspots[0]["reason"]
    assert "memory" in hotspots[1]["reason"]


def test_smoke_run_writes_report_with_budget_status(tmp_path) -> None:
    from bench.perf_harness import run_benchmarks

    result_path = tmp_path / "perf-results.json"
    markdown_path = tmp_path / "perf-report.md"
    report = run_benchmarks(
        channel_counts=(2,),
        record_lengths=(128,),
        iterations=3,
        warmups=1,
        output_json=result_path,
        output_markdown=markdown_path,
        targets=("validator",),
        budget_multiplier=1000.0,
    )

    assert result_path.exists()
    assert markdown_path.exists()
    stored = json.loads(result_path.read_text(encoding="utf-8"))
    assert stored["budgets"]["iterations"] == 3
    assert stored["budgets"]["warmups"] == 1
    assert stored["failures"] == []
    assert stored["hotspots"] == []
    assert {row["target"] for row in stored["results"]} == {"validator"}
    assert all(row["passed"] is True for row in stored["results"])
    assert report.failures == []
    assert report.hotspots == []
