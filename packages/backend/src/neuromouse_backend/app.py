from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from neuromouse_backend.auth import AuthError, AuthService, make_session_resolver
from neuromouse_backend.security import (
    AuthenticatedUser,
    EnvSessionTokenResolver,
    SessionTokenResolver,
    _parse_session_token_from_request,
    install_security_middlewares,
    user_from_request,
    user_from_websocket,
)
from neuromouse_backend.storage import (
    BackendStore,
    JobRecord,
    SessionRecord,
    create_backend_store,
)
from neuromouse_contract import DatasetValidationError, validate_dataset
from neuromouse_sandbox import MethodRef, SandboxError, SandboxLimits, run_in_sandbox
from neuromouse_sdk import Method, build_params
from neuromouse_sdk.examples.band_power_summary import band_power_summary

ROOT = Path(__file__).resolve().parents[4]
DEMO_DATASET_PATH = ROOT / "datasets" / "golden" / "data.json"
MEA_DEMO_DATASET_PATH = ROOT / "datasets" / "golden" / "mea_synthetic.json"
DEMO_OWNER_ID = "anonymous"
DEMO_METHODS = ("spike_detect", "network_burst", "electrode_connectivity")


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


class AuthCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1)
    password: str = Field(min_length=1)


UNPROCESSABLE_ENTITY = 422


class MethodLookupError(ValueError):
    """Raised when a method is not present in the backend catalog."""


class MethodExecutionError(ValueError):
    """Raised when a registered method cannot run against the supplied dataset."""


@dataclass(frozen=True)
class _QueuedJob:
    job_id: str
    session_id: str
    owner_id: str
    method_id: str
    params: dict[str, Any]


@dataclass(frozen=True)
class MethodCatalog:
    methods: dict[str, Method[Any]]
    # Process-isolation locators. When a method has a ``MethodRef`` its
    # ``compute`` runs in a sandboxed subprocess (the P1-4 boundary); methods
    # without one fall back to the legacy in-process path for compatibility.
    refs: dict[str, MethodRef] = dataclass_field(default_factory=dict)
    limits: SandboxLimits = dataclass_field(default_factory=SandboxLimits)

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
        ref = self.refs.get(_normalize_method_id(method_id))
        if ref is None:
            return self._run_in_process(method, dataset, params)
        return self._run_sandboxed(method, ref, dataset, params)

    def _run_sandboxed(
        self,
        method: Method[Any],
        ref: MethodRef,
        dataset: dict[str, Any],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        # The dataset is contract-validated in-process (trusted) so the untrusted
        # child only ever sees well-formed input; ``compute`` (and the untrusted
        # module import + param construction it implies) runs across the boundary.
        try:
            dataset_payload = validate_dataset(dataset).model_dump(mode="json")
        except DatasetValidationError as exc:
            raise MethodExecutionError(f"method {method.name!r} failed: {exc}") from exc
        try:
            return run_in_sandbox(
                ref,
                dataset_payload,
                dict(params),
                limits=self.limits,
                required_inputs=tuple(method.required_inputs),
                output_fields=tuple(field_.path for field_ in method.output.fields),
            )
        except SandboxError as exc:
            raise MethodExecutionError(f"method {method.name!r} failed: {exc}") from exc

    def _run_in_process(
        self,
        method: Method[Any],
        dataset: dict[str, Any],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            dataset_model = validate_dataset(dataset)
            typed_params = build_params(method.params_type, params)
            _require_declared_paths(dataset_model, method.required_inputs, owner=method.name)
            raw = method.compute(dataset_model, typed_params)
            result: dict[str, Any] = dict(raw)
            _require_declared_paths(
                result,
                [field_.path for field_ in method.output.fields],
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
    refs: dict[str, MethodRef] = {}

    band_id = _normalize_method_id(band_power_summary.name)
    methods[band_id] = band_power_summary
    refs[band_id] = MethodRef(
        kind="module",
        module="neuromouse_sdk.examples.band_power_summary",
        attr="band_power_summary",
    )

    for mea_name in ("spike_detect", "network_burst", "electrode_connectivity"):
        mea_method = _load_mea_method(mea_name)
        method_id = _normalize_method_id(mea_method.name)
        methods[method_id] = mea_method
        refs[method_id] = MethodRef(
            kind="file",
            path=str(ROOT / "methods" / f"{mea_name}.py"),
            attr="method",
        )
    return MethodCatalog(methods=methods, refs=refs)


def create_app(
    store: BackendStore | None = None,
    method_catalog: MethodCatalog | None = None,
    session_token_resolver: SessionTokenResolver | None = None,
) -> FastAPI:
    backend_store = store or create_backend_store()
    methods = method_catalog or create_default_method_catalog()
    app = FastAPI(
        title="NeuroMouse Backend",
        version="0.0.0",
        description="FastAPI backend for contract-validated NeuroMouse method jobs.",
    )
    if session_token_resolver is None:
        _env_resolver = EnvSessionTokenResolver.from_env()
        _auth_resolver = make_session_resolver(backend_store)

        def _combined_resolver(token: str) -> AuthenticatedUser | None:
            return _auth_resolver(token) or _env_resolver.resolve(token)

        session_token_resolver = _combined_resolver
    install_security_middlewares(app, session_token_resolver=session_token_resolver)

    auth_service = AuthService(backend_store)

    @app.post("/auth/register", status_code=status.HTTP_201_CREATED)
    async def auth_register(payload: AuthCredentials) -> dict[str, str]:
        try:
            account = auth_service.register(payload.email, payload.password)
        except AuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": account.id, "email": account.email}

    @app.post("/auth/login")
    async def auth_login(payload: AuthCredentials, response: Response) -> dict[str, str]:
        try:
            token = auth_service.login(payload.email, payload.password)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail="invalid email or password") from exc
        response.set_cookie(
            "neuromouse_session", token, httponly=True, samesite="lax", secure=True
        )
        return {"token": token}

    @app.post("/auth/logout")
    async def auth_logout(request: Request, response: Response) -> dict[str, str]:
        token = _parse_session_token_from_request(request, cookie_name="neuromouse_session")
        auth_service.logout(token)
        response.delete_cookie("neuromouse_session")
        return {"status": "logged out"}

    @app.get("/auth/me")
    async def auth_me(request: Request) -> dict[str, str]:
        user = user_from_request(request)
        account = auth_service.current(user.id)
        if account is None:
            raise HTTPException(status_code=404, detail="user not found")
        return {"id": account.id, "email": account.email}

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/healthz")
    async def health_check_alt() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def readiness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readiness_alt() -> dict[str, str]:
        return {"status": "ok"}

    job_queue: asyncio.Queue[_QueuedJob] = asyncio.Queue()
    watchers: dict[str, set[asyncio.Queue[None]]] = defaultdict(set)
    workers: list[asyncio.Task[None]] = []
    worker_bootstrap = asyncio.Lock()

    def _broadcast_job_update(event: dict[str, Any]) -> None:
        for queue in list(watchers.get(event["job_id"], set())):
            queue.put_nowait(None)

    async def _execute_job(queued_job: _QueuedJob) -> None:
        try:
            session = backend_store.get_session(
                queued_job.session_id,
                owner_id=queued_job.owner_id,
            )
            if session is None:
                failed = backend_store.append_job_event(
                    queued_job.job_id,
                    status="failed",
                    error="Session not found",
                    owner_id=queued_job.owner_id,
                )
                _broadcast_job_update(failed.events[-1])
                return

            running = backend_store.append_job_event(
                queued_job.job_id,
                status="running",
                owner_id=queued_job.owner_id,
            )
            _broadcast_job_update(running.events[-1])

            result = await asyncio.to_thread(
                methods.run,
                queued_job.method_id,
                session.dataset,
                params=queued_job.params,
            )
            completed = backend_store.append_job_event(
                queued_job.job_id,
                status="completed",
                result=jsonable_encoder(result),
                owner_id=queued_job.owner_id,
            )
            _broadcast_job_update(completed.events[-1])
        except MethodExecutionError as exc:
            failed = backend_store.append_job_event(
                queued_job.job_id,
                status="failed",
                error=str(exc),
                owner_id=queued_job.owner_id,
            )
            _broadcast_job_update(failed.events[-1])
        except Exception as exc:  # pragma: no cover - defensive boundary for future methods
            failed = backend_store.append_job_event(
                queued_job.job_id,
                status="failed",
                error=str(exc),
                owner_id=queued_job.owner_id,
            )
            _broadcast_job_update(failed.events[-1])

    async def _job_worker_loop() -> None:
        while True:
            queued_job = await job_queue.get()
            try:
                await _execute_job(queued_job)
            finally:
                job_queue.task_done()

    async def _start_workers() -> None:
        async with worker_bootstrap:
            if workers:
                return
            workers.append(asyncio.create_task(_job_worker_loop()))

    async def _stop_workers() -> None:
        for task in workers:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        workers.clear()
        watchers.clear()

    app.add_event_handler("startup", _start_workers)
    app.add_event_handler("shutdown", _stop_workers)

    @app.post(
        "/sessions",
        response_model=SessionResponse,
        status_code=status.HTTP_201_CREATED,
        responses={
            UNPROCESSABLE_ENTITY: {"description": "Dataset contract or request validation error"}
        },
    )
    async def create_session(
        http_request: Request,
        request: SessionCreateRequest,
    ) -> SessionResponse:
        user = user_from_request(http_request)
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

        session = backend_store.create_session(
            name=request.name,
            dataset=dataset,
            owner_id=user.id,
        )
        return _session_response(session)

    @app.get("/sessions", response_model=list[SessionSummary])
    async def list_sessions(http_request: Request) -> list[SessionSummary]:
        user = user_from_request(http_request)
        return [
            _session_summary(session)
            for session in backend_store.list_sessions(owner_id=user.id)
        ]

    @app.get("/sessions/{session_id}", response_model=SessionResponse)
    async def get_session(http_request: Request, session_id: str) -> SessionResponse:
        user = user_from_request(http_request)
        session = backend_store.get_session(session_id, owner_id=user.id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        return _session_response(session)

    @app.get("/methods", response_model=list[MethodResponse])
    async def list_methods() -> list[MethodResponse]:
        return [_method_response(method) for method in methods.methods.values()]

    @app.post("/demo/seed", response_model=DemoSeedResponse, status_code=status.HTTP_201_CREATED)
    async def seed_demo(http_request: Request) -> DemoSeedResponse:
        user = user_from_request(http_request)
        try:
            payload = json.loads(DEMO_DATASET_PATH.read_text(encoding="utf-8"))
            dataset = validate_dataset(payload).model_dump(mode="json")
        except (OSError, json.JSONDecodeError, DatasetValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Demo dataset could not be loaded: {exc}",
            ) from exc

        session = backend_store.create_session(
            name="Golden demo dataset",
            dataset=dataset,
            owner_id=user.id,
        )
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
            name="MEA golden demo (1024-ch synthetic)",
            dataset=dataset,
            owner_id=DEMO_OWNER_ID,
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
    async def create_job(
        http_request: Request,
        session_id: str,
        request: JobCreateRequest,
    ) -> JobResponse:
        user = user_from_request(http_request)
        session = backend_store.get_session(session_id, owner_id=user.id)
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
            owner_id=user.id,
        )
        await _start_workers()
        await job_queue.put(
            _QueuedJob(
                job_id=job.id,
                session_id=session.id,
                owner_id=user.id,
                method_id=request.method_id,
                params=request.params,
            ),
        )
        return _job_response(job, methods=methods)

    @app.get("/jobs/{job_id}", response_model=JobResponse)
    async def get_job(http_request: Request, job_id: str) -> JobResponse:
        user = user_from_request(http_request)
        job = backend_store.get_job(job_id, owner_id=user.id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        return _job_response(job, methods=methods)

    @app.post(
        "/demo/sessions/{session_id}/jobs",
        response_model=JobResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_demo_job(session_id: str, request: JobCreateRequest) -> JobResponse:
        # Public anonymous demo lane: only whitelisted MEA methods, only on demo-owned sessions.
        if request.method_id not in DEMO_METHODS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Method not available in the public demo lane",
            )
        session = backend_store.get_session(session_id, owner_id=DEMO_OWNER_ID)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Demo session not found"
            )
        try:
            methods.lookup(request.method_id)
        except MethodLookupError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Method not found"
            ) from exc
        job = backend_store.create_job(
            session_id=session.id,
            dataset_version=session.dataset_version,
            method_id=request.method_id,
            params=request.params,
            owner_id=DEMO_OWNER_ID,
        )
        await _start_workers()
        await job_queue.put(
            _QueuedJob(
                job_id=job.id,
                session_id=session.id,
                owner_id=DEMO_OWNER_ID,
                method_id=request.method_id,
                params=request.params,
            ),
        )
        return _job_response(job, methods=methods)

    @app.get("/demo/jobs/{job_id}", response_model=JobResponse)
    async def get_demo_job(job_id: str) -> JobResponse:
        job = backend_store.get_job(job_id, owner_id=DEMO_OWNER_ID)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        return _job_response(job, methods=methods)

    @app.get(
        "/ws/jobs/{job_id}",
        status_code=status.HTTP_426_UPGRADE_REQUIRED,
        responses={426: {"description": "Use a WebSocket client for this endpoint"}},
        tags=["websocket"],
    )
    async def websocket_job_http_fallback(http_request: Request, job_id: str) -> JSONResponse:
        user = user_from_request(http_request)
        if backend_store.get_job(job_id, owner_id=user.id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        return JSONResponse(
            status_code=status.HTTP_426_UPGRADE_REQUIRED,
            content={"detail": f"Use WebSocket /ws/jobs/{job_id} for job progress"},
        )

    @app.websocket("/ws/jobs/{job_id}")
    async def job_progress(websocket: WebSocket, job_id: str) -> None:
        user = user_from_websocket(websocket)
        if user is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.accept()
        job = backend_store.get_job(job_id, owner_id=user.id)
        if job is None:
            await websocket.send_json({"status": "not_found", "error": "Job not found"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        queue: asyncio.Queue[None] = asyncio.Queue()
        watchers[job_id].add(queue)
        try:
            sent = 0
            while True:
                current = backend_store.get_job(job_id, owner_id=user.id)
                if current is None:
                    return
                if len(current.events) > sent:
                    for event in current.events[sent:]:
                        await websocket.send_json(event)
                        sent += 1
                    if current.status in {"completed", "failed"}:
                        return
                await queue.get()
        except WebSocketDisconnect:
            return
        finally:
            active = watchers.get(job_id)
            if active is not None:
                active.discard(queue)
                if not active:
                    watchers.pop(job_id, None)

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
        if user_from_websocket(websocket) is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
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
