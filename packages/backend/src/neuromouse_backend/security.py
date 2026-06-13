from __future__ import annotations

import json
import os
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from fastapi import FastAPI, Request, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

DEFAULT_RATE_LIMIT_REQUESTS: Final = 120
DEFAULT_RATE_LIMIT_WINDOW_SECONDS: Final = 60
DEFAULT_SESSION_COOKIE_NAME: Final = "neuromouse_session"

PUBLIC_PATHS: Final = (
    "/health",
    "/healthz",
    "/ready",
    "/readyz",
    "/auth/register",
    "/auth/login",
    "/auth/logout",
)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str


SessionTokenResolver = Callable[[str], AuthenticatedUser | None]


@dataclass(frozen=True)
class SecurityConfig:
    session_token_resolver: SessionTokenResolver
    session_cookie_name: str
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


class EnvSessionTokenResolver:
    def __init__(self, token_to_user_id: Mapping[str, str]) -> None:
        self._token_to_user_id = dict(token_to_user_id)

    @classmethod
    def from_env(cls) -> EnvSessionTokenResolver:
        return cls(_parse_session_token_mapping(os.getenv("NEUROMOUSE_SESSION_TOKENS", "")))

    def resolve(self, token: str) -> AuthenticatedUser | None:
        user_id = self._token_to_user_id.get(token)
        if user_id is None:
            return None
        return AuthenticatedUser(id=user_id)


def _parse_session_token_mapping(raw: str) -> dict[str, str]:
    value = raw.strip()
    if not value:
        return {}
    if value.startswith("{"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {
            str(token).strip(): str(user_id).strip()
            for token, user_id in parsed.items()
            if str(token).strip() and str(user_id).strip()
        }

    token_to_user_id: dict[str, str] = {}
    for entry in value.split(","):
        item = entry.strip()
        if not item:
            continue
        separator = ":" if ":" in item else "="
        if separator not in item:
            continue
        token, user_id = item.split(separator, maxsplit=1)
        token = token.strip()
        user_id = user_id.strip()
        if token and user_id:
            token_to_user_id[token] = user_id
    return token_to_user_id


def _load_security_config(
    session_token_resolver: SessionTokenResolver | None = None,
) -> SecurityConfig:
    cors_allowlist = tuple(
        origin.strip()
        for origin in os.getenv("NEUROMOUSE_CORS_ALLOWLIST", "").split(",")
        if origin.strip()
    )
    return SecurityConfig(
        session_token_resolver=session_token_resolver or EnvSessionTokenResolver.from_env().resolve,
        session_cookie_name=(
            os.getenv("NEUROMOUSE_SESSION_COOKIE", DEFAULT_SESSION_COOKIE_NAME).strip()
            or DEFAULT_SESSION_COOKIE_NAME
        ),
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


def _parse_session_token_from_request(request: Request, *, cookie_name: str) -> str:
    header_token = request.headers.get("x-session-token", "").strip()
    if header_token:
        return header_token
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.cookies.get(cookie_name, "").strip()


def _parse_session_token_from_websocket(websocket: WebSocket, *, cookie_name: str) -> str:
    header_token = websocket.headers.get("x-session-token", "").strip()
    if header_token:
        return header_token
    authorization = websocket.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return websocket.cookies.get(cookie_name, "").strip()


def _resolve_session_token(
    token: str,
    *,
    resolver: SessionTokenResolver,
) -> AuthenticatedUser | None:
    if not token:
        return None
    return resolver(token)


def user_from_request(request: Request) -> AuthenticatedUser:
    user = getattr(request.state, "user", None)
    if not isinstance(user, AuthenticatedUser):  # pragma: no cover - route misuse guard
        raise RuntimeError("authenticated user was not attached to the request")
    return user


def user_from_websocket(websocket: WebSocket) -> AuthenticatedUser | None:
    app = websocket.scope["app"]
    resolver = getattr(app.state, "session_token_resolver", None)
    cookie_name = getattr(app.state, "session_cookie_name", DEFAULT_SESSION_COOKIE_NAME)
    if resolver is None:
        return None
    token = _parse_session_token_from_websocket(websocket, cookie_name=cookie_name)
    return _resolve_session_token(token, resolver=resolver)


def _is_public_path(path: str) -> bool:
    normalized = path.rstrip("/")
    return normalized in PUBLIC_PATHS


def _is_demo_path(path: str) -> bool:
    """Public anonymous demo lane — reachable without auth (owner = anonymous)."""
    normalized = path.rstrip("/")
    if normalized in {"/demo/seed-mea", "/demo/methods"}:
        return True
    if normalized.startswith("/demo/sessions/") and normalized.endswith("/jobs"):
        return True
    return normalized.startswith("/demo/jobs/")


def install_security_middlewares(
    app: FastAPI,
    *,
    session_token_resolver: SessionTokenResolver | None = None,
) -> None:
    config = _load_security_config(session_token_resolver)
    app.state.session_token_resolver = config.session_token_resolver
    app.state.session_cookie_name = config.session_cookie_name

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
            or _is_demo_path(request.url.path)
        ):
            return await call_next(request)

        token = _parse_session_token_from_request(
            request,
            cookie_name=config.session_cookie_name,
        )
        user = _resolve_session_token(token, resolver=config.session_token_resolver)
        if user is None:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing or invalid session token"},
            )

        request.state.user = user
        return await call_next(request)
