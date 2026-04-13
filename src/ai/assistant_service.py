from __future__ import annotations

import json
from typing import Any

from src.ai.llm_service import _call_gemini_with_retries, _is_gemini_available


_CASE_SUMMARY_SCHEMA: dict[str, Any] = {
    "name": "student_case_summary",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "headline": {"type": "string"},
            "summary": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
            "recommended_followup": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["headline", "summary", "key_points", "recommended_followup"],
    },
}

_COMMUNICATION_DRAFT_SCHEMA: dict[str, Any] = {
    "name": "student_communication_draft",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "subject": {"type": "string"},
            "opening": {"type": "string"},
            "body": {"type": "string"},
            "closing": {"type": "string"},
        },
        "required": ["subject", "opening", "body", "closing"],
    },
}

_GUARDIAN_DRAFT_SCHEMA: dict[str, Any] = {
    "name": "guardian_communication_draft",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "subject": {"type": "string"},
            "opening": {"type": "string"},
            "body": {"type": "string"},
            "closing": {"type": "string"},
            "compact_text": {"type": "string"},
        },
        "required": ["subject", "opening", "body", "closing", "compact_text"],
    },
}

_RECOVERY_PLAN_SCHEMA: dict[str, Any] = {
    "name": "student_recovery_plan",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "plan_summary": {"type": "string"},
            "weekly_priorities": {"type": "array", "items": {"type": "string"}},
            "support_actions": {"type": "array", "items": {"type": "string"}},
            "success_signals": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "plan_summary",
            "weekly_priorities",
            "support_actions",
            "success_signals",
        ],
    },
}


def _safe_case_context(case_context: dict) -> str:
    intelligence = case_context.get("intelligence") or {}
    latest_prediction = case_context.get("latest_prediction")
    latest_warning = case_context.get("latest_warning")
    latest_alert = case_context.get("latest_alert")
    latest_intervention = case_context.get("latest_intervention")
    latest_guardian_alert = case_context.get("latest_guardian_alert")
    profile = case_context.get("profile")

    payload = {
        "profile": {
            "student_id": getattr(profile, "student_id", None),
            "faculty_name": getattr(profile, "faculty_name", None),
            "parent_name": getattr(profile, "parent_name", None),
            "parent_relationship": getattr(profile, "parent_relationship", None),
            "preferred_guardian_channel": getattr(profile, "preferred_guardian_channel", None),
            "guardian_contact_enabled": getattr(profile, "guardian_contact_enabled", None),
            "gender": getattr(profile, "gender", None),
            "highest_education": getattr(profile, "highest_education", None),
            "age_band": getattr(profile, "age_band", None),
            "num_previous_attempts": getattr(profile, "num_previous_attempts", None),
        },
        "latest_prediction": {
            "final_risk_probability": getattr(latest_prediction, "final_risk_probability", None),
            "final_predicted_class": getattr(latest_prediction, "final_predicted_class", None),
            "finance_modifier": getattr(latest_prediction, "finance_modifier", None),
        },
        "risk_trend": intelligence.get("risk_trend"),
        "stability": intelligence.get("stability"),
        "risk_type": intelligence.get("risk_type"),
        "recommended_actions": intelligence.get("recommended_actions"),
        "trigger_alerts": intelligence.get("trigger_alerts"),
        "drivers": intelligence.get("drivers"),
        "activity_summary": case_context.get("activity_summary"),
        "milestone_flags": case_context.get("milestone_flags"),
        "sla_summary": case_context.get("sla_summary"),
        "latest_warning": {
            "warning_type": getattr(latest_warning, "warning_type", None),
            "delivery_status": getattr(latest_warning, "delivery_status", None),
            "resolution_status": getattr(latest_warning, "resolution_status", None),
        },
        "latest_alert": {
            "alert_type": getattr(latest_alert, "alert_type", None),
            "email_status": getattr(latest_alert, "email_status", None),
        },
        "latest_intervention": {
            "action_status": getattr(latest_intervention, "action_status", None),
            "actor_name": getattr(latest_intervention, "actor_name", None),
            "notes": getattr(latest_intervention, "notes", None),
            "outcome_status": getattr(latest_intervention, "outcome_status", None),
        },
        "latest_guardian_alert": {
            "alert_type": getattr(latest_guardian_alert, "alert_type", None),
            "channel": getattr(latest_guardian_alert, "channel", None),
            "delivery_status": getattr(latest_guardian_alert, "delivery_status", None),
            "provider_name": getattr(latest_guardian_alert, "provider_name", None),
        },
    }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str)


def _fallback_case_summary(case_context: dict) -> dict:
    intelligence = case_context.get("intelligence") or {}
    latest_prediction = case_context.get("latest_prediction")
    risk_level = "HIGH" if int(getattr(latest_prediction, "final_predicted_class", 0)) == 1 else "LOW"
    headline = (
        "High-risk case needs active follow-up."
        if risk_level == "HIGH"
        else "Student is currently stable but should be monitored."
    )
    summary = (
        f"Current risk level is {risk_level} with dominant pattern "
        f"{(intelligence.get('risk_type') or {}).get('primary_type', 'unavailable')}."
    )
    key_points = [
        (intelligence.get("risk_trend") or {}).get("summary", "Trend summary unavailable."),
        (intelligence.get("stability") or {}).get("summary", "Stability summary unavailable."),
        (case_context.get("activity_summary") or {}).get("summary", "Activity summary unavailable."),
    ]
    recommended_followup = [
        item.get("title", "")
        for item in (intelligence.get("recommended_actions") or [])[:3]
        if item.get("title")
    ] or ["Continue monitoring and collect fresh academic data."]
    return {
        "source": "fallback",
        "headline": headline,
        "summary": summary,
        "key_points": key_points,
        "recommended_followup": recommended_followup,
    }


def _fallback_communication_draft(case_context: dict, audience: str) -> dict:
    intelligence = case_context.get("intelligence") or {}
    profile = case_context.get("profile")
    student_id = getattr(profile, "student_id", None)
    subject = f"Student support follow-up for {audience.replace('_', ' ')}"
    opening = (
        f"This is regarding student {student_id} and the latest retention support review."
    )
    body = (
        f"The current dominant risk pattern is {(intelligence.get('risk_type') or {}).get('primary_type', 'unavailable')}. "
        f"{(intelligence.get('risk_trend') or {}).get('summary', '')} "
        f"{(intelligence.get('stability') or {}).get('summary', '')}"
    ).strip()
    closing = "Please coordinate the next support step and monitor the student closely."
    return {
        "source": "fallback",
        "audience": audience,
        "subject": subject,
        "opening": opening,
        "body": body,
        "closing": closing,
    }


def _fallback_recovery_plan(case_context: dict) -> dict:
    intelligence = case_context.get("intelligence") or {}
    return {
        "source": "fallback",
        "plan_summary": "This recovery plan is based on the student's current dominant risk pattern and operational signals.",
        "weekly_priorities": [
            item.get("title", "")
            for item in (intelligence.get("recommended_actions") or [])[:3]
            if item.get("title")
        ] or ["Collect fresh academic and engagement data this week."],
        "support_actions": [
            "Log the next faculty follow-up clearly.",
            "Review attendance and submission behavior before the next check.",
        ],
        "success_signals": [
            "Improved attendance consistency",
            "Better submission completion",
            "Lower final risk probability on the next scoring pass",
        ],
    }


def _guardian_risk_concerns(case_context: dict) -> list[str]:
    intelligence = case_context.get("intelligence") or {}
    milestone_flags = case_context.get("milestone_flags") or {}
    latest_finance_event = case_context.get("latest_finance_event")
    risk_type = intelligence.get("risk_type") or {}
    primary_type = str(risk_type.get("primary_type") or "").strip().lower()
    secondary_type = str(risk_type.get("secondary_type") or "").strip().lower()
    category_scores = risk_type.get("category_scores") or {}

    concerns: list[str] = []

    def _add(label: str) -> None:
        if label not in concerns:
            concerns.append(label)

    if primary_type == "academic_decline" or secondary_type == "academic_decline" or int(category_scores.get("academic", 0)) > 0:
        _add("academics")
    if primary_type == "attendance_driven" or secondary_type == "attendance_driven" or int(category_scores.get("attendance", 0)) > 0:
        _add("attendance")
    if primary_type == "engagement_drop" or secondary_type == "engagement_drop" or int(category_scores.get("engagement", 0)) > 0:
        _add("engagement")

    fee_pressure = bool(milestone_flags.get("fee_pressure_flag"))
    overdue_amount = float(getattr(latest_finance_event, "fee_overdue_amount", 0.0) or 0.0)
    payment_status = str(getattr(latest_finance_event, "payment_status", "") or "").strip().lower()
    if (
        primary_type == "finance_driven"
        or secondary_type == "finance_driven"
        or int(category_scores.get("finance", 0)) > 0
        or fee_pressure
        or overdue_amount > 0
        or payment_status in {"overdue", "pending", "delayed"}
    ):
        _add("fee status")

    return concerns


def _guardian_next_step(case_context: dict) -> str:
    intelligence = case_context.get("intelligence") or {}
    for item in (intelligence.get("recommended_actions") or []):
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        lowered = title.lower()
        if "financial" in lowered or "fee" in lowered:
            return "contact the institution support team at the earliest so financial support can be discussed"
        if "academic" in lowered or "remedial" in lowered or "tutoring" in lowered:
            return "contact the institution support team at the earliest so academic support can be arranged"
        return "contact the institution support team at the earliest"
    return "contact the institution support team at the earliest"


def _join_human_list(items: list[str]) -> str:
    if not items:
        return "academic progress"
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _build_guardian_controlled_message(case_context: dict, channel: str, *, source: str) -> dict:
    profile = case_context.get("profile")
    student_id = getattr(profile, "student_id", None)
    guardian_name = getattr(profile, "parent_name", None) or "Parent/Guardian"
    risk_probability = float(
        getattr(case_context.get("latest_prediction"), "final_risk_probability", 0.0) or 0.0
    )
    concern_labels = _guardian_risk_concerns(case_context)
    concern_text = _join_human_list(concern_labels)
    next_step = _guardian_next_step(case_context)
    compact_text = (
        f"Dear Parent/Guardian, this is an important update regarding student {student_id}. "
        f"Our system indicates continued concern in {concern_text} despite earlier support steps. "
        "Please speak with the student and contact the institution support team at the earliest."
    )

    return {
        "source": source,
        "channel": channel,
        "guardian_name": guardian_name,
        "subject": "Important student support update",
        "opening": "Dear Parent/Guardian,",
        "body": (
            f"This is an important academic support update regarding Student ID {student_id}. "
            f"Our monitoring system indicates continued concern in {concern_text} even after earlier support steps. "
            "We recommend that you speak with the student and connect with the institution as soon as possible so timely help can be arranged. "
            f"The immediate next step is to {next_step}."
        ),
        "closing": (
            "If you would like to discuss the situation further, please contact the institution support team. "
            f"Current risk score: {risk_probability:.2f}."
        ),
        "compact_text": compact_text[:320] if channel == "sms" else compact_text,
    }


def _fallback_guardian_communication_draft(case_context: dict, channel: str) -> dict:
    return _build_guardian_controlled_message(case_context, channel, source="fallback")


def generate_case_summary(case_context: dict) -> dict:
    fallback = _fallback_case_summary(case_context)
    prompt = (
        "You are helping a university retention system summarize one student case for faculty use. "
        "Use the live structured case context below. "
        "Do not change any prediction. Focus on clarity, operational usefulness, and concise language.\n\n"
        f"Case context: {_safe_case_context(case_context)}\n\n"
        "Return valid JSON only."
    )
    if not _is_gemini_available():
        return fallback
    try:
        parsed = _call_gemini_with_retries(
            prompt=prompt,
            schema=_CASE_SUMMARY_SCHEMA["schema"],
            schema_name=_CASE_SUMMARY_SCHEMA["name"],
        )
        parsed["source"] = "gemini"
        return parsed
    except Exception:
        return fallback


def generate_communication_draft(case_context: dict, audience: str) -> dict:
    fallback = _fallback_communication_draft(case_context, audience)
    prompt = (
        "You are drafting a short supportive communication for a student-retention workflow. "
        f"The target audience is {audience}. "
        "Use the live case context below. Keep the message practical, supportive, and appropriate for institutional use. "
        "Do not invent facts not present in the context.\n\n"
        f"Case context: {_safe_case_context(case_context)}\n\n"
        "Return valid JSON only."
    )
    if not _is_gemini_available():
        return fallback
    try:
        parsed = _call_gemini_with_retries(
            prompt=prompt,
            schema=_COMMUNICATION_DRAFT_SCHEMA["schema"],
            schema_name=_COMMUNICATION_DRAFT_SCHEMA["name"],
        )
        parsed["source"] = "gemini"
        parsed["audience"] = audience
        return parsed
    except Exception:
        return fallback


def generate_guardian_communication_draft(
    case_context: dict,
    channel: str,
    *,
    allow_llm: bool = True,
) -> dict:
    fallback = _fallback_guardian_communication_draft(case_context, channel)
    prompt = (
        "You are drafting a respectful, high-sensitivity guardian communication for a university "
        "retention and welfare workflow. The audience is a parent or guardian, not faculty. "
        f"The delivery channel is {channel}. "
        "Use the structured live case context below. Keep the wording supportive, clear, non-blaming, "
        "and action-oriented. Mention only facts present in the context. "
        "Do not mention faculty names. Do not mention improved outlook or reassuring progress inside a worst-case escalation. "
        "Do not include internal workflow language. Keep concern areas simple: academics, attendance, engagement, or fee status. "
        "For SMS keep compact_text within 320 characters. For WhatsApp keep it concise but human. "
        "For email provide a usable subject, opening, body, and closing.\n\n"
        f"Case context: {_safe_case_context(case_context)}\n\n"
        "Return valid JSON only."
    )
    if not allow_llm or not _is_gemini_available():
        return fallback
    try:
        parsed = _call_gemini_with_retries(
            prompt=prompt,
            schema=_GUARDIAN_DRAFT_SCHEMA["schema"],
            schema_name=_GUARDIAN_DRAFT_SCHEMA["name"],
        )
        _ = parsed
        return _build_guardian_controlled_message(case_context, channel, source="gemini_guarded")
    except Exception:
        return fallback


def generate_recovery_plan(case_context: dict) -> dict:
    fallback = _fallback_recovery_plan(case_context)
    prompt = (
        "You are generating a one-week recovery support plan for a student in a university retention workflow. "
        "Use the live case context below. Keep the plan specific, realistic, and action-oriented. "
        "Do not change the prediction. Do not mention unavailable data.\n\n"
        f"Case context: {_safe_case_context(case_context)}\n\n"
        "Return valid JSON only."
    )
    if not _is_gemini_available():
        return fallback
    try:
        parsed = _call_gemini_with_retries(
            prompt=prompt,
            schema=_RECOVERY_PLAN_SCHEMA["schema"],
            schema_name=_RECOVERY_PLAN_SCHEMA["name"],
        )
        parsed["source"] = "gemini"
        return parsed
    except Exception:
        return fallback
