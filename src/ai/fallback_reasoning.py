from __future__ import annotations


def _determine_confidence(
    risk_score: float,
    final_risk_probability: float,
    threshold: float,
    stability_summary: dict | None = None,
) -> str:
    stability_label = (stability_summary or {}).get("stability_label")
    stability_score = (stability_summary or {}).get("stability_score")
    if stability_label == "very_stable":
        return (
            f"High confidence. The prediction is operationally very stable "
            f"(stability score: {int(stability_score)})."
        )
    if stability_label == "stable":
        return (
            f"Good confidence. The prediction is operationally stable "
            f"(stability score: {int(stability_score)})."
        )
    if stability_label == "watchlist":
        return (
            f"Moderate confidence. The prediction is usable but should be watched closely "
            f"(stability score: {int(stability_score)})."
        )
    if stability_label == "volatile":
        return (
            f"Borderline confidence. The case is relatively volatile and should be refreshed "
            f"with new data soon (stability score: {int(stability_score)})."
        )

    distance_from_threshold = abs(final_risk_probability - threshold)

    if risk_score >= 0.8 or distance_from_threshold >= 0.25:
        return "High confidence based on strong academic and engagement signals."
    if distance_from_threshold >= 0.1:
        return "Moderate confidence based on the current student signals."
    return "Borderline confidence. The student should be monitored with updated data."


def _determine_urgency_and_timeline(risk_level: str) -> tuple[str, str]:
    if risk_level == "HIGH":
        return "HIGH", "Immediate"
    if risk_level == "MEDIUM":
        return "MEDIUM", "Within 3 days"
    return "LOW", "Monitor weekly"


def _build_reasoning_parts(student_data: dict, finance_modifier: float) -> list[str]:
    reasons: list[str] = []

    assessment_submission_rate = float(student_data.get("assessment_submission_rate", 0.0))
    weighted_assessment_score = float(student_data.get("weighted_assessment_score", 0.0))
    late_submission_count = float(student_data.get("late_submission_count", 0.0))
    days_since_last_lms_activity = float(student_data.get("days_since_last_lms_activity", 0.0))
    lms_clicks_7d = float(student_data.get("lms_clicks_7d", 0.0))
    assessment_score_trend = float(student_data.get("assessment_score_trend", 0.0))
    attendance_summary = student_data.get("attendance_summary") or {}
    attendance_ratio = attendance_summary.get("attendance_ratio")
    attendance_trend = attendance_summary.get("attendance_trend")
    consecutive_absences = attendance_summary.get("consecutive_absences")
    low_attendance_subjects = attendance_summary.get("low_attendance_subjects") or []

    if assessment_submission_rate < 0.4:
        reasons.append("low assessment submission rate")
    elif assessment_submission_rate < 0.7:
        reasons.append("moderate assessment completion")

    if weighted_assessment_score < 40:
        reasons.append("low weighted assessment performance")
    elif weighted_assessment_score < 60:
        reasons.append("average assessment performance")

    if late_submission_count >= 3:
        reasons.append("repeated late submissions")
    elif late_submission_count >= 1:
        reasons.append("some late submissions")

    if days_since_last_lms_activity >= 30:
        reasons.append("long LMS inactivity")
    elif lms_clicks_7d <= 5:
        reasons.append("low recent LMS engagement")

    if assessment_score_trend < -5:
        reasons.append("declining academic trend")

    if attendance_ratio is not None and float(attendance_ratio) < 0.6:
        reasons.append("low attendance ratio")
    elif attendance_ratio is not None and float(attendance_ratio) < 0.75:
        reasons.append("moderate attendance concern")

    if attendance_trend is not None and float(attendance_trend) < -0.05:
        reasons.append("attendance is trending downward")

    if consecutive_absences is not None and float(consecutive_absences) >= 3:
        reasons.append("repeated recent absences")

    if low_attendance_subjects:
        reasons.append("subject-wise attendance weakness is visible")

    if finance_modifier > 0:
        reasons.append("external finance context increased final risk")

    if not reasons:
        reasons.append("stable recent academic and engagement behavior")

    return reasons


def _build_faculty_actions(risk_level: str, student_data: dict) -> list[str]:
    actions: list[str] = []

    assessment_submission_rate = float(student_data.get("assessment_submission_rate", 0.0))
    weighted_assessment_score = float(student_data.get("weighted_assessment_score", 0.0))
    late_submission_count = float(student_data.get("late_submission_count", 0.0))
    lms_clicks_7d = float(student_data.get("lms_clicks_7d", 0.0))
    attendance_summary = student_data.get("attendance_summary") or {}
    attendance_ratio = attendance_summary.get("attendance_ratio")
    low_attendance_subjects = attendance_summary.get("low_attendance_subjects") or []
    consecutive_absences = attendance_summary.get("consecutive_absences")

    if risk_level == "HIGH":
        actions.append("Schedule an immediate faculty mentor meeting.")
        actions.append("Review missed or late assessments with the student.")
        actions.append("Monitor LMS engagement daily for the next 7 days.")
    elif risk_level == "MEDIUM":
        actions.append("Arrange an academic check-in within 3 days.")
        actions.append("Review current coursework progress and pending submissions.")
        actions.append("Monitor LMS engagement for the next week.")
    else:
        actions.append("Continue regular monitoring through weekly review.")

    if assessment_submission_rate < 0.5:
        actions.append("Prioritize completion of pending assessments.")
    if weighted_assessment_score < 50:
        actions.append("Recommend targeted academic support for weak subjects.")
    if late_submission_count >= 2:
        actions.append("Discuss time management and submission planning.")
    if lms_clicks_7d <= 5:
        actions.append("Encourage more consistent LMS participation.")
    if attendance_ratio is not None and float(attendance_ratio) < 0.75:
        actions.append("Review attendance discipline and missed-class patterns.")
    if low_attendance_subjects:
        actions.append("Prioritize mentor follow-up for subjects with weak attendance.")
    if consecutive_absences is not None and float(consecutive_absences) >= 3:
        actions.append("Check for immediate barriers causing consecutive absences.")

    deduplicated_actions: list[str] = []
    for action in actions:
        if action not in deduplicated_actions:
            deduplicated_actions.append(action)
    return deduplicated_actions


def _build_student_guidance(risk_level: str, student_data: dict) -> dict:
    weighted_assessment_score = float(student_data.get("weighted_assessment_score", 0.0))
    lms_clicks_7d = float(student_data.get("lms_clicks_7d", 0.0))
    late_submission_count = float(student_data.get("late_submission_count", 0.0))
    attendance_summary = student_data.get("attendance_summary") or {}
    attendance_ratio = attendance_summary.get("attendance_ratio")
    low_attendance_subjects = attendance_summary.get("low_attendance_subjects") or []

    if risk_level == "HIGH":
        summary = "Your recent academic and learning activity suggests you may need immediate support."
        motivation = "You can still improve your progress with quick action and regular support."
    elif risk_level == "MEDIUM":
        summary = "Your recent activity shows some signs that you may need closer support."
        motivation = "A few consistent steps now can help you stay on track."
    else:
        summary = "Your current progress looks stable, but staying consistent is important."
        motivation = "Keep building on your current progress with steady effort."

    suggestions: list[str] = []
    if weighted_assessment_score < 60:
        suggestions.append("Spend extra time reviewing difficult subjects this week.")
    if lms_clicks_7d <= 5:
        suggestions.append("Log into the LMS daily and revisit course materials.")
    if late_submission_count >= 1:
        suggestions.append("Plan assignment deadlines in advance to avoid late submissions.")
    if attendance_ratio is not None and float(attendance_ratio) < 0.75:
        suggestions.append("Attend classes more consistently over the next week.")
    if low_attendance_subjects:
        suggestions.append("Focus on improving attendance in the subjects you are missing most.")

    suggestions.append("Reach out to your faculty mentor if you feel stuck.")

    deduplicated_suggestions: list[str] = []
    for suggestion in suggestions:
        if suggestion not in deduplicated_suggestions:
            deduplicated_suggestions.append(suggestion)

    return {
        "summary": summary,
        "suggestions": deduplicated_suggestions,
        "motivation": motivation,
    }


def generate_fallback_insights(
    student_data: dict,
    risk_score: float,
    risk_level: str,
    final_risk_probability: float,
    threshold: float,
    finance_modifier: float = 0.0,
    operational_context: dict | None = None,
) -> dict:
    reasoning_parts = _build_reasoning_parts(student_data, finance_modifier)
    operational_context = operational_context or {}
    risk_trend = operational_context.get("risk_trend") or {}
    risk_type = operational_context.get("risk_type") or {}
    stability_summary = operational_context.get("stability") or {}
    trigger_alerts = operational_context.get("trigger_alerts") or {}
    trigger_items = trigger_alerts.get("triggers") or []
    confidence = _determine_confidence(
        risk_score=risk_score,
        final_risk_probability=final_risk_probability,
        threshold=threshold,
        stability_summary=stability_summary,
    )
    urgency, timeline = _determine_urgency_and_timeline(risk_level)
    if risk_level == "HIGH" and risk_trend.get("trend_label") in {
        "newly_high_risk",
        "sharp_worsening",
        "persistent_high_risk",
    }:
        urgency, timeline = "HIGH", "Immediate"
    elif stability_summary.get("stability_label") == "volatile":
        timeline = "Refresh with new data within 48 hours"
    if trigger_alerts.get("has_critical_trigger"):
        urgency = "HIGH"
        if timeline != "Immediate":
            timeline = "Immediate"

    return {
        "source": "fallback",
        "confidence": confidence,
        "reasoning": (
            "The current assessment is based on "
            + ", ".join(reasoning_parts[:-1])
            + (", and " if len(reasoning_parts) > 1 else "")
            + reasoning_parts[-1]
            + "."
        )
        if len(reasoning_parts) > 1
        else f"The current assessment is based on {reasoning_parts[0]}.",
        "actions": _build_faculty_actions(risk_level, student_data),
        "urgency": urgency,
        "timeline": timeline,
        "student_guidance": _build_student_guidance(risk_level, student_data),
    } | (
        {
            "reasoning": (
                (
                    "The current assessment is based on "
                    + ", ".join(reasoning_parts[:-1])
                    + (", and " if len(reasoning_parts) > 1 else "")
                    + reasoning_parts[-1]
                    + "."
                )
                if len(reasoning_parts) > 1
                else f"The current assessment is based on {reasoning_parts[0]}."
            )
            + (
                f" Trend signal: {risk_trend.get('summary')}"
                if risk_trend.get("summary")
                else ""
            )
            + (
                f" Dominant risk pattern: {risk_type.get('summary')}"
                if risk_type.get("summary")
                else ""
            )
            + (
                f" Stability note: {stability_summary.get('summary')}"
                if stability_summary.get("summary")
                else ""
            )
            + (
                " Trigger alerts: "
                + "; ".join(item.get("title", "") for item in trigger_items[:3])
                + "."
                if trigger_items
                else ""
            )
        }
        if operational_context
        else {}
    )
    
