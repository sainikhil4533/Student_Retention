from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv

from src.ai.assistant_service import generate_guardian_communication_draft
from src.api.ai_assistance_context import build_live_case_context

load_dotenv()


def get_default_alert_recipient() -> str | None:
    return os.getenv("FACULTY_ALERT_EMAIL", "").strip() or None


def get_alert_recipient(student_profile=None) -> str | None:
    # FACULTY_ALERT_EMAIL in .env always takes priority
    env_recipient = get_default_alert_recipient()
    if env_recipient:
        return env_recipient
    # Fall back to the student's assigned faculty email only if env var is not set
    if student_profile is not None:
        faculty_email = getattr(student_profile, "faculty_email", None)
        if faculty_email is not None and str(faculty_email).strip():
            return str(faculty_email).strip()
    return None


def is_smtp_configured() -> bool:
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"]
    return all(os.getenv(key, "").strip() for key in required)


def _subject_for_alert_type(alert_type: str) -> str:
    if alert_type == "faculty_followup_reminder":
        return "[RetentionOS] Follow-Up Reminder: High Risk Student Case Still Open"
    if alert_type == "post_warning_escalation":
        return "[RetentionOS] Escalation Notice: Student Requires Faculty Attention"
    return "[RetentionOS] Alert: High Risk Student Requires Attention"


def _intro_for_alert_type(alert_type: str) -> str:
    if alert_type == "faculty_followup_reminder":
        return (
            "This is an automated reminder that a previously escalated high-risk student case "
            "still has no recorded faculty follow-up action."
        )
    if alert_type == "post_warning_escalation":
        return (
            "The student remained high risk after the recovery window, so the case has been "
            "escalated to faculty."
        )
    return "A high-risk student condition has been detected."


def _build_email_body(student_id: int, prediction_record, alert_type: str) -> str:
    ai_insights = prediction_record.ai_insights or {}
    actions = ai_insights.get("actions") or []
    actions_text = "\n".join(f"- {action}" for action in actions) or "- No actions provided."

    return (
        f"{_intro_for_alert_type(alert_type)}\n\n"
        f"Student ID: {student_id}\n"
        f"Alert Type: {alert_type}\n"
        f"Risk Level: {'HIGH' if int(prediction_record.final_predicted_class) == 1 else 'LOW'}\n"
        f"Final Risk Probability: {float(prediction_record.final_risk_probability):.4f}\n"
        f"Urgency: {ai_insights.get('urgency', 'HIGH')}\n"
        f"Timeline: {ai_insights.get('timeline', 'Immediate')}\n\n"
        f"AI Reasoning:\n{ai_insights.get('reasoning', 'No reasoning available.')}\n\n"
        f"Recommended Actions:\n{actions_text}\n\n"
        f"---\nThis is an automated message from RetentionOS.\n"
        f"Do not reply directly to this email.\n"
        f"Log in to the RetentionOS dashboard to take action on this case.\n"
    )


def send_alert_email(student_id: int, prediction_record, alert_type: str, recipient: str | None = None) -> dict:
    resolved_recipient = recipient.strip() if recipient and recipient.strip() else None
    recipient = resolved_recipient or get_default_alert_recipient()
    if recipient is None:
        return {
            "recipient": None,
            "status": "skipped",
            "error_message": "Faculty alert recipient is not configured.",
        }

    if not is_smtp_configured():
        return {
            "recipient": recipient,
            "status": "skipped",
            "error_message": "SMTP configuration is incomplete.",
        }

    from_addr = os.getenv("SMTP_FROM_EMAIL", "").strip()
    message = EmailMessage()
    message["Subject"] = _subject_for_alert_type(alert_type)
    message["From"] = f"RetentionOS Alerts <{from_addr}>"
    message["To"] = recipient
    message["Reply-To"] = from_addr
    message.set_content(_build_email_body(student_id, prediction_record, alert_type))

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


def send_guardian_email(
    *,
    student_id: int,
    prediction_record,
    recipient: str,
    guardian_name: str | None = None,
    guardian_relationship: str | None = None,
    repository=None,
) -> dict:
    if not recipient.strip():
        return {
            "recipient": None,
            "status": "skipped",
            "error_message": "Guardian email is not configured.",
        }

    if not is_smtp_configured():
        return {
            "recipient": recipient,
            "status": "skipped",
            "error_message": "SMTP configuration is incomplete.",
        }

    greeting_name = guardian_name or "Parent/Guardian"
    relationship_text = f" ({guardian_relationship})" if guardian_relationship else ""
    draft = None
    if repository is not None:
        draft = generate_guardian_communication_draft(
            build_live_case_context(repository=repository, student_id=student_id),
            channel="email",
        )
    ai_insights = prediction_record.ai_insights or {}
    actions = ai_insights.get("actions") or []
    actions_text = "\n".join(f"- {item}" for item in actions[:3]) or "- Please contact the institution immediately for support."
    fallback_body = (
        f"Dear {greeting_name}{relationship_text},\n\n"
        f"This is an urgent student-support message regarding Student ID {student_id}.\n\n"
        f"Our academic monitoring system indicates that the student is still in a serious risk state "
        f"even after earlier student and faculty follow-up steps.\n\n"
        f"Current Risk Probability: {float(prediction_record.final_risk_probability):.4f}\n"
        f"Urgency: {ai_insights.get('urgency', 'HIGH')}\n"
        f"Timeline: {ai_insights.get('timeline', 'Immediate attention is recommended.')}\n\n"
        f"Current concern summary:\n{ai_insights.get('reasoning', 'The student currently needs urgent academic and welfare support.')}\n\n"
        f"Suggested next steps:\n{actions_text}\n\n"
        "Please connect with the student and the institution as soon as possible so coordinated support can be arranged.\n"
    )

    message = EmailMessage()
    message["Subject"] = (
        draft.get("subject", "").strip()
        if isinstance(draft, dict) and draft.get("subject")
        else "Urgent Student Welfare Update - Parent/Guardian Attention Needed"
    )
    message["From"] = os.getenv("SMTP_FROM_EMAIL", "").strip()
    message["To"] = recipient
    if isinstance(draft, dict):
        message.set_content(
            "\n\n".join(
                part
                for part in [
                    draft.get("opening", "").strip() or f"Dear {greeting_name}{relationship_text},",
                    draft.get("body", "").strip(),
                    draft.get("closing", "").strip(),
                ]
                if part
            )
        )
    else:
        message.set_content(fallback_body)

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
