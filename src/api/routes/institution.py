from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.academic_pressure import build_academic_pressure_snapshot
from src.api.auth import AuthContext, require_roles
from src.api.institutional_analytics import (
    build_institution_risk_overview,
    resolve_department_label,
    resolve_semester_label,
)
from src.api.risk_classification import classify_risk_level
from src.api.schemas import (
    AcademicPressureBucketItem,
    AcademicSubjectPressureItem,
    CounsellorAccountabilityItem,
    CounsellorAccountabilityResponse,
    InstitutionAcademicPressureResponse,
    InstitutionBucketSummary,
    InstitutionHeatmapCell,
    InstitutionRiskOverviewResponse,
    OutcomeDistributionItem,
    RiskTypeDistributionItem,
    StudentDirectoryItem,
    StudentDirectoryResponse,
)
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/institution", tags=["institution"])
_INSTITUTION_OVERVIEW_CACHE_TTL_SECONDS = 300.0
_INSTITUTION_OVERVIEW_CACHE_LOCK = Lock()
_INSTITUTION_OVERVIEW_CACHE: dict[str, tuple[float, InstitutionRiskOverviewResponse]] = {}
_INSTITUTION_ACADEMIC_PRESSURE_CACHE_LOCK = Lock()
_INSTITUTION_ACADEMIC_PRESSURE_CACHE: dict[
    str, tuple[float, InstitutionAcademicPressureResponse]
] = {}


def _overview_cache_key(*, imported_only: bool, include_academic_pressure: bool) -> str:
    return f"risk-overview:{int(imported_only)}:{int(include_academic_pressure)}"


def _academic_pressure_cache_key(*, imported_only: bool) -> str:
    return f"academic-pressure:{int(imported_only)}"


def _overview_cache_lookup(key: str) -> InstitutionRiskOverviewResponse | None:
    with _INSTITUTION_OVERVIEW_CACHE_LOCK:
        entry = _INSTITUTION_OVERVIEW_CACHE.get(key)
        if entry is None:
            return None
        created_at, value = entry
        if monotonic() - created_at > _INSTITUTION_OVERVIEW_CACHE_TTL_SECONDS:
            return None
        return value


def _overview_cache_store(
    key: str,
    value: InstitutionRiskOverviewResponse,
) -> InstitutionRiskOverviewResponse:
    with _INSTITUTION_OVERVIEW_CACHE_LOCK:
        _INSTITUTION_OVERVIEW_CACHE[key] = (monotonic(), value)
    return value


def _academic_pressure_cache_lookup(
    key: str,
) -> InstitutionAcademicPressureResponse | None:
    with _INSTITUTION_ACADEMIC_PRESSURE_CACHE_LOCK:
        entry = _INSTITUTION_ACADEMIC_PRESSURE_CACHE.get(key)
        if entry is None:
            return None
        created_at, value = entry
        if monotonic() - created_at > _INSTITUTION_OVERVIEW_CACHE_TTL_SECONDS:
            return None
        return value


def _academic_pressure_cache_store(
    key: str,
    value: InstitutionAcademicPressureResponse,
) -> InstitutionAcademicPressureResponse:
    with _INSTITUTION_ACADEMIC_PRESSURE_CACHE_LOCK:
        _INSTITUTION_ACADEMIC_PRESSURE_CACHE[key] = (monotonic(), value)
    return value


def _latest_by_student(rows: list[object]) -> dict[int, object]:
    latest: dict[int, object] = {}
    for row in rows:
        latest.setdefault(int(row.student_id), row)
    return latest


def _rows_by_student(rows: list[object]) -> dict[int, list[object]]:
    grouped: dict[int, list[object]] = {}
    for row in rows:
        grouped.setdefault(int(row.student_id), []).append(row)
    return grouped


def _prediction_primary_risk_type(prediction) -> str:
    payload = getattr(prediction, "risk_type", None) or {}
    if not isinstance(payload, dict):
        return "unavailable"
    value = payload.get("primary_type")
    if value in (None, ""):
        return "unavailable"
    return str(value)


def _prediction_has_critical_trigger(prediction) -> bool:
    payload = getattr(prediction, "trigger_alerts", None) or {}
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("has_critical_trigger"))


def _resolve_latest_prediction_scope(
    repository: EventRepository,
    *,
    imported_only: bool,
) -> list[object]:
    latest_predictions = repository.get_latest_predictions_for_all_students()
    if not imported_only:
        return latest_predictions
    imported_student_ids = {
        int(profile.student_id) for profile in repository.get_imported_student_profiles()
    }
    return [
        prediction
        for prediction in latest_predictions
        if int(prediction.student_id) in imported_student_ids
    ]


def _empty_academic_pressure_summary() -> dict:
    return {
        "total_students_with_overall_shortage": 0,
        "total_students_with_i_grade_risk": 0,
        "total_students_with_r_grade_risk": 0,
        "top_subject_pressure": [],
        "branch_pressure": [],
        "semester_pressure": [],
    }


def _academic_pressure_summary(repository: EventRepository, *, student_ids: set[int] | None = None) -> dict:
    snapshot = build_academic_pressure_snapshot(
        repository,
        student_ids=student_ids,
        subject_limit=8,
        bucket_limit=8,
        top_student_limit=8,
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


@router.get("/risk-overview", response_model=InstitutionRiskOverviewResponse)
def get_institution_risk_overview(
    imported_only: bool = False,
    include_academic_pressure: bool = True,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> InstitutionRiskOverviewResponse:
    cache_key = _overview_cache_key(
        imported_only=imported_only,
        include_academic_pressure=include_academic_pressure,
    )
    cached = _overview_cache_lookup(cache_key)
    if cached is not None:
        return cached

    repository = EventRepository(db)
    latest_predictions = _resolve_latest_prediction_scope(
        repository,
        imported_only=imported_only,
    )

    student_ids = {int(prediction.student_id) for prediction in latest_predictions}
    profiles_by_student = (
        repository.get_student_profiles_for_students(student_ids)
        if include_academic_pressure
        else {}
    )
    latest_erp_by_student = repository.get_latest_erp_events_for_students(student_ids)
    latest_intervention_by_student = {
        int(row.student_id): row
        for row in repository.get_latest_intervention_actions_for_students(student_ids)
    }
    latest_alert_by_student = {
        int(row.student_id): row
        for row in repository.get_latest_alert_events_for_students(student_ids)
    }
    latest_guardian_alert_by_student = _latest_by_student(
        repository.get_guardian_alert_events_for_students(student_ids)
    )
    repeated_high_risk_count_by_student: dict[int, int] = {}
    if include_academic_pressure:
        for row in repository.get_prediction_history_for_students(student_ids):
            if int(row.final_predicted_class) != 1:
                continue
            student_id = int(row.student_id)
            repeated_high_risk_count_by_student[student_id] = (
                repeated_high_risk_count_by_student.get(student_id, 0) + 1
            )

    student_rows: list[dict] = []
    for prediction in latest_predictions:
        student_id = int(prediction.student_id)
        profile = profiles_by_student.get(student_id)
        latest_erp_event = latest_erp_by_student.get(student_id)
        latest_intervention = latest_intervention_by_student.get(student_id)
        latest_alert = latest_alert_by_student.get(student_id)
        latest_guardian_alert = latest_guardian_alert_by_student.get(student_id)

        latest_intervention_status = (
            str(latest_intervention.action_status).strip().lower()
            if latest_intervention is not None
            else None
        )
        followup_overdue = bool(
            latest_alert is not None
            and latest_alert.alert_type == "faculty_followup_reminder"
            and latest_intervention_status
            not in {"seen", "acknowledged", "contacted", "support_provided", "resolved"}
        )

        student_rows.append(
            {
                "student_id": student_id,
                "department_label": resolve_department_label(profile, latest_erp_event),
                "semester_label": resolve_semester_label(latest_erp_event),
                "category_label": _resolve_profile_context_label(profile, "category", "unknown_category"),
                "region_label": _resolve_profile_context_label(profile, "region", "unknown_region"),
                "income_label": _resolve_profile_context_label(profile, "income", "unknown_income"),
                "risk_level": classify_risk_level(float(prediction.final_risk_probability)),
                "final_risk_probability": float(prediction.final_risk_probability),
                "risk_type": _prediction_primary_risk_type(prediction),
                "has_critical_trigger": _prediction_has_critical_trigger(prediction),
                "followup_overdue": followup_overdue,
                "has_guardian_escalation": latest_guardian_alert is not None,
                "is_reopened_case": bool(
                    latest_alert is not None
                    and latest_alert.alert_type == "faculty_followup_reminder"
                    and int(prediction.final_predicted_class) == 1
                    and latest_intervention_status == "resolved"
                ),
                "is_repeated_risk_case": repeated_high_risk_count_by_student.get(student_id, 0) >= 2,
                "outcome_status": _resolve_outcome_status(profile),
            }
        )

    summary = build_institution_risk_overview(student_rows=student_rows)
    academic_pressure = (
        _academic_pressure_summary(
            repository,
            student_ids={int(row["student_id"]) for row in student_rows},
        )
        if include_academic_pressure
        else _empty_academic_pressure_summary()
    )

    response = InstitutionRiskOverviewResponse(
        generated_at=to_ist(summary["generated_at"]),
        total_students=int(summary["total_students"]),
        total_high_risk_students=int(summary["total_high_risk_students"]),
        total_medium_risk_students=int(summary["total_medium_risk_students"]),
        total_low_risk_students=int(summary["total_low_risk_students"]),
        total_safe_students=int(summary["total_safe_students"]),
        total_critical_trigger_students=int(summary["total_critical_trigger_students"]),
        total_followup_overdue_students=int(summary["total_followup_overdue_students"]),
        total_guardian_escalation_students=int(summary["total_guardian_escalation_students"]),
        total_reopened_cases=int(summary["total_reopened_cases"]),
        total_repeated_risk_students=int(summary["total_repeated_risk_students"]),
        total_dropped_students=int(summary["total_dropped_students"]),
        total_studying_students=int(summary["total_studying_students"]),
        total_graduated_students=int(summary["total_graduated_students"]),
        total_students_with_overall_shortage=int(academic_pressure["total_students_with_overall_shortage"]),
        total_students_with_i_grade_risk=int(academic_pressure["total_students_with_i_grade_risk"]),
        total_students_with_r_grade_risk=int(academic_pressure["total_students_with_r_grade_risk"]),
        department_buckets=[
            InstitutionBucketSummary(**item) for item in summary["department_buckets"]
        ],
        semester_buckets=[
            InstitutionBucketSummary(**item) for item in summary["semester_buckets"]
        ],
        category_buckets=[
            InstitutionBucketSummary(**item) for item in summary["category_buckets"]
        ],
        region_buckets=[
            InstitutionBucketSummary(**item) for item in summary["region_buckets"]
        ],
        income_buckets=[
            InstitutionBucketSummary(**item) for item in summary["income_buckets"]
        ],
        heatmap_cells=[
            InstitutionHeatmapCell(**item) for item in summary["heatmap_cells"]
        ],
        top_risk_types=[
            RiskTypeDistributionItem(**item) for item in summary["top_risk_types"]
        ],
        top_subject_pressure=list(academic_pressure["top_subject_pressure"]),
        branch_pressure=list(academic_pressure["branch_pressure"]),
        semester_pressure=list(academic_pressure["semester_pressure"]),
        outcome_distribution=[
            OutcomeDistributionItem(**item) for item in summary["outcome_distribution"]
        ],
        summary=str(summary["summary"]),
    )
    return _overview_cache_store(cache_key, response)


@router.get("/academic-pressure", response_model=InstitutionAcademicPressureResponse)
def get_institution_academic_pressure(
    imported_only: bool = False,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> InstitutionAcademicPressureResponse:
    cache_key = _academic_pressure_cache_key(imported_only=imported_only)
    cached = _academic_pressure_cache_lookup(cache_key)
    if cached is not None:
        return cached

    repository = EventRepository(db)
    latest_predictions = _resolve_latest_prediction_scope(
        repository,
        imported_only=imported_only,
    )
    student_ids = {int(prediction.student_id) for prediction in latest_predictions}
    academic_pressure = _academic_pressure_summary(
        repository,
        student_ids=student_ids,
    )
    response = InstitutionAcademicPressureResponse(
        total_students_with_overall_shortage=int(
            academic_pressure["total_students_with_overall_shortage"]
        ),
        total_students_with_i_grade_risk=int(
            academic_pressure["total_students_with_i_grade_risk"]
        ),
        total_students_with_r_grade_risk=int(
            academic_pressure["total_students_with_r_grade_risk"]
        ),
        top_subject_pressure=list(academic_pressure["top_subject_pressure"]),
        branch_pressure=list(academic_pressure["branch_pressure"]),
        semester_pressure=list(academic_pressure["semester_pressure"]),
    )
    return _academic_pressure_cache_store(cache_key, response)


def _resolve_outcome_status(profile) -> str:
    if profile is None:
        return "unknown"
    profile_context = getattr(profile, "profile_context", None) or {}
    registration = profile_context.get("registration") or {}
    value = registration.get("final_status")
    if value in (None, ""):
        return "unknown"
    return str(value)


def _resolve_profile_context_label(profile, key: str, fallback: str) -> str:
    if profile is None:
        return fallback
    profile_context = getattr(profile, "profile_context", None) or {}
    value = profile_context.get(key)
    if value in (None, ""):
        return fallback
    return str(value)


def _extract_risk_reasons(prediction) -> list[str]:
    reasons = []
    if not prediction:
        return reasons
    risk_type = getattr(prediction, "risk_type", None) or {}
    primary = risk_type.get("primary_type", "")
    if primary == "attendance_driven":
        reasons.append("Low attendance is the primary risk driver.")
    elif primary == "academic_decline":
        reasons.append("Academic performance has declined significantly.")
    elif primary == "engagement_drop":
        reasons.append("LMS engagement and submission rates have dropped.")
    elif primary == "finance_driven":
        reasons.append("Fee payment delays are amplifying risk.")

    trigger_alerts = getattr(prediction, "trigger_alerts", None) or {}
    triggers = trigger_alerts.get("triggers", []) if isinstance(trigger_alerts, dict) else (getattr(trigger_alerts, "triggers", []) or [])
    for t in triggers[:2]:
        title = t.get("title") if isinstance(t, dict) else getattr(t, "title", None)
        if title and title not in reasons:
            reasons.append(title)

    if not reasons:
        actions = getattr(prediction, "recommended_actions", None) or []
        for a in actions[:1]:
            title = a.get("title") if isinstance(a, dict) else getattr(a, "title", None)
            if title:
                reasons.append(f"Recommended action: {title}")

    return reasons[:3]


@router.get("/students", response_model=StudentDirectoryResponse)
def list_students_by_risk(
    risk_level: str | None = None,
    branch: str | None = None,
    year: int | None = None,
    semester: int | None = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> StudentDirectoryResponse:
    from src.api.attendance_engine import build_attendance_summary
    from src.api.routes.cases import _build_case_state_from_rows

    repository = EventRepository(db)
    imported_profiles = repository.get_imported_student_profiles()
    profiles_by_student = {int(profile.student_id): profile for profile in imported_profiles}
    imported_student_ids = set(profiles_by_student)
    all_predictions = repository.get_latest_predictions_for_students(imported_student_ids)
    latest_erp_by_student = repository.get_latest_erp_events_for_students(imported_student_ids)

    filtered_students = []
    for prediction in all_predictions:
        student_id = int(prediction.student_id)
        if student_id not in imported_student_ids:
            continue
        
        current_risk_level = classify_risk_level(float(prediction.final_risk_probability))
        if risk_level and risk_level.upper() != "ALL" and current_risk_level != risk_level.upper():
            continue
            
        profile = profiles_by_student.get(student_id)
        latest_erp = latest_erp_by_student.get(student_id)
        
        student_branch = resolve_department_label(profile, latest_erp)
        if branch and branch.lower() != student_branch.lower():
            continue
            
        context = getattr(latest_erp, "context_fields", None) or {}
        
        if year is not None:
            student_year = context.get("year_of_study")
            if str(student_year) != str(year):
                continue
                
        if semester is not None:
            student_semester = context.get("semester_number")
            if str(student_semester) != str(semester):
                continue

        filtered_students.append((student_id, prediction, profile, latest_erp))

    # Pagination
    total = len(filtered_students)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_batch = filtered_students[start_idx:end_idx]
    paginated_student_ids = {student_id for student_id, _, _, _ in paginated_batch}
    latest_intervention_by_student = _latest_by_student(
        repository.get_latest_intervention_actions_for_students(paginated_student_ids)
    )
    intervention_history_by_student = _rows_by_student(
        repository.get_intervention_actions_for_students(paginated_student_ids)
    )
    latest_finance_by_student = repository.get_latest_finance_events_for_students(paginated_student_ids)
    prediction_history_by_student = _rows_by_student(
        repository.get_prediction_history_for_students(paginated_student_ids)
    )
    latest_warning_by_student = _latest_by_student(
        repository.get_latest_student_warning_events_for_students(paginated_student_ids)
    )
    latest_alert_by_student = _latest_by_student(
        repository.get_latest_alert_events_for_students(paginated_student_ids)
    )
    latest_guardian_alert_by_student = _latest_by_student(
        repository.get_guardian_alert_events_for_students(paginated_student_ids)
    )

    students_out = []
    for student_id, prediction, profile, latest_erp in paginated_batch:
        context = getattr(latest_erp, "context_fields", None) or {}
        attendance_summary = build_attendance_summary(context)
        overall_attendance = attendance_summary.get("attendance_ratio")
        if overall_attendance is not None:
            overall_attendance = float(overall_attendance) * 100

        intervention_history = intervention_history_by_student.get(student_id, [])
        latest_intervention = latest_intervention_by_student.get(student_id)
        latest_intervention_status = (
            str(latest_intervention.action_status).strip().lower()
            if latest_intervention is not None else None
        )

        lms_events = []
        latest_finance = latest_finance_by_student.get(student_id)
        prediction_history = prediction_history_by_student.get(student_id, [prediction])
        latest_warning = latest_warning_by_student.get(student_id)
        latest_alert = latest_alert_by_student.get(student_id)
        latest_guardian_alert = latest_guardian_alert_by_student.get(student_id)

        case_state_obj = _build_case_state_from_rows(
            student_id=student_id,
            profile=profile,
            lms_events=lms_events,
            latest_prediction=prediction,
            latest_erp_event=latest_erp,
            latest_finance_event=latest_finance,
            latest_warning=latest_warning,
            latest_alert=latest_alert,
            latest_guardian_alert=latest_guardian_alert,
            latest_intervention=latest_intervention,
            prediction_history=prediction_history,
            intervention_history=intervention_history,
        )

        followup_overdue = bool(
            latest_alert is not None
            and latest_alert.alert_type == "faculty_followup_reminder"
            and latest_intervention_status not in {"seen", "acknowledged", "contacted", "support_provided", "resolved"}
        )

        item = StudentDirectoryItem(
            student_id=student_id,
            risk_level=classify_risk_level(float(prediction.final_risk_probability)),
            risk_probability=float(prediction.final_risk_probability),
            counsellor_name=getattr(profile, "counsellor_name", None),
            counsellor_email=getattr(profile, "counsellor_email", None),
            branch=resolve_department_label(profile, latest_erp),
            year=str(context.get("year_of_study")) if context.get("year_of_study") else None,
            semester=str(context.get("semester_number")) if context.get("semester_number") else None,
            overall_attendance_percent=overall_attendance,
            top_risk_reasons=_extract_risk_reasons(prediction),
            latest_intervention_status=latest_intervention_status,
            case_state=case_state_obj.current_case_state,
            has_overdue_followup=followup_overdue
        )
        students_out.append(item)

    return StudentDirectoryResponse(
        total_students=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size if total > 0 else 1,
        students=students_out
    )


@router.get("/counsellor-accountability", response_model=CounsellorAccountabilityResponse)
def get_counsellor_accountability(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> CounsellorAccountabilityResponse:
    from collections import defaultdict

    repository = EventRepository(db)
    all_predictions = repository.get_latest_predictions_for_all_students()
    imported_profiles = repository.get_imported_student_profiles()
    profiles_by_student = {int(p.student_id): p for p in imported_profiles}
    imported_ids = set(profiles_by_student)
    latest_intervention_by_student = _latest_by_student(
        repository.get_latest_intervention_actions_for_students(imported_ids)
    )
    latest_alert_by_student = _latest_by_student(
        repository.get_latest_alert_events_for_students(imported_ids)
    )

    # Group students by counsellor
    counsellor_groups: dict[str, list[dict]] = defaultdict(list)

    for prediction in all_predictions:
        student_id = int(prediction.student_id)
        if student_id not in imported_ids:
            continue

        profile = profiles_by_student.get(student_id)
        counsellor_name = getattr(profile, "counsellor_name", None) or "Unassigned"
        counsellor_email = getattr(profile, "counsellor_email", None)
        risk_level = classify_risk_level(float(prediction.final_risk_probability))

        latest_intervention = latest_intervention_by_student.get(student_id)
        latest_status = (
            str(latest_intervention.action_status).strip().lower()
            if latest_intervention else None
        )

        latest_alert = latest_alert_by_student.get(student_id)

        followup_overdue = bool(
            latest_alert is not None
            and latest_alert.alert_type == "faculty_followup_reminder"
            and latest_status not in {"seen", "acknowledged", "contacted", "support_provided", "resolved"}
        )

        pending = bool(
            latest_alert is not None
            and latest_status not in {"seen", "acknowledged", "contacted", "support_provided", "resolved"}
        )

        counsellor_groups[counsellor_name].append({
            "counsellor_email": counsellor_email,
            "risk_level": risk_level,
            "followup_overdue": followup_overdue,
            "pending": pending,
            "last_action_date": (
                latest_intervention.created_at if latest_intervention else None
            ),
        })

    counsellors_out = []
    for name, students in sorted(counsellor_groups.items()):
        high = sum(1 for s in students if s["risk_level"] == "HIGH")
        medium = sum(1 for s in students if s["risk_level"] == "MEDIUM")
        pending_count = sum(1 for s in students if s["pending"])
        overdue_count = sum(1 for s in students if s["followup_overdue"])

        action_dates = [s["last_action_date"] for s in students if s["last_action_date"]]
        last_action = max(action_dates) if action_dates else None

        if overdue_count > 0:
            perf = "overdue"
        elif pending_count > 2:
            perf = "needs_attention"
        else:
            perf = "on_track"

        counsellors_out.append(CounsellorAccountabilityItem(
            counsellor_name=name,
            counsellor_email=students[0].get("counsellor_email"),
            total_assigned=len(students),
            high_risk_count=high,
            medium_risk_count=medium,
            pending_interventions=pending_count,
            overdue_followups=overdue_count,
            last_action_date=last_action,
            performance_label=perf,
        ))

    return CounsellorAccountabilityResponse(
        total_counsellors=len(counsellors_out),
        counsellors=counsellors_out,
    )
