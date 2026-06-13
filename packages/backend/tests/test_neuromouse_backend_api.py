from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from neuromouse_backend.app import MethodCatalog, create_app
from neuromouse_backend.storage import SQLiteBackendStore
from neuromouse_sdk import Method
from neuromouse_sdk.examples.band_power_summary import BandPowerParams, band_power_summary

ROOT = Path(__file__).resolve().parents[3]
GOLDEN_PATH = ROOT / "datasets" / "golden" / "data.json"
USER_A_TOKEN: Final = "neuromouse-user-a-token"
USER_B_TOKEN: Final = "neuromouse-user-b-token"
AUTH_HEADERS: Final = {"Authorization": f"Bearer {USER_A_TOKEN}"}
USER_B_HEADERS: Final = {"Authorization": f"Bearer {USER_B_TOKEN}"}
SESSION_TOKENS: Final = f"{USER_A_TOKEN}:user-a,{USER_B_TOKEN}:user-b"


def minimal_dataset(channel_count: int = 2) -> dict[str, Any]:
    channels = [f"C{i}" for i in range(channel_count)]
    return {
        "meta": {"channels": channels, "n_channels": channel_count},
        "welch_psd": {
            "frequencies": [8.0, 10.0, 12.0],
            "psd": [[0.1, 0.2, 0.3] for _ in channels],
        },
        "centroid": {
            "time_relative": [0.0, 0.5],
            "values": [[8.0, 8.5] for _ in channels],
        },
        "geometry": {
            "time": [0.0, 0.5],
            "centroid": [[8.0, 8.5] for _ in channels],
            "spread": [[1.0, 1.1] for _ in channels],
            "entropy": [[0.6, 0.7] for _ in channels],
            "flatness": [[0.2, 0.3] for _ in channels],
            "edge95": [[24.0, 24.5] for _ in channels],
            "alpha_relative_power": [[0.3, 0.31] for _ in channels],
            "area_normalized_psd": {
                "frequencies": [1.0, 2.0, 3.0],
                "psd": [[0.01, 0.02, 0.03] for _ in channels],
            },
        },
        "channel_summary": [
            {
                "channel": channel,
                "hemisphere": "",
                "region": "unknown",
                "has_clear_alpha_peak": False,
                "alpha_relative_power": 0.3,
                "spectral_centroid_hz": 8.0,
                "spectral_spread_hz": 1.0,
                "spectral_entropy": 0.6,
                "spectral_flatness": 0.2,
                "edge95_hz": 24.0,
                "alpha_peak_frequency_hz": 10.0,
                "sliding_alpha_relative_mean": 0.29,
            }
            for channel in channels
        ],
    }


class SlowBandPowerMethod(Method[Any]):
    name = "band_power_summary"
    version = "0.0.0"
    params_type = BandPowerParams
    required_inputs = band_power_summary.required_inputs
    output = band_power_summary.output

    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds

    def compute(self, dataset: Any, params: BandPowerParams) -> dict[str, Any]:
        time.sleep(self.delay_seconds)
        return band_power_summary.compute(dataset, params)


def _slow_job_app(tmp_path: Path, monkeypatch, delay_seconds: float = 0.4):
    monkeypatch.setenv("NEUROMOUSE_SESSION_TOKENS", SESSION_TOKENS)
    monkeypatch.setenv("NEUROMOUSE_RATE_LIMIT_PER_IP", "1000")
    return create_app(
        store=SQLiteBackendStore(tmp_path / "backend.sqlite3"),
        method_catalog=MethodCatalog(
            methods={"band_power_summary": SlowBandPowerMethod(delay_seconds)}
        ),
    )


async def _wait_job_done(
    client: httpx.AsyncClient,
    job_id: str,
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.01,
) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout
    while True:
        response = await client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"completed", "failed"}:
            return job
        if job["status"] not in {"queued", "running"}:
            raise AssertionError(f"unexpected status {job['status']}")
        if time.perf_counter() >= deadline:
            raise AssertionError(f"job {job_id} did not complete in {timeout} seconds")
        await asyncio.sleep(poll_interval)


def _wait_job_done_sync(
    client: TestClient,
    job_id: str,
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.01,
) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout
    while True:
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"completed", "failed"}:
            return job
        if job["status"] not in {"queued", "running"}:
            raise AssertionError(f"unexpected status {job['status']}")
        if time.perf_counter() >= deadline:
            raise AssertionError(f"job {job_id} did not complete in {timeout} seconds")
        time.sleep(poll_interval)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROMOUSE_SESSION_TOKENS", SESSION_TOKENS)
    monkeypatch.setenv("NEUROMOUSE_RATE_LIMIT_PER_IP", "1000")
    monkeypatch.setenv("NEUROMOUSE_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("NEUROMOUSE_CORS_ALLOWLIST", "https://example.org")
    store = SQLiteBackendStore(tmp_path / "backend.sqlite3")
    return create_app(store=store)


@pytest.mark.asyncio
async def test_auth_required_for_protected_routes_and_health_is_public(tmp_path, monkeypatch) -> None:  # noqa: E501
    monkeypatch.setenv("NEUROMOUSE_SESSION_TOKENS", SESSION_TOKENS)
    monkeypatch.delenv("NEUROMOUSE_API_TOKEN", raising=False)
    app = create_app(store=SQLiteBackendStore(tmp_path / "backend.sqlite3"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        protected_response = await client.get("/sessions")
        assert protected_response.status_code == 401

        invalid_response = await client.get(
            "/sessions",
            headers={"Authorization": "Bearer invalid"},
        )
        assert invalid_response.status_code == 401

        public_response = await client.get("/health")
        assert public_response.status_code == 200

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        authorized_response = await client.get("/sessions")
        assert authorized_response.status_code == 200


@pytest.mark.asyncio
async def test_api_disabled_without_token_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NEUROMOUSE_SESSION_TOKENS", raising=False)
    monkeypatch.delenv("NEUROMOUSE_API_TOKEN", raising=False)
    app = create_app(store=SQLiteBackendStore(tmp_path / "backend.sqlite3"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/sessions")
        assert response.status_code == 401

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        public_response = await client.get("/ready")
        assert public_response.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_returns_429_after_budget_exhausted(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NEUROMOUSE_SESSION_TOKENS", SESSION_TOKENS)
    monkeypatch.setenv("NEUROMOUSE_RATE_LIMIT_PER_IP", "2")
    app = create_app(store=SQLiteBackendStore(tmp_path / "backend.sqlite3"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        assert (await client.get("/methods")).status_code == 200
        assert (await client.get("/methods")).status_code == 200
        too_many_response = await client.get("/methods")
        assert too_many_response.status_code == 429


@pytest.mark.asyncio
async def test_cors_preflight_honors_allowlist(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NEUROMOUSE_SESSION_TOKENS", SESSION_TOKENS)
    monkeypatch.setenv(
        "NEUROMOUSE_CORS_ALLOWLIST",
        "https://allowed.example.com,https://another.example.com",
    )
    app = create_app(store=SQLiteBackendStore(tmp_path / "backend.sqlite3"))

    preflight_headers = {
        "Origin": "https://allowed.example.com",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        allowed_response = await client.options("/sessions", headers=preflight_headers)

    assert allowed_response.status_code == 200
    assert allowed_response.headers["access-control-allow-origin"] == "https://allowed.example.com"

    blocked_headers = {
        "Origin": "https://blocked.example.com",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        blocked_response = await client.options("/sessions", headers=blocked_headers)

    assert blocked_response.status_code in {200, 400}
    assert "access-control-allow-origin" not in (
        key.lower() for key in blocked_response.headers.keys()
    )


@pytest.mark.asyncio
async def test_openapi_generates_and_lists_backend_paths(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert set(paths) >= {
        "/sessions",
        "/sessions/{session_id}",
        "/methods",
        "/sessions/{session_id}/jobs",
        "/jobs/{job_id}",
        "/ws/jobs/{job_id}",
        "/ws/live",
    }


@pytest.mark.asyncio
async def test_rest_happy_path_creates_session_runs_job_and_returns_result(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        create_response = await client.post(
            "/sessions",
            json={"name": "baseline", "dataset": minimal_dataset()},
        )
        assert create_response.status_code == 201
        session = create_response.json()
        assert session["id"]
        assert session["name"] == "baseline"
        assert session["dataset"]["meta"]["channels"] == ["C0", "C1"]

        list_response = await client.get("/sessions")
        assert list_response.status_code == 200
        assert list_response.json() == [
            {
                "id": session["id"],
                "name": "baseline",
                "channel_count": 2,
                "dataset_version": 1,
                "created_at": session["created_at"],
            }
        ]

        get_response = await client.get(f"/sessions/{session['id']}")
        assert get_response.status_code == 200
        assert get_response.json()["dataset"] == session["dataset"]

        methods_response = await client.get("/methods")
        assert methods_response.status_code == 200
        assert {method["id"] for method in methods_response.json()} == {
            "band_power_summary",
            "spike_detect",
            "network_burst",
            "electrode_connectivity",
        }

        job_response = await client.post(
            f"/sessions/{session['id']}/jobs",
            json={"method_id": "band_power_summary", "params": {"min_hz": 8.0, "max_hz": 12.0}},
        )
        assert job_response.status_code == 201
        job = job_response.json()
        assert job["status"] == "queued"
        job = await _wait_job_done(client, job["id"])
        assert job["status"] == "completed"
        assert job["dataset_version"] == 1
        assert job["params"] == {"min_hz": 8.0, "max_hz": 12.0}
        assert job["result"]["output"]["band_power_summary"]["band"] == {
            "min_hz": 8.0,
            "max_hz": 12.0,
        }
        assert job["result"]["output"]["band_power_summary"]["mean_power"] == pytest.approx(0.8)
        assert job["result"]["panel"]["kind"] == "table"
        assert job["result"]["panel"]["field"] == "band_power_summary.channels"

        get_job_response = await client.get(f"/jobs/{job['id']}")
        assert get_job_response.status_code == 200
        assert get_job_response.json() == job


@pytest.mark.asyncio
async def test_users_only_list_read_and_run_their_own_sessions_and_jobs(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        user_a_session_response = await client.post(
            "/sessions",
            headers=AUTH_HEADERS,
            json={"name": "user-a-session", "dataset": minimal_dataset()},
        )
        assert user_a_session_response.status_code == 201
        user_a_session = user_a_session_response.json()

        user_a_job_response = await client.post(
            f"/sessions/{user_a_session['id']}/jobs",
            headers=AUTH_HEADERS,
            json={"method_id": "band_power_summary"},
        )
        assert user_a_job_response.status_code == 201
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers=AUTH_HEADERS,
        ) as user_a_client:
            user_a_job = await _wait_job_done(
                user_a_client,
                user_a_job_response.json()["id"],
            )
        assert user_a_job["status"] == "completed"

        user_b_list_response = await client.get("/sessions", headers=USER_B_HEADERS)
        assert user_b_list_response.status_code == 200
        assert user_b_list_response.json() == []

        user_b_get_session_response = await client.get(
            f"/sessions/{user_a_session['id']}",
            headers=USER_B_HEADERS,
        )
        assert user_b_get_session_response.status_code == 404
        assert "user-a-session" not in user_b_get_session_response.text
        assert user_a_session["id"] not in user_b_get_session_response.text

        user_b_run_job_response = await client.post(
            f"/sessions/{user_a_session['id']}/jobs",
            headers=USER_B_HEADERS,
            json={"method_id": "band_power_summary"},
        )
        assert user_b_run_job_response.status_code == 404
        assert user_a_session["id"] not in user_b_run_job_response.text

        user_b_get_job_response = await client.get(
            f"/jobs/{user_a_job['id']}",
            headers=USER_B_HEADERS,
        )
        assert user_b_get_job_response.status_code == 404
        assert user_a_job["id"] not in user_b_get_job_response.text
        assert user_a_session["id"] not in user_b_get_job_response.text

        user_b_session_response = await client.post(
            "/sessions",
            headers=USER_B_HEADERS,
            json={"name": "user-b-session", "dataset": minimal_dataset(channel_count=3)},
        )
        assert user_b_session_response.status_code == 201
        user_b_session = user_b_session_response.json()

        user_a_list_response = await client.get("/sessions", headers=AUTH_HEADERS)
        assert user_a_list_response.status_code == 200
        assert [session["id"] for session in user_a_list_response.json()] == [
            user_a_session["id"]
        ]

        user_b_list_response = await client.get("/sessions", headers=USER_B_HEADERS)
        assert user_b_list_response.status_code == 200
        assert [session["id"] for session in user_b_list_response.json()] == [
            user_b_session["id"]
        ]


@pytest.mark.asyncio
async def test_routes_persist_owner_id_in_storage_and_complete_owned_job(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEUROMOUSE_SESSION_TOKENS", SESSION_TOKENS)
    monkeypatch.setenv("NEUROMOUSE_RATE_LIMIT_PER_IP", "1000")
    db_path = tmp_path / "backend.sqlite3"
    app = create_app(store=SQLiteBackendStore(db_path))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        session_response = await client.post(
            "/sessions",
            json={"name": "stored-owner", "dataset": minimal_dataset()},
        )
        assert session_response.status_code == 201
        session = session_response.json()

        job_response = await client.post(
            f"/sessions/{session['id']}/jobs",
            json={"method_id": "band_power_summary"},
        )
        assert job_response.status_code == 201
        completed_job = await _wait_job_done(client, job_response.json()["id"])

    assert completed_job["status"] == "completed"
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        session_owner = connection.execute(
            "SELECT owner_id FROM sessions WHERE id = ?",
            (session["id"],),
        ).fetchone()
        dataset_owner = connection.execute(
            "SELECT owner_id FROM datasets WHERE session_id = ?",
            (session["id"],),
        ).fetchone()
        job_owner = connection.execute(
            "SELECT owner_id FROM jobs WHERE id = ?",
            (completed_job["id"],),
        ).fetchone()

    assert session_owner is not None
    assert dataset_owner is not None
    assert job_owner is not None
    assert session_owner["owner_id"] == "user-a"
    assert dataset_owner["owner_id"] == "user-a"
    assert job_owner["owner_id"] == "user-a"


@pytest.mark.asyncio
async def test_methods_include_render_specs_and_params_schema(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        response = await client.get("/methods")

    assert response.status_code == 200
    methods = response.json()
    band_power = next(method for method in methods if method["id"] == "band_power_summary")

    assert band_power["params_schema"]["title"] == "BandPowerParams"
    assert band_power["params_schema"]["properties"]["min_hz"]["default"] == 8.0
    assert band_power["params_schema"]["properties"]["max_hz"]["default"] == 13.0
    assert band_power["output_spec"]["panel"] == {
        "id": "band_power_summary",
        "title": "Band Power Summary",
        "kind": "table",
        "field": "band_power_summary.channels",
    }
    assert band_power["output_spec"]["fields"] == [
        {
            "path": "band_power_summary.band",
            "label": "Band",
            "description": "Frequency band used for integration",
            "unit": None,
        },
        {
            "path": "band_power_summary.channels",
            "label": "Channels",
            "description": "Per-channel band-power rows",
            "unit": None,
        },
        {
            "path": "band_power_summary.mean_power",
            "label": "Mean Power",
            "description": "Mean band power across channels",
            "unit": None,
        },
        {
            "path": "band_power_summary.top_channel",
            "label": "Top Channel",
            "description": "Channel with highest band power",
            "unit": None,
        },
    ]


@pytest.mark.asyncio
async def test_demo_seed_creates_runnable_session_from_golden_dataset(app) -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        seed_response = await client.post("/demo/seed")
        assert seed_response.status_code == 201
        seed = seed_response.json()
        assert seed["session_id"]
        assert seed["dataset_id"]
        assert seed["dataset_version"] == 1

        session_response = await client.get(f"/sessions/{seed['session_id']}")
        assert session_response.status_code == 200
        session = session_response.json()
        assert session["dataset"]["meta"]["channels"] == golden["meta"]["channels"]
        assert len(session["dataset"]["channel_summary"]) == len(golden["channel_summary"])
        assert session["channel_count"] == golden["meta"]["n_channels"]

        job_response = await client.post(
            f"/sessions/{seed['session_id']}/jobs",
            json={"method_id": "band_power_summary", "params": {"min_hz": 8.0, "max_hz": 13.0}},
        )
        assert job_response.status_code == 201
        job = job_response.json()
        assert job["status"] == "queued"
        job = await _wait_job_done(client, job["id"])
        assert job["status"] == "completed"
        assert job["result"]["panel"] == {
            "id": "band_power_summary",
            "title": "Band Power Summary",
            "kind": "table",
            "field": "band_power_summary.channels",
        }
        assert job["result"]["output_spec"]["fields"][1]["path"] == "band_power_summary.channels"
        channels = job["result"]["output"]["band_power_summary"]["channels"]
        assert len(channels) == seed["channel_count"]

        get_job_response = await client.get(f"/jobs/{job['id']}")
        assert get_job_response.status_code == 200
        assert get_job_response.json()["result"] == job["result"]


def test_job_and_live_websockets_stream_progress_and_echo(tmp_path, monkeypatch) -> None:
    app = _slow_job_app(tmp_path, monkeypatch, delay_seconds=0.4)
    with TestClient(app, headers=AUTH_HEADERS) as client:
        session_response = client.post(
            "/sessions",
            json={"name": "ws-session", "dataset": minimal_dataset()},
        )
        session_id = session_response.json()["id"]
        job_response = client.post(
            f"/sessions/{session_id}/jobs",
            json={"method_id": "band_power_summary", "params": {"min_hz": 8.0, "max_hz": 12.0}},
        )
        assert job_response.status_code == 201
        assert job_response.json()["status"] == "queued"
        job_id = job_response.json()["id"]

        with client.websocket_connect(
            f"/ws/jobs/{job_id}",
            headers=AUTH_HEADERS,
        ) as websocket:
            events = [websocket.receive_json() for _ in range(3)]

        assert [event["status"] for event in events] == ["queued", "running", "completed"]
        assert events[-1]["result"]["band_power_summary"]["top_channel"]["channel"] == "C0"

        with client.websocket_connect("/ws/live", headers=AUTH_HEADERS) as websocket:
            websocket.send_json({"kind": "ping", "samples": [1, 2, 3]})
            assert websocket.receive_json() == {"kind": "ping", "samples": [1, 2, 3]}


def test_job_websocket_does_not_stream_cross_user_job(tmp_path, monkeypatch) -> None:
    app = _slow_job_app(tmp_path, monkeypatch, delay_seconds=0.4)
    with TestClient(app) as client:
        session_response = client.post(
            "/sessions",
            headers=AUTH_HEADERS,
            json={"name": "ws-owner", "dataset": minimal_dataset()},
        )
        assert session_response.status_code == 201
        session_id = session_response.json()["id"]
        job_response = client.post(
            f"/sessions/{session_id}/jobs",
            headers=AUTH_HEADERS,
            json={"method_id": "band_power_summary"},
        )
        assert job_response.status_code == 201
        job_id = job_response.json()["id"]

        with client.websocket_connect(
            f"/ws/jobs/{job_id}",
            headers=USER_B_HEADERS,
        ) as websocket:
            denied = websocket.receive_json()
            assert denied == {"status": "not_found", "error": "Job not found"}
            assert job_id not in json.dumps(denied)
            assert session_id not in json.dumps(denied)
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


@pytest.mark.asyncio
async def test_async_jobs_are_non_blocking(tmp_path, monkeypatch) -> None:
    app = _slow_job_app(tmp_path, monkeypatch, delay_seconds=1.0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        session_response = await client.post(
            "/sessions",
            json={"name": "concurrent", "dataset": minimal_dataset()},
        )
        assert session_response.status_code == 201
        session_id = session_response.json()["id"]

        slow_job_task = asyncio.create_task(
            client.post(
                f"/sessions/{session_id}/jobs",
                json={"method_id": "band_power_summary", "params": {"min_hz": 8.0, "max_hz": 12.0}},
            )
        )
        methods_response = await asyncio.wait_for(client.get("/methods"), timeout=0.2)
        assert methods_response.status_code == 200

        slow_job_response = await asyncio.wait_for(slow_job_task, timeout=1.0)
        assert slow_job_response.status_code == 201
        slow_job = slow_job_response.json()
        assert slow_job["status"] == "queued"

        final_job = await _wait_job_done(client, slow_job["id"], timeout=3.0)
        assert final_job["status"] == "completed"
        assert final_job["result"]["output"]["band_power_summary"]["mean_power"] == pytest.approx(0.8)  # noqa: E501


@pytest.mark.asyncio
async def test_job_lifecycle_states_are_queued_running_and_completed(tmp_path, monkeypatch) -> None:  # noqa: E501
    app = _slow_job_app(tmp_path, monkeypatch, delay_seconds=0.4)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        session_response = await client.post(
            "/sessions",
            json={"name": "lifecycle", "dataset": minimal_dataset()},
        )
        assert session_response.status_code == 201
        session_id = session_response.json()["id"]

        job_response = await client.post(
            f"/sessions/{session_id}/jobs",
            json={"method_id": "band_power_summary", "params": {"min_hz": 8.0, "max_hz": 12.0}},
        )
        assert job_response.status_code == 201
        assert job_response.json()["status"] == "queued"
        job_id = job_response.json()["id"]

        seen_statuses = ["queued"]
        deadline = time.perf_counter() + 3.0
        while time.perf_counter() < deadline:
            response = await client.get(f"/jobs/{job_id}")
            assert response.status_code == 200
            status = response.json()["status"]
            if seen_statuses[-1] != status:
                seen_statuses.append(status)
            if status == "completed":
                break
            await asyncio.sleep(0.01)

        assert seen_statuses == ["queued", "running", "completed"]
@pytest.mark.asyncio
async def test_invalid_dataset_returns_422_with_clear_contract_error(app) -> None:
    dataset = minimal_dataset()
    dataset["meta"]["channels"] = []

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        response = await client.post("/sessions", json={"dataset": dataset})

    assert response.status_code == 422
    assert "meta.channels" in response.text
    assert "non-empty" in response.text


def test_job_lifecycle_persists_across_sqlite_store_reopen(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NEUROMOUSE_SESSION_TOKENS", SESSION_TOKENS)
    monkeypatch.delenv("NEUROMOUSE_API_TOKEN", raising=False)
    db_path = tmp_path / "backend.sqlite3"
    store = SQLiteBackendStore(db_path)
    app = create_app(store=store)

    with TestClient(app, headers=AUTH_HEADERS) as client:
        session_response = client.post(
            "/sessions",
            json={"name": "persistent", "dataset": minimal_dataset(channel_count=3)},
        )
        assert session_response.status_code == 201
        session = session_response.json()
        assert session["dataset_version"] == 1

        job_response = client.post(
            f"/sessions/{session['id']}/jobs",
            json={"method_id": "band_power_summary"},
        )
        assert job_response.status_code == 201
        job = job_response.json()
        assert job["status"] == "queued"
        job = _wait_job_done_sync(client, job["id"])
        assert job["status"] == "completed"

    store.close()

    restarted_app = create_app(store=SQLiteBackendStore(db_path))
    with TestClient(restarted_app, headers=AUTH_HEADERS) as client:
        session_after_restart = client.get(f"/sessions/{session['id']}")
        assert session_after_restart.status_code == 200
        assert session_after_restart.json()["dataset"] == session["dataset"]
        assert session_after_restart.json()["dataset_version"] == 1

        job_after_restart = client.get(f"/jobs/{job['id']}")
        assert job_after_restart.status_code == 200
        assert job_after_restart.json() == _wait_job_done_sync(client, job["id"])

        with client.websocket_connect(f"/ws/jobs/{job['id']}", headers=AUTH_HEADERS) as websocket:
            events = [websocket.receive_json() for _ in range(3)]
        assert [event["status"] for event in events] == ["queued", "running", "completed"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("POST", "/sessions", {"content": b"{", "headers": {"content-type": "application/json"}}),
        ("POST", "/sessions", {"json": {"name": "missing-dataset"}}),
        ("POST", "/sessions", {"json": {"dataset": {"meta": {"channels": []}}}}),
        ("POST", "/sessions/not-found/jobs", {"json": {"method_id": "band_power_summary"}}),
        ("GET", "/jobs/not-found", {}),
    ],
)
async def test_malformed_inputs_return_clean_4xx_not_5xx(
    app,
    method: str,
    path: str,
    kwargs: dict[str, Any],
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        response = await client.request(method, path, **kwargs)

    assert 400 <= response.status_code < 500


@pytest.mark.asyncio
async def test_demo_seed_mea_creates_1024ch_session_valid_per_contract(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        seed_response = await client.post("/demo/seed-mea")
        assert seed_response.status_code == 201
        seed = seed_response.json()
        assert seed["session_id"]
        assert seed["dataset_id"]
        assert seed["dataset_version"] == 1
        assert seed["channel_count"] == 1024

        session_response = await client.get(f"/sessions/{seed['session_id']}")
        assert session_response.status_code == 200
        session = session_response.json()
        assert len(session["dataset"]["meta"]["channels"]) == 1024
        assert session["dataset"]["mea"]["sampling_rate_hz"] == 1000.0
        assert len(session["dataset"]["mea"]["traces"]) == 1024
        assert session["channel_count"] == 1024


@pytest.mark.asyncio
async def test_methods_list_includes_all_three_mea_methods(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        response = await client.get("/methods")

    assert response.status_code == 200
    method_ids = {m["id"] for m in response.json()}
    assert {"spike_detect", "network_burst", "electrode_connectivity"}.issubset(method_ids)
    spike_method = next(m for m in response.json() if m["id"] == "spike_detect")
    assert spike_method["output_spec"]["panel"]["kind"] == "heatmap_table"
    assert spike_method["output_spec"]["panel"]["field"] == "spike_detect.rates"


@pytest.mark.asyncio
async def test_spike_detect_on_mea_seed_returns_57_spikes(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=AUTH_HEADERS,
    ) as client:
        seed_response = await client.post("/demo/seed-mea")
        assert seed_response.status_code == 201
        session_id = seed_response.json()["session_id"]

        job_response = await client.post(
            f"/sessions/{session_id}/jobs",
            json={"method_id": "spike_detect"},
        )
        assert job_response.status_code == 201
        job = await _wait_job_done(client, job_response.json()["id"])
        assert job["status"] == "completed", job.get("error")
        summary = job["result"]["output"]["spike_detect"]["summary"]
        assert summary["total_spikes"] == 53
