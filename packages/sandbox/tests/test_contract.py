"""The serialized in/out contract must round-trip and reject malformed refs."""

from __future__ import annotations

import pytest

from neuromouse_sandbox import MethodRef, SandboxLimits
from neuromouse_sandbox.contract import (
    CONTRACT_VERSION,
    STATUS_OK,
    STATUS_POLICY_VIOLATION,
    RequestEnvelope,
    ResponseEnvelope,
)


def test_method_ref_file_requires_path() -> None:
    with pytest.raises(ValueError, match="path"):
        MethodRef(kind="file")


def test_method_ref_module_requires_module() -> None:
    with pytest.raises(ValueError, match="module"):
        MethodRef(kind="module")


def test_method_ref_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="kind"):
        MethodRef(kind="bogus", path="x")  # ty: ignore[invalid-argument-type]


def test_method_ref_round_trip() -> None:
    ref = MethodRef(kind="file", path="/methods/spike_detect.py", attr="method")
    assert MethodRef.from_jsonable(ref.to_jsonable()) == ref


def test_request_envelope_round_trip() -> None:
    request = RequestEnvelope(
        method=MethodRef(kind="module", module="pkg.mod", attr="m"),
        dataset={"meta": {"channels": ["a"]}},
        params={"k": 1},
        required_inputs=("meta.channels",),
        output_fields=("out.value",),
    )
    restored = RequestEnvelope.from_json(request.to_json())
    assert restored == request


def test_request_envelope_rejects_foreign_version() -> None:
    payload = '{"version":"other.v9","method":{"kind":"file","path":"x"}}'
    with pytest.raises(ValueError, match="contract version"):
        RequestEnvelope.from_json(payload)


def test_response_envelope_round_trips_each_status() -> None:
    ok = ResponseEnvelope(status=STATUS_OK, result={"a": 1})
    assert ResponseEnvelope.from_json(ok.to_json()).result == {"a": 1}

    blocked = ResponseEnvelope(
        status=STATUS_POLICY_VIOLATION,
        error_message="denied",
        blocked_event="socket.connect",
    )
    restored = ResponseEnvelope.from_json(blocked.to_json())
    assert restored.status == STATUS_POLICY_VIOLATION
    assert restored.blocked_event == "socket.connect"
    assert restored.version == CONTRACT_VERSION


def test_limits_round_trip_and_ignore_unknown_keys() -> None:
    limits = SandboxLimits(wall_clock_sec=3.0, cpu_sec=2)
    payload = limits.to_jsonable()
    payload["bogus"] = 99
    assert SandboxLimits.from_jsonable(payload) == limits
