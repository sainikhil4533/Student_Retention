from __future__ import annotations


def _payment_status(value: str | None) -> str:
    return str(value or "").strip().lower()


def build_trigger_alerts(
    *,
    current_prediction,
    previous_prediction,
    current_erp,
    previous_erp,
    current_finance,
    previous_finance,
    attendance_summary: dict | None,
) -> dict:
    triggers: list[dict] = []
    attendance_summary = attendance_summary or {}

    def _append(
        trigger_code: str,
        title: str,
        severity: str,
        rationale: str,
        recommended_action: str,
    ) -> None:
        if any(existing["trigger_code"] == trigger_code for existing in triggers):
            return
        triggers.append(
            {
                "trigger_code": trigger_code,
                "title": title,
                "severity": severity,
                "rationale": rationale,
                "recommended_action": recommended_action,
            }
        )

    current_ratio = attendance_summary.get("attendance_ratio")
    previous_ratio = None
    previous_context = getattr(previous_erp, "context_fields", None) or {}
    if previous_context:
        previous_ratio = previous_context.get("attendance_ratio")

    if (
        current_ratio is not None
        and previous_ratio is not None
        and float(previous_ratio) - float(current_ratio) >= 0.1
    ):
        _append(
            "attendance_sharp_drop",
            "Attendance dropped sharply",
            "HIGH",
            (
                f"Attendance ratio fell from {float(previous_ratio):.2f} "
                f"to {float(current_ratio):.2f}."
            ),
            "Review recent absence causes and contact the student quickly.",
        )

    attendance_trend = attendance_summary.get("attendance_trend")
    consecutive_absences = attendance_summary.get("consecutive_absences")
    if attendance_trend is not None and float(attendance_trend) <= -0.08:
        _append(
            "attendance_decline_pattern",
            "Attendance is trending downward",
            "MEDIUM",
            f"Attendance trend is {float(attendance_trend):.2f}.",
            "Monitor attendance closely and initiate mentor follow-up this week.",
        )
    if consecutive_absences is not None and float(consecutive_absences) >= 3:
        _append(
            "consecutive_absence_trigger",
            "Repeated consecutive absences detected",
            "HIGH",
            f"Consecutive absences count is {float(consecutive_absences):.0f}.",
            "Make a direct welfare or mentor call to understand attendance barriers.",
        )

    current_submission_rate = float(getattr(current_erp, "assessment_submission_rate", 0.0) or 0.0)
    previous_submission_rate = (
        float(getattr(previous_erp, "assessment_submission_rate", 0.0) or 0.0)
        if previous_erp is not None
        else None
    )
    late_submission_count = float(getattr(current_erp, "late_submission_count", 0.0) or 0.0)
    if (
        previous_submission_rate is not None
        and previous_submission_rate - current_submission_rate >= 0.15
    ):
        _append(
            "submission_rate_drop",
            "Assignment submission rate dropped",
            "HIGH",
            (
                f"Submission rate fell from {previous_submission_rate:.2f} "
                f"to {current_submission_rate:.2f}."
            ),
            "Review pending coursework and set an immediate submission recovery plan.",
        )
    if late_submission_count >= 3 or current_submission_rate < 0.4:
        _append(
            "repeated_missed_submissions",
            "Repeated missed or late submissions",
            "HIGH",
            (
                f"Submission rate is {current_submission_rate:.2f} and "
                f"late submissions count is {late_submission_count:.0f}."
            ),
            "Open an academic support case focused on missed assessments and deadline discipline.",
        )

    current_score = float(getattr(current_erp, "weighted_assessment_score", 0.0) or 0.0)
    previous_score = (
        float(getattr(previous_erp, "weighted_assessment_score", 0.0) or 0.0)
        if previous_erp is not None
        else None
    )
    score_trend = float(getattr(current_erp, "assessment_score_trend", 0.0) or 0.0)
    if previous_score is not None and previous_score - current_score >= 10:
        _append(
            "marks_drop_trigger",
            "Assessment marks dropped sharply",
            "HIGH",
            f"Weighted score fell from {previous_score:.1f} to {current_score:.1f}.",
            "Review recent assessments with the student and refer to remedial support.",
        )
    if score_trend <= -5:
        _append(
            "consecutive_assessment_decline",
            "Marks are declining across recent assessments",
            "MEDIUM",
            f"Assessment score trend is {score_trend:.1f}.",
            "Investigate whether the student is struggling with recent modules or exam preparation.",
        )

    current_overdue = float(getattr(current_finance, "fee_overdue_amount", 0.0) or 0.0)
    current_delay = int(getattr(current_finance, "fee_delay_days", 0) or 0)
    current_payment_status = _payment_status(getattr(current_finance, "payment_status", None))
    previous_overdue = (
        float(getattr(previous_finance, "fee_overdue_amount", 0.0) or 0.0)
        if previous_finance is not None
        else 0.0
    )
    previous_payment_status = _payment_status(
        getattr(previous_finance, "payment_status", None)
        if previous_finance is not None
        else None
    )
    if (
        current_finance is not None
        and current_overdue > 0
        and current_payment_status in {"overdue", "partial_due", "unpaid"}
        and (current_delay >= 14 or previous_overdue > 0 or previous_payment_status in {"overdue", "partial_due", "unpaid"})
    ):
        _append(
            "fee_due_unresolved",
            "Fee due remains unresolved",
            "HIGH" if current_delay >= 30 else "MEDIUM",
            (
                f"Outstanding fee amount is {current_overdue:.2f} with "
                f"{current_delay} delay days."
            ),
            "Coordinate with finance support and verify whether fee pressure is affecting continuation.",
        )

    if (
        previous_prediction is not None
        and int(previous_prediction.final_predicted_class) == 0
        and int(current_prediction.final_predicted_class) == 1
    ):
        _append(
            "risk_threshold_crossed",
            "Risk crossed into high-alert state",
            "HIGH",
            (
                f"Final risk probability moved from "
                f"{float(previous_prediction.final_risk_probability):.2f} to "
                f"{float(current_prediction.final_risk_probability):.2f}."
            ),
            "Treat this as a newly escalated case and review the dominant drivers immediately.",
        )

    severity_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    triggers.sort(
        key=lambda item: (severity_rank.get(item["severity"], 0), item["trigger_code"]),
        reverse=True,
    )
    return {
        "triggers": triggers,
        "has_critical_trigger": any(item["severity"] == "HIGH" for item in triggers),
        "trigger_count": len(triggers),
        "summary": (
            "No major real-time trigger rule fired on the latest scoring pass."
            if not triggers
            else f"{len(triggers)} trigger rule(s) fired on the latest scoring pass."
        ),
    }
