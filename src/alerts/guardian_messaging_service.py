from __future__ import annotations

import os
from typing import Literal

from dotenv import load_dotenv
import requests

from src.ai.assistant_service import generate_guardian_communication_draft
from src.api.ai_assistance_context import build_live_case_context

load_dotenv()

GuardianChannel = Literal["sms", "whatsapp"]

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01/Accounts"
TWILIO_PROVIDER_NAME = "twilio"
TWILIO_TIMEOUT_SECONDS = float(os.getenv("TWILIO_TIMEOUT_SECONDS", "20"))
DEFAULT_PHONE_COUNTRY_CODE = os.getenv("DEFAULT_PHONE_COUNTRY_CODE", "+91").strip() or "+91"
GUARDIAN_SMS_USE_LLM = (
    os.getenv("GUARDIAN_SMS_USE_LLM", "true").strip().lower()
    not in {"0", "false", "no", "off"}
)


def _twilio_account_sid() -> str:
    return os.getenv("TWILIO_ACCOUNT_SID", "").strip()


def _twilio_auth_token() -> str:
    return os.getenv("TWILIO_AUTH_TOKEN", "").strip()


def _twilio_sms_from() -> str:
    return os.getenv("TWILIO_SMS_FROM", "").strip()


def _twilio_whatsapp_from() -> str:
    value = os.getenv("TWILIO_WHATSAPP_FROM", "").strip()
    if value and not value.startswith("whatsapp:"):
        return f"whatsapp:{value}"
    return value


def _digits_only(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def normalize_guardian_phone(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if cleaned.startswith("+"):
        return f"+{_digits_only(cleaned)}"

    digits = _digits_only(cleaned)
    if not digits:
        return None
    if len(digits) == 10:
        return f"{DEFAULT_PHONE_COUNTRY_CODE}{digits}"
    if cleaned.startswith("00"):
        return f"+{digits[2:]}"
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    return f"+{digits}"


def _twilio_ready_for_channel(channel: GuardianChannel) -> bool:
    base_ready = bool(_twilio_account_sid() and _twilio_auth_token())
    if not base_ready:
        return False
    if channel == "sms":
        return bool(_twilio_sms_from())
    return bool(_twilio_whatsapp_from())


def _twilio_from_value(channel: GuardianChannel) -> str:
    return _twilio_sms_from() if channel == "sms" else _twilio_whatsapp_from()


def _twilio_to_value(channel: GuardianChannel, phone_number: str) -> str:
    if channel == "sms":
        return phone_number
    return f"whatsapp:{phone_number}"


def _guardian_message_body(
    *,
    student_id: int,
    prediction_record,
    channel: GuardianChannel,
) -> str:
    risk_probability = float(prediction_record.final_risk_probability)
    if channel == "sms":
        return (
            f"Dear Parent/Guardian, this is an important update regarding student {student_id}. "
            "Our system indicates continued academic or welfare concern despite earlier support steps. "
            "Please speak with the student and contact the institution support team at the earliest."
        )[:320]
    return (
        f"Urgent parent/guardian update for Student {student_id}. "
        f"The student remains high risk after earlier student and faculty support steps. "
        f"Current risk score: {risk_probability:.2f}. "
        "Recommended next step: Please contact the institution support team at the earliest."
    )


def send_guardian_mobile_message(
    *,
    channel: GuardianChannel,
    student_id: int,
    prediction_record,
    recipient: str | None,
    repository=None,
) -> dict:
    normalized_phone = normalize_guardian_phone(recipient)
    if normalized_phone is None:
        return {
            "recipient": None,
            "status": "skipped",
            "error_message": f"Guardian {channel} recipient is not configured.",
            "provider_name": TWILIO_PROVIDER_NAME,
            "provider_message_id": None,
        }

    if not _twilio_ready_for_channel(channel):
        return {
            "recipient": normalized_phone,
            "status": "provider_pending",
            "error_message": f"{channel} delivery provider is not configured yet.",
            "provider_name": TWILIO_PROVIDER_NAME,
            "provider_message_id": None,
        }

    account_sid = _twilio_account_sid()
    auth_token = _twilio_auth_token()
    body = _guardian_message_body(
        student_id=student_id,
        prediction_record=prediction_record,
        channel=channel,
    )
    if repository is not None and (channel != "sms" or GUARDIAN_SMS_USE_LLM):
        draft = generate_guardian_communication_draft(
            build_live_case_context(repository=repository, student_id=student_id),
            channel=channel,
            allow_llm=True,
        )
        draft_text = str(draft.get("compact_text", "")).strip() if isinstance(draft, dict) else ""
        if draft_text:
            body = draft_text

    try:
        response = requests.post(
            f"{TWILIO_API_BASE}/{account_sid}/Messages.json",
            auth=(account_sid, auth_token),
            data={
                "From": _twilio_from_value(channel),
                "To": _twilio_to_value(channel, normalized_phone),
                "Body": body,
            },
            timeout=TWILIO_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            try:
                error_payload = response.json()
                error_message = error_payload.get("message") or response.text
            except Exception:
                error_message = response.text
            return {
                "recipient": normalized_phone,
                "status": "failed",
                "error_message": error_message,
                "provider_name": TWILIO_PROVIDER_NAME,
                "provider_message_id": None,
            }

        payload = response.json()
        return {
            "recipient": normalized_phone,
            "status": "sent",
            "error_message": None,
            "provider_name": TWILIO_PROVIDER_NAME,
            "provider_message_id": payload.get("sid"),
        }
    except Exception as error:
        return {
            "recipient": normalized_phone,
            "status": "failed",
            "error_message": str(error),
            "provider_name": TWILIO_PROVIDER_NAME,
            "provider_message_id": None,
        }
