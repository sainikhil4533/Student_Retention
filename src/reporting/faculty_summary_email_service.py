from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv


load_dotenv()


def _get_recipient() -> str | None:
    return os.getenv("FACULTY_ALERT_EMAIL", "").strip() or None


def _is_smtp_configured() -> bool:
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"]
    return all(os.getenv(key, "").strip() for key in required)


def _build_summary_body(snapshot_item) -> str:
    summary = snapshot_item.summary
    institution_overview = snapshot_item.institution_overview
    intervention_effectiveness = snapshot_item.intervention_effectiveness

    def _student_lines(rows: list) -> str:
        if not rows:
            return "- None"
        return "\n".join(
            f"- Student {row.student_id}: {row.note or row.status}"
            for row in rows[:5]
        )

    def _bucket_lines(rows: list) -> str:
        if not rows:
            return "- None"
        return "\n".join(
            f"- {row.label}: high-risk={row.high_risk_students}, critical_triggers={row.critical_trigger_students}"
            for row in rows[:5]
        )

    def _action_lines(rows: list) -> str:
        if not rows:
            return "- None"
        return "\n".join(
            f"- {row.action_status}: improved={row.improved_count}, false_alerts={row.false_alert_count}, reviewed={row.reviewed_actions}"
            for row in rows[:5]
        )

    return (
        f"Faculty Summary Snapshot\n"
        f"Snapshot Type: {snapshot_item.snapshot_type}\n"
        f"Generated At: {snapshot_item.generated_at.isoformat() if snapshot_item.generated_at else 'N/A'}\n\n"
        f"Counts\n"
        f"- Active high-risk students: {summary.total_active_high_risk_students}\n"
        f"- Active recovery windows: {summary.total_active_recovery_windows}\n"
        f"- Expired recovery windows: {summary.total_expired_recovery_windows}\n"
        f"- Escalated cases: {summary.total_escalated_cases}\n"
        f"- Follow-up reminders sent: {summary.total_followup_reminders_sent}\n"
        f"- Resolution candidates: {summary.total_resolution_candidates}\n"
        f"- Reopened cases: {summary.total_reopened_cases}\n"
        f"- Repeated-risk students: {summary.total_repeated_risk_students}\n"
        f"- Unhandled escalations: {summary.total_unhandled_escalations}\n\n"
        f"Institution Overview\n"
        f"- High-risk students in live cohort: {institution_overview.total_high_risk_students if institution_overview else 'N/A'}\n"
        f"- Critical-trigger students: {institution_overview.total_critical_trigger_students if institution_overview else 'N/A'}\n"
        f"- Follow-up overdue students: {institution_overview.total_followup_overdue_students if institution_overview else 'N/A'}\n"
        f"Top departments:\n{_bucket_lines(institution_overview.department_buckets if institution_overview else [])}\n\n"
        f"Intervention Effectiveness\n"
        f"- Review coverage: {intervention_effectiveness.review_coverage_percent if intervention_effectiveness else 'N/A'}%\n"
        f"- Improvement rate: {intervention_effectiveness.improvement_rate_percent if intervention_effectiveness else 'N/A'}%\n"
        f"- False-alert rate: {intervention_effectiveness.false_alert_rate_percent if intervention_effectiveness else 'N/A'}%\n"
        f"Action highlights:\n{_action_lines(intervention_effectiveness.action_effectiveness if intervention_effectiveness else [])}\n\n"
        f"Priority Highlights\n"
        f"Unhandled escalations:\n{_student_lines(summary.unhandled_escalation_students)}\n\n"
        f"Reopened cases:\n{_student_lines(summary.reopened_case_students)}\n\n"
        f"Active recovery windows:\n{_student_lines(summary.active_recovery_students)}\n"
    )


def send_faculty_summary_email(snapshot_item) -> dict:
    recipient = _get_recipient()
    if recipient is None:
        return {
            "recipient": None,
            "status": "skipped",
            "error_message": "FACULTY_ALERT_EMAIL is not configured.",
        }

    if not _is_smtp_configured():
        return {
            "recipient": recipient,
            "status": "skipped",
            "error_message": "SMTP configuration is incomplete.",
        }

    message = EmailMessage()
    message["Subject"] = (
        f"Faculty Daily Summary Report - "
        f"{snapshot_item.generated_at.strftime('%Y-%m-%d') if snapshot_item.generated_at else 'Generated'}"
    )
    message["From"] = os.getenv("SMTP_FROM_EMAIL", "").strip()
    message["To"] = recipient
    message.set_content(_build_summary_body(snapshot_item))

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
