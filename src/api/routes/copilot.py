from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles
from src.api.copilot_intents import detect_copilot_intent
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_runtime import COPILOT_PHASE_LABEL, COPILOT_SYSTEM_PROMPT_VERSION
from src.api.copilot_semantic_planner import plan_copilot_query_with_semantic_assist
from src.api.copilot_tools import generate_grounded_copilot_answer
from src.api.schemas import (
    CopilotAuditEventItem,
    CopilotAuditListResponse,
    CopilotChatMessageItem,
    CopilotChatMessageRequest,
    CopilotChatReplyResponse,
    CopilotChatSessionCreateRequest,
    CopilotChatSessionItem,
    CopilotChatSessionListResponse,
    CopilotChatSessionResponse,
)
from src.db.database import SessionLocal, get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/copilot", tags=["copilot"])


@router.post("/sessions", response_model=CopilotChatSessionResponse)
def create_copilot_session(
    payload: CopilotChatSessionCreateRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("student", "counsellor", "admin", "system")),
) -> CopilotChatSessionResponse:
    repository = EventRepository(db)
    now = datetime.now(UTC)
    try:
        session = repository.create_copilot_chat_session(
            {
                "owner_subject": auth.subject,
                "owner_role": auth.role,
                "owner_student_id": auth.student_id,
                "display_name": auth.display_name,
                "title": _resolved_session_title(payload.title, auth.role),
                "status": "active",
                "system_prompt_version": COPILOT_SYSTEM_PROMPT_VERSION,
                "last_message_at": now,
            },
            commit=False,
        )
        assistant_message = repository.add_copilot_chat_message(
            {
                "session_id": int(session.id),
                "role": "assistant",
                "message_type": "text",
                "content": _opening_message_for_role(
                    role=auth.role,
                    display_name=auth.display_name,
                    opening_message=payload.opening_message,
                ),
                "metadata_json": {
                    "phase": COPILOT_PHASE_LABEL,
                    "response_mode": "foundation",
                },
            },
            commit=False,
        )
        repository.update_copilot_chat_session(
            int(session.id),
            {"last_message_at": assistant_message.created_at or now},
            commit=False,
            refresh=False,
        )
        db.commit()
        db.refresh(session)
        db.refresh(assistant_message)
    except Exception:
        db.rollback()
        raise
    return CopilotChatSessionResponse(
        session=_serialize_copilot_session(session),
        messages=[_serialize_copilot_message(assistant_message)],
    )


@router.get("/sessions", response_model=CopilotChatSessionListResponse)
def list_copilot_sessions(
    status_filter: str | None = Query(default=None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("student", "counsellor", "admin", "system")),
) -> CopilotChatSessionListResponse:
    repository = EventRepository(db)
    sessions = repository.list_copilot_chat_sessions_for_subject(auth.subject)
    if status_filter:
        sessions = [session for session in sessions if str(session.status) == status_filter]
    return CopilotChatSessionListResponse(
        total_sessions=len(sessions),
        sessions=[_serialize_copilot_session(session) for session in sessions],
    )


@router.get("/sessions/{session_id}", response_model=CopilotChatSessionResponse)
def get_copilot_session(
    session_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("student", "counsellor", "admin", "system")),
) -> CopilotChatSessionResponse:
    repository = EventRepository(db)
    session = _get_authorized_session(repository, session_id, auth)
    messages = repository.list_copilot_chat_messages(session_id)
    return CopilotChatSessionResponse(
        session=_serialize_copilot_session(session),
        messages=[_serialize_copilot_message(message) for message in messages],
    )


@router.get("/audit", response_model=CopilotAuditListResponse)
def list_copilot_audit_events(
    session_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> CopilotAuditListResponse:
    repository = EventRepository(db)
    events = repository.list_copilot_audit_events(session_id=session_id, limit=limit)
    return CopilotAuditListResponse(
        total_events=len(events),
        events=[_serialize_copilot_audit_event(row) for row in events],
    )


@router.post("/sessions/{session_id}/messages", response_model=CopilotChatReplyResponse)
def send_copilot_message(
    session_id: int,
    payload: CopilotChatMessageRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("student", "counsellor", "admin", "system")),
) -> CopilotChatReplyResponse:
    content = str(payload.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")

    with SessionLocal() as planner_db:
        planner_repository = EventRepository(planner_db)
        _get_authorized_session(planner_repository, session_id, auth)
        session_messages = planner_repository.list_copilot_chat_messages(session_id)
        if auth.role == "admin":
            profiles = planner_repository.get_imported_student_profiles()
        elif auth.role == "counsellor":
            profiles = planner_repository.get_imported_student_profiles_for_counsellor_identity(
                subject=auth.subject,
                display_name=auth.display_name,
            )
        else:
            profiles = []

    memory = resolve_copilot_memory_context(
        message=content,
        session_messages=session_messages,
    )
    query_plan, semantic_planner = plan_copilot_query_with_semantic_assist(
        role=auth.role,
        message=content,
        session_messages=session_messages,
        profiles=profiles,
    )

    repository = EventRepository(db)
    session = _get_authorized_session(repository, session_id, auth)
    grounded_answer, tools_used, limitations, memory_context = generate_grounded_copilot_answer(
        auth=auth,
        repository=repository,
        message=content,
        session_messages=session_messages,
        memory=memory,
        query_plan=query_plan.to_dict(),
    )
    detected_intent = detect_copilot_intent(role=auth.role, message=content)
    resolved_intent = str(memory_context.get("intent") or query_plan.primary_intent or detected_intent)
    memory_applied = bool(memory.get("is_follow_up")) or resolved_intent != detected_intent
    refusal_reason = _resolve_copilot_refusal_reason(resolved_intent, limitations)
    try:
        user_message = repository.add_copilot_chat_message(
            {
                "session_id": session_id,
                "role": "user",
                "message_type": "text",
                "content": content,
                "metadata_json": {
                    "owner_role": auth.role,
                    "owner_student_id": auth.student_id,
                    "memory_resolution": {
                        "is_follow_up": bool(memory.get("is_follow_up")),
                        "requested_outcome_status": memory.get("requested_outcome_status"),
                        "explicit_student_id": memory.get("explicit_student_id"),
                    },
                },
            },
            commit=False,
        )
        assistant_message = repository.add_copilot_chat_message(
            {
                "session_id": session_id,
                "role": "assistant",
                "message_type": "text",
                "content": grounded_answer,
                "metadata_json": {
                    "phase": COPILOT_PHASE_LABEL,
                    "response_mode": "grounded_tool_answer",
                    "detected_intent": detected_intent,
                    "resolved_intent": resolved_intent,
                    "memory_applied": memory_applied,
                    "query_plan": query_plan.to_dict(),
                    "semantic_planner": semantic_planner,
                    "planner_execution": {
                        "planner_version": query_plan.version,
                        "analysis_mode": query_plan.analysis_mode,
                        "orchestration_steps": list(query_plan.orchestration_steps),
                        "confidence": query_plan.confidence,
                        "notes": list(query_plan.notes),
                    },
                    "grounded_tools_used": tools_used,
                    "limitations": limitations,
                    "memory_context": memory_context,
                    "safety_marker": {
                        "role_scope": auth.role,
                        "refusal_reason": refusal_reason,
                    },
                },
            },
            commit=False,
        )
        repository.add_copilot_audit_event(
            {
                "session_id": session_id,
                "message_id": int(assistant_message.id),
                "owner_subject": auth.subject,
                "owner_role": auth.role,
                "owner_student_id": auth.student_id,
                "detected_intent": detected_intent,
                "resolved_intent": resolved_intent,
                "memory_applied": memory_applied,
                "tool_summaries": tools_used,
                "refusal_reason": refusal_reason,
            },
            commit=False,
        )
        session.last_message_at = assistant_message.created_at or datetime.now(UTC)
        session.updated_at = assistant_message.created_at or datetime.now(UTC)
        db.commit()
        db.refresh(session)
        db.refresh(user_message)
        db.refresh(assistant_message)
    except Exception:
        db.rollback()
        raise
    return CopilotChatReplyResponse(
        session=_serialize_copilot_session(session),
        user_message=_serialize_copilot_message(user_message),
        assistant_message=_serialize_copilot_message(assistant_message),
    )


def _get_authorized_session(
    repository: EventRepository,
    session_id: int,
    auth: AuthContext,
):
    session = repository.get_copilot_chat_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Copilot session not found.")
    if str(session.owner_subject) != auth.subject:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access this copilot session.",
        )
    return session


def _resolved_session_title(title: str | None, role: str) -> str:
    parsed = str(title or "").strip()
    if parsed:
        return parsed[:255]
    return f"{role.title()} copilot chat"


def _opening_message_for_role(
    *,
    role: str,
    display_name: str | None,
    opening_message: str | None,
) -> str:
    if opening_message:
        return str(opening_message).strip()
    name = display_name or "there"
    if role == "student":
        return (
            f"Hello {name}. I am your RetainAI Copilot foundation. "
            "In the next phases I will answer grounded questions about your own risk, "
            "warnings, recovery plan, attendance, and support guidance. "
            "Right now this session is ready for safe role-aware chat storage and initial guidance."
        )
    if role == "counsellor":
        return (
            f"Hello {name}. I am your RetainAI Copilot foundation. "
            "In the next phases I will help with assigned-student drilldowns, cohort summaries, "
            "and follow-up prioritization while respecting role boundaries."
        )
    return (
        f"Hello {name}. I am your RetainAI Copilot foundation. "
        "In the next phases I will support institution analytics, cohort drilldowns, "
        "and governance questions with grounded backend data."
    )


def _serialize_copilot_session(session) -> CopilotChatSessionItem:
    return CopilotChatSessionItem(
        id=int(session.id),
        title=str(session.title),
        status=str(session.status),
        owner_role=str(session.owner_role),
        owner_student_id=(
            int(session.owner_student_id) if session.owner_student_id is not None else None
        ),
        display_name=str(session.display_name) if session.display_name is not None else None,
        system_prompt_version=str(session.system_prompt_version),
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_message_at=session.last_message_at,
    )


def _serialize_copilot_message(message) -> CopilotChatMessageItem:
    return CopilotChatMessageItem(
        id=int(message.id),
        session_id=int(message.session_id),
        role=str(message.role),
        message_type=str(message.message_type),
        content=str(message.content),
        metadata_json=message.metadata_json,
        created_at=message.created_at,
    )


def _serialize_copilot_audit_event(row) -> CopilotAuditEventItem:
    return CopilotAuditEventItem(
        id=int(row.id),
        session_id=int(row.session_id),
        message_id=int(row.message_id) if row.message_id is not None else None,
        owner_subject=str(row.owner_subject),
        owner_role=str(row.owner_role),
        owner_student_id=int(row.owner_student_id) if row.owner_student_id is not None else None,
        detected_intent=str(row.detected_intent) if row.detected_intent is not None else None,
        resolved_intent=str(row.resolved_intent) if row.resolved_intent is not None else None,
        memory_applied=bool(row.memory_applied),
        tool_summaries=row.tool_summaries,
        refusal_reason=str(row.refusal_reason) if row.refusal_reason is not None else None,
        created_at=row.created_at,
    )


def _resolve_copilot_refusal_reason(resolved_intent: str, limitations: list[str]) -> str | None:
    if resolved_intent == "planner_refusal":
        return "sensitive_request"
    if "unsupported" in resolved_intent:
        return "unsupported_request"
    if any("outside the current routed intent set" in item for item in limitations):
        return "unsupported_request"
    if any("not authorized" in item for item in limitations):
        return "role_scope_violation"
    return None
