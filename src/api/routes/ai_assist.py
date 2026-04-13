from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles, require_same_student_or_roles
from src.ai.assistant_service import (
    generate_case_summary,
    generate_communication_draft,
    generate_guardian_communication_draft,
    generate_recovery_plan,
)
from src.api.ai_assistance_context import build_live_case_context
from src.api.schemas import (
    AICaseSummaryResponse,
    AICommunicationDraftResponse,
    AIGuardianCommunicationDraftResponse,
    AIRecoveryPlanResponse,
)
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/ai-assist", tags=["ai-assist"])


def _get_required_case_context(student_id: int, repository: EventRepository) -> dict:
    case_context = build_live_case_context(repository=repository, student_id=student_id)
    if case_context.get("profile") is None:
        raise HTTPException(status_code=404, detail="Student profile not found.")
    if case_context.get("latest_prediction") is None:
        raise HTTPException(status_code=404, detail="No prediction history found for student.")
    if case_context.get("intelligence") is None:
        raise HTTPException(
            status_code=404,
            detail="Current AI assistance needs LMS and ERP data for this student.",
        )
    return case_context


@router.get("/case-summary/{student_id}", response_model=AICaseSummaryResponse)
def get_ai_case_summary(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> AICaseSummaryResponse:
    repository = EventRepository(db)
    result = generate_case_summary(_get_required_case_context(student_id, repository))
    return AICaseSummaryResponse(**result)


@router.get("/communication-draft/{student_id}", response_model=AICommunicationDraftResponse)
def get_ai_communication_draft(
    student_id: int,
    audience: str = Query(default="faculty", pattern="^(faculty|student|parent)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_same_student_or_roles("counsellor", "admin", "system")),
) -> AICommunicationDraftResponse:
    repository = EventRepository(db)
    result = generate_communication_draft(
        _get_required_case_context(student_id, repository),
        audience=audience,
    )
    return AICommunicationDraftResponse(**result)


@router.get("/guardian-draft/{student_id}", response_model=AIGuardianCommunicationDraftResponse)
def get_ai_guardian_communication_draft(
    student_id: int,
    channel: str = Query(default="whatsapp", pattern="^(email|sms|whatsapp)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> AIGuardianCommunicationDraftResponse:
    repository = EventRepository(db)
    result = generate_guardian_communication_draft(
        _get_required_case_context(student_id, repository),
        channel=channel,
    )
    return AIGuardianCommunicationDraftResponse(**result)


@router.get("/recovery-plan/{student_id}", response_model=AIRecoveryPlanResponse)
def get_ai_recovery_plan(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_same_student_or_roles("counsellor", "admin", "system")),
) -> AIRecoveryPlanResponse:
    repository = EventRepository(db)
    result = generate_recovery_plan(_get_required_case_context(student_id, repository))
    return AIRecoveryPlanResponse(**result)
