from __future__ import annotations

import csv
import math
import struct
from pathlib import Path
from typing import Any

_EPSILON = 1e-12
_GEOMETRY_KEYS = (
    "centroid",
    "spread",
    "entropy",
    "flatness",
    "edge95",
    "alpha_relative_power",
)


def read_file(path: str | Path) -> dict:
    """Read a replay file into the canonical NeuroMouse dataset shape."""
    source_path = Path(path)
    suffix = source_path.suffix.lower()
    if suffix == ".csv":
        return _read_csv(source_path)
    if suffix in {".edf", ".bdf"}:
        return _read_edf_bdf(source_path)
    raise ValueError(f"unsupported replay file format: {source_path.suffix or '<none>'}")


def _read_csv(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("CSV replay file is empty") from exc

        if len(header) < 2:
            raise ValueError("CSV replay file must include at least one channel column")

        axis_name = header[0].strip().lower()
        channels = [_clean_channel_name(name, index) for index, name in enumerate(header[1:])]
        if not channels:
            raise ValueError("CSV replay file must include at least one channel")

        axis: list[float] = []
        columns: list[list[float]] = [[] for _ in channels]
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) < len(header):
                raise ValueError(f"CSV row {line_number} has fewer columns than the header")
            axis.append(_parse_number(row[0], f"CSV row {line_number} axis"))
            for index, value in enumerate(row[1 : len(header)]):
                columns[index].append(_parse_number(value, f"CSV row {line_number} channel"))

    if not axis:
        raise ValueError("CSV replay file has no samples")

    if _is_frequency_axis(axis_name):
        psd = [[max(0.0, value) for value in column] for column in columns]
        return _dataset_from_psd(
            channels=channels,
            frequencies=axis,
            psd_by_channel=psd,
            sampling_rate_hz=None,
            source=str(path),
        )

    sampling_rate_hz = _infer_sampling_rate(axis)
    return _dataset_from_signals(
        channels=channels,
        samples_by_channel=columns,
        sampling_rate_hz=sampling_rate_hz,
        source=str(path),
    )


def _read_edf_bdf(path: Path) -> dict:
    payload = path.read_bytes()
    if len(payload) < 256:
        raise ValueError("EDF/BDF file is too small to contain a header")

    header_bytes = _parse_int_field(payload[184:192], "header byte count")
    record_count = _parse_int_field(payload[236:244], "data record count")
    record_duration_sec = _parse_float_field(payload[244:252], "data record duration")
    signal_count = _parse_int_field(payload[252:256], "signal count")
    if signal_count <= 0:
        raise ValueError("EDF/BDF file must contain at least one signal")
    if header_bytes < 256 + signal_count * 256:
        raise ValueError("EDF/BDF header byte count is smaller than the signal header")
    if record_duration_sec <= 0:
        raise ValueError("EDF/BDF data record duration must be positive")

    offset = 256
    labels, offset = _read_edf_signal_fields(payload, offset, signal_count, 16)
    _, offset = _read_edf_signal_fields(payload, offset, signal_count, 80)
    _, offset = _read_edf_signal_fields(payload, offset, signal_count, 8)
    physical_min, offset = _read_edf_float_fields(payload, offset, signal_count, 8, "physical min")
    physical_max, offset = _read_edf_float_fields(payload, offset, signal_count, 8, "physical max")
    digital_min, offset = _read_edf_int_fields(payload, offset, signal_count, 8, "digital min")
    digital_max, offset = _read_edf_int_fields(payload, offset, signal_count, 8, "digital max")
    _, offset = _read_edf_signal_fields(payload, offset, signal_count, 80)
    samples_per_record, offset = _read_edf_int_fields(
        payload, offset, signal_count, 8, "samples per data record"
    )

    bytes_per_sample = 3 if path.suffix.lower() == ".bdf" else 2
    bytes_per_record = sum(samples_per_record) * bytes_per_sample
    if record_count < 0:
        available = len(payload) - header_bytes
        record_count = available // bytes_per_record if bytes_per_record > 0 else 0
    if record_count <= 0:
        raise ValueError("EDF/BDF file has no data records")

    kept_indexes = [
        index
        for index, label in enumerate(labels)
        if "annotation" not in label.strip().lower() and samples_per_record[index] > 0
    ]
    if not kept_indexes:
        raise ValueError("EDF/BDF file must contain at least one EEG signal")

    samples_by_signal: list[list[float]] = [[] for _ in labels]
    cursor = header_bytes
    for _ in range(record_count):
        for signal_index in range(signal_count):
            count = samples_per_record[signal_index]
            for _ in range(count):
                if cursor + bytes_per_sample > len(payload):
                    raise ValueError("EDF/BDF data ended before all records were read")
                if bytes_per_sample == 2:
                    digital = struct.unpack_from("<h", payload, cursor)[0]
                else:
                    digital = _read_int24_le(payload[cursor : cursor + 3])
                cursor += bytes_per_sample
                if signal_index in kept_indexes:
                    samples_by_signal[signal_index].append(
                        _digital_to_physical(
                            digital=digital,
                            digital_min=digital_min[signal_index],
                            digital_max=digital_max[signal_index],
                            physical_min=physical_min[signal_index],
                            physical_max=physical_max[signal_index],
                        )
                    )

    channels = [_clean_channel_name(labels[index], index) for index in kept_indexes]
    samples_by_channel = [samples_by_signal[index] for index in kept_indexes]
    sampling_rate_hz = samples_per_record[kept_indexes[0]] / record_duration_sec
    return _dataset_from_signals(
        channels=channels,
        samples_by_channel=samples_by_channel,
        sampling_rate_hz=sampling_rate_hz,
        source=str(path),
    )


def _dataset_from_signals(
    *,
    channels: list[str],
    samples_by_channel: list[list[float]],
    sampling_rate_hz: float,
    source: str,
) -> dict:
    _validate_channel_data(channels, samples_by_channel)
    sample_count = min(len(samples) for samples in samples_by_channel)
    if sample_count <= 0:
        raise ValueError("replay file channels must contain at least one sample")

    aligned = [samples[:sample_count] for samples in samples_by_channel]
    frequencies, psd_by_channel = _welch_psd(aligned, sampling_rate_hz)
    segment_duration_sec = sample_count / sampling_rate_hz if sampling_rate_hz > 0 else None
    return _dataset_from_psd(
        channels=channels,
        frequencies=frequencies,
        psd_by_channel=psd_by_channel,
        sampling_rate_hz=sampling_rate_hz,
        source=source,
        segment_duration_sec=segment_duration_sec,
    )


def _dataset_from_psd(
    *,
    channels: list[str],
    frequencies: list[float],
    psd_by_channel: list[list[float]],
    sampling_rate_hz: float | None,
    source: str,
    segment_duration_sec: float | None = None,
) -> dict:
    _validate_channel_data(channels, psd_by_channel)
    if not frequencies:
        raise ValueError("PSD frequency axis must be non-empty")

    clean_frequencies = [float(frequency) for frequency in frequencies]
    clean_psd = [
        [_finite_non_negative(value) for value in row[: len(clean_frequencies)]]
        for row in psd_by_channel
    ]
    if any(len(row) != len(clean_frequencies) for row in clean_psd):
        raise ValueError("PSD rows must match the frequency axis length")

    metrics = [_spectral_metrics(clean_frequencies, row) for row in clean_psd]
    time_axis = [0.0]
    geometry: dict[str, Any] = {"time": time_axis}
    for key in _GEOMETRY_KEYS:
        geometry[key] = [[metric[key]] for metric in metrics]
    geometry["area_normalized_psd"] = {
        "frequencies": clean_frequencies,
        "psd": [_normalize_area(row) for row in clean_psd],
    }

    meta: dict[str, Any] = {
        "channels": channels,
        "n_channels": len(channels),
        "source": source,
        "analysis_by": "neuromouse_adapters.file_replay",
    }
    if sampling_rate_hz is not None:
        meta["sampling_rate_analysis_hz"] = sampling_rate_hz
    if segment_duration_sec is not None:
        meta["segment_duration_sec"] = segment_duration_sec

    return {
        "meta": meta,
        "welch_psd": {
            "frequencies": clean_frequencies,
            "psd": clean_psd,
        },
        "centroid": {
            "time_relative": time_axis,
            "values": [[metric["centroid"]] for metric in metrics],
        },
        "geometry": geometry,
        "channel_summary": [
            _channel_summary(channel, metric)
            for channel, metric in zip(channels, metrics, strict=True)
        ],
    }


def _welch_psd(
    samples_by_channel: list[list[float]], sampling_rate_hz: float
) -> tuple[list[float], list[list[float]]]:
    sampling_rate_hz = sampling_rate_hz if sampling_rate_hz > 0 else 1.0
    sample_count = min(len(samples) for samples in samples_by_channel)
    window_size = max(1, sample_count)
    frequencies = [index * sampling_rate_hz / window_size for index in range(window_size // 2 + 1)]
    psd_by_channel = [
        _single_segment_psd(samples[:window_size], sampling_rate_hz)
        for samples in samples_by_channel
    ]
    return frequencies, psd_by_channel


def _single_segment_psd(samples: list[float], sampling_rate_hz: float) -> list[float]:
    if not samples:
        return [0.0]

    mean = sum(samples) / len(samples)
    centered = [sample - mean for sample in samples]
    if len(centered) == 1:
        return [0.0]

    window = [
        0.5 - 0.5 * math.cos((2.0 * math.pi * index) / (len(centered) - 1))
        for index in range(len(centered))
    ]
    windowed = [sample * taper for sample, taper in zip(centered, window, strict=True)]
    scale = sampling_rate_hz * (sum(taper * taper for taper in window) or 1.0)
    psd: list[float] = []
    for frequency_index in range(len(centered) // 2 + 1):
        real = 0.0
        imaginary = 0.0
        for sample_index, sample in enumerate(windowed):
            angle = -2.0 * math.pi * frequency_index * sample_index / len(centered)
            real += sample * math.cos(angle)
            imaginary += sample * math.sin(angle)
        psd.append((real * real + imaginary * imaginary) / scale)
    return psd


def _spectral_metrics(frequencies: list[float], psd: list[float]) -> dict[str, float | bool]:
    total_power = sum(psd)
    if total_power <= _EPSILON:
        return {
            "centroid": 0.0,
            "spread": 0.0,
            "entropy": 0.0,
            "flatness": 0.0,
            "edge95": 0.0,
            "alpha_relative_power": 0.0,
            "alpha_peak_frequency_hz": 0.0,
            "has_clear_alpha_peak": False,
        }

    centroid = (
        sum(frequency * power for frequency, power in zip(frequencies, psd, strict=True))
        / total_power
    )
    spread = math.sqrt(
        sum(
            ((frequency - centroid) ** 2) * power
            for frequency, power in zip(frequencies, psd, strict=True)
        )
        / total_power
    )
    probabilities = [power / total_power for power in psd if power > _EPSILON]
    entropy = 0.0
    if len(psd) > 1 and probabilities:
        entropy = -sum(
            probability * math.log(probability) for probability in probabilities
        ) / math.log(len(psd))

    arithmetic_mean = total_power / len(psd)
    geometric_mean = math.exp(sum(math.log(max(power, _EPSILON)) for power in psd) / len(psd))
    flatness = geometric_mean / (arithmetic_mean + _EPSILON)

    cumulative = 0.0
    edge95 = frequencies[-1]
    for frequency, power in zip(frequencies, psd, strict=True):
        cumulative += power
        if cumulative >= total_power * 0.95:
            edge95 = frequency
            break

    alpha_bins = [
        (frequency, power)
        for frequency, power in zip(frequencies, psd, strict=True)
        if 8.0 <= frequency <= 13.0
    ]
    alpha_power = sum(power for _, power in alpha_bins)
    alpha_relative = alpha_power / total_power
    alpha_peak_frequency = 0.0
    if alpha_bins:
        alpha_peak_frequency = max(alpha_bins, key=lambda item: item[1])[0]

    return {
        "centroid": _finite(centroid),
        "spread": _finite(spread),
        "entropy": _finite(entropy),
        "flatness": _finite(flatness),
        "edge95": _finite(edge95),
        "alpha_relative_power": _finite(alpha_relative),
        "alpha_peak_frequency_hz": _finite(alpha_peak_frequency),
        "has_clear_alpha_peak": bool(alpha_relative >= 0.2 and alpha_peak_frequency > 0.0),
    }


def _channel_summary(channel: str, metric: dict[str, float | bool]) -> dict:
    return {
        "channel": channel,
        "hemisphere": _infer_hemisphere(channel),
        "region": _infer_region(channel),
        "has_clear_alpha_peak": metric["has_clear_alpha_peak"],
        "alpha_relative_power": metric["alpha_relative_power"],
        "spectral_centroid_hz": metric["centroid"],
        "spectral_spread_hz": metric["spread"],
        "spectral_entropy": metric["entropy"],
        "spectral_flatness": metric["flatness"],
        "edge95_hz": metric["edge95"],
        "alpha_peak_frequency_hz": metric["alpha_peak_frequency_hz"],
        "sliding_alpha_relative_mean": metric["alpha_relative_power"],
    }


def _normalize_area(row: list[float]) -> list[float]:
    total = sum(row)
    if total <= _EPSILON:
        return [0.0 for _ in row]
    return [value / total for value in row]


def _validate_channel_data(channels: list[str], rows: list[list[float]]) -> None:
    if not channels:
        raise ValueError("replay file must include at least one channel")
    if len(rows) != len(channels):
        raise ValueError("channel-major rows must match meta.channels")


def _infer_sampling_rate(axis: list[float]) -> float:
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


def _is_frequency_axis(axis_name: str) -> bool:
    return "freq" in axis_name or "hz" in axis_name


def _clean_channel_name(name: str, index: int) -> str:
    clean = str(name).strip()
    return clean or f"Ch{index + 1}"


def _infer_hemisphere(channel: str) -> str:
    name = channel.strip().lower()
    if name.endswith("z"):
        return "M"
    digits = "".join(character for character in reversed(name) if character.isdigit())
    if digits:
        number = int(digits[::-1])
        return "L" if number % 2 else "R"
    return ""


def _infer_region(channel: str) -> str:
    name = channel.strip().lower()
    if name.startswith(("fp", "af", "f")):
        return "frontal"
    if name.startswith("c"):
        return "central"
    if name.startswith("p"):
        return "parietal"
    if name.startswith("o"):
        return "occipital"
    if name.startswith("t"):
        return "temporal"
    return ""


def _parse_number(value: str, field_name: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    return _finite(number)


def _finite(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return float(value)


def _finite_non_negative(value: float) -> float:
    return max(0.0, _finite(float(value)))


def _read_edf_signal_fields(
    payload: bytes, offset: int, signal_count: int, width: int
) -> tuple[list[str], int]:
    values = []
    for index in range(signal_count):
        start = offset + index * width
        values.append(payload[start : start + width].decode("latin-1").strip())
    return values, offset + signal_count * width


def _read_edf_float_fields(
    payload: bytes, offset: int, signal_count: int, width: int, field_name: str
) -> tuple[list[float], int]:
    values, next_offset = _read_edf_signal_fields(payload, offset, signal_count, width)
    return [_parse_float_text(value, field_name) for value in values], next_offset


def _read_edf_int_fields(
    payload: bytes, offset: int, signal_count: int, width: int, field_name: str
) -> tuple[list[int], int]:
    values, next_offset = _read_edf_signal_fields(payload, offset, signal_count, width)
    return [_parse_int_text(value, field_name) for value in values], next_offset


def _parse_int_field(raw: bytes, field_name: str) -> int:
    return _parse_int_text(raw.decode("latin-1").strip(), field_name)


def _parse_float_field(raw: bytes, field_name: str) -> float:
    return _parse_float_text(raw.decode("latin-1").strip(), field_name)


def _parse_int_text(value: str, field_name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"EDF/BDF {field_name} must be an integer") from exc


def _parse_float_text(value: str, field_name: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"EDF/BDF {field_name} must be numeric") from exc


def _read_int24_le(raw: bytes) -> int:
    value = raw[0] | (raw[1] << 8) | (raw[2] << 16)
    if value & 0x800000:
        value -= 1 << 24
    return value


def _digital_to_physical(
    *,
    digital: int,
    digital_min: int,
    digital_max: int,
    physical_min: float,
    physical_max: float,
) -> float:
    if digital_max == digital_min:
        return float(digital)
    scale = (physical_max - physical_min) / (digital_max - digital_min)
    return physical_min + ((digital - digital_min) * scale)
