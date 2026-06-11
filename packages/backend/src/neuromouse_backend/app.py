from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from neuromouse_backend.storage import BackendStore, JobRecord, SessionRecord, SQLiteBackendStore
from neuromouse_contract import DatasetValidationError, validate_dataset
from neuromouse_sdk import Method, build_params
from neuromouse_sdk.examples.band_power_summary import band_power_summary

ROOT = Path(__file__).resolve().parents[4]
DEMO_DATASET_PATH = ROOT / "datasets" / "golden" / "data.json"
MEA_DEMO_DATASET_PATH = ROOT / "datasets" / "golden" / "mea_synthetic.json"


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
    required_inputs: list[str]
    params_schema: dict[str, Any]
    output_spec: OutputSpecResponse


class OutputFieldResponse(BaseModel):
    path: str
    label: str
    description: str
    unit: str | None = None


class PanelSpecResponse(BaseModel):
    id: str
    title: str
    kind: str
    field: str


class OutputSpecResponse(BaseModel):
    fields: list[OutputFieldResponse]
    panel: PanelSpecResponse | None = None


class JobResultResponse(BaseModel):
    output: dict[str, Any]
    output_spec: OutputSpecResponse | None = None
    panel: PanelSpecResponse | None = None


class DemoSeedResponse(BaseModel):
    session_id: str
    dataset_id: str
    dataset_version: int
    channel_count: int


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
    result: JobResultResponse | None = None
    error: str | None = None
    created_at: str
    updated_at: str


UNPROCESSABLE_ENTITY = 422


class MethodLookupError(ValueError):
    """Raised when a method is not present in the backend catalog."""


class MethodExecutionError(ValueError):
    """Raised when a registered method cannot run against the supplied dataset."""


@dataclass(frozen=True)
class MethodCatalog:
    methods: dict[str, Method[Any]]

    def lookup(self, method_id: str) -> Method[Any]:
        try:
            return self.methods[_normalize_method_id(method_id)]
        except KeyError as exc:
            raise MethodLookupError(f"unknown method: {method_id}") from exc

    def run(
        self,
        method_id: str,
        dataset: dict[str, Any],
        *,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        method = self.lookup(method_id)
        try:
            dataset_model = validate_dataset(dataset)
            typed_params = build_params(method.params_type, params)
            _require_declared_paths(dataset_model, method.required_inputs, owner=method.name)
            raw = method.compute(dataset_model, typed_params)
            result: dict[str, Any] = dict(raw)
            _require_declared_paths(
                result,
                [field.path for field in method.output.fields],
                owner=method.name,
            )
            return result
        except (DatasetValidationError, TypeError, ValueError) as exc:
            raise MethodExecutionError(f"method {method.name!r} failed: {exc}") from exc


def _load_mea_method(name: str) -> Method[Any]:
    module_name = f"_neuromouse_method_{name}"
    if module_name not in sys.modules:
        path = ROOT / "methods" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"MEA method not found at {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    return cast("Method[Any]", sys.modules[module_name].method)


def create_default_method_catalog() -> MethodCatalog:
    methods: dict[str, Method[Any]] = {}
    for method in (band_power_summary,):
        methods[_normalize_method_id(method.name)] = method
    for mea_name in ("spike_detect", "network_burst", "electrode_connectivity"):
        mea_method = _load_mea_method(mea_name)
        methods[_normalize_method_id(mea_method.name)] = mea_method
    return MethodCatalog(methods=methods)


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

    @app.post("/demo/seed", response_model=DemoSeedResponse, status_code=status.HTTP_201_CREATED)
    async def seed_demo() -> DemoSeedResponse:
        try:
            payload = json.loads(DEMO_DATASET_PATH.read_text(encoding="utf-8"))
            dataset = validate_dataset(payload).model_dump(mode="json")
        except (OSError, json.JSONDecodeError, DatasetValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Demo dataset could not be loaded: {exc}",
            ) from exc

        session = backend_store.create_session(name="Golden demo dataset", dataset=dataset)
        return DemoSeedResponse(
            session_id=session.id,
            dataset_id=session.dataset_id,
            dataset_version=session.dataset_version,
            channel_count=len(session.dataset["meta"]["channels"]),
        )

    @app.post(
        "/demo/seed-mea",
        response_model=DemoSeedResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def seed_demo_mea() -> DemoSeedResponse:
        try:
            payload = json.loads(MEA_DEMO_DATASET_PATH.read_text(encoding="utf-8"))
            dataset = validate_dataset(payload).model_dump(mode="json")
        except (OSError, json.JSONDecodeError, DatasetValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"MEA demo dataset could not be loaded: {exc}",
            ) from exc

        session = backend_store.create_session(
            name="MEA golden demo (1024-ch synthetic)", dataset=dataset
        )
        return DemoSeedResponse(
            session_id=session.id,
            dataset_id=session.dataset_id,
            dataset_version=session.dataset_version,
            channel_count=len(session.dataset["meta"]["channels"]),
        )

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
            methods.lookup(request.method_id)
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
            result = jsonable_encoder(
                methods.run(request.method_id, session.dataset, params=request.params)
            )
        except MethodExecutionError as exc:
            job = backend_store.append_job_event(job.id, status="failed", error=str(exc))
        except Exception as exc:  # pragma: no cover - defensive boundary for future methods
            job = backend_store.append_job_event(job.id, status="failed", error=str(exc))
        else:
            job = backend_store.append_job_event(job.id, status="completed", result=result)
        return _job_response(job, methods=methods)

    @app.get("/jobs/{job_id}", response_model=JobResponse)
    async def get_job(job_id: str) -> JobResponse:
        job = backend_store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        return _job_response(job, methods=methods)

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


def _job_response(job: JobRecord, *, methods: MethodCatalog) -> JobResponse:
    return JobResponse(
        id=job.id,
        session_id=job.session_id,
        dataset_version=job.dataset_version,
        method_id=job.method_id,
        params=job.params,
        status=cast(Literal["queued", "running", "completed", "failed"], job.status),
        result=_job_result_response(job, methods=methods),
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
    return MethodResponse(
        id=method.name,
        name=name,
        description="; ".join(fields),
        required_inputs=list(method.required_inputs),
        params_schema=_params_schema(method.params_type),
        output_spec=_output_spec_response(method),
    )


def _job_result_response(job: JobRecord, *, methods: MethodCatalog) -> JobResultResponse | None:
    if job.result is None:
        return None
    try:
        method = methods.lookup(job.method_id)
    except MethodLookupError:
        return JobResultResponse(output=job.result)

    output_spec = _output_spec_response(method)
    return JobResultResponse(
        output=job.result,
        output_spec=output_spec,
        panel=output_spec.panel,
    )


def _output_spec_response(method: Method[Any]) -> OutputSpecResponse:
    return OutputSpecResponse(
        fields=[
            OutputFieldResponse(
                path=field.path,
                label=_label_from_path(field.path),
                description=field.description,
                unit=field.unit,
            )
            for field in method.output.fields
        ],
        panel=PanelSpecResponse(
            id=method.output.panel.id,
            title=method.output.panel.title,
            kind=method.output.panel.kind,
            field=method.output.panel.field,
        )
        if method.output.panel is not None
        else None,
    )


def _params_schema(params_type: type[Any]) -> dict[str, Any]:
    try:
        schema = TypeAdapter(params_type).json_schema()
    except Exception:  # pragma: no cover - fallback for future non-schema params classes
        name = getattr(params_type, "__name__", "Params")
        return {"title": name, "type": "object", "properties": {}}
    return dict(schema)


def _label_from_path(path: str) -> str:
    return path.rsplit(".", maxsplit=1)[-1].replace("_", " ").title()


def _normalize_method_id(method_id: str) -> str:
    return method_id.strip()


def _require_declared_paths(value: Any, paths: list[str] | tuple[str, ...], *, owner: str) -> None:
    for path in paths:
        if not _has_field_path(value, path):
            raise MethodExecutionError(f"method {owner!r} missing declared field {path!r}")


def _has_field_path(value: Any, path: str) -> bool:
    current = value
    for part in path.split("."):
        if isinstance(current, BaseModel):
            if not hasattr(current, part):
                return False
            current = getattr(current, part)
        elif isinstance(current, dict):
            if part not in current:
                return False
            current = current[part]
        else:
            return False
    return True


app = create_app()
