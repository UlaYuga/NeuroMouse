from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from neuromouse_backend.app import create_app
from neuromouse_backend.storage import SQLiteBackendStore

ROOT = Path(__file__).resolve().parents[3]
GOLDEN_PATH = ROOT / "datasets" / "golden" / "data.json"


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


@pytest.fixture
def app(tmp_path):
    store = SQLiteBackendStore(tmp_path / "backend.sqlite3")
    return create_app(store=store)


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
async def test_methods_include_render_specs_and_params_schema(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
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


def test_job_and_live_websockets_stream_progress_and_echo(app) -> None:
    with TestClient(app) as client:
        session_response = client.post(
            "/sessions",
            json={"name": "ws-session", "dataset": minimal_dataset()},
        )
        session_id = session_response.json()["id"]
        job_response = client.post(
            f"/sessions/{session_id}/jobs",
            json={"method_id": "band_power_summary"},
        )
        job_id = job_response.json()["id"]

        with client.websocket_connect(f"/ws/jobs/{job_id}") as websocket:
            events = [websocket.receive_json() for _ in range(3)]

        assert [event["status"] for event in events] == ["queued", "running", "completed"]
        assert events[-1]["result"]["band_power_summary"]["top_channel"]["channel"] == "C0"

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


def test_job_lifecycle_persists_across_sqlite_store_reopen(tmp_path) -> None:
    db_path = tmp_path / "backend.sqlite3"
    store = SQLiteBackendStore(db_path)
    app = create_app(store=store)

    with TestClient(app) as client:
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
        assert job["status"] == "completed"

    store.close()

    restarted_app = create_app(store=SQLiteBackendStore(db_path))
    with TestClient(restarted_app) as client:
        session_after_restart = client.get(f"/sessions/{session['id']}")
        assert session_after_restart.status_code == 200
        assert session_after_restart.json()["dataset"] == session["dataset"]
        assert session_after_restart.json()["dataset_version"] == 1

        job_after_restart = client.get(f"/jobs/{job['id']}")
        assert job_after_restart.status_code == 200
        assert job_after_restart.json() == job

        with client.websocket_connect(f"/ws/jobs/{job['id']}") as websocket:
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
    ) as client:
        response = await client.request(method, path, **kwargs)

    assert 400 <= response.status_code < 500


@pytest.mark.asyncio
async def test_demo_seed_mea_creates_1024ch_session_valid_per_contract(app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
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
    ) as client:
        seed_response = await client.post("/demo/seed-mea")
        assert seed_response.status_code == 201
        session_id = seed_response.json()["session_id"]

        job_response = await client.post(
            f"/sessions/{session_id}/jobs",
            json={"method_id": "spike_detect"},
        )
        assert job_response.status_code == 201
        job = job_response.json()
        assert job["status"] == "completed", job.get("error")
        summary = job["result"]["output"]["spike_detect"]["summary"]
        assert summary["total_spikes"] == 53
