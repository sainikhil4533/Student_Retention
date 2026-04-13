from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles
from src.api.attendance_engine import build_attendance_summary
from src.api.operational_context import (
    build_activity_summary,
    build_milestone_flags,
    build_sla_summary,
)
from src.api.schemas import ActiveCasesResponse, StudentCaseStateResponse
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/cases", tags=["cases"])

FACULTY_HANDLING_STATUSES = {"seen", "acknowledged", "contacted", "support_provided"}


def _intervention_status(latest_intervention) -> str | None:
    if latest_intervention is None:
        return None
    return str(latest_intervention.action_status).strip().lower()


def _window_status(warning) -> str:
    if warning is None:
        return "no_warning"
    if warning.resolution_status is not None:
        return "resolved"

    deadline = warning.recovery_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return "expired" if deadline <= datetime.now(UTC) else "active"


def _is_current_case_resolved(latest_prediction, latest_intervention) -> bool:
    status = _intervention_status(latest_intervention)
    if status != "resolved" or latest_prediction is None or latest_intervention is None:
        return False

    prediction_time = latest_prediction.created_at
    intervention_time = latest_intervention.created_at
    if prediction_time is None or intervention_time is None:
        return False
    return intervention_time >= prediction_time


def _attendance_blocks_resolution(attendance_summary: dict) -> bool:
    attendance_ratio = attendance_summary.get("attendance_ratio")
    attendance_trend = attendance_summary.get("attendance_trend")
    consecutive_absences = attendance_summary.get("consecutive_absences")

    if attendance_ratio is not None and float(attendance_ratio) < 0.75:
        return True
    if attendance_trend is not None and float(attendance_trend) < -0.05:
        return True
    if consecutive_absences is not None and float(consecutive_absences) >= 3:
        return True
    return False


def _resolution_candidate_status(prediction, latest_intervention, warning, latest_alert, attendance_summary) -> bool:
    if prediction is None or int(prediction.final_predicted_class) != 0:
        return False
    if warning is None and latest_alert is None:
        return False
    if _attendance_blocks_resolution(attendance_summary):
        return False
    return not _is_current_case_resolved(prediction, latest_intervention)


def _is_reopened_case(prediction_history, intervention_history) -> bool:
    if not prediction_history:
        return False

    latest_prediction = prediction_history[0]
    if int(latest_prediction.final_predicted_class) != 1:
        return False

    resolution_times = sorted(
        row.created_at
        for row in intervention_history
        if str(row.action_status).strip().lower() == "resolved" and row.created_at is not None
    )
    if not resolution_times:
        return False

    ordered_predictions = list(reversed(prediction_history))
    previous_was_high = False
    for row in ordered_predictions:
        is_high = int(row.final_predicted_class) == 1
        if is_high and not previous_was_high:
            if any(resolution_time < row.created_at for resolution_time in resolution_times):
                return int(row.id) == int(latest_prediction.id)
        previous_was_high = is_high

    return False


def _latest_by_student(rows) -> dict[int, object]:
    latest: dict[int, object] = {}
    for row in rows:
        latest.setdefault(int(row.student_id), row)
    return latest


def _interventions_by_student(rows) -> dict[int, list]:
    grouped: dict[int, list] = {}
    for row in rows:
        grouped.setdefault(int(row.student_id), []).append(row)
    for student_id in grouped:
        grouped[student_id] = list(reversed(grouped[student_id]))
    return grouped


def _build_case_state_from_rows(
    student_id: int,
    profile,
    lms_events,
    latest_prediction,
    latest_erp_event,
    latest_finance_event,
    latest_warning,
    latest_alert,
    latest_guardian_alert,
    latest_intervention,
    prediction_history,
    intervention_history,
) -> StudentCaseStateResponse:
    risk_level = None
    final_risk_probability = None
    if latest_prediction is not None:
        risk_level = "HIGH" if int(latest_prediction.final_predicted_class) == 1 else "LOW"
        final_risk_probability = float(latest_prediction.final_risk_probability)

    latest_intervention_status = _intervention_status(latest_intervention)
    warning_window_status = _window_status(latest_warning)
    is_reopened_case = _is_reopened_case(prediction_history, intervention_history)
    attendance_summary = build_attendance_summary(
        getattr(latest_erp_event, "context_fields", None)
    )
    activity_summary = build_activity_summary(
        lms_events=lms_events,
        erp_event=latest_erp_event,
        finance_event=latest_finance_event,
    )
    milestone_flags = build_milestone_flags(
        profile=profile,
        erp_event=latest_erp_event,
        finance_event=latest_finance_event,
    )
    sla_summary = build_sla_summary(
        latest_prediction=latest_prediction,
        latest_warning=latest_warning,
        latest_alert=latest_alert,
        intervention_history=intervention_history,
    )
    candidate_for_resolution = _resolution_candidate_status(
        latest_prediction,
        latest_intervention,
        latest_warning,
        latest_alert,
        attendance_summary,
    )
    is_critical_unattended_case = (
        latest_prediction is not None
        and int(latest_prediction.final_predicted_class) == 1
        and latest_alert is not None
        and latest_alert.alert_type == "faculty_followup_reminder"
        and latest_intervention_status not in FACULTY_HANDLING_STATUSES.union({"resolved"})
    )

    current_case_state = "no_prediction"
    summary = "No prediction history exists for this student yet."

    if latest_prediction is None:
        pass
    elif _is_current_case_resolved(latest_prediction, latest_intervention):
        current_case_state = "resolved"
        summary = "Faculty has already marked the current case as resolved."
    elif is_critical_unattended_case:
        current_case_state = "critical_unattended_case"
        summary = "Student is still high risk even after escalation and follow-up reminder, with no faculty action logged."
    elif is_reopened_case:
        current_case_state = "reopened"
        summary = "Student is high risk again after a previously resolved case."
    elif candidate_for_resolution:
        current_case_state = "resolution_candidate"
        summary = "Student is now low risk after earlier intervention flow and appears ready for closure review."
    elif latest_prediction is not None and int(latest_prediction.final_predicted_class) == 0 and _attendance_blocks_resolution(attendance_summary):
        current_case_state = "attendance_followup_pending"
        summary = "Academic risk is lower, but attendance still needs follow-up before closure review."
    elif latest_intervention_status in FACULTY_HANDLING_STATUSES and risk_level == "HIGH":
        current_case_state = "faculty_handling_in_progress"
        summary = "Student is still high risk, but faculty follow-up is already in progress."
    elif latest_alert is not None and latest_alert.alert_type == "faculty_followup_reminder":
        current_case_state = "followup_reminder_sent"
        summary = "A follow-up reminder has been sent because escalation still had no recorded faculty action."
    elif latest_alert is not None and latest_alert.alert_type == "post_warning_escalation":
        current_case_state = "escalated"
        summary = "Student remained high risk after the recovery window and was escalated to faculty."
    elif latest_warning is not None and latest_warning.resolution_status is None and warning_window_status == "expired":
        current_case_state = "recovery_expired"
        summary = "Recovery deadline has passed and the case is awaiting escalation handling."
    elif latest_warning is not None and latest_warning.resolution_status is None and warning_window_status == "active":
        current_case_state = "recovery_active"
        summary = "Student is currently inside the recovery window after the initial warning."
    elif latest_prediction is not None and int(latest_prediction.final_predicted_class) == 1:
        current_case_state = "high_risk_active"
        summary = "Student is currently high risk."
    else:
        current_case_state = "low_risk_stable"
        summary = "Student is currently low risk and has no active intervention workflow."

    return StudentCaseStateResponse(
        student_id=student_id,
        current_case_state=current_case_state,
        risk_level=risk_level,
        final_risk_probability=final_risk_probability,
        latest_prediction_created_at=to_ist(
            latest_prediction.created_at if latest_prediction else None
        ),
        warning_status=latest_warning.delivery_status if latest_warning else None,
        warning_resolution_status=latest_warning.resolution_status if latest_warning else None,
        faculty_alert_type=latest_alert.alert_type if latest_alert else None,
        faculty_alert_status=latest_alert.email_status if latest_alert else None,
        guardian_alert_type=latest_guardian_alert.alert_type if latest_guardian_alert else None,
        guardian_alert_status=(
            latest_guardian_alert.delivery_status if latest_guardian_alert else None
        ),
        guardian_alert_channel=latest_guardian_alert.channel if latest_guardian_alert else None,
        guardian_alert_sent_at=to_ist(
            latest_guardian_alert.sent_at if latest_guardian_alert else None
        ),
        latest_intervention_status=latest_intervention.action_status if latest_intervention else None,
        candidate_for_resolution=candidate_for_resolution,
        is_reopened_case=is_reopened_case,
        is_critical_unattended_case=is_critical_unattended_case,
        last_meaningful_activity_at=to_ist(activity_summary["last_meaningful_activity_at"]),
        last_meaningful_activity_source=activity_summary["last_meaningful_activity_source"],
        active_milestone_flags=list(milestone_flags["active_flags"]),
        sla_status=str(sla_summary["sla_status"]),
        followup_overdue=bool(sla_summary["followup_overdue"]),
        summary=summary,
    )


def _build_case_state_response(student_id: int, repository: EventRepository) -> StudentCaseStateResponse:
    prediction_history = repository.get_prediction_history_for_student(student_id)
    latest_prediction = prediction_history[0] if prediction_history else None
    warning_history = repository.get_student_warning_history_for_student(student_id)
    latest_warning = warning_history[0] if warning_history else None
    alert_history = repository.get_alert_history_for_student(student_id)
    latest_alert = alert_history[0] if alert_history else None
    guardian_alert_history = repository.get_guardian_alert_history_for_student(student_id)
    latest_guardian_alert = guardian_alert_history[0] if guardian_alert_history else None
    intervention_history = repository.get_intervention_history_for_student(student_id)
    latest_intervention = intervention_history[0] if intervention_history else None

    return _build_case_state_from_rows(
        student_id=student_id,
        profile=repository.get_student_profile(student_id),
        lms_events=repository.get_lms_events_for_student(student_id),
        latest_prediction=latest_prediction,
        latest_erp_event=repository.get_latest_erp_event(student_id),
        latest_finance_event=repository.get_latest_finance_event(student_id),
        latest_warning=latest_warning,
        latest_alert=latest_alert,
        latest_guardian_alert=latest_guardian_alert,
        latest_intervention=latest_intervention,
        prediction_history=prediction_history,
        intervention_history=intervention_history,
    )


@router.get("/state/{student_id}", response_model=StudentCaseStateResponse)
def get_student_case_state(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> StudentCaseStateResponse:
    repository = EventRepository(db)
    history = repository.get_prediction_history_for_student(student_id)
    if not history:
        raise HTTPException(status_code=404, detail="No prediction history found for student.")
    return _build_case_state_response(student_id, repository)


@router.get("/active", response_model=ActiveCasesResponse)
def get_active_cases(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> ActiveCasesResponse:
    repository = EventRepository(db)
    latest_predictions = repository.get_latest_predictions_for_all_students()
    latest_prediction_map = {int(row.student_id): row for row in latest_predictions}
    warning_map = _latest_by_student(repository.get_all_student_warning_events())
    alert_map = _latest_by_student(repository.get_all_alert_events())
    guardian_alert_map = _latest_by_student(repository.get_all_guardian_alert_events())
    all_interventions = repository.get_all_intervention_actions()
    intervention_map = _latest_by_student(all_interventions)
    intervention_rows_by_student = _interventions_by_student(all_interventions)

    cases: list[StudentCaseStateResponse] = []
    active_states = {
        "critical_unattended_case",
        "reopened",
        "followup_reminder_sent",
        "escalated",
        "recovery_expired",
        "recovery_active",
        "faculty_handling_in_progress",
        "high_risk_active",
        "resolution_candidate",
        "attendance_followup_pending",
    }

    for student_id, latest_prediction in latest_prediction_map.items():
        case_state = _build_case_state_from_rows(
            student_id=student_id,
            profile=repository.get_student_profile(student_id),
            lms_events=repository.get_lms_events_for_student(student_id),
            latest_prediction=latest_prediction,
            latest_erp_event=repository.get_latest_erp_event(student_id),
            latest_finance_event=repository.get_latest_finance_event(student_id),
            latest_warning=warning_map.get(student_id),
            latest_alert=alert_map.get(student_id),
            latest_guardian_alert=guardian_alert_map.get(student_id),
            latest_intervention=intervention_map.get(student_id),
            prediction_history=repository.get_prediction_history_for_student(student_id),
            intervention_history=intervention_rows_by_student.get(student_id, []),
        )
        if case_state.current_case_state in active_states:
            cases.append(case_state)

    cases.sort(
        key=lambda item: (
            item.current_case_state == "critical_unattended_case",
            item.current_case_state == "reopened",
            item.current_case_state == "followup_reminder_sent",
            item.risk_level == "HIGH",
            item.final_risk_probability or 0.0,
            item.latest_prediction_created_at.isoformat()
            if item.latest_prediction_created_at
            else "",
        ),
        reverse=True,
    )

    return ActiveCasesResponse(total_students=len(cases), cases=cases)
