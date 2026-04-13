from __future__ import annotations

import os
from copy import deepcopy
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

    action = str(semantic_hint.get("action") or "keep").strip().lower()
    rewritten_message = str(semantic_hint.get("rewritten_message") or "").strip()
    clarification_question = str(semantic_hint.get("clarification_question") or "").strip()
    refusal_reason = str(semantic_hint.get("refusal_reason") or "").strip()
    confidence = _safe_confidence(semantic_hint.get("confidence"))
    rationale = str(semantic_hint.get("rationale") or "").strip()

    metadata["confidence"] = confidence
    metadata["rationale"] = rationale or None
    metadata["rewritten_message"] = rewritten_message or None

    if action == "refuse" and refusal_reason:
        plan = _clone_plan(base_plan)
        plan.user_goal = "refusal"
        plan.refusal_reason = refusal_reason
        plan.confidence = max(plan.confidence, confidence)
        if rationale:
            plan.notes.append(f"CB19 semantic planner refusal: {rationale}")
        metadata["used"] = True
        metadata["status"] = "refusal"
        return plan, metadata

    if action == "clarify" and clarification_question:
        plan = _clone_plan(base_plan)
        plan.clarification_needed = True
        plan.clarification_question = clarification_question
        plan.confidence = max(plan.confidence, confidence)
        if rationale:
            plan.notes.append(f"CB19 semantic planner clarification: {rationale}")
        metadata["used"] = True
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
            metadata["used"] = True
            metadata["status"] = "rewritten"
            return adopted_plan, metadata
        metadata["status"] = "rewrite_rejected"
        return base_plan, metadata

    metadata["status"] = "kept"
    return base_plan, metadata


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
    if _looks_like_legacy_grouped_or_subset_request(
        lowered=lowered,
        session_messages=session_messages,
    ):
        return False

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
    }
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
