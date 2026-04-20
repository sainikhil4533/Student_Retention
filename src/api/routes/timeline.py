from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.academic_burden import build_academic_burden_summary
from src.api.auth import AuthContext, require_same_student_or_roles
from src.api.scope import ensure_student_scope_access
from src.api.prediction_history_serialization import resolve_prediction_intelligence_snapshot
from src.api.student_intelligence import build_current_student_intelligence
from src.api.schemas import StudentTimelineResponse, TimelineEventItem
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/timeline", tags=["timeline"])


def _case_reopened_prediction_ids(prediction_rows, intervention_rows) -> set[int]:
    ordered_predictions = list(reversed(prediction_rows))
    resolution_times = sorted(
        row.created_at
        for row in intervention_rows
        if str(row.action_status).strip().lower() == "resolved" and row.created_at is not None
    )

    reopened_prediction_ids: set[int] = set()
    previous_was_high = False
    for row in ordered_predictions:
        is_high = int(row.final_predicted_class) == 1
        if is_high and not previous_was_high:
            if any(resolution_time < row.created_at for resolution_time in resolution_times):
                reopened_prediction_ids.add(int(row.id))
        previous_was_high = is_high

    return reopened_prediction_ids


@router.get("/{student_id}", response_model=StudentTimelineResponse)
def get_student_timeline(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_same_student_or_roles("counsellor", "admin", "system")),
) -> StudentTimelineResponse:
    repository = EventRepository(db)
    ensure_student_scope_access(auth=auth, repository=repository, student_id=student_id)
    prediction_rows = repository.get_prediction_history_for_student(student_id)
    warning_rows = repository.get_student_warning_history_for_student(student_id)
    alert_rows = repository.get_alert_history_for_student(student_id)
    guardian_alert_rows = repository.get_guardian_alert_history_for_student(student_id)
    intervention_rows = repository.get_intervention_history_for_student(student_id)
    lms_events = repository.get_lms_events_for_student(student_id)
    latest_erp_event = repository.get_latest_erp_event(student_id)
    erp_history = repository.get_erp_event_history_for_student(student_id)
    latest_finance_event = repository.get_latest_finance_event(student_id)
    finance_history = repository.get_finance_event_history_for_student(student_id)
    subject_attendance_rows = repository.get_student_subject_attendance_records(student_id)
    semester_progress_rows = repository.get_student_semester_progress_records(student_id)
    academic_rows = repository.get_student_academic_records(student_id)
    reopened_prediction_ids = _case_reopened_prediction_ids(
        prediction_rows=prediction_rows,
        intervention_rows=intervention_rows,
    )
    intelligence_by_prediction_id: dict[int, dict] = {}
    if lms_events and latest_erp_event is not None:
        for index, row in enumerate(prediction_rows):
            intelligence_by_prediction_id[int(row.id)] = build_current_student_intelligence(
                prediction_rows=prediction_rows,
                latest_prediction=row,
                lms_events=lms_events,
                erp_event=latest_erp_event,
                erp_history=erp_history,
                finance_event=latest_finance_event,
                finance_history=finance_history,
                previous_prediction=prediction_rows[index + 1]
                if index + 1 < len(prediction_rows)
                else None,
            )

    timeline: list[TimelineEventItem] = []

    for row in prediction_rows:
        risk_level = "HIGH" if int(row.final_predicted_class) == 1 else "LOW"
        intelligence = resolve_prediction_intelligence_snapshot(
            row,
            intelligence_by_prediction_id.get(int(row.id)),
        )
        timeline.append(
            TimelineEventItem(
                event_time=to_ist(row.created_at),
                event_type="prediction_created",
                title="Prediction generated",
                status="completed",
                student_id=row.student_id,
                prediction_history_id=row.id,
                risk_level=risk_level,
                final_risk_probability=float(row.final_risk_probability),
                details={
                    "champion_model": row.champion_model,
                    "ai_source": (row.ai_insights or {}).get("source"),
                    "final_predicted_class": int(row.final_predicted_class),
                    "risk_trend_label": (
                        intelligence["risk_trend"]["trend_label"]
                        if intelligence["risk_trend"] is not None
                        else None
                    ),
                    "risk_type": (
                        intelligence["risk_type"]["primary_type"]
                        if intelligence["risk_type"] is not None
                        else None
                    ),
                    "stability_label": (
                        intelligence["stability"]["stability_label"]
                        if intelligence["stability"] is not None
                        else None
                    ),
                    "recommended_next_action": (
                        intelligence["recommended_actions"][0]["title"]
                        if intelligence["recommended_actions"]
                        else None
                    ),
                    "trigger_codes": [
                        item["trigger_code"]
                        for item in (
                            intelligence["trigger_alerts"]["triggers"]
                            if intelligence["trigger_alerts"] is not None
                            else []
                        )
                    ],
                },
            )
        )

        if int(row.id) in reopened_prediction_ids:
            timeline.append(
                TimelineEventItem(
                    event_time=to_ist(row.created_at),
                    event_type="case_reopened",
                    title="Case reopened after faculty resolution",
                    status="active",
                    student_id=row.student_id,
                    prediction_history_id=row.id,
                    risk_level=risk_level,
                    final_risk_probability=float(row.final_risk_probability),
                    details={
                        "reason": "Student became high risk again after a faculty-marked resolution.",
                    },
                )
            )

    for row in warning_rows:
        recovery_deadline = to_ist(row.recovery_deadline)
        timeline.append(
            TimelineEventItem(
                event_time=to_ist(row.sent_at),
                event_type="student_warning_sent",
                title="Student warning created",
                status=row.delivery_status,
                student_id=row.student_id,
                prediction_history_id=row.prediction_history_id,
                warning_event_id=row.id,
                risk_level=row.risk_level,
                final_risk_probability=float(row.final_risk_probability),
                details={
                    "warning_type": row.warning_type,
                    "recipient": row.recipient,
                    "recovery_deadline": recovery_deadline.isoformat()
                    if recovery_deadline
                    else None,
                    "error_message": row.error_message,
                },
            )
        )

        if row.resolved_at is not None:
            timeline.append(
                TimelineEventItem(
                    event_time=to_ist(row.resolved_at),
                    event_type="student_warning_resolved",
                    title="Student warning resolved",
                    status=row.resolution_status,
                    student_id=row.student_id,
                    prediction_history_id=row.prediction_history_id,
                    warning_event_id=row.id,
                    risk_level=row.risk_level,
                    final_risk_probability=float(row.final_risk_probability),
                    details={
                        "warning_type": row.warning_type,
                        "recipient": row.recipient,
                    },
                )
            )

    for row in alert_rows:
        timeline.append(
            TimelineEventItem(
                event_time=to_ist(row.sent_at),
                event_type="faculty_alert_sent",
                title="Faculty alert created",
                status=row.email_status,
                student_id=row.student_id,
                prediction_history_id=row.prediction_history_id,
                alert_event_id=row.id,
                risk_level=row.risk_level,
                final_risk_probability=float(row.final_risk_probability),
                details={
                    "alert_type": row.alert_type,
                    "recipient": row.recipient,
                    "error_message": row.error_message,
                },
            )
        )

    for row in guardian_alert_rows:
        timeline.append(
            TimelineEventItem(
                event_time=to_ist(row.sent_at),
                event_type="guardian_alert_sent",
                title="Guardian escalation created",
                status=row.delivery_status,
                student_id=row.student_id,
                prediction_history_id=row.prediction_history_id,
                risk_level=row.risk_level,
                final_risk_probability=float(row.final_risk_probability),
                details={
                    "alert_type": row.alert_type,
                    "recipient": row.recipient,
                    "channel": row.channel,
                    "guardian_name": row.guardian_name,
                    "guardian_relationship": row.guardian_relationship,
                    "provider_name": row.provider_name,
                    "provider_message_id": row.provider_message_id,
                    "error_message": row.error_message,
                },
            )
        )

    for row in intervention_rows:
        timeline.append(
            TimelineEventItem(
                event_time=to_ist(row.created_at),
                event_type="faculty_intervention_logged",
                title="Faculty intervention recorded",
                status=row.action_status,
                student_id=row.student_id,
                alert_event_id=row.alert_event_id,
                details={
                    "actor_name": row.actor_name,
                    "notes": row.notes,
                },
            )
        )

    for row in subject_attendance_rows:
        subject_status = str(row.subject_status or "").upper()
        if subject_status not in {"I_GRADE", "R_GRADE"}:
            continue
        timeline.append(
            TimelineEventItem(
                event_time=to_ist(row.updated_at),
                event_type="attendance_policy_triggered",
                title=f"{row.subject_name} entered {subject_status.replace('_', ' ')} status",
                status=subject_status.lower(),
                student_id=row.student_id,
                details={
                    "semester": row.semester,
                    "year": row.year,
                    "subject_code": row.subject_code,
                    "subject_attendance_percent": row.subject_attendance_percent,
                    "required_percent": row.required_percent,
                    "grade_consequence": row.grade_consequence,
                    "condonation_required": bool(row.condonation_required),
                    "summer_repeat_required": bool(row.summer_repeat_required),
                    "end_sem_eligible": bool(row.end_sem_eligible),
                },
            )
        )

    for row in semester_progress_rows:
        if row.overall_status != "SHORTAGE":
            continue
        timeline.append(
            TimelineEventItem(
                event_time=to_ist(row.updated_at),
                event_type="semester_attendance_shortage",
                title=f"Semester {row.semester} attendance fell below the required overall threshold",
                status="shortage",
                student_id=row.student_id,
                details={
                    "year": row.year,
                    "overall_attendance_percent": row.overall_attendance_percent,
                    "subjects_below_75_count": row.subjects_below_75_count,
                    "subjects_below_65_count": row.subjects_below_65_count,
                    "current_eligibility": row.current_eligibility,
                    "semester_mode": row.semester_mode,
                },
            )
        )

    academic_burden = build_academic_burden_summary(
        academic_rows=academic_rows,
        attendance_rows=subject_attendance_rows,
    )
    attendance_time_index: dict[tuple[int | None, str], object] = {}
    for row in subject_attendance_rows:
        attendance_time_index[(row.semester, str(row.subject_name or ""))] = row
    for item in academic_burden["active_r_grade_subjects"] + academic_burden["active_i_grade_subjects"]:
        matched_attendance = attendance_time_index.get((item.get("semester"), str(item.get("subject_name") or "")))
        cadence = "weekly" if item.get("effective_grade") == "R" else "monthly"
        timeline.append(
            TimelineEventItem(
                event_time=to_ist(getattr(matched_attendance, "updated_at", None)),
                event_type="active_academic_burden",
                title=f"{item.get('subject_name') or 'Subject'} still remains uncleared",
                status=str(item.get("effective_grade") or "pending").lower(),
                student_id=student_id,
                details={
                    "semester": item.get("semester"),
                    "year": item.get("year"),
                    "effective_result_status": item.get("effective_result_status"),
                    "effective_grade": item.get("effective_grade"),
                    "subject_attendance_percent": item.get("subject_attendance_percent"),
                    "monitoring_cadence": cadence,
                    "reason": (
                        f"This subject should remain visible as uncleared until the {item.get('effective_grade')} grade is actually cleared."
                    ),
                },
            )
        )

    timeline.sort(
        key=lambda item: item.event_time.isoformat() if item.event_time else "",
        reverse=True,
    )

    return StudentTimelineResponse(student_id=student_id, timeline=timeline)
