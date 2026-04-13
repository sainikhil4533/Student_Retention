from __future__ import annotations


def _severity_rank(severity: str) -> int:
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(severity, 0)


def build_risk_drivers(
    *,
    prediction,
    lms_summary: dict,
    erp_summary: dict,
    attendance_summary: dict | None,
    finance_modifier: float,
    limit: int | None = 3,
) -> list[dict]:
    drivers: list[dict] = []

    submission_rate = float(erp_summary.get("assessment_submission_rate", 0.0))
    weighted_score = float(erp_summary.get("weighted_assessment_score", 0.0))
    late_submission_count = float(erp_summary.get("late_submission_count", 0.0))
    completed_assessments = float(erp_summary.get("total_assessments_completed", 0.0))
    score_trend = float(erp_summary.get("assessment_score_trend", 0.0))

    lms_clicks_7d = float(lms_summary.get("lms_clicks_7d", 0.0))
    lms_unique_resources_7d = float(lms_summary.get("lms_unique_resources_7d", 0.0))
    lms_percent_change = float(lms_summary.get("lms_7d_vs_14d_percent_change", 0.0))
    engagement_acceleration = float(lms_summary.get("engagement_acceleration", 0.0))
    attendance_summary = attendance_summary or {}
    attendance_ratio = attendance_summary.get("attendance_ratio")
    attendance_trend = attendance_summary.get("attendance_trend")
    consecutive_absences = attendance_summary.get("consecutive_absences")
    missed_sessions_7d = attendance_summary.get("missed_sessions_7d")
    low_attendance_subjects = attendance_summary.get("low_attendance_subjects") or []

    if submission_rate < 0.4:
        drivers.append(
            {
                "driver_name": "low_submission_rate",
                "severity": "HIGH",
                "evidence": f"Assessment submission rate is {submission_rate:.2f}.",
            }
        )
    elif submission_rate < 0.7:
        drivers.append(
            {
                "driver_name": "moderate_submission_rate",
                "severity": "MEDIUM",
                "evidence": f"Assessment submission rate is {submission_rate:.2f}.",
            }
        )

    if weighted_score < 40:
        drivers.append(
            {
                "driver_name": "low_assessment_score",
                "severity": "HIGH",
                "evidence": f"Weighted assessment score is {weighted_score:.1f}.",
            }
        )
    elif weighted_score < 60:
        drivers.append(
            {
                "driver_name": "average_assessment_score",
                "severity": "MEDIUM",
                "evidence": f"Weighted assessment score is {weighted_score:.1f}.",
            }
        )

    if late_submission_count >= 3:
        drivers.append(
            {
                "driver_name": "repeated_late_submissions",
                "severity": "HIGH",
                "evidence": f"Late submissions count is {late_submission_count:.0f}.",
            }
        )
    elif late_submission_count >= 1:
        drivers.append(
            {
                "driver_name": "some_late_submissions",
                "severity": "MEDIUM",
                "evidence": f"Late submissions count is {late_submission_count:.0f}.",
            }
        )

    if completed_assessments <= 2:
        drivers.append(
            {
                "driver_name": "low_completed_assessments",
                "severity": "MEDIUM",
                "evidence": f"Completed assessments count is {completed_assessments:.0f}.",
            }
        )

    if score_trend < -5:
        drivers.append(
            {
                "driver_name": "declining_assessment_trend",
                "severity": "HIGH",
                "evidence": f"Assessment score trend is {score_trend:.1f}.",
            }
        )
    elif score_trend < 0:
        drivers.append(
            {
                "driver_name": "slightly_negative_trend",
                "severity": "MEDIUM",
                "evidence": f"Assessment score trend is {score_trend:.1f}.",
            }
        )

    if lms_clicks_7d <= 5:
        drivers.append(
            {
                "driver_name": "low_recent_lms_engagement",
                "severity": "HIGH",
                "evidence": f"LMS clicks in the last 7 days are {lms_clicks_7d:.0f}.",
            }
        )
    elif lms_clicks_7d <= 15:
        drivers.append(
            {
                "driver_name": "moderate_recent_lms_engagement",
                "severity": "MEDIUM",
                "evidence": f"LMS clicks in the last 7 days are {lms_clicks_7d:.0f}.",
            }
        )

    if lms_unique_resources_7d <= 2:
        drivers.append(
            {
                "driver_name": "low_resource_variety",
                "severity": "MEDIUM",
                "evidence": f"Unique LMS resources accessed in 7 days are {lms_unique_resources_7d:.0f}.",
            }
        )

    if lms_percent_change < -0.25 or engagement_acceleration < -5:
        drivers.append(
            {
                "driver_name": "declining_engagement_pattern",
                "severity": "MEDIUM",
                "evidence": (
                    f"LMS 7d vs 14d percent change is {lms_percent_change:.2f} "
                    f"and engagement acceleration is {engagement_acceleration:.1f}."
                ),
            }
        )

    if attendance_ratio is not None and float(attendance_ratio) < 0.5:
        drivers.append(
            {
                "driver_name": "critical_attendance_drop",
                "severity": "HIGH",
                "evidence": f"Attendance ratio is {float(attendance_ratio):.2f}.",
            }
        )
    elif attendance_ratio is not None and float(attendance_ratio) < 0.75:
        drivers.append(
            {
                "driver_name": "attendance_concern",
                "severity": "MEDIUM",
                "evidence": f"Attendance ratio is {float(attendance_ratio):.2f}.",
            }
        )

    if attendance_trend is not None and float(attendance_trend) < -0.05:
        drivers.append(
            {
                "driver_name": "declining_attendance_trend",
                "severity": "MEDIUM",
                "evidence": f"Attendance trend is {float(attendance_trend):.2f}.",
            }
        )

    if consecutive_absences is not None and float(consecutive_absences) >= 3:
        drivers.append(
            {
                "driver_name": "consecutive_absence_pattern",
                "severity": "HIGH",
                "evidence": f"Consecutive absences count is {float(consecutive_absences):.0f}.",
            }
        )

    if missed_sessions_7d is not None and float(missed_sessions_7d) >= 2:
        drivers.append(
            {
                "driver_name": "recent_missed_sessions",
                "severity": "MEDIUM",
                "evidence": f"Missed sessions in the last 7 days are {float(missed_sessions_7d):.0f}.",
            }
        )

    if low_attendance_subjects:
        drivers.append(
            {
                "driver_name": "subject_wise_attendance_gap",
                "severity": "MEDIUM",
                "evidence": "Low attendance subjects: " + ", ".join(low_attendance_subjects[:3]) + ".",
            }
        )

    if finance_modifier >= 0.1:
        drivers.append(
            {
                "driver_name": "finance_stress_modifier",
                "severity": "HIGH",
                "evidence": f"Finance modifier increased final risk by {finance_modifier:.2f}.",
            }
        )
    elif finance_modifier > 0:
        drivers.append(
            {
                "driver_name": "finance_context_modifier",
                "severity": "MEDIUM",
                "evidence": f"Finance modifier increased final risk by {finance_modifier:.2f}.",
            }
        )

    if not drivers:
        drivers.append(
            {
                "driver_name": "stable_profile",
                "severity": "LOW",
                "evidence": "No major academic or engagement risk driver is currently dominant.",
            }
        )

    drivers.sort(
        key=lambda item: (_severity_rank(item["severity"]), item["driver_name"]),
        reverse=True,
    )
    if limit is None:
        return drivers
    return drivers[:limit]
