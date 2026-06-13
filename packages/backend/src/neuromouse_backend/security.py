from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Final

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

DEFAULT_RATE_LIMIT_REQUESTS: Final = 120
DEFAULT_RATE_LIMIT_WINDOW_SECONDS: Final = 60

PUBLIC_PATHS: Final = ("/health", "/healthz", "/ready", "/readyz")


@dataclass(frozen=True)
class SecurityConfig:
    api_token: str
    rate_limit_requests: int
    rate_limit_window_seconds: int
    cors_allowlist: tuple[str, ...]


def _parse_positive_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value.strip())
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _load_security_config() -> SecurityConfig:
    token = os.getenv("NEUROMOUSE_API_TOKEN", "").strip()
    cors_allowlist = tuple(
        origin.strip()
        for origin in os.getenv("NEUROMOUSE_CORS_ALLOWLIST", "").split(",")
        if origin.strip()
    )
    return SecurityConfig(
        api_token=token,
        rate_limit_requests=_parse_positive_int(
            os.getenv("NEUROMOUSE_RATE_LIMIT_PER_IP"),
            DEFAULT_RATE_LIMIT_REQUESTS,
        ),
        rate_limit_window_seconds=_parse_positive_int(
            os.getenv("NEUROMOUSE_RATE_LIMIT_WINDOW_SECONDS"),
            DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
        ),
        cors_allowlist=cors_allowlist,
    )


def _parse_auth_token(request: Request) -> str:
    header_token = request.headers.get("x-api-token", "").strip()
    if header_token:
        return header_token
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _is_public_path(path: str) -> bool:
    normalized = path.rstrip("/")
    return normalized in PUBLIC_PATHS


def install_security_middlewares(app: FastAPI) -> None:
    config = _load_security_config()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_allowlist),
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    request_log: dict[str, deque[float]] = defaultdict(deque)

    @app.middleware("http")
    async def _rate_limit_middleware(request: Request, call_next):
        if (
            request.scope["type"] != "http"
            or request.method.upper() == "OPTIONS"
            or _is_public_path(request.url.path)
            or config.rate_limit_requests <= 0
            or config.rate_limit_window_seconds <= 0
        ):
            return await call_next(request)

        client_host = request.client.host if request.client is not None else "unknown"
        now = time.time()
        cutoff = now - config.rate_limit_window_seconds
        client_requests = request_log[client_host]
        while client_requests and client_requests[0] <= cutoff:
            client_requests.popleft()
        if len(client_requests) >= config.rate_limit_requests:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(config.rate_limit_window_seconds)},
            )

        client_requests.append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(config.rate_limit_requests)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, config.rate_limit_requests - len(client_requests))
        )
        response.headers["X-RateLimit-Reset"] = str(config.rate_limit_window_seconds)
        return response

    @app.middleware("http")
    async def _api_token_middleware(request: Request, call_next):
        if (
            request.scope["type"] != "http"
            or request.method.upper() == "OPTIONS"
            or _is_public_path(request.url.path)
        ):
            return await call_next(request)

        if not config.api_token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "API token is not configured"},
            )

        if not hmac.compare_digest(_parse_auth_token(request), config.api_token):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing or invalid API token"},
            )

        return await call_next(request)
