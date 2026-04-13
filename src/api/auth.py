from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import requests


load_dotenv()

RoleName = Literal["student", "counsellor", "admin", "system"]

AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "student-retention-dev-secret").strip()
AUTH_TOKEN_EXPIRE_HOURS = int(os.getenv("AUTH_TOKEN_EXPIRE_HOURS", "12"))
JWT_ALGORITHM = "HS256"
SUPABASE_AUTH_ENABLED = os.getenv("SUPABASE_AUTH_ENABLED", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
SUPABASE_AUTH_TIMEOUT_SECONDS = float(os.getenv("SUPABASE_AUTH_TIMEOUT_SECONDS", "10"))
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    role: RoleName
    subject: str
    student_id: int | None = None
    display_name: str | None = None
    auth_provider: str | None = None


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(message: str) -> str:
    digest = hmac.new(
        AUTH_SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64url_encode(digest)


def create_access_token(
    *,
    role: RoleName,
    subject: str,
    student_id: int | None = None,
    display_name: str | None = None,
    expires_in_hours: int | None = None,
) -> str:
    expires_at = datetime.now(UTC) + timedelta(
        hours=expires_in_hours or AUTH_TOKEN_EXPIRE_HOURS
    )
    header = {
        "alg": JWT_ALGORITHM,
        "typ": "JWT",
    }
    payload = {
        "sub": subject,
        "role": role,
        "student_id": student_id,
        "display_name": display_name,
        "exp": expires_at.isoformat(),
    }
    encoded_header = _b64url_encode(
        json.dumps(header, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )
    encoded_payload = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = _sign(signing_input)
    return f"{encoded_header}.{encoded_payload}.{signature}"


def decode_access_token(token: str) -> AuthContext:
    try:
        encoded_header, encoded_payload, provided_signature = token.split(".", 2)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT format.",
        ) from error

    signing_input = f"{encoded_header}.{encoded_payload}"
    expected_signature = _sign(signing_input)
    if not hmac.compare_digest(provided_signature, expected_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT signature.",
        )

    try:
        header = json.loads(_b64url_decode(encoded_header).decode("utf-8"))
        payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
        expires_at = datetime.fromisoformat(str(payload["exp"]))
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT payload.",
        ) from error

    if header.get("typ") != "JWT" or header.get("alg") != JWT_ALGORITHM:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unsupported JWT header.",
        )

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT token has expired.",
        )

    role = str(payload.get("role") or "").strip().lower()
    if role not in {"student", "counsellor", "admin", "system"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT role is invalid.",
        )

    student_id = payload.get("student_id")
    return AuthContext(
        role=role,  # type: ignore[arg-type]
        subject=str(payload.get("sub") or ""),
        student_id=int(student_id) if student_id not in (None, "") else None,
        display_name=(
            str(payload.get("display_name"))
            if payload.get("display_name") not in (None, "")
            else None
        ),
        auth_provider="local_jwt",
    )


def _is_supabase_auth_configured() -> bool:
    return bool(SUPABASE_AUTH_ENABLED and _resolve_supabase_url() and SUPABASE_PUBLISHABLE_KEY)


def _resolve_supabase_url() -> str:
    if SUPABASE_URL:
        normalized = SUPABASE_URL
        if normalized.startswith("SUPABASE_URL="):
            normalized = normalized.split("=", 1)[1].strip()
        return normalized

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return ""

    parsed = urlparse(database_url)
    username = parsed.username or ""
    if username.startswith("postgres."):
        project_ref = username.split(".", 1)[1]
        if project_ref:
            return f"https://{project_ref}.supabase.co"
    return ""


def _extract_role_from_supabase_user(user_payload: dict) -> RoleName:
    app_metadata = user_payload.get("app_metadata") or {}
    user_metadata = user_payload.get("user_metadata") or {}
    role = (
        app_metadata.get("role")
        or user_metadata.get("role")
        or "student"
    )
    role = str(role).strip().lower()
    if role not in {"student", "counsellor", "admin", "system"}:
        return "student"
    return role  # type: ignore[return-value]


def _extract_student_id_from_supabase_user(user_payload: dict) -> int | None:
    app_metadata = user_payload.get("app_metadata") or {}
    user_metadata = user_payload.get("user_metadata") or {}
    for value in (
        app_metadata.get("student_id"),
        user_metadata.get("student_id"),
    ):
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def verify_supabase_access_token(token: str) -> AuthContext:
    if not _is_supabase_auth_configured():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Supabase Auth verification is not configured.",
        )

    try:
        response = requests.get(
            f"{_resolve_supabase_url().rstrip('/')}/auth/v1/user",
            headers={
                "apikey": SUPABASE_PUBLISHABLE_KEY,
                "Authorization": f"Bearer {token}",
            },
            timeout=SUPABASE_AUTH_TIMEOUT_SECONDS,
        )
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase Auth verification failed due to network error.",
        ) from error

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Supabase access token is invalid.",
        )

    user_payload = response.json()
    return AuthContext(
        role=_extract_role_from_supabase_user(user_payload),
        subject=str(user_payload.get("id") or user_payload.get("email") or "supabase_user"),
        student_id=_extract_student_id_from_supabase_user(user_payload),
        display_name=(
            str(
                (user_payload.get("user_metadata") or {}).get("display_name")
                or user_payload.get("email")
                or user_payload.get("id")
            )
        ),
        auth_provider="supabase_auth",
    )


def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthContext:
    if not AUTH_ENABLED:
        return AuthContext(role="admin", subject="auth_disabled", display_name="Auth Disabled")

    if credentials is None or str(credentials.scheme).lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    token = str(credentials.credentials or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    try:
        return decode_access_token(token)
    except HTTPException as local_error:
        if not _is_supabase_auth_configured():
            raise local_error
    return verify_supabase_access_token(token)


def require_roles(*roles: RoleName):
    def dependency(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if auth.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource.",
            )
        return auth

    return dependency


def require_same_student_or_roles(*roles: RoleName):
    def dependency(
        student_id: int,
        auth: AuthContext = Depends(get_auth_context),
    ) -> AuthContext:
        if auth.role in roles:
            return auth
        if auth.role == "student" and auth.student_id == student_id:
            return auth
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this student resource.",
        )

    return dependency
