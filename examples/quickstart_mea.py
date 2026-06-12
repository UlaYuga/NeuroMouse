#!/usr/bin/env python3
"""Quickstart: plug a method in, get a result on the 1024-channel MEA golden.

This is the NeuroMouse wedge in one short script:

    register a method  ->  run it on a dataset  ->  get a reproducible result

We exercise two reference method plugins on the golden HD-MEA recording
(1024 electrodes of raw voltage traces with known, injected spikes):

    1. ``spike_detect``           raw traces            -> per-electrode spikes
    2. ``electrode_connectivity`` those detected spikes -> a coupling matrix

Everything goes through the *public* registry (``neuromouse_core.register`` /
``neuromouse_core.run``) -- the same API a real user calls. ``run`` validates the
dataset against the contract, executes the method under a fixed seed, and hands
back the output together with a reproducibility manifest (a run id + content
hashes), so the result is verifiable, not just printed.

Run it::

    uv run python examples/quickstart_mea.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# The reference methods ship as drop-in plugins under <repo>/methods. Putting
# that directory on the import path lets us import them like any other plugin a
# method author might publish -- we never reach into package internals.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "methods"))

import neuromouse_core as core  # public registry: register() + run()  # noqa: E402
import electrode_connectivity  # reference method plugin  # noqa: E402
import spike_detect  # reference method plugin  # noqa: E402

GOLDEN_PATH = REPO_ROOT / "datasets" / "golden" / "mea_synthetic.json"

# Plug the methods in. This single step -- handing a method object to the
# registry -- is the wedge: author a method, register it, run it on real data
# through one stable, versioned API.
core.register(spike_detect.method)
core.register(electrode_connectivity.method)


def run_pipeline(dataset: dict) -> dict:
    """Detect spikes, then derive electrode connectivity, via the public registry."""

    # --- Step 1: detect spikes on the raw traces -----------------------------
    # The golden's injected spikes are positive-going, so ask for positive
    # polarity. core.run() returns output + a reproducibility manifest.
    spike_run = core.run(dataset, "spike_detect", {"polarity": "positive"}, seed=0)
    spikes_out = spike_run.output["spike_detect"]

    # --- Step 2: feed the detected spikes into connectivity ------------------
    # electrode_connectivity consumes per-electrode spike trains. We pass it the
    # spikes we just detected (electrode -> spike times) plus the recording
    # duration; the contract's Mea model lets these extra fields through.
    spikes = {row["electrode"]: row["spike_times_sec"] for row in spikes_out["spikes"]}
    duration_sec = len(dataset["mea"]["traces"][0]) / dataset["mea"]["sampling_rate_hz"]
    conn_input = dict(dataset, mea=dict(dataset["mea"], spikes=spikes, duration_sec=duration_sec))
    conn_run = core.run(
        conn_input, "electrode_connectivity", {"bin_size_ms": 5.0, "max_lag_ms": 5.0}, seed=0
    )
    conn_out = conn_run.output["electrode_connectivity"]
    matrix, strongest = conn_out["matrix"], conn_out["summary"]["strongest_pair"]

    return {
        "electrodes": len(dataset["meta"]["channels"]),
        "total_spikes": spikes_out["summary"]["total_spikes"],
        "connectivity_shape": (len(matrix), len(matrix[0])),
        "strongest_pair": (strongest["source"], strongest["target"]),
        "spike_run_id": spike_run.manifest.run_id,
    }


def main() -> dict:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    summary = run_pipeline(golden)
    rows, cols = summary["connectivity_shape"]
    src, dst = summary["strongest_pair"]
    print(f"electrodes:          {summary['electrodes']}")
    print(f"spikes detected:     {summary['total_spikes']}")
    print(f"connectivity matrix: {rows} x {cols}")
    print(f"strongest pair:      {src} -> {dst}")
    print(f"spike_detect run_id: {summary['spike_run_id'][:16]}…  (reproducible)")
    return summary


if __name__ == "__main__":
    main()
