from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING
from typing import Any, Callable, Iterable, Mapping, Protocol
from uuid import uuid4

if TYPE_CHECKING:
    import psycopg  # pragma: no cover
    from psycopg.rows import dict_row as _DictRow  # type: ignore[unused-import]


def _require_psycopg():
    import importlib

    psycopg = importlib.import_module("psycopg")
    dict_row = importlib.import_module("psycopg.rows").dict_row
    return psycopg, dict_row


_MIGRATIONS_ROOT = Path(__file__).resolve().parents[2] / "migrations"
_KNOWN_POSTGRES_PREFIXES = ("postgres://", "postgresql://")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SessionRecord:
    id: str
    dataset_id: str
    name: str | None
    dataset: dict[str, Any]
    dataset_version: int
    created_at: str


@dataclass
class JobRecord:
    id: str
    session_id: str
    dataset_version: int
    method_id: str
    params: dict[str, Any]
    status: str
    created_at: str
    updated_at: str
    result: dict[str, Any] | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


class BackendStore(Protocol):
    def create_session(self, *, name: str | None, dataset: dict[str, Any]) -> SessionRecord: ...

    def list_sessions(self) -> Iterable[SessionRecord]: ...

    def get_session(self, session_id: str) -> SessionRecord | None: ...

    def create_job(
        self,
        *,
        session_id: str,
        dataset_version: int,
        method_id: str,
        params: dict[str, Any] | None = None,
    ) -> JobRecord: ...

    def get_job(self, job_id: str) -> JobRecord | None: ...

    def append_job_event(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> JobRecord: ...


class InMemoryBackendStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._jobs: dict[str, JobRecord] = {}

    def create_session(self, *, name: str | None, dataset: dict[str, Any]) -> SessionRecord:
        session = SessionRecord(
            id=str(uuid4()),
            dataset_id=str(uuid4()),
            name=name,
            dataset=dataset,
            dataset_version=1,
            created_at=utc_now(),
        )
        self._sessions[session.id] = session
        return session

    def list_sessions(self) -> Iterable[SessionRecord]:
        return self._sessions.values()

    def get_session(self, session_id: str) -> SessionRecord | None:
        return self._sessions.get(session_id)

    def create_job(
        self,
        *,
        session_id: str,
        dataset_version: int,
        method_id: str,
        params: dict[str, Any] | None = None,
    ) -> JobRecord:
        timestamp = utc_now()
        job = JobRecord(
            id=str(uuid4()),
            session_id=session_id,
            dataset_version=dataset_version,
            method_id=method_id,
            params=dict(params or {}),
            status="queued",
            created_at=timestamp,
            updated_at=timestamp,
        )
        job.events.append(self._event(job, status="queued"))
        self._jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def append_job_event(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> JobRecord:
        job = self._jobs[job_id]
        job.status = status
        job.updated_at = utc_now()
        job.result = result
        job.error = error
        job.events.append(self._event(job, status=status, result=result, error=error))
        return job

    @staticmethod
    def _event(
        job: JobRecord,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "job_id": job.id,
            "session_id": job.session_id,
            "dataset_version": job.dataset_version,
            "method_id": job.method_id,
            "status": status,
            "timestamp": utc_now(),
        }
        if result is not None:
            event["result"] = result
        if error is not None:
            event["error"] = error
        return event


def _resolve_backend_factory(database_url: str | None = None) -> str:
    selected = database_url or os.environ.get("DATABASE_URL")
    if selected is None:
        return "sqlite"
    if selected.startswith(_KNOWN_POSTGRES_PREFIXES):
        return "postgres"
    return "sqlite"


def create_backend_store(
    *,
    database_url: str | None = None,
    sqlite_path: str | os.PathLike[str] | None = None,
) -> BackendStore:
    backend = _resolve_backend_factory(database_url)
    if backend == "postgres":
        return PostgreSQLBackendStore(database_url=database_url)
    return SQLiteBackendStore(path=sqlite_path)


class SQLiteBackendStore:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        raw_path = path or os.environ.get("NEUROMOUSE_BACKEND_DB") or "neuromouse_backend.sqlite3"
        self._path = Path(raw_path)
        self._connection: sqlite3.Connection | None = None
        self._lock = RLock()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def create_session(self, *, name: str | None, dataset: dict[str, Any]) -> SessionRecord:
        session_id = str(uuid4())
        created_at = utc_now()
        dataset_id = str(uuid4())
        with self._lock:
            connection = self._connect()
            with connection:
                connection.execute(
                    "INSERT INTO sessions (id, name, created_at) VALUES (?, ?, ?)",
                    (session_id, name, created_at),
                )
                connection.execute(
                    """
                    INSERT INTO datasets (id, session_id, version, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (dataset_id, session_id, 1, _dump_json(dataset), created_at),
                )
            session = self.get_session(session_id)
            if session is None:  # pragma: no cover - sqlite transaction invariant
                raise RuntimeError("created session could not be reloaded")
            return session

    def list_sessions(self) -> Iterable[SessionRecord]:
        with self._lock:
            rows = self._connect().execute(
                """
                SELECT
                    s.id,
                    s.name,
                    s.created_at,
                    d.id AS dataset_id,
                    d.version AS dataset_version,
                    d.payload_json AS dataset_json
                FROM sessions AS s
                JOIN datasets AS d ON d.session_id = s.id
                WHERE d.version = (
                    SELECT MAX(version) FROM datasets WHERE session_id = s.id
                )
                ORDER BY s.created_at, s.id
                """
            )
            return [_session_from_row(row) for row in rows]

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            row = self._connect().execute(
                """
                SELECT
                    s.id,
                    s.name,
                    s.created_at,
                    d.id AS dataset_id,
                    d.version AS dataset_version,
                    d.payload_json AS dataset_json
                FROM sessions AS s
                JOIN datasets AS d ON d.session_id = s.id
                WHERE s.id = ?
                ORDER BY d.version DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            return _session_from_row(row) if row is not None else None

    def create_job(
        self,
        *,
        session_id: str,
        dataset_version: int,
        method_id: str,
        params: dict[str, Any] | None = None,
    ) -> JobRecord:
        if self.get_session(session_id) is None:
            raise KeyError(f"unknown session: {session_id}")

        timestamp = utc_now()
        job_id = str(uuid4())
        params_json = _dump_json(params or {})
        with self._lock:
            connection = self._connect()
            with connection:
                connection.execute(
                    """
                    INSERT INTO jobs (
                        id,
                        session_id,
                        dataset_version,
                        method_id,
                        params_json,
                        status,
                        error,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        session_id,
                        dataset_version,
                        method_id,
                        params_json,
                        "queued",
                        None,
                        timestamp,
                        timestamp,
                    ),
                )
                self._insert_job_event(
                    connection,
                    {
                        "job_id": job_id,
                        "session_id": session_id,
                        "dataset_version": dataset_version,
                        "method_id": method_id,
                        "status": "queued",
                        "timestamp": timestamp,
                    },
                )
            job = self.get_job(job_id)
            if job is None:  # pragma: no cover - sqlite transaction invariant
                raise RuntimeError("created job could not be reloaded")
            return job

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            connection = self._connect()
            row = connection.execute(
                """
                SELECT
                    j.id,
                    j.session_id,
                    j.dataset_version,
                    j.method_id,
                    j.params_json,
                    j.status,
                    j.error,
                    j.created_at,
                    j.updated_at,
                    r.payload_json AS result_json
                FROM jobs AS j
                LEFT JOIN job_results AS r ON r.job_id = j.id
                WHERE j.id = ?
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            events = [
                _load_json(event_row["payload_json"])
                for event_row in connection.execute(
                    """
                    SELECT payload_json
                    FROM job_events
                    WHERE job_id = ?
                    ORDER BY sequence
                    """,
                    (job_id,),
                )
            ]
            return _job_from_row(row, events=events)

    def append_job_event(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> JobRecord:
        with self._lock:
            existing = self.get_job(job_id)
            if existing is None:
                raise KeyError(f"unknown job: {job_id}")

            timestamp = utc_now()
            connection = self._connect()
            with connection:
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = ?, error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, error, timestamp, job_id),
                )
                if result is not None:
                    connection.execute(
                        """
                        INSERT INTO job_results (job_id, payload_json, created_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(job_id) DO UPDATE SET
                            payload_json = excluded.payload_json,
                            created_at = excluded.created_at
                        """,
                        (job_id, _dump_json(result), timestamp),
                    )
                elif status == "failed":
                    connection.execute("DELETE FROM job_results WHERE job_id = ?", (job_id,))

                event: dict[str, Any] = {
                    "job_id": existing.id,
                    "session_id": existing.session_id,
                    "dataset_version": existing.dataset_version,
                    "method_id": existing.method_id,
                    "status": status,
                    "timestamp": timestamp,
                }
                if result is not None:
                    event["result"] = result
                if error is not None:
                    event["error"] = error
                self._insert_job_event(connection, event)

            updated = self.get_job(job_id)
            if updated is None:  # pragma: no cover - sqlite transaction invariant
                raise RuntimeError("updated job could not be reloaded")
            return updated

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            if str(self._path) != ":memory:":
                self._path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(str(self._path), check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._migrate(self._connection)
        return self._connection

    def _migrate(self, connection: sqlite3.Connection) -> None:
        with connection:
            _ensure_schema_migrations(connection.execute)
            existing = {
                name for name in (row["name"] for row in connection.execute("SELECT name FROM schema_migrations").fetchall())
            }
            for migration in _migration_paths("sqlite"):
                if migration.name in existing:
                    continue
                for statement in _migration_statements(migration):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                    (migration.name, utc_now()),
                )

    def _insert_job_event(self, connection: sqlite3.Connection, event: dict[str, Any]) -> None:
        next_sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM job_events WHERE job_id = ?",
            (event["job_id"],),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO job_events (job_id, sequence, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (event["job_id"], next_sequence, _dump_json(event), event["timestamp"]),
        )


class PostgreSQLBackendStore:
    def __init__(self, database_url: str | None = None) -> None:
        if not self._is_postgres_url(database_url or os.environ.get("DATABASE_URL", "")):
            raise ValueError("PostgreSQL backend requires a postgres:// or postgresql:// DATABASE_URL")

        try:
            self._psycopg, self._dict_row = _require_psycopg()
        except ModuleNotFoundError as exc:  # pragma: no cover - runtime dependency guard
            raise RuntimeError("psycopg is required for PostgreSQLBackendStore") from exc

        self._database_url = (
            database_url
            or os.environ.get("DATABASE_URL")
            or ""
        ).strip()

    @staticmethod
    def _is_postgres_url(value: str) -> bool:
        return value.startswith(_KNOWN_POSTGRES_PREFIXES)

    def close(self) -> None:
        return None

    def create_session(self, *, name: str | None, dataset: dict[str, Any]) -> SessionRecord:
        session_id = str(uuid4())
        created_at = utc_now()
        dataset_id = str(uuid4())
        with self._connect() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO sessions (id, name, created_at) VALUES (%s, %s, %s)",
                        (session_id, name, created_at),
                    )
                    cursor.execute(
                        """
                        INSERT INTO datasets (id, session_id, version, payload_json, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (dataset_id, session_id, 1, _dump_json(dataset), created_at),
                    )
        session = self.get_session(session_id)
        if session is None:  # pragma: no cover - postgres transaction invariant
            raise RuntimeError("created session could not be reloaded")
        return session

    def list_sessions(self) -> Iterable[SessionRecord]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        s.id,
                        s.name,
                        s.created_at,
                        d.id AS dataset_id,
                        d.version AS dataset_version,
                        d.payload_json AS dataset_json
                    FROM sessions AS s
                    JOIN datasets AS d ON d.session_id = s.id
                    WHERE d.version = (
                        SELECT MAX(version) FROM datasets WHERE session_id = s.id
                    )
                    ORDER BY s.created_at, s.id
                    """
                )
                return [_session_from_row(row) for row in cursor.fetchall()]

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        s.id,
                        s.name,
                        s.created_at,
                        d.id AS dataset_id,
                        d.version AS dataset_version,
                        d.payload_json AS dataset_json
                    FROM sessions AS s
                    JOIN datasets AS d ON d.session_id = s.id
                    WHERE s.id = %s
                    ORDER BY d.version DESC
                    LIMIT 1
                    """,
                    (session_id,),
                )
                row = cursor.fetchone()
                return _session_from_row(row) if row is not None else None

    def create_job(
        self,
        *,
        session_id: str,
        dataset_version: int,
        method_id: str,
        params: dict[str, Any] | None = None,
    ) -> JobRecord:
        if self.get_session(session_id) is None:
            raise KeyError(f"unknown session: {session_id}")

        timestamp = utc_now()
        job_id = str(uuid4())
        params_json = _dump_json(params or {})
        with self._connect() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO jobs (
                            id,
                            session_id,
                            dataset_version,
                            method_id,
                            params_json,
                            status,
                            error,
                            created_at,
                            updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            job_id,
                            session_id,
                            dataset_version,
                            method_id,
                            params_json,
                            "queued",
                            None,
                            timestamp,
                            timestamp,
                        ),
                    )
                    cursor.execute(
                        """
                        INSERT INTO job_events (job_id, sequence, payload_json, created_at)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (
                            job_id,
                            self._next_event_sequence(cursor, job_id),
                            _dump_json(
                                {
                                    "job_id": job_id,
                                    "session_id": session_id,
                                    "dataset_version": dataset_version,
                                    "method_id": method_id,
                                    "status": "queued",
                                    "timestamp": timestamp,
                                }
                            ),
                            timestamp,
                        ),
                    )
        job = self.get_job(job_id)
        if job is None:  # pragma: no cover - postgres transaction invariant
            raise RuntimeError("created job could not be reloaded")
        return job

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        j.id,
                        j.session_id,
                        j.dataset_version,
                        j.method_id,
                        j.params_json,
                        j.status,
                        j.error,
                        j.created_at,
                        j.updated_at,
                        r.payload_json AS result_json
                    FROM jobs AS j
                    LEFT JOIN job_results AS r ON r.job_id = j.id
                    WHERE j.id = %s
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                cursor.execute(
                    """
                    SELECT payload_json
                    FROM job_events
                    WHERE job_id = %s
                    ORDER BY sequence
                    """,
                    (job_id,),
                )
                events = [_load_json(event_row["payload_json"]) for event_row in cursor.fetchall()]
                return _job_from_row(row, events=events)

    def append_job_event(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> JobRecord:
        existing = self.get_job(job_id)
        if existing is None:
            raise KeyError(f"unknown job: {job_id}")

        timestamp = utc_now()
        with self._connect() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE jobs
                        SET status = %s, error = %s, updated_at = %s
                        WHERE id = %s
                        """,
                        (status, error, timestamp, job_id),
                    )
                    if result is not None:
                        cursor.execute(
                            """
                            INSERT INTO job_results (job_id, payload_json, created_at)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (job_id) DO UPDATE SET
                                payload_json = EXCLUDED.payload_json,
                                created_at = EXCLUDED.created_at
                            """,
                            (job_id, _dump_json(result), timestamp),
                        )
                    elif status == "failed":
                        cursor.execute("DELETE FROM job_results WHERE job_id = %s", (job_id,))

                    event = {
                        "job_id": existing.id,
                        "session_id": existing.session_id,
                        "dataset_version": existing.dataset_version,
                        "method_id": existing.method_id,
                        "status": status,
                        "timestamp": timestamp,
                    }
                    if result is not None:
                        event["result"] = result
                    if error is not None:
                        event["error"] = error

                    cursor.execute(
                        """
                        INSERT INTO job_events (job_id, sequence, payload_json, created_at)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (
                            existing.id,
                            self._next_event_sequence(cursor, existing.id),
                            _dump_json(event),
                            timestamp,
                        ),
                    )
        updated = self.get_job(job_id)
        if updated is None:  # pragma: no cover - postgres transaction invariant
            raise RuntimeError("updated job could not be reloaded")
        return updated

    def _connect(self):
        connection = self._psycopg.connect(self._database_url, row_factory=self._dict_row)
        _ensure_schema_migrations(connection.execute)
        existing = {
            name for name in (row["name"] for row in connection.execute("SELECT name FROM schema_migrations").fetchall())
        }
        for migration in _migration_paths("postgres"):
            if migration.name in existing:
                continue
            for statement in _migration_statements(migration):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (%s, %s)",
                (migration.name, utc_now()),
            )
        connection.commit()
        return connection

    def _next_event_sequence(self, cursor: Any, job_id: str) -> int:
        cursor.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM job_events WHERE job_id = %s",
            (job_id,),
        )
        value = cursor.fetchone()
        if value is None:
            return 1
        if isinstance(value, Mapping):
            for key in ("coalesce", "next_sequence"):
                if key in value:
                    return int(value[key])
            return int(next(iter(value.values())))
        return int(value[0])


def _ensure_schema_migrations(
    execute: Callable[[str, tuple[Any, ...] | None], Any],
) -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _migration_paths(backend: str) -> list[Path]:
    return sorted((_MIGRATIONS_ROOT / backend).glob("*.sql"), key=lambda path: path.name)


def _migration_statements(path: Path) -> Iterable[str]:
    for statement in path.read_text(encoding="utf-8").split(";"):
        stripped = statement.strip()
        if stripped:
            yield stripped


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _load_json(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def _session_from_row(row: Mapping[str, Any]) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        dataset_id=row["dataset_id"],
        name=row["name"],
        dataset=_load_json(row["dataset_json"]),
        dataset_version=row["dataset_version"],
        created_at=row["created_at"],
    )


def _job_from_row(row: Mapping[str, Any], *, events: list[dict[str, Any]]) -> JobRecord:
    return JobRecord(
        id=row["id"],
        session_id=row["session_id"],
        dataset_version=row["dataset_version"],
        method_id=row["method_id"],
        params=_load_json(row["params_json"]),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        result=_load_json(row["result_json"]),
        error=row["error"],
        events=events,
    )
