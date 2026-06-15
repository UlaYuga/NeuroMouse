from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from neuromouse_backend import storage as storage_module
from neuromouse_backend.storage import PostgreSQLBackendStore, SQLiteBackendStore


def dataset_for(channel_count: int, frequency_count: int, time_count: int) -> dict[str, Any]:
    channels = [f"C{i}" for i in range(channel_count)]
    frequencies = [float(8 + index) for index in range(frequency_count)]
    psd = [
        [
            float((channel_index + 1) * (frequency_index + 1))
            for frequency_index in range(frequency_count)
        ]
        for channel_index in range(channel_count)
    ]
    time = [float(index) for index in range(time_count)]
    values = [
        [float(channel_index + index) for index in range(time_count)]
        for channel_index in range(channel_count)
    ]
    return {
        "meta": {"channels": channels, "n_channels": channel_count},
        "welch_psd": {"frequencies": frequencies, "psd": psd},
        "centroid": {"time_relative": time, "values": values},
        "geometry": {"time": time},
    }


def make_backend(backend_name: str, tmp_path: Path) -> tuple[str | Path, SQLiteBackendStore | PostgreSQLBackendStore]:  # noqa: E501
    if backend_name == "sqlite":
        return tmp_path / "backend.sqlite3", SQLiteBackendStore(tmp_path / "backend.sqlite3")

    if backend_name != "postgres":
        raise ValueError(f"unknown backend: {backend_name}")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is not set for postgres backend tests")

    return database_url, PostgreSQLBackendStore(database_url=database_url)


def _close_backend(store: SQLiteBackendStore | PostgreSQLBackendStore) -> None:
    if hasattr(store, "close"):
        store.close()


def _reopen_store(backend_name: str, source: str | Path) -> SQLiteBackendStore | PostgreSQLBackendStore:  # noqa: E501
    if backend_name == "sqlite":
        return SQLiteBackendStore(source)
    return PostgreSQLBackendStore(database_url=str(source))


def test_postgres_store_uses_pool_and_migrates_once(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResult:
        def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
            self._rows = rows or []

        def fetchall(self) -> list[dict[str, Any]]:
            return list(self._rows)

    class FakeConnection:
        def __init__(self) -> None:
            self.migration_selects = 0
            self.commits = 0
            self.inserted_migrations: list[str] = []

        def __enter__(self) -> FakeConnection:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> FakeResult:
            if "SELECT name FROM schema_migrations" in sql:
                self.migration_selects += 1
            if "INSERT INTO schema_migrations" in sql and params is not None:
                self.inserted_migrations.append(str(params[0]))
            return FakeResult()

        def commit(self) -> None:
            self.commits += 1

    class FakePsycopg:
        def __init__(self) -> None:
            self.direct_connects = 0

        def connect(self, *_args: object, **_kwargs: object) -> FakeConnection:
            self.direct_connects += 1
            return FakeConnection()

    class FakePool:
        instances: list[FakePool] = []

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.connection_calls = 0
            self._connection = FakeConnection()
            self.closed = False
            FakePool.instances.append(self)

        @contextmanager
        def connection(self):
            self.connection_calls += 1
            yield self._connection

        def close(self, *_args: object, **_kwargs: object) -> None:
            self.closed = True

    fake_psycopg = FakePsycopg()
    monkeypatch.setattr(storage_module, "_require_psycopg", lambda: (fake_psycopg, object()))
    monkeypatch.setattr(storage_module, "_require_psycopg_pool", lambda: FakePool, raising=False)

    store = PostgreSQLBackendStore(database_url="postgresql://example.test/neuromouse")
    try:
        for _ in range(3):
            with store._connect() as connection:  # type: ignore[attr-defined]
                assert connection is FakePool.instances[0]._connection

        assert fake_psycopg.direct_connects == 0
        assert len(FakePool.instances) == 1
        assert FakePool.instances[0].connection_calls == 4
        assert FakePool.instances[0]._connection.migration_selects == 1
        assert FakePool.instances[0]._connection.commits == 1
        assert FakePool.instances[0]._connection.inserted_migrations == [
            path.name for path in storage_module._migration_paths("postgres")
        ]
    finally:
        _close_backend(store)


@pytest.mark.parametrize("backend_name", ["sqlite", "postgres"])
def test_storage_ownerscope_by_query_identity(
    backend_name: str,
    tmp_path: Path,
) -> None:
    source, store = make_backend(backend_name, tmp_path)
    try:
        owner_a = "owner-a"
        owner_b = "owner-b"
        dataset_a = dataset_for(3, 2, 2)

        session_a = store.create_session_with_owner(
            name="owner-a",
            dataset=dataset_a,
            owner_id=owner_a,
        )
        session_b = store.create_session_with_owner(
            name="owner-b",
            dataset=dataset_a,
            owner_id=owner_b,
        )

        assert session_a.owner_id == owner_a
        assert session_b.owner_id == owner_b
        assert session_a in store.list_sessions(owner_id=owner_a)
        assert session_b not in store.list_sessions(owner_id=owner_a)
        assert session_b in store.list_sessions(owner_id=owner_b)
        assert session_a not in store.list_sessions(owner_id=owner_b)
        assert store.get_session(session_a.id, owner_id=owner_b) is None
        assert store.get_session(session_a.id, owner_id=owner_a) == session_a

        demo_session = store.create_session(name="demo", dataset=dataset_a)
        assert demo_session.owner_id == "anonymous"
        assert demo_session in store.list_sessions()
        assert store.get_session(demo_session.id) == demo_session

        job_a = store.create_job_with_owner(
            session_id=session_a.id,
            dataset_version=session_a.dataset_version,
            method_id="band_power_summary",
            params={"frequency_count": 2},
            owner_id=owner_a,
        )
        job_b = store.create_job_with_owner(
            session_id=session_b.id,
            dataset_version=session_b.dataset_version,
            method_id="band_power_summary",
            params={"frequency_count": 2},
            owner_id=owner_b,
        )
        anonymous_job = store.create_job(
            session_id=demo_session.id,
            dataset_version=demo_session.dataset_version,
            method_id="band_power_summary",
            params={"frequency_count": 2},
        )

        assert store.get_job(job_a.id, owner_id=owner_a) == job_a
        assert store.get_job(job_a.id, owner_id=owner_b) is None
        assert store.get_job(job_b.id, owner_id=owner_b) == job_b
        assert store.get_job(job_b.id, owner_id=owner_a) is None
        assert store.get_job(anonymous_job.id) == anonymous_job

        with store._connect() as connection:  # type: ignore[attr-defined]
            if backend_name == "sqlite":
                session_owner = connection.execute(
                    "SELECT owner_id FROM sessions WHERE id = ?",
                    (session_a.id,),
                ).fetchone()
                dataset_owner = connection.execute(
                    "SELECT owner_id FROM datasets WHERE session_id = ?",
                    (session_a.id,),
                ).fetchone()
                job_owner = connection.execute(
                    "SELECT owner_id FROM jobs WHERE id = ?",
                    (job_a.id,),
                ).fetchone()
            else:
                session_owner = connection.execute(
                    "SELECT owner_id FROM sessions WHERE id = %s",
                    (session_a.id,),
                ).fetchone()
                dataset_owner = connection.execute(
                    "SELECT owner_id FROM datasets WHERE session_id = %s",
                    (session_a.id,),
                ).fetchone()
                job_owner = connection.execute(
                    "SELECT owner_id FROM jobs WHERE id = %s",
                    (job_a.id,),
                ).fetchone()

            assert session_owner is not None
            assert dataset_owner is not None
            assert job_owner is not None
            assert session_owner["owner_id"] == owner_a
            assert dataset_owner["owner_id"] == owner_a
            assert job_owner["owner_id"] == owner_a
    finally:
        _close_backend(store)


@pytest.mark.parametrize("backend_name", ["sqlite", "postgres"])
@given(
    name=st.one_of(st.none(), st.text(alphabet=st.characters(max_codepoint=126), max_size=24)),
    channel_count=st.integers(min_value=1, max_value=6),
    frequency_count=st.integers(min_value=1, max_value=6),
    time_count=st.integers(min_value=1, max_value=6),
    method_id=st.text(
        alphabet=st.characters(min_codepoint=48, max_codepoint=122),
        min_size=1,
        max_size=24,
    ),
)
@settings(
    max_examples=40,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_storage_round_trips_sessions_dataset_versions_jobs_and_events_for_backends(
    backend_name: str,
    tmp_path: Path,
    name: str | None,
    channel_count: int,
    frequency_count: int,
    time_count: int,
    method_id: str,
) -> None:
    source, store = make_backend(backend_name, tmp_path)
    try:
        dataset = dataset_for(channel_count, frequency_count, time_count)
        result = {"method": method_id, "channels": channel_count}

        session = store.create_session(name=name, dataset=dataset)
        assert session.dataset_version == 1
        assert store.get_session(session.id) == session
        assert session in store.list_sessions()

        job = store.create_job(
            session_id=session.id,
            dataset_version=session.dataset_version,
            method_id=method_id,
            params={"frequency_count": frequency_count},
        )
        assert job.status == "queued"
        assert job.events[0]["status"] == "queued"

        running = store.append_job_event(job.id, status="running")
        completed = store.append_job_event(job.id, status="completed", result=result)
        assert running.status == "running"
        assert completed.result == result
        assert [event["status"] for event in completed.events] == ["queued", "running", "completed"]

        store.close()
        reopened = _reopen_store(backend_name, source)
        try:
            assert reopened.get_session(session.id) == session
            assert reopened.get_job(job.id) == completed
        finally:
            _close_backend(reopened)
    finally:
        _close_backend(store)


@pytest.mark.parametrize("backend_name", ["sqlite", "postgres"])
@given(
    status_count=st.integers(min_value=3, max_value=12),
)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_concurrent_job_event_updates_do_not_deadlock_for_backends(
    backend_name: str,
    tmp_path: Path,
    status_count: int,
) -> None:
    _, store = make_backend(backend_name, tmp_path)
    try:
        session = store.create_session(name="concurrent", dataset=dataset_for(2, 2, 2))
        job = store.create_job(
            session_id=session.id,
            dataset_version=session.dataset_version,
            method_id="band_power_summary",
            params={},
        )

        def append_event(index: int) -> str:
            status = "running" if index % 2 == 0 else "completed"
            status_result = store.append_job_event(
                job.id,
                status=status,
                result={"index": index},
            )
            return status_result.status

        with ThreadPoolExecutor(max_workers=min(8, status_count)) as executor:
            futures = [executor.submit(append_event, index) for index in range(status_count)]
            for future in as_completed(futures):
                assert future.result() in {"running", "completed"}

        final_job = store.get_job(job.id)
        assert final_job is not None
        assert len(final_job.events) >= status_count + 1
        assert final_job.events[0]["status"] == "queued"
    finally:
        _close_backend(store)


@pytest.mark.parametrize("backend_name", ["sqlite", "postgres"])
def test_store_migrations_apply_cleanly_before_first_use(backend_name: str, tmp_path: Path) -> None:
    source, store = make_backend(backend_name, tmp_path)
    try:
        with store._connect() as connection:  # type: ignore[attr-defined]
            cursor = connection.cursor()
            if backend_name == "sqlite":
                rows = {
                    row["name"]
                    for row in cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?, ?, ?, ?)",  # noqa: E501
                        (
                            "schema_migrations",
                            "sessions",
                            "datasets",
                            "jobs",
                            "job_results",
                            "job_events",
                        ),
                    ).fetchall()
                }
                assert rows == {
                    "schema_migrations",
                    "sessions",
                    "datasets",
                    "jobs",
                    "job_results",
                    "job_events",
                }
            else:
                cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name IN (
                          'schema_migrations', 'sessions', 'datasets',
                          'jobs', 'job_results', 'job_events'
                      )
                    """
                )
                rows = {row["table_name"] for row in cursor.fetchall()}
                assert rows == {
                    "schema_migrations",
                    "sessions",
                    "datasets",
                    "jobs",
                    "job_results",
                    "job_events",
                }
    finally:
        _close_backend(store)

        if backend_name == "sqlite" and isinstance(source, Path) and source.exists():
            source.unlink()
