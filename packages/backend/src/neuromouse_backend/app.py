from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import time
from collections import defaultdict, deque
from contextlib import suppress
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
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
    UserMethodRecord,
    create_backend_store,
)
from neuromouse_contract import DatasetValidationError, validate_dataset
from neuromouse_sandbox import (
    MethodRef,
    SandboxError,
    SandboxLimits,
    describe_in_sandbox,
    run_in_sandbox,
)
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
    private: bool = False


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


def _abuse_limit(name: str, default: int) -> int:
    """Read an env-tunable abuse cap at call time (so tests/envs take effect).
    ``0`` disables the corresponding limit."""
    try:
        return max(0, int(os.environ[name]))
    except (KeyError, ValueError):
        return default


class RateLimiter:
    """Fixed-window in-memory limiter (single-replica). ``limit<=0`` disables it."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = limit
        self._window = window_seconds
        self._log: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        if self._limit <= 0:
            return True
        bucket = self._log[key]
        now = time.monotonic()
        cutoff = now - self._window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self._limit:
            return False
        bucket.append(now)
        return True


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client is not None else "unknown"


def _too_many(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": "60"},
    )


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
    async def auth_register(
        http_request: Request, payload: AuthCredentials
    ) -> dict[str, str]:
        if not auth_limiter.allow(f"auth:{_client_ip(http_request)}"):
            raise _too_many("Too many attempts; try again in a minute")
        # Spoof-proof backstop against mass account creation (IP can be forged).
        if not registration_limiter.allow("global"):
            raise _too_many("Registration is temporarily rate-limited; try again later")
        try:
            account = auth_service.register(payload.email, payload.password)
        except AuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": account.id, "email": account.email}

    @app.post("/auth/login")
    async def auth_login(
        http_request: Request, payload: AuthCredentials, response: Response
    ) -> dict[str, str]:
        if not auth_limiter.allow(f"auth:{_client_ip(http_request)}"):
            raise _too_many("Too many attempts; try again in a minute")
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

    # Abuse caps — read from env at app-construction time (0 disables). Keyed by
    # authenticated user where possible (unspoofable); global/IP caps back-stop
    # the unauthenticated lanes.
    max_job_queue = _abuse_limit("NEUROMOUSE_MAX_JOB_QUEUE", 256)
    max_active_jobs = _abuse_limit("NEUROMOUSE_MAX_ACTIVE_JOBS_PER_USER", 3)
    max_methods_per_user = _abuse_limit("NEUROMOUSE_MAX_METHODS_PER_USER", 25)
    max_dataset_bytes = _abuse_limit("NEUROMOUSE_MAX_DATASET_BYTES", 32 * 1024 * 1024)

    job_queue: asyncio.Queue[_QueuedJob] = asyncio.Queue(maxsize=max_job_queue)
    watchers: dict[str, set[asyncio.Queue[None]]] = defaultdict(set)
    workers: list[asyncio.Task[None]] = []
    worker_bootstrap = asyncio.Lock()

    active_jobs: dict[str, int] = defaultdict(int)
    job_limiter = RateLimiter(_abuse_limit("NEUROMOUSE_JOBS_PER_MIN", 30), 60.0)
    upload_limiter = RateLimiter(_abuse_limit("NEUROMOUSE_UPLOADS_PER_MIN", 10), 60.0)
    session_limiter = RateLimiter(_abuse_limit("NEUROMOUSE_SESSIONS_PER_MIN", 30), 60.0)
    auth_limiter = RateLimiter(_abuse_limit("NEUROMOUSE_AUTH_PER_MIN_PER_IP", 10), 60.0)
    registration_limiter = RateLimiter(
        _abuse_limit("NEUROMOUSE_REGISTRATIONS_PER_HOUR", 50), 3600.0
    )

    def _enqueue_job(queued: _QueuedJob) -> None:
        """Admit a job to the bounded queue, or reject (429/503). Caller must
        have already passed the per-user rate + active-job checks."""
        if max_job_queue and job_queue.qsize() >= max_job_queue:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Job queue is full; try again shortly",
                headers={"Retry-After": "30"},
            )
        # No await between the qsize check and put_nowait → admission is atomic.
        job_queue.put_nowait(queued)
        active_jobs[queued.owner_id] += 1

    def _enqueue_or_fail(job: JobRecord, queued: _QueuedJob) -> None:
        try:
            _enqueue_job(queued)
        except HTTPException:
            with suppress(Exception):
                backend_store.append_job_event(
                    job.id, status="failed", error="job queue full", owner_id=queued.owner_id
                )
            raise

    def _broadcast_job_update(event: dict[str, Any]) -> None:
        for queue in list(watchers.get(event["job_id"], set())):
            queue.put_nowait(None)

    def _resolve_and_run(
        method_id: str,
        owner_id: str,
        dataset: dict[str, Any],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = _normalize_method_id(method_id)
        if normalized in methods.methods:
            return methods.run(normalized, dataset, params=params)
        record = backend_store.get_user_method(owner_id, normalized)
        if record is None:
            raise MethodExecutionError(f"unknown method: {method_id}")
        return run_user_method(record, dataset, params)

    def _user_method_meta_for(method_id: str, owner_id: str) -> dict[str, Any] | None:
        normalized = _normalize_method_id(method_id)
        if normalized in methods.methods:
            return None
        record = backend_store.get_user_method(owner_id, normalized)
        return record.metadata if record is not None else None

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
                _resolve_and_run,
                queued_job.method_id,
                queued_job.owner_id,
                session.dataset,
                queued_job.params,
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
        finally:
            remaining = active_jobs.get(queued_job.owner_id, 0) - 1
            if remaining > 0:
                active_jobs[queued_job.owner_id] = remaining
            else:
                active_jobs.pop(queued_job.owner_id, None)

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
        if not session_limiter.allow(user.id):
            raise _too_many("Too many sessions created; slow down")
        if max_dataset_bytes and len(json.dumps(request.dataset)) > max_dataset_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"dataset exceeds {max_dataset_bytes} bytes",
            )
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
    async def list_methods(http_request: Request) -> list[MethodResponse]:
        user = user_from_request(http_request)
        builtin = [_method_response(method) for method in methods.methods.values()]
        private = [
            _user_method_response(record)
            for record in backend_store.list_user_methods(user.id)
        ]
        return builtin + private

    @app.post(
        "/methods",
        response_model=MethodResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_method(
        http_request: Request,
        file: Annotated[UploadFile, File()],
    ) -> MethodResponse:
        user = user_from_request(http_request)
        if not upload_limiter.allow(user.id):
            raise _too_many("Too many method uploads; slow down")
        if max_methods_per_user and len(list(backend_store.list_user_methods(user.id))) >= (
            max_methods_per_user
        ):
            raise _too_many(
                f"Method limit reached ({max_methods_per_user}); delete some before uploading more"
            )
        raw = await file.read(MAX_METHOD_SOURCE_BYTES + 1)
        if len(raw) > MAX_METHOD_SOURCE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"method source exceeds {MAX_METHOD_SOURCE_BYTES} bytes",
            )
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="method source must be UTF-8 text",
            ) from exc

        # Introspect the (untrusted) module inside the sandbox to read its
        # declared metadata — never imported in this process.
        try:
            metadata = describe_uploaded_method(source)
        except MethodUploadError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        method_id = _normalize_method_id(metadata["name"])
        if method_id in methods.methods:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"method id {method_id!r} collides with a built-in method",
            )
        record = backend_store.upsert_user_method(
            owner_id=user.id,
            method_id=method_id,
            name=metadata["name"],
            version=str(metadata.get("version", "0.0.0")),
            source=source,
            metadata=metadata,
        )
        return _user_method_response(record)

    @app.delete("/methods/{method_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_method(http_request: Request, method_id: str) -> Response:
        user = user_from_request(http_request)
        if not backend_store.delete_user_method(user.id, _normalize_method_id(method_id)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Method not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

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

        normalized = _normalize_method_id(request.method_id)
        if normalized not in methods.methods and (
            backend_store.get_user_method(user.id, normalized) is None
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Method not found",
            )

        if not job_limiter.allow(user.id):
            raise _too_many("Too many job submissions; slow down")
        if max_active_jobs and active_jobs.get(user.id, 0) >= max_active_jobs:
            raise _too_many("Too many concurrent jobs; wait for the running ones to finish")

        job = backend_store.create_job(
            session_id=session.id,
            dataset_version=session.dataset_version,
            method_id=request.method_id,
            params=request.params,
            owner_id=user.id,
        )
        await _start_workers()
        _enqueue_or_fail(
            job,
            _QueuedJob(
                job_id=job.id,
                session_id=session.id,
                owner_id=user.id,
                method_id=request.method_id,
                params=request.params,
            ),
        )
        return _job_response(
            job,
            methods=methods,
            user_method_meta=_user_method_meta_for(request.method_id, user.id),
        )

    @app.get("/jobs/{job_id}", response_model=JobResponse)
    async def get_job(http_request: Request, job_id: str) -> JobResponse:
        user = user_from_request(http_request)
        job = backend_store.get_job(job_id, owner_id=user.id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        return _job_response(
            job,
            methods=methods,
            user_method_meta=_user_method_meta_for(job.method_id, user.id),
        )

    @app.post(
        "/demo/sessions/{session_id}/jobs",
        response_model=JobResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_demo_job(
        http_request: Request, session_id: str, request: JobCreateRequest
    ) -> JobResponse:
        # Public anonymous demo lane: only whitelisted MEA methods, only on demo-owned sessions.
        if request.method_id not in DEMO_METHODS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Method not available in the public demo lane",
            )
        # Anonymous lane → rate-limit by best-effort client IP.
        if not job_limiter.allow(f"demo:{_client_ip(http_request)}"):
            raise _too_many("Too many demo jobs; slow down")
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
        _enqueue_or_fail(
            job,
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


def _job_response(
    job: JobRecord,
    *,
    methods: MethodCatalog,
    user_method_meta: dict[str, Any] | None = None,
) -> JobResponse:
    return JobResponse(
        id=job.id,
        session_id=job.session_id,
        dataset_version=job.dataset_version,
        method_id=job.method_id,
        params=job.params,
        status=cast(Literal["queued", "running", "completed", "failed"], job.status),
        result=_job_result_response(job, methods=methods, user_method_meta=user_method_meta),
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


# --- user-uploaded private methods ------------------------------------------

# Tight budget for untrusted user methods: enough for real DSP on the golden
# fixtures, well short of anything that could threaten the backend host.
USER_METHOD_LIMITS = SandboxLimits(
    wall_clock_sec=20.0,
    cpu_sec=12,
    memory_bytes=1024 * 1024 * 1024,
    max_output_bytes=64 * 1024 * 1024,
    max_processes=64,
    max_open_files=128,
)
MAX_METHOD_SOURCE_BYTES = 256 * 1024


class MethodUploadError(ValueError):
    """Raised when an uploaded method cannot be registered (bad source / sandbox)."""


def _write_temp_method(source: str) -> str:
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - path handed to subprocess
        mode="w", suffix=".py", prefix="nm_user_method_", delete=False, encoding="utf-8"
    )
    try:
        handle.write(source)
    finally:
        handle.close()
    return handle.name


def _safe_unlink(path: str) -> None:
    with suppress(OSError):
        os.unlink(path)


def describe_uploaded_method(source: str) -> dict[str, Any]:
    """Introspect an uploaded method's metadata in the sandbox (no compute)."""

    path = _write_temp_method(source)
    try:
        return describe_in_sandbox(
            MethodRef(kind="file", path=path, attr="method"), limits=USER_METHOD_LIMITS
        )
    except SandboxError as exc:
        raise MethodUploadError(f"method could not be registered: {exc}") from exc
    finally:
        _safe_unlink(path)


def run_user_method(
    record: UserMethodRecord,
    dataset: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Run a stored user method through the sandbox (same boundary as built-ins)."""

    try:
        dataset_payload = validate_dataset(dataset).model_dump(mode="json")
    except DatasetValidationError as exc:
        raise MethodExecutionError(f"method {record.method_id!r} failed: {exc}") from exc

    output_meta = record.metadata.get("output", {})
    required_inputs = tuple(record.metadata.get("required_inputs") or ())
    output_fields = tuple(field["path"] for field in output_meta.get("fields", []))
    path = _write_temp_method(record.source)
    try:
        return run_in_sandbox(
            MethodRef(kind="file", path=path, attr="method"),
            dataset_payload,
            dict(params),
            limits=USER_METHOD_LIMITS,
            required_inputs=required_inputs,
            output_fields=output_fields,
        )
    except SandboxError as exc:
        raise MethodExecutionError(f"method {record.method_id!r} failed: {exc}") from exc
    finally:
        _safe_unlink(path)


def _output_spec_response_from_meta(output_meta: dict[str, Any]) -> OutputSpecResponse:
    panel_meta = output_meta.get("panel")
    return OutputSpecResponse(
        fields=[
            OutputFieldResponse(
                path=field["path"],
                label=_label_from_path(field["path"]),
                description=field.get("description", ""),
                unit=field.get("unit"),
            )
            for field in output_meta.get("fields", [])
        ],
        panel=PanelSpecResponse(
            id=panel_meta["id"],
            title=panel_meta["title"],
            kind=panel_meta["kind"],
            field=panel_meta["field"],
        )
        if panel_meta
        else None,
    )


def _user_method_response(record: UserMethodRecord) -> MethodResponse:
    meta = record.metadata
    output_meta = meta.get("output", {})
    panel_meta = output_meta.get("panel")
    name = panel_meta["title"] if panel_meta else record.name
    descriptions = []
    for field in output_meta.get("fields", []):
        if field.get("description"):
            descriptions.append(f"{field['path']}: {field['description']}")
        else:
            descriptions.append(field["path"])
    return MethodResponse(
        id=record.method_id,
        name=name,
        description="; ".join(descriptions),
        required_inputs=list(meta.get("required_inputs") or []),
        params_schema=meta.get("params_schema")
        or {"title": "Params", "type": "object", "properties": {}},
        output_spec=_output_spec_response_from_meta(output_meta),
        private=True,
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


def _job_result_response(
    job: JobRecord,
    *,
    methods: MethodCatalog,
    user_method_meta: dict[str, Any] | None = None,
) -> JobResultResponse | None:
    if job.result is None:
        return None
    try:
        method = methods.lookup(job.method_id)
    except MethodLookupError:
        if user_method_meta is not None:
            spec = _output_spec_response_from_meta(user_method_meta.get("output", {}))
            return JobResultResponse(output=job.result, output_spec=spec, panel=spec.panel)
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
