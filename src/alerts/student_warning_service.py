from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv


load_dotenv()


def _smtp_configured() -> bool:
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"]
    return all(os.getenv(key, "").strip() for key in required)


def send_student_warning_email(student_id: int, prediction_record, recipient: str, warning_type: str) -> dict:
    if not recipient.strip():
        return {
            "recipient": None,
            "status": "skipped",
            "error_message": "Student email is not configured.",
        }

    if not _smtp_configured():
        return {
            "recipient": recipient,
            "status": "skipped",
            "error_message": "SMTP configuration is incomplete.",
        }

    ai_insights = prediction_record.ai_insights or {}
    suggestions = ai_insights.get("student_guidance", {}).get("suggestions") or []
    suggestions_text = "\n".join(f"- {item}" for item in suggestions) or "- Follow the improvement plan shared by your institution."

    message = EmailMessage()
    message["Subject"] = "Student Support Warning - Action Needed"
    message["From"] = os.getenv("SMTP_FROM_EMAIL", "").strip()
    message["To"] = recipient
    message.set_content(
        f"Student ID: {student_id}\n"
        f"Warning Type: {warning_type}\n"
        f"Current Risk Level: {'HIGH' if int(prediction_record.final_predicted_class) == 1 else 'LOW'}\n"
        f"Current Risk Probability: {float(prediction_record.final_risk_probability):.4f}\n\n"
        f"Support Summary:\n{ai_insights.get('student_guidance', {}).get('summary', 'Please review your academic progress carefully.')}\n\n"
        f"Why this warning was sent:\n{ai_insights.get('reasoning', 'No additional reasoning available.')}\n\n"
        f"Recommended next steps:\n{suggestions_text}\n\n"
        f"Motivation:\n{ai_insights.get('student_guidance', {}).get('motivation', 'Please take action now and reach out for support if needed.')}\n"
    )

    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(message)
        return {
            "recipient": recipient,
            "status": "sent",
            "error_message": None,
        }
    except Exception as error:
        return {
            "recipient": recipient,
            "status": "failed",
            "error_message": str(error),
        }
