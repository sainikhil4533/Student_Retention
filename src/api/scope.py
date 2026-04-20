from __future__ import annotations

from fastapi import HTTPException, status

from src.api.auth import AuthContext
from src.db.repository import EventRepository


def get_counsellor_scope_student_ids(
    *,
    auth: AuthContext,
    repository: EventRepository,
) -> set[int] | None:
    if auth.role != "counsellor":
        return None
    profiles = repository.get_imported_student_profiles_for_counsellor_identity(
        subject=auth.subject,
        display_name=auth.display_name,
    )
    return {int(profile.student_id) for profile in profiles}


def ensure_student_scope_access(
    *,
    auth: AuthContext,
    repository: EventRepository,
    student_id: int,
) -> None:
    if auth.role in {"admin", "system"}:
        return
    if auth.role == "student" and auth.student_id == student_id:
        return
    if auth.role == "counsellor":
        scoped_ids = get_counsellor_scope_student_ids(auth=auth, repository=repository)
        if student_id in (scoped_ids or set()):
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this student resource.",
    )
