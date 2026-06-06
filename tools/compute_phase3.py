#!/usr/bin/env python3
"""Compute Phase 3 GX raw EEG metrics and merge them into data/data.json."""

from __future__ import annotations

import json
import math
from pathlib import Path

import h5py
import numpy as np
from scipy.signal import butter, hilbert, sosfiltfilt
from scipy.spatial import cKDTree


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "data.json"
GX_DIR = ROOT / "source-data" / "gx"
SYNC_SEGMENT_SEC = 30.0
WINDOW_SEC = 2.0
STEP_SEC = 0.25
HIGUCHI_KMAX = 10


def main() -> None:
    mat_files = sorted(path for path in GX_DIR.glob("*.mat") if path.is_file())
    if not mat_files:
        print("No GX .mat file found. Skipping Phase 3.")
        return

    data = json.loads(DATA_PATH.read_text())
    channels = data["meta"]["channels"]
    geometry_times = np.asarray(data["geometry"]["time"], dtype=float)
    analysis_segment_sec = float(data["meta"].get("segment_duration_sec") or geometry_times[-1] + 1.0)
    mat_path = mat_files[0]
    print(f"Loading GX file: {mat_path}")

    eeg_full, fs, labels = load_gx_segment(mat_path, channels, analysis_segment_sec)
    print(f"EEG segment shape: {eeg_full.shape}, fs={fs:g}")
    eeg_full = normalize_channels(eeg_full)
    alpha_phase_full = alpha_phase(eeg_full, fs)

    add_kuramoto(data, alpha_phase_full, fs, geometry_times)
    add_phase_synchrony(data, alpha_phase_full, fs, geometry_times)
    add_higuchi_fd(data, eeg_full, fs, geometry_times)
    add_lyapunov(data, eeg_full, fs)
    add_tda(data)
    data["phase3_meta"] = {
        "source_file": mat_path.name,
        "gx_labels": labels,
        "sampling_rate_hz": round_float(fs, 3),
        "analysis_segment_sec": round_float(eeg_full.shape[1] / fs, 3),
        "sync_segment_sec": SYNC_SEGMENT_SEC,
        "higuchi_kmax": HIGUCHI_KMAX,
        "notes": [
            "Kuramoto and Higuchi align to data.geometry.time.",
            "PLV static/sliding use the first 30 seconds to keep data.json compact.",
            "Lyapunov uses the first 30 seconds decimated to approximately 250 Hz.",
        ],
    }

    DATA_PATH.write_text(json.dumps(data, separators=(",", ":")))
    print(f"Phase 3 complete: updated {DATA_PATH}")


def load_gx_segment(mat_path: Path, channels: list[str], seconds: float) -> tuple[np.ndarray, float, list[str]]:
    with h5py.File(mat_path, "r") as file:
        if "DSamp" not in file or "EEGdata" not in file["DSamp"]:
            raise ValueError("Expected DSamp/EEGdata in GX .mat file")
        dsamp = file["DSamp"]
        fs = float(np.asarray(dsamp["fs"])[0, 0])
        labels = read_labels(file, dsamp["label"])
        label_index = {label: index for index, label in enumerate(labels)}
        missing = [channel for channel in channels if channel not in label_index]
        if missing:
            raise ValueError(f"GX file is missing channels: {', '.join(missing)}")

        eeg = dsamp["EEGdata"]
        sample_count = min(int(round(seconds * fs)), eeg.shape[0])
        channel_indices = [label_index[channel] for channel in channels]
        segment = np.asarray(eeg[:sample_count, channel_indices], dtype=np.float64).T
        return segment, fs, labels


def read_labels(file: h5py.File, label_dataset: h5py.Dataset) -> list[str]:
    labels = []
    for ref in label_dataset[0]:
        raw = np.asarray(file[ref]).flatten()
        labels.append("".join(chr(int(value)) for value in raw if int(value) != 0))
    return labels


def normalize_channels(eeg: np.ndarray) -> np.ndarray:
    centered = eeg - np.median(eeg, axis=1, keepdims=True)
    scale = np.std(centered, axis=1, keepdims=True)
    scale[scale == 0] = 1.0
    return centered / scale


def alpha_phase(eeg: np.ndarray, fs: float) -> np.ndarray:
    sos = butter(4, [8 / (fs / 2), 13 / (fs / 2)], btype="band", output="sos")
    filtered = sosfiltfilt(sos, eeg, axis=-1)
    return np.angle(hilbert(filtered, axis=-1))


def add_kuramoto(data: dict, phase: np.ndarray, fs: float, times: np.ndarray) -> None:
    win = max(1, int(round(STEP_SEC * fs)))
    channel_phases = np.zeros((phase.shape[0], len(times)))
    order_r = np.zeros(len(times))
    mean_psi = np.zeros(len(times))

    for index, time_sec in enumerate(times):
        start = centered_start(time_sec, STEP_SEC, fs, phase.shape[1])
        window = phase[:, start:start + win]
        phases = circular_mean(window, axis=1)
        channel_phases[:, index] = phases
        z = np.mean(np.exp(1j * phases))
        order_r[index] = np.abs(z)
        mean_psi[index] = np.angle(z)

    data["kuramoto"] = {
        "time": round_array(times),
        "order_parameter_r": round_array(order_r),
        "mean_phase_psi": round_array(mean_psi),
        "channel_phases": round_matrix(channel_phases),
        "channels": data["meta"]["channels"],
    }


def add_phase_synchrony(data: dict, phase: np.ndarray, fs: float, times: np.ndarray) -> None:
    sync_samples = min(phase.shape[1], int(round(SYNC_SEGMENT_SEC * fs)))
    sync_phase = phase[:, :sync_samples]
    data["phase_synchrony"] = {
        "channels": data["meta"]["channels"],
        "plv_static": round_matrix(plv(sync_phase)),
    }

    win = int(round(WINDOW_SEC * fs))
    usable_times = [float(time) for time in times if time <= SYNC_SEGMENT_SEC - WINDOW_SEC / 2]
    sliding = []
    for time_sec in usable_times:
        start = centered_start(time_sec, WINDOW_SEC, fs, sync_samples)
        sliding.append(plv(sync_phase[:, start:start + win]))

    if sliding:
        data["phase_synchrony"]["plv_sliding_time"] = round_array(np.asarray(usable_times))
        data["phase_synchrony"]["plv_sliding"] = [round_matrix(matrix) for matrix in sliding]


def plv(phase_window: np.ndarray) -> np.ndarray:
    unit = np.exp(1j * phase_window)
    matrix = np.abs(np.einsum("it,jt->ij", unit, unit.conj(), optimize=True) / max(1, unit.shape[1]))
    matrix = np.clip(matrix, 0.0, 1.0)
    np.fill_diagonal(matrix, 1.0)
    return matrix


def add_higuchi_fd(data: dict, eeg: np.ndarray, fs: float, times: np.ndarray) -> None:
    win = int(round(WINDOW_SEC * fs))
    hfd = np.zeros((eeg.shape[0], len(times)))
    for channel_index in range(eeg.shape[0]):
        channel = eeg[channel_index]
        for time_index, time_sec in enumerate(times):
            start = centered_start(time_sec, WINDOW_SEC, fs, eeg.shape[1])
            hfd[channel_index, time_index] = higuchi_fd(channel[start:start + win], HIGUCHI_KMAX)
        print(f"Higuchi FD: channel {channel_index + 1}/{eeg.shape[0]}")
    data["geometry"]["higuchi_fd"] = round_matrix(hfd)


def higuchi_fd(x: np.ndarray, kmax: int = 10) -> float:
    x = np.asarray(x, dtype=float)
    n = x.size
    lengths = []
    for k in range(1, kmax + 1):
        lk = []
        for m in range(k):
            indexes = np.arange(m, n, k)
            if indexes.size < 2:
                continue
            diffs = np.abs(np.diff(x[indexes])).sum()
            norm = (n - 1) / ((indexes.size - 1) * k)
            lk.append((diffs * norm) / k)
        lengths.append(np.mean(lk) if lk else np.nan)

    lengths = np.asarray(lengths, dtype=float)
    ks = np.arange(1, kmax + 1, dtype=float)
    mask = np.isfinite(lengths) & (lengths > 0)
    if mask.sum() < 2:
        return 0.0
    slope = np.polyfit(np.log(ks[mask]), np.log(lengths[mask]), 1)[0]
    return float(-slope)


def add_lyapunov(data: dict, eeg: np.ndarray, fs: float) -> None:
    source_samples = min(eeg.shape[1], int(round(SYNC_SEGMENT_SEC * fs)))
    decimation = max(1, int(round(fs / 250)))
    effective_fs = fs / decimation
    values = []
    for channel_index in range(eeg.shape[0]):
        series = eeg[channel_index, :source_samples:decimation]
        values.append(largest_lyapunov_rosenstein(series, effective_fs))
        print(f"Lyapunov: channel {channel_index + 1}/{eeg.shape[0]}")

    for item, value in zip(data["channel_summary"], values):
        item["lyapunov_exponent"] = round_float(value)


def largest_lyapunov_rosenstein(
    x: np.ndarray,
    fs: float,
    emb_dim: int = 6,
    lag: int = 2,
    min_tsep: int | None = None,
) -> float:
    x = np.asarray(x, dtype=float)
    if min_tsep is None:
        min_tsep = max(1, int(round(fs * 0.1)))

    m = x.size - (emb_dim - 1) * lag
    if m <= emb_dim + min_tsep + 4:
        return 0.0

    traj = np.column_stack([x[offset:offset + m] for offset in range(0, emb_dim * lag, lag)])
    tree = cKDTree(traj)
    query_k = min(m, max(8, min_tsep + 8))
    _, candidates = tree.query(traj, k=query_k)
    nearest = np.full(m, -1, dtype=int)
    for index in range(m):
        row = np.atleast_1d(candidates[index])
        valid = row[np.abs(row - index) >= min_tsep]
        if valid.size:
            nearest[index] = int(valid[0])

    valid_base = np.where(nearest >= 0)[0]
    if valid_base.size < 4:
        return 0.0

    max_div_steps = min(20, m // 4)
    divergence = []
    for step in range(max_div_steps):
        base = valid_base[(valid_base + step < m) & (nearest[valid_base] + step < m)]
        if base.size < 4:
            continue
        dist = np.linalg.norm(traj[nearest[base] + step] - traj[base + step], axis=1)
        dist = dist[dist > 1e-12]
        if dist.size:
            divergence.append(float(np.log(dist).mean()))

    if len(divergence) < 4:
        return 0.0
    fit_count = min(12, len(divergence))
    time = np.arange(fit_count) / fs
    return float(np.polyfit(time, divergence[:fit_count], 1)[0])


def add_tda(data: dict) -> None:
    try:
        from ripser import ripser
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        data["tda"] = {
            "status": "skipped",
            "reason": "ripser not available",
        }
        print("TDA skipped: ripser not available")
        return

    geo_keys = ["centroid", "spread", "entropy", "flatness", "edge95", "alpha_relative_power"]
    points = np.asarray([
        [np.mean(data["geometry"][key][channel_index]) for key in geo_keys]
        for channel_index in range(32)
    ], dtype=float)
    points = StandardScaler().fit_transform(points)
    result = ripser(points, maxdim=1)
    h0 = finite_diagram(result["dgms"][0])
    h1 = finite_diagram(result["dgms"][1]) if len(result["dgms"]) > 1 else np.empty((0, 2))
    data["tda"] = {
        "status": "computed",
        "h0": round_matrix(h0),
        "h1": round_matrix(h1),
        "point_cloud": round_matrix(points),
        "channels": data["meta"]["channels"],
        "features": geo_keys,
    }


def finite_diagram(diagram: np.ndarray) -> np.ndarray:
    if diagram.size == 0:
        return np.empty((0, 2))
    return diagram[np.isfinite(diagram[:, 1])]


def centered_start(center_sec: float, win_sec: float, fs: float, sample_count: int) -> int:
    win = max(1, int(round(win_sec * fs)))
    start = int(round((center_sec - win_sec / 2) * fs))
    return max(0, min(max(0, sample_count - win), start))


def circular_mean(values: np.ndarray, axis: int) -> np.ndarray:
    return np.angle(np.mean(np.exp(1j * values), axis=axis))


def round_float(value: float, digits: int = 6) -> float:
    number = float(value)
    if not math.isfinite(number):
        return 0.0
    return round(number, digits)


def round_array(values: np.ndarray, digits: int = 6) -> list[float]:
    return [round_float(value, digits) for value in np.asarray(values).tolist()]


def round_matrix(values: np.ndarray, digits: int = 6) -> list[list[float]]:
    return [[round_float(value, digits) for value in row] for row in np.asarray(values).tolist()]


if __name__ == "__main__":
    main()
