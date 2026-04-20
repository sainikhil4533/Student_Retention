from __future__ import annotations

from typing import Any


UNCLEARED_STATUS_TOKENS = {
    "I",
    "R",
    "I_GRADE",
    "R_GRADE",
    "I GRADE",
    "R GRADE",
    "I_GRADE_PENDING_CLEARANCE",
    "R_GRADE_PENDING_CLEARANCE",
    "INCOMPLETE",
    "REPEAT",
}

CLEARED_STATUS_TOKENS = {
    "PASS",
    "PASSED",
    "CLEARED",
    "COMPLETED",
    "SAFE",
}


def build_academic_burden_summary(
    *,
    academic_rows: list[object],
    attendance_rows: list[object] | None = None,
) -> dict[str, Any]:
    latest_by_subject: dict[str, dict[str, Any]] = {}
    attendance_rows = attendance_rows or []
    attendance_by_subject: dict[str, object] = {}

    for row in attendance_rows:
        key = _subject_key(
            getattr(row, "subject_code", None),
            getattr(row, "subject_name", None),
        )
        if key:
            attendance_by_subject[key] = row

    for row in academic_rows:
        key = _subject_key(
            getattr(row, "subject_code", None),
            getattr(row, "subject_name", None),
        )
        if not key:
            continue
        current_order = (
            int(getattr(row, "year", 0) or 0),
            int(getattr(row, "semester", 0) or 0),
            int(getattr(row, "id", 0) or 0),
        )
        existing = latest_by_subject.get(key)
        if existing is None or current_order >= existing["order"]:
            latest_by_subject[key] = {"row": row, "order": current_order}

    active_i_grade_subjects: list[dict[str, Any]] = []
    active_r_grade_subjects: list[dict[str, Any]] = []

    for key, item in latest_by_subject.items():
        row = item["row"]
        normalized_status = _normalized_uncleared_status(
            attendance_status=getattr(row, "attendance_linked_status", None),
            result_status=getattr(row, "result_status", None),
            grade=getattr(row, "grade", None),
            attendance_row=attendance_by_subject.get(key),
        )
        if normalized_status is None:
            continue

        subject_entry = {
            "subject_code": getattr(row, "subject_code", None),
            "subject_name": getattr(row, "subject_name", None),
            "year": getattr(row, "year", None),
            "semester": getattr(row, "semester", None),
            "raw_result_status": getattr(row, "result_status", None),
            "raw_grade": getattr(row, "grade", None),
            "attendance_linked_status": getattr(row, "attendance_linked_status", None),
            "effective_result_status": (
                "Pending I-grade clearance"
                if normalized_status == "I_GRADE"
                else "Pending R-grade clearance"
            ),
            "effective_grade": "I" if normalized_status == "I_GRADE" else "R",
            "subject_attendance_percent": (
                float(getattr(attendance_by_subject.get(key), "subject_attendance_percent", 0.0))
                if attendance_by_subject.get(key) is not None
                and getattr(attendance_by_subject.get(key), "subject_attendance_percent", None) is not None
                else None
            ),
        }
        if normalized_status == "R_GRADE":
            active_r_grade_subjects.append(subject_entry)
        else:
            active_i_grade_subjects.append(subject_entry)

    active_r_grade_subjects.sort(
        key=lambda item: (
            int(item["semester"] or 0),
            str(item["subject_name"] or ""),
        )
    )
    active_i_grade_subjects.sort(
        key=lambda item: (
            int(item["semester"] or 0),
            str(item["subject_name"] or ""),
        )
    )

    has_active_r = bool(active_r_grade_subjects)
    has_active_i = bool(active_i_grade_subjects)
    if has_active_r:
        academic_risk_band = "SEVERE"
        monitoring_cadence = "WEEKLY"
        monitoring_summary = "Weekly counsellor monitoring is recommended until the unresolved R-grade subjects are cleared."
    elif has_active_i:
        academic_risk_band = "WATCHLIST"
        monitoring_cadence = "MONTHLY"
        monitoring_summary = "Monthly counsellor monitoring is recommended until the unresolved I-grade subjects are cleared."
    else:
        academic_risk_band = "SAFE"
        monitoring_cadence = "NONE"
        monitoring_summary = "No unresolved I-grade or R-grade subjects are currently active."

    active_burden_count = len(active_i_grade_subjects) + len(active_r_grade_subjects)
    summary = monitoring_summary
    if active_burden_count:
        summary = (
            f"{active_burden_count} uncleared academic burden subject(s) are still active: "
            f"{len(active_i_grade_subjects)} I-grade and {len(active_r_grade_subjects)} R-grade."
        )

    return {
        "active_i_grade_subjects": active_i_grade_subjects,
        "active_r_grade_subjects": active_r_grade_subjects,
        "active_burden_count": active_burden_count,
        "has_active_i_grade_burden": has_active_i,
        "has_active_r_grade_burden": has_active_r,
        "has_active_burden": has_active_i or has_active_r,
        "academic_risk_band": academic_risk_band,
        "monitoring_cadence": monitoring_cadence,
        "monitoring_summary": monitoring_summary,
        "summary": summary,
    }


def _subject_key(subject_code: object, subject_name: object) -> str:
    code = str(subject_code or "").strip().lower()
    name = str(subject_name or "").strip().lower()
    return code or name


def _normalized_uncleared_status(
    *,
    attendance_status: object,
    result_status: object,
    grade: object,
    attendance_row: object | None,
) -> str | None:
    for candidate in (
        _normalize_token(attendance_status),
        _normalize_token(getattr(attendance_row, "subject_status", None) if attendance_row is not None else None),
        _normalize_token(result_status),
        _normalize_token(grade),
    ):
        if candidate in {"R", "R_GRADE", "R GRADE"}:
            return "R_GRADE"
        if candidate in {"I", "I_GRADE", "I GRADE", "INCOMPLETE"}:
            return "I_GRADE"
        if candidate in CLEARED_STATUS_TOKENS:
            return None
    return None


def _normalize_token(value: object) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    normalized = text.replace("-", "_")
    if normalized in UNCLEARED_STATUS_TOKENS or normalized in CLEARED_STATUS_TOKENS:
        return normalized
    return normalized
