from __future__ import annotations

import os
import time

from dotenv import load_dotenv

from src.alerts.email_service import send_guardian_email
from src.alerts.guardian_messaging_service import send_guardian_mobile_message
from src.db.database import SessionLocal
from src.db.repository import EventRepository


load_dotenv()

EMAIL_MAX_RETRIES = max(1, int(os.getenv("EMAIL_MAX_RETRIES", "3")))
EMAIL_RETRY_DELAY_SECONDS = float(os.getenv("EMAIL_RETRY_DELAY_SECONDS", "2"))


def dispatch_guardian_alert(guardian_alert_event_id: int) -> None:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        alert_event = repository.get_guardian_alert_event(guardian_alert_event_id)
        if alert_event is None:
            return

        prediction_record = repository.get_prediction_history_by_id(alert_event.prediction_history_id)
        if prediction_record is None:
            repository.update_guardian_alert_event(
                guardian_alert_event_id,
                {
                    "delivery_status": "failed",
                    "error_message": "Prediction history record not found during guardian dispatch.",
                },
            )
            return

        channel = str(alert_event.channel or "").strip().lower()
        result = None
        last_attempt = int(alert_event.retry_count or 0)
        attempts_made = last_attempt

        for attempt in range(last_attempt + 1, EMAIL_MAX_RETRIES + 1):
            attempts_made = attempt
            repository.update_guardian_alert_event(
                guardian_alert_event_id,
                {
                    "delivery_status": "sending",
                    "retry_count": attempt,
                    "error_message": None,
                },
            )
            if channel in {"sms", "whatsapp"}:
                result = send_guardian_mobile_message(
                    channel=channel,
                    student_id=int(alert_event.student_id),
                    prediction_record=prediction_record,
                    recipient=str(alert_event.recipient),
                    repository=repository,
                )
            else:
                result = send_guardian_email(
                    student_id=int(alert_event.student_id),
                    prediction_record=prediction_record,
                    recipient=str(alert_event.recipient),
                    guardian_name=alert_event.guardian_name,
                    guardian_relationship=alert_event.guardian_relationship,
                    repository=repository,
                )
            if result["status"] != "failed":
                break
            if attempt < EMAIL_MAX_RETRIES:
                time.sleep(EMAIL_RETRY_DELAY_SECONDS)

        if result is None:
            return

        repository.update_guardian_alert_event(
            guardian_alert_event_id,
            {
                "recipient": result["recipient"] or "unconfigured",
                "delivery_status": result["status"],
                "provider_name": result.get("provider_name"),
                "provider_message_id": result.get("provider_message_id"),
                "error_message": result["error_message"],
                "retry_count": max(attempts_made, 0),
            },
        )
        updated_event = repository.get_guardian_alert_event(guardian_alert_event_id)
        print(
            f"[guardian.background] student_id={alert_event.student_id} channel={channel or 'email'} "
            f"status={result['status']} retries={updated_event.retry_count if updated_event else 'n/a'}"
        )
    finally:
        db.close()
