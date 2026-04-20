from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles
from src.api.scope import ensure_student_scope_access
from src.api.attendance_engine import build_attendance_summary
from src.api.schemas import RecoveryScorecardResponse
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/recovery", tags=["recovery"])


def _risk_level_from_prediction(prediction) -> str | None:
    if prediction is None:
        return None
    return "HIGH" if int(prediction.final_predicted_class) == 1 else "LOW"


def _window_status(warning) -> str:
    if warning is None:
        return "no_warning"
    if warning.resolution_status is not None:
        return "resolved"

    now_utc = datetime.now(UTC)
    deadline = warning.recovery_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)

    return "active" if deadline > now_utc else "expired"


def _improvement_status(baseline_prediction, latest_prediction, warning) -> str:
    if warning is None or baseline_prediction is None or latest_prediction is None:
        return "unavailable"

    if warning.resolution_status == "recovered":
        return "recovered"
    if warning.resolution_status == "escalated_to_faculty":
        return "escalated"

    baseline_prob = float(baseline_prediction.final_risk_probability)
    latest_prob = float(latest_prediction.final_risk_probability)
    latest_class = int(latest_prediction.final_predicted_class)

    if latest_class == 0:
        return "recovered"
    if latest_prob < baseline_prob:
        return "improving"
    if latest_prob > baseline_prob:
        return "worsening"
    return "unchanged"


def _attendance_recovery_status(attendance_summary: dict) -> str:
    if not attendance_summary:
        return "unavailable"

    attendance_ratio = attendance_summary.get("attendance_ratio")
    attendance_trend = attendance_summary.get("attendance_trend")
    consecutive_absences = attendance_summary.get("consecutive_absences")
    low_attendance_subjects = attendance_summary.get("low_attendance_subjects") or []

    if attendance_ratio is None and attendance_trend is None and consecutive_absences is None and not low_attendance_subjects:
        return "unavailable"
    if attendance_ratio is not None and float(attendance_ratio) < 0.5:
        return "critical"
    if consecutive_absences is not None and float(consecutive_absences) >= 3:
        return "critical"
    if attendance_ratio is not None and float(attendance_ratio) < 0.75:
        return "needs_attention"
    if attendance_trend is not None and float(attendance_trend) < -0.05:
        return "needs_attention"
    if low_attendance_subjects:
        return "subject_concern"
    return "stable"


def _resolution_candidate_status(
    latest_prediction,
    latest_intervention,
    warning,
    latest_alert,
    attendance_summary,
) -> tuple[bool, str | None]:
    if latest_prediction is None:
        return False, None
    if int(latest_prediction.final_predicted_class) != 0:
        return False, None
    if warning is None and latest_alert is None:
        return False, None

    attendance_recovery_status = _attendance_recovery_status(attendance_summary)
    if attendance_recovery_status in {"critical", "needs_attention"}:
        attendance_ratio = attendance_summary.get("attendance_ratio")
        if attendance_ratio is not None:
            return (
                False,
                f"Academic risk is lower, but attendance still needs improvement (current ratio {float(attendance_ratio):.2f}).",
            )
        return False, "Academic risk is lower, but attendance still needs improvement before closure review."

    if latest_intervention is not None:
        action_status = str(latest_intervention.action_status).strip().lower()
        intervention_time = latest_intervention.created_at
        prediction_time = latest_prediction.created_at
        if (
            action_status == "resolved"
            and intervention_time is not None
            and prediction_time is not None
            and intervention_time >= prediction_time
        ):
            return False, None

    if latest_alert is not None and latest_alert.alert_type == "faculty_followup_reminder":
        return True, "Student is now low risk after an escalated case that required faculty reminder follow-up."
    if latest_alert is not None and latest_alert.alert_type == "post_warning_escalation":
        return True, "Student is now low risk after faculty escalation and appears ready for closure review."
    if warning is not None:
        return True, "Student is now low risk after a warning cycle and appears ready for closure review."

    return False, None


@router.get("/scorecard/{student_id}", response_model=RecoveryScorecardResponse)
def get_recovery_scorecard(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> RecoveryScorecardResponse:
    repository = EventRepository(db)
    ensure_student_scope_access(auth=auth, repository=repository, student_id=student_id)
    warning_rows = repository.get_student_warning_history_for_student(student_id)
    latest_prediction = repository.get_latest_prediction_for_student(student_id)
    alert_rows = repository.get_alert_history_for_student(student_id)
    latest_intervention = repository.get_latest_intervention_for_student(student_id)

    if not warning_rows:
        raise HTTPException(
            status_code=404,
            detail="No student warning history found for student.",
        )

    warning = warning_rows[0]
    baseline_prediction = repository.get_prediction_history_by_id(warning.prediction_history_id)
    latest_alert = alert_rows[0] if alert_rows else None
    attendance_summary = (
        build_attendance_summary(getattr(repository.get_latest_erp_event(student_id), "context_fields", None))
        if latest_prediction is not None
        else {}
    )

    baseline_probability = (
        float(baseline_prediction.final_risk_probability)
        if baseline_prediction is not None
        else None
    )
    current_probability = (
        float(latest_prediction.final_risk_probability)
        if latest_prediction is not None
        else None
    )
    probability_change = (
        current_probability - baseline_probability
        if baseline_probability is not None and current_probability is not None
        else None
    )

    improvement_status = _improvement_status(
        baseline_prediction=baseline_prediction,
        latest_prediction=latest_prediction,
        warning=warning,
    )
    recovery_window_status = _window_status(warning)
    candidate_for_resolution, resolution_candidate_reason = _resolution_candidate_status(
        latest_prediction=latest_prediction,
        latest_intervention=latest_intervention,
        warning=warning,
        latest_alert=latest_alert,
        attendance_summary=attendance_summary,
    )
    attendance_recovery_status = _attendance_recovery_status(attendance_summary)

    if improvement_status == "recovered":
        summary = "Student has recovered from the warning baseline and is no longer in the same high-risk state."
    elif improvement_status == "improving":
        summary = "Student is still under recovery tracking, but the latest score indicates improvement compared with the warning baseline."
    elif improvement_status == "worsening":
        summary = "Student remains under recovery tracking and risk has worsened compared with the warning baseline."
    elif improvement_status == "escalated":
        summary = "Recovery window ended without sufficient improvement and the case has been escalated to faculty."
    else:
        summary = "Recovery tracking is active, but no significant change is visible yet."

    if attendance_summary.get("attendance_flag"):
        attendance_ratio = attendance_summary.get("attendance_ratio")
        if attendance_ratio is not None:
            summary = (
                f"{summary} Attendance also needs attention because the latest ratio is "
                f"{float(attendance_ratio):.2f}."
            )
        else:
            summary = f"{summary} Attendance also shows a concern in the latest ERP context."
    elif attendance_recovery_status == "stable":
        summary = f"{summary} Attendance currently looks stable."

    if latest_intervention is not None:
        summary = (
            f"{summary} Latest faculty intervention status is "
            f"'{latest_intervention.action_status}'."
        )
    if candidate_for_resolution and resolution_candidate_reason:
        summary = f"{summary} Resolution suggestion: {resolution_candidate_reason}"

    return RecoveryScorecardResponse(
        student_id=student_id,
        warning_event_id=warning.id,
        warning_type=warning.warning_type,
        warning_sent_at=to_ist(warning.sent_at),
        recovery_deadline=to_ist(warning.recovery_deadline),
        recovery_window_status=recovery_window_status,
        resolution_status=warning.resolution_status,
        student_warning_status=warning.delivery_status,
        faculty_alert_status=latest_alert.email_status if latest_alert else None,
        faculty_alert_type=latest_alert.alert_type if latest_alert else None,
        latest_intervention_status=(
            latest_intervention.action_status if latest_intervention else None
        ),
        latest_intervention_actor=(
            latest_intervention.actor_name if latest_intervention else None
        ),
        latest_intervention_notes=latest_intervention.notes if latest_intervention else None,
        latest_intervention_created_at=to_ist(
            latest_intervention.created_at if latest_intervention else None
        ),
        baseline_risk_level=_risk_level_from_prediction(baseline_prediction),
        current_risk_level=_risk_level_from_prediction(latest_prediction),
        baseline_final_risk_probability=baseline_probability,
        current_final_risk_probability=current_probability,
        risk_probability_change=probability_change,
        improvement_status=improvement_status,
        attendance_recovery_status=attendance_recovery_status,
        current_attendance_ratio=attendance_summary.get("attendance_ratio"),
        current_attendance_trend=attendance_summary.get("attendance_trend"),
        consecutive_absences=attendance_summary.get("consecutive_absences"),
        low_attendance_subjects=list(attendance_summary.get("low_attendance_subjects") or []),
        candidate_for_resolution=candidate_for_resolution,
        resolution_candidate_reason=resolution_candidate_reason,
        latest_prediction_created_at=to_ist(
            latest_prediction.created_at if latest_prediction else None
        ),
        summary=summary,
    )
