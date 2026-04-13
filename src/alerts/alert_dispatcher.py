from __future__ import annotations

import os
import time

from dotenv import load_dotenv

from src.alerts.email_service import send_alert_email
from src.db.database import SessionLocal
from src.db.repository import EventRepository


load_dotenv()

EMAIL_MAX_RETRIES = max(1, int(os.getenv("EMAIL_MAX_RETRIES", "3")))
EMAIL_RETRY_DELAY_SECONDS = float(os.getenv("EMAIL_RETRY_DELAY_SECONDS", "2"))


def dispatch_alert_email(alert_event_id: int, student_id: int, prediction_history_id: int, alert_type: str) -> None:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        prediction_record = repository.get_prediction_history_by_id(prediction_history_id)
        alert_event = repository.get_alert_event(alert_event_id)
        if prediction_record is None:
            repository.update_alert_event(
                alert_event_id,
                {
                    "email_status": "failed",
                    "error_message": "Prediction history record not found during alert dispatch.",
                },
            )
            return

        if alert_event is None:
            return

        email_result = None
        last_attempt = int(alert_event.retry_count or 0)
        recipient = (
            str(alert_event.recipient).strip()
            if str(alert_event.recipient).strip() != "unconfigured"
            else None
        )
        attempts_made = last_attempt
        for attempt in range(last_attempt + 1, EMAIL_MAX_RETRIES + 1):
            attempts_made = attempt
            repository.update_alert_event(
                alert_event_id,
                {
                    "email_status": "sending",
                    "retry_count": attempt,
                    "error_message": None,
                },
            )
            email_result = send_alert_email(
                student_id=student_id,
                prediction_record=prediction_record,
                alert_type=alert_type,
                recipient=recipient,
            )
            if email_result["status"] != "failed":
                break
            if attempt < EMAIL_MAX_RETRIES:
                time.sleep(EMAIL_RETRY_DELAY_SECONDS)

        if email_result is None:
            return
        repository.update_alert_event(
            alert_event_id,
            {
                "recipient": email_result["recipient"] or "unconfigured",
                "email_status": email_result["status"],
                "error_message": email_result["error_message"],
                "retry_count": max(attempts_made, 0),
            },
        )
        updated_alert = repository.get_alert_event(alert_event_id)
        print(
            f"[alerts.background] student_id={student_id} alert_type={alert_type} "
            f"status={email_result['status']} retries={updated_alert.retry_count if updated_alert else 'n/a'}"
        )
    finally:
        db.close()
