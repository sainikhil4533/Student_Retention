from __future__ import annotations

from datetime import UTC, datetime, timedelta


SEVERITY_WEIGHTS = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
DRIVER_CATEGORY_MAP = {
    "low_submission_rate": "academic",
    "moderate_submission_rate": "academic",
    "low_assessment_score": "academic",
    "average_assessment_score": "academic",
    "repeated_late_submissions": "academic",
    "some_late_submissions": "academic",
    "low_completed_assessments": "academic",
    "declining_assessment_trend": "academic",
    "slightly_negative_trend": "academic",
    "low_recent_lms_engagement": "engagement",
    "moderate_recent_lms_engagement": "engagement",
    "low_resource_variety": "engagement",
    "declining_engagement_pattern": "engagement",
    "critical_attendance_drop": "attendance",
    "attendance_concern": "attendance",
    "declining_attendance_trend": "attendance",
    "consecutive_absence_pattern": "attendance",
    "recent_missed_sessions": "attendance",
    "subject_wise_attendance_gap": "attendance",
    "finance_stress_modifier": "finance",
    "finance_context_modifier": "finance",
    "stable_profile": "stable",
}
RISK_TYPE_LABELS = {
    "academic": "academic_decline",
    "attendance": "attendance_driven",
    "engagement": "engagement_drop",
    "finance": "finance_driven",
    "stable": "stable_profile",
}


def build_stability_summary(
    *,
    prediction,
    prediction_rows: list,
) -> dict:
    threshold = float(getattr(prediction, "threshold", 0.55))
    final_probability = float(getattr(prediction, "final_risk_probability", 0.0))
    final_class = int(getattr(prediction, "final_predicted_class", 0))
    base_probability = float(getattr(prediction, "base_risk_probability", final_probability))
    challenger_predictions = list(getattr(prediction, "challenger_predictions", None) or [])

    threshold_distance = abs(final_probability - threshold)
    model_probabilities = [base_probability]
    model_classes = [int(getattr(prediction, "base_predicted_class", final_class))]
    for challenger in challenger_predictions:
        probability = float(challenger.get("predicted_risk_probability", 0.0))
        model_probabilities.append(probability)
        model_classes.append(
            int(
                challenger.get(
                    "predicted_class",
                    1 if probability >= threshold else 0,
                )
            )
        )

    agreement_ratio = (
        sum(1 for predicted_class in model_classes if predicted_class == final_class)
        / len(model_classes)
        if model_classes
        else 1.0
    )
    probability_spread = (
        max(model_probabilities) - min(model_probabilities)
        if model_probabilities
        else 0.0
    )

    ordered_rows = sorted(
        prediction_rows,
        key=lambda row: (_as_utc(getattr(row, "created_at", None)), int(getattr(row, "id", 0))),
    )
    previous = None
    if ordered_rows:
        current_id = int(getattr(prediction, "id", 0))
        filtered = [row for row in ordered_rows if int(getattr(row, "id", 0)) != current_id]
        previous = filtered[-1] if filtered else None
    recent_volatility = (
        abs(final_probability - float(previous.final_risk_probability))
        if previous is not None
        else 0.0
    )

    stability_score = round(
        min(threshold_distance / 0.35, 1.0) * 45
        + agreement_ratio * 30
        + max(0.0, 1.0 - min(probability_spread / 0.6, 1.0)) * 15
        + max(0.0, 1.0 - min(recent_volatility / 0.35, 1.0)) * 10
    )
    stability_score = max(0, min(100, stability_score))

    if stability_score >= 80:
        stability_label = "very_stable"
        summary = (
            "Prediction is highly stable because the score is far from threshold and model agreement is strong."
        )
    elif stability_score >= 65:
        stability_label = "stable"
        summary = (
            "Prediction is operationally stable with good agreement and a comfortable threshold margin."
        )
    elif stability_score >= 45:
        stability_label = "watchlist"
        summary = (
            "Prediction is usable but should be interpreted carefully because the case is closer to threshold or recent movement is noticeable."
        )
    else:
        stability_label = "volatile"
        summary = (
            "Prediction is relatively unstable because model agreement or threshold margin is weak, or the case moved sharply recently."
        )

    return {
        "stability_score": int(stability_score),
        "stability_label": stability_label,
        "threshold_distance": round(threshold_distance, 4),
        "model_agreement_ratio": round(agreement_ratio, 4),
        "probability_spread": round(probability_spread, 4),
        "recent_volatility": round(recent_volatility, 4),
        "summary": summary,
    }


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def build_risk_trend_summary(prediction_rows: list) -> dict:
    if not prediction_rows:
        return {
            "trend_score": 0,
            "trend_label": "no_history",
            "trend_direction": "stable",
            "current_probability": None,
            "previous_probability": None,
            "probability_change": None,
            "high_risk_count_7d": 0,
            "high_risk_count_14d": 0,
            "high_risk_count_30d": 0,
            "summary": "No prediction history is available yet.",
        }

    ordered = sorted(
        prediction_rows,
        key=lambda row: (_as_utc(getattr(row, "created_at", None)), int(getattr(row, "id", 0))),
    )
    current = ordered[-1]
    previous = ordered[-2] if len(ordered) >= 2 else None
    reference_time = _as_utc(getattr(current, "created_at", None))
    current_probability = float(current.final_risk_probability)
    current_is_high = int(current.final_predicted_class) == 1
    previous_probability = (
        float(previous.final_risk_probability) if previous is not None else None
    )
    previous_is_high = (
        int(previous.final_predicted_class) == 1 if previous is not None else None
    )
    probability_change = (
        current_probability - previous_probability
        if previous_probability is not None
        else None
    )

    def _window_high_risk_count(days: int) -> int:
        cutoff = reference_time - timedelta(days=days)
        return sum(
            1
            for row in ordered
            if _as_utc(getattr(row, "created_at", None)) >= cutoff
            and int(row.final_predicted_class) == 1
        )

    high_risk_count_7d = _window_high_risk_count(7)
    high_risk_count_14d = _window_high_risk_count(14)
    high_risk_count_30d = _window_high_risk_count(30)

    if previous is None:
        trend_label = "initial_high_risk" if current_is_high else "initial_low_risk"
        trend_direction = "up" if current_is_high else "stable"
        summary = (
            "Initial prediction already indicates elevated risk."
            if current_is_high
            else "Initial prediction shows a low-risk baseline."
        )
    elif current_is_high and previous_is_high and high_risk_count_30d >= 3:
        trend_label = "persistent_high_risk"
        trend_direction = "up"
        summary = "Student has remained high risk across multiple recent scoring cycles."
    elif current_is_high and not previous_is_high:
        trend_label = "newly_high_risk"
        trend_direction = "up"
        summary = "Student has newly crossed into a high-risk state compared with the prior score."
    elif not current_is_high and previous_is_high:
        trend_label = "recovering"
        trend_direction = "down"
        summary = "Student moved out of the previous high-risk state and is currently improving."
    elif probability_change is not None and probability_change >= 0.12:
        trend_label = "sharp_worsening"
        trend_direction = "up"
        summary = "Risk probability has increased sharply since the previous score."
    elif probability_change is not None and probability_change >= 0.05:
        trend_label = "worsening"
        trend_direction = "up"
        summary = "Risk probability is trending upward and needs closer monitoring."
    elif probability_change is not None and probability_change <= -0.12:
        trend_label = "strong_improvement"
        trend_direction = "down"
        summary = "Risk probability has dropped substantially since the previous score."
    elif probability_change is not None and probability_change <= -0.05:
        trend_label = "improving"
        trend_direction = "down"
        summary = "Risk probability is moving in the right direction."
    else:
        trend_label = "stable"
        trend_direction = "stable"
        summary = "Risk level is relatively stable compared with the recent scoring history."

    trend_score = round(current_probability * 100)
    if current_is_high:
        trend_score += min(high_risk_count_30d * 4, 12)
    if probability_change is not None:
        trend_score += round(probability_change * 50)
    if not current_is_high and previous_is_high:
        trend_score -= 10
    trend_score = max(0, min(100, trend_score))

    return {
        "trend_score": int(trend_score),
        "trend_label": trend_label,
        "trend_direction": trend_direction,
        "current_probability": current_probability,
        "previous_probability": previous_probability,
        "probability_change": probability_change,
        "high_risk_count_7d": high_risk_count_7d,
        "high_risk_count_14d": high_risk_count_14d,
        "high_risk_count_30d": high_risk_count_30d,
        "summary": summary,
    }


def classify_risk_type(drivers: list[dict]) -> dict:
    category_scores: dict[str, int] = {
        "academic": 0,
        "attendance": 0,
        "engagement": 0,
        "finance": 0,
        "stable": 0,
    }

    for driver in drivers:
        category = DRIVER_CATEGORY_MAP.get(driver.get("driver_name", ""), "stable")
        category_scores[category] = category_scores.get(category, 0) + SEVERITY_WEIGHTS.get(
            str(driver.get("severity", "")).upper(),
            1,
        )

    ordered = sorted(category_scores.items(), key=lambda item: item[1], reverse=True)
    primary_category, primary_score = ordered[0]
    secondary_category, secondary_score = ordered[1]

    if primary_score <= 0:
        primary_type = "stable_profile"
        secondary_type = None
        summary = "No dominant operational risk category is currently standing out."
    elif secondary_score > 0 and primary_score - secondary_score <= 1:
        primary_type = "multi_factor_risk"
        secondary_type = RISK_TYPE_LABELS.get(primary_category)
        summary = (
            "Risk appears to be multi-factor, with more than one domain contributing "
            "materially to the student's current state."
        )
    else:
        primary_type = RISK_TYPE_LABELS.get(primary_category, "stable_profile")
        secondary_type = (
            RISK_TYPE_LABELS.get(secondary_category)
            if secondary_score > 0 and secondary_category != "stable"
            else None
        )
        summary = {
            "academic_decline": (
                "Academic performance and submission behavior are the main sources of risk."
            ),
            "attendance_driven": (
                "Attendance deterioration is currently the dominant operational risk pattern."
            ),
            "engagement_drop": (
                "Reduced LMS engagement is the strongest warning signal at the moment."
            ),
            "finance_driven": (
                "Finance-related signals are materially increasing operational risk."
            ),
            "stable_profile": "No dominant operational risk category is currently standing out.",
        }.get(primary_type, "Current risk drivers require multi-domain attention.")

    return {
        "primary_type": primary_type,
        "secondary_type": secondary_type,
        "summary": summary,
        "category_scores": {
            "academic": int(category_scores.get("academic", 0)),
            "attendance": int(category_scores.get("attendance", 0)),
            "engagement": int(category_scores.get("engagement", 0)),
            "finance": int(category_scores.get("finance", 0)),
        },
    }


def build_action_recommendations(
    *,
    risk_type: dict,
    drivers: list[dict],
    final_risk_probability: float,
) -> list[dict]:
    primary_type = risk_type.get("primary_type")
    driver_names = {driver.get("driver_name") for driver in drivers}
    recommendations: list[dict] = []

    def _append(code: str, title: str, priority: str, rationale: str) -> None:
        if any(existing["action_code"] == code for existing in recommendations):
            return
        recommendations.append(
            {
                "action_code": code,
                "title": title,
                "priority": priority,
                "rationale": rationale,
            }
        )

    if primary_type == "attendance_driven":
        _append(
            "attendance_counselling",
            "Run an attendance recovery check-in",
            "IMMEDIATE" if final_risk_probability >= 0.85 else "THIS_WEEK",
            "Attendance is the dominant driver, so early mentor contact should focus on missed classes and recovery planning.",
        )
        _append(
            "subject_followup",
            "Notify subject faculty for weak-attendance courses",
            "THIS_WEEK",
            "Subject-wise attendance gaps need local faculty follow-up before the pattern worsens.",
        )
    elif primary_type == "academic_decline":
        _append(
            "academic_support_plan",
            "Create a short academic recovery plan",
            "IMMEDIATE" if final_risk_probability >= 0.85 else "THIS_WEEK",
            "Academic decline is the main risk source, so the student needs targeted support on marks, submissions, and deadlines.",
        )
        _append(
            "remedial_referral",
            "Refer to remedial or tutoring support",
            "THIS_WEEK",
            "Low scores or repeated late work indicate the student may need structured academic help.",
        )
    elif primary_type == "engagement_drop":
        _append(
            "engagement_reactivation",
            "Start an LMS re-engagement plan",
            "THIS_WEEK",
            "Recent academic activity has weakened, so a focused re-engagement check should happen quickly.",
        )
        _append(
            "assignment_completion_push",
            "Push completion of pending academic activity",
            "THIS_WEEK",
            "Low recent engagement often improves when the student is given a concrete next academic step.",
        )
    elif primary_type == "finance_driven":
        _append(
            "fee_counselling",
            "Arrange fee or scholarship counselling",
            "IMMEDIATE" if final_risk_probability >= 0.85 else "THIS_WEEK",
            "Finance signals are materially increasing risk and need administrative follow-up.",
        )
        _append(
            "finance_office_referral",
            "Coordinate with finance or student support office",
            "THIS_WEEK",
            "Students with fee pressure benefit from fast clarification of payment, waiver, or scholarship options.",
        )
    elif primary_type == "multi_factor_risk":
        _append(
            "case_conference",
            "Open a multi-factor support case",
            "IMMEDIATE",
            "Multiple domains are contributing to risk, so a coordinated intervention is safer than a single-channel response.",
        )
        _append(
            "weekly_monitoring",
            "Place the student on weekly monitoring",
            "THIS_WEEK",
            "Multi-factor cases need repeated review to confirm whether the intervention is working.",
        )

    if "finance_stress_modifier" in driver_names or "finance_context_modifier" in driver_names:
        _append(
            "financial_check",
            "Verify fee or financial pressure status",
            "THIS_WEEK",
            "Finance context is actively contributing to the current risk score.",
        )
    if "critical_attendance_drop" in driver_names or "consecutive_absence_pattern" in driver_names:
        _append(
            "urgent_attendance_call",
            "Make an urgent mentor call about absences",
            "IMMEDIATE",
            "Repeated or severe absence patterns should not wait for the next regular review cycle.",
        )
    if "declining_assessment_trend" in driver_names or "low_assessment_score" in driver_names:
        _append(
            "assessment_review",
            "Review recent assessment performance",
            "THIS_WEEK",
            "Declining marks need a concrete discussion on missed concepts and upcoming assessments.",
        )

    if not recommendations:
        _append(
            "monitor_and_recheck",
            "Continue monitoring with the next data refresh",
            "MONITOR",
            "No strong driver-specific action is required yet, but the student should remain under observation.",
        )

    return recommendations[:3]
