from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from neuromouse_backend.storage import BackendStore, InMemoryBackendStore, JobRecord, SessionRecord
from neuromouse_contract import DatasetValidationError, validate_dataset


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    dataset: dict[str, Any]


class SessionSummary(BaseModel):
    id: str
    name: str | None
    channel_count: int
    created_at: str


class SessionResponse(SessionSummary):
    dataset: dict[str, Any]


class MethodResponse(BaseModel):
    id: str
    name: str
    description: str


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method_id: str = Field(min_length=1)


class JobResponse(BaseModel):
    id: str
    session_id: str
    method_id: str
    status: Literal["queued", "running", "completed", "failed"]
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    updated_at: str


MethodRunner = Callable[[SessionRecord], dict[str, Any]]
UNPROCESSABLE_ENTITY = 422


def _summary_method(session: SessionRecord) -> dict[str, Any]:
    return {
        "channel_count": len(session.dataset["meta"]["channels"]),
        "method_id": "summary",
    }


METHODS: dict[str, tuple[MethodResponse, MethodRunner]] = {
    "summary": (
        MethodResponse(
            id="summary",
            name="Dataset summary",
            description="Returns basic contract-derived dataset metadata.",
        ),
        _summary_method,
    )
}


def create_app(store: BackendStore | None = None) -> FastAPI:
    backend_store = store or InMemoryBackendStore()
    app = FastAPI(
        title="NeuroMouse Backend",
        version="0.0.0",
        description="FastAPI skeleton for contract-validated NeuroMouse backend workflows.",
    )

    @app.post(
        "/sessions",
        response_model=SessionResponse,
        status_code=status.HTTP_201_CREATED,
        responses={
            UNPROCESSABLE_ENTITY: {"description": "Dataset contract or request validation error"}
        },
    )
    async def create_session(request: SessionCreateRequest) -> SessionResponse:
        try:
            dataset = validate_dataset(request.dataset).model_dump(mode="json")
        except DatasetValidationError as exc:
            raise HTTPException(
                status_code=UNPROCESSABLE_ENTITY,
                detail=[
                    {
                        "loc": ["body", "dataset"],
                        "msg": str(exc),
                        "type": "value_error.dataset_contract",
                    }
                ],
            ) from exc

        session = backend_store.create_session(name=request.name, dataset=dataset)
        return _session_response(session)

    @app.get("/sessions", response_model=list[SessionSummary])
    async def list_sessions() -> list[SessionSummary]:
        return [_session_summary(session) for session in backend_store.list_sessions()]

    @app.get("/sessions/{session_id}", response_model=SessionResponse)
    async def get_session(session_id: str) -> SessionResponse:
        session = backend_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        return _session_response(session)

    @app.get("/methods", response_model=list[MethodResponse])
    async def list_methods() -> list[MethodResponse]:
        return [method for method, _runner in METHODS.values()]

    @app.post(
        "/sessions/{session_id}/jobs",
        response_model=JobResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_job(session_id: str, request: JobCreateRequest) -> JobResponse:
        session = backend_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        method = METHODS.get(request.method_id)
        if method is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Method not found")

        _method_response, runner = method
        job = backend_store.create_job(session_id=session.id, method_id=request.method_id)
        backend_store.append_job_event(job.id, status="running")
        try:
            result = runner(session)
        except Exception as exc:  # pragma: no cover - defensive boundary for future methods
            job = backend_store.append_job_event(job.id, status="failed", error=str(exc))
        else:
            job = backend_store.append_job_event(job.id, status="completed", result=result)
        return _job_response(job)

    @app.get("/jobs/{job_id}", response_model=JobResponse)
    async def get_job(job_id: str) -> JobResponse:
        job = backend_store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        return _job_response(job)

    @app.get(
        "/ws/jobs/{job_id}",
        status_code=status.HTTP_426_UPGRADE_REQUIRED,
        responses={426: {"description": "Use a WebSocket client for this endpoint"}},
        tags=["websocket"],
    )
    async def websocket_job_http_fallback(job_id: str) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_426_UPGRADE_REQUIRED,
            content={"detail": f"Use WebSocket /ws/jobs/{job_id} for job progress"},
        )

    @app.websocket("/ws/jobs/{job_id}")
    async def job_progress(websocket: WebSocket, job_id: str) -> None:
        await websocket.accept()
        job = backend_store.get_job(job_id)
        if job is None:
            await websocket.send_json({"status": "not_found", "error": "Job not found"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        for event in job.events:
            await websocket.send_json(event)
        await websocket.close()

    @app.get(
        "/ws/live",
        status_code=status.HTTP_426_UPGRADE_REQUIRED,
        responses={426: {"description": "Use a WebSocket client for this endpoint"}},
        tags=["websocket"],
    )
    async def websocket_live_http_fallback() -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_426_UPGRADE_REQUIRED,
            content={"detail": "Use WebSocket /ws/live for live ingestion echo"},
        )

    @app.websocket("/ws/live")
    async def live_echo(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                payload = await websocket.receive_json()
                await websocket.send_json(payload)
        except WebSocketDisconnect:
            return

    return app


def _session_summary(session: SessionRecord) -> SessionSummary:
    return SessionSummary(
        id=session.id,
        name=session.name,
        channel_count=len(session.dataset["meta"]["channels"]),
        created_at=session.created_at,
    )


def _session_response(session: SessionRecord) -> SessionResponse:
    return SessionResponse(
        **_session_summary(session).model_dump(),
        dataset=session.dataset,
    )


def _job_response(job: JobRecord) -> JobResponse:
    return JobResponse(
        id=job.id,
        session_id=job.session_id,
        method_id=job.method_id,
        status=job.status,
        result=job.result,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


app = create_app()
