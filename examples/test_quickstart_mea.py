"""Smoke test that keeps examples/quickstart_mea.py runnable in CI.

It exercises the same public registry path the example uses (register -> run ->
run), but on a 128-electrode slice of the golden so it stays fast (~0.2s). A
slice is a valid dataset because the contract only requires per-channel arrays to
agree in length, which we preserve by slicing them together.
"""

from __future__ import annotations

import json

import quickstart_mea as qs


def _golden_slice(n_electrodes: int) -> dict:
    golden = json.loads(qs.GOLDEN_PATH.read_text(encoding="utf-8"))
    channels = golden["meta"]["channels"][:n_electrodes]
    return dict(
        golden,
        meta=dict(golden["meta"], channels=channels, n_channels=len(channels)),
        welch_psd=dict(golden["welch_psd"], psd=golden["welch_psd"]["psd"][:n_electrodes]),
        centroid=dict(golden["centroid"], values=golden["centroid"]["values"][:n_electrodes]),
        channel_summary=golden["channel_summary"][:n_electrodes],
        mea=dict(golden["mea"], traces=golden["mea"]["traces"][:n_electrodes]),
    )


def test_quickstart_pipeline_runs_on_golden_slice() -> None:
    summary = qs.run_pipeline(_golden_slice(128))

    # spike_detect recovers the 8 injected ground-truth spikes in the first 128
    # electrodes; the connectivity matrix is square over those electrodes.
    assert summary["electrodes"] == 128
    assert summary["total_spikes"] == 8
    assert summary["connectivity_shape"] == (128, 128)
    # The manifest run id is a 64-char content hash, i.e. the result is provenance-tracked.
    assert len(summary["spike_run_id"]) == 64
