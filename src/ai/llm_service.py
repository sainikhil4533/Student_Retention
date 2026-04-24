from __future__ import annotations

import json
import os
import time
from typing import Any

from dotenv import load_dotenv
from google import genai

from src.ai.fallback_reasoning import generate_fallback_insights


load_dotenv()

DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "3"))
GEMINI_RETRY_BASE_DELAY_SECONDS = float(
    os.getenv("GEMINI_RETRY_BASE_DELAY_SECONDS", "2.0")
)


def _has_real_secret(env_name: str) -> bool:
    value = os.getenv(env_name, "").strip()
    return bool(value) and not value.startswith("PASTE_YOUR_")


_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower()
_GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

_INSIGHTS_SCHEMA: dict[str, Any] = {
    "name": "student_retention_ai_insights",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "confidence": {"type": "string"},
            "reasoning": {"type": "string"},
            "actions": {
                "type": "array",
                "items": {"type": "string"},
            },
            "urgency": {
                "type": "string",
                "enum": ["LOW", "MEDIUM", "HIGH"],
            },
            "timeline": {"type": "string"},
            "student_guidance": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "summary": {"type": "string"},
                    "suggestions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "motivation": {"type": "string"},
                },
                "required": ["summary", "suggestions", "motivation"],
            },
        },
        "required": [
            "confidence",
            "reasoning",
            "actions",
            "urgency",
            "timeline",
            "student_guidance",
        ],
    },
}


def _build_student_summary(
    student_data: dict,
    finance_modifier: float,
    operational_context: dict | None = None,
) -> str:
    summary = {
        "demographics": {
            "gender": student_data.get("gender"),
            "highest_education": student_data.get("highest_education"),
            "age_band": student_data.get("age_band"),
            "disability_status": student_data.get("disability_status"),
            "num_previous_attempts": student_data.get("num_previous_attempts"),
        },
        "lms": {
            "lms_clicks_7d": student_data.get("lms_clicks_7d"),
            "lms_clicks_14d": student_data.get("lms_clicks_14d"),
            "lms_clicks_30d": student_data.get("lms_clicks_30d"),
            "lms_unique_resources_7d": student_data.get("lms_unique_resources_7d"),
            "days_since_last_lms_activity": student_data.get("days_since_last_lms_activity"),
            "lms_7d_vs_14d_percent_change": student_data.get("lms_7d_vs_14d_percent_change"),
            "engagement_acceleration": student_data.get("engagement_acceleration"),
        },
        "erp": {
            "assessment_submission_rate": student_data.get("assessment_submission_rate"),
            "weighted_assessment_score": student_data.get("weighted_assessment_score"),
            "late_submission_count": student_data.get("late_submission_count"),
            "total_assessments_completed": student_data.get("total_assessments_completed"),
            "assessment_score_trend": student_data.get("assessment_score_trend"),
        },
        "attendance": student_data.get("attendance_summary"),
        "finance_modifier": finance_modifier,
        "operational_context": operational_context or {},
    }
    return json.dumps(summary, separators=(",", ":"), ensure_ascii=True)


def _is_gemini_available() -> bool:
    return _has_real_secret("GEMINI_API_KEY")


def _is_groq_available() -> bool:
    return _has_real_secret("GROQ_API_KEY")



def _call_gemini_json(
    *,
    prompt: str,
    schema: dict[str, Any],
    schema_name: str,
) -> dict:
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    response = client.models.generate_content(
        model=DEFAULT_GEMINI_MODEL,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_json_schema": schema,
        },
    )
    text = getattr(response, "text", None)
    if not text:
        raise ValueError("Gemini response did not include text output.")

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"Gemini response for {schema_name} was not a JSON object.")
    return parsed


def _call_gemini_with_retries(
    *,
    prompt: str,
    schema: dict[str, Any],
    schema_name: str,
) -> dict:
    last_error: Exception | None = None

    for attempt in range(1, GEMINI_MAX_RETRIES + 1):
        try:
            print(
                f"[llm] Gemini attempt {attempt}/{GEMINI_MAX_RETRIES} "
                f"with model={DEFAULT_GEMINI_MODEL}",
                flush=True,
            )
            return _call_gemini_json(
                prompt=prompt,
                schema=schema,
                schema_name=schema_name,
            )
        except Exception as error:
            last_error = error
            if not _should_retry_gemini_error(error):
                print(
                    f"[llm] Gemini attempt {attempt} failed "
                    f"({type(error).__name__}: {error}); falling back without retry",
                    flush=True,
                )
                break
            if attempt >= GEMINI_MAX_RETRIES:
                break

            delay_seconds = GEMINI_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            print(
                f"[llm] Gemini attempt {attempt} failed "
                f"({type(error).__name__}: {error}); retrying in {delay_seconds:.1f}s",
                flush=True,
            )
            time.sleep(delay_seconds)

    assert last_error is not None
    raise last_error


def _call_groq_json(
    *,
    prompt: str,
) -> dict:
    from groq import Groq

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a specialized student retention analyst. Always return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Groq response did not include content output.")

    return json.loads(content)


def _should_retry_gemini_error(error: Exception) -> bool:
    text = str(error).lower()
    non_retriable_markers = (
        "resource_exhausted",
        "quota exceeded",
        "generate_content_free_tier_requests",
        "billing details",
        "api key not valid",
        "permission_denied",
        "unauthenticated",
        "invalid_argument",
    )
    return not any(marker in text for marker in non_retriable_markers)


def generate_ai_insights(
    student_data: dict,
    risk_score: float,
    risk_level: str,
    final_risk_probability: float,
    threshold: float,
    finance_modifier: float = 0.0,
    operational_context: dict | None = None,
) -> dict:
    fallback = generate_fallback_insights(
        student_data=student_data,
        risk_score=risk_score,
        risk_level=risk_level,
        final_risk_probability=final_risk_probability,
        threshold=threshold,
        finance_modifier=finance_modifier,
        operational_context=operational_context,
    )

    prompt = (
        "You are helping a student retention support system. "
        "The ML prediction is already final and must not be changed. "
        "Use the student summary below to provide concise structured support output.\n\n"
        f"Student summary: {_build_student_summary(student_data, finance_modifier, operational_context)}\n"
        f"Base risk score: {risk_score:.4f}\n"
        f"Final adjusted risk probability: {final_risk_probability:.4f}\n"
        f"Risk level: {risk_level}\n"
        f"Decision threshold: {threshold:.2f}\n\n"
        "Tasks:\n"
        "1. Explain why the student is at risk or stable.\n"
        "2. Use the operational context such as risk trend, dominant risk type, recommended actions, and stability when useful.\n"
        "3. Suggest actions for faculty.\n"
        "4. Set urgency and timeline.\n"
        "5. Provide supportive student guidance.\n"
        "6. Keep the response concise, practical, and non-threatening.\n"
        "7. Do not change the risk level or prediction.\n"
        "8. If operational trigger alerts are present, reflect them naturally in the explanation and urgency.\n"
        "9. Return valid JSON only."
    )

    # ── Attempt 1: Gemini ──
    if _is_gemini_available():
        try:
            parsed = _call_gemini_with_retries(
                prompt=prompt,
                schema=_INSIGHTS_SCHEMA["schema"],
                schema_name=_INSIGHTS_SCHEMA["name"],
            )
            parsed["source"] = "gemini"
            print("[llm] Gemini success", flush=True)
            return parsed
        except Exception as error:
            print(
                f"[llm] Gemini failed -> trying Groq fallback ({type(error).__name__}: {error})",
                flush=True,
            )

    # ── Attempt 2: Groq ──
    if _is_groq_available():
        try:
            print(f"[llm] Groq attempt with model={_GROQ_MODEL}", flush=True)
            parsed = _call_groq_json(prompt=prompt)
            parsed["source"] = "groq"
            print("[llm] Groq success", flush=True)
            return parsed
        except Exception as error:
            print(
                f"[llm] Groq failed -> using deterministic fallback ({type(error).__name__}: {error})",
                flush=True,
            )

    print("[llm] no LLM providers available -> using deterministic fallback", flush=True)
    return fallback
