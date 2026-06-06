#!/usr/bin/env python3
"""Compute Phase 2 derived metrics from data/data.json."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "data.json"
METRICS = [
    "centroid",
    "spread",
    "entropy",
    "flatness",
    "edge95",
    "alpha_relative_power",
]
VAR_PREFIX = {
    "centroid": "centroid",
    "spread": "spread",
    "entropy": "entropy",
    "flatness": "flatness",
    "edge95": "edge95",
    "alpha_relative_power": "alpha",
}


def main() -> None:
    data = json.loads(DATA_PATH.read_text())
    channels = data["meta"]["channels"]
    summary = data["channel_summary"]

    add_polar_chronomap(data, channels, summary)
    add_channel_network(data, channels)
    add_temporal_variability(data)

    DATA_PATH.write_text(json.dumps(data, separators=(",", ":")))
    print(f"Phase 2 complete: updated {DATA_PATH}")


def add_polar_chronomap(data: dict, channels: list[str], summary: list[dict]) -> None:
    alpha = np.asarray(data["geometry"]["alpha_relative_power"], dtype=float)
    regions = [item.get("region", "") for item in summary]
    posterior_idx = [
        index
        for index, region in enumerate(regions)
        if region in {"occipital", "parietal"}
    ]
    frontal_idx = [
        index
        for index, region in enumerate(regions)
        if str(region).startswith("frontal")
    ]
    if not posterior_idx:
        raise ValueError("No posterior channels found for polar_chronomap")
    if not frontal_idx:
        raise ValueError("No frontal channels found for polar_chronomap")

    posterior_alpha = alpha[posterior_idx].mean(axis=0)
    frontal_alpha = alpha[frontal_idx].mean(axis=0)
    balance = posterior_alpha - frontal_alpha

    data["polar_chronomap"] = {
        "time": round_list(data["geometry"]["time"]),
        "posterior_alpha": round_array(posterior_alpha),
        "frontal_alpha": round_array(frontal_alpha),
        "balance": round_array(balance),
        "posterior_channels": [channels[index] for index in posterior_idx],
        "frontal_channels": [channels[index] for index in frontal_idx],
    }


def add_channel_network(data: dict, channels: list[str]) -> None:
    corr_matrices: dict[str, list[list[float]]] = {}
    abs_matrices = []

    for metric in METRICS:
        values = np.asarray(data["geometry"][metric], dtype=float)
        corr = np.corrcoef(values)
        corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
        corr = np.clip(corr, -1.0, 1.0)
        np.fill_diagonal(corr, 1.0)
        corr_matrices[metric] = round_matrix(corr)
        abs_matrices.append(np.abs(corr))

    composite = np.mean(abs_matrices, axis=0)
    np.fill_diagonal(composite, 1.0)
    data["channel_network"] = {
        "channels": channels,
        "composite_correlation": round_matrix(composite),
        "per_metric": corr_matrices,
        "threshold_strong": 0.7,
        "threshold_moderate": 0.5,
    }


def add_temporal_variability(data: dict) -> None:
    variability_by_metric = {}
    for metric in METRICS:
        values = np.asarray(data["geometry"][metric], dtype=float)
        variability_by_metric[metric] = {
            "std": values.std(axis=1),
            "range": values.max(axis=1) - values.min(axis=1),
            "mean": values.mean(axis=1),
        }

    for channel_index, item in enumerate(data["channel_summary"]):
        variability = dict(item.get("variability", {}))
        for metric, stats in variability_by_metric.items():
            prefix = VAR_PREFIX[metric]
            variability[f"{prefix}_std"] = round_float(stats["std"][channel_index])
            variability[f"{prefix}_range"] = round_float(stats["range"][channel_index])
            variability[f"{prefix}_mean"] = round_float(stats["mean"][channel_index])
        item["variability"] = variability


def round_float(value: float, digits: int = 6) -> float:
    number = float(value)
    if not np.isfinite(number):
        return 0.0
    return round(number, digits)


def round_array(values: np.ndarray, digits: int = 6) -> list[float]:
    return [round_float(value, digits) for value in values.tolist()]


def round_matrix(values: np.ndarray, digits: int = 6) -> list[list[float]]:
    return [[round_float(value, digits) for value in row] for row in values.tolist()]


def round_list(values: list[float], digits: int = 6) -> list[float]:
    return [round_float(value, digits) for value in values]


if __name__ == "__main__":
    main()
