from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from src.api.auth import RoleName
from src.api.copilot_intents import detect_copilot_intent
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_runtime import COPILOT_SYSTEM_PROMPT_VERSION

COPILOT_PLANNER_VERSION = COPILOT_SYSTEM_PROMPT_VERSION


@dataclass
class CopilotQueryPlan:
    version: str = COPILOT_PLANNER_VERSION
    role: str = ""
    original_message: str = ""
    normalized_message: str = ""
    primary_intent: str = "unsupported"
    user_goal: str = "unknown"
    filters: dict[str, Any] = field(default_factory=dict)
    grouping: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    comparison: dict[str, Any] = field(default_factory=dict)
    time_window_days: int | None = None
    follow_up_action: str | None = None
    analysis_mode: str | None = None
    orchestration_steps: list[str] = field(default_factory=list)
    clarification_needed: bool = False
    clarification_question: str | None = None
    refusal_reason: str | None = None
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan_copilot_query(
    *,
    role: RoleName,
    message: str,
    session_messages: list[object],
    profiles: list[object] | None = None,
) -> CopilotQueryPlan:
    lowered = str(message or "").strip().lower()
    memory = resolve_copilot_memory_context(message=message, session_messages=session_messages)
    detected_intent = detect_copilot_intent(role=role, message=message)
    profile_list = profiles or []

    plan = CopilotQueryPlan(
        role=role,
        original_message=message,
        normalized_message=message,
        primary_intent=detected_intent,
        confidence=0.55,
        filters=_extract_filters(lowered=lowered, profiles=profile_list),
        time_window_days=memory.get("window_days") or _parse_time_window_days(lowered),
        follow_up_action="follow_up" if memory.get("is_follow_up") else None,
    )

    if _is_sensitive_request(lowered):
        plan.refusal_reason = "sensitive_request"
        plan.user_goal = "refusal"
        plan.confidence = 0.99
        return plan

    if role == "admin":
        _plan_admin_query(plan=plan, lowered=lowered, profiles=profile_list, memory=memory)
    elif role == "counsellor":
        _plan_counsellor_query(plan=plan, lowered=lowered)
    else:
        _plan_student_query(plan=plan, lowered=lowered)

    return plan


def _plan_admin_query(*, plan: CopilotQueryPlan, lowered: str, profiles: list[object], memory: dict[str, Any]) -> None:
    attention_dimensions = _detect_compare_dimensions(lowered=lowered, profiles=profiles)
    attention_analysis_context = bool(attention_dimensions) or any(
        token in lowered for token in {"compare", " versus ", " vs ", " vs. "}
    )

    if _looks_like_attention_analysis_request(lowered) and attention_analysis_context:
        mentioned_dimensions = attention_dimensions
        compare_dimension = mentioned_dimensions[0] if mentioned_dimensions else None
        if len(mentioned_dimensions) > 1:
            plan.user_goal = "attention_analysis"
            plan.analysis_mode = "attention_ranking"
            plan.clarification_needed = True
            plan.clarification_question = (
                f"I detected more than one analysis dimension: {', '.join(mentioned_dimensions)}. "
                "Please choose one dimension at a time so I can rank the riskiest retention bucket cleanly."
            )
            plan.confidence = 0.48
            plan.notes.append("Planner detected a multi-dimension attention-analysis request that needs clarification.")
            return
        if compare_dimension is None:
            plan.user_goal = "attention_analysis"
            plan.analysis_mode = "attention_ranking"
            plan.clarification_needed = True
            plan.clarification_question = (
                "Which retention dimension should I rank for attention: branch, region, category, income, or outcome status?"
            )
            plan.confidence = 0.46
            plan.notes.append("Planner needs a comparison dimension before ranking which cohort needs attention most.")
            return
        explicit_values: list[str] = []
        if compare_dimension == "branch":
            explicit_values = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="branch")
        elif compare_dimension == "category":
            explicit_values = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="category")
        elif compare_dimension == "region":
            explicit_values = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="region")
        elif compare_dimension == "income":
            explicit_values = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="income")
        elif compare_dimension == "outcome_status":
            explicit_values = _extract_outcome_mentions(lowered)
        plan.primary_intent = "admin_governance"
        plan.user_goal = "attention_analysis"
        plan.analysis_mode = "attention_ranking"
        plan.grouping = [compare_dimension]
        plan.comparison = {
            "enabled": True,
            "dimension": compare_dimension,
            "values": explicit_values,
        }
        plan.metrics = _derive_attention_metrics(lowered)
        plan.time_window_days = plan.time_window_days or 30
        plan.orchestration_steps = [
            "filter_requested_subset",
            f"group_subset_by_{compare_dimension}",
            "compute_current_risk_state",
            "compute_warning_and_support_gap",
            "compute_recent_risk_entry_trend",
            "rank_attention_index",
            "compose_reasoned_grounded_summary",
        ]
        plan.normalized_message = f"rank {compare_dimension} buckets by retention attention"
        plan.confidence = 0.92
        plan.notes.append("Planner recognized a domain-reasoning question asking which cohort needs attention most.")
        if "why" in lowered:
            plan.notes.append("Planner will include the strongest grounded reasons behind the top-ranked bucket.")
        return

    if any(
        token in lowered
        for token in {
            "needs attention first",
            "needs attention",
            "attention first",
            "attention now",
            "priority cases",
            "who should we focus on first",
        }
    ):
        plan.primary_intent = "admin_governance"
        plan.user_goal = "priority_queue"
        plan.normalized_message = "show the priority queue"
        plan.orchestration_steps = [
            "resolve_governance_scope",
            "load_current_priority_queue",
            "rank_priority_students",
            "compose_grounded_priority_summary",
        ]
        plan.confidence = 0.94
        plan.notes.append("Normalized attention-first phrasing to priority queue governance request.")
        return

    if _looks_like_diagnostic_reasoning_request(lowered=lowered, profiles=profiles):
        mentioned_dimensions = _detect_compare_dimensions(lowered=lowered, profiles=profiles)
        compare_dimension = mentioned_dimensions[0] if mentioned_dimensions else None
        if len(mentioned_dimensions) > 1:
            plan.user_goal = "diagnostic_comparison"
            plan.analysis_mode = "diagnostic_comparison"
            plan.clarification_needed = True
            plan.clarification_question = (
                f"I detected more than one diagnostic dimension: {', '.join(mentioned_dimensions)}. "
                "Please choose one dimension at a time so I can explain the strongest retention drivers cleanly."
            )
            plan.confidence = 0.5
            plan.notes.append("Planner detected a multi-dimension diagnostic request that needs clarification.")
            return
        if compare_dimension is None:
            plan.user_goal = "diagnostic_comparison"
            plan.analysis_mode = "diagnostic_comparison"
            plan.clarification_needed = True
            plan.clarification_question = (
                "Which retention dimension should I diagnose for you: branch, region, category, income, or outcome status?"
            )
            plan.confidence = 0.48
            plan.notes.append("Planner needs one diagnostic comparison dimension before explaining the main retention drivers.")
            return
        explicit_values: list[str] = []
        if compare_dimension == "branch":
            explicit_values = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="branch")
        elif compare_dimension == "category":
            explicit_values = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="category")
        elif compare_dimension == "region":
            explicit_values = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="region")
        elif compare_dimension == "income":
            explicit_values = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="income")
        elif compare_dimension == "outcome_status":
            explicit_values = _extract_outcome_mentions(lowered)
        plan.primary_intent = "admin_governance"
        plan.user_goal = "diagnostic_comparison"
        plan.analysis_mode = "diagnostic_comparison"
        plan.grouping = [compare_dimension]
        plan.comparison = {
            "enabled": True,
            "dimension": compare_dimension,
            "values": explicit_values,
        }
        plan.metrics = _derive_diagnostic_metrics(lowered)
        plan.time_window_days = plan.time_window_days or 30
        plan.orchestration_steps = [
            "filter_requested_subset",
            f"group_subset_by_{compare_dimension}",
            "compute_grounded_retention_signals",
            "derive_operational_gap_metrics",
            "rank_diagnostic_pressure",
            "compose_driver_explanation",
        ]
        plan.normalized_message = f"diagnose {compare_dimension} retention drivers"
        plan.confidence = 0.9
        plan.notes.append("Planner recognized a diagnostic retention question asking what is driving the gap or pressure.")
        return

    if _looks_like_comparison_request(lowered=lowered, profiles=profiles):
        mentioned_dimensions = _detect_compare_dimensions(lowered=lowered, profiles=profiles)
        compare_dimension = mentioned_dimensions[0] if mentioned_dimensions else None
        explicit_values = []
        if compare_dimension == "branch":
            explicit_values = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="branch")
        elif compare_dimension == "category":
            explicit_values = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="category")
        elif compare_dimension == "region":
            explicit_values = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="region")
        elif compare_dimension == "income":
            explicit_values = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="income")
        elif compare_dimension == "outcome_status":
            explicit_values = _extract_outcome_mentions(lowered)

        plan.user_goal = "comparison"
        plan.metrics = _infer_comparison_metrics(lowered)
        if len(mentioned_dimensions) > 1:
            plan.clarification_needed = True
            plan.clarification_question = (
                f"I detected more than one comparison dimension: {', '.join(mentioned_dimensions)}. "
                "Please choose one comparison dimension at a time so I can keep the result grounded."
            )
            plan.confidence = 0.45
            plan.notes.append("Planner detected a multi-dimension comparison request that needs clarification.")
            return
        if compare_dimension is None:
            plan.clarification_needed = True
            plan.clarification_question = (
                "What should I compare for you: branch, category, region, income, or outcome status?"
            )
            plan.confidence = 0.45
            return
        trend_metrics = {"recent_entry_risk_trend", "warning_trend", "intervention_trend"}
        if "improving" in lowered and len(explicit_values) <= 1 and not any(
            metric in trend_metrics for metric in plan.metrics
        ):
            plan.clarification_needed = True
            plan.clarification_question = (
                "I can compare current coverage across groups, but historical improvement by one bucket is not built yet. "
                "Do you want the current snapshot for that group, or a comparison across multiple groups?"
            )
            plan.confidence = 0.5
            plan.notes.append("Planner detected an improvement-over-time request that still needs a historical comparison layer.")
            return
        plan.grouping = [compare_dimension]
        plan.comparison = {
            "enabled": True,
            "dimension": compare_dimension,
            "values": explicit_values,
        }
        plan.analysis_mode = "comparison"
        plan.orchestration_steps = [
            "filter_requested_subset",
            f"group_subset_by_{compare_dimension}",
            "compute_requested_metrics",
            "rank_requested_buckets",
            "compose_grounded_comparison_summary",
        ]
        plan.primary_intent = "cohort_summary"
        plan.confidence = 0.88
        if compare_dimension == "branch" and not explicit_values and any(token in lowered for token in {"department", "departments", "branch", "branches"}):
            plan.normalized_message = "compare branches by high-risk students"
            plan.notes.append("Planner inferred a branch-wide comparison from department phrasing.")
        elif explicit_values and compare_dimension == "region":
            value_phrase = " vs ".join(explicit_values)
            if plan.filters.get("outcome_status"):
                plan.normalized_message = f"compare {value_phrase} {plan.filters['outcome_status'].lower()} high-risk students"
            else:
                plan.normalized_message = f"compare {value_phrase} high-risk students"
        elif explicit_values:
            value_phrase = " vs ".join(explicit_values)
            plan.normalized_message = f"compare {value_phrase} high-risk students"
        if any(metric in plan.metrics for metric in {"recent_entry_risk", "recent_entry_risk_trend", "warning_trend", "intervention_trend"}) and plan.time_window_days is None:
            plan.time_window_days = 30
            plan.notes.append("Planner defaulted the trend comparison window to 30 days.")
        if len(plan.metrics) > 1:
            plan.notes.append("Planner detected a multi-metric comparison request.")
        return

    if any(token in lowered for token in {"likely to drop out", "likely dropout", "students likely to drop out"}):
        plan.primary_intent = "admin_governance"
        plan.user_goal = "priority_queue"
        plan.normalized_message = "show the priority queue"
        plan.metrics = ["risk"]
        plan.orchestration_steps = [
            "resolve_governance_scope",
            "load_current_priority_queue",
            "rank_priority_students",
            "compose_grounded_priority_summary",
        ]
        plan.confidence = 0.84
        plan.notes.append("Mapped likely-dropout phrasing to current high-risk student priority view.")
        return

    if any(token in lowered for token in {"mentor", "assigned mentor", "assigned person", "flagged", "danger zone", "danger cases"}):
        plan.notes.append("Planner recognized broader retention-domain synonym phrasing.")
        plan.confidence = max(plan.confidence, 0.72)

    if memory.get("is_follow_up"):
        plan.follow_up_action = "follow_up"
        plan.confidence = max(plan.confidence, 0.8)


def _plan_counsellor_query(*, plan: CopilotQueryPlan, lowered: str) -> None:
    if any(token in lowered for token in {"needs attention first", "who needs attention first", "who should i focus on first"}):
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "priority_queue"
        plan.normalized_message = "priority queue"
        plan.orchestration_steps = [
            "resolve_counsellor_assignment_scope",
            "load_scoped_priority_queue",
            "rank_priority_students",
            "compose_grounded_priority_summary",
        ]
        plan.confidence = 0.9


def _plan_student_query(*, plan: CopilotQueryPlan, lowered: str) -> None:
    if any(
        token in lowered
        for token in {
            "am i in danger",
            "am i risky",
            "how bad is my risk",
            "am i likely to drop out",
            "how likely am i to drop out",
            "am i in trouble",
        }
    ):
        plan.primary_intent = "student_self_risk"
        plan.user_goal = "self_risk"
        plan.normalized_message = "what is my risk"
        plan.orchestration_steps = [
            "resolve_authenticated_student_scope",
            "load_latest_prediction",
            "compose_grounded_self_risk_summary",
        ]
        plan.confidence = 0.9


def _extract_filters(*, lowered: str, profiles: list[object]) -> dict[str, Any]:
    return {
        "outcome_status": _extract_outcome_mentions(lowered)[0] if len(_extract_outcome_mentions(lowered)) == 1 else None,
        "branches": _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="branch"),
        "categories": _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="category"),
        "regions": _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="region"),
        "incomes": _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="income"),
    }


def _infer_compare_dimension(*, lowered: str, profiles: list[object]) -> str | None:
    dimensions = _detect_compare_dimensions(lowered=lowered, profiles=profiles)
    return dimensions[0] if dimensions else None


def _detect_compare_dimensions(*, lowered: str, profiles: list[object]) -> list[str]:
    dimensions: list[str] = []
    if any(token in lowered for token in {"department", "departments", "branch", "branches"}):
        dimensions.append("branch")
    if any(token in lowered for token in {"region", "urban", "rural"}):
        dimensions.append("region")
    if any(token in lowered for token in {"category", "sc", "obc", "bc"}):
        dimensions.append("category")
    if any(token in lowered for token in {"income", "lpa"}):
        dimensions.append("income")
    branch_mentions = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="branch")
    if len(branch_mentions) > 1 and "branch" not in dimensions:
        dimensions.append("branch")
    region_mentions = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="region")
    if len(region_mentions) > 1 and "region" not in dimensions:
        dimensions.append("region")
    category_mentions = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="category")
    if len(category_mentions) > 1 and "category" not in dimensions:
        dimensions.append("category")
    income_mentions = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="income")
    if len(income_mentions) > 1 and "income" not in dimensions:
        dimensions.append("income")
    outcome_mentions = _extract_outcome_mentions(lowered)
    if len(outcome_mentions) > 1 and "outcome_status" not in dimensions:
        dimensions.append("outcome_status")
    return dimensions


def _extract_profile_context_mentions(*, lowered: str, profiles: list[object], key: str) -> list[str]:
    known_values = {
        str(_profile_context_value(profile, key)).strip()
        for profile in profiles
        if _profile_context_value(profile, key) not in (None, "")
    }
    matches_with_pos: list[tuple[int, str]] = []
    for value in known_values:
        match = re.search(rf"\b{re.escape(value.lower())}\b", lowered)
        if match is None:
            continue
        matches_with_pos.append((match.start(), value))
    matches_with_pos.sort(key=lambda item: (item[0], len(item[1])))
    return [value for _, value in matches_with_pos]


def _profile_context_value(profile: object, key: str) -> str | None:
    profile_context = getattr(profile, "profile_context", None) or {}
    value = profile_context.get(key)
    if value in (None, ""):
        return None
    return str(value)


def _extract_outcome_mentions(lowered: str) -> list[str]:
    mentions: list[str] = []
    if "dropped" in lowered or "dropout" in lowered or "dropouts" in lowered:
        mentions.append("Dropped")
    if "graduated" in lowered or "graduates" in lowered:
        mentions.append("Graduated")
    if "studying" in lowered or "continuing" in lowered:
        mentions.append("Studying")
    return mentions


def _is_sensitive_request(lowered: str) -> bool:
    return any(
        token in lowered
        for token in {
            "password",
            "passwords",
            "secret",
            "secrets",
            "api key",
            "api keys",
            "token",
            "tokens",
            "credential",
            "credentials",
            "private key",
            "private keys",
            "session cookie",
            "cookies",
            "database dump",
            "db dump",
            "export secrets",
            "leak secrets",
            "bank account",
            "credit card",
            "jwt",
            "bearer token",
            "refresh token",
            "env file",
            ".env",
            "admin password",
            "root password",
            "reveal credentials",
            "show credentials",
            "show tokens",
            "dump tokens",
        }
    )


def _looks_like_comparison_request(*, lowered: str, profiles: list[object]) -> bool:
    comparison_tokens = {
        "riskier lately",
        "getting riskier",
        "doing worse",
        "falling behind",
        "under pressure",
        "struggling most",
        "watch most closely",
        "compare",
        "versus",
        " vs ",
        " vs. ",
        "better",
        "worse",
        "improving",
        "improve",
        "highest",
        "lowest",
        "worst",
        "best",
        "largest",
        "biggest",
        "overlap",
        "gap",
    }
    if any(token in lowered for token in comparison_tokens):
        return True
    if re.search(r"\bwhich\s+(branch|branches|department|departments|region|regions|category|categories|income|band)\b", lowered):
        return True
    return False


def _infer_comparison_metrics(lowered: str) -> list[str]:
    metrics: list[str] = []
    trend_requested = _looks_like_trend_request(lowered)
    if any(
        token in lowered
        for token in {
            "dropped-to-risk overlap",
            "drop-to-risk overlap",
            "dropout-to-risk overlap",
            "dropped risk overlap",
            "dropout overlap",
        }
    ):
        metrics.append("dropped_risk_overlap")
    if any(
        token in lowered
        for token in {
            "warning-to-intervention gap",
            "warning intervention gap",
            "warnings-to-intervention gap",
            "warning-to-support gap",
            "warning support gap",
            "support gap",
        }
    ):
        metrics.append("warning_intervention_gap")
    if any(
        token in lowered
        for token in {
            "dropped-to-warning overlap",
            "drop-to-warning overlap",
            "dropped warning overlap",
            "dropout warning overlap",
        }
    ):
        metrics.append("dropped_warning_overlap")
    if any(
        token in lowered
        for token in {
            "high-risk-to-warning overlap",
            "high risk to warning overlap",
            "risk-to-warning overlap",
            "risk warning overlap",
            "flagged high risk overlap",
        }
    ):
        metrics.append("high_risk_warning_overlap")
    if any(
        token in lowered
        for token in {
            "high-risk-to-intervention gap",
            "high risk to intervention gap",
            "risk-to-intervention gap",
            "risk intervention gap",
            "high-risk support gap",
            "high risk support gap",
        }
    ):
        metrics.append("high_risk_intervention_gap")
    if any(
        token in lowered
        for token in {
            "unresolved risk burden",
            "risk burden",
            "unresolved burden",
            "operational burden",
            "support burden",
            "missing interventions most",
        }
    ):
        metrics.append("unresolved_risk_burden")
    if any(
        token in lowered
        for token in {
            "newly entered risk",
            "newly enter risk",
            "newly high risk",
            "recently entered risk",
            "entered risk",
            "entered into risk",
            "new high-risk",
            "new high risk",
        }
    ):
        metrics.append("recent_entry_risk")
    if trend_requested and any(
        token in lowered
        for token in {
            "riskier lately",
            "getting riskier",
            "newly entered risk",
            "newly high risk",
            "entered risk",
            "entered into risk",
            "drop out",
            "dropout",
            "doing worse",
        }
    ):
        metrics.append("recent_entry_risk_trend")
    if _parse_time_window_days(lowered) is not None and any(
        token in lowered for token in {"warning", "warnings", "flagged", "alert", "alerts"}
    ):
        metrics.append("recent_warning_events")
    if trend_requested and any(
        token in lowered for token in {"warning", "warnings", "flagged", "alert", "alerts"}
    ):
        metrics.append("warning_trend")
    if _parse_time_window_days(lowered) is not None and any(
        token in lowered for token in {"intervention", "interventions", "review coverage"}
    ):
        metrics.append("recent_intervention_events")
    if trend_requested and any(
        token in lowered for token in {"intervention", "interventions", "review coverage", "intervention coverage"}
    ):
        metrics.append("intervention_trend")
    if any(token in lowered for token in {"intervention coverage", "review coverage", "intervention review", "interventions"}):
        metrics.append("intervention_coverage")
    if any(token in lowered for token in {"warning", "warnings", "flagged", "alert", "alerts"}):
        metrics.append("warnings")
    if any(
        token in lowered
        for token in {
            "counsellor coverage",
            "counsellor",
            "counsellors",
            "mentor coverage",
            "assigned mentor",
            "assigned person",
        }
    ):
        metrics.append("counsellor_coverage")
    if any(token in lowered for token in {"risk", "riskier", "danger", "drop out", "dropout", "overlap", "doing worse"}):
        metrics.append("risk")
    if not metrics:
        metrics.append("count")
    ordered_unique: list[str] = []
    for item in metrics:
        if item not in ordered_unique:
            ordered_unique.append(item)
    return ordered_unique


def _derive_attention_metrics(lowered: str) -> list[str]:
    metrics: list[str] = []
    inferred_metrics = _infer_comparison_metrics(lowered)
    for metric in inferred_metrics:
        if metric not in {"count"}:
            metrics.append(metric)
    for metric in ["risk", "warning_intervention_gap", "recent_entry_risk_trend"]:
        if metric not in metrics:
            metrics.append(metric)
    ordered_unique: list[str] = []
    for metric in metrics:
        if metric not in ordered_unique:
            ordered_unique.append(metric)
    return ordered_unique


def _derive_diagnostic_metrics(lowered: str) -> list[str]:
    metrics: list[str] = []
    for metric in _infer_comparison_metrics(lowered):
        if metric not in {"count"}:
            metrics.append(metric)
    for metric in [
        "risk",
        "warning_intervention_gap",
        "high_risk_intervention_gap",
        "recent_entry_risk_trend",
        "warnings",
        "intervention_coverage",
    ]:
        if metric not in metrics:
            metrics.append(metric)
    if "unresolved_risk_burden" not in metrics and any(
        token in lowered
        for token in {"why", "driver", "drivers", "driving", "behind the gap", "explain the gap", "root cause"}
    ):
        metrics.append("unresolved_risk_burden")
    ordered_unique: list[str] = []
    for metric in metrics:
        if metric not in ordered_unique:
            ordered_unique.append(metric)
    return ordered_unique


def _looks_like_attention_analysis_request(lowered: str) -> bool:
    return any(
        token in lowered
        for token in {
            "needs attention first",
            "need attention first",
            "needs the most attention",
            "need the most attention",
            "slipping most",
            "falling behind most",
            "under the most pressure",
            "under pressure",
            "struggling most",
            "watch most closely",
            "doing worst overall",
            "most concerning",
            "should we intervene on first",
            "attention most",
        }
    )


def _looks_like_diagnostic_reasoning_request(*, lowered: str, profiles: list[object]) -> bool:
    if not (_looks_like_comparison_request(lowered=lowered, profiles=profiles) or _looks_like_attention_analysis_request(lowered)):
        return False
    return any(
        token in lowered
        for token in {
            "why is",
            "why are",
            "what is driving",
            "what's driving",
            "drivers",
            "driving the gap",
            "behind the gap",
            "root cause",
            "explain the gap",
            "missing interventions most",
        }
    )


def _looks_like_trend_request(lowered: str) -> bool:
    return any(
        token in lowered
        for token in {
            "lately",
            "recently",
            "long term",
            "long-term",
            "over the last quarter",
            "over the quarter",
            "over the last semester",
            "improving",
            "improve",
            "trend",
            "trending",
            "increase",
            "increasing",
            "decrease",
            "decline",
            "declining",
            "getting riskier",
            "doing worse",
            "change over time",
        }
    )


def _parse_time_window_days(lowered: str) -> int | None:
    match = re.search(r"\b(\d{1,3})\s*(day|days|d)\b", lowered)
    if match:
        return int(match.group(1))
    if "last week" in lowered or "past week" in lowered:
        return 7
    if "last month" in lowered or "past month" in lowered:
        return 30
    if "last 24 hours" in lowered or "past 24 hours" in lowered or "last day" in lowered:
        return 1
    if "last quarter" in lowered or "past quarter" in lowered or "over the last quarter" in lowered:
        return 90
    if "last semester" in lowered or "past semester" in lowered or "over the last semester" in lowered:
        return 180
    return None
