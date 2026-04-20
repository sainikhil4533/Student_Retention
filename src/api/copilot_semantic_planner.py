from __future__ import annotations

import json
import os
import re
import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.ai.llm_service import (
    DEFAULT_GEMINI_MODEL,
    _call_gemini_with_retries,
    _is_gemini_available,
)
from src.api.auth import RoleName
from src.api.copilot_planner import CopilotQueryPlan, plan_copilot_query


CB19_PHASE_LABEL = "CB19"
CB19_PROVIDER_NAME = "gemini"
CB19_ENABLED = os.getenv("COPILOT_SEMANTIC_PLANNER_ENABLED", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
CB19_CACHE_ENABLED = os.getenv("COPILOT_SEMANTIC_CACHE_ENABLED", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
CB19_CACHE_VERSION = os.getenv("COPILOT_SEMANTIC_CACHE_VERSION", "4").strip() or "4"
CB19_CACHE_MAX_ENTRIES = max(20, int(os.getenv("COPILOT_SEMANTIC_CACHE_MAX_ENTRIES", "500")))
CB19_CACHE_PATH = Path(
    os.getenv(
        "COPILOT_SEMANTIC_CACHE_PATH",
        str(Path(".cache") / "copilot_semantic_planner_cache.json"),
    )
)
CB19_LOCAL_FALLBACK_ENABLED = os.getenv("COPILOT_LOCAL_SEMANTIC_FALLBACK_ENABLED", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

_SEMANTIC_PLANNER_SCHEMA: dict[str, Any] = {
    "name": "copilot_semantic_rewrite",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": ["keep", "rewrite", "clarify", "refuse"],
            },
            "rewritten_message": {"type": "string"},
            "clarification_question": {"type": "string"},
            "refusal_reason": {"type": "string"},
            "confidence": {"type": "number"},
            "rationale": {"type": "string"},
        },
        "required": [
            "action",
            "rewritten_message",
            "clarification_question",
            "refusal_reason",
            "confidence",
            "rationale",
        ],
    },
}


def plan_copilot_query_with_semantic_assist(
    *,
    role: RoleName,
    message: str,
    session_messages: list[object],
    profiles: list[object] | None = None,
) -> tuple[CopilotQueryPlan, dict[str, Any]]:
    base_plan = plan_copilot_query(
        role=role,
        message=message,
        session_messages=session_messages,
        profiles=profiles,
    )
    metadata: dict[str, Any] = {
        "phase": CB19_PHASE_LABEL,
        "enabled": CB19_ENABLED,
        "provider": CB19_PROVIDER_NAME,
        "model": DEFAULT_GEMINI_MODEL,
        "local_fallback_enabled": CB19_LOCAL_FALLBACK_ENABLED,
        "cache_enabled": CB19_CACHE_ENABLED,
        "cache_hit": False,
        "used": False,
        "status": "deterministic_only",
        "source_message": message,
        "rewritten_message": None,
        "rationale": None,
        "confidence": None,
    }

    if not CB19_ENABLED:
        metadata["status"] = "disabled"
        return base_plan, metadata

    if not _should_try_semantic_assist(
        base_plan=base_plan,
        message=message,
        session_messages=session_messages,
    ):
        metadata["status"] = "not_needed"
        return base_plan, metadata

    cache_key = _build_semantic_cache_key(role=role, message=message, session_messages=session_messages)
    if CB19_CACHE_ENABLED:
        cached_hint = _get_cached_semantic_hint(cache_key)
        if cached_hint is not None:
            metadata["cache_hit"] = True
            metadata["used"] = True
            return _apply_semantic_hint(
                base_plan=base_plan,
                semantic_hint=cached_hint,
                message=message,
                role=role,
                session_messages=session_messages,
                profiles=profiles,
                metadata=metadata,
                cache_key=cache_key,
                cached=True,
            )

    if CB19_LOCAL_FALLBACK_ENABLED:
        local_hint = _try_local_semantic_assist(
            role=role,
            message=message,
            base_plan=base_plan,
            session_messages=session_messages,
        )
        if local_hint is not None:
            metadata["provider"] = "local_fallback"
            metadata["model"] = None
            local_hint = {
                **local_hint,
                "_source_provider": "local_fallback",
            }
            return _apply_semantic_hint(
                base_plan=base_plan,
                semantic_hint=local_hint,
                message=message,
                role=role,
                session_messages=session_messages,
                profiles=profiles,
                metadata=metadata,
                cache_key=cache_key,
                cached=False,
            )

    if not _semantic_planner_available():
        metadata["status"] = "provider_unavailable"
        return base_plan, metadata

    try:
        semantic_hint = _call_semantic_planner(
            role=role,
            message=message,
            base_plan=base_plan,
        )
    except Exception as error:
        metadata["status"] = "provider_failed"
        metadata["error_type"] = type(error).__name__
        return base_plan, metadata
    semantic_hint = {
        **semantic_hint,
        "_source_provider": CB19_PROVIDER_NAME,
    }
    return _apply_semantic_hint(
        base_plan=base_plan,
        semantic_hint=semantic_hint,
        message=message,
        role=role,
        session_messages=session_messages,
        profiles=profiles,
        metadata=metadata,
        cache_key=cache_key,
        cached=False,
    )


def _clone_plan(plan: CopilotQueryPlan) -> CopilotQueryPlan:
    return CopilotQueryPlan(**deepcopy(plan.to_dict()))


def _semantic_planner_available() -> bool:
    return _is_gemini_available()


def _call_semantic_planner(
    *,
    role: RoleName,
    message: str,
    base_plan: CopilotQueryPlan,
) -> dict[str, Any]:
    prompt = (
        "You are a semantic normalization layer for a university retention copilot. "
        "Your job is not to answer the user. Your job is to decide whether the current message should be kept as-is, "
        "rewritten into a clearer grounded retention query, clarified, or refused.\n\n"
        f"Role: {role}\n"
        f"Original message: {message}\n"
        f"Deterministic planner summary: user_goal={base_plan.user_goal}, "
        f"primary_intent={base_plan.primary_intent}, analysis_mode={base_plan.analysis_mode}, "
        f"clarification_needed={base_plan.clarification_needed}, refusal_reason={base_plan.refusal_reason}, "
        f"confidence={base_plan.confidence:.2f}\n\n"
        "Supported grounded behaviors include:\n"
        "- comparison across one dimension at a time: branch, region, category, income, or outcome status\n"
        "- attention ranking: which bucket needs attention first and why\n"
        "- diagnostic comparison: what is driving the gap or pressure across a dimension\n"
        "- counsellor or student priority/risk questions inside role scope\n"
        "- refusal for secrets, passwords, tokens, credentials, or protected access data\n\n"
        "Rules:\n"
        "1. Prefer `keep` unless the wording is messy enough that a clearer grounded rewrite would materially help.\n"
        "2. If rewriting, produce a short grounded retention query that the deterministic planner can route safely.\n"
        "3. Never invent unsupported new backend abilities.\n"
        "4. Use `clarify` when more than one comparison dimension is truly competing.\n"
        "5. Use `refuse` only for sensitive/secret requests.\n"
        "6. Return valid JSON only.\n"
    )
    return _call_gemini_with_retries(
        prompt=prompt,
        schema=_SEMANTIC_PLANNER_SCHEMA["schema"],
        schema_name=_SEMANTIC_PLANNER_SCHEMA["name"],
    )


def _safe_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(parsed, 1.0))


def _should_try_semantic_assist(
    *,
    base_plan: CopilotQueryPlan,
    message: str,
    session_messages: list[object],
) -> bool:
    lowered = str(message or "").strip().lower()
    last_context = _extract_last_memory_context(session_messages)
    normalized_followup = _normalized_followup_text(lowered)
    fuzzy_tokens = {
        "strain",
        "slipping",
        "pressure",
        "watch closest",
        "driving the gap",
        "driving it",
        "what's behind",
        "hotspot",
        "pain point",
        "burden",
        "support gap",
        "coverage slipping",
        "heaviest",
        "gpa",
        "cgpa",
        "grade point",
        "login",
        "performing",
        "performance okay",
        "trouble",
        "worried",
        "worry",
        "serious",
        "panic",
        "improving",
        "worse",
        "fail",
        "future",
    }
    if _looks_like_legacy_grouped_or_subset_request(
        lowered=lowered,
        session_messages=session_messages,
    ) and not _should_preserve_local_followup_semantics(
        lowered=lowered,
        last_context=last_context,
    ):
        return False

    if base_plan.primary_intent == "cohort_summary" and any(
        phrase in lowered
        for phrase in {
            "show my assigned students",
            "show my students",
            "list my students",
            "list my assigned students",
            "who are my students",
            "who all are my students",
            "who are under me",
            "who all are under me",
        }
    ):
        return False

    if (
        normalized_followup in {
            "yes",
            "ok",
            "okay",
            "continue",
            "proceed",
            "go on",
            "then",
            "more",
            "what next",
            "next steps",
            "what now",
        }
        and str(last_context.get("pending_role_follow_up") or "").strip().lower() == "operational_actions"
    ):
        return False

    direct_supported_intents = {
        "student_self_attendance",
        "student_self_risk",
        "student_self_warning",
        "student_self_profile",
        "student_self_subject_risk",
        "student_self_plan",
        "student_drilldown",
        "identity",
        "help",
    }
    if (
        base_plan.primary_intent in direct_supported_intents
        and not base_plan.clarification_needed
        and not any(token in lowered for token in fuzzy_tokens)
    ):
        return False

    token_count = len([token for token in re.split(r"\s+", lowered) if token.strip()])
    if token_count <= 2 and base_plan.primary_intent != "unsupported" and not base_plan.clarification_needed:
        return False
    return (
        base_plan.user_goal in {"unknown"}
        or base_plan.primary_intent == "unsupported"
        or base_plan.clarification_needed
        or base_plan.confidence < 0.82
        or any(token in lowered for token in fuzzy_tokens)
    )


def _looks_like_legacy_grouped_or_subset_request(
    *,
    lowered: str,
    session_messages: list[object],
) -> bool:
    direct_grouped_markers = (
        " and tell me warnings",
        " and tell me counsellors",
        " and tell me how many are high risk",
        " and tell me risk",
        "show only the ",
        "only the ",
        "everything except ",
        "exclude the ",
        "bucket",
    )
    if any(marker in lowered for marker in direct_grouped_markers):
        return True

    short_metric_follow_ups = {
        "show risk",
        "show warnings",
        "show counsellors",
        "risk",
        "warnings",
        "counsellors",
    }
    if lowered in short_metric_follow_ups and session_messages:
        return True

    return False


def _should_preserve_local_followup_semantics(*, lowered: str, last_context: dict[str, Any]) -> bool:
    last_kind = str(last_context.get("kind") or "").strip().lower()
    last_grouped_by = str(last_context.get("grouped_by") or "").strip().lower()
    if last_kind not in {"import_coverage", "admin_academic"} or not last_grouped_by:
        return False
    return any(
        marker in lowered
        for marker in {
            "which is worse",
            "worse then",
            "what about only",
            "only the high-risk",
            "only the high risk",
            "just the high-risk",
            "just the high risk",
            "only ",
        }
    )


def _should_adopt_rewritten_plan(*, base_plan: CopilotQueryPlan, rewritten_plan: CopilotQueryPlan) -> bool:
    base_metrics = set(base_plan.metrics)
    rewritten_metrics = set(rewritten_plan.metrics)

    if rewritten_plan.refusal_reason and not base_plan.refusal_reason:
        return True
    if rewritten_plan.clarification_needed and not base_plan.clarification_needed and base_plan.user_goal == "unknown":
        return True
    if base_plan.primary_intent == "unsupported" and rewritten_plan.primary_intent != "unsupported":
        return True
    if base_plan.user_goal == "unknown" and rewritten_plan.user_goal != "unknown":
        return True
    if base_plan.clarification_needed and not rewritten_plan.clarification_needed:
        return True
    if rewritten_plan.user_goal != base_plan.user_goal and rewritten_plan.confidence > (base_plan.confidence + 0.05):
        return True
    if (
        rewritten_plan.primary_intent != base_plan.primary_intent
        and rewritten_plan.user_goal != "unknown"
        and rewritten_plan.normalized_message.strip().lower()
        != base_plan.normalized_message.strip().lower()
        and rewritten_plan.confidence >= (base_plan.confidence - 0.05)
    ):
        return True
    if (
        rewritten_plan.user_goal == base_plan.user_goal
        and rewritten_plan.analysis_mode == base_plan.analysis_mode
        and list(rewritten_plan.grouping) == list(base_plan.grouping)
        and (rewritten_metrics == base_metrics or rewritten_metrics.issuperset(base_metrics))
        and rewritten_plan.normalized_message.strip().lower()
        != base_plan.normalized_message.strip().lower()
        and rewritten_plan.confidence >= (base_plan.confidence - 0.05)
    ):
        return True
    return False


def _contains_any_phrase(text: str, phrases: set[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _extract_last_memory_context(session_messages: list[object]) -> dict[str, Any]:
    for row in reversed(session_messages):
        if str(getattr(row, "role", "")) != "assistant":
            continue
        metadata = getattr(row, "metadata_json", None) or {}
        memory_context = metadata.get("memory_context")
        if isinstance(memory_context, dict):
            return memory_context
    return {}


def _normalized_followup_text(text: str) -> str:
    lowered = " ".join(str(text or "").strip().lower().split())
    return re.sub(r"[^a-z0-9\s]", "", lowered).strip()


def _extract_requested_group_dimension(text: str) -> str | None:
    lowered = " ".join(str(text or "").strip().lower().split())
    dimension_aliases = {
        "program type": "program type",
        "age band": "age band",
        "branch": "branch",
        "branches": "branch",
        "semester": "semester",
        "sem": "semester",
        "year": "year",
        "years": "year",
        "gender": "gender",
        "region": "region",
        "regions": "region",
        "category": "category",
        "income": "income",
        "batch": "batch",
        "program": "program type",
        "age": "age band",
    }
    for alias, dimension in dimension_aliases.items():
        if alias in lowered and ("wise" in lowered or "group by" in lowered or "also" in lowered):
            return dimension
    return None


def _match_bucket_value_from_context(*, text: str, bucket_values: list[object]) -> str | None:
    lowered = " ".join(str(text or "").strip().lower().split())
    ordered_values = sorted(
        [str(raw_value or "").strip() for raw_value in bucket_values if str(raw_value or "").strip()],
        key=len,
        reverse=True,
    )
    for value in ordered_values:
        pattern = r"(?<![a-z0-9])" + re.escape(value.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, lowered):
            return value
    return None


def _try_local_semantic_assist(
    *,
    role: RoleName,
    message: str,
    base_plan: CopilotQueryPlan,
    session_messages: list[object],
) -> dict[str, Any] | None:
    lowered = " ".join(str(message or "").strip().lower().split())
    normalized_followup = _normalized_followup_text(message)
    last_context = _extract_last_memory_context(session_messages)

    if role == "student":
        if any(
            phrase in lowered
            for phrase in {
                "lms details",
                "my lms details",
                "lms activity",
                "my lms activity",
                "show my lms",
                "show my lms activity",
                "give me my lms",
                "give me my lms activity",
                "learning activity",
            }
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "show me my lms activity right now",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.9,
                "rationale": "Mapped a simple LMS wording to the grounded student LMS activity summary path.",
            }
        if any(
            phrase in lowered
            for phrase in {
                "erp details",
                "my erp details",
                "erp activity",
                "my erp activity",
                "show my erp",
                "show my erp details",
                "erp data",
                "my erp data",
            }
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "show me my erp details right now",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.89,
                "rationale": "Mapped a simple ERP wording to the grounded student ERP academic-performance summary path.",
            }
        if any(
            phrase in lowered
            for phrase in {
                "finance details",
                "my finance details",
                "financial details",
                "payment status",
                "fee status",
                "my finance status",
                "my fee status",
                "dues status",
                "my dues",
            }
        ) and not any(
            token in lowered
            for token in {
                "risk",
                "high risk",
                "high alert",
                "helping",
                "hurting",
                "affecting",
                "impact",
                "why",
            }
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "show me my finance details right now",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.89,
                "rationale": "Mapped a simple finance wording to the grounded student finance summary path.",
            }
        if any(
            phrase in lowered
            for phrase in {
                "assignment rate",
                "assignment submission rate",
                "submission rate",
                "assignment completion rate",
                "coursework submission rate",
            }
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "what is my assignment submission rate right now",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.9,
                "rationale": "Applied the shared default assumption that a simple assignment-rate question most likely means assignment submission rate.",
            }
        if any(
            phrase in lowered
            for phrase in {
                "how to increase my gpa",
                "how can i increase my gpa",
                "how to improve assignments",
                "how can i improve assignments",
                "how can i improve it",
                "what should i prioritize now",
                "step by step plan",
                "step by step recovery plan",
            }
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "show me my coursework priorities",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.87,
                "rationale": "Mapped coursework and GPA-improvement phrasing to the grounded student coursework-priority action path.",
            }
        if any(
            phrase in lowered
            for phrase in {
                "what is my gpa",
                "show my gpa",
                "current gpa",
                "my gpa",
                "cgpa",
                "current cgpa",
                "previous and current gpa",
                "grade point",
            }
        ) and not any(
            phrase in lowered
            for phrase in {
                "why is my gpa",
                "why gpa",
                "how to increase my gpa",
                "how can i increase my gpa",
                "low even with good attendance",
            }
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "show me my gpa and academic performance right now",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.89,
                "rationale": "Mapped GPA wording to the grounded student ERP academic-performance path with GPA context.",
            }
        if any(
            phrase in lowered
            for phrase in {
                "how many days did i login",
                "how many days i login",
                "days did i login",
                "login days",
                "days active on lms",
                "how often did i login",
            }
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "show me my lms activity and active login days right now",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.88,
                "rationale": "Mapped login-frequency wording to the grounded student LMS activity path.",
            }
        if any(
            phrase in lowered
            for phrase in {
                "am i doing good",
                "how am i performing",
                "is my performance okay",
                "am i in trouble",
                "should i be worried",
                "how bad is my situation",
                "am i improving or getting worse",
                "am i in danger",
                "how serious is my situation",
                "should i panic",
                "am i going to fail",
                "is it too late for me",
                "can i still recover",
                "tell me honestly am i safe",
                "should i worry about my future",
                "is my situation normal",
                "am i worse than others",
            }
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "am i safe or should i worry",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.88,
                "rationale": "Mapped broad student wellbeing/performance phrasing to the grounded student safety explanation path.",
            }
        if any(
            phrase in lowered
            for phrase in {
                "how to increase my gpa",
                "improve my gpa",
                "what should i do",
                "best way to recover",
                "give me steps to improve",
                "how to improve assignments",
                "what should i do right now",
            }
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "show me my overall recovery priorities",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.85,
                "rationale": "Mapped broad student action phrasing to the grounded student recovery-priority path.",
            }
        if any(
            phrase in lowered
            for phrase in {
                "how are assignments affecting my risk",
                "is finance affecting my performance",
                "why is my gpa low even with good attendance",
                "my lms activity is high but performance is low why",
                "what caused this",
                "what caused it",
                "how is my attendance and assignments together",
                "compare my lms and gpa",
                "which is affecting me more assignments or attendance",
                "what is my biggest weakness",
                "what caused my risk",
                "why is my performance low",
                "what is affecting my results",
                "why is my gpa dropping",
                "what is going wrong",
                "does attendance really matter",
                "is lms important",
                "what if i stop studying",
                "what happens if i don't improve",
                "what happens if i dont improve",
                "what happens if i ignore this",
                "will i fail",
                "what is worst case",
                "how long will it take",
                "how much time i have",
                "how fast can i improve",
            }
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "what exactly is hurting me most right now",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.86,
                "rationale": "Mapped broad student explanation and mixed-signal wording to the grounded weakest-driver explanation path.",
            }
        pending_follow_up = str(last_context.get("pending_student_follow_up") or "").strip().lower()
        if normalized_followup in {"yes", "yeah", "yep", "ok", "okay", "continue", "proceed"}:
            remembered_rewrite = str(last_context.get("default_follow_up_rewrite") or "").strip()
            if str(last_context.get("intent") or "").strip().lower() == "planner_clarification" and remembered_rewrite:
                return {
                    "action": "rewrite",
                    "rewritten_message": remembered_rewrite,
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.84,
                    "rationale": "Used the remembered default follow-up rewrite so a vague student reply continues the same topic instead of reopening clarification.",
                }
        if normalized_followup in {
            "yes",
            "yeah",
            "yep",
            "ok",
            "okay",
            "ok tell",
            "tell",
            "tell me",
            "continue",
            "go on",
            "then",
            "proceed",
            "so what",
            "what does that mean",
            "am i okay then",
            "sure",
            "alright",
            "all right",
            "more",
        }:
            if pending_follow_up == "attendance_territory":
                return {
                    "action": "rewrite",
                    "rewritten_message": "do i have i grade risk or r grade risk and am i eligible for end sem",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.88,
                    "rationale": "Continued the student attendance-territory follow-up thread using local conversation memory.",
                }
            if pending_follow_up == "lms_risk_explanation":
                return {
                    "action": "rewrite",
                    "rewritten_message": "how is my current lms activity affecting my risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.88,
                    "rationale": "Continued the student LMS-to-risk follow-up thread using local conversation memory.",
                }
            if pending_follow_up == "finance_risk_explanation":
                return {
                    "action": "rewrite",
                    "rewritten_message": "how is my current finance posture affecting my risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.88,
                    "rationale": "Continued the student finance-to-risk follow-up thread using local conversation memory.",
                }
            if pending_follow_up == "coursework_risk_explanation":
                return {
                    "action": "rewrite",
                    "rewritten_message": "how is my current coursework pattern affecting my risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.88,
                    "rationale": "Continued the student coursework-to-risk follow-up thread using local conversation memory.",
                }
            if pending_follow_up == "student_action_list":
                return {
                    "action": "rewrite",
                    "rewritten_message": "what should i do first",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.87,
                    "rationale": "Continued the student action-list follow-up thread using local conversation memory.",
                }
            if pending_follow_up == "weekly_focus_breakdown":
                return {
                    "action": "rewrite",
                    "rewritten_message": "turn this into a simple day by day plan for the week",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.86,
                    "rationale": "Continued the weekly-plan breakdown thread by moving into an actionable day-by-day plan using local conversation memory.",
                }
            if pending_follow_up == "day_by_day_plan":
                return {
                    "action": "rewrite",
                    "rewritten_message": "turn this into a simple day by day plan for the week",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.87,
                    "rationale": "Continued the day-by-day weekly planning thread using local conversation memory.",
                }
            if pending_follow_up == "risk_label_reduction_explanation":
                return {
                    "action": "rewrite",
                    "rewritten_message": "how can i remove the high label risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.87,
                    "rationale": "Continued the student recovery-impact follow-up thread using local conversation memory.",
                }
        last_intent = str(last_context.get("intent") or "").strip().lower()
        if any(
            phrase in lowered
            for phrase in {
                "overall recovery priorities",
                "recovery priorities",
                "proceed with overall recovery",
                "proceed with recovery",
                "continue with recovery",
            }
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "show me my overall recovery priorities",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.86,
                "rationale": "Mapped a short student recovery continuation to a grounded recovery-priority request.",
            }
        if any(
            phrase in lowered
            for phrase in {
                "attendance priorities",
                "proceed with attendance",
                "continue with attendance",
                "attendance focus",
            }
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "show me my attendance priorities",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.85,
                "rationale": "Mapped a short student continuation to a grounded attendance-priority request.",
            }
        if any(
            phrase in lowered
            for phrase in {
                "coursework priorities",
                "proceed with coursework",
                "continue with coursework",
                "coursework focus",
            }
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "show me my coursework priorities",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.85,
                "rationale": "Mapped a short student continuation to a grounded coursework-priority request.",
            }
        if normalized_followup in {
            "and why exactly",
            "why exactly",
            "what do you mean",
            "what do you mean by that",
            "prediction or attendance",
            "prediction or attendance risk",
        }:
            if last_intent == "risk_layer_difference":
                return {
                    "action": "rewrite",
                    "rewritten_message": "what is the difference between prediction risk and attendance risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.86,
                    "rationale": "Continued the student risk-layer explanation using local conversation memory.",
                }
            if last_intent in {"student_self_risk", "student_self_attendance", "student_self_subject_risk"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "am i safe or should i worry",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.84,
                    "rationale": "Converted a short student why-follow-up into the grounded student safety explanation path using local conversation memory.",
                }
        if last_intent in {"student_self_risk", "student_self_subject_risk", "student_self_plan", "student_weekly_focus"}:
            if normalized_followup in {"which is most important"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "show me my overall recovery priorities",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.86,
                    "rationale": "Mapped a short student prioritization follow-up to the grounded recovery-priority path.",
                }
            if normalized_followup in {
                "what caused this",
                "what caused it",
                "why",
                "explain more",
                "what is main problem",
                "what is going wrong",
            }:
                return {
                    "action": "rewrite",
                    "rewritten_message": "what is causing my current risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.86,
                    "rationale": "Mapped a short student cause follow-up to the grounded current-risk explanation path.",
                }
            if normalized_followup in {
                "can i fix it",
                "how to fix that",
                "what next",
                "what else should i do",
                "what should i do right now",
            }:
                return {
                    "action": "rewrite",
                    "rewritten_message": "show me my overall recovery priorities",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.86,
                    "rationale": "Mapped a short student action follow-up to the grounded recovery-priority path.",
                }
            if normalized_followup in {
                "how long will it take",
                "how much time i have",
                "how fast can i improve",
                "can i recover fully",
                "is that enough",
                "what is worst case",
                "what if i don't improve",
                "what if i dont improve",
                "what happens if i don't improve",
                "what happens if i dont improve",
                "what happens if i ignore this",
                "will i fail",
            }:
                return {
                    "action": "rewrite",
                    "rewritten_message": "what happens if i do not improve my current risk drivers",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.85,
                    "rationale": "Mapped a short student consequence follow-up to the grounded current-risk consequence path.",
                }
        if last_intent in {"student_recovery_focus", "student_weekly_focus", "student_weekly_focus_breakdown", "student_day_by_day_plan"}:
            if normalized_followup in {"why", "explain more"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "what is causing my current risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.84,
                    "rationale": "Mapped a short student plan follow-up back to the grounded current-risk explanation path.",
                }
            if normalized_followup in {"is that enough"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "would only fixing assignments be enough to reduce my current risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.84,
                    "rationale": "Mapped a short student sufficiency follow-up to a grounded risk-reduction explanation path.",
                }
            if str(last_context.get("focus") or "").strip().lower() == "coursework" and normalized_followup in {
                "what if i miss next one",
                "if i miss next one",
                "will my risk increase",
                "will risk increase",
                "by how much",
                "what should i prioritize now",
            }:
                rewritten = {
                    "what if i miss next one": "what happens if i miss my next assignment submission",
                    "if i miss next one": "what happens if i miss my next assignment submission",
                    "will my risk increase": "will missing coursework increase my current risk",
                    "will risk increase": "will missing coursework increase my current risk",
                    "by how much": "how much could missing coursework raise my current risk",
                    "what should i prioritize now": "how to improve assignments",
                }[normalized_followup]
                return {
                    "action": "rewrite",
                    "rewritten_message": rewritten,
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.86,
                    "rationale": "Continued the coursework-focused action thread with a grounded coursework consequence or prioritization follow-up.",
                }
        if pending_follow_up == "assignment_sufficiency_follow_up":
            if normalized_followup in {"is that enough", "and then", "what else", "what else then"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "what else is still driving my risk besides assignments",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.86,
                    "rationale": "Continued the assignment-sufficiency thread by asking for the remaining grounded risk drivers beyond assignments.",
                }
        if pending_follow_up == "coursework_quality_evaluation":
            if normalized_followup in {"is it good or bad", "is that good or bad", "good or bad"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "is my current assignment submission rate helping or hurting my current risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.87,
                    "rationale": "Continued the coursework-evaluation thread by converting a vague quality judgement follow-up into a grounded coursework-versus-risk explanation.",
                }
        if pending_follow_up in {"coursework_quality_evaluation", "coursework_risk_explanation"}:
            if normalized_followup in {"what if i miss next one", "if i miss next one"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "what happens if i miss my next assignment submission",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.87,
                    "rationale": "Continued the coursework thread by turning a vague missed-assignment follow-up into a grounded coursework-consequence question.",
                }
            if normalized_followup in {"will my risk increase", "will risk increase"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "will missing coursework increase my current risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.86,
                    "rationale": "Continued the coursework thread by turning a vague risk-increase follow-up into a grounded coursework-versus-risk consequence question.",
                }
            if normalized_followup in {"by how much"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "how much could missing coursework raise my current risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.84,
                    "rationale": "Continued the coursework consequence thread by asking for a grounded magnitude explanation instead of a vague quantity follow-up.",
                }
            if normalized_followup in {"what should i prioritize now"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "how to improve assignments",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.86,
                    "rationale": "Continued the coursework thread by mapping a priority follow-up to grounded assignment improvement advice.",
                }
            if normalized_followup in {"give me a step by step plan", "step by step plan"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "give me a full recovery plan",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.83,
                    "rationale": "Continued the coursework thread by mapping a step-by-step request into a grounded full recovery plan.",
                }
        if pending_follow_up == "coursework_consequence_follow_up":
            if normalized_followup in {"will my risk increase", "will risk increase"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "will missing coursework increase my current risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.87,
                    "rationale": "Continued the coursework consequence thread by asking whether a missed submission would increase current risk.",
                }
            if normalized_followup in {"by how much"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "how much could missing coursework raise my current risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.85,
                    "rationale": "Continued the coursework consequence thread by asking for the grounded magnitude of a missed-submission impact.",
                }
            if normalized_followup in {"what should i prioritize now"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "how to improve assignments",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.86,
                    "rationale": "Continued the coursework consequence thread by returning to grounded assignment improvement priorities.",
                }
            if normalized_followup in {"give me a step by step plan", "step by step plan"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "give me a full recovery plan",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.83,
                    "rationale": "Continued the coursework consequence thread by turning the follow-up into a grounded full recovery plan request.",
                }

    if role in {"admin", "counsellor"}:
        pending_role_follow_up = str(last_context.get("pending_role_follow_up") or "").strip().lower()
        last_intent = str(last_context.get("intent") or "").strip().lower()
        last_kind = str(last_context.get("kind") or "").strip().lower()
        generic_role_followups = {
            "yes",
            "yeah",
            "yep",
            "ok",
            "okay",
            "sure",
            "alright",
            "all right",
            "continue",
            "go on",
            "then",
            "proceed",
            "what next",
            "next steps",
            "what now",
            "and then",
        }
        if normalized_followup in generic_role_followups and (
            pending_role_follow_up == "operational_actions"
            or last_intent
            in {
                "grouped_risk_breakdown",
                "attention_analysis_summary",
                "diagnostic_comparison_summary",
                "comparison_summary",
                "counsellor_priority_follow_up",
                "admin_priority_queue_summary",
                "counsellor_active_burden_monitoring",
                "counsellor_branch_pressure",
                "counsellor_semester_pressure",
                "counsellor_i_grade_summary",
                "counsellor_r_grade_summary",
                "admin_branch_attention_summary",
                "admin_semester_attention_summary",
                "admin_i_grade_summary",
                "admin_r_grade_summary",
                "admin_attendance_pressure_summary",
            }
        ):
            if role == "counsellor":
                rewritten = "what should i do first for my students"
            else:
                rewritten = (
                    "show a branch-specific admin action list"
                    if last_intent == "admin_operational_actions"
                    else "what should we do first institution wide"
                )
            return {
                "action": "rewrite",
                "rewritten_message": rewritten,
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.87,
                "rationale": "Continued a counsellor/admin operational follow-up into the grounded role action layer using local conversation memory.",
            }
        if last_kind == "import_coverage" and normalized_followup in {
            "top 3",
            "top 5",
            "top 10",
            "top three",
            "top five",
            "top ten",
            "what about top 3",
            "what about top 5",
            "what about top 10",
            "what about top three",
            "what about top five",
            "what about top ten",
        }:
            return {
                "action": "rewrite",
                "rewritten_message": "show my assigned students" if role == "counsellor" else "how many students are high risk",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.85,
                "rationale": "Preserved a top-N subset follow-up so the grounded memory-follow-up layer can answer it locally instead of reopening clarification.",
            }
        if any(
            phrase in lowered
            for phrase in {
                "what should we do first",
                "what do we do first",
                "what should admin do first",
                "what should i do first",
                "what do i do first",
                "what should i do as counsellor",
                "what should we focus on first",
                "what should i focus on first",
                "action list",
                "action plan",
                "operational priorities",
                "operational actions",
                "how do we reduce this",
                "how can we reduce this",
                "how should we reduce this",
                "how should we respond",
                "how should i respond",
                "what should we do about this",
                "what should i do about this",
                "what should i do for my students",
                "what should i do for high risk students",
                "what action should i take for high risk students",
            }
        ):
            rewritten = (
                "what should i do first for my students"
                if role == "counsellor"
                else "what should we do first institution wide"
            )
            return {
                "action": "rewrite",
                "rewritten_message": rewritten,
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.86,
                "rationale": "Mapped a fuzzy counsellor/admin action request to the grounded operational advisory path without using the external provider.",
            }

    if normalized_followup in {
        "prediction or attendance",
        "prediction or attendance risk",
        "which one do you mean",
        "what do you mean",
        "what do you mean by that",
    }:
        last_intent = str(last_context.get("intent") or "").strip().lower()
        if last_intent in {"risk_layer_difference", "grouped_risk_breakdown", "admin_high_risk_semester_year_breakdown"}:
            return {
                "action": "rewrite",
                "rewritten_message": "what is the difference between prediction risk and attendance risk",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.85,
                "rationale": "Continued a prior risk-layer or grouped-risk explanation using local conversation memory.",
            }

    if normalized_followup in {"and why exactly", "why exactly", "what do you mean by that"}:
        last_kind = str(last_context.get("kind") or "").strip().lower()
        last_intent = str(last_context.get("intent") or "").strip().lower()
        remembered_student_id = last_context.get("student_id")
        if last_kind == "student_drilldown" and remembered_student_id is not None:
            return {
                "action": "rewrite",
                "rewritten_message": f"show details for student {int(remembered_student_id)}",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.83,
                "rationale": "Reused the previous student drilldown context for a short why-follow-up using local conversation memory.",
            }
        if last_intent == "risk_layer_difference":
            return {
                "action": "rewrite",
                "rewritten_message": "what is the difference between prediction risk and attendance risk",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.84,
                "rationale": "Continued the prior risk-layer explanation using local conversation memory.",
            }

    requested_dimension = _extract_requested_group_dimension(message)
    if "also" in lowered and requested_dimension is not None:
        last_kind = str(last_context.get("kind") or "").strip().lower()
        last_intent = str(last_context.get("intent") or "").strip().lower()
        if last_kind in {"admin_academic", "import_coverage"}:
            if role == "admin" and "high_risk" in last_intent:
                return {
                    "action": "rewrite",
                    "rewritten_message": f"show prediction high risk and attendance risk {requested_dimension} wise",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.85,
                    "rationale": "Extended the previous grouped high-risk analysis into another requested dimension using local conversation memory.",
                }
            return {
                "action": "rewrite",
                "rewritten_message": f"show attendance risk {requested_dimension} wise",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.84,
                "rationale": "Extended the previous grouped attendance analysis into another requested dimension using local conversation memory.",
            }

    last_kind = str(last_context.get("kind") or "").strip().lower()
    last_grouped_by = str(last_context.get("grouped_by") or "").strip().lower()
    bucket_values = list(last_context.get("bucket_values") or [])
    if last_kind in {"import_coverage", "admin_academic"} and last_grouped_by:
        if normalized_followup in {
            "which is worse",
            "which is worse then",
            "worse then",
            "worse now",
            "which one is worse",
        }:
            return {
                "action": "rewrite",
                "rewritten_message": f"which {last_grouped_by} is worse and why",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.85,
                "rationale": "Continued the previous grouped comparison into a diagnostic worse-and-why query using local conversation memory.",
            }
        if normalized_followup in {
            "only the highrisk ones",
            "only the high risk ones",
            "what about only the highrisk ones",
            "what about only the high risk ones",
            "just the highrisk ones",
            "just the high risk ones",
        }:
            return {
                "action": "rewrite",
                "rewritten_message": "only the high-risk ones",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.84,
                "rationale": "Normalized a grouped high-risk subset follow-up using local conversation memory.",
            }
        matched_bucket = _match_bucket_value_from_context(text=message, bucket_values=bucket_values)
        if matched_bucket is not None and _contains_any_phrase(
            lowered,
            {"what about only", "only ", "just ", "what about ", "focus on ", "show only "},
        ):
            return {
                "action": "rewrite",
                "rewritten_message": f"only {matched_bucket}",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.83,
                "rationale": "Normalized a bucket-specific grouped follow-up using local conversation memory.",
            }

    if role in {"admin", "counsellor"}:
        if _contains_any_phrase(
            lowered,
            {
                "heaviest strain",
                "under the heaviest strain",
                "heaviest pressure",
                "trouble worst",
                "worst trouble",
                "bleeding most",
                "needs attention most",
            },
        ) and any(
            token in lowered for token in {"why", "right now", "currently", "today"}
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "which branch needs attention first and why",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.89,
                "rationale": "Mapped strain-style phrasing to grounded attention analysis without using the external provider.",
            }
        if (
            _contains_any_phrase(
                lowered,
                {
                    "support gap",
                    "gap worst",
                    "coverage slipping",
                    "coverage gap",
                    "follow-up gap",
                    "support coverage slipping",
                },
            )
            and any(token in lowered for token in {"region", "regions", "urban", "rural"})
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "which region has the highest warning-to-intervention gap",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.9,
                "rationale": "Mapped support-gap phrasing to grounded warning/intervention gap comparison without using the external provider.",
            }
        if _contains_any_phrase(
            lowered,
            {
                "hotspot",
                "pain point",
                "hurting us the most",
                "causing the most pain",
                "most attendance pain",
                "most attendance pressure",
            },
        ) and "attendance" in lowered:
            return {
                "action": "rewrite",
                "rewritten_message": "which subjects are causing the most attendance issues",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.88,
                "rationale": "Mapped hotspot-style attendance phrasing to a grounded subject-pressure query.",
            }
        if role == "counsellor":
            if lowered.strip() in {
                "students",
                "students?",
                "my students",
                "assigned students",
                "my assigned students",
                "show my students",
                "show my assigned students",
            }:
                return {
                    "action": "rewrite",
                    "rewritten_message": "show my assigned students",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.88,
                    "rationale": "Mapped a simple counsellor student-list request to the grounded assigned-students view.",
                }
            if re.search(r"\bstudent(?:\s+with)?\s+id\s*\d+\b", lowered) and "attendance" in lowered:
                return {
                    "action": "rewrite",
                    "rewritten_message": message.strip(),
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.9,
                    "rationale": "Kept a direct counsellor student-attendance drilldown on the deterministic local path so it does not wait on external semantic planning.",
                }
            if any(
                phrase in lowered
                for phrase in {
                    "good attendance but high risk",
                    "high risk but good attendance",
                    "good attendance and high risk",
                }
            ):
                return {
                    "action": "rewrite",
                    "rewritten_message": "which students have good attendance but high risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.89,
                    "rationale": "Mapped a counsellor contradiction query to the grounded good-attendance/high-risk cohort path.",
                }
            if any(
                phrase in lowered
                for phrase in {
                    "low assignments",
                    "low assignment",
                    "poor assignments",
                    "low submission",
                    "low submissions",
                }
            ) and any(
                marker in lowered
                for marker in {
                    "students",
                    "show",
                    "give me",
                    "only",
                    "which",
                }
            ):
                return {
                    "action": "rewrite",
                    "rewritten_message": "which students have low assignment submission rate",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.88,
                    "rationale": "Mapped a counsellor low-assignment filter to the grounded low-submission cohort path.",
                }
            if "weekly plan" in lowered or (
                "weekly" in lowered and any(token in lowered for token in {"plan", "follow up", "follow-up", "cadence"})
            ):
                return {
                    "action": "rewrite",
                    "rewritten_message": "what weekly plan should i follow as counsellor",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.87,
                    "rationale": "Mapped counsellor weekly-planning phrasing to the grounded operational weekly-plan path.",
                }
            if "i grade" in lowered and "r grade" in lowered and any(
                token in lowered
                for token in {"how many", "count", "students", "there"}
            ):
                return {
                    "action": "rewrite",
                    "rewritten_message": "how many i grade students and how many r grade students are in my scope",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.88,
                    "rationale": "Mapped counsellor I-grade/R-grade counting phrasing to the grounded scoped burden summary path.",
                }
            if _contains_any_phrase(
                lowered,
                {
                    "watch closest",
                    "watch most closely",
                    "who needs watching",
                    "keep the closest eye on",
                    "keep an eye on",
                    "who should i watch",
                    "who should i be watching",
                },
            ) and any(token in lowered for token in {"right now", "this week", "currently", "first"}):
                return {
                    "action": "rewrite",
                    "rewritten_message": "which students need attention first this week",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.87,
                    "rationale": "Mapped watch-closest phrasing to the grounded counsellor priority queue.",
                }
            if _contains_any_phrase(
                lowered,
                {
                    "doing fine now",
                    "look okay now",
                    "seem okay now",
                    "seem fine now",
                    "still needs watching",
                    "still need watching",
                    "still need monitoring",
                    "keep monitoring",
                },
            ) and any(token in lowered for token in {"weekly", "watch", "monitoring", "monitor"}):
                return {
                    "action": "rewrite",
                    "rewritten_message": "which of my students need weekly monitoring because of unresolved r grade burden",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.86,
                    "rationale": "Mapped fuzzy unresolved-burden monitoring phrasing to the grounded weekly burden path.",
                }
        if role == "admin":
            if lowered.strip() in {"stats", "stats?", "institution stats", "current stats"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "how many students are high risk",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.87,
                    "rationale": "Mapped a vague admin stats request to the grounded institutional risk snapshot.",
                }
            if lowered.strip() in {"trend", "trend?", "current trend", "risk trend"}:
                return {
                    "action": "rewrite",
                    "rewritten_message": "how many students just entered risk in the last 30 days",
                    "clarification_question": "",
                    "refusal_reason": "",
                    "confidence": 0.84,
                    "rationale": "Mapped a vague admin trend request to the grounded recent-entry risk trend snapshot.",
                }

    if role == "student":
        if (
            any(token in lowered for token in {"attendance", "safe", "okay"})
            and _contains_any_phrase(
                lowered,
                {
                    "high alert",
                    "high risk",
                    "put into high",
                    "red flagged",
                    "flagged high",
                    "why am i flagged",
                },
            )
            and any(token in lowered for token in {"why", "but why", "how come", "then why"})
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "am i safe or should i worry",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.86,
                "rationale": "Mapped safe-attendance but high-alert phrasing to the grounded student safety explanation path.",
            }
        if _contains_any_phrase(
            lowered,
            {
                "what's hurting me most",
                "what is hurting me most",
                "what's dragging me down",
                "what is dragging me down",
                "what's going wrong with me",
            },
        ) and any(
            token in lowered for token in {"what should i do first", "what do i do first", "fix first", "do first"}
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "what exactly is hurting me most and what should i do first",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.85,
                "rationale": "Normalized a fuzzy student recovery question to a grounded weakest-subject/action path.",
            }
        if _contains_any_phrase(
            lowered,
            {
                "recover from high alert",
                "recover from high risk",
                "remove the high label",
                "remove high label",
                "remove the high risk label",
                "remove the high alert label",
                "reduce my risk",
                "lower my risk",
                "come out of high alert",
                "get out of high alert",
            },
        ):
            return {
                "action": "rewrite",
                "rewritten_message": "show me my overall recovery priorities",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.88,
                "rationale": "Mapped fuzzy student recovery phrasing to a grounded overall-recovery action request.",
            }
        if _contains_any_phrase(
            lowered,
            {
                "old uncleared grade",
                "older sems",
                "older semesters",
                "old grade baggage",
                "old uncleared stuff",
                "still carrying any old grade",
            },
        ) and any(token in lowered for token in {"uncleared", "old", "older", "still", "carry", "carrying"}):
            return {
                "action": "rewrite",
                "rewritten_message": "do i still have any uncleared grade issue from older sems",
                "clarification_question": "",
                "refusal_reason": "",
                "confidence": 0.84,
                "rationale": "Normalized fuzzy older-semester burden phrasing to the grounded uncleared-grade path.",
            }

    mentions_branch_dimension = any(token in lowered for token in {"branch", "cse", "ece", "department"})
    mentions_region_dimension = any(token in lowered for token in {"region", "urban", "rural"})
    if "compare" in lowered and mentions_branch_dimension and mentions_region_dimension:
        return {
            "action": "clarify",
            "rewritten_message": "",
            "clarification_question": "Do you want me to compare by branch or by region first?",
            "refusal_reason": "",
            "confidence": 0.84,
            "rationale": "Detected competing comparison dimensions using local semantic fallback.",
        }

    return None


def _semantic_cache_context_fragment(session_messages: list[object]) -> dict[str, Any]:
    last_context = _extract_last_memory_context(session_messages)
    return {
        "kind": str(last_context.get("kind") or "").strip().lower(),
        "intent": str(last_context.get("intent") or "").strip().lower(),
        "grouped_by": str(last_context.get("grouped_by") or "").strip().lower(),
        "pending_student_follow_up": str(last_context.get("pending_student_follow_up") or "").strip().lower(),
        "pending_role_follow_up": str(last_context.get("pending_role_follow_up") or "").strip().lower(),
    }


def _build_semantic_cache_key(*, role: RoleName, message: str, session_messages: list[object]) -> str:
    normalized = " ".join(str(message or "").strip().lower().split())
    context_fragment = json.dumps(_semantic_cache_context_fragment(session_messages), sort_keys=True, ensure_ascii=True)
    payload = f"{CB19_PHASE_LABEL}|{CB19_CACHE_VERSION}|{DEFAULT_GEMINI_MODEL}|{role}|{normalized}|{context_fragment}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_semantic_cache() -> dict[str, Any]:
    try:
        if not CB19_CACHE_PATH.exists():
            return {}
        parsed = json.loads(CB19_CACHE_PATH.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _save_semantic_cache(cache: dict[str, Any]) -> None:
    try:
        CB19_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CB19_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=True, indent=2), encoding="utf-8")
    except Exception:
        return


def _get_cached_semantic_hint(cache_key: str) -> dict[str, Any] | None:
    cache = _load_semantic_cache()
    cached = cache.get(cache_key)
    return cached if isinstance(cached, dict) else None


def _store_cached_semantic_hint(cache_key: str, semantic_hint: dict[str, Any]) -> None:
    if not CB19_CACHE_ENABLED:
        return
    cache = _load_semantic_cache()
    cache[cache_key] = dict(semantic_hint)
    if len(cache) > CB19_CACHE_MAX_ENTRIES:
        keys = list(cache.keys())
        for key in keys[: len(cache) - CB19_CACHE_MAX_ENTRIES]:
            cache.pop(key, None)
    _save_semantic_cache(cache)


def _apply_semantic_hint(
    *,
    base_plan: CopilotQueryPlan,
    semantic_hint: dict[str, Any],
    message: str,
    role: RoleName,
    session_messages: list[object],
    profiles: list[object] | None,
    metadata: dict[str, Any],
    cache_key: str,
    cached: bool,
) -> tuple[CopilotQueryPlan, dict[str, Any]]:
    action = str(semantic_hint.get("action") or "keep").strip().lower()
    rewritten_message = str(semantic_hint.get("rewritten_message") or "").strip()
    clarification_question = str(semantic_hint.get("clarification_question") or "").strip()
    refusal_reason = str(semantic_hint.get("refusal_reason") or "").strip()
    confidence = _safe_confidence(semantic_hint.get("confidence"))
    rationale = str(semantic_hint.get("rationale") or "").strip()
    source_provider = str(semantic_hint.get("_source_provider") or "").strip()

    if source_provider:
        metadata["provider"] = source_provider
        metadata["model"] = None if source_provider == "local_fallback" else DEFAULT_GEMINI_MODEL

    metadata["confidence"] = confidence
    metadata["rationale"] = rationale or None
    metadata["rewritten_message"] = rewritten_message or None
    metadata["used"] = True
    if cached:
        metadata["status"] = "cache_hit"

    if not cached:
        _store_cached_semantic_hint(cache_key, semantic_hint)

    if action == "refuse" and refusal_reason:
        plan = _clone_plan(base_plan)
        plan.user_goal = "refusal"
        plan.refusal_reason = refusal_reason
        plan.confidence = max(plan.confidence, confidence)
        if rationale:
            plan.notes.append(f"CB19 semantic planner refusal: {rationale}")
        if not cached:
            metadata["status"] = "refusal"
        return plan, metadata

    if action == "clarify" and clarification_question:
        plan = _clone_plan(base_plan)
        plan.clarification_needed = True
        plan.clarification_question = clarification_question
        plan.confidence = max(plan.confidence, confidence)
        if rationale:
            plan.notes.append(f"CB19 semantic planner clarification: {rationale}")
        if not cached:
            metadata["status"] = "clarification"
        return plan, metadata

    if action == "rewrite" and rewritten_message and rewritten_message.lower() != message.strip().lower():
        rewritten_plan = plan_copilot_query(
            role=role,
            message=rewritten_message,
            session_messages=session_messages,
            profiles=profiles,
        )
        if _should_adopt_rewritten_plan(base_plan=base_plan, rewritten_plan=rewritten_plan):
            adopted_plan = _clone_plan(rewritten_plan)
            adopted_plan.original_message = message
            adopted_plan.normalized_message = rewritten_message
            adopted_plan.confidence = max(adopted_plan.confidence, confidence)
            if rationale:
                adopted_plan.notes.append(f"CB19 semantic planner rewrite: {rationale}")
            if not cached:
                metadata["status"] = "rewritten"
            return adopted_plan, metadata
        metadata["status"] = "rewrite_rejected_from_cache" if cached else "rewrite_rejected"
        return base_plan, metadata

    if not cached:
        metadata["status"] = "kept"
    return base_plan, metadata
