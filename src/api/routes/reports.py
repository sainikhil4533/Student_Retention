from datetime import UTC, datetime
import csv
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles
from src.api.routes.faculty import get_faculty_priority_queue, get_faculty_summary
from src.api.routes.institution import get_institution_risk_overview
from src.api.routes.interventions import get_intervention_effectiveness_analytics
from src.api.schemas import (
    FacultySummarySnapshotHistoryResponse,
    FacultySummarySnapshotItem,
    ImportCoverageResponse,
    ImportCoverageStudentItem,
    OperationalReportOverviewResponse,
)
from src.api.time_utils import to_ist
from src.db.database import get_db
from src.db.repository import EventRepository
from src.reporting.faculty_summary_snapshot_service import (
    create_faculty_summary_snapshot,
    deliver_faculty_summary_snapshot_email,
    serialize_faculty_summary_snapshot,
)


router = APIRouter(prefix="/reports", tags=["reports"])
_SYSTEM_AUTH = AuthContext(role="system", subject="system")


def _csv_response(filename: str, fieldnames: list[str], rows: list[dict]) -> PlainTextResponse:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    response = PlainTextResponse(buffer.getvalue(), media_type="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@router.get("/operations-overview", response_model=OperationalReportOverviewResponse)
def get_operational_report_overview(
    imported_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> OperationalReportOverviewResponse:
    return OperationalReportOverviewResponse(
        generated_at=to_ist(datetime.now(UTC)),
        summary=get_faculty_summary(db=db, auth=_SYSTEM_AUTH),
        institution_overview=get_institution_risk_overview(db=db, imported_only=imported_only, auth=_SYSTEM_AUTH),
        intervention_effectiveness=get_intervention_effectiveness_analytics(db=db, auth=_SYSTEM_AUTH),
    )


@router.post("/faculty-summary/generate", response_model=FacultySummarySnapshotItem)
def generate_faculty_summary_snapshot(
    snapshot_type: str = Query(default="manual"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> FacultySummarySnapshotItem:
    return create_faculty_summary_snapshot(db, snapshot_type=snapshot_type)


@router.post("/faculty-summary/send-latest", response_model=FacultySummarySnapshotItem)
def send_latest_faculty_summary_snapshot(
    snapshot_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> FacultySummarySnapshotItem:
    repository = EventRepository(db)
    row = repository.get_latest_faculty_summary_snapshot(snapshot_type=snapshot_type)
    if row is None:
        raise HTTPException(status_code=404, detail="No faculty summary snapshot found.")
    return deliver_faculty_summary_snapshot_email(db, snapshot_id=row.id)


@router.get("/faculty-summary/latest", response_model=FacultySummarySnapshotItem)
def get_latest_faculty_summary_snapshot(
    snapshot_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> FacultySummarySnapshotItem:
    repository = EventRepository(db)
    row = repository.get_latest_faculty_summary_snapshot(snapshot_type=snapshot_type)
    if row is None:
        raise HTTPException(status_code=404, detail="No faculty summary snapshot found.")
    return serialize_faculty_summary_snapshot(row)


@router.get("/faculty-summary/history", response_model=FacultySummarySnapshotHistoryResponse)
def get_faculty_summary_snapshot_history(
    snapshot_type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> FacultySummarySnapshotHistoryResponse:
    repository = EventRepository(db)
    rows = repository.get_faculty_summary_snapshot_history(
        snapshot_type=snapshot_type,
        limit=limit,
    )
    snapshots = [serialize_faculty_summary_snapshot(row) for row in rows]
    return FacultySummarySnapshotHistoryResponse(
        total_snapshots=len(snapshots),
        snapshots=snapshots,
    )


@router.get("/exports/priority-queue")
def export_priority_queue_csv(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> PlainTextResponse:
    queue = get_faculty_priority_queue(db).queue
    rows = [
        {
            "student_id": item.student_id,
            "risk_level": item.current_risk_level,
            "final_risk_probability": item.final_risk_probability,
            "priority_score": item.priority_score,
            "priority_label": item.priority_label,
            "risk_type": item.risk_type,
            "recommended_next_action": item.recommended_next_action,
            "sla_status": item.sla_status,
        }
        for item in queue
    ]
    return _csv_response(
        "priority_queue_export.csv",
        [
            "student_id",
            "risk_level",
            "final_risk_probability",
            "priority_score",
            "priority_label",
            "risk_type",
            "recommended_next_action",
            "sla_status",
        ],
        rows,
    )


@router.get("/exports/institution-overview")
def export_institution_overview_csv(
    imported_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> PlainTextResponse:
    overview = get_institution_risk_overview(db=db, imported_only=imported_only)
    rows = [
        {
            "department_label": item.department_label,
            "semester_label": item.semester_label,
            "total_students": item.total_students,
            "high_risk_students": item.high_risk_students,
            "critical_trigger_students": item.critical_trigger_students,
            "guardian_escalation_students": item.guardian_escalation_students,
            "average_risk_probability": item.average_risk_probability,
        }
        for item in overview.heatmap_cells
    ]
    return _csv_response(
        "institution_risk_overview.csv",
        [
            "department_label",
            "semester_label",
            "total_students",
            "high_risk_students",
            "critical_trigger_students",
            "guardian_escalation_students",
            "average_risk_probability",
        ],
        rows,
    )


@router.get("/exports/outcome-distribution")
def export_outcome_distribution_csv(
    imported_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> PlainTextResponse:
    overview = get_institution_risk_overview(db=db, imported_only=imported_only)
    rows = [
        {
            "outcome_status": item.outcome_status,
            "student_count": item.student_count,
        }
        for item in overview.outcome_distribution
    ]
    return _csv_response(
        "outcome_distribution.csv",
        ["outcome_status", "student_count"],
        rows,
    )


@router.get("/exports/intervention-effectiveness")
def export_intervention_effectiveness_csv(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> PlainTextResponse:
    analytics = get_intervention_effectiveness_analytics(db)
    rows = [
        {
            "action_status": item.action_status,
            "total_actions": item.total_actions,
            "reviewed_actions": item.reviewed_actions,
            "review_rate": item.review_rate,
            "false_alert_count": item.false_alert_count,
            "false_alert_rate": item.false_alert_rate,
            "outcomes_recorded": item.outcomes_recorded,
            "improved_count": item.improved_count,
            "unresolved_count": item.unresolved_count,
            "effectiveness_score": item.effectiveness_score,
            "summary": item.summary,
        }
        for item in analytics.action_effectiveness
    ]
    return _csv_response(
        "intervention_effectiveness.csv",
        [
            "action_status",
            "total_actions",
            "reviewed_actions",
            "review_rate",
            "false_alert_count",
            "false_alert_rate",
            "outcomes_recorded",
            "improved_count",
            "unresolved_count",
            "effectiveness_score",
            "summary",
        ],
        rows,
    )


@router.get("/import-coverage", response_model=ImportCoverageResponse)
def get_import_coverage_report(
    imported_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> ImportCoverageResponse:
    repository = EventRepository(db)
    profiles = (
        repository.get_imported_student_profiles()
        if imported_only
        else repository.get_all_student_profiles()
    )

    students: list[ImportCoverageStudentItem] = []
    students_missing_lms = 0
    students_missing_erp = 0
    students_missing_finance = 0
    students_missing_student_email = 0
    students_missing_faculty_email = 0
    students_missing_counsellor_email = 0
    scored_students = 0

    for profile in profiles:
        student_id = int(profile.student_id)
        has_lms_data = bool(repository.get_lms_events_for_student(student_id))
        has_erp_data = repository.get_latest_erp_event(student_id) is not None
        has_finance_data = repository.get_latest_finance_event(student_id) is not None
        has_prediction = repository.get_latest_prediction_for_student(student_id) is not None
        if has_prediction:
            scored_students += 1

        missing_reasons: list[str] = []
        if not has_lms_data:
            students_missing_lms += 1
            missing_reasons.append("missing_lms_data")
        if not has_erp_data:
            students_missing_erp += 1
            missing_reasons.append("missing_erp_data")
        if not has_finance_data:
            students_missing_finance += 1
            missing_reasons.append("missing_finance_data")
        if not getattr(profile, "student_email", None):
            students_missing_student_email += 1
            missing_reasons.append("missing_student_email")
        if not getattr(profile, "faculty_email", None):
            students_missing_faculty_email += 1
            missing_reasons.append("missing_faculty_email")
        if not getattr(profile, "counsellor_email", None):
            students_missing_counsellor_email += 1
            missing_reasons.append("missing_counsellor_email")

        profile_context = getattr(profile, "profile_context", None) or {}
        registration = profile_context.get("registration") or {}
        students.append(
            ImportCoverageStudentItem(
                student_id=student_id,
                external_student_ref=getattr(profile, "external_student_ref", None),
                student_email=getattr(profile, "student_email", None),
                faculty_email=getattr(profile, "faculty_email", None),
                counsellor_email=getattr(profile, "counsellor_email", None),
                has_lms_data=has_lms_data,
                has_erp_data=has_erp_data,
                has_finance_data=has_finance_data,
                has_prediction=has_prediction,
                outcome_status=registration.get("final_status"),
                missing_reasons=missing_reasons,
            )
        )

    total_students = len(profiles)
    return ImportCoverageResponse(
        total_imported_students=total_students,
        scored_students=scored_students,
        unscored_students=max(total_students - scored_students, 0),
        students_missing_lms=students_missing_lms,
        students_missing_erp=students_missing_erp,
        students_missing_finance=students_missing_finance,
        students_missing_student_email=students_missing_student_email,
        students_missing_faculty_email=students_missing_faculty_email,
        students_missing_counsellor_email=students_missing_counsellor_email,
        students=students[:limit],
    )
