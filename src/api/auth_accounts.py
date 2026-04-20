from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from src.db.models import AuthAccount, StudentProfile
from src.db.repository import EventRepository


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000
DEFAULT_IMPORTED_ACCOUNT_PASSWORD = os.getenv(
    "AUTH_IMPORTED_ACCOUNT_INITIAL_PASSWORD",
    "Welcome@123",
).strip() or "Welcome@123"
BOOTSTRAP_DISABLED = str(os.getenv("RETENTIONOS_DISABLE_BOOTSTRAP_AUTH", "false")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_BOOTSTRAP_READY = False


@dataclass(frozen=True)
class BootstrapAccount:
    username: str
    password: str
    role: str
    student_id: int | None
    display_name: str
    institution_email: str | None = None
    must_reset_password: bool = False


BOOTSTRAP_ACCOUNTS = (
    BootstrapAccount(
        username="admin.retention",
        password="Admin@123",
        role="admin",
        student_id=None,
        display_name="Retention Admin",
        institution_email="admin@retentionos.local",
    ),
    BootstrapAccount(
        username="counsellor.vignan",
        password="Counsellor@123",
        role="counsellor",
        student_id=None,
        display_name="Vignan Counsellor",
        institution_email="counsellor@retentionos.local",
    ),
    BootstrapAccount(
        username="student.880001",
        password="Student@123",
        role="student",
        student_id=880001,
        display_name="Student 880001",
        institution_email="student880001@retentionos.local",
    ),
)


def _preferred_counsellor_username(*, counsellor_name: str | None, counsellor_email: str | None) -> str | None:
    email = str(counsellor_email or "").strip().lower()
    if email and "@" in email:
        local = email.split("@", 1)[0]
        if local:
            return normalize_username(local)
    name = str(counsellor_name or "").strip().lower()
    if not name:
        return None
    normalized = ".".join(part for part in re.split(r"[\s._-]+", name) if part)
    return normalize_username(normalized) if normalized else None


def normalize_username(value: str) -> str:
    return str(value or "").strip().lower()


def hash_password(password: str, *, salt: str | None = None) -> str:
    if not password:
        raise ValueError("Password cannot be empty.")
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_value.encode("utf-8"),
        PASSWORD_ITERATIONS,
    ).hex()
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${salt_value}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations, salt, digest = password_hash.split("$", 3)
    except ValueError:
        return False
    if scheme != PASSWORD_SCHEME:
        return False
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    ).hex()
    return hmac.compare_digest(derived, digest)


def ensure_bootstrap_accounts(repository: EventRepository) -> None:
    global _BOOTSTRAP_READY
    if _BOOTSTRAP_READY or BOOTSTRAP_DISABLED:
        return
    for account in BOOTSTRAP_ACCOUNTS:
        if repository.get_auth_account_by_username(account.username) is not None:
            continue
        try:
            repository.create_auth_account(
                {
                    "username": normalize_username(account.username),
                    "password_hash": hash_password(account.password),
                    "role": account.role,
                    "student_id": account.student_id,
                    "display_name": account.display_name,
                    "institution_email": account.institution_email,
                    "is_active": True,
                    "must_reset_password": account.must_reset_password,
                }
            )
        except IntegrityError:
            repository.db.rollback()
    _BOOTSTRAP_READY = True


def provision_student_auth_account(
    repository: EventRepository,
    *,
    profile: StudentProfile,
    initial_password: str | None = None,
    commit: bool = True,
) -> tuple[AuthAccount, bool]:
    AuthAccount.__table__.create(bind=repository.db.bind, checkfirst=True)
    preferred_username = normalize_username(
        str(getattr(profile, "external_student_ref", "") or "")
        or f"student.{int(profile.student_id)}"
    )
    existing = repository.get_auth_account_by_username(preferred_username)
    if existing is not None:
        return existing, False
    try:
        created = repository.create_auth_account(
            {
                "username": preferred_username,
                "password_hash": hash_password(initial_password or DEFAULT_IMPORTED_ACCOUNT_PASSWORD),
                "role": "student",
                "student_id": int(profile.student_id),
                "display_name": str(getattr(profile, "external_student_ref", "") or f"Student {int(profile.student_id)}"),
                "institution_email": getattr(profile, "student_email", None),
                "is_active": True,
                "must_reset_password": True,
            },
            commit=commit,
        )
        return created, True
    except IntegrityError:
        repository.db.rollback()
        existing = repository.get_auth_account_by_username(preferred_username)
        if existing is None:
            raise
        return existing, False


def provision_counsellor_auth_accounts(
    repository: EventRepository,
    *,
    profiles: list[StudentProfile],
    initial_password: str | None = None,
    commit: bool = True,
) -> int:
    AuthAccount.__table__.create(bind=repository.db.bind, checkfirst=True)
    created_count = 0
    seen_usernames: set[str] = set()
    for profile in profiles:
        counsellor_name = str(getattr(profile, "counsellor_name", "") or "").strip()
        counsellor_email = str(getattr(profile, "counsellor_email", "") or "").strip().lower()
        if not counsellor_name and not counsellor_email:
            continue
        preferred_username = _preferred_counsellor_username(
            counsellor_name=counsellor_name,
            counsellor_email=counsellor_email,
        )
        if not preferred_username or preferred_username in seen_usernames:
            continue
        seen_usernames.add(preferred_username)
        existing = repository.get_auth_account_by_username(preferred_username)
        if existing is not None:
            continue
        try:
            repository.create_auth_account(
                {
                    "username": preferred_username,
                    "password_hash": hash_password(initial_password or DEFAULT_IMPORTED_ACCOUNT_PASSWORD),
                    "role": "counsellor",
                    "student_id": None,
                    "display_name": counsellor_name or preferred_username,
                    "institution_email": counsellor_email or None,
                    "is_active": True,
                    "must_reset_password": True,
                },
                commit=commit,
            )
            created_count += 1
        except IntegrityError:
            repository.db.rollback()
    return created_count
