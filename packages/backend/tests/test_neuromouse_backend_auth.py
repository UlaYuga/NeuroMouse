from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from neuromouse_backend.app import create_app
from neuromouse_backend.auth import hash_password, verify_password
from neuromouse_backend.storage import SQLiteBackendStore


@pytest.fixture
def app(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("NEUROMOUSE_SESSION_TOKENS", raising=False)
    monkeypatch.delenv("NEUROMOUSE_API_TOKEN", raising=False)
    monkeypatch.setenv("NEUROMOUSE_RATE_LIMIT_PER_IP", "1000")
    return create_app(store=SQLiteBackendStore(tmp_path / "backend.sqlite3"))


def test_password_hash_roundtrip() -> None:
    stored = hash_password("s3cret-pw")
    assert stored != "s3cret-pw"
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("s3cret-pw", stored)
    assert not verify_password("wrong", stored)
    # a second hash uses a fresh salt
    assert hash_password("s3cret-pw") != stored


def test_register_login_me_flow(app) -> None:
    with TestClient(app) as client:
        registered = client.post(
            "/auth/register", json={"email": "A@x.io", "password": "pw123456"}
        )
        assert registered.status_code == 201
        assert registered.json()["email"] == "a@x.io"  # normalized

        duplicate = client.post(
            "/auth/register", json={"email": "a@x.io", "password": "pw123456"}
        )
        assert duplicate.status_code == 400

        # protected route rejected without a token
        assert client.get("/sessions").status_code == 401

        login = client.post("/auth/login", json={"email": "a@x.io", "password": "pw123456"})
        assert login.status_code == 200
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        me = client.get("/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["email"] == "a@x.io"

        # issued token unlocks protected routes
        assert client.get("/sessions", headers=headers).status_code == 200

        # wrong password is rejected (and does not leak which field)
        assert client.post(
            "/auth/login", json={"email": "a@x.io", "password": "nope"}
        ).status_code == 401


def test_auth_session_is_optional_without_weakening_me(app) -> None:
    with TestClient(app) as client:
        anonymous_session = client.get("/auth/session")
        assert anonymous_session.status_code == 200
        assert anonymous_session.json() == {"user": None}
        assert client.get("/auth/me").status_code == 401

        client.post("/auth/register", json={"email": "session@x.io", "password": "pw123456"})
        token = client.post(
            "/auth/login", json={"email": "session@x.io", "password": "pw123456"}
        ).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        session = client.get("/auth/session", headers=headers)
        assert session.status_code == 200
        assert session.json()["user"]["email"] == "session@x.io"


def test_logout_invalidates_token(app) -> None:
    with TestClient(app) as client:
        client.post("/auth/register", json={"email": "b@x.io", "password": "pw123456"})
        token = client.post(
            "/auth/login", json={"email": "b@x.io", "password": "pw123456"}
        ).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        assert client.get("/auth/me", headers=headers).status_code == 200
        client.post("/auth/logout", headers=headers)
        assert client.get("/auth/me", headers=headers).status_code == 401


def test_two_users_are_isolated_via_issued_tokens(app) -> None:
    with TestClient(app) as client:
        for email in ("u1@x.io", "u2@x.io"):
            client.post("/auth/register", json={"email": email, "password": "pw123456"})
        t1 = client.post(
            "/auth/login", json={"email": "u1@x.io", "password": "pw123456"}
        ).json()["token"]
        t2 = client.post(
            "/auth/login", json={"email": "u2@x.io", "password": "pw123456"}
        ).json()["token"]

        # u1 creates a private session
        created = client.post(
            "/sessions",
            headers={"Authorization": f"Bearer {t1}"},
            json={"name": "u1-private", "dataset": _minimal_dataset()},
        )
        assert created.status_code == 201
        session_id = created.json()["id"]

        # u2 cannot see or read it
        u2_list = client.get("/sessions", headers={"Authorization": f"Bearer {t2}"})
        assert all(s["id"] != session_id for s in u2_list.json())
        assert client.get(
            f"/sessions/{session_id}", headers={"Authorization": f"Bearer {t2}"}
        ).status_code == 404


def test_public_demo_lane_works_without_auth(app) -> None:
    with TestClient(app) as client:
        # seed reachable without any token -> anonymous session
        seed = client.post("/demo/seed-mea")
        assert seed.status_code == 201
        session_id = seed.json()["session_id"]

        # non-whitelisted method is rejected on the demo lane
        rejected = client.post(
            f"/demo/sessions/{session_id}/jobs",
            json={"method_id": "band_power_summary", "params": {}},
        )
        assert rejected.status_code == 403

        # a whitelisted MEA method is accepted (queued), still no auth
        job = client.post(
            f"/demo/sessions/{session_id}/jobs",
            json={"method_id": "spike_detect", "params": {}},
        )
        assert job.status_code == 201
        assert job.json()["status"] == "queued"

        # a real user's protected routes still demand a token
        assert client.get("/sessions").status_code == 401


def _minimal_dataset() -> dict:
    channels = ["C0", "C1"]
    return {
        "meta": {"channels": channels, "n_channels": 2},
        "welch_psd": {"frequencies": [8.0, 10.0], "psd": [[0.1, 0.2] for _ in channels]},
        "centroid": {"time_relative": [0.0, 0.5], "values": [[8.0, 8.5] for _ in channels]},
        "geometry": {"time": [0.0, 0.5]},
    }
