#!/usr/bin/env python3
"""Convert source EEG spectral exports into the dashboard data contract."""

from __future__ import annotations

import csv
import json
import math
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "source-data"
OUTPUT_PATH = ROOT / "data" / "data.json"

WELCH_ZIP = SOURCE_DIR / "eeg_welch_export.zip"
GEOMETRY_ZIP = SOURCE_DIR / "spectral_centroid_export.zip"

CHANNELS = [
    "Fp1",
    "Fpz",
    "Fp2",
    "F7",
    "F3",
    "Fz",
    "F4",
    "F8",
    "FC5",
    "FC1",
    "FC2",
    "FC6",
    "M1",
    "T7",
    "C3",
    "Cz",
    "C4",
    "T8",
    "M2",
    "CP5",
    "CP1",
    "CP2",
    "CP6",
    "P7",
    "P3",
    "Pz",
    "P4",
    "P8",
    "POz",
    "O1",
    "Oz",
    "O2",
]

GEOMETRY_FILES = {
    "centroid": "sliding_spectral_centroid_wide.csv",
    "spread": "sliding_spectral_spread_wide.csv",
    "entropy": "sliding_spectral_entropy_wide.csv",
    "flatness": "sliding_spectral_flatness_wide.csv",
    "edge95": "sliding_spectral_edge95_wide.csv",
    "alpha_relative_power": "sliding_alpha_relative_power_wide.csv",
}


def read_zip_csv(zip_path: Path, member: str) -> list[dict[str, str]]:
    if not zip_path.exists():
        raise FileNotFoundError(f"Missing source archive: {zip_path}")
    with zipfile.ZipFile(zip_path) as archive:
        with archive.open(member) as fp:
            text = fp.read().decode("utf-8-sig")
    return list(csv.DictReader(text.splitlines()))


def read_zip_json(zip_path: Path, member: str) -> dict:
    with zipfile.ZipFile(zip_path) as archive:
        return json.loads(archive.read(member))


def to_float(value: str | float | int | None) -> float | None:
    if value in (None, ""):
        return None
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, 6)


def read_wide_matrix(
    zip_path: Path,
    member: str,
    axis_key: str,
    channels: list[str],
) -> tuple[list[float], list[list[float | None]]]:
    rows = read_zip_csv(zip_path, member)
    if not rows:
        raise ValueError(f"{member} has no rows")

    missing = [channel for channel in channels if channel not in rows[0]]
    if missing:
        raise ValueError(f"{member} is missing channel columns: {missing}")

    axis = [to_float(row[axis_key]) for row in rows]
    matrix = [
        [to_float(row[channel]) for row in rows]
        for channel in channels
    ]
    return axis, matrix


def bool_from_csv(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "y"}


def short_hemisphere(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("left"):
        return "L"
    if normalized.startswith("right"):
        return "R"
    if normalized.startswith("mid"):
        return "M"
    return value


def build_channel_summary(channels: list[str]) -> list[dict]:
    rows = read_zip_csv(GEOMETRY_ZIP, "spectral_centroid_channel_summary.csv")
    by_channel = {row["channel"]: row for row in rows}
    summary = []
    for channel in channels:
        row = by_channel[channel]
        summary.append(
            {
                "channel": channel,
                "hemisphere": short_hemisphere(row["hemisphere"]),
                "region": row["region"],
                "has_clear_alpha_peak": bool_from_csv(row["has_clear_alpha_peak"]),
                "alpha_relative_power": to_float(row["alpha_relative_power_2_45Hz"]),
                "spectral_centroid_hz": to_float(row["spectral_centroid_Hz_2_45Hz"]),
                "spectral_spread_hz": to_float(row["spectral_spread_Hz_2_45Hz"]),
                "spectral_entropy": to_float(row["spectral_entropy_normalized_2_45Hz"]),
                "spectral_flatness": to_float(row["spectral_flatness_2_45Hz"]),
                "edge95_hz": to_float(row["spectral_edge_95Hz"]),
                "alpha_peak_frequency_hz": to_float(row["alpha_peak_frequency_Hz"]),
                "sliding_alpha_relative_mean": to_float(row["sliding_alpha_relative_mean"]),
            }
        )
    return summary


def main() -> None:
    welch_json = read_zip_json(WELCH_ZIP, "eeg_welch_centroid_export.json")
    geometry_meta = read_zip_json(GEOMETRY_ZIP, "spectral_centroid_geometry_metadata.json")

    channels = welch_json["metadata"].get("channel_names", CHANNELS)
    if channels != CHANNELS:
        raise ValueError("Unexpected channel order in source exports")

    welch_freq, welch_psd = read_wide_matrix(
        WELCH_ZIP,
        "welch_psd_wide.csv",
        "frequency_hz",
        channels,
    )
    centroid_time, centroid_values = read_wide_matrix(
        WELCH_ZIP,
        "spectral_centroid_wide.csv",
        "time_relative_sec",
        channels,
    )
    geometry_time, geometry_centroid = read_wide_matrix(
        GEOMETRY_ZIP,
        GEOMETRY_FILES["centroid"],
        "time_relative_sec",
        channels,
    )

    geometry = {
        "time": geometry_time,
        "centroid": geometry_centroid,
    }
    for key, member in GEOMETRY_FILES.items():
        if key == "centroid":
            continue
        time, values = read_wide_matrix(GEOMETRY_ZIP, member, "time_relative_sec", channels)
        if time != geometry_time:
            raise ValueError(f"{member} has a different time axis")
        geometry[key] = values

    area_freq, area_psd = read_wide_matrix(
        GEOMETRY_ZIP,
        "mean_psd_area_normalized_wide.csv",
        "frequency_hz",
        channels,
    )
    geometry["area_normalized_psd"] = {
        "frequencies": area_freq,
        "psd": area_psd,
    }

    segment_start = float(geometry_meta["segment_start_sec"])
    segment_end = float(geometry_meta["segment_end_sec"])

    output = {
        "meta": {
            "channels": channels,
            "n_channels": len(channels),
            "segment_duration_sec": round(segment_end - segment_start, 3),
            "sampling_rate_analysis_hz": int(geometry_meta["analysis_sample_rate_hz"]),
            "welch_window_sec": int(geometry_meta["welch_window_sec"]),
            "welch_overlap_fraction": float(geometry_meta["welch_overlap"]),
            "sliding_window_sec": int(geometry_meta["sliding_window_sec"]),
            "sliding_step_sec": float(geometry_meta["sliding_step_sec"]),
            "source": "GX dataset (Gebodh/CCNY), CC BY-SA 4.0",
            "analysis_by": "soulsyrup1/Complete-Neural-Signal-Analysis",
            "source_files": {
                "welch": "eeg_welch_export.zip",
                "geometry": "spectral_centroid_export.zip",
            },
        },
        "welch_psd": {
            "frequencies": welch_freq,
            "psd": welch_psd,
        },
        "centroid": {
            "time_relative": centroid_time,
            "values": centroid_values,
        },
        "geometry": geometry,
        "channel_summary": build_channel_summary(channels),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fp:
        json.dump(output, fp, ensure_ascii=False, separators=(",", ":"))

    print(f"Wrote {OUTPUT_PATH}")
    print(f"Channels: {len(channels)}")
    print(f"Welch PSD: {len(welch_freq)} frequencies x {len(welch_psd)} channels")
    print(f"Centroid: {len(centroid_time)} times x {len(centroid_values)} channels")
    print(f"Geometry: {len(geometry_time)} times x {len(channels)} channels x {len(GEOMETRY_FILES)} metrics")
    print(f"Area-normalized PSD: {len(area_freq)} frequencies x {len(area_psd)} channels")
    print(f"Channel summary: {len(output['channel_summary'])} channels")
    print(f"Size: {OUTPUT_PATH.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()

