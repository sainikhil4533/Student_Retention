from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles
from src.api.attendance_engine import build_attendance_summary
from src.api.operational_context import (
    build_activity_summary,
    build_milestone_flags,
    build_sla_summary,
)
from src.api.schemas import (
    FacultyPriorityQueueItem,
    FacultyPriorityQueueResponse,
    FacultySummaryResponse,
    FacultySummaryStudentItem,
)
from src.api.student_intelligence import build_current_student_intelligence
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/faculty", tags=["faculty"])


def _latest_by_student(rows) -> dict[int, object]:
    latest: dict[int, object] = {}
    for row in rows:
        latest.setdefault(int(row.student_id), row)
    return latest


def _repeat_high_risk_count(prediction_rows) -> dict[int, int]:
    counts: dict[int, int] = {}
    for row in prediction_rows:
        if int(row.final_predicted_class) == 1:
            counts[int(row.student_id)] = counts.get(int(row.student_id), 0) + 1
        else:
            counts.setdefault(int(row.student_id), counts.get(int(row.student_id), 0))
    return counts


def _interventions_by_student(rows) -> dict[int, list]:
    grouped: dict[int, list] = {}
    for row in rows:
        grouped.setdefault(int(row.student_id), []).append(row)
    for student_id in grouped:
        grouped[student_id] = list(reversed(grouped[student_id]))
    return grouped


def _repeated_risk_summary(prediction_rows, intervention_rows_by_student: dict[int, list]) -> dict[int, dict]:
    grouped: dict[int, list] = {}
    for row in reversed(prediction_rows):
        grouped.setdefault(int(row.student_id), []).append(row)

    summary: dict[int, dict] = {}
    for student_id, rows in grouped.items():
        intervention_rows = intervention_rows_by_student.get(student_id, [])
        resolution_times = sorted(
            row.created_at
            for row in intervention_rows
            if str(row.action_status).strip().lower() == "resolved" and row.created_at is not None
        )
        high_risk_prediction_count = sum(
            1 for row in rows if int(row.final_predicted_class) == 1
        )
        high_risk_cycle_count = 0
        previous_was_high = False
        has_relapsed_after_recovery = False
        has_relapsed_after_resolution = False
        has_seen_recovery = False

        for row in rows:
            is_high = int(row.final_predicted_class) == 1
            if is_high and not previous_was_high:
                high_risk_cycle_count += 1
                if has_seen_recovery:
                    has_relapsed_after_recovery = True
                if any(resolution_time < row.created_at for resolution_time in resolution_times):
                    has_relapsed_after_resolution = True
            if not is_high:
                has_seen_recovery = True
            previous_was_high = is_high

        latest_row = rows[-1]
        is_reopened_case = int(latest_row.final_predicted_class) == 1 and has_relapsed_after_resolution

        summary[student_id] = {
            "repeat_high_risk_count": high_risk_prediction_count,
            "high_risk_cycle_count": high_risk_cycle_count,
            "has_relapsed_after_recovery": has_relapsed_after_recovery,
            "has_relapsed_after_resolution": has_relapsed_after_resolution,
            "is_repeated_risk_case": (
                high_risk_cycle_count >= 2 or high_risk_prediction_count >= 2
            ),
            "is_reopened_case": is_reopened_case,
        }

    return summary


def _window_status(warning) -> str:
    if warning is None:
        return "no_warning"
    if warning.resolution_status is not None:
        return "resolved"

    now_utc = datetime.now(UTC)
    deadline = warning.recovery_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return "expired" if deadline <= now_utc else "active"


def _intervention_status(latest_intervention) -> str | None:
    if latest_intervention is None:
        return None
    return str(latest_intervention.action_status).strip().lower()


def _is_current_case_resolved(latest_prediction, latest_intervention) -> bool:
    status = _intervention_status(latest_intervention)
    if status != "resolved" or latest_prediction is None or latest_intervention is None:
        return False

    intervention_time = latest_intervention.created_at
    prediction_time = latest_prediction.created_at
    if intervention_time is None or prediction_time is None:
        return False

    return intervention_time >= prediction_time


def _priority_for_student(
    latest_prediction,
    warning,
    latest_alert,
    latest_intervention,
    repeat_high_count: int,
    high_risk_cycle_count: int,
    has_relapsed_after_recovery: bool,
    has_relapsed_after_resolution: bool,
    is_critical_unattended_case: bool,
) -> tuple[int, str, str]:
    probability = float(latest_prediction.final_risk_probability)
    window_status = _window_status(warning)
    intervention_status = _intervention_status(latest_intervention)

    score = 0
    label = "LOW"
    reason = "Monitoring only."

    if is_critical_unattended_case:
        score = 100
        label = "CRITICAL"
        reason = (
            "Faculty escalation and follow-up reminder were both sent, but no faculty action "
            "has been logged and the student is still high risk."
        )
    elif latest_alert is not None and latest_alert.alert_type == "post_warning_escalation":
        score = 90
        label = "CRITICAL"
        reason = "Faculty escalation has already been triggered and requires follow-up."
    elif warning is not None and warning.resolution_status is None and window_status == "expired":
        score = 85
        label = "CRITICAL"
        reason = "Recovery window expired while the student still appears high risk."
    elif warning is not None and warning.resolution_status is None and window_status == "active":
        score = 70
        label = "HIGH"
        reason = "Student is in an active recovery window and needs close monitoring."
    else:
        score = 60
        label = "HIGH"
        reason = "Student is currently high risk."

    if probability >= 0.95:
        score += 10
        reason = f"{reason} Final risk probability is extremely high."
    elif probability >= 0.85:
        score += 5

    if has_relapsed_after_resolution:
        score += 20
        reason = f"{reason} Student became high risk again after faculty had already resolved an earlier case."
    elif has_relapsed_after_recovery:
        score += 15
        reason = f"{reason} Student relapsed into high risk after an earlier recovery."
    elif high_risk_cycle_count >= 2 or repeat_high_count >= 2:
        score += 10
        reason = f"{reason} Student has repeated high-risk predictions."

    if intervention_status == "support_provided":
        score = max(score - 8, 0)
        reason = f"{reason} Faculty has already provided support."
    elif intervention_status == "contacted":
        score = max(score - 5, 0)
        reason = f"{reason} Faculty contact has already been logged."
    elif intervention_status in {"acknowledged", "seen"}:
        score = max(score - 3, 0)
        reason = f"{reason} Faculty has already acknowledged the case."

    if score >= 90:
        label = "CRITICAL"
    elif score >= 70:
        label = "HIGH"
    else:
        label = "MEDIUM"

    return score, label, reason


def _resolution_candidate_status(prediction, latest_intervention, warning, latest_alert) -> tuple[bool, str | None]:
    if prediction is None or int(prediction.final_predicted_class) != 0:
        return False, None
    if warning is None and latest_alert is None:
        return False, None

    intervention_status = _intervention_status(latest_intervention)
    if intervention_status == "resolved" and latest_intervention is not None:
        intervention_time = latest_intervention.created_at
        prediction_time = prediction.created_at
        if (
            intervention_time is not None
            and prediction_time is not None
            and intervention_time >= prediction_time
        ):
            return False, None

    if latest_alert is not None and latest_alert.alert_type == "faculty_followup_reminder":
        return True, "Low-risk state reached after reminder-backed faculty follow-up."
    if latest_alert is not None and latest_alert.alert_type == "post_warning_escalation":
        return True, "Low-risk state reached after faculty escalation."
    if warning is not None:
        return True, "Low-risk state reached after student warning cycle."

    return False, None


def _attendance_resolution_note(attendance_summary: dict) -> str | None:
    attendance_ratio = attendance_summary.get("attendance_ratio")
    attendance_trend = attendance_summary.get("attendance_trend")
    consecutive_absences = attendance_summary.get("consecutive_absences")

    if attendance_ratio is not None and float(attendance_ratio) < 0.75:
        return (
            f"Academic risk is lower, but attendance is still below policy comfort level "
            f"({float(attendance_ratio):.2f})."
        )
    if attendance_trend is not None and float(attendance_trend) < -0.05:
        return "Academic risk is lower, but attendance trend is still declining."
    if consecutive_absences is not None and float(consecutive_absences) >= 3:
        return "Academic risk is lower, but consecutive absences still need follow-up."
    return None


def _build_summary_student_item(
    student_id: int,
    status: str,
    prediction=None,
    event_time=None,
    note: str | None = None,
) -> FacultySummaryStudentItem:
    return FacultySummaryStudentItem(
        student_id=student_id,
        risk_level=(
            "HIGH"
            if prediction is not None and int(prediction.final_predicted_class) == 1
            else (
                "LOW"
                if prediction is not None and int(prediction.final_predicted_class) == 0
                else None
            )
        ),
        final_risk_probability=(
            float(prediction.final_risk_probability) if prediction is not None else None
        ),
        status=status,
        event_time=to_ist(event_time),
        note=note,
    )


@router.get("/priority-queue", response_model=FacultyPriorityQueueResponse)
def get_faculty_priority_queue(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> FacultyPriorityQueueResponse:
    repository = EventRepository(db)
    latest_predictions = repository.get_latest_predictions_for_all_students()
    warning_map = _latest_by_student(repository.get_all_student_warning_events())
    alert_map = _latest_by_student(repository.get_all_alert_events())
    all_interventions = repository.get_all_intervention_actions()
    intervention_map = _latest_by_student(all_interventions)
    intervention_rows_by_student = _interventions_by_student(all_interventions)
    prediction_history = repository.get_all_prediction_history()
    repeat_high_counts = _repeat_high_risk_count(prediction_history)
    repeated_risk_map = _repeated_risk_summary(prediction_history, intervention_rows_by_student)

    queue: list[FacultyPriorityQueueItem] = []

    for prediction in latest_predictions:
        if int(prediction.final_predicted_class) != 1:
            continue

        student_id = int(prediction.student_id)
        warning = warning_map.get(student_id)
        latest_alert = alert_map.get(student_id)
        latest_intervention = intervention_map.get(student_id)
        if _is_current_case_resolved(prediction, latest_intervention):
            continue
        lms_events = repository.get_lms_events_for_student(student_id)
        latest_erp_event = repository.get_latest_erp_event(student_id)
        latest_finance_event = repository.get_latest_finance_event(student_id)
        prediction_rows_for_student = repository.get_prediction_history_for_student(student_id)
        intervention_history = intervention_rows_by_student.get(student_id, [])
        profile = repository.get_student_profile(student_id)
        intelligence = None
        if lms_events and latest_erp_event is not None:
            intelligence = build_current_student_intelligence(
                prediction_rows=prediction_rows_for_student,
                latest_prediction=prediction,
                lms_events=lms_events,
                erp_event=latest_erp_event,
                erp_history=repository.get_erp_event_history_for_student(student_id),
                finance_event=latest_finance_event,
                finance_history=repository.get_finance_event_history_for_student(student_id),
                previous_prediction=prediction_rows_for_student[1]
                if len(prediction_rows_for_student) >= 2
                else None,
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
            latest_prediction=prediction,
            latest_warning=warning,
            latest_alert=latest_alert,
            intervention_history=intervention_history,
        )

        repeated_risk = repeated_risk_map.get(
            student_id,
            {
                "repeat_high_risk_count": repeat_high_counts.get(student_id, 0),
                "high_risk_cycle_count": 0,
                "has_relapsed_after_recovery": False,
                "has_relapsed_after_resolution": False,
                "is_repeated_risk_case": False,
                "is_reopened_case": False,
            },
        )
        latest_intervention_status = _intervention_status(latest_intervention)
        is_critical_unattended_case = (
            latest_alert is not None
            and latest_alert.alert_type == "faculty_followup_reminder"
            and latest_intervention_status
            not in {"seen", "acknowledged", "contacted", "support_provided", "resolved"}
        )
        priority_score, priority_label, queue_reason = _priority_for_student(
            latest_prediction=prediction,
            warning=warning,
            latest_alert=latest_alert,
            latest_intervention=latest_intervention,
            repeat_high_count=repeat_high_counts.get(student_id, 0),
            high_risk_cycle_count=int(repeated_risk["high_risk_cycle_count"]),
            has_relapsed_after_recovery=bool(repeated_risk["has_relapsed_after_recovery"]),
            has_relapsed_after_resolution=bool(
                repeated_risk["has_relapsed_after_resolution"]
            ),
            is_critical_unattended_case=is_critical_unattended_case,
        )

        queue.append(
            FacultyPriorityQueueItem(
                student_id=student_id,
                priority_score=priority_score,
                priority_label=priority_label,
                queue_reason=queue_reason,
                current_risk_level="HIGH",
                final_risk_probability=float(prediction.final_risk_probability),
                risk_trend_score=(
                    int(intelligence["risk_trend"]["trend_score"])
                    if intelligence is not None
                    else int(round(float(prediction.final_risk_probability) * 100))
                ),
                risk_trend_label=(
                    str(intelligence["risk_trend"]["trend_label"])
                    if intelligence is not None
                    else "unavailable"
                ),
                stability_score=(
                    int(intelligence["stability"]["stability_score"])
                    if intelligence is not None
                    else 0
                ),
                stability_label=(
                    str(intelligence["stability"]["stability_label"])
                    if intelligence is not None
                    else "unavailable"
                ),
                risk_type=(
                    str(intelligence["risk_type"]["primary_type"])
                    if intelligence is not None
                    else "unavailable"
                ),
                recommended_next_action=(
                    str(intelligence["recommended_actions"][0]["title"])
                    if intelligence is not None and intelligence["recommended_actions"]
                    else None
                ),
                active_trigger_codes=(
                    [
                        str(item["trigger_code"])
                        for item in intelligence["trigger_alerts"]["triggers"]
                    ]
                    if intelligence is not None
                    else []
                ),
                has_critical_trigger=(
                    bool(intelligence["trigger_alerts"]["has_critical_trigger"])
                    if intelligence is not None
                    else False
                ),
                last_meaningful_activity_at=to_ist(
                    activity_summary["last_meaningful_activity_at"]
                ),
                last_meaningful_activity_source=activity_summary[
                    "last_meaningful_activity_source"
                ],
                active_milestone_flags=list(milestone_flags["active_flags"]),
                sla_status=str(sla_summary["sla_status"]),
                followup_overdue=bool(sla_summary["followup_overdue"]),
                recovery_window_status=_window_status(warning),
                warning_status=warning.delivery_status if warning else None,
                faculty_alert_status=latest_alert.email_status if latest_alert else None,
                faculty_alert_type=latest_alert.alert_type if latest_alert else None,
                latest_intervention_status=(
                    latest_intervention.action_status if latest_intervention else None
                ),
                repeat_high_risk_count=repeat_high_counts.get(student_id, 0),
                high_risk_cycle_count=int(repeated_risk["high_risk_cycle_count"]),
                has_relapsed_after_recovery=bool(repeated_risk["has_relapsed_after_recovery"]),
                has_relapsed_after_resolution=bool(
                    repeated_risk["has_relapsed_after_resolution"]
                ),
                is_repeated_risk_case=bool(repeated_risk["is_repeated_risk_case"]),
                is_reopened_case=bool(repeated_risk["is_reopened_case"]),
                is_critical_unattended_case=is_critical_unattended_case,
                latest_prediction_created_at=to_ist(prediction.created_at),
            )
        )

    queue.sort(
        key=lambda item: (item.priority_score, item.final_risk_probability),
        reverse=True,
    )

    return FacultyPriorityQueueResponse(total_students=len(queue), queue=queue)


@router.get("/summary", response_model=FacultySummaryResponse)
def get_faculty_summary(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> FacultySummaryResponse:
    repository = EventRepository(db)
    now_utc = datetime.now(UTC)
    latest_predictions = repository.get_latest_predictions_for_all_students()
    latest_prediction_map = {
        int(prediction.student_id): prediction for prediction in latest_predictions
    }
    warning_map = _latest_by_student(repository.get_all_student_warning_events())
    alert_map = _latest_by_student(repository.get_all_alert_events())
    all_interventions = repository.get_all_intervention_actions()
    intervention_map = _latest_by_student(all_interventions)
    intervention_rows_by_student = _interventions_by_student(all_interventions)
    prediction_history = repository.get_all_prediction_history()
    repeated_risk_map = _repeated_risk_summary(prediction_history, intervention_rows_by_student)

    active_recovery_students: list[FacultySummaryStudentItem] = []
    expired_recovery_students: list[FacultySummaryStudentItem] = []
    escalated_students: list[FacultySummaryStudentItem] = []
    followup_reminder_students: list[FacultySummaryStudentItem] = []
    resolution_candidate_students: list[FacultySummaryStudentItem] = []
    reopened_case_students: list[FacultySummaryStudentItem] = []
    critical_unattended_case_students: list[FacultySummaryStudentItem] = []
    repeated_risk_students: list[FacultySummaryStudentItem] = []
    unhandled_escalation_students: list[FacultySummaryStudentItem] = []

    active_high_risk_count = 0

    for student_id, prediction in latest_prediction_map.items():
        latest_intervention = intervention_map.get(student_id)
        warning = warning_map.get(student_id)
        latest_alert = alert_map.get(student_id)
        latest_erp_event = repository.get_latest_erp_event(student_id)
        attendance_summary = build_attendance_summary(
            getattr(latest_erp_event, "context_fields", None)
        )
        if int(prediction.final_predicted_class) == 1 and not _is_current_case_resolved(
            prediction, latest_intervention
        ):
            active_high_risk_count += 1

        is_resolution_candidate, resolution_note = _resolution_candidate_status(
            prediction=prediction,
            latest_intervention=latest_intervention,
            warning=warning,
            latest_alert=latest_alert,
        )
        attendance_note = _attendance_resolution_note(attendance_summary)
        if is_resolution_candidate and attendance_note is not None:
            is_resolution_candidate = False
            resolution_note = attendance_note
        if is_resolution_candidate:
            resolution_candidate_students.append(
                _build_summary_student_item(
                    student_id=student_id,
                    status="resolution_candidate",
                    prediction=prediction,
                    event_time=prediction.created_at,
                    note=resolution_note,
                )
            )

        repeated_risk = repeated_risk_map.get(student_id)
        if repeated_risk and repeated_risk["is_reopened_case"]:
            reopened_case_students.append(
                _build_summary_student_item(
                    student_id=student_id,
                    status="reopened_case",
                    prediction=prediction,
                    event_time=prediction.created_at,
                    note="Student is high risk again after faculty had previously resolved the case.",
                )
            )
        if repeated_risk and repeated_risk["is_repeated_risk_case"]:
            repeated_risk_students.append(
                _build_summary_student_item(
                    student_id=student_id,
                    status="repeated_risk",
                    prediction=prediction,
                    event_time=prediction.created_at,
                    note=(
                        "Reopened after faculty resolution."
                        if repeated_risk["has_relapsed_after_resolution"]
                        else (
                            "Relapsed after recovery."
                            if repeated_risk["has_relapsed_after_recovery"]
                            else "Repeated high-risk pattern detected."
                        )
                    ),
                )
            )

    for student_id, warning in warning_map.items():
        prediction = latest_prediction_map.get(student_id)
        window_status = _window_status(warning)
        if warning.resolution_status is None and window_status == "active":
            active_recovery_students.append(
                _build_summary_student_item(
                    student_id=student_id,
                    status="active_recovery_window",
                    prediction=prediction,
                    event_time=warning.recovery_deadline,
                    note="Student is currently within the recovery window.",
                )
            )
        elif warning.resolution_status is None and window_status == "expired":
            expired_recovery_students.append(
                _build_summary_student_item(
                    student_id=student_id,
                    status="expired_recovery_window",
                    prediction=prediction,
                    event_time=warning.recovery_deadline,
                    note="Recovery deadline passed and still awaits outcome handling.",
                )
            )

    for student_id, alert in alert_map.items():
        prediction = latest_prediction_map.get(student_id)
        latest_intervention = intervention_map.get(student_id)
        intervention_status = _intervention_status(latest_intervention)

        if alert.alert_type == "post_warning_escalation":
            note = "Faculty escalation has been sent."
            if intervention_status is not None:
                note = f"Latest faculty intervention status is '{intervention_status}'."

            escalated_students.append(
                _build_summary_student_item(
                    student_id=student_id,
                    status=alert.email_status,
                    prediction=prediction,
                    event_time=alert.sent_at,
                    note=note,
                )
            )

            if intervention_status not in {
                "seen",
                "acknowledged",
                "contacted",
                "support_provided",
                "resolved",
            }:
                unhandled_escalation_students.append(
                    _build_summary_student_item(
                        student_id=student_id,
                        status="unhandled_escalation",
                        prediction=prediction,
                        event_time=alert.sent_at,
                        note="Escalation exists but no faculty intervention has been logged yet.",
                    )
                )

        elif alert.alert_type == "faculty_followup_reminder":
            note = "Automated follow-up reminder has been sent because no faculty action was logged."
            if intervention_status is not None:
                note = (
                    f"Follow-up reminder exists. Latest faculty intervention status is "
                    f"'{intervention_status}'."
                )

            followup_reminder_students.append(
                _build_summary_student_item(
                    student_id=student_id,
                    status=alert.email_status,
                    prediction=prediction,
                    event_time=alert.sent_at,
                    note=note,
                )
            )
            if intervention_status not in {
                "seen",
                "acknowledged",
                "contacted",
                "support_provided",
                "resolved",
            }:
                critical_unattended_case_students.append(
                    _build_summary_student_item(
                        student_id=student_id,
                        status="critical_unattended_case",
                        prediction=prediction,
                        event_time=alert.sent_at,
                        note="Reminder was already sent and still no faculty intervention is logged.",
                    )
                )

    active_recovery_students.sort(
        key=lambda item: item.event_time or now_utc,
        reverse=False,
    )
    expired_recovery_students.sort(
        key=lambda item: item.event_time or now_utc,
        reverse=False,
    )
    escalated_students.sort(
        key=lambda item: item.event_time or now_utc,
        reverse=True,
    )
    followup_reminder_students.sort(
        key=lambda item: item.event_time or now_utc,
        reverse=True,
    )
    resolution_candidate_students.sort(
        key=lambda item: item.event_time or now_utc,
        reverse=True,
    )
    reopened_case_students.sort(
        key=lambda item: item.event_time or now_utc,
        reverse=True,
    )
    critical_unattended_case_students.sort(
        key=lambda item: item.event_time or now_utc,
        reverse=True,
    )
    repeated_risk_students.sort(
        key=lambda item: (item.final_risk_probability or 0.0, item.event_time or now_utc),
        reverse=True,
    )
    unhandled_escalation_students.sort(
        key=lambda item: item.event_time or now_utc,
        reverse=True,
    )

    return FacultySummaryResponse(
        generated_at=to_ist(now_utc),
        total_active_high_risk_students=active_high_risk_count,
        total_active_recovery_windows=len(active_recovery_students),
        total_expired_recovery_windows=len(expired_recovery_students),
        total_escalated_cases=len(escalated_students),
        total_followup_reminders_sent=len(followup_reminder_students),
        total_resolution_candidates=len(resolution_candidate_students),
        total_reopened_cases=len(reopened_case_students),
        total_critical_unattended_cases=len(critical_unattended_case_students),
        total_repeated_risk_students=len(repeated_risk_students),
        total_unhandled_escalations=len(unhandled_escalation_students),
        active_recovery_students=active_recovery_students,
        expired_recovery_students=expired_recovery_students,
        escalated_students=escalated_students,
        followup_reminder_students=followup_reminder_students,
        resolution_candidate_students=resolution_candidate_students,
        reopened_case_students=reopened_case_students,
        critical_unattended_case_students=critical_unattended_case_students,
        repeated_risk_students=repeated_risk_students,
        unhandled_escalation_students=unhandled_escalation_students,
    )
