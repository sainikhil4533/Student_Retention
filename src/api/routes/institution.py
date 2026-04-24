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
    InstitutionBucketSummary,
    InstitutionHeatmapCell,
    InstitutionRiskOverviewResponse,
    OutcomeDistributionItem,
    RiskTypeDistributionItem,
    StudentDirectoryItem,
    StudentDirectoryResponse,
)
from src.api.student_intelligence import build_current_student_intelligence
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/institution", tags=["institution"])


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
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> InstitutionRiskOverviewResponse:
    repository = EventRepository(db)
    latest_predictions = repository.get_latest_predictions_for_all_students()
    if imported_only:
        imported_student_ids = {
            int(profile.student_id) for profile in repository.get_imported_student_profiles()
        }
        latest_predictions = [
            prediction
            for prediction in latest_predictions
            if int(prediction.student_id) in imported_student_ids
        ]

    student_rows: list[dict] = []
    for prediction in latest_predictions:
        student_id = int(prediction.student_id)
        profile = repository.get_student_profile(student_id)
        latest_erp_event = repository.get_latest_erp_event(student_id)
        latest_finance_event = repository.get_latest_finance_event(student_id)
        intervention_history = repository.get_intervention_history_for_student(student_id)
        latest_intervention = intervention_history[0] if intervention_history else None
        alert_history = repository.get_alert_history_for_student(student_id)
        latest_alert = alert_history[0] if alert_history else None
        guardian_alert_history = repository.get_guardian_alert_history_for_student(student_id)
        latest_guardian_alert = guardian_alert_history[0] if guardian_alert_history else None
        lms_events = repository.get_lms_events_for_student(student_id)
        prediction_rows = repository.get_prediction_history_for_student(student_id)

        intelligence = None
        if lms_events and latest_erp_event is not None:
            intelligence = build_current_student_intelligence(
                prediction_rows=prediction_rows,
                latest_prediction=prediction,
                lms_events=lms_events,
                erp_event=latest_erp_event,
                erp_history=repository.get_erp_event_history_for_student(student_id),
                finance_event=latest_finance_event,
                finance_history=repository.get_finance_event_history_for_student(student_id),
                previous_prediction=prediction_rows[1]
                if len(prediction_rows) >= 2
                else None,
            )

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
                "risk_type": (
                    str(intelligence["risk_type"]["primary_type"])
                    if intelligence is not None
                    else "unavailable"
                ),
                "has_critical_trigger": (
                    bool(intelligence["trigger_alerts"]["has_critical_trigger"])
                    if intelligence is not None
                    else False
                ),
                "followup_overdue": followup_overdue,
                "has_guardian_escalation": latest_guardian_alert is not None,
                "is_reopened_case": bool(
                    latest_alert is not None
                    and latest_alert.alert_type == "faculty_followup_reminder"
                    and int(prediction.final_predicted_class) == 1
                    and latest_intervention_status == "resolved"
                ),
                "is_repeated_risk_case": len(
                    [row for row in prediction_rows if int(row.final_predicted_class) == 1]
                )
                >= 2,
                "outcome_status": _resolve_outcome_status(profile),
            }
        )

    summary = build_institution_risk_overview(student_rows=student_rows)
    academic_pressure = _academic_pressure_summary(
        repository,
        student_ids={int(row["student_id"]) for row in student_rows},
    )

    return InstitutionRiskOverviewResponse(
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
    all_predictions = repository.get_latest_predictions_for_all_students()
    imported_student_ids = {
        int(profile.student_id) for profile in repository.get_imported_student_profiles()
    }

    filtered_students = []
    for prediction in all_predictions:
        student_id = int(prediction.student_id)
        if student_id not in imported_student_ids:
            continue
        
        current_risk_level = classify_risk_level(float(prediction.final_risk_probability))
        if risk_level and risk_level.upper() != "ALL" and current_risk_level != risk_level.upper():
            continue
            
        profile = repository.get_student_profile(student_id)
        latest_erp = repository.get_latest_erp_event(student_id)
        
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

    students_out = []
    for student_id, prediction, profile, latest_erp in paginated_batch:
        context = getattr(latest_erp, "context_fields", None) or {}
        attendance_summary = build_attendance_summary(context)
        overall_attendance = attendance_summary.get("attendance_ratio")
        if overall_attendance is not None:
            overall_attendance = float(overall_attendance) * 100

        intervention_history = repository.get_intervention_history_for_student(student_id)
        latest_intervention = intervention_history[0] if intervention_history else None
        latest_intervention_status = (
            str(latest_intervention.action_status).strip().lower()
            if latest_intervention is not None else None
        )

        lms_events = repository.get_lms_events_for_student(student_id)
        latest_finance = repository.get_latest_finance_event(student_id)
        prediction_history = repository.get_prediction_history_for_student(student_id)
        warning_history = repository.get_student_warning_history_for_student(student_id)
        latest_warning = warning_history[0] if warning_history else None
        alert_history = repository.get_alert_history_for_student(student_id)
        latest_alert = alert_history[0] if alert_history else None
        guardian_alert_history = repository.get_guardian_alert_history_for_student(student_id)
        latest_guardian_alert = guardian_alert_history[0] if guardian_alert_history else None

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
    imported_ids = {
        int(p.student_id) for p in repository.get_imported_student_profiles()
    }

    # Group students by counsellor
    counsellor_groups: dict[str, list[dict]] = defaultdict(list)

    for prediction in all_predictions:
        student_id = int(prediction.student_id)
        if student_id not in imported_ids:
            continue

        profile = repository.get_student_profile(student_id)
        counsellor_name = getattr(profile, "counsellor_name", None) or "Unassigned"
        counsellor_email = getattr(profile, "counsellor_email", None)
        risk_level = classify_risk_level(float(prediction.final_risk_probability))

        intervention_history = repository.get_intervention_history_for_student(student_id)
        latest_intervention = intervention_history[0] if intervention_history else None
        latest_status = (
            str(latest_intervention.action_status).strip().lower()
            if latest_intervention else None
        )

        alert_history = repository.get_alert_history_for_student(student_id)
        latest_alert = alert_history[0] if alert_history else None

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
