from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv

from src.alerts.email_service import get_alert_recipient, is_smtp_configured
from src.alerts.guardian_alert_service import queue_guardian_escalation_if_eligible
from src.db.database import SessionLocal
from src.db.repository import EventRepository
from src.worker.job_queue import enqueue_faculty_alert_email_job


load_dotenv()

RECOVERY_ESCALATION_CHECK_SECONDS = int(
    os.getenv("RECOVERY_ESCALATION_CHECK_SECONDS", "60")
)
ENABLE_RECOVERY_ESCALATION_MONITOR = (
    os.getenv("ENABLE_RECOVERY_ESCALATION_MONITOR", "true").strip().lower()
    not in {"0", "false", "no", "off"}
)
FOLLOWUP_REMINDER_DELAY_HOURS = int(
    os.getenv("FOLLOWUP_REMINDER_DELAY_HOURS", "48")
)
FACULTY_HANDLED_STATUSES = {
    "seen",
    "acknowledged",
    "contacted",
    "support_provided",
    "resolved",
}


def _is_faculty_resolved_for_current_case(latest_prediction, latest_intervention) -> bool:
    if latest_prediction is None or latest_intervention is None:
        return False

    status = str(latest_intervention.action_status).strip().lower()
    if status != "resolved":
        return False

    intervention_time = latest_intervention.created_at
    prediction_time = latest_prediction.created_at
    if intervention_time is None or prediction_time is None:
        return False

    return intervention_time >= prediction_time


def _intervention_status(latest_intervention) -> str | None:
    if latest_intervention is None:
        return None
    return str(latest_intervention.action_status).strip().lower()


def _has_followup_after_escalation(latest_escalation, latest_intervention) -> bool:
    if latest_escalation is None or latest_intervention is None:
        return False

    status = _intervention_status(latest_intervention)
    intervention_time = latest_intervention.created_at
    escalation_time = latest_escalation.sent_at
    if status not in FACULTY_HANDLED_STATUSES:
        return False
    if intervention_time is None or escalation_time is None:
        return False

    return intervention_time >= escalation_time


def _has_reminder_for_escalation(latest_escalation, alert_history) -> bool:
    if latest_escalation is None or latest_escalation.sent_at is None:
        return False

    escalation_time = latest_escalation.sent_at
    for alert in alert_history:
        if alert.alert_type != "faculty_followup_reminder":
            continue
        reminder_time = alert.sent_at
        if reminder_time is None:
            continue
        if reminder_time >= escalation_time:
            return True

    return False


def _maybe_create_followup_reminder(repository: EventRepository, reference_time: datetime) -> int:
    reminder_count = 0
    latest_predictions = repository.get_latest_predictions_for_all_students()

    for prediction in latest_predictions:
        student_id = int(prediction.student_id)
        alert_history = repository.get_alert_history_for_student(student_id)
        latest_escalation = next(
            (row for row in alert_history if row.alert_type == "post_warning_escalation"),
            None,
        )
        if latest_escalation is None:
            continue
        if latest_escalation.email_status != "sent" or latest_escalation.sent_at is None:
            continue
        if int(prediction.final_predicted_class) != 1:
            continue

        latest_intervention = repository.get_latest_intervention_for_student(student_id)
        if _has_followup_after_escalation(latest_escalation, latest_intervention):
            continue
        if _has_reminder_for_escalation(latest_escalation, alert_history):
            continue

        if latest_escalation.sent_at + timedelta(hours=FOLLOWUP_REMINDER_DELAY_HOURS) > reference_time:
            continue

        profile = repository.get_student_profile(student_id)
        recipient = get_alert_recipient(profile)
        if recipient is None:
            alert_status = "skipped"
            error_message = "Faculty alert recipient is not configured."
        elif not is_smtp_configured():
            alert_status = "skipped"
            error_message = "SMTP configuration is incomplete."
        else:
            alert_status = "pending"
            error_message = None

        reminder_event = repository.add_alert_event(
            {
                "student_id": student_id,
                "prediction_history_id": prediction.id,
                "alert_type": "faculty_followup_reminder",
                "risk_level": "HIGH",
                "final_risk_probability": float(prediction.final_risk_probability),
                "recipient": recipient or "unconfigured",
                "email_status": alert_status,
                "error_message": error_message,
            }
        )

        if alert_status == "pending":
            enqueue_faculty_alert_email_job(
                alert_event_id=reminder_event.id,
                student_id=student_id,
                prediction_history_id=prediction.id,
                alert_type="faculty_followup_reminder",
            )

        reminder_count += 1
        print(
            f"[recovery.monitor] followup_reminder student_id={student_id} "
            f"alert_status={alert_status}",
            flush=True,
        )

    return reminder_count


def _maybe_queue_guardian_escalations(repository: EventRepository) -> int:
    guardian_count = 0
    latest_predictions = repository.get_latest_predictions_for_all_students()

    for prediction in latest_predictions:
        student_id = int(prediction.student_id)
        result = queue_guardian_escalation_if_eligible(
            repository,
            student_id=student_id,
            actor_role="system",
            actor_subject="recovery_monitor",
        )
        if result.queued:
            guardian_count += 1
            print(
                f"[recovery.monitor] guardian_escalation student_id={student_id} "
                f"channel={result.assessment.channel}",
                flush=True,
            )

    return guardian_count


def run_recovery_escalation_pass() -> dict[str, int]:
    db = SessionLocal()
    escalated_count = 0
    reminder_count = 0
    guardian_count = 0
    try:
        repository = EventRepository(db)
        reference_time = datetime.now(UTC)
        expired_warnings = repository.get_expired_active_student_warnings(
            reference_time=reference_time
        )

        for warning in expired_warnings:
            latest_prediction = repository.get_latest_prediction_for_student(warning.student_id)
            if latest_prediction is None:
                repository.update_student_warning_event(
                    warning.id,
                    {
                        "resolved_at": datetime.now(UTC),
                        "resolution_status": "missing_prediction",
                        "error_message": "No latest prediction found during scheduled escalation.",
                    },
                )
                continue

            latest_intervention = repository.get_latest_intervention_for_student(
                warning.student_id
            )
            if _is_faculty_resolved_for_current_case(
                latest_prediction=latest_prediction,
                latest_intervention=latest_intervention,
            ):
                repository.update_student_warning_event(
                    warning.id,
                    {
                        "resolved_at": datetime.now(UTC),
                        "resolution_status": "faculty_resolved",
                    },
                )
                continue

            if int(latest_prediction.final_predicted_class) != 1:
                repository.update_student_warning_event(
                    warning.id,
                    {
                        "resolved_at": datetime.now(UTC),
                        "resolution_status": "recovered",
                    },
                )
                continue

            profile = repository.get_student_profile(warning.student_id)
            recipient = get_alert_recipient(profile)
            if recipient is None:
                alert_status = "skipped"
                error_message = "Faculty alert recipient is not configured."
            elif not is_smtp_configured():
                alert_status = "skipped"
                error_message = "SMTP configuration is incomplete."
            else:
                alert_status = "pending"
                error_message = None

            alert_event = repository.add_alert_event(
                {
                    "student_id": warning.student_id,
                    "prediction_history_id": latest_prediction.id,
                    "alert_type": "post_warning_escalation",
                    "risk_level": "HIGH",
                    "final_risk_probability": float(latest_prediction.final_risk_probability),
                    "recipient": recipient or "unconfigured",
                    "email_status": alert_status,
                    "error_message": error_message,
                }
            )
            repository.update_student_warning_event(
                warning.id,
                {
                    "resolved_at": datetime.now(UTC),
                    "resolution_status": "escalated_to_faculty",
                },
            )

            if alert_status == "pending":
                enqueue_faculty_alert_email_job(
                    alert_event_id=alert_event.id,
                    student_id=warning.student_id,
                    prediction_history_id=latest_prediction.id,
                    alert_type="post_warning_escalation",
                )

            escalated_count += 1
            print(
                f"[recovery.monitor] student_id={warning.student_id} "
                f"alert_status={alert_status}",
                flush=True,
            )

        reminder_count = _maybe_create_followup_reminder(
            repository=repository,
            reference_time=reference_time,
        )
        guardian_count = _maybe_queue_guardian_escalations(repository)
        return {
            "escalated_count": escalated_count,
            "reminder_count": reminder_count,
            "guardian_count": guardian_count,
        }
    finally:
        db.close()


async def recovery_escalation_monitor_loop() -> None:
    print(
        f"[recovery.monitor] started interval={RECOVERY_ESCALATION_CHECK_SECONDS}s",
        flush=True,
    )
    try:
        while True:
            try:
                result = await asyncio.to_thread(run_recovery_escalation_pass)
                escalated = int(result.get("escalated_count", 0))
                reminders = int(result.get("reminder_count", 0))
                guardians = int(result.get("guardian_count", 0))
                if escalated:
                    print(
                        f"[recovery.monitor] escalated_count={escalated}",
                        flush=True,
                    )
                if reminders:
                    print(
                        f"[recovery.monitor] reminder_count={reminders}",
                        flush=True,
                    )
                if guardians:
                    print(
                        f"[recovery.monitor] guardian_count={guardians}",
                        flush=True,
                    )
            except Exception as error:
                print(f"[recovery.monitor] pass failed: {error}", flush=True)

            await asyncio.sleep(RECOVERY_ESCALATION_CHECK_SECONDS)
    except asyncio.CancelledError:
        print("[recovery.monitor] stopped", flush=True)
        raise


async def start_recovery_monitor_if_enabled() -> asyncio.Task | None:
    if not ENABLE_RECOVERY_ESCALATION_MONITOR:
        print("[recovery.monitor] disabled by configuration", flush=True)
        return None
    return asyncio.create_task(recovery_escalation_monitor_loop())


async def stop_recovery_monitor(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
