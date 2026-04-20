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
    default_follow_up_rewrite: str | None = None
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
    memory = resolve_copilot_memory_context(message=message, session_messages=session_messages)
    normalized_message = _apply_shared_default_assumptions(
        role=role,
        message=message,
        memory=memory,
    )
    lowered = str(normalized_message or "").strip().lower()
    original_lowered = str(message or "").strip().lower()
    admin_default_topic_reset = (
        role == "admin"
        and (original_lowered in {"risk", "trend", "stats", "analysis", "report", "performance"} or lowered in {"risk", "trend", "stats", "analysis", "report", "performance"})
    )
    detected_intent = detect_copilot_intent(role=role, message=normalized_message)
    profile_list = profiles or []

    plan = CopilotQueryPlan(
        role=role,
        original_message=message,
        normalized_message=normalized_message,
        primary_intent=detected_intent,
        confidence=0.55,
        filters=_extract_filters(lowered=lowered, profiles=profile_list),
        grouping=_extract_grouping_dimensions(lowered),
        time_window_days=memory.get("window_days") or _parse_time_window_days(lowered),
        follow_up_action="follow_up" if memory.get("is_follow_up") and not admin_default_topic_reset else None,
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


def _apply_shared_default_assumptions(
    *,
    role: RoleName,
    message: str,
    memory: dict[str, Any],
) -> str:
    raw_message = str(message or "").strip()
    if not raw_message:
        return raw_message

    normalized = " ".join(raw_message.split())
    lowered = normalized.lower()
    trimmed = lowered.strip(" ?!.")
    last_context = memory.get("last_context") or {}
    remembered_rewrite = str(last_context.get("default_follow_up_rewrite") or "").strip()
    pending_role_follow_up = str(last_context.get("pending_role_follow_up") or "").strip().lower()
    last_intent = str(last_context.get("intent") or "").strip().lower()

    if memory.get("is_follow_up") and remembered_rewrite and trimmed in {
        "yes",
        "yeah",
        "yep",
        "ok",
        "okay",
        "continue",
        "proceed",
        "go on",
        "tell",
        "tell me",
        "then",
    } and not (
        role == "counsellor"
        and pending_role_follow_up == "student_specific_action"
        and last_intent == "counsellor_student_action_plan"
    ):
        return remembered_rewrite

    if role == "student":
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
            return "what is my assignment submission rate right now"
        if trimmed in {"attendance", "my attendance", "current attendance", "overall attendance"}:
            return "what is my overall attendance right now"
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
            return "show me my lms activity right now"
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
            return "show me my erp details right now"
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
            return "show me my finance details right now"
        if trimmed in {"risk", "my risk", "current risk"}:
            return "what is my current risk level"

    if role == "counsellor":
        if any(
            phrase in lowered
            for phrase in {
                "which students are high risk",
                "show high risk students",
                "list all risky students",
                "who are in danger",
                "show risky students",
                "risky students",
                "students in danger",
            }
        ) and not any(
            phrase in lowered
            for phrase in {
                "compare attendance and assignments for risky students",
                "compare assignments and attendance for risky students",
            }
        ):
            return "which students are high risk"
        if any(
            phrase in lowered
            for phrase in {
                "top 5 risky students",
                "top 3 risky students",
                "show top 3",
                "most critical students",
                "give me most critical students",
                "worst performing students",
                "who are worst performing",
                "who is worst student",
                "which student is worst",
            }
        ):
            return "show top 3 risky students" if "top 3" in lowered else "show top 5 risky students"
        if any(
            phrase in lowered
            for phrase in {
                "how can i help them",
                "what intervention should i take",
                "how to reduce their risk",
                "what actions are needed",
            }
        ):
            return "what should i do for high risk students"
        if trimmed in {"risk", "my risk", "current risk"}:
            return "which students are high risk"
        if trimmed in {"status", "status?"}:
            return "which students are high risk"
        if trimmed in {"list", "list?"}:
            return "show my assigned students"
        if trimmed in {"performance", "performance?"}:
            return "which students are struggling"
        if trimmed in {
            "students",
            "students?",
            "my students",
            "assigned students",
            "my assigned students",
            "show my students",
            "show my assigned students",
            "who are my students",
            "who all are my students",
            "who are under me",
            "who all are under me",
        }:
            return "show my assigned students"

    if role == "admin":
        if trimmed in {"risk", "current risk"}:
            return "how many students are high risk"
        if trimmed in {"stats", "stats?", "institution stats", "current stats"}:
            return "how many students are high risk"
        if trimmed in {"trend", "trend?", "current trend", "risk trend"}:
            return "how many students just entered risk in the last 30 days"
        if trimmed in {"analysis", "analysis?", "report", "report?"}:
            return "show institution report"
        if trimmed in {"performance", "performance?"}:
            return "how is overall performance"
        if any(
            phrase in lowered
            for phrase in {
                "total number of students",
                "how many active students",
            }
        ):
            return "show institution student count"
        if any(
            phrase in lowered
            for phrase in {
                "branch wise student count",
                "number of students per department",
            }
        ):
            return "show branch wise student count"
        if any(
            phrase in lowered
            for phrase in {
                "show risk distribution",
                "how many low medium high risk students",
            }
        ):
            return "show institution risk distribution"

    return normalized


def _plan_admin_query(*, plan: CopilotQueryPlan, lowered: str, profiles: list[object], memory: dict[str, Any]) -> None:
    if lowered == "show institution student count":
        plan.primary_intent = "import_coverage"
        plan.user_goal = "institution_student_count"
        plan.analysis_mode = "institution_counts"
        plan.confidence = 0.94
        return

    if lowered == "show institution report":
        plan.primary_intent = "admin_governance"
        plan.user_goal = "institution_report"
        plan.analysis_mode = "institution_snapshot"
        plan.confidence = 0.9
        return

    if plan.filters.get("branches") and "why" in lowered and "high risk" in lowered:
        plan.primary_intent = "admin_governance"
        plan.user_goal = "filtered_branch_explanation"
        plan.analysis_mode = "branch_reasoning"
        plan.confidence = 0.9
        return

    if lowered in {
        "how is overall performance",
        "is everything going well",
        "which area is problematic",
        "are students doing okay",
        "is the situation under control",
        "which factor is affecting students most",
        "why is performance declining",
        "compare lms vs erp impact",
        "how finance is affecting risk",
        "which factor impacts performance most",
        "hidden risk across departments",
        "which branch has good attendance but high risk",
    }:
        plan.primary_intent = "admin_governance"
        plan.user_goal = "institution_health_explanation"
        plan.analysis_mode = "institution_health"
        plan.confidence = 0.9
        return

    if lowered in {
        "year wise performance",
        "risk by year",
        "compare 1st year vs final year",
        "compare first year vs final year",
    }:
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "grouped_risk_breakdown"
        plan.analysis_mode = "grouped_breakdown"
        plan.grouping = ["year"]
        plan.metrics = ["prediction_high_risk", "overall_shortage", "i_grade_risk", "r_grade_risk"]
        plan.orchestration_steps = [
            "resolve_institution_scope",
            "group_students_by_requested_academic_dimensions",
            "compute_prediction_and_attendance_risk_layers",
            "compose_grounded_grouped_breakdown",
        ]
        plan.normalized_message = "show grouped institutional risk breakdown"
        plan.confidence = 0.91
        return

    if lowered in {
        "performance by branch",
        "risk by department",
    }:
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "grouped_risk_breakdown"
        plan.analysis_mode = "grouped_breakdown"
        plan.grouping = ["branch"]
        plan.metrics = ["prediction_high_risk", "overall_shortage", "i_grade_risk", "r_grade_risk"]
        plan.orchestration_steps = [
            "resolve_institution_scope",
            "group_students_by_requested_academic_dimensions",
            "compute_prediction_and_attendance_risk_layers",
            "compose_grounded_grouped_breakdown",
        ]
        plan.normalized_message = "show grouped institutional risk breakdown"
        plan.confidence = 0.91
        return

    if lowered == "show branch wise student count":
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "grouped_student_count"
        plan.analysis_mode = "grouped_counts"
        plan.grouping = ["branch"]
        plan.metrics = ["count"]
        plan.confidence = 0.94
        return

    if lowered == "show institution risk distribution":
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "risk_distribution"
        plan.analysis_mode = "distribution"
        plan.confidence = 0.94
        return

    grouped_risk_metrics = _extract_grouped_risk_metrics(lowered)
    if plan.grouping and grouped_risk_metrics:
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "grouped_risk_breakdown"
        plan.analysis_mode = "grouped_breakdown"
        plan.metrics = grouped_risk_metrics
        plan.orchestration_steps = [
            "resolve_institution_scope",
            "group_students_by_requested_academic_dimensions",
            "compute_prediction_and_attendance_risk_layers",
            "compose_grounded_grouped_breakdown",
        ]
        plan.normalized_message = "show grouped institutional risk breakdown"
        plan.confidence = 0.95
        if "prediction_high_risk" in grouped_risk_metrics and any(
            metric in grouped_risk_metrics for metric in {"overall_shortage", "i_grade_risk", "r_grade_risk"}
        ):
            plan.notes.append("Planner recognized that generic high-risk phrasing is ambiguous and should separate prediction risk from attendance-policy risk.")
        return

    if _looks_like_role_action_request(lowered=lowered, role="admin"):
        plan.primary_intent = "admin_governance"
        plan.user_goal = "role_action_request"
        plan.analysis_mode = "operational_advisory"
        plan.normalized_message = "show institutional operational priorities"
        plan.orchestration_steps = [
            "resolve_institution_scope",
            "load_priority_queue",
            "load_attendance_pressure_and_subject_hotspots",
            "load_carry_forward_burden_counts",
            "compose_grounded_institution_action_list",
        ]
        plan.confidence = 0.88
        plan.notes.append("Planner mapped an admin action-style question to a grounded institutional operational advisory response.")
        return

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
        explicit_values = _extract_compare_explicit_values(
            lowered=lowered,
            profiles=profiles,
            compare_dimension=compare_dimension,
        )
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
        explicit_values = _extract_compare_explicit_values(
            lowered=lowered,
            profiles=profiles,
            compare_dimension=compare_dimension,
        )
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
        explicit_values = _extract_compare_explicit_values(
            lowered=lowered,
            profiles=profiles,
            compare_dimension=compare_dimension,
        )

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

    if any(
        token in lowered
        for token in {
            "needs attention first",
            "need attention first",
            "which students need attention first",
            "students need attention first",
            "attention first this week",
            "who should we focus on first",
        }
    ):
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
        plan.confidence = 0.9
        plan.notes.append("Mapped attention-first phrasing to current institutional priority queue view.")
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

    admin_default_topic_reset = (
        plan.role == "admin"
        and (
            lowered.strip().lower() in {"risk", "trend", "stats", "analysis", "report", "performance"}
            or str(plan.original_message or "").strip().lower() in {"risk", "trend", "stats", "analysis", "report", "performance"}
        )
    )
    if memory.get("is_follow_up") and not admin_default_topic_reset:
        plan.follow_up_action = "follow_up"
        plan.confidence = max(plan.confidence, 0.8)


def _plan_counsellor_query(*, plan: CopilotQueryPlan, lowered: str) -> None:
    if re.search(r"\b(88\d{4,})\b", lowered):
        plan.primary_intent = "student_drilldown"
        plan.user_goal = "student_drilldown"
        plan.analysis_mode = "individual_reasoning"
        plan.normalized_message = lowered
        plan.confidence = 0.94
        return

    grouped_risk_metrics = _extract_grouped_risk_metrics(lowered)
    if plan.grouping and grouped_risk_metrics:
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "grouped_risk_breakdown"
        plan.analysis_mode = "grouped_breakdown"
        plan.metrics = grouped_risk_metrics
        plan.orchestration_steps = [
            "resolve_counsellor_assignment_scope",
            "group_scoped_students_by_requested_academic_dimensions",
            "compute_prediction_and_attendance_risk_layers",
            "compose_grounded_grouped_breakdown",
        ]
        plan.normalized_message = "show grouped counsellor risk breakdown"
        plan.confidence = 0.93
        if "prediction_high_risk" in grouped_risk_metrics and any(
            metric in grouped_risk_metrics for metric in {"overall_shortage", "i_grade_risk", "r_grade_risk"}
        ):
            plan.notes.append("Planner recognized that generic high-risk phrasing should separate prediction risk from attendance-policy risk inside counsellor scope.")
        return

    if _looks_like_role_action_request(lowered=lowered, role="counsellor"):
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "role_action_request"
        plan.analysis_mode = "operational_advisory"
        plan.normalized_message = "show counsellor operational priorities"
        plan.orchestration_steps = [
            "resolve_counsellor_assignment_scope",
            "load_scoped_priority_queue",
            "load_scoped_attendance_pressure_and_subject_hotspots",
            "load_scoped_carry_forward_burden_counts",
            "compose_grounded_counsellor_action_list",
        ]
        plan.confidence = 0.87
        plan.notes.append("Planner mapped a counsellor action-style question to a grounded scoped operational advisory response.")
        return

    if any(
        token in lowered
        for token in {
            "needs attention first",
            "need attention first",
            "who needs attention first",
            "which students need attention first",
            "students need attention first",
            "attention first this week",
            "who should i focus on first",
        }
    ):
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
        return

    if any(
        token in lowered
        for token in {
            "who needs attention",
            "which students are struggling",
            "any critical cases",
            "who should i focus on",
            "which students are not doing well",
            "who is in trouble",
            "which students need immediate help",
            "who needs urgent help",
            "who is in serious condition",
            "which student should i prioritize",
        }
    ):
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "priority_queue"
        plan.normalized_message = "priority queue"
        plan.analysis_mode = "attention_queue"
        plan.orchestration_steps = [
            "resolve_counsellor_assignment_scope",
            "load_scoped_priority_queue",
            "rank_priority_students",
            "compose_grounded_priority_summary",
        ]
        plan.confidence = 0.88
        return

    if any(
        token in lowered
        for token in {
            "what is biggest issue across my students",
            "which factor is affecting most students",
            "which students are improving vs declining",
            "which group is performing worst",
            "which department has more risk",
            "are my students improving",
            "is risk increasing in my group",
            "who will fail if ignored",
            "which student will fail",
            "should i worry about my group",
            "are things getting worse",
        }
    ):
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "cohort_explanation"
        plan.analysis_mode = "cohort_reasoning"
        plan.normalized_message = lowered
        plan.orchestration_steps = [
            "resolve_counsellor_assignment_scope",
            "load_scoped_prediction_and_attendance_pressure",
            "load_scoped_burden_and_subject_hotspots",
            "compose_grounded_cohort_explanation",
        ]
        plan.confidence = 0.87
        return

    if (
        "why are" in lowered
        and "risky" in lowered
        and "student" in lowered
    ):
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "cohort_explanation"
        plan.analysis_mode = "cohort_reasoning"
        plan.normalized_message = lowered
        plan.orchestration_steps = [
            "resolve_counsellor_assignment_scope",
            "load_scoped_prediction_and_attendance_pressure",
            "load_scoped_burden_and_subject_hotspots",
            "compose_grounded_cohort_explanation",
        ]
        plan.confidence = 0.85
        return

    if _looks_like_attention_analysis_request(lowered) and _detect_compare_dimensions(lowered=lowered, profiles=[]):
        mentioned_dimensions = _detect_compare_dimensions(lowered=lowered, profiles=[])
        compare_dimension = mentioned_dimensions[0] if mentioned_dimensions else None
        if len(mentioned_dimensions) > 1:
            plan.user_goal = "attention_analysis"
            plan.analysis_mode = "attention_ranking"
            plan.clarification_needed = True
            plan.clarification_question = (
                f"I detected more than one analysis dimension: {', '.join(mentioned_dimensions)}. "
                "Please choose one dimension at a time so I can rank the riskiest bucket cleanly inside your counsellor scope."
            )
            plan.confidence = 0.48
            return
        if compare_dimension is None:
            plan.user_goal = "attention_analysis"
            plan.analysis_mode = "attention_ranking"
            plan.clarification_needed = True
            plan.clarification_question = (
                "Which dimension should I rank for attention inside your counsellor scope: branch, gender, age band, batch, program type, category, region, income, or outcome status?"
            )
            plan.confidence = 0.46
            return
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "attention_analysis"
        plan.analysis_mode = "attention_ranking"
        plan.grouping = [compare_dimension]
        plan.comparison = {
            "enabled": True,
            "dimension": compare_dimension,
            "values": [],
        }
        plan.metrics = _derive_attention_metrics(lowered)
        plan.time_window_days = plan.time_window_days or 30
        plan.orchestration_steps = [
            "resolve_counsellor_assignment_scope",
            f"group_scoped_students_by_{compare_dimension}",
            "compute_current_risk_state",
            "compute_warning_and_support_gap",
            "compute_recent_risk_entry_trend",
            "rank_attention_index",
            "compose_reasoned_grounded_summary",
        ]
        plan.confidence = 0.9
        return

    if _looks_like_diagnostic_reasoning_request(lowered=lowered, profiles=[]):
        mentioned_dimensions = _detect_compare_dimensions(lowered=lowered, profiles=[])
        compare_dimension = mentioned_dimensions[0] if mentioned_dimensions else None
        if len(mentioned_dimensions) > 1:
            plan.user_goal = "diagnostic_comparison"
            plan.analysis_mode = "diagnostic_comparison"
            plan.clarification_needed = True
            plan.clarification_question = (
                f"I detected more than one diagnostic dimension: {', '.join(mentioned_dimensions)}. "
                "Please choose one dimension at a time so I can explain the strongest driver cleanly inside your counsellor scope."
            )
            plan.confidence = 0.5
            return
        if compare_dimension is None:
            plan.user_goal = "diagnostic_comparison"
            plan.analysis_mode = "diagnostic_comparison"
            plan.clarification_needed = True
            plan.clarification_question = (
                "Which dimension should I diagnose inside your counsellor scope: branch, gender, age band, batch, program type, category, region, income, or outcome status?"
            )
            plan.confidence = 0.48
            return
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "diagnostic_comparison"
        plan.analysis_mode = "diagnostic_comparison"
        plan.grouping = [compare_dimension]
        plan.comparison = {
            "enabled": True,
            "dimension": compare_dimension,
            "values": [],
        }
        plan.metrics = _derive_diagnostic_metrics(lowered)
        plan.time_window_days = plan.time_window_days or 30
        plan.orchestration_steps = [
            "resolve_counsellor_assignment_scope",
            f"group_scoped_students_by_{compare_dimension}",
            "compute_grounded_retention_signals",
            "derive_operational_gap_metrics",
            "rank_diagnostic_pressure",
            "compose_driver_explanation",
        ]
        plan.confidence = 0.88
        return

    if any(
        phrase in lowered
        for phrase in {
            "compare attendance and assignments for risky students",
            "compare assignments and attendance for risky students",
        }
    ):
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "cohort_explanation"
        plan.analysis_mode = "cohort_reasoning"
        plan.normalized_message = lowered
        plan.orchestration_steps = [
            "resolve_counsellor_assignment_scope",
            "load_scoped_prediction_and_attendance_pressure",
            "load_scoped_coursework_and_submission_pressure",
            "compose_grounded_cohort_explanation",
        ]
        plan.confidence = 0.9
        return

    if _looks_like_comparison_request(lowered=lowered, profiles=[]):
        mentioned_dimensions = _detect_compare_dimensions(lowered=lowered, profiles=[])
        compare_dimension = mentioned_dimensions[0] if mentioned_dimensions else None
        if len(mentioned_dimensions) > 1:
            plan.clarification_needed = True
            plan.clarification_question = (
                f"I detected more than one comparison dimension: {', '.join(mentioned_dimensions)}. "
                "Please choose one comparison dimension at a time so I can keep the result grounded inside your counsellor scope."
            )
            plan.confidence = 0.45
            return
        if compare_dimension is None:
            plan.clarification_needed = True
            plan.clarification_question = (
                "What should I compare for you inside your counsellor scope: branch, gender, age band, batch, program type, category, region, income, or outcome status?"
            )
            plan.confidence = 0.45
            return
        plan.primary_intent = "cohort_summary"
        plan.user_goal = "comparison"
        plan.grouping = [compare_dimension]
        plan.comparison = {
            "enabled": True,
            "dimension": compare_dimension,
            "values": [],
        }
        plan.metrics = _infer_comparison_metrics(lowered)
        plan.analysis_mode = "comparison"
        plan.orchestration_steps = [
            "resolve_counsellor_assignment_scope",
            f"group_scoped_students_by_{compare_dimension}",
            "compute_requested_metrics",
            "rank_requested_buckets",
            "compose_grounded_comparison_summary",
        ]
        plan.confidence = 0.86
        return


def _plan_student_query(*, plan: CopilotQueryPlan, lowered: str) -> None:
    if (
        "assignment" in lowered
        and "complete" in lowered
        and any(token in lowered for token in {"should i", "need to", "do i need to", "must i"})
    ):
        plan.primary_intent = "student_self_plan"
        plan.user_goal = "student_action_request"
        plan.normalized_message = "coursework priorities"
        plan.analysis_mode = "advisory"
        plan.orchestration_steps = [
            "resolve_authenticated_student_scope",
            "load_coursework_and_prediction_context",
            "build_grounded_student_action_advice",
        ]
        plan.confidence = 0.9
        return

    if (
        "attendance" in lowered
        and "risk" in lowered
        and any(token in lowered for token in {"good", "safe", "looks good", "looks safe"})
    ):
        plan.primary_intent = "student_self_subject_risk"
        plan.user_goal = "student_explanation_request"
        plan.normalized_message = "my attendance is good but why am i high risk"
        plan.analysis_mode = "diagnostic_explanation"
        plan.orchestration_steps = [
            "resolve_authenticated_student_scope",
            "load_attendance_and_academic_burden_context",
            "build_grounded_student_subject_risk_explanation",
        ]
        plan.confidence = 0.9
        return

    if any(
        phrase in lowered
        for phrase in {
            "can i fix it",
            "how to fix that",
            "what next",
            "what else should i do",
            "which is most important",
        }
    ):
        plan.primary_intent = "student_self_plan"
        plan.user_goal = "student_action_request"
        plan.normalized_message = "show me my overall recovery priorities"
        plan.analysis_mode = "advisory"
        plan.orchestration_steps = [
            "resolve_authenticated_student_scope",
            "load_prediction_attendance_lms_erp_finance_context",
            "build_grounded_student_action_advice",
        ]
        plan.confidence = 0.88
        return

    if any(
        phrase in lowered
        for phrase in {
            "what caused this",
            "what caused it",
            "what caused my risk",
            "what else is still driving my risk besides assignments",
            "what happens if i miss my next assignment submission",
            "will missing coursework increase my current risk",
            "how much could missing coursework raise my current risk",
            "what is affecting my results",
            "why is my performance low",
            "why is my gpa dropping",
            "what is going wrong",
            "what is main problem",
            "explain more",
            "why",
            "how serious is it",
            "what does this risk posture mean right now",
            "how is my attendance and assignments together",
            "compare my lms and gpa",
            "which is affecting me more assignments or attendance",
            "what is my biggest weakness",
            "am i worse than others",
            "does attendance really matter",
            "is lms important",
            "what if i don't fix it",
            "what if i dont fix it",
            "what if i only fix assignments",
            "would only fixing assignments be enough to reduce my current risk",
            "is that enough",
            "what if i stop studying",
            "what happens if i do not improve my current risk drivers",
            "what happens if i don't improve",
            "what happens if i dont improve",
            "what happens if i ignore this",
            "if i do not clear this what happens",
            "if i dont clear this what happens",
            "what happens if i do not clear this",
            "what happens if i dont clear this",
            "will i fail",
            "what is worst case",
            "how long will it take",
            "how much time i have",
            "how fast can i improve",
            "can i still recover",
            "can i recover fully",
        }
    ):
        plan.primary_intent = "student_self_subject_risk"
        plan.user_goal = "student_explanation_request"
        plan.analysis_mode = "diagnostic_explanation"
        plan.orchestration_steps = [
            "resolve_authenticated_student_scope",
            "load_attendance_and_academic_burden_context",
            "build_grounded_student_subject_risk_explanation",
        ]
        if any(
            phrase in lowered
            for phrase in {
                "how is my attendance and assignments together",
                "compare my lms and gpa",
                "which is affecting me more assignments or attendance",
                "what is my biggest weakness",
            }
        ):
            plan.normalized_message = "what exactly is hurting me most right now"
        elif "what is main problem" in lowered:
            plan.normalized_message = "what exactly is hurting me most right now"
        elif any(
            phrase in lowered
            for phrase in {
                "what caused this",
                "what caused it",
                "what caused my risk",
                "what is affecting my results",
                "why is my performance low",
                "why is my gpa dropping",
                "what is going wrong",
                "explain more",
                "why",
                "what does this risk posture mean right now",
            }
        ):
            plan.normalized_message = "what is causing my current risk"
        elif "how serious is it" in lowered:
            plan.normalized_message = "how serious is my situation"
        elif any(
            phrase in lowered
            for phrase in {
                "does attendance really matter",
                "is lms important",
            }
        ):
            plan.normalized_message = lowered
        elif any(
            phrase in lowered
            for phrase in {
                "what if i stop studying",
                "what happens if i don't improve",
                "what happens if i dont improve",
                "what happens if i ignore this",
                "what if i don't fix it",
                "what if i dont fix it",
                "if i do not clear this what happens",
                "if i dont clear this what happens",
                "what happens if i do not clear this",
                "what happens if i dont clear this",
            }
        ):
            plan.normalized_message = "what happens if i do not improve my current risk drivers"
        elif any(
            phrase in lowered
            for phrase in {
                "what if i only fix assignments",
                "would only fixing assignments be enough to reduce my current risk",
                "is that enough",
            }
        ):
            plan.normalized_message = "would only fixing assignments be enough to reduce my current risk"
        elif "will i fail" in lowered:
            plan.normalized_message = "will i fail if my current risk drivers do not improve"
        elif "what is worst case" in lowered:
            plan.normalized_message = "what is the worst case if my current risk drivers do not improve"
        elif any(
            phrase in lowered
            for phrase in {
                "how long will it take",
                "how much time i have",
                "how fast can i improve",
            }
        ):
            plan.normalized_message = "how long might recovery take from my current risk"
        elif any(
            phrase in lowered
            for phrase in {
                "can i still recover",
                "can i recover fully",
            }
        ):
            plan.normalized_message = "can i still recover from my current risk"
        else:
            plan.normalized_message = "am i safe or should i worry"
        plan.confidence = 0.9
        return

    if any(
        token in lowered
        for token in {
            "am i in danger",
            "am i in trouble",
        }
    ):
        plan.primary_intent = "student_self_subject_risk"
        plan.user_goal = "student_explanation_request"
        plan.normalized_message = "am i safe or should i worry"
        plan.analysis_mode = "diagnostic_explanation"
        plan.orchestration_steps = [
            "resolve_authenticated_student_scope",
            "load_attendance_and_academic_burden_context",
            "build_grounded_student_subject_risk_explanation",
        ]
        plan.confidence = 0.9
        return

    if any(
        token in lowered
        for token in {
            "am i risky",
            "how bad is my risk",
            "am i likely to drop out",
            "how likely am i to drop out",
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
        return

    if plan.primary_intent == "student_self_plan":
        plan.user_goal = "student_action_request"
        plan.analysis_mode = "advisory"
        plan.orchestration_steps = [
            "resolve_authenticated_student_scope",
            "load_prediction_attendance_lms_erp_finance_context",
            "build_grounded_student_action_advice",
        ]
        plan.confidence = max(plan.confidence, 0.86)
        return

    if plan.primary_intent == "student_self_subject_risk":
        plan.user_goal = "student_explanation_request"
        plan.analysis_mode = "diagnostic_explanation"
        plan.orchestration_steps = [
            "resolve_authenticated_student_scope",
            "load_attendance_and_academic_burden_context",
            "build_grounded_student_subject_risk_explanation",
        ]
        plan.confidence = max(plan.confidence, 0.84)
        return

    if plan.primary_intent == "student_self_attendance":
        plan.user_goal = "student_data_request"
        plan.analysis_mode = "grounded_summary"
        plan.orchestration_steps = [
            "resolve_authenticated_student_scope",
            "load_current_attendance_foundation",
            "compose_grounded_attendance_summary",
        ]
        plan.confidence = max(plan.confidence, 0.84)
        return


def _extract_filters(*, lowered: str, profiles: list[object]) -> dict[str, Any]:
    return {
        "outcome_status": _extract_outcome_mentions(lowered)[0] if len(_extract_outcome_mentions(lowered)) == 1 else None,
        "branches": _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="branch"),
        "genders": _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="gender"),
        "age_bands": _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="age_band"),
        "batches": _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="batch"),
        "program_types": _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="program_type"),
        "categories": _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="category"),
        "regions": _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="region"),
        "incomes": _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="income"),
    }


def _extract_grouping_dimensions(lowered: str) -> list[str]:
    grouping: list[str] = []
    if any(token in lowered for token in {"semester-wise", "semester wise", "sem-wise", "sem wise"}):
        grouping.append("semester")
    if any(token in lowered for token in {"year-wise", "year wise"}):
        grouping.append("year")
    if any(token in lowered for token in {"branch-wise", "branch wise", "department-wise", "department wise", "by department"}):
        grouping.append("branch")
    if any(token in lowered for token in {"gender-wise", "gender wise", "sex-wise", "sex wise"}):
        grouping.append("gender")
    if any(token in lowered for token in {"age-wise", "age wise", "age-band-wise", "age band wise"}):
        grouping.append("age_band")
    if any(token in lowered for token in {"batch-wise", "batch wise"}):
        grouping.append("batch")
    if any(
        token in lowered
        for token in {"program-wise", "program wise", "programme-wise", "programme wise", "program-type-wise", "program type wise"}
    ):
        grouping.append("program_type")
    if any(token in lowered for token in {"category-wise", "category wise"}):
        grouping.append("category")
    if any(token in lowered for token in {"region-wise", "region wise"}):
        grouping.append("region")
    if any(token in lowered for token in {"income-wise", "income wise"}):
        grouping.append("income")
    if any(token in lowered for token in {"status-wise", "status wise", "outcome-wise", "outcome wise"}):
        grouping.append("outcome_status")
    if any(token in lowered for token in {"group by semester", "by semester", "semester by semester"}) and "semester" not in grouping:
        grouping.append("semester")
    if any(token in lowered for token in {"group by year", "by year", "year by year"}) and "year" not in grouping:
        grouping.append("year")
    if any(token in lowered for token in {"group by branch", "by branch"}) and "branch" not in grouping:
        grouping.append("branch")
    if any(token in lowered for token in {"group by gender", "by gender", "group by sex", "by sex"}) and "gender" not in grouping:
        grouping.append("gender")
    if any(token in lowered for token in {"group by age", "by age", "group by age band", "by age band"}) and "age_band" not in grouping:
        grouping.append("age_band")
    if any(token in lowered for token in {"group by batch", "by batch"}) and "batch" not in grouping:
        grouping.append("batch")
    if any(
        token in lowered
        for token in {"group by program", "by program", "group by programme", "by programme", "group by program type", "by program type"}
    ) and "program_type" not in grouping:
        grouping.append("program_type")
    if any(token in lowered for token in {"group by category", "by category"}) and "category" not in grouping:
        grouping.append("category")
    if any(token in lowered for token in {"group by region", "by region"}) and "region" not in grouping:
        grouping.append("region")
    if any(token in lowered for token in {"group by income", "by income"}) and "income" not in grouping:
        grouping.append("income")
    if any(token in lowered for token in {"group by status", "group by outcome", "by status", "by outcome"}) and "outcome_status" not in grouping:
        grouping.append("outcome_status")
    return grouping


def _extract_grouped_risk_metrics(lowered: str) -> list[str]:
    metrics: list[str] = []
    mentions_prediction = any(
        token in lowered for token in {"prediction", "model", "predicted", "ml risk", "prediction risk"}
    )
    mentions_overall_shortage = any(
        token in lowered for token in {"overall shortage", "overall attendance", "below overall", "shortage"}
    )
    mentions_i_grade = any(token in lowered for token in {"i grade", "i-grade", "condonation"})
    mentions_r_grade = any(token in lowered for token in {"r grade", "r-grade", "repeat grade", "repeat subject"})
    mentions_attendance = any(
        token in lowered for token in {"attendance", "attendance risk", "academic risk", "policy risk"}
    )
    mentions_generic_risk = any(
        token in lowered for token in {"high risk", "high-risk", "risk", "risky", "at risk"}
    )

    if mentions_prediction:
        metrics.append("prediction_high_risk")
    if mentions_overall_shortage:
        metrics.append("overall_shortage")
    if mentions_i_grade:
        metrics.append("i_grade_risk")
    if mentions_r_grade:
        metrics.append("r_grade_risk")
    if mentions_attendance:
        for metric in ("overall_shortage", "i_grade_risk", "r_grade_risk"):
            if metric not in metrics:
                metrics.append(metric)
    if mentions_generic_risk and not metrics:
        metrics.extend(["prediction_high_risk", "overall_shortage", "i_grade_risk", "r_grade_risk"])
    elif mentions_generic_risk and "prediction_high_risk" not in metrics and not mentions_attendance:
        metrics.insert(0, "prediction_high_risk")

    ordered_unique: list[str] = []
    for metric in metrics:
        if metric not in ordered_unique:
            ordered_unique.append(metric)
    return ordered_unique


def _infer_compare_dimension(*, lowered: str, profiles: list[object]) -> str | None:
    dimensions = _detect_compare_dimensions(lowered=lowered, profiles=profiles)
    return dimensions[0] if dimensions else None


def _detect_compare_dimensions(*, lowered: str, profiles: list[object]) -> list[str]:
    dimensions: list[str] = []
    if any(token in lowered for token in {"department", "departments", "branch", "branches"}):
        dimensions.append("branch")
    if any(token in lowered for token in {"gender", "male", "female", "sex"}):
        dimensions.append("gender")
    if any(token in lowered for token in {"age band", "age-band", "age group"}):
        dimensions.append("age_band")
    if "batch" in lowered:
        dimensions.append("batch")
    if any(token in lowered for token in {"program", "programme", "program type", "programme type"}):
        dimensions.append("program_type")
    if any(token in lowered for token in {"region", "urban", "rural"}):
        dimensions.append("region")
    if any(token in lowered for token in {"category", "sc", "obc", "bc"}):
        dimensions.append("category")
    if any(token in lowered for token in {"income", "lpa"}):
        dimensions.append("income")
    branch_mentions = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="branch")
    if len(branch_mentions) > 1 and "branch" not in dimensions:
        dimensions.append("branch")
    gender_mentions = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="gender")
    if len(gender_mentions) > 1 and "gender" not in dimensions:
        dimensions.append("gender")
    age_band_mentions = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="age_band")
    if len(age_band_mentions) > 1 and "age_band" not in dimensions:
        dimensions.append("age_band")
    batch_mentions = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="batch")
    if len(batch_mentions) > 1 and "batch" not in dimensions:
        dimensions.append("batch")
    program_type_mentions = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key="program_type")
    if len(program_type_mentions) > 1 and "program_type" not in dimensions:
        dimensions.append("program_type")
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


def _extract_compare_explicit_values(*, lowered: str, profiles: list[object], compare_dimension: str | None) -> list[str]:
    if compare_dimension in {"branch", "gender", "age_band", "batch", "program_type", "category", "region", "income"}:
        return _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key=str(compare_dimension))
    if compare_dimension == "outcome_status":
        return _extract_outcome_mentions(lowered)
    return []


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


def _looks_like_role_action_request(*, lowered: str, role: str) -> bool:
    if not any(
        phrase in lowered
        for phrase in {
            "what should we do first",
            "what do we do first",
            "what strategy should we take",
            "what strategy should we use",
            "what strategy should we follow",
            "what should our strategy be",
            "what should we do to reduce risk",
            "what should admin do first",
            "what actions should admin take",
            "what should i do first",
            "what do i do first",
            "what should i do as counsellor",
            "what should we focus on first",
            "what should i focus on first",
            "action list",
            "action plan",
            "give improvement plan",
            "give strategic plan",
            "give strategic roadmap",
            "operational priorities",
            "operational actions",
            "how do we reduce this",
            "how can we reduce this",
            "how should we reduce this",
            "how to improve student retention",
            "how can we reduce dropout rate",
            "how to reduce dropout risk",
            "how can we reduce dropout risk",
            "how do we reduce dropout risk",
            "how should we respond",
            "how should i respond",
            "what should we do about this",
            "what should i do about this",
            "what should i do for my students",
            "what should i do for high risk students",
            "what action should i take for high risk students",
            "how can i help them",
            "what intervention should i take",
            "how to reduce their risk",
            "what actions are needed",
            "institution wide",
        }
    ):
        return False
    if any(
        token in lowered
        for token in {
            "which branch",
            "which semester",
            "which region",
            "which category",
            "which income",
            "which gender",
            "which batch",
            "which age band",
            "compare ",
            " versus ",
            " vs ",
            " vs. ",
            "which is worse",
        }
    ):
        return False
    if role == "counsellor":
        return True
    return True


def _looks_like_diagnostic_reasoning_request(*, lowered: str, profiles: list[object]) -> bool:
    if not (_looks_like_comparison_request(lowered=lowered, profiles=profiles) or _looks_like_attention_analysis_request(lowered)):
        return False
    return any(
        token in lowered
        for token in {
            "why",
            "and why",
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
