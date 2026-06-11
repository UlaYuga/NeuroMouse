from __future__ import annotations

from typing import Any

import httpx
import pytest

from neuromouse_backend.app import create_app


def minimal_dataset(channel_count: int = 2) -> dict[str, Any]:
    channels = [f"C{i}" for i in range(channel_count)]
    return {
        "meta": {"channels": channels, "n_channels": channel_count},
        "welch_psd": {
            "frequencies": [1.0, 2.0, 3.0],
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


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_openapi_generates_and_lists_backend_paths(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
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
                "created_at": session["created_at"],
            }
        ]

        get_response = await client.get(f"/sessions/{session['id']}")
        assert get_response.status_code == 200
        assert get_response.json()["dataset"] == session["dataset"]

        methods_response = await client.get("/methods")
        assert methods_response.status_code == 200
        assert {method["id"] for method in methods_response.json()} == {"summary"}

        job_response = await client.post(
            f"/sessions/{session['id']}/jobs",
            json={"method_id": "summary"},
        )
        assert job_response.status_code == 201
        job = job_response.json()
        assert job["status"] == "completed"
        assert job["result"] == {"channel_count": 2, "method_id": "summary"}

        get_job_response = await client.get(f"/jobs/{job['id']}")
        assert get_job_response.status_code == 200
        assert get_job_response.json() == job


def test_job_and_live_websockets_stream_progress_and_echo(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        session_response = client.post(
            "/sessions",
            json={"name": "ws-session", "dataset": minimal_dataset()},
        )
        session_id = session_response.json()["id"]
        job_response = client.post(
            f"/sessions/{session_id}/jobs",
            json={"method_id": "summary"},
        )
        job_id = job_response.json()["id"]

        with client.websocket_connect(f"/ws/jobs/{job_id}") as websocket:
            events = [websocket.receive_json() for _ in range(3)]

        assert [event["status"] for event in events] == ["queued", "running", "completed"]
        assert events[-1]["result"] == {"channel_count": 2, "method_id": "summary"}

        with client.websocket_connect("/ws/live") as websocket:
            websocket.send_json({"kind": "ping", "samples": [1, 2, 3]})
            assert websocket.receive_json() == {"kind": "ping", "samples": [1, 2, 3]}


@pytest.mark.asyncio
async def test_invalid_dataset_returns_422_with_clear_contract_error(app) -> None:
    dataset = minimal_dataset()
    dataset["meta"]["channels"] = []

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/sessions", json={"dataset": dataset})

    assert response.status_code == 422
    assert "meta.channels" in response.text
    assert "non-empty" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("POST", "/sessions", {"content": b"{", "headers": {"content-type": "application/json"}}),
        ("POST", "/sessions", {"json": {"name": "missing-dataset"}}),
        ("POST", "/sessions", {"json": {"dataset": {"meta": {"channels": []}}}}),
        ("POST", "/sessions/not-found/jobs", {"json": {"method_id": "summary"}}),
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
    ) as client:
        response = await client.request(method, path, **kwargs)

    assert 400 <= response.status_code < 500
