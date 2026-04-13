from __future__ import annotations

import os
from datetime import UTC, datetime

from dotenv import load_dotenv


load_dotenv()

FOLLOWUP_REMINDER_DELAY_HOURS = int(os.getenv("FOLLOWUP_REMINDER_DELAY_HOURS", "48"))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_context_timestamp(context: dict | None) -> datetime | None:
    context = context or {}
    for key in (
        "event_timestamp",
        "observed_at",
        "event_time",
        "recorded_at",
    ):
        value = context.get(key)
        if not value:
            continue
        try:
            return _as_utc(datetime.fromisoformat(str(value)))
        except ValueError:
            continue
    return None


def build_activity_summary(
    *,
    lms_events: list,
    erp_event,
    finance_event,
    reference_time: datetime | None = None,
) -> dict:
    now_utc = _as_utc(reference_time) or datetime.now(UTC)
    latest_lms_event_day = max((event.event_date for event in lms_events), default=None)
    erp_timestamp = _parse_context_timestamp(getattr(erp_event, "context_fields", None))
    finance_timestamp = _parse_context_timestamp(
        getattr(finance_event, "context_fields", None) if finance_event is not None else None
    )

    last_meaningful_activity_at = erp_timestamp or finance_timestamp
    if erp_timestamp is not None:
        source = "erp_assessment_sync"
    elif finance_timestamp is not None:
        source = "finance_event_sync"
    else:
        source = None

    days_since_last_meaningful_activity = (
        round((now_utc - last_meaningful_activity_at).total_seconds() / 86400, 2)
        if last_meaningful_activity_at is not None
        else None
    )

    if last_meaningful_activity_at is not None:
        summary = (
            f"Latest meaningful activity came from {source} at "
            f"{last_meaningful_activity_at.isoformat()}."
        )
    elif latest_lms_event_day is not None:
        summary = (
            "No absolute activity timestamp is available yet, but LMS activity exists "
            f"up to relative course day {latest_lms_event_day}."
        )
    else:
        summary = "No meaningful academic activity timestamp is currently available."

    return {
        "last_meaningful_activity_at": last_meaningful_activity_at,
        "last_meaningful_activity_source": source,
        "days_since_last_meaningful_activity": days_since_last_meaningful_activity,
        "latest_lms_event_day": latest_lms_event_day,
        "summary": summary,
    }


def build_milestone_flags(
    *,
    profile,
    erp_event,
    finance_event,
) -> dict:
    context = getattr(erp_event, "context_fields", None) or {}
    finance_context = getattr(finance_event, "context_fields", None) or {}
    finance_status = str(getattr(finance_event, "payment_status", "") or "").strip().lower()
    fee_delay_days = int(getattr(finance_event, "fee_delay_days", 0) or 0)
    fee_overdue_amount = float(getattr(finance_event, "fee_overdue_amount", 0.0) or 0.0)
    scholarship_status = str(finance_context.get("scholarship", "") or "").strip().lower()

    semester_number = context.get("semester_number")
    year_of_study = context.get("year_of_study", context.get("academic_year"))
    backlog_count = context.get("backlog_count", context.get("carried_backlogs"))
    academic_phase = str(context.get("academic_phase", "") or "").strip().lower()

    repeat_attempt_flag = float(getattr(profile, "num_previous_attempts", 0.0) or 0.0) >= 1.0
    first_year_flag = (
        (semester_number is not None and int(semester_number) <= 2)
        or (year_of_study is not None and int(year_of_study) == 1)
    )
    backlog_heavy_flag = backlog_count is not None and int(backlog_count) >= 3
    pre_exam_phase_flag = academic_phase in {
        "pre_exam",
        "exam_window",
        "final_exam_window",
        "midterm_window",
    }
    fee_pressure_flag = (
        fee_overdue_amount > 0
        and (finance_status in {"overdue", "partial_due", "unpaid"} or fee_delay_days >= 14)
    )
    scholarship_support_flag = scholarship_status in {"yes", "y", "true", "1", "active"}
    fee_support_gap_flag = fee_pressure_flag and not scholarship_support_flag

    active_flags: list[str] = []
    if repeat_attempt_flag:
        active_flags.append("repeat_attempt_risk")
    if first_year_flag:
        active_flags.append("first_year_transition")
    if backlog_heavy_flag:
        active_flags.append("backlog_heavy_phase")
    if pre_exam_phase_flag:
        active_flags.append("pre_exam_phase")
    if fee_pressure_flag:
        active_flags.append("fee_pressure")
    if scholarship_support_flag:
        active_flags.append("scholarship_recorded")
    if fee_support_gap_flag:
        active_flags.append("fee_support_gap")

    if active_flags:
        summary = "Active milestone flags: " + ", ".join(active_flags) + "."
    else:
        summary = "No critical milestone flag is currently active."

    return {
        "repeat_attempt_flag": repeat_attempt_flag,
        "first_year_flag": bool(first_year_flag),
        "backlog_heavy_flag": bool(backlog_heavy_flag),
        "pre_exam_phase_flag": bool(pre_exam_phase_flag),
        "fee_pressure_flag": bool(fee_pressure_flag),
        "active_flags": active_flags,
        "summary": summary,
    }


def build_sla_summary(
    *,
    latest_prediction,
    latest_warning,
    latest_alert,
    intervention_history: list,
    reference_time: datetime | None = None,
) -> dict:
    now_utc = _as_utc(reference_time) or datetime.now(UTC)
    prediction_time = _as_utc(getattr(latest_prediction, "created_at", None))
    warning_time = _as_utc(getattr(latest_warning, "sent_at", None))
    alert_time = _as_utc(getattr(latest_alert, "sent_at", None))

    hours_since_latest_prediction = (
        round((now_utc - prediction_time).total_seconds() / 3600, 2)
        if prediction_time is not None
        else None
    )
    hours_since_warning_created = (
        round((now_utc - warning_time).total_seconds() / 3600, 2)
        if warning_time is not None and latest_warning is not None and latest_warning.resolution_status is None
        else None
    )

    first_action_after_alert = None
    if alert_time is not None:
        for row in reversed(intervention_history):
            created_at = _as_utc(getattr(row, "created_at", None))
            if created_at is not None and created_at >= alert_time:
                first_action_after_alert = created_at
                break

    hours_to_first_faculty_action = (
        round((first_action_after_alert - alert_time).total_seconds() / 3600, 2)
        if first_action_after_alert is not None and alert_time is not None
        else None
    )
    hours_open_without_faculty_action = (
        round((now_utc - alert_time).total_seconds() / 3600, 2)
        if alert_time is not None and first_action_after_alert is None
        else None
    )
    followup_overdue = bool(
        alert_time is not None
        and first_action_after_alert is None
        and (now_utc - alert_time).total_seconds() / 3600 >= FOLLOWUP_REMINDER_DELAY_HOURS
    )

    if followup_overdue:
        sla_status = "overdue"
        summary = "Faculty follow-up is overdue for the current escalated case."
    elif hours_to_first_faculty_action is not None and hours_to_first_faculty_action <= 48:
        sla_status = "within_sla"
        summary = "Faculty follow-up met the expected response window."
    elif alert_time is not None and first_action_after_alert is None:
        sla_status = "attention_needed"
        summary = "The case is escalated and still awaiting the first faculty action."
    elif latest_warning is not None and latest_warning.resolution_status is None:
        sla_status = "within_monitoring"
        summary = "The student is still inside the warning-monitoring workflow."
    else:
        sla_status = "not_applicable"
        summary = "No active SLA-sensitive workflow is currently open."

    return {
        "sla_status": sla_status,
        "hours_since_latest_prediction": hours_since_latest_prediction,
        "hours_since_warning_created": hours_since_warning_created,
        "hours_to_first_faculty_action": hours_to_first_faculty_action,
        "hours_open_without_faculty_action": hours_open_without_faculty_action,
        "followup_overdue": followup_overdue,
        "summary": summary,
    }
