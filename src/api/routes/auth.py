from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.auth import AUTH_ENABLED, AuthContext, create_access_token, get_auth_context
from src.api.auth_accounts import (
    BOOTSTRAP_ACCOUNTS,
    DEFAULT_IMPORTED_ACCOUNT_PASSWORD,
    ensure_bootstrap_accounts,
    hash_password,
    normalize_username,
    verify_password,
)
from src.api.schemas import (
    AuthLoginRequest,
    AuthMeResponse,
    AuthResetPasswordRequest,
    AuthResetPasswordResponse,
    AuthTokenResponse,
)
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/auth", tags=["auth"])


def _fallback_token_response(
    *,
    username: str,
    role: str,
    student_id: int | None,
    display_name: str | None,
) -> AuthTokenResponse:
    token = create_access_token(
        role=role,
        subject=username,
        student_id=student_id,
        display_name=display_name,
    )
    return AuthTokenResponse(
        access_token=token,
        token_type="bearer",
        subject=username,
        username=username,
        role=role,
        student_id=student_id,
        display_name=display_name,
        auth_provider="local_fallback_account",
        password_reset_required=False,
    )


def _local_login_fallback(payload: AuthLoginRequest) -> AuthTokenResponse | None:
    username = normalize_username(payload.username)
    password = str(payload.password or "")

    for account in BOOTSTRAP_ACCOUNTS:
        if username == normalize_username(account.username) and password == account.password:
            return _fallback_token_response(
                username=username,
                role=account.role,
                student_id=account.student_id,
                display_name=account.display_name,
            )

    if password == DEFAULT_IMPORTED_ACCOUNT_PASSWORD and username.endswith(".counsellor"):
        display_name = " ".join(part.capitalize() for part in username.replace(".counsellor", "").split(".") if part).strip()
        return _fallback_token_response(
            username=username,
            role="counsellor",
            student_id=None,
            display_name=f"Counsellor {display_name}" if display_name else "Counsellor",
        )

    if password == DEFAULT_IMPORTED_ACCOUNT_PASSWORD and username.startswith("student."):
        student_tail = username.split(".", 1)[1].strip()
        student_id = int(student_tail) if student_tail.isdigit() else None
        return _fallback_token_response(
            username=username,
            role="student",
            student_id=student_id,
            display_name=f"Student {student_id}" if student_id is not None else "Student",
        )

    return None


@router.post("/login", response_model=AuthTokenResponse)
def login(
    payload: AuthLoginRequest,
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    if not AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="Auth is disabled in this environment.")

    fallback = _local_login_fallback(payload)
    if fallback is not None:
        return fallback

    repository = EventRepository(db)
    ensure_bootstrap_accounts(repository)

    username = str(payload.username or "").strip().lower()
    account = repository.get_auth_account_by_username(username)
    if account is None or not account.is_active:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    if not verify_password(payload.password, str(account.password_hash)):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    token = create_access_token(
        role=str(account.role),  # type: ignore[arg-type]
        subject=str(account.username),
        student_id=account.student_id,
        display_name=account.display_name,
    )
    return AuthTokenResponse(
        access_token=token,
        token_type="bearer",
        subject=str(account.username),
        username=str(account.username),
        role=str(account.role),
        student_id=account.student_id,
        display_name=account.display_name,
        auth_provider="local_institution_account",
        password_reset_required=bool(account.must_reset_password),
    )


@router.get("/me", response_model=AuthMeResponse)
def get_current_user(auth: AuthContext = Depends(get_auth_context)) -> AuthMeResponse:
    return AuthMeResponse(
        role=auth.role,
        subject=auth.subject,
        username=auth.subject if auth.auth_provider == "local_institution_account" else None,
        student_id=auth.student_id,
        display_name=auth.display_name,
        auth_provider=auth.auth_provider,
    )


@router.post("/reset-password", response_model=AuthResetPasswordResponse)
def reset_password(
    payload: AuthResetPasswordRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> AuthResetPasswordResponse:
    repository = EventRepository(db)
    account = repository.get_auth_account_by_username(auth.subject)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found for the authenticated user.")
    if not account.is_active:
        raise HTTPException(status_code=403, detail="This account is inactive.")
    if len(str(payload.new_password or "")) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters long.")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="Choose a new password that is different from the current password.")
    if not verify_password(payload.current_password, str(account.password_hash)):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    repository.update_auth_account(
        int(account.id),
        {
            "password_hash": hash_password(payload.new_password),
            "must_reset_password": False,
        },
    )
    return AuthResetPasswordResponse(
        status="updated",
        message="Password updated successfully. You can continue into your dashboard.",
        password_reset_required=False,
    )
