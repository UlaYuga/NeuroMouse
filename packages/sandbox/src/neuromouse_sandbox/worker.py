"""Untrusted-side entry point: ``python -m neuromouse_sandbox.worker IN OUT``.

Run inside the isolated child. Reads a :class:`RequestEnvelope` from ``IN``,
locates and imports the (untrusted) method module *under* the audit policy,
builds params, runs ``compute`` against the dataset, validates the declared
output paths, and writes a :class:`ResponseEnvelope` to ``OUT``.

Ordering is load-bearing: trusted infrastructure (contract validation, the JSON
envelope) is imported and the dataset is reconstructed *before* the policy is
installed and the untrusted module is touched. The result is written through a
file descriptor opened *before* the policy locks the filesystem, so a method
that floods stdout or blocks ``open`` cannot corrupt or suppress the response.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import traceback
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from neuromouse_sandbox.contract import (
    STATUS_BAD_REQUEST,
    STATUS_METHOD_ERROR,
    STATUS_OK,
    STATUS_POLICY_VIOLATION,
    MethodRef,
    RequestEnvelope,
    ResponseEnvelope,
)
from neuromouse_sandbox.policy import PolicyViolation, install_runtime_policy


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        # No usable output channel — fail loudly on stderr and signal misuse.
        sys.stderr.write("usage: python -m neuromouse_sandbox.worker INPUT OUTPUT\n")
        return 2
    input_path, output_path = argv[1], argv[2]

    # --- trusted phase: read request, reconstruct dataset, open result fd ----
    with open(input_path, encoding="utf-8") as handle:
        request = RequestEnvelope.from_json(handle.read())

    # Pre-import trusted infrastructure so it is resolved before the policy and
    # the untrusted import run.
    from neuromouse_contract import validate_dataset  # noqa: PLC0415
    from neuromouse_sdk import build_params  # noqa: PLC0415

    dataset_obj: Any
    if request.dataset is None:
        dataset_obj = SimpleNamespace()
    else:
        dataset_obj = validate_dataset(request.dataset)

    out_fd = os.open(output_path, os.O_WRONLY | os.O_TRUNC)

    def _emit(envelope: ResponseEnvelope) -> int:
        try:
            os.write(out_fd, envelope.to_json().encode("utf-8"))
        finally:
            os.close(out_fd)
        return 0

    # --- lock down, then enter untrusted territory --------------------------
    _install_policy(request.method)

    try:
        module = _load_module(request.method)
        method = getattr(module, request.method.attr, None)
        if method is None or not callable(getattr(method, "compute", None)):
            return _emit(
                ResponseEnvelope(
                    status=STATUS_BAD_REQUEST,
                    error_message=(
                        f"method attribute {request.method.attr!r} missing or not a Method"
                    ),
                )
            )

        params = build_params(getattr(method, "params_type", dict), request.params)
        _require_paths(dataset_obj, request.required_inputs, "required input")

        raw = method.compute(dataset_obj, params)
        if not isinstance(raw, Mapping):
            raise TypeError("method returned a non-mapping result")
        result = _jsonable(raw)
        _require_paths(result, request.output_fields, "declared output field")
    except PolicyViolation as exc:
        return _emit(
            ResponseEnvelope(
                status=STATUS_POLICY_VIOLATION,
                error_message=str(exc),
                blocked_event=exc.event,
            )
        )
    except BaseException as exc:  # noqa: BLE001 - boundary: classify everything as graceful failure
        # A method may have caught our PolicyViolation and re-raised something
        # else; surface the original blocked event if one is in the chain.
        blocked = _find_blocked_event(exc)
        if blocked is not None:
            return _emit(
                ResponseEnvelope(
                    status=STATUS_POLICY_VIOLATION,
                    error_message=str(exc),
                    blocked_event=blocked,
                )
            )
        return _emit(
            ResponseEnvelope(
                status=STATUS_METHOD_ERROR,
                error_message=f"{type(exc).__name__}: {exc}",
                error_detail=_short_traceback(exc),
            )
        )

    return _emit(ResponseEnvelope(status=STATUS_OK, result=result))


def _install_policy(ref: MethodRef) -> None:
    workdir = os.getcwd()
    read_prefixes: list[str] = [sys.base_prefix, sys.prefix, sys.exec_prefix, workdir]
    read_prefixes.extend(p for p in sys.path if p and os.path.isdir(p))
    if ref.kind == "file" and ref.path:
        read_prefixes.append(os.path.dirname(os.path.abspath(ref.path)))
    install_runtime_policy(
        workdir=workdir,
        read_allow_prefixes=tuple(dict.fromkeys(read_prefixes)),
        write_allow_prefixes=(),
    )


def _load_module(ref: MethodRef) -> Any:
    if ref.kind == "module":
        if ref.module is None:
            raise ImportError("module method ref is missing a module name")
        return importlib.import_module(ref.module)
    if ref.path is None:
        raise ImportError("file method ref is missing a path")
    name = f"_nm_sandbox_method_{abs(hash(ref.path)) & 0xFFFFFFFF:x}"
    spec = importlib.util.spec_from_file_location(name, ref.path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load method module at {ref.path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _require_paths(value: Any, paths: tuple[str, ...], label: str) -> None:
    for path in paths:
        if not _has_path(value, path):
            raise ValueError(f"method missing {label} {path!r}")


def _has_path(value: Any, path: str) -> bool:
    current = value
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return False
            current = current[part]
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            return False
        if current is None:
            return False
    return True


def _jsonable(value: Any) -> Any:
    """Coerce a method result into JSON-native types without importing heavy deps.

    Methods are expected to return plain Python; this defends against stray
    numpy scalars/arrays so a well-behaved method is never failed for a benign
    return type while keeping the contract strictly JSON.
    """

    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return _jsonable(tolist())
    item = getattr(value, "item", None)
    if callable(item):
        return _jsonable(item())
    raise TypeError(f"method result is not JSON-serializable: {type(value).__name__}")


def _find_blocked_event(exc: BaseException) -> str | None:
    seen = set()
    cursor: BaseException | None = exc
    while cursor is not None and id(cursor) not in seen:
        seen.add(id(cursor))
        if isinstance(cursor, PolicyViolation):
            return cursor.event
        cursor = cursor.__cause__ or cursor.__context__
    return None


def _short_traceback(exc: BaseException) -> str:
    lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    text = "".join(lines)
    return text[-2000:]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
