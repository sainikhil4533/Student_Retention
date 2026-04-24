from datetime import UTC, datetime
from collections import defaultdict
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.academic_pressure import (
    build_academic_pressure_snapshot,
    build_academic_pressure_snapshot_from_rows,
)
from src.api.academic_burden import build_academic_burden_summary
from src.api.auth import AuthContext, require_roles
from src.api.attendance_engine import build_attendance_summary
from src.api.schemas import (
    AcademicPressureBucketItem,
    AcademicSubjectPressureItem,
    FacultyDashboardSummaryResponse,
    FacultyPriorityQueueItem,
    FacultyPriorityQueueResponse,
    FacultySummaryResponse,
    FacultySummaryStudentItem,
)
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/faculty", tags=["faculty"])
_FACULTY_RESPONSE_CACHE_TTL_SECONDS = 30.0
_FACULTY_SCOPE_CACHE_TTL_SECONDS = 300.0
_FACULTY_CACHE_LOCK = Lock()
_FACULTY_SCOPE_CACHE: dict[str, tuple[float, set[int] | None]] = {}
_FACULTY_RESPONSE_CACHE: dict[str, tuple[float, object]] = {}


def _cache_lookup(
    cache: dict[str, tuple[float, object]],
    key: str,
    *,
    allow_stale: bool = False,
) -> object | None:
    with _FACULTY_CACHE_LOCK:
        entry = cache.get(key)
        if entry is None:
            return None
        created_at, value = entry
        ttl_seconds = (
            _FACULTY_SCOPE_CACHE_TTL_SECONDS
            if cache is _FACULTY_SCOPE_CACHE
            else _FACULTY_RESPONSE_CACHE_TTL_SECONDS
        )
        if monotonic() - created_at > ttl_seconds:
            return value if allow_stale else None
        return value


def _cache_store(cache: dict[str, tuple[float, object]], key: str, value: object) -> object:
    with _FACULTY_CACHE_LOCK:
        cache[key] = (monotonic(), value)
    return value


def _faculty_cache_key(kind: str, auth: AuthContext) -> str:
    return f"{kind}:{auth.role}:{auth.subject}:{auth.display_name or ''}"


def _empty_faculty_dashboard_summary(*, generated_at: datetime) -> FacultyDashboardSummaryResponse:
    return FacultyDashboardSummaryResponse(
        generated_at=to_ist(generated_at),
        total_active_high_risk_students=0,
        total_critical_unattended_cases=0,
        total_students_with_overall_shortage=0,
        total_students_with_i_grade_risk=0,
        total_students_with_r_grade_risk=0,
        total_students_with_active_academic_burden=0,
        total_students_with_active_i_grade_burden=0,
        total_students_with_active_r_grade_burden=0,
        top_subject_pressure=[],
        branch_pressure=[],
        semester_pressure=[],
    )


def _empty_faculty_priority_queue() -> FacultyPriorityQueueResponse:
    return FacultyPriorityQueueResponse(total_students=0, queue=[])


def _empty_faculty_summary(*, generated_at: datetime) -> FacultySummaryResponse:
    return FacultySummaryResponse(
        generated_at=to_ist(generated_at),
        total_active_high_risk_students=0,
        total_active_recovery_windows=0,
        total_expired_recovery_windows=0,
        total_escalated_cases=0,
        total_followup_reminders_sent=0,
        total_resolution_candidates=0,
        total_reopened_cases=0,
        total_critical_unattended_cases=0,
        total_repeated_risk_students=0,
        total_unhandled_escalations=0,
        total_students_with_overall_shortage=0,
        total_students_with_i_grade_risk=0,
        total_students_with_r_grade_risk=0,
        total_students_with_active_academic_burden=0,
        total_students_with_active_i_grade_burden=0,
        total_students_with_active_r_grade_burden=0,
        top_subject_pressure=[],
        branch_pressure=[],
        semester_pressure=[],
        active_recovery_students=[],
        expired_recovery_students=[],
        escalated_students=[],
        followup_reminder_students=[],
        resolution_candidate_students=[],
        reopened_case_students=[],
        critical_unattended_case_students=[],
        repeated_risk_students=[],
        unhandled_escalation_students=[],
        academic_burden_monitoring_students=[],
    )


@router.get("/dashboard-summary", response_model=FacultyDashboardSummaryResponse)
def get_faculty_dashboard_summary(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> FacultyDashboardSummaryResponse:
    cache_key = _faculty_cache_key("dashboard-summary", auth)
    cached = _cache_lookup(_FACULTY_RESPONSE_CACHE, cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    stale_cached = _cache_lookup(_FACULTY_RESPONSE_CACHE, cache_key, allow_stale=True)
    repository = EventRepository(db)
    now_utc = datetime.now(UTC)
    try:
        scoped_student_ids = _scoped_student_ids(repository, auth)
        latest_predictions = repository.get_latest_predictions_for_students(scoped_student_ids)
        latest_prediction_map = {
            int(prediction.student_id): prediction for prediction in latest_predictions
        }
        warning_map = _latest_by_student(repository.get_latest_student_warning_events_for_students(scoped_student_ids))
        alert_map = _latest_by_student(repository.get_latest_alert_events_for_students(scoped_student_ids))
        intervention_map = _latest_by_student(repository.get_latest_intervention_actions_for_students(scoped_student_ids))

        active_high_risk_count = 0
        critical_unattended_case_count = 0

        for student_id, prediction in latest_prediction_map.items():
            latest_intervention = intervention_map.get(student_id)
            if int(prediction.final_predicted_class) == 1 and not _is_current_case_resolved(
                prediction, latest_intervention
            ):
                active_high_risk_count += 1

        for student_id, alert in alert_map.items():
            latest_intervention = intervention_map.get(student_id)
            intervention_status = _intervention_status(latest_intervention)
            if (
                alert.alert_type == "faculty_followup_reminder"
                and intervention_status not in {"seen", "acknowledged", "contacted", "support_provided", "resolved"}
            ):
                critical_unattended_case_count += 1

        student_ids = scoped_student_ids or set(latest_prediction_map.keys())
        academic_rows = repository.get_student_academic_records_for_students(student_ids or None)
        attendance_rows = repository.get_current_student_subject_attendance_records_for_students(student_ids or None)
        academic_progress_rows = repository.get_student_academic_progress_records_for_students(student_ids or None)
        semester_rows = repository.get_latest_student_semester_progress_records_for_students(student_ids or None)
        academic_rows_by_student: dict[int, list] = defaultdict(list)
        attendance_rows_by_student: dict[int, list] = defaultdict(list)
        for row in academic_rows:
            academic_rows_by_student[int(row.student_id)].append(row)
        for row in attendance_rows:
            attendance_rows_by_student[int(row.student_id)].append(row)

        active_burden_count = 0
        active_i_grade_burden_count = 0
        active_r_grade_burden_count = 0
        for student_id in student_ids:
            academic_burden = build_academic_burden_summary(
                academic_rows=academic_rows_by_student.get(student_id, []),
                attendance_rows=attendance_rows_by_student.get(student_id, []),
            )
            if bool(academic_burden["has_active_burden"]):
                active_burden_count += 1
                if bool(academic_burden["has_active_i_grade_burden"]):
                    active_i_grade_burden_count += 1
                if bool(academic_burden["has_active_r_grade_burden"]):
                    active_r_grade_burden_count += 1

        academic_pressure = _academic_pressure_summary(
            repository,
            student_ids=scoped_student_ids,
            academic_progress_rows=academic_progress_rows,
            semester_rows=semester_rows,
            subject_rows=attendance_rows,
        )

        response = FacultyDashboardSummaryResponse(
            generated_at=to_ist(now_utc),
            total_active_high_risk_students=active_high_risk_count,
            total_critical_unattended_cases=critical_unattended_case_count,
            total_students_with_overall_shortage=int(academic_pressure["total_students_with_overall_shortage"]),
            total_students_with_i_grade_risk=int(academic_pressure["total_students_with_i_grade_risk"]),
            total_students_with_r_grade_risk=int(academic_pressure["total_students_with_r_grade_risk"]),
            total_students_with_active_academic_burden=active_burden_count,
            total_students_with_active_i_grade_burden=active_i_grade_burden_count,
            total_students_with_active_r_grade_burden=active_r_grade_burden_count,
            top_subject_pressure=list(academic_pressure["top_subject_pressure"]),
            branch_pressure=list(academic_pressure["branch_pressure"]),
            semester_pressure=list(academic_pressure["semester_pressure"]),
        )
        return _cache_store(_FACULTY_RESPONSE_CACHE, cache_key, response)  # type: ignore[return-value]
    except Exception:
        if stale_cached is not None:
            return stale_cached  # type: ignore[return-value]
        return _empty_faculty_dashboard_summary(generated_at=now_utc)


def _scoped_student_ids(repository: EventRepository, auth: AuthContext) -> set[int] | None:
    if auth.role != "counsellor":
        return None
    cache_key = _faculty_cache_key("scope-ids", auth)
    cached = _cache_lookup(_FACULTY_SCOPE_CACHE, cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    profiles = repository.get_imported_student_profiles_for_counsellor_identity(
        subject=auth.subject,
        display_name=auth.display_name,
    )
    scoped_ids = {int(profile.student_id) for profile in profiles}
    return _cache_store(_FACULTY_SCOPE_CACHE, cache_key, scoped_ids or set())  # type: ignore[return-value]


def _academic_pressure_summary(
    repository: EventRepository,
    *,
    student_ids: set[int] | None,
    academic_progress_rows: list[object] | None = None,
    semester_rows: list[object] | None = None,
    subject_rows: list[object] | None = None,
) -> dict:
    if academic_progress_rows is not None and semester_rows is not None and subject_rows is not None:
        snapshot = build_academic_pressure_snapshot_from_rows(
            academic_progress_rows=academic_progress_rows,
            semester_rows=semester_rows,
            subject_rows=subject_rows,
            subject_limit=5,
            bucket_limit=5,
            top_student_limit=5,
        )
    else:
        snapshot = build_academic_pressure_snapshot(
            repository,
            student_ids=student_ids,
            subject_limit=5,
            bucket_limit=5,
            top_student_limit=5,
        )
    return {
        "total_students_with_overall_shortage": int(snapshot["total_students_with_overall_shortage"]),
        "total_students_with_i_grade_risk": int(snapshot["total_students_with_i_grade_risk"]),
        "total_students_with_r_grade_risk": int(snapshot["total_students_with_r_grade_risk"]),
        "top_subject_pressure": [
            AcademicSubjectPressureItem(**item) for item in snapshot["top_subjects"]
        ],
        "branch_pressure": [
            AcademicPressureBucketItem(**item) for item in snapshot["branch_pressure"]
        ],
        "semester_pressure": [
            AcademicPressureBucketItem(**item) for item in snapshot["semester_pressure"]
        ],
    }


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
    elif score >= 60:
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


def _academic_burden_note(summary: dict) -> str:
    cadence = str(summary.get("monitoring_cadence") or "NONE").replace("_", " ").title()
    return f"{summary['summary']} Recommended counsellor monitoring cadence: {cadence}."


def _recommended_queue_action(
    *,
    is_currently_high_risk: bool,
    academic_burden: dict,
    latest_alert,
    latest_intervention,
) -> str:
    intervention_status = _intervention_status(latest_intervention)
    if is_currently_high_risk:
        if latest_alert is not None and latest_alert.alert_type == "faculty_followup_reminder":
            return "Log same-day counsellor follow-up and confirm direct student contact."
        if latest_alert is not None and latest_alert.alert_type == "post_warning_escalation":
            return "Prioritize an escalation follow-up plan and confirm the first counsellor action."
        if intervention_status in {"seen", "acknowledged", "contacted", "support_provided"}:
            return "Continue the current counsellor handling plan until the risk drivers stabilize."
        return "Start with direct outreach and an immediate academic barrier review."
    if bool(academic_burden.get("has_active_r_grade_burden")):
        return "Create a weekly clearance plan for unresolved R-grade subjects."
    return "Create a monthly follow-up plan for unresolved I-grade subjects."


def _lightweight_risk_type(*, is_currently_high_risk: bool, academic_burden: dict) -> str:
    if is_currently_high_risk and bool(academic_burden.get("has_active_burden")):
        return "mixed_risk_with_active_burden"
    if is_currently_high_risk:
        return "current_high_risk"
    if bool(academic_burden.get("has_active_r_grade_burden")):
        return "active_r_grade_burden"
    return "active_i_grade_burden"


def _build_faculty_priority_queue_items(
    repository: EventRepository,
    auth: AuthContext,
) -> list[FacultyPriorityQueueItem]:
    scoped_student_ids = _scoped_student_ids(repository, auth)
    latest_predictions = repository.get_latest_predictions_for_students(scoped_student_ids)
    student_ids = {int(prediction.student_id) for prediction in latest_predictions}
    if not student_ids:
        return []

    warning_map = _latest_by_student(repository.get_latest_student_warning_events_for_students(student_ids))
    alert_map = _latest_by_student(repository.get_latest_alert_events_for_students(student_ids))
    intervention_map = _latest_by_student(repository.get_latest_intervention_actions_for_students(student_ids))
    semester_progress_rows = repository.get_latest_student_semester_progress_records_for_students(student_ids)
    academic_rows = repository.get_student_academic_records_for_students(student_ids)
    attendance_rows = repository.get_current_student_subject_attendance_records_for_students(student_ids)
    semester_progress_by_student = {
        int(row.student_id): row for row in semester_progress_rows
    }

    academic_rows_by_student: dict[int, list] = defaultdict(list)
    attendance_rows_by_student: dict[int, list] = defaultdict(list)
    for row in academic_rows:
        academic_rows_by_student[int(row.student_id)].append(row)
    for row in attendance_rows:
        attendance_rows_by_student[int(row.student_id)].append(row)

    queue: list[FacultyPriorityQueueItem] = []

    for prediction in latest_predictions:
        student_id = int(prediction.student_id)
        semester_progress = semester_progress_by_student.get(student_id)
        academic_burden = build_academic_burden_summary(
            academic_rows=academic_rows_by_student.get(student_id, []),
            attendance_rows=attendance_rows_by_student.get(student_id, []),
        )
        has_active_burden = bool(academic_burden["has_active_burden"])
        has_current_r_grade_risk = bool(getattr(semester_progress, "has_r_grade_risk", False))
        has_current_i_grade_risk = bool(getattr(semester_progress, "has_i_grade_risk", False))
        current_overall_status = str(getattr(semester_progress, "overall_status", "") or "").strip().upper()
        has_current_overall_shortage = current_overall_status == "SHORTAGE"
        is_currently_high_risk = float(prediction.final_risk_probability) >= 0.50
        if (
            not is_currently_high_risk
            and not has_active_burden
            and not has_current_r_grade_risk
            and not has_current_i_grade_risk
            and not has_current_overall_shortage
        ):
            continue

        warning = warning_map.get(student_id)
        latest_alert = alert_map.get(student_id)
        latest_intervention = intervention_map.get(student_id)
        if is_currently_high_risk and _is_current_case_resolved(prediction, latest_intervention):
            continue

        latest_intervention_status = _intervention_status(latest_intervention)
        is_critical_unattended_case = (
            latest_alert is not None
            and latest_alert.alert_type == "faculty_followup_reminder"
            and latest_intervention_status
            not in {"seen", "acknowledged", "contacted", "support_provided", "resolved"}
        )
        if is_currently_high_risk:
            priority_score, priority_label, queue_reason = _priority_for_student(
                latest_prediction=prediction,
                warning=warning,
                latest_alert=latest_alert,
                latest_intervention=latest_intervention,
                repeat_high_count=0,
                high_risk_cycle_count=0,
                has_relapsed_after_recovery=False,
                has_relapsed_after_resolution=False,
                is_critical_unattended_case=is_critical_unattended_case,
            )
        else:
            # Compute subject-level counts for intelligent scoring
            _att_rows = attendance_rows_by_student.get(student_id, [])
            _cur_r_subjects = [
                r for r in _att_rows
                if str(getattr(r, "subject_status", "") or "").strip().upper() == "R_GRADE"
            ]
            _cur_i_subjects = [
                r for r in _att_rows
                if str(getattr(r, "subject_status", "") or "").strip().upper() == "I_GRADE"
            ]

            # Detect same subject failing both this semester AND as carry-forward
            # (student repeating the same subject again → red flag)
            _carry_r_names = {
                str(s.get("subject_name") or "").strip().lower()
                for s in academic_burden["active_r_grade_subjects"]
                if s.get("subject_name")
            }
            _cur_r_names = {
                str(getattr(r, "subject_name", "") or "").strip().lower()
                for r in _cur_r_subjects
                if getattr(r, "subject_name", None)
            }
            _has_repeated_subject = bool(_carry_r_names & _cur_r_names)

            if has_current_r_grade_risk:
                # Current semester attendance < 65% → below R-grade threshold (recoverable)
                # Must stay below 60 (the ML HIGH risk floor)
                r_count = len(_cur_r_subjects)
                base = 52 if r_count <= 2 else 57
                if _has_repeated_subject:
                    base = min(base + 5, 59)  # same subject failing again
                if has_active_burden:
                    base = min(base + 2, 59)  # also has carry-forward burden
                priority_score = base
                priority_label = "CURRENT_R_SHORTAGE"
                weakest_subject = next(
                    (
                        row
                        for row in _cur_r_subjects
                        if getattr(row, "subject_attendance_percent", None) is not None
                    ),
                    None,
                )
                queue_reason = (
                    f"Current semester attendance has fallen below 65% (R-grade threshold)"
                    + (
                        f" in `{weakest_subject.subject_name}` at {float(weakest_subject.subject_attendance_percent or 0.0):.2f}%."
                        if weakest_subject is not None
                        else "."
                    )
                )
                if _has_repeated_subject:
                    queue_reason += " Same subject also has a carry-forward burden — repeated failure pattern."

            elif has_current_i_grade_risk:
                # Current semester attendance 65–75% → below I-grade threshold (recoverable)
                i_count = len(_cur_i_subjects)
                base = 46 if i_count <= 2 else 51
                if has_active_burden:
                    base = min(base + 2, 59)
                priority_score = base
                priority_label = "CURRENT_I_SHORTAGE"
                weakest_subject = next(
                    (
                        row
                        for row in _cur_i_subjects
                        if getattr(row, "subject_attendance_percent", None) is not None
                    ),
                    None,
                )
                queue_reason = (
                    f"Current semester attendance is between 65–75% (I-grade risk threshold)"
                    + (
                        f" in `{weakest_subject.subject_name}` at {float(weakest_subject.subject_attendance_percent or 0.0):.2f}%."
                        if weakest_subject is not None
                        else "."
                    )
                )

            elif has_current_overall_shortage:
                # Overall attendance below safe threshold but no subject-level grade risk yet
                overall_percent = getattr(semester_progress, "overall_attendance_percent", None)
                priority_score = 40
                priority_label = "CURRENT_SHORTAGE"
                queue_reason = (
                    "Current semester overall attendance is below the safe threshold"
                    + (
                        f" at {float(overall_percent):.2f}%."
                        if overall_percent is not None
                        else "."
                    )
                )

            elif bool(academic_burden["has_active_r_grade_burden"]):
                # Carry-forward R-grades from past semesters (need supplementary exam)
                r_carry = len(academic_burden["active_r_grade_subjects"])
                base = 32 if r_carry <= 3 else 38
                if _has_repeated_subject:
                    base = min(base + 8, 42)  # same subject failing repeatedly
                priority_score = base
                priority_label = "ACADEMIC_SEVERE"
                queue_reason = _academic_burden_note(academic_burden)

            else:
                # Carry-forward I-grades only from past semesters
                i_carry = len(academic_burden["active_i_grade_subjects"])
                base = 22 if i_carry <= 5 else 28
                priority_score = base
                priority_label = "ACADEMIC_WATCHLIST"
                queue_reason = _academic_burden_note(academic_burden)

            if has_active_burden:
                queue_reason = (
                    f"{queue_reason} Carry-forward burden still active: {academic_burden['summary']}"
                    if not queue_reason.endswith(academic_burden["summary"])
                    else queue_reason
                )

        from src.api.risk_classification import classify_risk_level
        queue.append(
            FacultyPriorityQueueItem(
                student_id=student_id,
                priority_score=priority_score,
                priority_label=priority_label,
                queue_reason=queue_reason,
                current_risk_level=classify_risk_level(float(prediction.final_risk_probability)),
                final_risk_probability=float(prediction.final_risk_probability),
                risk_trend_score=int(round(float(prediction.final_risk_probability) * 100)),
                risk_trend_label="high_risk_active" if is_currently_high_risk else "monitoring",
                stability_score=0,
                stability_label="unavailable",
                risk_type=_lightweight_risk_type(
                    is_currently_high_risk=is_currently_high_risk,
                    academic_burden=academic_burden,
                ),
                recommended_next_action=_recommended_queue_action(
                    is_currently_high_risk=is_currently_high_risk,
                    academic_burden=academic_burden,
                    latest_alert=latest_alert,
                    latest_intervention=latest_intervention,
                ),
                active_trigger_codes=[],
                has_critical_trigger=is_critical_unattended_case,
                last_meaningful_activity_at=None,
                last_meaningful_activity_source=None,
                active_milestone_flags=[],
                sla_status="not_applicable",
                followup_overdue=False,
                recovery_window_status=_window_status(warning),
                warning_status=warning.delivery_status if warning else None,
                faculty_alert_status=latest_alert.email_status if latest_alert else None,
                faculty_alert_type=latest_alert.alert_type if latest_alert else None,
                latest_intervention_status=(
                    latest_intervention.action_status if latest_intervention else None
                ),
                has_active_academic_burden=has_active_burden,
                academic_risk_band=str(academic_burden["academic_risk_band"]),
                monitoring_cadence=str(academic_burden["monitoring_cadence"]),
                active_burden_count=int(academic_burden["active_burden_count"]),
                repeat_high_risk_count=0,
                high_risk_cycle_count=0,
                has_relapsed_after_recovery=False,
                has_relapsed_after_resolution=False,
                is_repeated_risk_case=False,
                is_reopened_case=False,
                is_critical_unattended_case=is_critical_unattended_case,
                latest_prediction_created_at=to_ist(prediction.created_at),
            )
        )

    queue.sort(
        key=lambda item: (item.priority_score, item.final_risk_probability),
        reverse=True,
    )
    return queue


@router.get("/priority-queue", response_model=FacultyPriorityQueueResponse)
def get_faculty_priority_queue(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> FacultyPriorityQueueResponse:
    cache_key = _faculty_cache_key("priority-queue", auth)
    cached = _cache_lookup(_FACULTY_RESPONSE_CACHE, cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    stale_cached = _cache_lookup(_FACULTY_RESPONSE_CACHE, cache_key, allow_stale=True)
    repository = EventRepository(db)
    try:
        queue = _build_faculty_priority_queue_items(repository, auth)
        response = FacultyPriorityQueueResponse(total_students=len(queue), queue=queue)
        return _cache_store(_FACULTY_RESPONSE_CACHE, cache_key, response)  # type: ignore[return-value]
    except Exception:
        if stale_cached is not None:
            return stale_cached  # type: ignore[return-value]
        return _empty_faculty_priority_queue()


@router.get("/summary", response_model=FacultySummaryResponse)
def get_faculty_summary(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> FacultySummaryResponse:
    cache_key = _faculty_cache_key("summary", auth)
    cached = _cache_lookup(_FACULTY_RESPONSE_CACHE, cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    stale_cached = _cache_lookup(_FACULTY_RESPONSE_CACHE, cache_key, allow_stale=True)
    now_utc = datetime.now(UTC)
    if auth.role == "counsellor":
        try:
            dashboard = get_faculty_dashboard_summary(db=db, auth=auth)
            priority_queue = get_faculty_priority_queue(db=db, auth=auth)
            academic_burden_monitoring_students = [
                _build_summary_student_item(
                    student_id=int(item.student_id),
                    status="academic_burden_monitoring",
                    prediction=None,
                    event_time=item.latest_prediction_created_at,
                    note=item.queue_reason,
                )
                for item in priority_queue.queue
                if item.has_active_academic_burden
            ]
            response = FacultySummaryResponse(
                generated_at=dashboard.generated_at,
                total_active_high_risk_students=dashboard.total_active_high_risk_students,
                total_active_recovery_windows=0,
                total_expired_recovery_windows=0,
                total_escalated_cases=0,
                total_followup_reminders_sent=dashboard.total_critical_unattended_cases,
                total_resolution_candidates=0,
                total_reopened_cases=0,
                total_critical_unattended_cases=dashboard.total_critical_unattended_cases,
                total_repeated_risk_students=0,
                total_unhandled_escalations=0,
                total_students_with_overall_shortage=dashboard.total_students_with_overall_shortage,
                total_students_with_i_grade_risk=dashboard.total_students_with_i_grade_risk,
                total_students_with_r_grade_risk=dashboard.total_students_with_r_grade_risk,
                total_students_with_active_academic_burden=dashboard.total_students_with_active_academic_burden,
                total_students_with_active_i_grade_burden=dashboard.total_students_with_active_i_grade_burden,
                total_students_with_active_r_grade_burden=dashboard.total_students_with_active_r_grade_burden,
                top_subject_pressure=dashboard.top_subject_pressure,
                branch_pressure=dashboard.branch_pressure,
                semester_pressure=dashboard.semester_pressure,
                active_recovery_students=[],
                expired_recovery_students=[],
                escalated_students=[],
                followup_reminder_students=[],
                resolution_candidate_students=[],
                reopened_case_students=[],
                critical_unattended_case_students=[],
                repeated_risk_students=[],
                unhandled_escalation_students=[],
                academic_burden_monitoring_students=academic_burden_monitoring_students,
            )
            return _cache_store(_FACULTY_RESPONSE_CACHE, cache_key, response)  # type: ignore[return-value]
        except Exception:
            if stale_cached is not None:
                return stale_cached  # type: ignore[return-value]
            return _empty_faculty_summary(generated_at=now_utc)
    repository = EventRepository(db)
    scoped_student_ids = _scoped_student_ids(repository, auth)
    latest_predictions = repository.get_latest_predictions_for_students(scoped_student_ids)
    latest_prediction_map = {
        int(prediction.student_id): prediction for prediction in latest_predictions
    }
    warning_map = _latest_by_student(repository.get_latest_student_warning_events_for_students(scoped_student_ids))
    alert_map = _latest_by_student(repository.get_latest_alert_events_for_students(scoped_student_ids))
    all_interventions = repository.get_intervention_actions_for_students(scoped_student_ids)
    intervention_map = _latest_by_student(all_interventions)
    intervention_rows_by_student = _interventions_by_student(all_interventions)
    prediction_history = repository.get_prediction_history_for_students(scoped_student_ids)
    repeated_risk_map = _repeated_risk_summary(prediction_history, intervention_rows_by_student)
    student_ids = scoped_student_ids or set(latest_prediction_map.keys())
    latest_erp_by_student = repository.get_latest_erp_events_for_students(student_ids or None)
    academic_rows = repository.get_student_academic_records_for_students(student_ids or None)
    attendance_rows = repository.get_current_student_subject_attendance_records_for_students(student_ids or None)
    academic_progress_rows = repository.get_student_academic_progress_records_for_students(student_ids or None)
    semester_rows = repository.get_latest_student_semester_progress_records_for_students(student_ids or None)
    academic_rows_by_student: dict[int, list] = defaultdict(list)
    attendance_rows_by_student: dict[int, list] = defaultdict(list)
    for row in academic_rows:
        academic_rows_by_student[int(row.student_id)].append(row)
    for row in attendance_rows:
        attendance_rows_by_student[int(row.student_id)].append(row)

    active_recovery_students: list[FacultySummaryStudentItem] = []
    expired_recovery_students: list[FacultySummaryStudentItem] = []
    escalated_students: list[FacultySummaryStudentItem] = []
    followup_reminder_students: list[FacultySummaryStudentItem] = []
    resolution_candidate_students: list[FacultySummaryStudentItem] = []
    reopened_case_students: list[FacultySummaryStudentItem] = []
    critical_unattended_case_students: list[FacultySummaryStudentItem] = []
    repeated_risk_students: list[FacultySummaryStudentItem] = []
    unhandled_escalation_students: list[FacultySummaryStudentItem] = []
    academic_burden_monitoring_students: list[FacultySummaryStudentItem] = []

    active_high_risk_count = 0
    active_burden_count = 0
    active_i_grade_burden_count = 0
    active_r_grade_burden_count = 0

    for student_id, prediction in latest_prediction_map.items():
        latest_intervention = intervention_map.get(student_id)
        warning = warning_map.get(student_id)
        latest_alert = alert_map.get(student_id)
        latest_erp_event = latest_erp_by_student.get(student_id)
        attendance_summary = build_attendance_summary(
            getattr(latest_erp_event, "context_fields", None)
        )
        academic_burden = build_academic_burden_summary(
            academic_rows=academic_rows_by_student.get(student_id, []),
            attendance_rows=attendance_rows_by_student.get(student_id, []),
        )
        if int(prediction.final_predicted_class) == 1 and not _is_current_case_resolved(
            prediction, latest_intervention
        ):
            active_high_risk_count += 1

        if bool(academic_burden["has_active_burden"]):
            active_burden_count += 1
            if bool(academic_burden["has_active_i_grade_burden"]):
                active_i_grade_burden_count += 1
            if bool(academic_burden["has_active_r_grade_burden"]):
                active_r_grade_burden_count += 1
            academic_burden_monitoring_students.append(
                _build_summary_student_item(
                    student_id=student_id,
                    status="academic_burden_monitoring",
                    prediction=prediction,
                    event_time=prediction.created_at,
                    note=_academic_burden_note(academic_burden),
                )
            )

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
    academic_burden_monitoring_students.sort(
        key=lambda item: (item.final_risk_probability or 0.0, item.event_time or now_utc),
        reverse=True,
    )
    academic_pressure = _academic_pressure_summary(
        repository,
        student_ids=scoped_student_ids,
        academic_progress_rows=academic_progress_rows,
        semester_rows=semester_rows,
        subject_rows=attendance_rows,
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
        total_students_with_overall_shortage=int(academic_pressure["total_students_with_overall_shortage"]),
        total_students_with_i_grade_risk=int(academic_pressure["total_students_with_i_grade_risk"]),
        total_students_with_r_grade_risk=int(academic_pressure["total_students_with_r_grade_risk"]),
        total_students_with_active_academic_burden=active_burden_count,
        total_students_with_active_i_grade_burden=active_i_grade_burden_count,
        total_students_with_active_r_grade_burden=active_r_grade_burden_count,
        top_subject_pressure=list(academic_pressure["top_subject_pressure"]),
        branch_pressure=list(academic_pressure["branch_pressure"]),
        semester_pressure=list(academic_pressure["semester_pressure"]),
        active_recovery_students=active_recovery_students,
        expired_recovery_students=expired_recovery_students,
        escalated_students=escalated_students,
        followup_reminder_students=followup_reminder_students,
        resolution_candidate_students=resolution_candidate_students,
        reopened_case_students=reopened_case_students,
        critical_unattended_case_students=critical_unattended_case_students,
        repeated_risk_students=repeated_risk_students,
        unhandled_escalation_students=unhandled_escalation_students,
        academic_burden_monitoring_students=academic_burden_monitoring_students,
    )
