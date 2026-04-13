from __future__ import annotations

import os
import time

from dotenv import load_dotenv

from src.alerts.student_warning_service import send_student_warning_email
from src.db.database import SessionLocal
from src.db.repository import EventRepository


load_dotenv()

EMAIL_MAX_RETRIES = max(1, int(os.getenv("EMAIL_MAX_RETRIES", "3")))
EMAIL_RETRY_DELAY_SECONDS = float(os.getenv("EMAIL_RETRY_DELAY_SECONDS", "2"))


def dispatch_student_warning_email(
    warning_event_id: int,
    student_id: int,
    prediction_history_id: int,
    warning_type: str,
    recipient: str,
) -> None:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        prediction_record = repository.get_prediction_history_by_id(prediction_history_id)
        warning_event = repository.get_student_warning_event(warning_event_id)
        if prediction_record is None:
            repository.update_student_warning_event(
                warning_event_id,
                {
                    "delivery_status": "failed",
                    "error_message": "Prediction history record not found during warning dispatch.",
                },
            )
            return

        if warning_event is None:
            return

        result = None
        last_attempt = int(warning_event.retry_count or 0)
        resolved_recipient = (
            str(warning_event.recipient).strip()
            if str(warning_event.recipient).strip() != "unconfigured"
            else recipient
        )
        attempts_made = last_attempt
        for attempt in range(last_attempt + 1, EMAIL_MAX_RETRIES + 1):
            attempts_made = attempt
            repository.update_student_warning_event(
                warning_event_id,
                {
                    "delivery_status": "sending",
                    "retry_count": attempt,
                    "error_message": None,
                },
            )
            result = send_student_warning_email(
                student_id=student_id,
                prediction_record=prediction_record,
                recipient=resolved_recipient,
                warning_type=warning_type,
            )
            if result["status"] != "failed":
                break
            if attempt < EMAIL_MAX_RETRIES:
                time.sleep(EMAIL_RETRY_DELAY_SECONDS)

        if result is None:
            return
        repository.update_student_warning_event(
            warning_event_id,
            {
                "recipient": result["recipient"] or "unconfigured",
                "delivery_status": result["status"],
                "error_message": result["error_message"],
                "retry_count": max(attempts_made, 0),
            },
        )
        updated_warning = repository.get_student_warning_event(warning_event_id)
        print(
            f"[warnings.background] student_id={student_id} warning_type={warning_type} "
            f"status={result['status']} retries={updated_warning.retry_count if updated_warning else 'n/a'}"
        )
    finally:
        db.close()
