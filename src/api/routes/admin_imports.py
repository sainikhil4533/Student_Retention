from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO, TextIOWrapper
import csv
import re
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
import openpyxl

from src.api.auth import AuthContext, require_roles
from src.api.dependencies import prediction_service
from src.api.scoring_service import score_student_from_db
from src.api.schemas import VignanImportResponse
from src.db.database import get_db
from src.db.repository import EventRepository
from src.worker.job_queue import (
    enqueue_faculty_alert_email_job,
    enqueue_student_warning_email_job,
)


router = APIRouter(prefix="/admin/imports", tags=["admin-imports"])

REQUIRED_SHEETS = {
    "Admissions",
    "Academics",
    "Attendance",
    "Finance",
    "Registration",
    "LMS",
}

OPTIONAL_SHEETS = {"SupportMapping"}

REQUIRED_COLUMNS = {
    "Admissions": {
        "registerno",
        "Branch",
        "Batch",
        "Category",
        "Region",
        "ParentEdu",
        "Occupation",
        "Income",
        "Gender",
        "AgeBand",
        "Attempts",
    },
    "Academics": {"registerno", "Semester", "CGPA", "Backlogs", "shortname", "Marks"},
    "Attendance": {
        "registerno",
        "Semester",
        "Overall%",
        "shortname",
        "Subject%",
        "ConsecutiveAbs",
        "MissedvDays",
        "Trend",
    },
    "Finance": {"registerno", "Status", "Due", "DelayDays", "Scholarship", "Modifier"},
    "Registration": {"registerno", "Semester", "Registered", "FinalStatus"},
    "LMS": {
        "registerno",
        "event_date",
        "id_site",
        "sum_click",
        "engagement_tag",
        "resource_type",
    },
}

OPTIONAL_REQUIRED_COLUMNS = {
    "SupportMapping": {
        "registerno",
        "student_email",
        "disability_status",
        "faculty_name",
        "faculty_email",
        "parent_name",
        "parent_relationship",
        "parent_email",
        "parent_phone",
        "preferred_guardian_channel",
        "guardian_contact_enabled",
        "counsellor_name",
        "counsellor_email",
    }
}

FAIRNESS_REVIEW_REQUIRED_PROFILE_FIELDS = (
    "category",
    "region",
    "income",
    "parent_education",
    "occupation",
)


@dataclass
class ImportCounters:
    profiles_upserted: int = 0
    support_mappings_applied: int = 0
    lms_events_ingested: int = 0
    erp_events_ingested: int = 0
    finance_events_ingested: int = 0
    scoring_triggered: int = 0


@router.post("/vignan", response_model=VignanImportResponse)
async def import_vignan(
    file: UploadFile = File(...),
    trigger_scoring: bool = True,
    dry_run: bool = False,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin")),
) -> VignanImportResponse:
    if file.filename is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload a .xlsx or .zip file.",
        )

    filename = file.filename.lower()
    payload = await file.read()
    if filename.endswith(".xlsx"):
        sheets = _read_excel(BytesIO(payload))
    elif filename.endswith(".zip"):
        sheets = _read_zip_csv(BytesIO(payload))
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Use .xlsx or a .zip of CSV sheets.",
        )

    missing = REQUIRED_SHEETS - set(sheets.keys())
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing sheets: {', '.join(sorted(missing))}.",
        )

    missing_columns = _validate_required_columns(sheets)
    if missing_columns:
        formatted = "; ".join(
            f"{sheet}: {', '.join(sorted(cols))}"
            for sheet, cols in missing_columns.items()
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required columns -> {formatted}.",
        )

    repository = EventRepository(db)
    counters = ImportCounters()
    errors: list[str] = []

    admissions = _group_by_registerno(sheets["Admissions"])
    academics = _group_by_registerno(sheets["Academics"])
    attendance = _group_by_registerno(sheets["Attendance"])
    finance = _group_by_registerno(sheets["Finance"])
    registration = _group_by_registerno(sheets["Registration"])
    lms = _group_by_registerno(sheets["LMS"])
    support_mapping = _group_by_registerno(sheets.get("SupportMapping", []))

    all_regs = set(admissions) | set(academics) | set(attendance) | set(finance) | set(
        registration
    ) | set(lms)

    next_student_id = _next_student_id(repository)
    for reg in sorted(all_regs):
        try:
            profile = repository.get_student_profile_by_external_ref(reg)
            if profile is None:
                student_id = next_student_id
                next_student_id += 1
            else:
                student_id = int(profile.student_id)

            admissions_row = _first_row(admissions.get(reg))
            registration_row = _first_row(registration.get(reg))
            support_mapping_row = _first_row(support_mapping.get(reg))
            profile_payload = _build_profile_payload(
                student_id=student_id,
                registerno=reg,
                admissions_row=admissions_row,
                registration_row=registration_row,
                support_mapping_row=support_mapping_row,
            )
            if support_mapping_row is not None:
                counters.support_mappings_applied += 1
            if not dry_run:
                repository.upsert_student_profile(profile_payload)
            counters.profiles_upserted += 1

            for lms_row in lms.get(reg, []):
                event = _build_lms_event(student_id, reg, lms_row)
                if not dry_run:
                    repository.add_lms_event(event)
                counters.lms_events_ingested += 1

            erp_event = _build_erp_event(
                student_id=student_id,
                registerno=reg,
                academics_rows=academics.get(reg, []),
                attendance_rows=attendance.get(reg, []),
                admissions_row=admissions_row,
                registration_row=registration_row,
            )
            if erp_event is not None:
                if not dry_run:
                    repository.add_erp_event(erp_event)
                counters.erp_events_ingested += 1

            finance_row = _first_row(finance.get(reg))
            if finance_row:
                finance_event = _build_finance_event(student_id, reg, finance_row)
                if not dry_run:
                    repository.add_finance_event(finance_event)
                counters.finance_events_ingested += 1

            if (
                trigger_scoring
                and not dry_run
                and erp_event is not None
                and lms.get(reg)
            ):
                score_result = score_student_from_db(
                    student_id=student_id,
                    db=db,
                    prediction_service=prediction_service,
                )
                if (
                    score_result.get("student_warning_triggered")
                    and score_result.get("student_warning_status") == "pending"
                    and score_result.get("student_warning_event_id") is not None
                ):
                    enqueue_student_warning_email_job(
                        warning_event_id=int(score_result["student_warning_event_id"]),
                        student_id=student_id,
                        prediction_history_id=int(score_result["prediction_history_id"]),
                        warning_type=str(score_result["student_warning_type"]),
                        recipient=str(profile_payload.get("student_email") or "unconfigured"),
                    )
                if (
                    score_result.get("alert_triggered")
                    and score_result.get("alert_status") == "pending"
                    and score_result.get("alert_event_id") is not None
                ):
                    enqueue_faculty_alert_email_job(
                        alert_event_id=int(score_result["alert_event_id"]),
                        student_id=student_id,
                        prediction_history_id=int(score_result["prediction_history_id"]),
                        alert_type=str(score_result["alert_type"]),
                    )
                counters.scoring_triggered += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{reg}: {exc}")

    return VignanImportResponse(
        status="completed",
        total_students=len(all_regs),
        profiles_upserted=counters.profiles_upserted,
        support_mappings_applied=counters.support_mappings_applied,
        lms_events_ingested=counters.lms_events_ingested,
        erp_events_ingested=counters.erp_events_ingested,
        finance_events_ingested=counters.finance_events_ingested,
        scoring_triggered=counters.scoring_triggered,
        errors=errors,
    )


def _read_excel(buffer: BytesIO) -> dict[str, list[dict]]:
    wb = openpyxl.load_workbook(buffer, read_only=True, data_only=True)
    sheets: dict[str, list[dict]] = {}
    for name in wb.sheetnames:
        ws = wb[name]
        headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
        missing_headers = [header for header in headers if header in (None, "")]
        if missing_headers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Sheet {name} has empty header cells.",
            )
        rows: list[dict] = []
        for r in range(2, ws.max_row + 1):
            values = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
            if all(value in (None, "") for value in values):
                continue
            row = {str(headers[i]).strip(): values[i] for i in range(len(headers))}
            rows.append(row)
        sheets[str(name).strip()] = rows
    return sheets


def _read_zip_csv(buffer: BytesIO) -> dict[str, list[dict]]:
    sheets: dict[str, list[dict]] = {}
    with zipfile.ZipFile(buffer) as archive:
        for info in archive.infolist():
            name = info.filename.split("/")[-1]
            if not name.lower().endswith(".csv"):
                continue
            sheet_name = name[:-4]
            with archive.open(info) as handle:
                wrapper = TextIOWrapper(handle, encoding="utf-8")
                reader = csv.DictReader(wrapper)
                if not reader.fieldnames or any(
                    name in (None, "") for name in reader.fieldnames
                ):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Sheet {sheet_name} has empty header cells.",
                    )
                sheets[sheet_name] = [row for row in reader if any(row.values())]
    return sheets


def _validate_required_columns(sheets: dict[str, list[dict]]) -> dict[str, set[str]]:
    missing: dict[str, set[str]] = {}
    for sheet, required in REQUIRED_COLUMNS.items():
        rows = sheets.get(sheet, [])
        if not rows:
            continue
        present = set(str(key).strip() for key in rows[0].keys())
        missing_columns = set(required) - present
        if missing_columns:
            missing[sheet] = missing_columns
    for sheet, required in OPTIONAL_REQUIRED_COLUMNS.items():
        rows = sheets.get(sheet, [])
        if not rows:
            continue
        present = set(str(key).strip() for key in rows[0].keys())
        missing_columns = set(required) - present
        if missing_columns:
            missing[sheet] = missing_columns
    return missing


def _group_by_registerno(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        reg = _normalize_registerno(row.get("registerno"))
        if reg:
            grouped[reg].append(row)
    return grouped


def _normalize_registerno(value) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _next_student_id(repository: EventRepository) -> int:
    base = repository.get_max_student_id()
    return max(base, 880000) + 1


def _first_row(rows: list[dict] | None) -> dict | None:
    if not rows:
        return None
    return rows[0]


def _build_profile_payload(
    *,
    student_id: int,
    registerno: str,
    admissions_row: dict | None,
    registration_row: dict | None,
    support_mapping_row: dict | None,
) -> dict:
    admissions = admissions_row or {}
    registration = registration_row or {}
    support_mapping = support_mapping_row or {}
    gender = _safe_str(admissions.get("Gender")) or "U"
    age_band = _safe_str(admissions.get("AgeBand")) or "Unknown"
    attempts = _safe_float(admissions.get("Attempts")) or 0.0
    highest_education = "Intermediate" if admissions.get("intermediate") not in (None, "") else "SSC"
    profile_context = {
        "branch": _safe_str(admissions.get("Branch")),
        "batch": _safe_str(admissions.get("Batch")),
        "ssc": admissions.get("ssc"),
        "intermediate": admissions.get("intermediate"),
        "vsat": admissions.get("vsat"),
        "category": _safe_str(admissions.get("Category")),
        "region": _safe_str(admissions.get("Region")),
        "parent_education": _safe_str(admissions.get("ParentEdu")),
        "occupation": _safe_str(admissions.get("Occupation")),
        "income": admissions.get("Income"),
        "registration": {
            "semester": registration.get("Semester"),
            "registered": registration.get("Registered"),
            "final_status": registration.get("FinalStatus"),
        },
        "model_input_exclusions": list(FAIRNESS_REVIEW_REQUIRED_PROFILE_FIELDS),
        "fairness_review_required": True,
        "support_mapping_present": bool(support_mapping_row),
    }

    return {
        "student_id": student_id,
        "student_email": _normalized_email(support_mapping.get("student_email")),
        "faculty_name": _safe_str(support_mapping.get("faculty_name")),
        "faculty_email": _normalized_email(support_mapping.get("faculty_email")),
        "counsellor_name": _safe_str(support_mapping.get("counsellor_name")),
        "counsellor_email": _normalized_email(support_mapping.get("counsellor_email")),
        "parent_name": _safe_str(support_mapping.get("parent_name")),
        "parent_relationship": _normalized_relationship(support_mapping.get("parent_relationship")),
        "parent_email": _normalized_email(support_mapping.get("parent_email")),
        "parent_phone": _normalized_phone(support_mapping.get("parent_phone")),
        "preferred_guardian_channel": _normalized_channel(support_mapping.get("preferred_guardian_channel")),
        "guardian_contact_enabled": _safe_bool(support_mapping.get("guardian_contact_enabled")),
        "external_student_ref": registerno,
        "profile_context": profile_context,
        "gender": gender,
        "highest_education": highest_education,
        "age_band": age_band,
        "disability_status": _normalized_disability_status(support_mapping.get("disability_status")),
        "num_previous_attempts": float(attempts),
    }


def _build_lms_event(student_id: int, registerno: str, row: dict) -> dict:
    event_date = _normalize_event_date(row.get("event_date"))
    return {
        "student_id": student_id,
        "code_module": "VIG",
        "code_presentation": "2026T",
        "id_site": int(_safe_float(row.get("id_site")) or 0),
        "event_date": int(event_date),
        "sum_click": int(_safe_float(row.get("sum_click")) or 0),
        "context_fields": {
            "registerno": registerno,
            "engagement_tag": _safe_str(row.get("engagement_tag")),
            "resource_type": _safe_str(row.get("resource_type")),
            "source_event_id": f"vignan-{registerno}-{event_date}-{row.get('id_site')}",
        },
    }


def _build_erp_event(
    *,
    student_id: int,
    registerno: str,
    academics_rows: list[dict],
    attendance_rows: list[dict],
    admissions_row: dict | None,
    registration_row: dict | None,
) -> dict | None:
    if not academics_rows and not attendance_rows:
        return None

    attendance_ratio = _average_percent(attendance_rows, "Overall%")
    attendance_trend = _average_attendance_trend(attendance_rows, "Trend")
    consecutive_absences = _max_float(attendance_rows, "ConsecutiveAbs")
    missed_sessions = _max_float(attendance_rows, "MissedvDays")
    subject_attendance = {
        _safe_str(row.get("shortname")): _percent_value(row.get("Subject%"))
        for row in attendance_rows
        if _safe_str(row.get("shortname"))
    }
    subject_attendance = {
        key: value for key, value in subject_attendance.items() if value is not None
    }

    avg_marks = _average_float(academics_rows, "Marks")
    avg_cgpa = _average_float(academics_rows, "CGPA")
    backlogs = _max_float(academics_rows, "Backlogs")
    subject_marks = {
        _safe_str(row.get("shortname")): _safe_float(row.get("Marks"))
        for row in academics_rows
        if _safe_str(row.get("shortname"))
    }

    semester = None
    if registration_row:
        semester = registration_row.get("Semester")
    elif attendance_rows:
        semester = attendance_rows[0].get("Semester")
    elif academics_rows:
        semester = academics_rows[0].get("Semester")

    context = {
        "registerno": registerno,
        "attendance_ratio": attendance_ratio,
        "attendance_trend": attendance_trend,
        "consecutive_absences": consecutive_absences,
        "missed_sessions_7d": missed_sessions,
        "subject_attendance": subject_attendance,
        "academic_marks_by_subject": subject_marks,
        "cgpa": avg_cgpa,
        "backlogs": backlogs,
        "backlog_count": backlogs,
        "semester": semester,
        "branch": _safe_str((admissions_row or {}).get("Branch")),
        "source_event_id": f"vignan-{registerno}-erp",
        "event_timestamp": datetime.now().isoformat(),
    }

    weighted_score = avg_marks if avg_marks is not None else (avg_cgpa * 10 if avg_cgpa else 0.0)
    return {
        "student_id": student_id,
        "code_module": "VIG",
        "code_presentation": "2026T",
        "assessment_submission_rate": attendance_ratio,
        "weighted_assessment_score": weighted_score,
        "late_submission_count": int(backlogs or 0),
        "total_assessments_completed": len(academics_rows) if academics_rows else None,
        "assessment_score_trend": attendance_trend,
        "context_fields": context,
    }


def _build_finance_event(student_id: int, registerno: str, row: dict) -> dict:
    status = _safe_str(row.get("Status"))
    return {
        "student_id": student_id,
        "fee_overdue_amount": _safe_float(row.get("Due")),
        "fee_delay_days": int(_safe_float(row.get("DelayDays")) or 0),
        "payment_status": status,
        "modifier_candidate": _safe_float(row.get("Modifier")),
        "context_fields": {
            "registerno": registerno,
            "scholarship": _safe_str(row.get("Scholarship")),
            "status": status,
            "source_event_id": f"vignan-{registerno}-finance",
        },
    }


def _safe_str(value) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip()


def _normalized_email(value) -> str | None:
    parsed = _safe_str(value)
    if parsed is None or "@" not in parsed:
        return None
    return parsed.lower()


def _normalized_phone(value) -> str | None:
    parsed = _safe_str(value)
    if parsed is None:
        return None
    cleaned = parsed.replace(" ", "").replace("-", "")
    return cleaned or None


def _normalized_channel(value) -> str | None:
    parsed = _safe_str(value)
    if parsed is None:
        return None
    lowered = parsed.lower()
    if lowered in {"email", "sms", "whatsapp"}:
        return lowered
    return None


def _normalized_relationship(value) -> str | None:
    parsed = _safe_str(value)
    if parsed is None:
        return None
    mapping = {
        "father": "Father",
        "mother": "Mother",
        "parent": "Parent",
        "guardian": "Guardian",
    }
    return mapping.get(parsed.lower(), parsed.title())


def _normalized_disability_status(value) -> str:
    parsed = (_safe_str(value) or "").upper()
    sanitized = parsed.replace("0", "").replace(" ", "")
    if sanitized in {"Y", "YES", "TRUE", "T"}:
        return "Y"
    return "N"


def _safe_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percent_value(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        text = str(value).strip()
        if text.endswith("%"):
            text = text[:-1]
        return float(text) / 100.0
    except (TypeError, ValueError):
        return None


def _safe_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _average_percent(rows: list[dict], field: str) -> float | None:
    values = [_percent_value(row.get(field)) for row in rows]
    values = [v for v in values if v is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _average_float(rows: list[dict], field: str) -> float | None:
    values = [_safe_float(row.get(field)) for row in rows]
    values = [v for v in values if v is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _max_float(rows: list[dict], field: str) -> float | None:
    values = [_safe_float(row.get(field)) for row in rows]
    values = [v for v in values if v is not None]
    if not values:
        return None
    return max(values)


def _average_attendance_trend(rows: list[dict], field: str) -> float | None:
    values: list[float] = []
    for row in rows:
        raw = row.get(field)
        numeric = _safe_float(raw)
        if numeric is not None:
            values.append(numeric)
            continue
        label = _safe_str(raw)
        if label is None:
            continue
        mapped = {"poor": -1.0, "average": 0.0, "good": 1.0}.get(label.lower())
        if mapped is not None:
            values.append(mapped)
    if not values:
        return None
    return sum(values) / len(values)


def _normalize_event_date(value) -> int:
    if isinstance(value, datetime):
        return value.date().toordinal()
    if isinstance(value, date):
        return value.toordinal()
    if value in (None, ""):
        return int(datetime.now().date().toordinal())
    try:
        return int(float(value))
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(str(value))
            return parsed.date().toordinal()
        except ValueError:
            return int(datetime.now().date().toordinal())
