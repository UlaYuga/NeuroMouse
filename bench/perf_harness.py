from __future__ import annotations

import argparse
import gc
import json
import math
import os
import subprocess
import sys
import time
import tracemalloc
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for source_path in (
    REPO_ROOT / "contracts" / "src",
    REPO_ROOT / "packages" / "core" / "src",
    REPO_ROOT / "packages" / "sdk" / "src",
):
    source_path_text = str(source_path)
    if source_path_text not in sys.path:
        sys.path.insert(0, source_path_text)

CHANNEL_COUNTS = (32, 256, 1024, 2048)
RECORD_LENGTHS = (1024, 4096, 8192, 16384)
DEFAULT_ITERATIONS = 21
DEFAULT_WARMUPS = 3
DEFAULT_TARGETS = ("validator", "dsp")
SAMPLING_RATE_HZ = 250.0
BYTES_PER_MB = 1024 * 1024
IMPORT_TIMEOUT_SEC = 20.0

DSP_FILE = "packages/core/src/neuromouse_core/dsp.py"
DSP_FUNCTION = "compute_channels"
VALIDATOR_FILE = "contracts/src/neuromouse_contract/dataset.py"
VALIDATOR_FUNCTION = "validate_dataset"

# MEA reference-method benchmark configuration. These methods are benchmarked on the
# full 1024-channel raw-trace golden fixture (spike_detect -> spikes -> burst/connectivity).
METHOD_TARGETS = ("spike_detect", "network_burst", "electrode_connectivity")
GOLDEN_MEA_PATH = REPO_ROOT / "datasets" / "golden" / "mea_synthetic.json"
GOLDEN_MEA_CHANNELS = 1024
SPIKE_MATCH_TOLERANCE_SEC = 0.0015
DEFAULT_METHOD_ITERATIONS = 9
DEFAULT_METHOD_WARMUPS = 2
# Explicit per-method p95 latency budgets (ms) and peak budgets (MB) on the full golden.
METHOD_P95_BUDGET_MS = {
    "spike_detect": 8.0,
    "network_burst": 5.0,
    "electrode_connectivity": 300.0,
}
METHOD_PEAK_BUDGET_MB = {
    "spike_detect": 96.0,
    "network_burst": 96.0,
    "electrode_connectivity": 512.0,
}


@dataclass(frozen=True)
class BenchmarkRow:
    target: str
    channels: int
    record_samples: int
    iterations: int
    p50_ms: float
    p95_ms: float
    peak_mb: float
    budget_p95_ms: float
    budget_peak_mb: float
    file: str
    function: str
    passed: bool | None = None
    error: str | None = None
    input_peak_mb: float = 0.0
    operation_peak_mb: float = 0.0
    frequency_bins: int = 0
    time_points: int = 0
    ground_truth_recovered: int = 0
    ground_truth_expected: int = 0

    def to_json(self) -> dict[str, Any]:
        row = asdict(self)
        row["passed"] = bool(self.passed)
        return row


@dataclass(frozen=True)
class BenchmarkReport:
    results: list[BenchmarkRow]
    failures: list[BenchmarkRow]
    hotspots: list[dict[str, Any]]
    budgets: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "budgets": self.budgets,
            "results": [row.to_json() for row in self.results],
            "failures": [row.to_json() for row in self.failures],
            "hotspots": self.hotspots,
        }


@dataclass(frozen=True)
class Measurement:
    p50_ms: float
    p95_ms: float
    operation_peak_mb: float


class BenchmarkDependencyError(RuntimeError):
    pass


def run_benchmarks(
    *,
    channel_counts: Sequence[int] = CHANNEL_COUNTS,
    record_lengths: Sequence[int] = RECORD_LENGTHS,
    iterations: int = DEFAULT_ITERATIONS,
    warmups: int = DEFAULT_WARMUPS,
    output_json: str | Path = Path("bench/perf-results.json"),
    output_markdown: str | Path | None = Path("bench/perf-report.md"),
    targets: Sequence[str] = DEFAULT_TARGETS,
    budget_multiplier: float = 1.0,
) -> BenchmarkReport:
    _validate_run_config(channel_counts, record_lengths, iterations, warmups, targets)

    rows: list[BenchmarkRow] = []
    for channels in channel_counts:
        for record_samples in record_lengths:
            if "validator" in targets:
                rows.append(
                    _benchmark_validator(
                        channels,
                        record_samples,
                        iterations=iterations,
                        warmups=warmups,
                        budget_multiplier=budget_multiplier,
                    )
                )
            if "dsp" in targets:
                rows.append(
                    _benchmark_dsp(
                        channels,
                        record_samples,
                        iterations=iterations,
                        warmups=warmups,
                        budget_multiplier=budget_multiplier,
                    )
                )
            gc.collect()

    evaluated, hotspots = evaluate_budget_results(rows)
    failures = [row for row in evaluated if not row.passed]
    report = BenchmarkReport(
        results=evaluated,
        failures=failures,
        hotspots=hotspots,
        budgets={
            "channel_counts": list(channel_counts),
            "record_lengths": list(record_lengths),
            "iterations": iterations,
            "warmups": warmups,
            "targets": list(targets),
            "budget_multiplier": budget_multiplier,
            "notes": [
                "Latency budgets are explicit per-row p95 thresholds.",
                "Peak memory is input peak plus measured operation peak.",
                "Input peak is traced for validator payloads and ndarray bytes for DSP.",
            ],
        },
    )

    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report.to_json(), indent=2) + "\n", encoding="utf-8")

    if output_markdown is not None:
        output_markdown = Path(output_markdown)
        output_markdown.parent.mkdir(parents=True, exist_ok=True)
        output_markdown.write_text(format_markdown_report(report), encoding="utf-8")

    return report


def evaluate_budget_results(
    rows: Sequence[BenchmarkRow],
) -> tuple[list[BenchmarkRow], list[dict[str, Any]]]:
    evaluated = [
        replace(
            row,
            passed=(
                row.error is None
                and row.p95_ms <= row.budget_p95_ms
                and row.peak_mb <= row.budget_peak_mb
            ),
        )
        for row in rows
    ]
    hotspots = [_hotspot_for_row(row) for row in evaluated if not row.passed]
    hotspots.sort(key=lambda item: item["budget_ratio"], reverse=True)
    return evaluated, hotspots


def format_markdown_report(report: BenchmarkReport) -> str:
    lines = [
        "# NeuroMouse Performance Bench",
        "",
        "## Budget Policy",
        "",
        "| Target | Budget |",
        "| --- | --- |",
        (
            "| validator | p95 <= max(75 ms, "
            "0.0020 ms * channels * (frequency_bins + 7 * time_points) "
            "+ 0.20 ms * channels); peak <= max(96 MB, 2.75 * input_peak + 64 MB) |"
        ),
        (
            "| dsp | p95 <= max(100 ms, 0.0012 ms * channels * record_samples "
            "+ 0.30 ms * channels); peak <= max(128 MB, 2.0 * input_peak + 96 MB) |"
        ),
        "",
        f"Iterations: {report.budgets['iterations']} measured, "
        f"{report.budgets['warmups']} warmups.",
        "",
        "## Results",
        "",
        "| Target | Channels | Samples | Shape | p50 ms | p95 ms | Peak MB | "
        "Budget p95 ms | Budget MB | Status |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report.results:
        status = "PASS" if row.passed else "FAIL"
        shape = f"{row.frequency_bins} freq / {row.time_points} time"
        lines.append(
            "| "
            f"{row.target} | {row.channels} | {row.record_samples} | {shape} | "
            f"{row.p50_ms:.2f} | {row.p95_ms:.2f} | {row.peak_mb:.2f} | "
            f"{row.budget_p95_ms:.2f} | {row.budget_peak_mb:.2f} | {status} |"
        )

    lines.extend(["", "## Hotspots", ""])
    if report.hotspots:
        lines.extend(
            [
                "| Rank | Target | Location | Cost | Budget Ratio | Reason |",
                "| ---: | --- | --- | --- | ---: | --- |",
            ]
        )
        for index, hotspot in enumerate(report.hotspots, start=1):
            lines.append(
                "| "
                f"{index} | {hotspot['target']} | "
                f"`{hotspot['file']}::{hotspot['function']}` | "
                f"{hotspot['measured_cost']} | {hotspot['budget_ratio']:.2f} | "
                f"{hotspot['reason']} |"
            )
    else:
        lines.append("All within budget.")
    lines.append("")
    return "\n".join(lines)


def _benchmark_validator(
    channels: int,
    record_samples: int,
    *,
    iterations: int,
    warmups: int,
    budget_multiplier: float,
) -> BenchmarkRow:
    from neuromouse_contract import validate_dataset

    frequency_bins, time_points = _contract_shape(record_samples)
    payload, input_peak_mb = _build_with_traced_peak(
        lambda: _make_contract_dataset(channels, frequency_bins, time_points)
    )

    measurement = _measure_operation(
        lambda: validate_dataset(payload, max_channels=max(4096, channels)),
        iterations=iterations,
        warmups=warmups,
    )
    budget_p95_ms = budget_multiplier * _validator_latency_budget_ms(
        channels,
        frequency_bins,
        time_points,
    )
    budget_peak_mb = budget_multiplier * max(96.0, (2.75 * input_peak_mb) + 64.0)
    total_peak_mb = input_peak_mb + measurement.operation_peak_mb
    return BenchmarkRow(
        target="validator",
        channels=channels,
        record_samples=record_samples,
        iterations=iterations,
        p50_ms=measurement.p50_ms,
        p95_ms=measurement.p95_ms,
        peak_mb=total_peak_mb,
        budget_p95_ms=budget_p95_ms,
        budget_peak_mb=budget_peak_mb,
        input_peak_mb=input_peak_mb,
        operation_peak_mb=measurement.operation_peak_mb,
        frequency_bins=frequency_bins,
        time_points=time_points,
        file=VALIDATOR_FILE,
        function=VALIDATOR_FUNCTION,
    )


def _benchmark_dsp(
    channels: int,
    record_samples: int,
    *,
    iterations: int,
    warmups: int,
    budget_multiplier: float,
) -> BenchmarkRow:
    frequency_bins = min(record_samples, 1024) // 2 + 1
    input_peak_mb = float(channels * record_samples * 4) / BYTES_PER_MB
    budget_p95_ms = budget_multiplier * _dsp_latency_budget_ms(channels, record_samples)
    budget_peak_mb = budget_multiplier * max(128.0, (2.0 * input_peak_mb) + 96.0)
    try:
        compute_channels = _load_compute_channels()
    except BenchmarkDependencyError as exc:
        return BenchmarkRow(
            target="dsp",
            channels=channels,
            record_samples=record_samples,
            iterations=iterations,
            p50_ms=IMPORT_TIMEOUT_SEC * 1000.0,
            p95_ms=IMPORT_TIMEOUT_SEC * 1000.0,
            peak_mb=input_peak_mb,
            budget_p95_ms=budget_p95_ms,
            budget_peak_mb=budget_peak_mb,
            input_peak_mb=input_peak_mb,
            operation_peak_mb=0.0,
            frequency_bins=frequency_bins,
            time_points=record_samples,
            file=DSP_FILE,
            function=DSP_FUNCTION,
            error=str(exc),
        )

    buffers = _make_dsp_buffers(channels, record_samples)
    input_peak_mb = float(buffers.nbytes) / BYTES_PER_MB
    measurement = _measure_operation(
        lambda: compute_channels(buffers, sampling_rate=SAMPLING_RATE_HZ),
        iterations=iterations,
        warmups=warmups,
        output_size_mb=_dsp_output_mb,
    )
    total_peak_mb = input_peak_mb + measurement.operation_peak_mb
    return BenchmarkRow(
        target="dsp",
        channels=channels,
        record_samples=record_samples,
        iterations=iterations,
        p50_ms=measurement.p50_ms,
        p95_ms=measurement.p95_ms,
        peak_mb=total_peak_mb,
        budget_p95_ms=budget_p95_ms,
        budget_peak_mb=budget_peak_mb,
        input_peak_mb=input_peak_mb,
        operation_peak_mb=measurement.operation_peak_mb,
        frequency_bins=frequency_bins,
        time_points=record_samples,
        file=DSP_FILE,
        function=DSP_FUNCTION,
    )


def _measure_operation(
    operation: Callable[[], Any],
    *,
    iterations: int,
    warmups: int,
    output_size_mb: Callable[[Any], float] | None = None,
) -> Measurement:
    for _ in range(warmups):
        result = operation()
        del result
    gc.collect()

    timings_ms: list[float] = []
    peaks_mb: list[float] = []
    for _ in range(iterations):
        gc.collect()
        tracemalloc.start()
        started = time.perf_counter()
        result = operation()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        _, peak_bytes = tracemalloc.get_traced_memory()
        output_mb = output_size_mb(result) if output_size_mb is not None else 0.0
        tracemalloc.stop()
        timings_ms.append(elapsed_ms)
        peaks_mb.append((float(peak_bytes) / BYTES_PER_MB) + output_mb)
        del result

    return Measurement(
        p50_ms=_percentile(timings_ms, 50),
        p95_ms=_percentile(timings_ms, 95),
        operation_peak_mb=max(peaks_mb),
    )


_COMPUTE_CHANNELS: Callable[..., Any] | None = None
_COMPUTE_CHANNELS_ERROR: BenchmarkDependencyError | None = None


def _load_compute_channels() -> Callable[..., Any]:
    global _COMPUTE_CHANNELS, _COMPUTE_CHANNELS_ERROR
    if _COMPUTE_CHANNELS is not None:
        return _COMPUTE_CHANNELS
    if _COMPUTE_CHANNELS_ERROR is not None:
        raise _COMPUTE_CHANNELS_ERROR
    _check_dsp_import_subprocess()
    try:
        from neuromouse_core.dsp import compute_channels
    except Exception as exc:  # noqa: BLE001 - benchmark reports dependency failures.
        _COMPUTE_CHANNELS_ERROR = BenchmarkDependencyError(f"DSP dependency import failed: {exc}")
        raise _COMPUTE_CHANNELS_ERROR from exc
    _COMPUTE_CHANNELS = compute_channels
    return compute_channels


def _check_dsp_import_subprocess() -> None:
    global _COMPUTE_CHANNELS_ERROR
    code = (
        "import sys; "
        f"sys.path[:0] = {repr(_source_paths())}; "
        "from neuromouse_core.dsp import compute_channels; "
        "print('ok')"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([*map(str, _source_paths()), env.get("PYTHONPATH", "")])
    env["NEUROMOUSE_NATIVE_PREWARM_CHILD"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=IMPORT_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _COMPUTE_CHANNELS_ERROR = BenchmarkDependencyError(
            f"DSP dependency import timed out after {IMPORT_TIMEOUT_SEC:.0f}s"
        )
        raise _COMPUTE_CHANNELS_ERROR from exc
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown import error"
        _COMPUTE_CHANNELS_ERROR = BenchmarkDependencyError(
            f"DSP dependency import failed in subprocess: {stderr}"
        )
        raise _COMPUTE_CHANNELS_ERROR


def _source_paths() -> list[str]:
    return [
        str(REPO_ROOT / "contracts" / "src"),
        str(REPO_ROOT / "packages" / "core" / "src"),
        str(REPO_ROOT / "packages" / "sdk" / "src"),
    ]


def _build_with_traced_peak(builder: Callable[[], Any]) -> tuple[Any, float]:
    gc.collect()
    tracemalloc.start()
    value = builder()
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return value, float(peak_bytes) / BYTES_PER_MB


def _contract_shape(record_samples: int) -> tuple[int, int]:
    frequency_bins = min(1025, max(65, (record_samples // 16) + 1))
    time_points = min(128, max(8, record_samples // 128))
    return frequency_bins, time_points


def _make_contract_dataset(
    channels: int,
    frequency_bins: int,
    time_points: int,
) -> dict[str, Any]:
    channel_names = [f"Ch{index:04d}" for index in range(channels)]
    freqs = [float(index) * 0.25 for index in range(frequency_bins)]
    time_axis = [float(index) * 0.5 for index in range(time_points)]
    psd = _matrix(channels, frequency_bins, scale=0.0001, offset=0.001)
    metric = _matrix(channels, time_points, scale=0.0005, offset=0.1)
    return {
        "meta": {
            "channels": channel_names,
            "n_channels": channels,
            "sampling_rate_analysis_hz": SAMPLING_RATE_HZ,
            "welch_window_sec": 4.0,
            "welch_overlap_fraction": 0.5,
        },
        "welch_psd": {
            "frequencies": freqs,
            "psd": psd,
        },
        "centroid": {
            "time_relative": time_axis,
            "values": _matrix(channels, time_points, scale=0.001, offset=8.0),
        },
        "geometry": {
            "time": time_axis,
            "centroid": metric,
            "spread": _matrix(channels, time_points, scale=0.0002, offset=1.0),
            "entropy": _matrix(channels, time_points, scale=0.0002, offset=0.5),
            "flatness": _matrix(channels, time_points, scale=0.0001, offset=0.2),
            "edge95": _matrix(channels, time_points, scale=0.002, offset=20.0),
            "alpha_relative_power": _matrix(channels, time_points, scale=0.0001, offset=0.3),
        },
        "channel_summary": [
            {
                "channel": channel,
                "hemisphere": "",
                "region": "unknown",
                "has_clear_alpha_peak": False,
                "alpha_relative_power": 0.3,
                "spectral_centroid_hz": 8.0,
                "spectral_spread_hz": 1.0,
                "spectral_entropy": 0.6,
                "spectral_flatness": 0.2,
                "edge95_hz": 24.0,
                "alpha_peak_frequency_hz": 10.0,
                "sliding_alpha_relative_mean": 0.29,
            }
            for channel in channel_names
        ],
    }


def _matrix(rows: int, columns: int, *, scale: float, offset: float) -> list[list[float]]:
    return [
        [offset + (((row_index * 31) + column_index) % 997) * scale for column_index in range(columns)]
        for row_index in range(rows)
    ]


def _make_dsp_buffers(channels: int, record_samples: int) -> Any:
    import numpy as np

    time_axis = np.arange(record_samples, dtype=np.float32) / np.float32(SAMPLING_RATE_HZ)
    buffers = np.empty((channels, record_samples), dtype=np.float32)
    for channel in range(channels):
        primary_hz = np.float32(4.0 + (channel % 17))
        secondary_hz = np.float32(18.0 + (channel % 23))
        phase = np.float32((channel % 29) * 0.07)
        buffers[channel] = (
            np.sin((2.0 * np.pi * primary_hz * time_axis) + phase)
            + (0.35 * np.sin((2.0 * np.pi * secondary_hz * time_axis) + (phase * 0.5)))
            + np.float32((channel % 11) * 0.001)
        )
    return buffers


def _dsp_output_mb(result: Sequence[Any]) -> float:
    bytes_used = 0
    for channel_result in result:
        bytes_used += channel_result.frequencies.nbytes
        bytes_used += channel_result.psd.nbytes
    return float(bytes_used) / BYTES_PER_MB


def _validator_latency_budget_ms(
    channels: int,
    frequency_bins: int,
    time_points: int,
) -> float:
    scanned_cells = channels * (frequency_bins + (7 * time_points))
    return max(75.0, (0.0020 * scanned_cells) + (0.20 * channels))


def _dsp_latency_budget_ms(channels: int, record_samples: int) -> float:
    return max(100.0, (0.0012 * channels * record_samples) + (0.30 * channels))


def _hotspot_for_row(row: BenchmarkRow) -> dict[str, Any]:
    latency_ratio = _safe_ratio(row.p95_ms, row.budget_p95_ms)
    memory_ratio = _safe_ratio(row.peak_mb, row.budget_peak_mb)
    reasons: list[str] = []
    costs: list[str] = []
    if row.error is not None:
        reasons.append(f"benchmark error: {row.error}")
        costs.append(row.error)
    if row.p95_ms > row.budget_p95_ms:
        reasons.append("latency budget exceeded")
        costs.append(f"p95 {row.p95_ms:.2f} ms > {row.budget_p95_ms:.2f} ms")
    if row.peak_mb > row.budget_peak_mb:
        reasons.append("memory budget exceeded")
        costs.append(f"peak {row.peak_mb:.2f} MB > {row.budget_peak_mb:.2f} MB")
    return {
        "target": row.target,
        "channels": row.channels,
        "record_samples": row.record_samples,
        "file": row.file,
        "function": row.function,
        "measured_cost": "; ".join(costs),
        "budget_ratio": max(latency_ratio, memory_ratio),
        "reason": " and ".join(reasons),
    }


def _safe_ratio(actual: float, budget: float) -> float:
    if budget <= 0:
        return math.inf
    return actual / budget


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile for an empty sequence")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * (percentile / 100.0)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    lower_value = ordered[lower]
    upper_value = ordered[upper]
    return lower_value + ((upper_value - lower_value) * (position - lower))


def _validate_run_config(
    channel_counts: Sequence[int],
    record_lengths: Sequence[int],
    iterations: int,
    warmups: int,
    targets: Sequence[str],
) -> None:
    if not channel_counts or any(value <= 0 for value in channel_counts):
        raise ValueError("channel counts must be positive")
    if not record_lengths or any(value < 8 for value in record_lengths):
        raise ValueError("record lengths must be at least 8 samples")
    if tuple(record_lengths) != tuple(sorted(record_lengths)):
        raise ValueError("record lengths must be sorted in increasing order")
    if iterations < 3:
        raise ValueError("at least 3 iterations are required to compute p95")
    if warmups < 0:
        raise ValueError("warmups cannot be negative")
    invalid_targets = set(targets) - set(DEFAULT_TARGETS)
    if invalid_targets:
        raise ValueError(f"unknown benchmark target(s): {sorted(invalid_targets)}")


def _parse_int_list(raw: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in raw.split(",") if part.strip())


def _parse_targets(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run NeuroMouse MEA-scale performance budgets.")
    parser.add_argument("--channels", default=",".join(str(value) for value in CHANNEL_COUNTS))
    parser.add_argument("--records", default=",".join(str(value) for value in RECORD_LENGTHS))
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--targets", default=",".join(DEFAULT_TARGETS))
    parser.add_argument("--output-json", default="bench/perf-results.json")
    parser.add_argument("--output-markdown", default="bench/perf-report.md")
    parser.add_argument("--budget-multiplier", type=float, default=1.0)
    parser.add_argument(
        "--methods",
        action="store_true",
        help="Benchmark the MEA reference methods on the full 1024-channel golden traces.",
    )
    parser.add_argument("--method-targets", default=",".join(METHOD_TARGETS))
    parser.add_argument("--method-iterations", type=int, default=DEFAULT_METHOD_ITERATIONS)
    parser.add_argument("--method-warmups", type=int, default=DEFAULT_METHOD_WARMUPS)
    parser.add_argument("--channel-limit", type=int, default=None)
    return parser


def run_method_benchmarks(
    *,
    golden_path: str | Path = GOLDEN_MEA_PATH,
    methods: Sequence[str] = METHOD_TARGETS,
    iterations: int = DEFAULT_METHOD_ITERATIONS,
    warmups: int = DEFAULT_METHOD_WARMUPS,
    channel_limit: int | None = None,
    output_json: str | Path = Path("bench/method-perf-results.json"),
    output_markdown: str | Path | None = Path("bench/method-perf-report.md"),
    budget_multiplier: float = 1.0,
) -> BenchmarkReport:
    """Benchmark the MEA reference methods on the full 1024-channel golden traces.

    The detector runs first (positive polarity, recovering the injected ground-truth
    spikes); its detected spikes feed the burst/connectivity benchmarks, mirroring the
    real per-electrode-detector -> population-analysis pipeline.
    """
    _validate_method_run_config(methods, iterations, warmups)

    golden = _load_golden_mea(golden_path)
    channels, traces, sampling_rate_hz, duration_sec = _golden_trace_inputs(
        golden, channel_limit
    )
    trace_dataset = _MeaDataset(channels, {
        "sampling_rate_hz": sampling_rate_hz,
        "traces": traces,
        "duration_sec": duration_sec,
    })

    spike_detect = _load_method_module("spike_detect")
    spike_params = _method_params(spike_detect, {"polarity": "positive"})
    spike_result = spike_detect.method.compute(trace_dataset, spike_params)["spike_detect"]
    detected = {row["electrode"]: row["spike_times_sec"] for row in spike_result["spikes"]}
    recovered, expected = _spike_recovery(detected, golden, set(channels))

    spike_dataset = _MeaDataset(channels, {
        "spikes": detected,
        "duration_sec": duration_sec,
    })

    rows: list[BenchmarkRow] = []
    for name in methods:
        if name == "spike_detect":
            operation = _method_operation(spike_detect, trace_dataset, spike_params)
            row_recovered, row_expected = recovered, expected
        else:
            module = _load_method_module(name)
            operation = _method_operation(module, spike_dataset, _method_params(module, {}))
            row_recovered, row_expected = 0, 0

        rows.append(
            _benchmark_method(
                name,
                operation,
                channels=len(channels),
                record_samples=len(traces[0]),
                iterations=iterations,
                warmups=warmups,
                budget_multiplier=budget_multiplier,
                ground_truth_recovered=row_recovered,
                ground_truth_expected=row_expected,
            )
        )
        gc.collect()

    failures = [row for row in rows if not row.passed]
    hotspots = [_hotspot_for_row(row) for row in rows if not row.passed]
    hotspots.sort(key=lambda item: item["budget_ratio"], reverse=True)
    report = BenchmarkReport(
        results=rows,
        failures=failures,
        hotspots=hotspots,
        budgets={
            "golden_path": str(golden_path),
            "channels": len(channels),
            "record_samples": len(traces[0]),
            "iterations": iterations,
            "warmups": warmups,
            "targets": list(methods),
            "budget_multiplier": budget_multiplier,
            "p95_budget_ms": {name: METHOD_P95_BUDGET_MS[name] for name in methods},
            "spike_detect_ground_truth": {"recovered": recovered, "expected": expected},
            "notes": [
                "spike_detect runs on raw traces (positive polarity).",
                "network_burst / electrode_connectivity consume the detected spikes.",
                "spike_detect must recover all injected ground-truth spikes to pass.",
            ],
        },
    )

    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report.to_json(), indent=2) + "\n", encoding="utf-8")
    if output_markdown is not None:
        output_markdown = Path(output_markdown)
        output_markdown.parent.mkdir(parents=True, exist_ok=True)
        output_markdown.write_text(format_method_markdown_report(report), encoding="utf-8")
    return report


def format_method_markdown_report(report: BenchmarkReport) -> str:
    budgets = report.budgets
    gt = budgets.get("spike_detect_ground_truth", {})
    lines = [
        "# NeuroMouse MEA-Method Performance Bench",
        "",
        f"Workload: {budgets.get('channels')} channels x "
        f"{budgets.get('record_samples')} samples (golden raw traces).",
        f"Iterations: {budgets.get('iterations')} measured, "
        f"{budgets.get('warmups')} warmups.",
        f"spike_detect ground truth: {gt.get('recovered')}/{gt.get('expected')} spikes "
        "recovered.",
        "",
        "## Results",
        "",
        "| Method | p50 ms | p95 ms | Peak MB | Budget p95 ms | Ground truth | Status |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in report.results:
        status = "PASS" if row.passed else "FAIL"
        if row.target == "spike_detect":
            gt_cell = f"{row.ground_truth_recovered}/{row.ground_truth_expected}"
        else:
            gt_cell = "n/a"
        lines.append(
            "| "
            f"{row.target} | {row.p50_ms:.2f} | {row.p95_ms:.2f} | {row.peak_mb:.2f} | "
            f"{row.budget_p95_ms:.2f} | {gt_cell} | {status} |"
        )
    lines.append("")
    return "\n".join(lines)


class _MeaDataset:
    """Lightweight dataset view exposing ``meta.channels`` and ``mea`` like the contract."""

    __slots__ = ("meta", "mea")

    def __init__(self, channels: list[str], mea: dict[str, Any]) -> None:
        self.meta = SimpleNamespace(channels=channels)
        self.mea = mea


def _measure_method_operation(
    operation: Callable[[], Any],
    *,
    iterations: int,
    warmups: int,
) -> Measurement:
    """Measure latency without tracemalloc (which would inflate allocation-heavy Python),
    then measure peak operation memory in a single separate traced pass."""
    for _ in range(warmups):
        operation()
    gc.collect()

    timings_ms: list[float] = []
    for _ in range(iterations):
        gc.collect()
        started = time.perf_counter()
        result = operation()
        timings_ms.append((time.perf_counter() - started) * 1000.0)
        del result

    gc.collect()
    tracemalloc.start()
    traced = operation()
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del traced

    return Measurement(
        p50_ms=_percentile(timings_ms, 50),
        p95_ms=_percentile(timings_ms, 95),
        operation_peak_mb=float(peak_bytes) / BYTES_PER_MB,
    )


def _benchmark_method(
    name: str,
    operation: Callable[[], Any],
    *,
    channels: int,
    record_samples: int,
    iterations: int,
    warmups: int,
    budget_multiplier: float,
    ground_truth_recovered: int,
    ground_truth_expected: int,
) -> BenchmarkRow:
    measurement = _measure_method_operation(operation, iterations=iterations, warmups=warmups)
    budget_p95_ms = budget_multiplier * METHOD_P95_BUDGET_MS[name]
    budget_peak_mb = budget_multiplier * METHOD_PEAK_BUDGET_MB[name]
    ground_truth_ok = (
        ground_truth_expected == 0 or ground_truth_recovered == ground_truth_expected
    )
    passed = (
        measurement.p95_ms <= budget_p95_ms
        and measurement.operation_peak_mb <= budget_peak_mb
        and ground_truth_ok
    )
    return BenchmarkRow(
        target=name,
        channels=channels,
        record_samples=record_samples,
        iterations=iterations,
        p50_ms=measurement.p50_ms,
        p95_ms=measurement.p95_ms,
        peak_mb=measurement.operation_peak_mb,
        budget_p95_ms=budget_p95_ms,
        budget_peak_mb=budget_peak_mb,
        operation_peak_mb=measurement.operation_peak_mb,
        time_points=record_samples,
        file=f"methods/{name}.py",
        function="compute",
        passed=passed,
        ground_truth_recovered=ground_truth_recovered,
        ground_truth_expected=ground_truth_expected,
    )


def _validate_method_run_config(
    methods: Sequence[str],
    iterations: int,
    warmups: int,
) -> None:
    if not methods:
        raise ValueError("at least one method target is required")
    unknown = set(methods) - set(METHOD_TARGETS)
    if unknown:
        raise ValueError(f"unknown method target(s): {sorted(unknown)}")
    if iterations < 3:
        raise ValueError("at least 3 iterations are required to compute p95")
    if warmups < 0:
        raise ValueError("warmups cannot be negative")


def _load_golden_mea(golden_path: str | Path) -> dict[str, Any]:
    return json.loads(Path(golden_path).read_text(encoding="utf-8"))


def _golden_trace_inputs(
    golden: dict[str, Any],
    channel_limit: int | None,
) -> tuple[list[str], list[list[float]], float, float]:
    mea = golden["mea"]
    channels = list(golden["meta"]["channels"])
    traces = mea["traces"]
    if channel_limit is not None:
        channels = channels[:channel_limit]
        traces = traces[:channel_limit]
    sampling_rate_hz = float(mea["sampling_rate_hz"])
    duration_sec = len(traces[0]) / sampling_rate_hz
    return channels, traces, sampling_rate_hz, duration_sec


def _method_operation(module: Any, dataset: Any, params: Any) -> Callable[[], Any]:
    def operation() -> Any:
        return module.method.compute(dataset, params)

    return operation


def _method_params(module: Any, params: dict[str, Any]) -> Any:
    from neuromouse_sdk import build_params

    return build_params(module.method.params_type, params)


def _load_method_module(name: str) -> Any:
    import importlib.util

    path = REPO_ROOT / "methods" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"nm_bench_method_{name}", path)
    if spec is None or spec.loader is None:
        raise BenchmarkDependencyError(f"cannot load method plugin at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _spike_recovery(
    detected: dict[str, list[float]],
    golden: dict[str, Any],
    included_channels: set[str],
) -> tuple[int, int]:
    sampling_rate_hz = float(golden["mea"]["sampling_rate_hz"])
    expected: dict[str, list[float]] = {}
    for event in golden["spike_ground_truth"]["events"]:
        channel = event["channel"]
        if channel not in included_channels:
            continue
        expected.setdefault(channel, []).append(event["sample_index"] / sampling_rate_hz)

    matched = 0
    total = 0
    for channel, expected_times in expected.items():
        remaining = list(detected.get(channel, []))
        for expected_time in expected_times:
            total += 1
            if not remaining:
                continue
            closest = min(remaining, key=lambda actual: abs(actual - expected_time))
            if abs(closest - expected_time) <= SPIKE_MATCH_TOLERANCE_SEC:
                matched += 1
                remaining.remove(closest)
    return matched, total


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    markdown_path = Path(args.output_markdown) if args.output_markdown else None
    if args.methods:
        method_json = (
            args.output_json
            if args.output_json != "bench/perf-results.json"
            else "bench/method-perf-results.json"
        )
        method_md = (
            markdown_path
            if args.output_markdown not in (None, "bench/perf-report.md")
            else (None if markdown_path is None else Path("bench/method-perf-report.md"))
        )
        report = run_method_benchmarks(
            methods=_parse_targets(args.method_targets),
            iterations=args.method_iterations,
            warmups=args.method_warmups,
            channel_limit=args.channel_limit,
            output_json=Path(method_json),
            output_markdown=method_md,
            budget_multiplier=args.budget_multiplier,
        )
        print(format_method_markdown_report(report))
        return 1 if report.failures else 0
    report = run_benchmarks(
        channel_counts=_parse_int_list(args.channels),
        record_lengths=_parse_int_list(args.records),
        iterations=args.iterations,
        warmups=args.warmups,
        targets=_parse_targets(args.targets),
        output_json=Path(args.output_json),
        output_markdown=markdown_path,
        budget_multiplier=args.budget_multiplier,
    )
    print(format_markdown_report(report))
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
