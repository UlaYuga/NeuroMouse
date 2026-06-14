"""Serialized in/out contract shared by the parent runner and the child worker.

Everything that crosses the process boundary is plain JSON. The parent writes a
:class:`request envelope <RequestEnvelope>` describing *how to locate the method*
(:class:`MethodRef`), the dataset and the params; the child writes a
:class:`response envelope <ResponseEnvelope>` carrying either the result mapping
or a structured, classified error. No Python objects, no pickling — a hostile
method cannot smuggle code back across the boundary through the contract.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

CONTRACT_VERSION = "neuromouse.sandbox.v1"

# Response status values written by the worker into the result envelope.
STATUS_OK = "ok"
STATUS_METHOD_ERROR = "method_error"  # method raised / bad inputs / bad output (graceful)
STATUS_POLICY_VIOLATION = "policy_violation"  # audit hook denied an operation
STATUS_BAD_REQUEST = "bad_request"  # malformed request envelope / unloadable method

ResponseStatus = Literal[
    "ok",
    "method_error",
    "policy_violation",
    "bad_request",
]


@dataclass(frozen=True)
class MethodRef:
    """A JSON-serializable locator telling the worker how to import a method.

    ``kind="file"`` loads ``path`` as a standalone module (the bundled MEA
    reference methods live as loose ``methods/*.py`` files); ``kind="module"``
    imports a dotted module name already importable on ``sys.path``. In both
    cases ``attr`` is the module attribute holding the ``Method`` instance.
    """

    kind: Literal["file", "module"]
    attr: str = "method"
    path: str | None = None
    module: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "file" and not self.path:
            raise ValueError("MethodRef(kind='file') requires a path")
        if self.kind == "module" and not self.module:
            raise ValueError("MethodRef(kind='module') requires a module name")
        if self.kind not in ("file", "module"):
            raise ValueError(f"unknown MethodRef kind: {self.kind!r}")
        if not self.attr:
            raise ValueError("MethodRef requires a non-empty attr")

    def to_jsonable(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_jsonable(cls, payload: dict[str, Any]) -> MethodRef:
        return cls(
            kind=payload["kind"],
            attr=payload.get("attr", "method"),
            path=payload.get("path"),
            module=payload.get("module"),
        )


@dataclass(frozen=True)
class SandboxLimits:
    """Resource budget enforced on the untrusted child process.

    Defaults are generous enough for the bundled MEA reference methods on the
    1024-channel golden fixture while still containing pathological code.
    """

    wall_clock_sec: float = 30.0
    cpu_sec: int = 25
    memory_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GiB address space
    max_output_bytes: int = 256 * 1024 * 1024  # RLIMIT_FSIZE
    max_processes: int = 256  # RLIMIT_NPROC ceiling (fork-bomb backstop)
    max_open_files: int = 256  # RLIMIT_NOFILE

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_jsonable(cls, payload: dict[str, Any]) -> SandboxLimits:
        return cls(**{k: v for k, v in payload.items() if k in cls.__dataclass_fields__})


# Request modes: run the method, or merely introspect its declared metadata.
MODE_COMPUTE = "compute"
MODE_DESCRIBE = "describe"

RequestMode = Literal["compute", "describe"]


@dataclass(frozen=True)
class RequestEnvelope:
    method: MethodRef
    dataset: dict[str, Any] | None
    params: dict[str, Any]
    required_inputs: tuple[str, ...]
    output_fields: tuple[str, ...]
    mode: RequestMode = MODE_COMPUTE
    version: str = CONTRACT_VERSION

    def to_json(self) -> str:
        payload = {
            "version": self.version,
            "mode": self.mode,
            "method": self.method.to_jsonable(),
            "dataset": self.dataset,
            "params": self.params,
            "required_inputs": list(self.required_inputs),
            "output_fields": list(self.output_fields),
        }
        return json.dumps(payload, separators=(",", ":"), allow_nan=False)

    @classmethod
    def from_json(cls, text: str) -> RequestEnvelope:
        payload = json.loads(text)
        if payload.get("version") != CONTRACT_VERSION:
            raise ValueError(f"unsupported sandbox contract version: {payload.get('version')!r}")
        mode = payload.get("mode", MODE_COMPUTE)
        if mode not in (MODE_COMPUTE, MODE_DESCRIBE):
            raise ValueError(f"unsupported sandbox request mode: {mode!r}")
        return cls(
            method=MethodRef.from_jsonable(payload["method"]),
            dataset=payload.get("dataset"),
            params=payload.get("params") or {},
            required_inputs=tuple(payload.get("required_inputs") or ()),
            output_fields=tuple(payload.get("output_fields") or ()),
            mode=mode,
        )


@dataclass(frozen=True)
class ResponseEnvelope:
    status: ResponseStatus
    result: dict[str, Any] | None = None
    error_message: str | None = None
    error_detail: str | None = None
    blocked_event: str | None = None  # the audit event name, for policy violations
    diagnostics: dict[str, Any] = field(default_factory=dict)
    version: str = CONTRACT_VERSION

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": self.version,
                "status": self.status,
                "result": self.result,
                "error_message": self.error_message,
                "error_detail": self.error_detail,
                "blocked_event": self.blocked_event,
                "diagnostics": self.diagnostics,
            },
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def from_json(cls, text: str) -> ResponseEnvelope:
        payload = json.loads(text)
        return cls(
            status=payload["status"],
            result=payload.get("result"),
            error_message=payload.get("error_message"),
            error_detail=payload.get("error_detail"),
            blocked_event=payload.get("blocked_event"),
            diagnostics=payload.get("diagnostics") or {},
            version=payload.get("version", CONTRACT_VERSION),
        )
