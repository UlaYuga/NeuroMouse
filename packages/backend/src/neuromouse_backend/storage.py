from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SessionRecord:
    id: str
    name: str | None
    dataset: dict[str, Any]
    created_at: str


@dataclass
class JobRecord:
    id: str
    session_id: str
    method_id: str
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

    def create_job(self, *, session_id: str, method_id: str) -> JobRecord: ...

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
            name=name,
            dataset=dataset,
            created_at=utc_now(),
        )
        self._sessions[session.id] = session
        return session

    def list_sessions(self) -> Iterable[SessionRecord]:
        return self._sessions.values()

    def get_session(self, session_id: str) -> SessionRecord | None:
        return self._sessions.get(session_id)

    def create_job(self, *, session_id: str, method_id: str) -> JobRecord:
        timestamp = utc_now()
        job = JobRecord(
            id=str(uuid4()),
            session_id=session_id,
            method_id=method_id,
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
            "method_id": job.method_id,
            "status": status,
            "timestamp": utc_now(),
        }
        if result is not None:
            event["result"] = result
        if error is not None:
            event["error"] = error
        return event
