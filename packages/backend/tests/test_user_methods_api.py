"""End-to-end API for private, user-uploaded methods: upload → list → run → delete."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Final

import httpx
import pytest
from fastapi.testclient import TestClient

from neuromouse_backend.app import create_app
from neuromouse_backend.storage import SQLiteBackendStore

USER_A: Final = "tok-a"
USER_B: Final = "tok-b"
HEADERS_A: Final = {"Authorization": f"Bearer {USER_A}"}
HEADERS_B: Final = {"Authorization": f"Bearer {USER_B}"}

# A self-contained method following the SDK template; works on meta.channels only.
METHOD_SOURCE = '''
from dataclasses import dataclass
from neuromouse_sdk import OutputField, OutputSpec, PanelSpec


@dataclass(frozen=True)
class Params:
    scale: float = 2.0


class ChannelCounter:
    name = "channel_counter"
    version = "0.1.0"
    params_type = Params
    required_inputs = ("meta.channels",)
    output = OutputSpec(
        fields=(
            OutputField("channel_counter.rows", description="Per-channel rows"),
            OutputField("channel_counter.summary", description="Summary"),
        ),
        panel=PanelSpec(
            id="channel_counter",
            title="Channel Counter",
            kind="table",
            field="channel_counter.rows",
        ),
    )

    def compute(self, dataset, params):
        channels = list(dataset.meta.channels)
        rows = [
            {"channel": c, "index": i, "scaled": i * params.scale}
            for i, c in enumerate(channels)
        ]
        return {"channel_counter": {"rows": rows, "summary": {"channels": len(channels)}}}


method = ChannelCounter()
'''

HOSTILE_SOURCE = '''
import socket
socket.socket().connect(("1.1.1.1", 80))
class M:
    name = "evil"
    compute = lambda self, d, p: {}
method = M()
'''


def minimal_dataset(channel_count: int = 3) -> dict[str, Any]:
    channels = [f"C{i}" for i in range(channel_count)]
    return {
        "meta": {"channels": channels, "n_channels": channel_count},
        "welch_psd": {"frequencies": [8.0, 10.0], "psd": [[0.1, 0.2] for _ in channels]},
        "centroid": {"time_relative": [0.0], "values": [[8.0] for _ in channels]},
        "geometry": {"time": [0.0]},
    }


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROMOUSE_SESSION_TOKENS", f"{USER_A}:user-a,{USER_B}:user-b")
    return create_app(store=SQLiteBackendStore(tmp_path / "be.sqlite3"))


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def _upload(client: TestClient, source: str, headers: dict) -> Any:
    return client.post(
        "/methods",
        files={"file": ("method.py", source.encode("utf-8"), "text/x-python")},
        headers=headers,
    )


@pytest.mark.asyncio
async def test_upload_lists_and_runs_private_method(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/methods",
            files={"file": ("method.py", METHOD_SOURCE.encode("utf-8"), "text/x-python")},
            headers=HEADERS_A,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["id"] == "channel_counter"
        assert body["private"] is True
        assert body["output_spec"]["panel"]["field"] == "channel_counter.rows"

        listed = (await client.get("/methods", headers=HEADERS_A)).json()
        ids = {m["id"] for m in listed}
        assert "channel_counter" in ids and "spike_detect" in ids  # private + built-in

        session_id = (
            await client.post(
                "/sessions", json={"name": "s", "dataset": minimal_dataset(3)}, headers=HEADERS_A
            )
        ).json()["id"]
        created = await client.post(
            f"/sessions/{session_id}/jobs", json={"method_id": "channel_counter"}, headers=HEADERS_A
        )
        assert created.status_code == 201, created.text
        job_id = created.json()["id"]
        deadline = time.perf_counter() + 30.0
        while True:
            job = (await client.get(f"/jobs/{job_id}", headers=HEADERS_A)).json()
            if job["status"] in ("completed", "failed"):
                break
            if time.perf_counter() >= deadline:
                raise AssertionError("job did not finish")
            await asyncio.sleep(0.05)

        assert job["status"] == "completed", job.get("error")
        out = job["result"]["output"]["channel_counter"]
        assert out["summary"]["channels"] == 3
        assert job["result"]["panel"]["field"] == "channel_counter.rows"


def test_private_method_is_isolated_per_user(client: TestClient) -> None:
    _upload(client, METHOD_SOURCE, HEADERS_A)
    # User B sees only built-ins, and cannot run user A's private method.
    b_ids = {m["id"] for m in client.get("/methods", headers=HEADERS_B).json()}
    assert "channel_counter" not in b_ids
    session_b = client.post(
        "/sessions", json={"name": "b", "dataset": minimal_dataset(2)}, headers=HEADERS_B
    ).json()["id"]
    denied = client.post(
        f"/sessions/{session_b}/jobs", json={"method_id": "channel_counter"}, headers=HEADERS_B
    )
    assert denied.status_code == 404


def test_delete_private_method(client: TestClient) -> None:
    _upload(client, METHOD_SOURCE, HEADERS_A)
    assert client.delete("/methods/channel_counter", headers=HEADERS_A).status_code == 204
    assert client.delete("/methods/channel_counter", headers=HEADERS_A).status_code == 404
    ids = {m["id"] for m in client.get("/methods", headers=HEADERS_A).json()}
    assert "channel_counter" not in ids


def test_hostile_upload_rejected_at_registration(client: TestClient) -> None:
    # A method that attacks at import time is contained by the describe sandbox,
    # so registration fails cleanly (422) and nothing is stored.
    resp = _upload(client, HOSTILE_SOURCE, HEADERS_A)
    assert resp.status_code == 422, resp.text
    ids = {m["id"] for m in client.get("/methods", headers=HEADERS_A).json()}
    assert "evil" not in ids
