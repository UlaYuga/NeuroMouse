from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    model_validator,
)

DEFAULT_MAX_CHANNELS = 4096
NonEmptyFloatList = Annotated[list[float], Field(min_length=1)]
NonEmptyStringList = Annotated[list[str], Field(min_length=1)]


class DatasetValidationError(ValueError):
    """Raised when a data.json object violates the executable contract."""


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Meta(ContractModel):
    channels: NonEmptyStringList
    n_channels: int | None = None
    segment_duration_sec: float | None = None
    sampling_rate_analysis_hz: float | None = None
    welch_window_sec: float | None = None
    welch_overlap_fraction: float | None = None
    sliding_window_sec: float | None = None
    sliding_step_sec: float | None = None
    source: str | None = None
    analysis_by: str | None = None


class WelchPsd(ContractModel):
    frequencies: NonEmptyFloatList
    psd: list[list[float]]


class Centroid(ContractModel):
    time_relative: NonEmptyFloatList
    values: list[list[float]]


class Geometry(ContractModel):
    time: NonEmptyFloatList
    centroid: list[list[float]] | None = None
    spread: list[list[float]] | None = None
    entropy: list[list[float]] | None = None
    flatness: list[list[float]] | None = None
    edge95: list[list[float]] | None = None
    alpha_relative_power: list[list[float]] | None = None
    area_normalized_psd: WelchPsd | None = None


class ChannelSummary(ContractModel):
    channel: str
    hemisphere: Literal["L", "R", "M", ""] | None = None
    region: str | None = None
    has_clear_alpha_peak: bool | None = None
    alpha_relative_power: float | None = None
    spectral_centroid_hz: float | None = None
    spectral_spread_hz: float | None = None
    spectral_entropy: float | None = None
    spectral_flatness: float | None = None
    edge95_hz: float | None = None
    alpha_peak_frequency_hz: float | None = None
    sliding_alpha_relative_mean: float | None = None


class Dataset(ContractModel):
    meta: Meta
    welch_psd: WelchPsd
    centroid: Centroid
    geometry: Geometry
    channel_summary: list[ChannelSummary] | None = None

    @model_validator(mode="before")
    @classmethod
    def enforce_documented_hard_rules(cls, value: Any, info: ValidationInfo) -> Any:
        if not isinstance(value, Mapping):
            return value

        channels = _get_nested(value, "meta", "channels")
        if not isinstance(channels, list) or len(channels) == 0:
            raise ValueError("data.json must contain a non-empty meta.channels array")
        channel_count = len(channels)
        max_channels = _max_channel_count(info)
        if channel_count > max_channels:
            raise ValueError(f"meta.channels length must be at most {max_channels}")

        meta = value.get("meta")
        n_channels_present = isinstance(meta, Mapping) and "n_channels" in meta
        if n_channels_present:
            n_channels = meta.get("n_channels")
            if not _is_positive_integer(n_channels):
                raise ValueError("meta.n_channels must be a positive integer")
            if n_channels != channel_count:
                raise ValueError("meta.n_channels must equal meta.channels length")

        welch_frequencies = _get_nested(value, "welch_psd", "frequencies")
        welch_psd = _get_nested(value, "welch_psd", "psd")
        if not isinstance(welch_frequencies, list) or not isinstance(welch_psd, list):
            raise ValueError("data.json is missing welch_psd arrays")
        if len(welch_frequencies) == 0:
            raise ValueError("welch_psd.frequencies must be a non-empty array")
        _require_finite_numbers(
            welch_frequencies,
            "welch_psd.frequencies must contain only finite numbers",
        )
        if len(welch_psd) != channel_count:
            raise ValueError(
                f"welch_psd.psd has {len(welch_psd)} channel rows "
                f"but meta.channels lists {channel_count}"
            )
        _require_matrix_rows(
            welch_psd,
            expected_width=len(welch_frequencies),
            label="welch_psd.psd",
            width_label="welch_psd.frequencies length",
        )

        centroid_time = _get_nested(value, "centroid", "time_relative")
        centroid_values = _get_nested(value, "centroid", "values")
        if not isinstance(centroid_time, list) or not isinstance(centroid_values, list):
            raise ValueError("data.json is missing centroid arrays")
        if len(centroid_time) == 0:
            raise ValueError("centroid.time_relative must be a non-empty array")
        if len(centroid_values) != channel_count:
            raise ValueError(
                f"centroid.values has {len(centroid_values)} channel rows "
                f"but meta.channels lists {channel_count}"
            )
        _require_matrix_rows(
            centroid_values,
            expected_width=len(centroid_time),
            label="centroid.values",
            width_label="centroid.time_relative length",
        )

        geometry_time = _get_nested(value, "geometry", "time")
        if not isinstance(geometry_time, list):
            raise ValueError("data.json is missing geometry.time")
        if len(geometry_time) == 0:
            raise ValueError("geometry.time must be a non-empty array")
        _require_finite_numbers(
            geometry_time,
            "geometry.time must contain only finite numbers",
        )

        return value


def validate_dataset(obj: Any, *, max_channels: int = DEFAULT_MAX_CHANNELS) -> Dataset:
    try:
        return Dataset.model_validate(obj, context={"max_channels": max_channels})
    except ValidationError as exc:
        raise DatasetValidationError(_clear_validation_message(exc)) from exc


def emit_dataset_schema(path: str | Path | None = None) -> Path:
    target = Path(path) if path is not None else _default_schema_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(Dataset.model_json_schema(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return target


def _default_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schema" / "dataset.schema.json"


def _get_nested(value: Mapping[str, Any], first: str, second: str) -> Any:
    child = value.get(first)
    if not isinstance(child, Mapping):
        return None
    return child.get(second)


def _max_channel_count(info: ValidationInfo) -> int:
    raw_max_channels = None
    if isinstance(info.context, Mapping):
        raw_max_channels = info.context.get("max_channels")
    if raw_max_channels is None:
        return DEFAULT_MAX_CHANNELS
    if not _is_positive_integer(raw_max_channels):
        raise ValueError("max_channels must be a positive integer")
    return raw_max_channels


def _is_positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _require_finite_numbers(values: list[Any], message: str) -> None:
    for value in values:
        if not _is_finite_number(value):
            raise ValueError(message)


def _require_matrix_rows(
    rows: list[Any],
    *,
    expected_width: int,
    label: str,
    width_label: str,
) -> None:
    for index, row in enumerate(rows):
        if not isinstance(row, list):
            raise ValueError(f"{label} row {index} must be an array")
        if len(row) != expected_width:
            raise ValueError(f"{label} row {index} length must equal {width_label}")
        _require_finite_numbers(
            row,
            f"{label} row {index} must contain only finite numbers",
        )


def _clear_validation_message(exc: ValidationError) -> str:
    for error in exc.errors():
        cause = error.get("ctx", {}).get("error")
        if isinstance(cause, ValueError):
            return str(cause)
    first = exc.errors()[0] if exc.errors() else None
    if first is None:
        return str(exc)
    location = ".".join(str(part) for part in first.get("loc", ()))
    message = first.get("msg", str(exc))
    return f"{location}: {message}" if location else message
