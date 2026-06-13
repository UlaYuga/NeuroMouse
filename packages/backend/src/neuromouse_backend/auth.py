from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from neuromouse_backend.security import AuthenticatedUser
from neuromouse_backend.storage import PostgreSQLBackendStore, utc_now

_PBKDF2_ROUNDS = 200_000
_SESSION_TTL = timedelta(days=7)


class AuthError(Exception):
    """An auth operation failed (duplicate email, bad credentials, etc.)."""


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds_text, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        rounds = int(rounds_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(candidate, expected)


@dataclass(frozen=True)
class UserAccount:
    id: str
    email: str


def _normalize_email(email: str) -> str:
    return email.strip().lower() if isinstance(email, str) else ""


def _is_expired(expires_at: str) -> bool:
    try:
        return datetime.fromisoformat(expires_at.replace("Z", "+00:00")) < datetime.now(UTC)
    except (ValueError, AttributeError):
        return True


class AuthService:
    """User registration / login / session-token resolution backed by the store's DB.

    Reuses the store's connection + migrations (the `users` / `auth_sessions` tables from
    migration 003). Placeholder style is chosen by backend so the same SQL works on both.
    """

    def __init__(self, store: Any) -> None:
        self._store = store
        self._ph = "%s" if isinstance(store, PostgreSQLBackendStore) else "?"

    def _placeholders(self, count: int) -> str:
        return ", ".join([self._ph] * count)

    @staticmethod
    def _fetchone(cursor: Any, sql: str, params: tuple[Any, ...]) -> Any:
        cursor.execute(sql, params)
        return cursor.fetchone()

    def register(self, email: str, password: str) -> UserAccount:
        email = _normalize_email(email)
        if not email or not password:
            raise AuthError("email and password are required")
        user_id = str(uuid4())
        with self._store._connect() as connection:
            cursor = connection.cursor()
            existing = self._fetchone(
                cursor, f"SELECT id FROM users WHERE email = {self._ph}", (email,)
            )
            if existing is not None:
                raise AuthError("email already registered")
            cursor.execute(
                "INSERT INTO users (id, email, password_hash, created_at) "
                f"VALUES ({self._placeholders(4)})",
                (user_id, email, hash_password(password), utc_now()),
            )
        return UserAccount(id=user_id, email=email)

    def login(self, email: str, password: str) -> str:
        email = _normalize_email(email)
        with self._store._connect() as connection:
            cursor = connection.cursor()
            row = self._fetchone(
                cursor,
                f"SELECT id, password_hash FROM users WHERE email = {self._ph}",
                (email,),
            )
            if row is None or not verify_password(password, row["password_hash"]):
                raise AuthError("invalid email or password")
            token = secrets.token_urlsafe(32)
            expires_at = (datetime.now(UTC) + _SESSION_TTL).isoformat().replace("+00:00", "Z")
            cursor.execute(
                "INSERT INTO auth_sessions (token, user_id, expires_at, created_at) "
                f"VALUES ({self._placeholders(4)})",
                (token, row["id"], expires_at, utc_now()),
            )
        return token

    def resolve(self, token: str) -> AuthenticatedUser | None:
        if not token:
            return None
        with self._store._connect() as connection:
            row = self._fetchone(
                connection.cursor(),
                f"SELECT user_id, expires_at FROM auth_sessions WHERE token = {self._ph}",
                (token,),
            )
        if row is None:
            return None
        if _is_expired(row["expires_at"]):
            self.logout(token)
            return None
        return AuthenticatedUser(id=row["user_id"])

    def logout(self, token: str) -> None:
        if not token:
            return
        with self._store._connect() as connection:
            connection.cursor().execute(
                f"DELETE FROM auth_sessions WHERE token = {self._ph}", (token,)
            )

    def current(self, user_id: str) -> UserAccount | None:
        with self._store._connect() as connection:
            row = self._fetchone(
                connection.cursor(),
                f"SELECT id, email FROM users WHERE id = {self._ph}",
                (user_id,),
            )
        if row is None:
            return None
        return UserAccount(id=row["id"], email=row["email"])


def make_session_resolver(store: Any):
    """Return a SessionTokenResolver backed by issued auth_sessions."""
    return AuthService(store).resolve
