from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator


class DatasetValidationError(ValueError):
    """Raised when a data.json object violates the executable contract."""


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Meta(ContractModel):
    channels: list[str]
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
    frequencies: list[float]
    psd: list[list[float]]


class Centroid(ContractModel):
    time_relative: list[float]
    values: list[list[float]]


class Geometry(ContractModel):
    time: list[float]
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
    def enforce_documented_hard_rules(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        channels = _get_nested(value, "meta", "channels")
        if not isinstance(channels, list) or len(channels) == 0:
            raise ValueError("data.json must contain a non-empty meta.channels array")
        channel_count = len(channels)

        welch_frequencies = _get_nested(value, "welch_psd", "frequencies")
        welch_psd = _get_nested(value, "welch_psd", "psd")
        if not isinstance(welch_frequencies, list) or not isinstance(welch_psd, list):
            raise ValueError("data.json is missing welch_psd arrays")
        if len(welch_psd) != channel_count:
            raise ValueError(
                f"welch_psd.psd has {len(welch_psd)} channel rows "
                f"but meta.channels lists {channel_count}"
            )

        centroid_time = _get_nested(value, "centroid", "time_relative")
        centroid_values = _get_nested(value, "centroid", "values")
        if not isinstance(centroid_time, list) or not isinstance(centroid_values, list):
            raise ValueError("data.json is missing centroid arrays")
        if len(centroid_values) != channel_count:
            raise ValueError(
                f"centroid.values has {len(centroid_values)} channel rows "
                f"but meta.channels lists {channel_count}"
            )

        geometry_time = _get_nested(value, "geometry", "time")
        if not isinstance(geometry_time, list):
            raise ValueError("data.json is missing geometry.time")

        return value


def validate_dataset(obj: Any) -> Dataset:
    try:
        return Dataset.model_validate(obj)
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
