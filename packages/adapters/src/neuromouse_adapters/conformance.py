from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any

from neuromouse_contract import DatasetValidationError, validate_dataset

_GEOMETRY_CHANNEL_MAJOR_KEYS = (
    "centroid",
    "spread",
    "entropy",
    "flatness",
    "edge95",
    "alpha_relative_power",
)


def assert_adapter_conforms(dataset: dict, *, adapter_name: str = "adapter") -> None:
    """Assert that an adapter output follows the NeuroMouse dataset contract."""
    try:
        validate_dataset(dataset)
    except DatasetValidationError as exc:
        raise AssertionError(f"{adapter_name} violates neuromouse_contract: {exc}") from exc

    root = _as_mapping(dataset, adapter_name)
    meta = _as_mapping(root.get("meta"), f"{adapter_name}.meta")
    channels = _as_list(meta.get("channels"), f"{adapter_name}.meta.channels")
    if not channels:
        raise AssertionError(f"{adapter_name}.meta.channels must be non-empty")
    if not all(isinstance(channel, str) and channel.strip() for channel in channels):
        raise AssertionError(f"{adapter_name}.meta.channels must contain non-empty strings")

    channel_count = len(channels)
    declared_count = meta.get("n_channels")
    if declared_count is not None and declared_count != channel_count:
        raise AssertionError(
            f"{adapter_name}.meta.n_channels={declared_count} does not match "
            f"{channel_count} channel names"
        )

    welch_psd = _as_mapping(root.get("welch_psd"), f"{adapter_name}.welch_psd")
    frequencies = _finite_axis(
        welch_psd.get("frequencies"),
        f"{adapter_name}.welch_psd.frequencies",
        min_length=1,
    )
    _finite_channel_major(
        welch_psd.get("psd"),
        f"{adapter_name}.welch_psd.psd",
        channel_count=channel_count,
        width=len(frequencies),
    )

    centroid = _as_mapping(root.get("centroid"), f"{adapter_name}.centroid")
    centroid_time = _finite_axis(
        centroid.get("time_relative"),
        f"{adapter_name}.centroid.time_relative",
        min_length=1,
    )
    _finite_channel_major(
        centroid.get("values"),
        f"{adapter_name}.centroid.values",
        channel_count=channel_count,
        width=len(centroid_time),
    )

    geometry = _as_mapping(root.get("geometry"), f"{adapter_name}.geometry")
    geometry_time = _finite_axis(
        geometry.get("time"),
        f"{adapter_name}.geometry.time",
        min_length=1,
    )
    for key in _GEOMETRY_CHANNEL_MAJOR_KEYS:
        if geometry.get(key) is not None:
            _finite_channel_major(
                geometry.get(key),
                f"{adapter_name}.geometry.{key}",
                channel_count=channel_count,
                width=len(geometry_time),
            )

    area_normalized_psd = geometry.get("area_normalized_psd")
    if area_normalized_psd is not None:
        area = _as_mapping(area_normalized_psd, f"{adapter_name}.geometry.area_normalized_psd")
        area_frequencies = _finite_axis(
            area.get("frequencies"),
            f"{adapter_name}.geometry.area_normalized_psd.frequencies",
            min_length=1,
        )
        _finite_channel_major(
            area.get("psd"),
            f"{adapter_name}.geometry.area_normalized_psd.psd",
            channel_count=channel_count,
            width=len(area_frequencies),
        )

    channel_summary = root.get("channel_summary")
    if channel_summary is not None:
        summaries = _as_list(channel_summary, f"{adapter_name}.channel_summary")
        if len(summaries) != channel_count:
            raise AssertionError(
                f"{adapter_name}.channel_summary has {len(summaries)} rows "
                f"but meta.channels lists {channel_count}"
            )
        for index, (summary, channel) in enumerate(zip(summaries, channels, strict=True)):
            summary_mapping = _as_mapping(summary, f"{adapter_name}.channel_summary[{index}]")
            if summary_mapping.get("channel") != channel:
                raise AssertionError(
                    f"{adapter_name}.channel_summary[{index}].channel is "
                    f"{summary_mapping.get('channel')!r}, expected {channel!r}"
                )

    _assert_all_numeric_values_are_finite(root, adapter_name)


def _as_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AssertionError(f"{path} must be a mapping")
    return value


def _as_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise AssertionError(f"{path} must be a list")
    return value


def _finite_axis(value: Any, path: str, *, min_length: int) -> list[Any]:
    axis = _as_list(value, path)
    if len(axis) < min_length:
        raise AssertionError(f"{path} must contain at least {min_length} value")
    for index, item in enumerate(axis):
        _assert_finite_number(item, f"{path}[{index}]")
    return axis


def _finite_channel_major(value: Any, path: str, *, channel_count: int, width: int) -> None:
    rows = _as_list(value, path)
    if len(rows) != channel_count:
        raise AssertionError(
            f"{path} has {len(rows)} channel rows but meta.channels lists {channel_count}"
        )
    for row_index, row in enumerate(rows):
        row_values = _as_list(row, f"{path}[{row_index}]")
        if len(row_values) != width:
            raise AssertionError(
                f"{path}[{row_index}] has length {len(row_values)}, expected {width}"
            )
        for column_index, item in enumerate(row_values):
            _assert_finite_number(item, f"{path}[{row_index}][{column_index}]")


def _assert_all_numeric_values_are_finite(value: Any, path: str) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, Real):
        _assert_finite_number(value, path)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_all_numeric_values_are_finite(item, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _assert_all_numeric_values_are_finite(item, f"{path}[{index}]")


def _assert_finite_number(value: Any, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise AssertionError(f"{path} must be a finite number")
    if not math.isfinite(float(value)):
        raise AssertionError(f"{path} must be finite")
