"""Abuse/DoS guardrails: rate limits, per-user quotas, dataset + queue caps."""

from __future__ import annotations

from typing import Any, Final

from fastapi.testclient import TestClient

from neuromouse_backend.app import create_app
from neuromouse_backend.storage import SQLiteBackendStore

TOK: Final = "tok-a"
HDR: Final = {"Authorization": f"Bearer {TOK}"}

METHOD_SRC = b'''
from dataclasses import dataclass
from neuromouse_sdk import OutputField, OutputSpec, PanelSpec
@dataclass(frozen=True)
class P:
    pass
class M:
    name = "noop"
    version = "0.0.0"
    params_type = P
    required_inputs = ()
    output = OutputSpec(
        fields=(OutputField("noop.rows", description="r"),),
        panel=PanelSpec(id="noop", title="Noop", kind="table", field="noop.rows"),
    )
    def compute(self, dataset, params):
        return {"noop": {"rows": []}}
method = M()
'''


def minimal_dataset(n: int = 2) -> dict[str, Any]:
    channels = [f"C{i}" for i in range(n)]
    return {
        "meta": {"channels": channels, "n_channels": n},
        "welch_psd": {"frequencies": [8.0, 10.0], "psd": [[0.1, 0.2] for _ in channels]},
        "centroid": {"time_relative": [0.0], "values": [[8.0] for _ in channels]},
        "geometry": {"time": [0.0]},
    }


def _client(tmp_path, monkeypatch, **env) -> TestClient:
    monkeypatch.setenv("NEUROMOUSE_SESSION_TOKENS", f"{TOK}:user-a")
    for key, val in env.items():
        monkeypatch.setenv(key, str(val))
    return TestClient(create_app(store=SQLiteBackendStore(tmp_path / "be.sqlite3")))


def _upload(client: TestClient, name: str = "noop") -> Any:
    src = METHOD_SRC.replace(b'name = "noop"', f'name = "{name}"'.encode()).replace(
        b"noop.rows", f"{name}.rows".encode()
    ).replace(b'id="noop"', f'id="{name}"'.encode())
    return client.post(
        "/methods", files={"file": ("m.py", src, "text/x-python")}, headers=HDR
    )


def test_session_creation_rate_limited(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, NEUROMOUSE_SESSIONS_PER_MIN=2)
    codes = [
        client.post(
            "/sessions", json={"name": "s", "dataset": minimal_dataset()}, headers=HDR
        ).status_code
        for _ in range(3)
    ]
    assert codes[:2] == [201, 201]
    assert codes[2] == 429


def test_dataset_too_large_rejected(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, NEUROMOUSE_MAX_DATASET_BYTES=200)
    r = client.post("/sessions", json={"name": "s", "dataset": minimal_dataset(8)}, headers=HDR)
    assert r.status_code == 413


def test_method_count_cap(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, NEUROMOUSE_MAX_METHODS_PER_USER=1)
    assert _upload(client, "alpha").status_code == 201
    assert _upload(client, "beta").status_code == 429


def test_upload_rate_limited(tmp_path, monkeypatch) -> None:
    client = _client(
        tmp_path, monkeypatch, NEUROMOUSE_UPLOADS_PER_MIN=1, NEUROMOUSE_MAX_METHODS_PER_USER=0
    )
    assert _upload(client, "alpha").status_code == 201
    assert _upload(client, "beta").status_code == 429


def test_registration_global_cap(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, NEUROMOUSE_REGISTRATIONS_PER_HOUR=2)
    codes = [
        client.post(
            "/auth/register", json={"email": f"u{i}@x.io", "password": "pw-strong-123"}
        ).status_code
        for i in range(3)
    ]
    assert codes[:2] == [201, 201]
    assert codes[2] == 429


def test_job_submission_rate_limited(tmp_path, monkeypatch) -> None:
    # Per-user job-rate cap (active-job cap disabled here so the rate limit is
    # what's exercised, independent of worker-drain timing).
    client = _client(
        tmp_path, monkeypatch, NEUROMOUSE_JOBS_PER_MIN=1, NEUROMOUSE_MAX_ACTIVE_JOBS_PER_USER=0
    )
    sid = client.post(
        "/sessions", json={"name": "s", "dataset": minimal_dataset()}, headers=HDR
    ).json()["id"]
    first = client.post(
        f"/sessions/{sid}/jobs", json={"method_id": "band_power_summary"}, headers=HDR
    )
    second = client.post(
        f"/sessions/{sid}/jobs", json={"method_id": "band_power_summary"}, headers=HDR
    )
    assert first.status_code == 201
    assert second.status_code == 429
