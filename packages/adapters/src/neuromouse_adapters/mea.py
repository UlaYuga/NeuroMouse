from __future__ import annotations

import csv
import math
import random
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from neuromouse_adapters.file_replay import _dataset_from_signals

MEA_CSV_LAYOUT = (
    "csv-wide-v1: first column is time_sec or sample_index; remaining columns are "
    "MEA channel names with one numeric voltage per sample."
)
MEA_HDF5_LAYOUT = (
    "hdf5-signals-v1: /signals is a numeric 2D dataset, /channels is an optional "
    "string vector, /time_sec is optional, attrs.sampling_rate_hz is used when "
    "time_sec is absent, and attrs.axis_order is 'time,channel' or 'channel,time'."
)

_HDF5_SUFFIXES = {".h5", ".hdf5", ".brw"}
_SPIKEINTERFACE_READER_NAMES = ("read_maxwell", "read_biocam", "read_3brain")
_MAX_ANALYSIS_SAMPLES = 128
_MAX_SYNTHETIC_SAMPLES = 64
_SPIKE_TEMPLATE = {
    -2: -0.08,
    -1: -0.32,
    0: 1.0,
    1: -0.24,
    2: -0.08,
}


def read_mea(path: str | Path) -> dict:
    """Read an HD-MEA recording into the canonical NeuroMouse dataset shape.

    Vendor HD-MEA files are attempted through SpikeInterface first when it is
    installed, covering MaxWell ``.h5`` and BioCam/3Brain-style ``.brw`` inputs.
    Without optional readers, this supports the documented fallback layouts named
    by ``MEA_CSV_LAYOUT`` and ``MEA_HDF5_LAYOUT``.
    """
    source_path = Path(path)
    suffix = source_path.suffix.lower()
    if suffix == ".csv":
        return _read_wide_csv_mea(source_path)
    if suffix in _HDF5_SUFFIXES:
        spikeinterface_dataset = _read_with_spikeinterface(source_path)
        if spikeinterface_dataset is not None:
            return spikeinterface_dataset
        return _read_hdf5_mea(source_path)
    raise ValueError(f"unsupported MEA file format: {source_path.suffix or '<none>'}")


def make_synthetic_mea(
    n_channels: int,
    duration: float,
    seed: int,
    *,
    sampling_rate_hz: float = 1_000.0,
) -> dict:
    """Create deterministic synthetic HD-MEA summary data with known spikes."""
    channel_count = _positive_int(n_channels, "n_channels")
    duration_sec = _positive_float(duration, "duration")
    requested_rate_hz = _positive_float(sampling_rate_hz, "sampling_rate_hz")
    sample_count = _bounded_sample_count(duration_sec, requested_rate_hz)
    analysis_rate_hz = sample_count / duration_sec
    channels = [f"MEA-{index:04d}" for index in range(channel_count)]
    rng = random.Random(int(seed))
    samples_by_channel = _base_synthetic_samples(
        channel_count=channel_count,
        sample_count=sample_count,
        sampling_rate_hz=analysis_rate_hz,
        rng=rng,
    )
    events = _inject_known_spikes(
        samples_by_channel=samples_by_channel,
        channels=channels,
        duration_sec=duration_sec,
        sampling_rate_hz=analysis_rate_hz,
        rng=rng,
    )

    dataset = _dataset_from_signals(
        channels=channels,
        samples_by_channel=samples_by_channel,
        sampling_rate_hz=analysis_rate_hz,
        source=f"synthetic://hd-mea?n_channels={channel_count}&seed={int(seed)}",
    )
    dataset["meta"].update(
        {
            "analysis_by": "neuromouse_adapters.mea",
            "modality": "hd_mea",
            "mea": {
                "layout": "synthetic-hd-mea-v1",
                "sample_count": sample_count,
                "duration_sec": duration_sec,
                "requested_sampling_rate_hz": requested_rate_hz,
                "summary_sample_count": sample_count,
                "generator_seed": int(seed),
            },
        }
    )
    dataset["mea"] = {
        "sampling_rate_hz": analysis_rate_hz,
        "traces": samples_by_channel,
    }
    dataset["spike_ground_truth"] = {
        "schema": "synthetic-mea-spikes-v1",
        "seed": int(seed),
        "n_events": len(events),
        "events": events,
    }
    return dataset


def _read_wide_csv_mea(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("MEA CSV file is empty") from exc
        if len(header) < 2:
            raise ValueError("MEA CSV file must include at least one channel column")

        axis_name = header[0].strip().lower()
        channels = [_clean_channel_name(name, index) for index, name in enumerate(header[1:])]
        time_axis: list[float] = []
        samples_by_channel: list[list[float]] = [[] for _ in channels]
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) < len(header):
                raise ValueError(f"MEA CSV row {line_number} has fewer columns than the header")
            axis_value = _parse_number(row[0], f"MEA CSV row {line_number} axis")
            time_axis.append(axis_value)
            for channel_index, value in enumerate(row[1 : len(header)]):
                samples_by_channel[channel_index].append(
                    _parse_number(value, f"MEA CSV row {line_number} channel")
                )

    if not time_axis:
        raise ValueError("MEA CSV file has no samples")
    sampling_rate_hz = _sampling_rate_from_axis(axis_name, time_axis)
    raw_sample_count = len(time_axis)
    analysis_rows = _limit_samples(samples_by_channel, max_samples=_MAX_ANALYSIS_SAMPLES)
    dataset = _dataset_from_signals(
        channels=channels,
        samples_by_channel=analysis_rows,
        sampling_rate_hz=sampling_rate_hz,
        source=str(path),
    )
    _mark_mea_dataset(
        dataset,
        layout="csv-wide-v1",
        sample_count=raw_sample_count,
        analysis_sample_count=len(analysis_rows[0]),
        source_path=path,
        reader="csv",
    )
    return dataset


def _read_hdf5_mea(path: Path) -> dict:
    try:
        import h5py  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValueError(
            "h5py is required for documented HDF5 MEA fallback files; install "
            "neuromouse-adapters[mea] or provide csv-wide-v1"
        ) from exc

    with h5py.File(path, "r") as handle:
        if "signals" not in handle:
            raise ValueError(f"documented MEA HDF5 fallback requires /signals; {MEA_HDF5_LAYOUT}")
        signals = _to_nested_float_rows(handle["signals"][()])
        axis_order = _decode_scalar(handle.attrs.get("axis_order", "time,channel")).lower()
        if axis_order in {"channel,time", "channels,time"}:
            samples_by_channel = signals
        elif axis_order in {"time,channel", "time,channels"}:
            samples_by_channel = _transpose_time_major(signals)
        else:
            raise ValueError("MEA HDF5 attrs.axis_order must be 'time,channel' or 'channel,time'")

        sample_count = len(samples_by_channel[0]) if samples_by_channel else 0
        channels = _hdf5_channels(handle, channel_count=len(samples_by_channel))
        sampling_rate_hz = _hdf5_sampling_rate(handle, sample_count=sample_count)

    analysis_rows = _limit_samples(samples_by_channel, max_samples=_MAX_ANALYSIS_SAMPLES)
    dataset = _dataset_from_signals(
        channels=channels,
        samples_by_channel=analysis_rows,
        sampling_rate_hz=sampling_rate_hz,
        source=str(path),
    )
    _mark_mea_dataset(
        dataset,
        layout="hdf5-signals-v1",
        sample_count=sample_count,
        analysis_sample_count=len(analysis_rows[0]),
        source_path=path,
        reader="h5py",
    )
    return dataset


def _read_with_spikeinterface(path: Path) -> dict | None:
    try:
        import spikeinterface.extractors as se  # type: ignore[import-not-found]
    except Exception:
        return None

    for reader_name in _SPIKEINTERFACE_READER_NAMES:
        reader = getattr(se, reader_name, None)
        if reader is None:
            continue
        try:
            recording = _call_spikeinterface_reader(reader, path)
        except Exception:
            continue
        return _dataset_from_spikeinterface_recording(
            recording,
            source_path=path,
            reader_name=reader_name,
        )
    return None


def _call_spikeinterface_reader(reader: Any, path: Path) -> Any:
    try:
        return reader(str(path))
    except TypeError:
        return reader(file_path=str(path))


def _dataset_from_spikeinterface_recording(
    recording: Any,
    *,
    source_path: Path,
    reader_name: str,
) -> dict:
    channels = [str(channel_id) for channel_id in recording.get_channel_ids()]
    sampling_rate_hz = _positive_float(recording.get_sampling_frequency(), "sampling_rate_hz")
    sample_count = _spikeinterface_sample_count(recording)
    analysis_count = min(sample_count, _MAX_ANALYSIS_SAMPLES)
    traces = _spikeinterface_traces(recording, analysis_count=analysis_count)
    time_major = _to_nested_float_rows(traces)
    samples_by_channel = _transpose_time_major(time_major)
    dataset = _dataset_from_signals(
        channels=channels,
        samples_by_channel=samples_by_channel,
        sampling_rate_hz=sampling_rate_hz,
        source=str(source_path),
    )
    _mark_mea_dataset(
        dataset,
        layout="spikeinterface-recording",
        sample_count=sample_count,
        analysis_sample_count=analysis_count,
        source_path=source_path,
        reader=f"spikeinterface.{reader_name}",
    )
    return dataset


def _spikeinterface_sample_count(recording: Any) -> int:
    for name in ("get_num_samples", "get_num_frames"):
        method = getattr(recording, name, None)
        if method is None:
            continue
        try:
            return _positive_int(method(segment_index=0), name)
        except TypeError:
            return _positive_int(method(), name)
    raise ValueError("SpikeInterface recording did not expose a sample count")


def _spikeinterface_traces(recording: Any, *, analysis_count: int) -> Any:
    try:
        return recording.get_traces(
            start_frame=0,
            end_frame=analysis_count,
            segment_index=0,
            return_scaled=True,
        )
    except TypeError:
        try:
            return recording.get_traces(
                start_frame=0,
                end_frame=analysis_count,
                segment_index=0,
            )
        except TypeError:
            return recording.get_traces(start_frame=0, end_frame=analysis_count)


def _mark_mea_dataset(
    dataset: dict,
    *,
    layout: str,
    sample_count: int,
    analysis_sample_count: int,
    source_path: Path,
    reader: str,
) -> None:
    dataset["meta"].update(
        {
            "analysis_by": "neuromouse_adapters.mea",
            "modality": "hd_mea",
            "mea": {
                "layout": layout,
                "sample_count": int(sample_count),
                "analysis_sample_count": int(analysis_sample_count),
                "reader": reader,
                "supported_csv_layout": MEA_CSV_LAYOUT,
                "supported_hdf5_layout": MEA_HDF5_LAYOUT,
                "source_name": source_path.name,
            },
        }
    )


def _hdf5_channels(handle: Any, *, channel_count: int) -> list[str]:
    if "channels" in handle:
        raw_channels = handle["channels"][()]
        values = raw_channels.tolist() if hasattr(raw_channels, "tolist") else raw_channels
        channels = [
            _clean_channel_name(_decode_scalar(value), index)
            for index, value in enumerate(values)
        ]
        if len(channels) != channel_count:
            raise ValueError("MEA HDF5 /channels length must match /signals channel count")
        return channels
    attr_channels = handle.attrs.get("channels")
    if attr_channels is not None:
        values = attr_channels.tolist() if hasattr(attr_channels, "tolist") else attr_channels
        if isinstance(values, str | bytes):
            split_values: Iterable[Any] = _decode_scalar(values).split(",")
        else:
            split_values = values
        channels = [
            _clean_channel_name(_decode_scalar(value), index)
            for index, value in enumerate(split_values)
        ]
        if len(channels) != channel_count:
            raise ValueError("MEA HDF5 attrs.channels length must match /signals channel count")
        return channels
    return [f"MEA-{index:04d}" for index in range(channel_count)]


def _hdf5_sampling_rate(handle: Any, *, sample_count: int) -> float:
    if "time_sec" in handle:
        time_axis_raw = handle["time_sec"][()]
        time_axis = _to_float_list(time_axis_raw)
        if len(time_axis) != sample_count:
            raise ValueError("MEA HDF5 /time_sec length must match /signals sample count")
        return _sampling_rate_from_axis("time_sec", time_axis)
    if "sampling_rate_hz" in handle.attrs:
        return _positive_float(handle.attrs["sampling_rate_hz"], "sampling_rate_hz")
    raise ValueError("MEA HDF5 requires attrs.sampling_rate_hz when /time_sec is absent")


def _base_synthetic_samples(
    *,
    channel_count: int,
    sample_count: int,
    sampling_rate_hz: float,
    rng: random.Random,
) -> list[list[float]]:
    samples_by_channel: list[list[float]] = []
    for channel_index in range(channel_count):
        fast_hz = 12.0 + (channel_index % 29) * 0.5
        slow_hz = 1.5 + (channel_index % 7) * 0.25
        phase = rng.random() * 2.0 * math.pi
        amplitude = 0.025 + (channel_index % 13) * 0.001
        samples = [
            amplitude
            * math.sin((2.0 * math.pi * fast_hz * sample_index / sampling_rate_hz) + phase)
            + 0.008
            * math.sin((2.0 * math.pi * slow_hz * sample_index / sampling_rate_hz) + phase / 2.0)
            for sample_index in range(sample_count)
        ]
        samples_by_channel.append(samples)
    return samples_by_channel


def _inject_known_spikes(
    *,
    samples_by_channel: list[list[float]],
    channels: Sequence[str],
    duration_sec: float,
    sampling_rate_hz: float,
    rng: random.Random,
) -> list[dict[str, float | int | str]]:
    channel_count = len(channels)
    sample_count = len(samples_by_channel[0])
    event_channel_count = min(channel_count, max(1, min(32, channel_count // 16 or 1)))
    if event_channel_count == channel_count:
        event_channels = list(range(channel_count))
    else:
        event_channels = sorted(rng.sample(range(channel_count), event_channel_count))

    centers = _spike_centers(sample_count)
    events: list[dict[str, float | int | str]] = []
    for event_channel in event_channels:
        events_per_channel = min(len(centers), 1 + (event_channel % 3))
        for event_order, center in enumerate(centers[:events_per_channel]):
            jitter = rng.randint(-1, 1) if sample_count > 10 else 0
            sample_index = min(sample_count - 2, max(1, center + jitter))
            amplitude_uv = 0.65 + rng.random() * 0.35
            for offset, weight in _SPIKE_TEMPLATE.items():
                target = sample_index + offset
                if 0 <= target < sample_count:
                    samples_by_channel[event_channel][target] += amplitude_uv * weight
            events.append(
                {
                    "channel": channels[event_channel],
                    "channel_index": event_channel,
                    "sample_index": sample_index,
                    "time_sec": sample_index / sampling_rate_hz,
                    "amplitude_uV": amplitude_uv,
                    "template": "biphasic-positive-v1",
                    "event_order": event_order,
                }
            )
    events.sort(key=lambda event: (event["sample_index"], event["channel_index"]))
    return events


def _spike_centers(sample_count: int) -> list[int]:
    raw_centers = [sample_count // 4, sample_count // 2, (3 * sample_count) // 4]
    centers = sorted({min(sample_count - 2, max(1, center)) for center in raw_centers})
    return centers or [1]


def _bounded_sample_count(duration_sec: float, sampling_rate_hz: float) -> int:
    requested = int(round(duration_sec * sampling_rate_hz))
    requested = max(8, requested)
    return min(_MAX_SYNTHETIC_SAMPLES, requested)


def _limit_samples(rows: list[list[float]], *, max_samples: int) -> list[list[float]]:
    if not rows:
        raise ValueError("MEA data must include at least one channel")
    width = min(len(row) for row in rows)
    if width <= 0:
        raise ValueError("MEA data channels must contain at least one sample")
    kept = min(width, max_samples)
    return [row[:kept] for row in rows]


def _transpose_time_major(rows: list[list[float]]) -> list[list[float]]:
    if not rows:
        raise ValueError("MEA data must include at least one sample")
    width = len(rows[0])
    if width <= 0:
        raise ValueError("MEA data must include at least one channel")
    if any(len(row) != width for row in rows):
        raise ValueError("MEA time-major rows must have equal channel width")
    return [[float(row[channel_index]) for row in rows] for channel_index in range(width)]


def _to_nested_float_rows(value: Any) -> list[list[float]]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, list) or not value:
        raise ValueError("MEA signals must be a non-empty 2D numeric array")
    rows: list[list[float]] = []
    for row_index, row in enumerate(value):
        if hasattr(row, "tolist"):
            row = row.tolist()
        if not isinstance(row, list) or not row:
            raise ValueError(f"MEA signals row {row_index} must be a non-empty numeric array")
        rows.append([_finite_float(item, f"MEA signals row {row_index}") for item in row])
    return rows


def _to_float_list(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, list):
        raise ValueError("MEA axis must be a numeric array")
    return [_finite_float(item, "MEA axis") for item in value]


def _sampling_rate_from_axis(axis_name: str, axis: list[float]) -> float:
    if "sample" in axis_name and "time" not in axis_name:
        return 1.0
    if len(axis) < 2:
        return 1.0
    deltas = [
        later - earlier
        for earlier, later in zip(axis, axis[1:], strict=False)
        if math.isfinite(later - earlier) and later > earlier
    ]
    if not deltas:
        return 1.0
    ordered = sorted(deltas)
    median_delta = ordered[len(ordered) // 2]
    return 1.0 / median_delta if median_delta > 0 else 1.0


def _parse_number(value: str, field_name: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    return _finite_float(number, field_name)


def _finite_float(value: Any, field_name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _clean_channel_name(name: object, index: int) -> str:
    clean = str(name).strip()
    return clean or f"MEA-{index:04d}"


def _decode_scalar(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if hasattr(value, "item"):
        try:
            return _decode_scalar(value.item())
        except ValueError:
            pass
    return str(value)


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or int(value) != value or int(value) <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _positive_float(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return number
