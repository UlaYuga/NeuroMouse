from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from neuromouse_backend.storage import BackendStore, JobRecord, SessionRecord, SQLiteBackendStore
from neuromouse_contract import DatasetValidationError, validate_dataset
from neuromouse_core.method_registry import MethodExecutionError, MethodLookupError, MethodRegistry
from neuromouse_sdk import Method
from neuromouse_sdk.examples.band_power_summary import band_power_summary


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    dataset: dict[str, Any]


class SessionSummary(BaseModel):
    id: str
    name: str | None
    channel_count: int
    dataset_version: int
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
    params: dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    id: str
    session_id: str
    dataset_version: int
    method_id: str
    params: dict[str, Any]
    status: Literal["queued", "running", "completed", "failed"]
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    updated_at: str


UNPROCESSABLE_ENTITY = 422


@dataclass(frozen=True)
class MethodCatalog:
    registry: MethodRegistry
    methods: dict[str, Method[Any]]


def create_default_method_catalog() -> MethodCatalog:
    registry = MethodRegistry()
    methods: dict[str, Method[Any]] = {}
    for method in (band_power_summary,):
        registered = registry.register(method)
        methods[registered.name] = registered
    return MethodCatalog(registry=registry, methods=methods)


def create_app(
    store: BackendStore | None = None,
    method_catalog: MethodCatalog | None = None,
) -> FastAPI:
    backend_store = store or SQLiteBackendStore()
    methods = method_catalog or create_default_method_catalog()
    app = FastAPI(
        title="NeuroMouse Backend",
        version="0.0.0",
        description="FastAPI backend for contract-validated NeuroMouse method jobs.",
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
        return [_method_response(method) for method in methods.methods.values()]

    @app.post(
        "/sessions/{session_id}/jobs",
        response_model=JobResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_job(session_id: str, request: JobCreateRequest) -> JobResponse:
        session = backend_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        try:
            methods.registry.lookup(request.method_id)
        except MethodLookupError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Method not found",
            ) from exc

        job = backend_store.create_job(
            session_id=session.id,
            dataset_version=session.dataset_version,
            method_id=request.method_id,
            params=request.params,
        )
        backend_store.append_job_event(job.id, status="running")
        try:
            run = methods.registry.run(request.method_id, session.dataset, params=request.params)
            result = jsonable_encoder(run.result)
        except MethodExecutionError as exc:
            job = backend_store.append_job_event(job.id, status="failed", error=str(exc))
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
        dataset_version=session.dataset_version,
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
        dataset_version=job.dataset_version,
        method_id=job.method_id,
        params=job.params,
        status=job.status,
        result=job.result,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _method_response(method: Method[Any]) -> MethodResponse:
    panel = method.output.panel
    name = panel.title if panel is not None else method.name.replace("_", " ").title()
    fields = []
    for field in method.output.fields:
        if field.description:
            fields.append(f"{field.path}: {field.description}")
        else:
            fields.append(field.path)
    return MethodResponse(id=method.name, name=name, description="; ".join(fields))


app = create_app()
