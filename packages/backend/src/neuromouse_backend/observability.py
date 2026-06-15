from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Final

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_MAX_BODY_BYTES: Final = 10 * 1024 * 1024
REQUEST_LOGGER: Final = logging.getLogger("neuromouse_backend.request")


class RequestBodyTooLargeError(ValueError):
    """Raised when a streaming request body exceeds the configured byte ceiling."""


def _parse_max_body_bytes(raw: str | None) -> int | None:
    if raw is None:
        return DEFAULT_MAX_BODY_BYTES
    value = raw.strip()
    if not value:
        return DEFAULT_MAX_BODY_BYTES
    try:
        parsed = int(value)
    except ValueError:
        return DEFAULT_MAX_BODY_BYTES
    return parsed if parsed > 0 else None


def _configure_request_logger() -> None:
    level_name = os.getenv("NEUROMOUSE_LOG_LEVEL", "INFO").strip().upper() or "INFO"
    level = getattr(logging, level_name, logging.INFO)
    REQUEST_LOGGER.setLevel(level)
    REQUEST_LOGGER.propagate = False
    if any(
        handler.get_name() == "neuromouse-json"
        for handler in REQUEST_LOGGER.handlers
    ):
        return
    handler = logging.StreamHandler()
    handler.set_name("neuromouse-json")
    handler.setFormatter(logging.Formatter("%(message)s"))
    REQUEST_LOGGER.addHandler(handler)


def _content_length(headers: Headers) -> int | None:
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _client_host(scope: Scope) -> str:
    client = scope.get("client")
    if isinstance(client, tuple) and client:
        return str(client[0])
    return "unknown"


def _base_payload(scope: Scope, start: float, status_code: int) -> dict[str, object]:
    headers = Headers(scope=scope)
    payload: dict[str, object] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "method": str(scope.get("method", "")),
        "path": str(scope.get("path", "")),
        "status_code": status_code,
        "duration_ms": round((time.perf_counter() - start) * 1000, 3),
        "client": _client_host(scope),
    }
    request_id = headers.get("x-request-id")
    if request_id:
        payload["request_id"] = request_id
    return payload


def _log_payload(level: int, payload: dict[str, object]) -> None:
    REQUEST_LOGGER.log(level, json.dumps(payload, sort_keys=True, separators=(",", ":")))


class RequestObservabilityMiddleware:
    def __init__(self, app: ASGIApp, *, max_body_bytes: int | None) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        _configure_request_logger()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code: int | None = None
        response_started = False
        received_body_bytes = 0
        headers = Headers(scope=scope)
        content_length = _content_length(headers)

        if (
            self.max_body_bytes is not None
            and content_length is not None
            and content_length > self.max_body_bytes
        ):
            await self._send_body_too_large(scope, receive, send, start)
            return

        async def receive_limited() -> Message:
            nonlocal received_body_bytes
            message = await receive()
            if message["type"] == "http.request" and self.max_body_bytes is not None:
                body = message.get("body", b"")
                if isinstance(body, bytes):
                    received_body_bytes += len(body)
                if received_body_bytes > self.max_body_bytes:
                    raise RequestBodyTooLargeError
            return message

        async def send_observed(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive_limited, send_observed)
        except RequestBodyTooLargeError:
            if response_started:
                payload = _base_payload(
                    scope,
                    start,
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
                payload.update(
                    {
                        "event": "http_error",
                        "error_type": "RequestBodyTooLargeError",
                        "error": f"request body exceeds {self.max_body_bytes} bytes",
                    }
                )
                _log_payload(logging.ERROR, payload)
                raise
            await self._send_body_too_large(scope, receive, send, start)
            return
        except Exception as exc:
            payload = _base_payload(scope, start, status.HTTP_500_INTERNAL_SERVER_ERROR)
            payload.update(
                {
                    "event": "http_error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            _log_payload(logging.ERROR, payload)
            raise

        completed_status = status_code or status.HTTP_500_INTERNAL_SERVER_ERROR
        payload = _base_payload(scope, start, completed_status)
        if completed_status >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            payload["event"] = "http_error"
            _log_payload(logging.ERROR, payload)
            return
        payload["event"] = "http_request"
        _log_payload(logging.INFO, payload)

    async def _send_body_too_large(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        start: float,
    ) -> None:
        max_body_bytes = self.max_body_bytes or 0
        response = JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"detail": f"request body exceeds {max_body_bytes} bytes"},
        )
        await response(scope, receive, send)
        payload = _base_payload(scope, start, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        payload["event"] = "http_request"
        _log_payload(logging.WARNING, payload)


def install_observability_middleware(app: FastAPI) -> None:
    app.add_middleware(
        RequestObservabilityMiddleware,
        max_body_bytes=_parse_max_body_bytes(os.getenv("NEUROMOUSE_MAX_BODY_BYTES")),
    )
