from __future__ import annotations


def build_attendance_summary(context_fields: dict | None) -> dict:
    context = context_fields or {}

    overall_ratio = _safe_float(context.get("attendance_ratio"))
    attendance_trend = _safe_float(
        context.get("attendance_trend", context.get("attendance_ratio_trend"))
    )
    consecutive_absences = _safe_float(context.get("consecutive_absences"))
    missed_sessions_7d = _safe_float(context.get("missed_sessions_7d"))

    subject_ratios_raw = context.get("subject_attendance") or context.get("attendance_by_subject")
    subject_attendance: dict[str, float] = {}
    if isinstance(subject_ratios_raw, dict):
        for key, value in subject_ratios_raw.items():
            parsed = _safe_float(value)
            if parsed is not None:
                subject_attendance[str(key)] = parsed

    low_subjects = [
        subject
        for subject, ratio in sorted(subject_attendance.items())
        if ratio < 0.75
    ]

    severity = "unknown"
    if overall_ratio is not None:
        if overall_ratio < 0.5:
            severity = "high"
        elif overall_ratio < 0.75:
            severity = "medium"
        else:
            severity = "low"

    return {
        "attendance_ratio": overall_ratio,
        "attendance_trend": attendance_trend,
        "consecutive_absences": consecutive_absences,
        "missed_sessions_7d": missed_sessions_7d,
        "subject_attendance": subject_attendance,
        "low_attendance_subjects": low_subjects,
        "attendance_severity": severity,
        "attendance_flag": _has_attendance_concern(
            overall_ratio=overall_ratio,
            attendance_trend=attendance_trend,
            consecutive_absences=consecutive_absences,
            missed_sessions_7d=missed_sessions_7d,
            low_subject_count=len(low_subjects),
        ),
    }


def _has_attendance_concern(
    *,
    overall_ratio: float | None,
    attendance_trend: float | None,
    consecutive_absences: float | None,
    missed_sessions_7d: float | None,
    low_subject_count: int,
) -> bool:
    if overall_ratio is not None and overall_ratio < 0.75:
        return True
    if attendance_trend is not None and attendance_trend < -0.05:
        return True
    if consecutive_absences is not None and consecutive_absences >= 3:
        return True
    if missed_sessions_7d is not None and missed_sessions_7d >= 2:
        return True
    return low_subject_count > 0


def _safe_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
