from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.api.academic_burden import build_academic_burden_summary
from src.api.academic_pressure import build_academic_pressure_snapshot
from src.api.auth import AuthContext
from src.api.copilot_intents import detect_copilot_intent, suggest_copilot_intents
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_response_builder import build_grounded_response
from src.api.copilot_runtime import COPILOT_PLANNER_TOOL_NAME, COPILOT_SYSTEM_PROMPT_VERSION
from src.api.routes.faculty import get_faculty_priority_queue, get_faculty_summary
from src.api.routes.interventions import get_intervention_effectiveness_analytics
from src.api.student_intelligence import build_current_student_intelligence
from src.db.models import StudentAcademicRecord, StudentSubjectAttendanceRecord
from src.db.repository import EventRepository


def generate_grounded_copilot_answer(
    *,
    auth: AuthContext,
    repository: EventRepository,
    message: str,
    session_messages: list[object],
    memory: dict | None = None,
    query_plan: dict | None = None,
) -> tuple[str, list[dict], list[str], dict]:
    planner = query_plan or {}
    execution_message = str(planner.get("normalized_message") or message)
    lowered = execution_message.lower().strip()
    original_lowered = str(planner.get("original_message") or message).lower().strip()
    memory = memory or resolve_copilot_memory_context(
        message=message,
        session_messages=session_messages,
    )
    intent = str(planner.get("primary_intent") or detect_copilot_intent(role=auth.role, message=execution_message))
    if auth.role == "student":
        student_follow_up_intent = _resolve_student_follow_up_intent(
            lowered=lowered,
            last_context=memory.get("last_context") or {},
        )
        if student_follow_up_intent:
            intent = student_follow_up_intent
        elif _looks_like_student_safe_but_high_alert_question(lowered):
            intent = "student_self_subject_risk"

    if auth.role == "admin" and original_lowered in {
        "compare current vs previous term",
        "what is biggest issue overall",
        "what is biggest weakness overall",
        "which branch has improving vs declining performance",
    }:
        planner = {
            **planner,
            "clarification_needed": False,
            "clarification_question": None,
            "default_follow_up_rewrite": None,
            "user_goal": (
                "institution_health_explanation"
                if original_lowered != "compare current vs previous term"
                else planner.get("user_goal") or "unknown"
            ),
            "normalized_message": original_lowered,
        }

    if auth.role == "student" and _looks_like_student_weekly_focus_request(lowered):
        return _answer_student_weekly_focus(
            auth=auth,
            repository=repository,
        )

    if planner.get("refusal_reason") and not (
        auth.role == "student" and _looks_like_false_positive_student_sensitive_refusal(original_lowered)
    ):
        refusal_reason = str(planner.get("refusal_reason"))
        return (
            build_grounded_response(
                opening="I can’t help with that request.",
                key_points=[
                    "I cannot share passwords or secrets.",
                    "I can help with grounded retention analytics, but I can’t reveal secrets, credentials, or protected access data.",
                ],
                tools_used=[{"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Classified the request as a sensitive refusal before tool execution"}],
                limitations=[f"planner refusal: {refusal_reason}"],
            ),
            [{"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Classified the request as a sensitive refusal before tool execution"}],
            [f"planner refusal: {refusal_reason}"],
            {
                "kind": "planner",
                "intent": "planner_refusal",
                "planner_version": str(planner.get("version") or COPILOT_SYSTEM_PROMPT_VERSION),
                "refusal_reason": refusal_reason,
            },
        )

    # ── 4-tier risk listing handler ──────────────────────────────────
    if auth.role in ("admin", "counsellor", "system"):
        tier_match = _detect_risk_tier_listing_request(lowered)
        if tier_match:
            return _answer_risk_tier_listing(
                tier=tier_match,
                auth=auth,
                repository=repository,
            )

    if (
        auth.role == "admin"
        and any(token in lowered for token in {"newly entered risk", "just entered risk", "entered risk lately", "lately"})
        and "risk" in lowered
        and _parse_time_window_days(lowered) is None
    ):
        return (
            build_grounded_response(
                opening="I can answer that, but I need one comparison window first.",
                key_points=[
                    "Which time window should I use for this comparison?",
                    "For example: last 7 days, last 14 days, or last 30 days.",
                ],
                tools_used=[{"tool_name": "admin_intent_router", "summary": "Asked for a time window before resolving a newly-entered-risk admin query"}],
                limitations=["newly-entered risk questions need a comparison window before grounded counting can continue"],
            ),
            [{"tool_name": "admin_intent_router", "summary": "Asked for a time window before resolving a newly-entered-risk admin query"}],
            ["newly-entered risk questions need a comparison window before grounded counting can continue"],
            {"kind": "planner", "intent": "planner_clarification"},
        )

    if planner.get("clarification_needed") and (
        memory.get("is_follow_up")
        or (
            auth.role == "admin"
            and _looks_like_admin_contextual_follow_up(
                lowered=lowered,
                last_context=memory.get("last_context") or {},
            )
        )
    ):
        rescue_profiles: list[object] = []
        if auth.role == "counsellor":
            rescue_profiles = repository.get_imported_student_profiles_for_counsellor_identity(
                subject=auth.subject,
                display_name=auth.display_name,
            )
        elif auth.role == "admin":
            rescue_profiles = repository.get_imported_student_profiles()
        rescue_memory = memory
        if auth.role == "admin" and not memory.get("is_follow_up"):
            rescue_memory = dict(memory)
            rescue_memory["is_follow_up"] = True
            rescue_memory["lowered_message"] = lowered
        clarification_follow_up = _maybe_answer_role_follow_up(
            role=auth.role,
            repository=repository,
            intent=intent,
            memory=rescue_memory,
            profiles=rescue_profiles,
        )
        if clarification_follow_up is not None:
            return clarification_follow_up

    if planner.get("clarification_needed"):
        clarification_question = str(planner.get("clarification_question") or "Can you clarify what you want me to compare or filter?")
        if auth.role == "student":
            return (
                build_grounded_response(
                    opening="I can help with that, but I want to keep the advice useful and specific for you.",
                    key_points=[
                        clarification_question,
                        "You can reply in a short way and I will continue from there.",
                    ],
                    tools_used=[],
                    limitations=[],
                ),
                [{"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Asked the student for one short clarification before continuing"}],
                [],
                {
                    "kind": "planner",
                    "intent": "planner_clarification",
                    "planner_version": str(planner.get("version") or COPILOT_SYSTEM_PROMPT_VERSION),
                    "clarification_question": clarification_question,
                    "default_follow_up_rewrite": str(planner.get("default_follow_up_rewrite") or ""),
                    "source_message": str(planner.get("normalized_message") or execution_message),
                },
            )
        clarification_key_points = [
            "Which time window should I use for this comparison?",
            clarification_question,
            "I will keep the current retention context once you answer, so you do not need to restate the full question.",
        ]
        return (
            build_grounded_response(
                opening="I understood the retention-domain request, but I need one more detail before I run the backend query.",
                key_points=clarification_key_points,
                tools_used=[{"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Structured the query into a CB22 plan and asked for clarification"}],
                limitations=["planner needs one missing detail before grounded tool execution can continue"],
            ),
            [{"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Structured the query into a CB22 plan and asked for clarification"}],
            ["planner needs one missing detail before grounded tool execution can continue"],
            {
                "kind": "planner",
                "intent": "planner_clarification",
                "planner_version": str(planner.get("version") or COPILOT_SYSTEM_PROMPT_VERSION),
                "clarification_question": clarification_question,
                "default_follow_up_rewrite": str(planner.get("default_follow_up_rewrite") or ""),
                "source_message": str(planner.get("normalized_message") or execution_message),
            },
        )

    if auth.role == "student":
        answer, tools_used, limitations, memory_context = _answer_student_question(
            auth=auth,
            repository=repository,
            lowered=lowered,
            intent=intent,
            memory=memory,
        )
        return (
            answer,
            tools_used,
            limitations,
            _enrich_student_memory_context(memory_context=memory_context, lowered=lowered),
        )
    if auth.role == "counsellor":
        answer, tools_used, limitations, memory_context = _answer_counsellor_question(
            auth=auth,
            repository=repository,
            lowered=lowered,
            intent=intent,
            memory=memory,
            query_plan=planner,
        )
        return (
            answer,
            tools_used,
            limitations,
            _enrich_counsellor_memory_context(memory_context=memory_context, lowered=lowered),
        )
    answer, tools_used, limitations, memory_context = _answer_admin_question(
        auth=auth,
        repository=repository,
        lowered=lowered,
        intent=intent,
        memory=memory,
        query_plan=planner,
    )
    return (
        answer,
        tools_used,
        limitations,
        _enrich_admin_memory_context(memory_context=memory_context, lowered=lowered),
    )


_SENSITIVE_REQUEST_TOKENS = {
    "password",
    "passwords",
    "otp",
    "token",
    "tokens",
    "secret",
    "secrets",
    "api key",
    "api keys",
    "credential",
    "credentials",
    "private key",
    "private keys",
    "access key",
    "access keys",
    "session cookie",
    "cookies",
    "bearer token",
    "refresh token",
    "jwt",
    ".env",
    "env file",
    "database password",
    "admin password",
    "root password",
    "hash",
    "hashed",
    "ssn",
    "credit",
    "card",
    "bank",
    "account",
}


def _looks_like_false_positive_student_sensitive_refusal(lowered: str) -> bool:
    if _is_sensitive_request(lowered):
        return False
    return any(
        token in lowered
        for token in {
            "which semester",
            "what semester",
            "current semester",
            "which year am i in",
            "assignment",
            "attendance",
            "risk",
            "lms",
            "erp",
            "finance",
            "gpa",
            "performance",
            "week by week",
            "week-by-week",
            "second week",
        }
    )


def _looks_like_student_weekly_focus_request(lowered: str) -> bool:
    focus_phrases = (
        "what should i focus on first this week",
        "what should i focus on this week",
        "what should i focus on first",
        "what do i focus on first this week",
        "what do i focus on first",
        "what should i focus on next week",
        "what should i focus on 2nd week",
        "what should i focus on second week",
        "can you plan my next few weeks",
        "plan my routine for next few weeks",
        "which students need attention first this week",
        "which students need attention first",
    )
    return any(phrase in lowered for phrase in focus_phrases)


def _looks_like_student_coursework_metric_request(lowered: str) -> bool:
    metric_tokens = {"rate", "submission", "submissions", "assignment", "assignments", "coursework", "lms"}
    return (
        any(token in lowered for token in {"assignment", "submission", "coursework"})
        and any(token in lowered for token in metric_tokens)
    )


def _looks_like_student_lms_request(lowered: str) -> bool:
    return "lms" in lowered or (
        any(token in lowered for token in {"activity", "engagement", "clicks", "resources"})
        and any(token in lowered for token in {"my", "current", "latest", "details", "activity"})
    )


def _looks_like_student_erp_request(lowered: str) -> bool:
    return "erp" in lowered or any(
        token in lowered
        for token in {
            "weighted score",
            "late submissions",
            "completed assessments",
            "erp score",
            "erp data",
            "erp details",
            "erp activity",
            "gpa",
            "cgpa",
            "grade point",
            "academic performance",
            "performance",
            "marks",
            "progress",
        }
    )


def _looks_like_student_finance_request(lowered: str) -> bool:
    return any(
        token in lowered
        for token in {
            "finance",
            "financial",
            "payment status",
            "fee status",
            "fee delay",
            "overdue amount",
            "fees",
            "dues",
            "dues status",
        }
    )


def _looks_like_student_semester_position_request(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in {
            "which semester i am in",
            "which semester am i in",
            "what semester am i in",
            "which semester am i in right now",
            "what semester am i in right now",
            "current semester",
            "which year am i in",
            "what year am i in",
        }
    )


def _looks_like_student_assignment_total_request(lowered: str) -> bool:
    return (
        any(token in lowered for token in {"assignment", "assignments", "assessment", "assessments"})
        and any(token in lowered for token in {"total", "needed", "need", "required"})
        and any(token in lowered for token in {"submitted", "submit", "completed", "done"})
    )


def _looks_like_student_finance_vs_performance_question(lowered: str) -> bool:
    return (
        any(token in lowered for token in {"finance", "fee", "payment", "dues"})
        and any(token in lowered for token in {"performance", "marks", "results", "gpa", "cgpa", "risk"})
        and any(token in lowered for token in {"affecting", "impact", "hurting", "helping", "why"})
    )


def _extract_requested_student_plan_week(lowered: str) -> int | None:
    if any(phrase in lowered for phrase in {"second week", "2nd week", "week 2"}):
        return 2
    if any(phrase in lowered for phrase in {"third week", "3rd week", "week 3"}):
        return 3
    if any(phrase in lowered for phrase in {"fourth week", "4th week", "week 4"}):
        return 4
    if any(phrase in lowered for phrase in {"first week", "1st week", "week 1"}):
        return 1
    return None


def _looks_like_student_multi_week_plan_request(lowered: str) -> bool:
    return _extract_requested_student_plan_week(lowered) is not None or any(
        phrase in lowered
        for phrase in {
            "week by week",
            "week-by-week",
            "weekly plan",
            "week wise plan",
            "week-wise plan",
            "week by week plan",
        }
    )


def _looks_like_student_seriousness_question(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in {
            "should i panic",
            "should i be worried",
            "should i worry",
            "am i safe or should i worry",
            "am i in danger",
            "am i in trouble",
            "how serious is my situation",
            "how serious is it",
        }
    )


def _looks_like_student_label_reduction_follow_up(lowered: str, last_context: dict) -> bool:
    pending_follow_up = str(last_context.get("pending_student_follow_up") or "").strip().lower()
    if pending_follow_up != "risk_label_reduction_explanation":
        return False
    normalized = re.sub(r"[^\w\s]", " ", lowered).strip()
    normalized = " ".join(normalized.split())
    return normalized in {
        "ok",
        "okay",
        "ok give",
        "give",
        "ok tell",
        "tell",
        "tell me",
        "yes",
        "yes tell me",
        "go on",
        "continue",
        "proceed",
        "explain",
    }


def _classify_student_query(*, lowered: str, last_context: dict) -> dict[str, object]:
    if _looks_like_student_semester_position_request(lowered):
        return {"topic": "semester_position", "mode": "data"}
    if _looks_like_student_assignment_total_request(lowered):
        return {"topic": "assignment_totals", "mode": "data"}
    if _looks_like_student_finance_vs_performance_question(lowered):
        return {"topic": "finance_vs_performance", "mode": "explanation"}
    if _looks_like_student_label_reduction_follow_up(lowered, last_context):
        return {"topic": "label_reduction", "mode": "explanation"}
    if _looks_like_student_multi_week_plan_request(lowered):
        return {
            "topic": "multi_week_plan",
            "mode": "plan",
            "week": _extract_requested_student_plan_week(lowered),
        }
    if _looks_like_student_seriousness_question(lowered):
        return {"topic": "seriousness", "mode": "explanation"}
    return {"topic": "generic", "mode": "generic", "week": _extract_requested_student_plan_week(lowered)}


def _looks_like_counsellor_natural_priority_request(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in {
            "who needs attention",
            "which students are struggling",
            "any critical cases",
            "who should i focus on",
            "which students are not doing well",
            "who is in trouble",
            "who needs urgent help",
            "who is in serious condition",
            "which student should i prioritize",
            "top 5 risky students",
            "give me most critical students",
            "who are worst performing",
        }
    )


def _looks_like_counsellor_factor_reasoning_request(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in {
            "why are many students struggling",
            "what is main issue in my students",
            "what is main problem in my students",
            "why are they performing poorly",
            "what is biggest issue across my students",
            "which factor is affecting most students",
            "which group is performing worst",
            "which department has more risk",
            "are my students improving",
            "is risk increasing in my group",
            "should i worry about my group",
            "are things getting worse",
            "which student will fail",
        }
    )


def _looks_like_counsellor_fresh_filter_request(lowered: str) -> bool:
    if not (lowered.startswith("only ") or lowered.startswith("show only ")):
        return False
    return any(
        token in lowered
        for token in {
            "cse",
            "ece",
            "eee",
            "final year",
            "1st year",
            "2nd year",
            "3rd year",
            "4th year",
            "high risk",
            "low attendance",
            "low assignments",
            "students",
        }
    )


def _classify_counsellor_query(*, lowered: str, last_context: dict) -> dict[str, str]:
    if _looks_like_counsellor_fresh_filter_request(lowered):
        return {"topic": "fresh_filter", "mode": "data"}
    if _looks_like_counsellor_natural_priority_request(lowered):
        return {"topic": "priority", "mode": "data"}
    if _looks_like_counsellor_factor_reasoning_request(lowered):
        return {"topic": "factor_reasoning", "mode": "explanation"}
    if (
        str(last_context.get("pending_role_follow_up") or "").strip().lower() == "student_specific_action"
        and _looks_like_generic_progression_follow_up(lowered)
    ):
        return {"topic": "student_action_follow_up", "mode": "action"}
    return {"topic": "generic", "mode": "generic"}


def _looks_like_admin_institution_health_request(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in {
            "how is overall performance",
            "is everything going well",
            "which area is problematic",
            "are students doing okay",
            "is the situation under control",
            "what is biggest issue overall",
            "what is biggest weakness overall",
            "what is most critical area",
            "is situation critical",
            "are we in danger",
            "should we be worried",
            "is performance normal",
            "which factor impacts performance most",
            "which factor is affecting students most",
            "which factor affects most students",
            "hidden risk across departments",
            "which branch has good attendance but high risk",
            "which branch has improving vs declining performance",
        }
    )


def _looks_like_admin_fresh_grouped_request(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in {
            "branch wise risk",
            "risk by department",
            "risk by year",
            "year wise performance",
            "performance by branch",
            "branch wise student count",
            "number of students per department",
            "compare cse vs ece",
            "compare 1st year vs final year",
            "compare attendance and risk across branches",
            "show risk distribution",
            "how many low medium high risk students",
        }
    )


def _looks_like_admin_strategy_or_consequence_request(lowered: str) -> bool:
    if _looks_like_role_operational_request(lowered):
        return True
    return any(
        phrase in lowered
        for phrase in {
            "what if we don't act",
            "what if we dont act",
            "what if no action is taken",
            "can situation get worse",
            "what is worst case scenario",
            "how fast should we act",
            "can we recover in 1 semester",
            "what is realistic timeline",
            "give full solution plan",
            "give detailed plan",
        }
    )


def _classify_admin_query(*, lowered: str, last_context: dict) -> dict[str, str]:
    if _looks_like_admin_fresh_grouped_request(lowered):
        return {"topic": "fresh_grouped", "mode": "data"}
    if _looks_like_admin_institution_health_request(lowered):
        return {"topic": "institution_health", "mode": "explanation"}
    if _looks_like_admin_strategy_or_consequence_request(lowered):
        return {"topic": "strategy", "mode": "action"}
    if (
        str(last_context.get("pending_role_follow_up") or "").strip().lower() == "operational_actions"
        and _looks_like_generic_progression_follow_up(lowered)
    ):
        return {"topic": "strategy_follow_up", "mode": "action"}
    return {"topic": "generic", "mode": "generic"}


def _looks_like_affirmative_student_follow_up(lowered: str) -> bool:
    affirmative_phrases = {
        "yes",
        "yes do it",
        "do it",
        "yes please",
        "please do it",
        "break it down",
        "yes break it down",
        "break it down for me",
        "can you break it down",
    }
    normalized = re.sub(r"[^\w\s]", " ", lowered).strip()
    normalized = " ".join(normalized.split())
    return normalized in affirmative_phrases


def _looks_like_generic_progression_follow_up(lowered: str) -> bool:
    normalized = re.sub(r"[^\w\s]", " ", lowered).strip()
    normalized = " ".join(normalized.split())
    generic_follow_ups = {
        "yes",
        "yeah",
        "yep",
        "ok",
        "okay",
        "ok give",
        "okay give",
        "ok tell",
        "okay tell",
        "ok tell me",
        "okay tell me",
        "tell",
        "tell me",
        "yes tell",
        "yes tell me",
        "go on",
        "continue",
        "proceed",
        "then",
        "more",
        "and then",
        "so",
        "so what",
        "what next",
        "next steps",
        "what now",
        "what about that",
        "what should i do for them",
        "how can i fix it",
        "give solution plan",
        "how to prioritize students",
        "how fast should i act",
        "what is best strategy",
        "give weekly plan",
        "what does that mean",
        "explain that",
        "explain it",
        "sure",
        "alright",
        "all right",
    }
    return normalized in generic_follow_ups


def _student_response_type_for_context(*, memory_context: dict, lowered: str) -> str:
    intent = str(memory_context.get("intent") or "").strip().lower()
    if intent in {
        "student_self_plan",
        "student_weekly_focus",
        "student_weekly_focus_breakdown",
        "student_recovery_focus",
        "student_day_by_day_plan",
        "student_multi_week_plan",
    }:
        return "action"
    if intent in {
        "student_finance_vs_performance",
        "student_seriousness_check",
        "student_label_reduction_explanation",
    }:
        return "explanation"
    if intent in {"student_semester_position", "student_assignment_totals"}:
        return "data"
    if intent == "student_self_risk":
        if any(
            token in lowered
            for token in {
                "why",
                "reason",
                "cause",
                "caused",
                "because",
                "hurting",
                "helping",
                "affecting",
                "impact",
                "attendance is good",
                "attendance is safe",
                "attendance looks good",
                "attendance looks safe",
                "good attendance",
                "safe attendance",
                "trouble",
                "worried",
                "worry",
                "danger",
                "serious",
                "bad",
                "panic",
                "fail",
                "safe academically",
                "doing good",
                "performing",
                "performance okay",
                "improving",
                "getting worse",
            }
        ):
            return "explanation"
        return "data"
    if intent == "student_self_subject_risk":
        return "explanation"
    if intent == "student_self_attendance":
        if any(
            token in lowered
            for token in {
                "why",
                "hurting",
                "helping",
                "affecting",
                "impact",
            }
        ):
            return "explanation"
        return "data"
    if intent in {"student_self_warning", "student_self_profile", "help", "identity"}:
        return "data"
    return "data"


def _student_topic_for_context(*, memory_context: dict, lowered: str) -> str:
    intent = str(memory_context.get("intent") or "").strip().lower()
    if intent == "student_self_attendance":
        if _looks_like_student_lms_request(lowered):
            return "lms"
        if _looks_like_student_erp_request(lowered) or _looks_like_student_coursework_metric_request(lowered):
            return "coursework"
        if _looks_like_student_finance_request(lowered):
            return "finance"
        return "attendance"
    if intent == "student_semester_position":
        return "semester_position"
    if intent == "student_assignment_totals":
        return "coursework"
    if intent == "student_finance_vs_performance":
        return "finance"
    if intent == "student_seriousness_check":
        return "risk"
    if intent == "student_label_reduction_explanation":
        return "recovery"
    if intent == "student_multi_week_plan":
        return "recovery_plan"
    if intent == "student_self_risk":
        if _looks_like_student_lms_request(lowered):
            return "lms_risk"
        if _looks_like_student_finance_request(lowered):
            return "finance_risk"
        return "risk"
    if intent == "student_self_subject_risk":
        if any(token in lowered for token in {"end sem", "end-sem", "eligible"}):
            return "eligibility"
        if any(token in lowered for token in {"i grade", "r grade", "uncleared", "older sem"}):
            return "academic_burden"
        return "attendance_territory"
    if intent in {"student_self_plan", "student_weekly_focus", "student_weekly_focus_breakdown", "student_recovery_focus", "student_day_by_day_plan"}:
        if any(token in lowered for token in {"day by day", "day-by-day", "daily plan"}):
            return "day_by_day_recovery"
        if any(token in lowered for token in {"recover", "recovery", "high alert", "high risk", "improve"}):
            return "recovery_actions"
        return "student_actions"
    if intent == "student_self_warning":
        return "warning"
    if intent == "student_self_profile":
        return "profile"
    return intent or "student"


def _enrich_student_memory_context(*, memory_context: dict, lowered: str) -> dict:
    enriched = dict(memory_context or {})
    intent = str(enriched.get("intent") or "").strip().lower()
    if not intent:
        return enriched
    enriched["last_intent"] = intent
    enriched["response_type"] = _student_response_type_for_context(memory_context=enriched, lowered=lowered)
    enriched["last_topic"] = _student_topic_for_context(memory_context=enriched, lowered=lowered)
    return enriched


def _counsellor_response_type_for_context(*, memory_context: dict, lowered: str) -> str:
    intent = str(memory_context.get("intent") or "").strip().lower()
    if intent == "counsellor_priority_follow_up":
        if any(
            token in lowered
            for token in {
                "focus on",
                "priority first",
                "what should i do first",
                "what do i do first",
            }
        ):
            return "action"
        if any(
            token in lowered
            for token in {
                "why",
                "cause",
                "causing",
                "driver",
                "drivers",
                "reason",
                "because",
                "serious",
                "urgent",
                "critical",
            }
        ):
            return "explanation"
        return "data"
    if intent in {
        "counsellor_student_action_plan",
        "counsellor_operational_actions",
        "counsellor_role_action_plan",
    }:
        return "action"
    if intent in {
        "counsellor_student_reasoning",
        "grouped_risk_breakdown",
        "comparison_summary",
        "attention_analysis_summary",
        "diagnostic_comparison_summary",
        "counsellor_risky_subset_compare",
    }:
        return "explanation"
    if intent in {"counsellor_active_burden_monitoring"}:
        return "data"
    if intent in {
        "counsellor_assigned_students",
        "counsellor_high_risk_students",
        "counsellor_branch_pressure",
        "counsellor_semester_pressure",
        "counsellor_i_grade_summary",
        "counsellor_r_grade_summary",
        "counsellor_attendance_pressure_summary",
        "cohort_summary",
    }:
        if any(
            token in lowered
            for token in {
                "why",
                "cause",
                "causing",
                "driver",
                "drivers",
                "reason",
                "because",
                "main issue",
                "main problem",
                "biggest issue",
                "struggling",
                "performing poorly",
                "not doing well",
                "getting worse",
                "improving",
                "increasing in my group",
                "department has more risk",
                "more risk",
                "worry",
                "should i worry",
                "fail",
                "will fail",
                "fail if ignored",
                "worst",
                "serious",
            }
        ):
            return "explanation"
        return "data"
    return "data"


def _counsellor_topic_for_context(*, memory_context: dict, lowered: str) -> str:
    intent = str(memory_context.get("intent") or "").strip().lower()
    if intent in {"counsellor_assigned_students"}:
        return "assigned_students"
    if intent in {"counsellor_high_risk_students", "counsellor_priority_follow_up"}:
        return "high_risk_students"
    if intent in {"counsellor_i_grade_summary"}:
        return "i_grade_risk"
    if intent in {"counsellor_r_grade_summary"}:
        return "r_grade_risk"
    if intent in {"counsellor_active_burden_monitoring"}:
        return "academic_burden_monitoring"
    if intent in {"counsellor_branch_pressure"}:
        return "branch_pressure"
    if intent in {"counsellor_semester_pressure"}:
        return "semester_pressure"
    if intent in {"counsellor_attendance_pressure_summary"}:
        return "attendance_pressure"
    if intent in {"counsellor_student_reasoning"}:
        return "student_reasoning"
    if intent in {"counsellor_student_action_plan"}:
        return "student_actions"
    if intent in {"counsellor_operational_actions", "counsellor_role_action_plan"}:
        return "cohort_actions"
    if intent in {"counsellor_role_action_plan"}:
        return "cohort_actions"
    if intent in {"grouped_risk_breakdown"}:
        grouping = list(memory_context.get("grouping") or [])
        if grouping:
            return f"grouped_{'_'.join(str(item) for item in grouping)}"
        return "grouped_risk"
    if intent in {"comparison_summary", "attention_analysis_summary", "diagnostic_comparison_summary"}:
        return "grouped_comparison"
    if intent in {"cohort_summary"}:
        if "attendance" in lowered or "subject" in lowered:
            return "attendance_pressure"
        return "cohort_summary"
    return intent or "counsellor"


def _enrich_counsellor_memory_context(*, memory_context: dict, lowered: str) -> dict:
    enriched = dict(memory_context or {})
    intent = str(enriched.get("intent") or "").strip().lower()
    if not intent:
        return enriched
    enriched["last_intent"] = intent
    enriched["response_type"] = str(enriched.get("response_type") or "").strip().lower() or _counsellor_response_type_for_context(
        memory_context=enriched,
        lowered=lowered,
    )
    enriched["last_topic"] = str(enriched.get("last_topic") or "").strip() or _counsellor_topic_for_context(
        memory_context=enriched,
        lowered=lowered,
    )
    return enriched


def _admin_response_type_for_context(*, memory_context: dict, lowered: str) -> str:
    intent = str(memory_context.get("intent") or "").strip().lower()
    if intent in {
        "admin_operational_actions",
        "admin_subset_action_follow_up",
    }:
        return "action"
    if intent in {
        "grouped_risk_breakdown",
        "comparison_summary",
        "attention_analysis_summary",
        "diagnostic_comparison_summary",
        "risk_layer_difference",
        "institution_health_explanation",
        "filtered_branch_explanation",
        "admin_subset_reasoning_follow_up",
    }:
        return "explanation"
    if intent in {
        "admin_governance",
        "admin_priority_queue_summary",
        "admin_branch_attention_summary",
        "admin_semester_attention_summary",
        "admin_i_grade_summary",
        "admin_r_grade_summary",
        "admin_attendance_pressure_summary",
        "cohort_summary",
        "import_coverage",
        "identity",
        "help",
    }:
        if any(
            token in lowered
            for token in {
                "why",
                "cause",
                "causing",
                "driver",
                "drivers",
                "reason",
                "because",
            }
        ):
            return "explanation"
        return "data"
    return "data"


def _admin_topic_for_context(*, memory_context: dict, lowered: str) -> str:
    intent = str(memory_context.get("intent") or "").strip().lower()
    if intent in {"admin_operational_actions"}:
        return "institution_actions"
    if intent in {"admin_priority_queue_summary"}:
        return "priority_queue"
    if intent in {"cohort_recent_entry"}:
        return "trend"
    if intent in {"admin_branch_attention_summary"}:
        return "branch_attention"
    if intent in {"admin_semester_attention_summary"}:
        return "semester_attention"
    if intent in {"admin_i_grade_summary"}:
        return "i_grade_risk"
    if intent in {"admin_r_grade_summary"}:
        return "r_grade_risk"
    if intent in {"admin_attendance_pressure_summary"}:
        return "attendance_pressure"
    if intent in {"grouped_risk_breakdown"}:
        grouping = list(memory_context.get("grouping") or [])
        if not grouping:
            grouped_by = str(memory_context.get("grouped_by") or "").strip()
            if grouped_by:
                grouping = [grouped_by]
        if grouping:
            return f"grouped_{'_'.join(str(item) for item in grouping)}"
        return "grouped_risk"
    if intent in {"comparison_summary"}:
        return "comparison"
    if intent in {"attention_analysis_summary"}:
        return "attention_analysis"
    if intent in {"diagnostic_comparison_summary"}:
        return "diagnostic_comparison"
    if intent in {"risk_layer_difference"}:
        return "risk_layers"
    if intent in {"admin_governance"}:
        if "trend" in lowered:
            return "trend"
        if "subject" in lowered or "attendance" in lowered:
            return "attendance_pressure"
        if "strategy" in lowered or "reduce" in lowered or "what should we do" in lowered:
            return "institution_actions"
        return "governance"
    if intent in {"institution_health_explanation"}:
        return "institution_health"
    if intent in {"filtered_branch_explanation"}:
        return "branch_attention"
    if intent in {"institution_report"}:
        return "institution_report"
    if intent in {"cohort_summary"}:
        if "trend" in lowered or "entered risk" in lowered:
            return "trend"
        if "subject" in lowered or "attendance" in lowered:
            return "attendance_pressure"
        return "institution_risk"
    if intent in {"import_coverage"}:
        return "import_coverage"
    return intent or "admin"


def _enrich_admin_memory_context(*, memory_context: dict, lowered: str) -> dict:
    enriched = dict(memory_context or {})
    intent = str(enriched.get("intent") or "").strip().lower()
    if not intent:
        return enriched
    enriched["last_intent"] = intent
    enriched["response_type"] = _admin_response_type_for_context(memory_context=enriched, lowered=lowered)
    enriched["last_topic"] = _admin_topic_for_context(memory_context=enriched, lowered=lowered)
    return enriched


def _looks_like_role_operational_request(lowered: str) -> bool:
    normalized = re.sub(r"[^\w\s]", " ", lowered).strip()
    normalized = " ".join(normalized.split())
    explicit_phrases = {
        "what should we do first",
        "what do we do first",
        "what should admin do first",
        "what should i do first",
        "what do i do first",
        "what should i do as counsellor",
        "what should we focus on first",
        "what should i focus on first",
        "what next",
        "next steps",
        "what now",
        "action list",
        "action plan",
        "operational priorities",
        "operational actions",
        "what strategy should we follow",
        "what actions should admin take",
        "give improvement plan",
        "give strategic plan",
        "give strategic roadmap",
        "which branch needs urgent attention",
        "which group needs immediate attention",
        "which branch should we prioritize",
        "where should we focus",
        "where should we take action first",
    }
    if normalized in explicit_phrases:
        return True
    return any(
        phrase in normalized
        for phrase in {
            "how do we reduce this",
            "how can we reduce this",
            "how should we reduce this",
            "what should we do to reduce risk",
            "how to improve student retention",
            "how can we reduce dropout rate",
            "how should we respond",
            "how should i respond",
            "what should we do about this",
            "what should i do about this",
            "what should admin do about this",
            "what should i do for my students",
        }
    )


def _should_continue_role_operational_actions(
    *,
    lowered: str,
    memory: dict,
    last_context: dict,
) -> bool:
    if _looks_like_role_operational_request(lowered):
        return True
    if not _looks_like_generic_progression_follow_up(lowered):
        return False
    if str(last_context.get("pending_role_follow_up") or "").strip().lower() == "operational_actions":
        return True
    return str(last_context.get("intent") or "").strip().lower() in {
        "grouped_risk_breakdown",
        "attention_analysis_summary",
        "diagnostic_comparison_summary",
        "comparison_summary",
        "cohort_summary",
        "institution_health_explanation",
        "grouped_bucket_focus_follow_up",
        "admin_subset_reasoning_follow_up",
        "admin_subset_action_follow_up",
        "admin_subset_priority_follow_up",
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


def _looks_like_admin_contextual_follow_up(*, lowered: str, last_context: dict) -> bool:
    lowered = str(lowered or "").strip().lower()
    if not lowered:
        return False
    if str(last_context.get("role_scope") or "").strip().lower() != "admin" and str(last_context.get("kind") or "").strip().lower() != "import_coverage":
        return False
    follow_up_tokens = {
        "only ",
        "compare with",
        "break it by",
        "why",
        "cause",
        "factor",
        "affecting",
        "what should we",
        "what actions should we",
        "how to fix",
        "how fast",
        "timeline",
        "how long",
        "what if",
        "situation get worse",
        "worst case",
        "recover in",
        "realistic timeline",
        "strategic plan",
        "strategic roadmap",
        "detailed plan",
        "solution plan",
        "full solution plan",
        "urgent attention",
        "improvement",
        "what next",
        "then",
        "continue",
        "more",
        "ok",
        "okay",
        "explain",
    }
    return any(token in lowered for token in follow_up_tokens)


def _resolve_student_follow_up_intent(*, lowered: str, last_context: dict) -> str | None:
    pending_follow_up = str(last_context.get("pending_student_follow_up") or "").strip().lower()
    if pending_follow_up == "coursework_consequence_follow_up" and any(
        token in lowered
        for token in {
            "will my risk increase",
            "will risk increase",
            "by how much",
        }
    ):
        return "student_self_subject_risk"
    if not _looks_like_generic_progression_follow_up(lowered):
        return None
    if not pending_follow_up:
        last_intent = str(last_context.get("intent") or "").strip().lower()
        last_response_type = str(last_context.get("response_type") or "").strip().lower()
        if last_intent == "student_self_attendance":
            pending_follow_up = "attendance_territory"
        elif last_intent == "student_self_subject_risk":
            pending_follow_up = "student_action_list"
        elif last_intent == "student_self_risk":
            pending_follow_up = "risk_explanation_continuation" if last_response_type == "data" else "student_action_list"
        elif last_intent == "student_weekly_focus":
            pending_follow_up = "weekly_focus_breakdown"
        else:
            return None
    if pending_follow_up == "attendance_territory":
        return "student_self_subject_risk"
    if pending_follow_up == "finance_risk_explanation":
        return "student_self_risk"
    if pending_follow_up == "lms_risk_explanation":
        return "student_self_risk"
    if pending_follow_up == "coursework_risk_explanation":
        return "student_self_risk"
    if pending_follow_up == "risk_explanation_continuation":
        return "student_self_subject_risk"
    if pending_follow_up == "student_action_list":
        return "student_self_plan"
    if pending_follow_up == "weekly_focus_breakdown":
        return "student_self_plan"
    if pending_follow_up == "day_by_day_plan":
        return "student_self_plan"
    if pending_follow_up == "risk_label_reduction_explanation":
        return "student_self_plan"
    if pending_follow_up == "assignment_sufficiency_follow_up":
        return "student_self_subject_risk"
    return None


def _detect_student_plan_focus(*, lowered: str, last_context: dict) -> str:
    normalized = re.sub(r"[^\w\s]", " ", lowered).strip()
    normalized = " ".join(normalized.split())
    pending_follow_up = str(last_context.get("pending_student_follow_up") or "").strip().lower()
    requested_week = _extract_requested_student_plan_week(lowered)

    if pending_follow_up == "day_by_day_plan" and normalized in {
        "yes",
        "yeah",
        "yep",
        "ok",
        "okay",
        "continue",
        "go on",
        "then",
        "proceed",
        "tell me",
        "tell",
        "sure",
        "alright",
        "all right",
    }:
        return "day_by_day"
    if pending_follow_up == "risk_label_reduction_explanation" and normalized in {
        "yes",
        "yeah",
        "yep",
        "ok",
        "okay",
        "continue",
        "go on",
        "then",
        "proceed",
        "tell me",
        "tell",
        "sure",
        "alright",
        "all right",
    }:
        return "label_reduction"
    if pending_follow_up == "risk_label_reduction_explanation" and normalized in {
        "ok give",
        "okay give",
        "ok tell",
        "ok tell me",
        "tell me",
        "tell",
        "give",
        "yes tell me",
    }:
        return "label_reduction"
    if _looks_like_student_multi_week_plan_request(lowered):
        return f"week_{requested_week}" if requested_week else "multi_week"
    if any(
        phrase in lowered
        for phrase in {
            "day by day",
            "day-by-day",
            "daily plan",
            "plan for the week",
            "week plan",
        }
    ):
        return "day_by_day"
    if any(
        phrase in normalized
        for phrase in {
            "overall recovery priorities",
            "recovery priorities",
            "top priority",
            "most important",
            "priority order",
            "priority list",
        }
    ):
        return "priorities"
    if any(
        phrase in normalized
        for phrase in {
            "overall recovery priorities",
            "recover from high alert",
            "recover from high risk",
            "remove the high label",
            "remove high label",
            "reduce my risk",
            "lower my risk",
            "come out of high alert",
            "get out of high alert",
            "remove the high risk label",
            "remove the high alert label",
        }
    ):
        return "recovery"
    if any(
        phrase in normalized
        for phrase in {
            "attendance priorities",
            "attendance focus",
            "focus on attendance",
        }
    ):
        return "attendance"
    if any(
        phrase in normalized
        for phrase in {
            "how to improve assignments",
            "improve assignments",
            "assignment priorities",
            "coursework priorities",
            "coursework focus",
            "focus on coursework",
            "submission priorities",
        }
    ):
        return "coursework"
    if pending_follow_up == "student_action_list":
        return "recovery"
    if pending_follow_up == "coursework_risk_explanation":
        return "recovery"
    if pending_follow_up == "weekly_focus_breakdown":
        return "breakdown"
    return "generic"


def _looks_like_student_safe_but_high_alert_question(lowered: str) -> bool:
    has_attendance_language = any(
        token in lowered
        for token in {
            "attendance",
            "safe mode",
            "safe status",
            "safe",
            "good attendance",
            "attendance is good",
            "attendance looks good",
            "attendance okay",
            "attendance ok",
        }
    )
    has_risk_language = any(
        token in lowered
        for token in {
            "high alert",
            "high risk",
            "high warning",
            "put into high",
            "why i have been put",
            "why am i high",
            "why high",
            "why risk",
            "still risk",
            "still risky",
            "still at risk",
            "why am i risky",
            "why am i at risk",
            "why risk then",
        }
    )
    wants_explanation = any(
        token in lowered
        for token in {
            "why",
            "how come",
            "then why",
            "but why",
        }
    )
    return has_attendance_language and has_risk_language and wants_explanation


def _load_student_signal_bundle(*, repository: EventRepository, student_id: int) -> dict:
    latest_prediction = repository.get_latest_prediction_for_student(student_id)
    prediction_history = repository.get_prediction_history_for_student(student_id)
    lms_events = repository.get_lms_events_for_student(student_id)
    latest_erp_event = repository.get_latest_erp_event(student_id)
    erp_history = repository.get_erp_event_history_for_student(student_id)
    latest_finance_event = repository.get_latest_finance_event(student_id)
    finance_history = repository.get_finance_event_history_for_student(student_id)
    intelligence = None
    if latest_prediction is not None and lms_events and latest_erp_event is not None:
        try:
            intelligence = build_current_student_intelligence(
                prediction_rows=prediction_history,
                latest_prediction=latest_prediction,
                lms_events=lms_events,
                erp_event=latest_erp_event,
                erp_history=erp_history,
                finance_event=latest_finance_event,
                finance_history=finance_history,
                previous_prediction=prediction_history[1] if len(prediction_history) >= 2 else None,
            )
        except Exception:
            intelligence = None
    return {
        "latest_prediction": latest_prediction,
        "prediction_history": prediction_history,
        "lms_events": lms_events,
        "latest_erp_event": latest_erp_event,
        "erp_history": erp_history,
        "latest_finance_event": latest_finance_event,
        "finance_history": finance_history,
        "intelligence": intelligence,
    }


def _format_risk_type_label(primary_type: str | None) -> str:
    mapping = {
        "academic_decline": "academic decline",
        "attendance_driven": "attendance pressure",
        "engagement_drop": "engagement drop",
        "finance_driven": "finance pressure",
        "multi_factor_risk": "multi-factor risk",
        "stable_profile": "stable profile",
    }
    return mapping.get(str(primary_type or "").strip(), str(primary_type or "mixed profile").replace("_", " "))


def _build_student_data_inventory_points(
    *,
    signal_bundle: dict,
    has_warning_history: bool,
    has_attendance_foundation: bool,
) -> list[str]:
    points: list[str] = []
    prediction = signal_bundle.get("latest_prediction")
    intelligence = signal_bundle.get("intelligence") or {}
    lms_events = signal_bundle.get("lms_events") or []
    latest_erp_event = signal_bundle.get("latest_erp_event")
    latest_finance_event = signal_bundle.get("latest_finance_event")
    if prediction is not None:
        points.append(
            f"Prediction data is available: latest risk probability {float(prediction.final_risk_probability):.4f} with class "
            f"{'HIGH' if int(prediction.final_predicted_class) == 1 else 'LOW'}."
        )
    else:
        points.append("Prediction data is not available yet.")
    if has_attendance_foundation:
        points.append("Attendance foundation data is available, including overall semester and subject-wise attendance.")
    else:
        points.append("Attendance foundation data is not available yet.")
    if lms_events:
        lms_summary = intelligence.get("lms_summary") or {}
        if lms_summary:
            points.append(
                f"LMS engagement data is available: {int(lms_summary.get('lms_clicks_7d', 0) or 0)} clicks in the last 7 days and "
                f"{int(lms_summary.get('lms_unique_resources_7d', 0) or 0)} unique resources touched."
            )
        else:
            points.append("LMS engagement data is available.")
    else:
        points.append("LMS engagement data is not available yet.")
    if latest_erp_event is not None:
        points.append(
            f"ERP academic-performance data is available: submission rate {float(getattr(latest_erp_event, 'assessment_submission_rate', 0.0) or 0.0):.2f}, "
            f"weighted score {float(getattr(latest_erp_event, 'weighted_assessment_score', 0.0) or 0.0):.1f}."
        )
    else:
        points.append("ERP academic-performance data is not available yet.")
    if latest_finance_event is not None:
        payment_status = str(getattr(latest_finance_event, "payment_status", None) or "not available")
        delay_days = int(getattr(latest_finance_event, "fee_delay_days", 0) or 0)
        overdue_amount = float(getattr(latest_finance_event, "fee_overdue_amount", 0.0) or 0.0)
        points.append(
            f"Finance context is available: payment status {payment_status}, delay {delay_days} day(s), overdue amount {overdue_amount:.2f}."
        )
    else:
        points.append("Finance context is not available yet.")
    if has_warning_history:
        points.append("Warning and support-workflow history is available for your record.")
    return points


def _build_cross_signal_reasoning_points(
    *,
    signal_bundle: dict,
    current_semester_progress=None,
    include_availability_gap: bool = False,
    include_reconciliation_notice: bool = True,
    include_stability: bool = True,
    include_triggers: bool = True,
) -> list[str]:
    intelligence = signal_bundle.get("intelligence")
    if not intelligence:
        if not include_availability_gap:
            return []
        missing_bits: list[str] = []
        if not signal_bundle.get("lms_events"):
            missing_bits.append("LMS")
        if signal_bundle.get("latest_erp_event") is None:
            missing_bits.append("ERP")
        if signal_bundle.get("latest_prediction") is None:
            missing_bits.append("prediction")
        if missing_bits:
            return [
                "Cross-signal reasoning is limited right now because some live signal families are missing: "
                + ", ".join(missing_bits)
                + "."
            ]
        return []

    points: list[str] = []
    prediction = signal_bundle.get("latest_prediction")
    risk_type = intelligence.get("risk_type") or {}
    risk_summary = str(risk_type.get("summary") or "").strip()
    primary_type = _format_risk_type_label(risk_type.get("primary_type"))
    if current_semester_progress is not None and prediction is not None:
        overall_status = str(getattr(current_semester_progress, "overall_status", "") or "").upper()
        predicted_high = int(getattr(prediction, "final_predicted_class", 0)) == 1
        if include_reconciliation_notice and overall_status == "SAFE" and predicted_high:
            points.append(
                "These signals are not contradictory: attendance currently looks SAFE, but broader non-attendance signals are still keeping the model risk high."
            )
    if risk_summary:
        points.append(f"Dominant cross-signal explanation: {risk_summary}")
    else:
        points.append(f"Dominant cross-signal explanation: the current pattern is mainly {primary_type}.")

    drivers = intelligence.get("drivers") or []
    if drivers:
        points.append(
            "Strongest current drivers: "
            + "; ".join(str(driver.get("evidence") or "").strip() for driver in drivers[:3] if driver.get("evidence"))
        )

    lms_summary = intelligence.get("lms_summary") or {}
    if lms_summary:
        points.append(
            f"LMS snapshot: {int(lms_summary.get('lms_clicks_7d', 0) or 0)} clicks in 7 days, "
            f"{int(lms_summary.get('lms_unique_resources_7d', 0) or 0)} unique resources, "
            f"engagement change {float(lms_summary.get('lms_7d_vs_14d_percent_change', 0.0) or 0.0):+.2f}."
        )

    erp_summary = intelligence.get("erp_summary") or {}
    if erp_summary:
        points.append(
            f"ERP snapshot: submission rate {float(erp_summary.get('assessment_submission_rate', 0.0) or 0.0):.2f}, "
            f"weighted score {float(erp_summary.get('weighted_assessment_score', 0.0) or 0.0):.1f}, "
            f"late submissions {int(erp_summary.get('late_submission_count', 0) or 0)}."
        )

    latest_finance_event = signal_bundle.get("latest_finance_event")
    if latest_finance_event is not None and prediction is not None:
        points.append(
            f"Finance snapshot: status {str(getattr(latest_finance_event, 'payment_status', None) or 'not available')}, "
            f"delay {int(getattr(latest_finance_event, 'fee_delay_days', 0) or 0)} day(s), "
            f"modifier {float(getattr(prediction, 'finance_modifier', 0.0) or 0.0):+.2f}."
        )

    if include_triggers:
        trigger_alerts = intelligence.get("trigger_alerts") or {}
        triggers = list(trigger_alerts.get("triggers") or [])
        if triggers:
            top_trigger = triggers[0]
            points.append(
                f"Latest real-time trigger: {top_trigger.get('title')}. {top_trigger.get('rationale')}"
            )

    if include_stability:
        stability = intelligence.get("stability") or {}
        if stability.get("summary"):
            points.append(f"Model stability: {stability['summary']}")

    return points


def _answer_student_question(
    *,
    auth: AuthContext,
    repository: EventRepository,
    lowered: str,
    intent: str,
    memory: dict,
) -> tuple[str, list[dict], list[str], dict]:
    if auth.student_id is None:
        return (
            "Your student account is missing a linked student record, so I cannot answer self-service questions yet.",
            [],
            ["student token is missing student_id binding"],
            {"kind": "student_self", "student_id": None, "intent": "unsupported"},
        )

    student_id = auth.student_id
    profile = repository.get_student_profile(student_id)
    latest_prediction = repository.get_latest_prediction_for_student(student_id)
    warnings = repository.get_student_warning_history_for_student(student_id)
    academic_progress = repository.get_student_academic_progress_record(student_id)
    semester_progress_rows = repository.get_student_semester_progress_records(student_id)
    current_semester_progress = repository.get_latest_student_semester_progress_record(student_id)
    current_subject_attendance = repository.get_current_student_subject_attendance_records(student_id)
    last_context = memory.get("last_context") or {}
    signal_bundle = _load_student_signal_bundle(repository=repository, student_id=student_id)
    student_query = _classify_student_query(lowered=lowered, last_context=last_context)

    if str(student_query.get("topic")) == "semester_position":
        key_points = []
        if academic_progress is not None:
            key_points.append(
                f"Current academic position: year {academic_progress.current_year or 'unknown'}, semester {academic_progress.current_semester or 'unknown'}, mode {academic_progress.semester_mode or 'regular coursework'}."
            )
            if getattr(academic_progress, "branch", None):
                key_points.append(f"Current branch/program context: {academic_progress.branch}.")
        if current_semester_progress is not None and current_semester_progress.current_eligibility:
            key_points.append(f"Current eligibility view: {current_semester_progress.current_eligibility}.")
        if not key_points:
            key_points.append("I do not yet have enough semester-position detail in the current imported record.")
        return (
            build_grounded_response(
                opening="Here is your current semester position from the visible academic record.",
                key_points=key_points,
                tools_used=[{"tool_name": "student_semester_position_lookup", "summary": "Returned the current year, semester, and academic-mode position for the authenticated student"}],
                limitations=[],
            ),
            [{"tool_name": "student_semester_position_lookup", "summary": "Returned the current year, semester, and academic-mode position for the authenticated student"}],
            [],
            {"kind": "student_self", "student_id": student_id, "intent": "student_semester_position"},
        )

    if str(student_query.get("topic")) == "assignment_totals":
        latest_erp_event = signal_bundle.get("latest_erp_event")
        intelligence = signal_bundle.get("intelligence") or {}
        erp_summary = intelligence.get("erp_summary") or {}
        completed_assessments = erp_summary.get("total_assessments_completed")
        submission_rate = float(
            (
                erp_summary.get("assessment_submission_rate")
                if erp_summary
                else getattr(latest_erp_event, "assessment_submission_rate", 0.0)
            )
            or 0.0
        )
        key_points = []
        if completed_assessments is not None:
            key_points.append(f"Assignments/assessments currently visible as completed in the imported ERP snapshot: {int(float(completed_assessments or 0.0))}.")
        key_points.append(f"Current assignment submission rate visible in ERP: {submission_rate:.2f}.")
        key_points.append("The current imported ERP snapshot does not expose the exact total number of assignments required so far in this semester, so I cannot give a guaranteed exact assigned-total count from the grounded data alone.")
        return (
            build_grounded_response(
                opening="Here is the grounded assignment-count view I can support right now.",
                key_points=key_points,
                tools_used=[{"tool_name": "student_coursework_metric_lookup", "summary": "Returned completed-assessment visibility and submission-rate context from the current ERP snapshot"}],
                limitations=["exact assigned-total count is not exposed in the current imported ERP snapshot"],
                closing="If you want, I can next explain whether this coursework pattern is helping or hurting your current risk.",
            ),
            [{"tool_name": "student_coursework_metric_lookup", "summary": "Returned completed-assessment visibility and submission-rate context from the current ERP snapshot"}],
            ["exact assigned-total count is not exposed in the current imported ERP snapshot"],
            {"kind": "student_self", "student_id": student_id, "intent": "student_assignment_totals", "pending_student_follow_up": "coursework_risk_explanation"},
        )

    if str(student_query.get("topic")) == "finance_vs_performance":
        latest_finance_event = signal_bundle.get("latest_finance_event")
        latest_erp_event = signal_bundle.get("latest_erp_event")
        latest_prediction = signal_bundle.get("latest_prediction")
        key_points = []
        if latest_finance_event is not None:
            key_points.append(
                f"Finance view: current status is {str(getattr(latest_finance_event, 'payment_status', 'Unknown'))} with overdue amount {float(getattr(latest_finance_event, 'fee_overdue_amount', 0.0) or 0.0):.2f} and delay {int(getattr(latest_finance_event, 'fee_delay_days', 0) or 0)} day(s)."
            )
        if latest_prediction is not None:
            key_points.append(
                f"Finance is affecting your overall risk posture right now because the finance modifier on the latest prediction is {float(getattr(latest_prediction, 'finance_modifier', 0.0) or 0.0):+.2f}."
            )
        if latest_erp_event is not None:
            key_points.append(
                f"The direct academic weakness is still coursework quality: weighted assessment score {float(getattr(latest_erp_event, 'weighted_assessment_score', 0.0) or 0.0):.1f} with submission rate {float(getattr(latest_erp_event, 'assessment_submission_rate', 0.0) or 0.0):.2f}."
            )
        key_points.append("So the honest answer is: yes, finance is adding pressure, but it is stacking together with academic-performance weakness rather than replacing it.")
        return (
            build_grounded_response(
                opening="Yes, finance is affecting your current performance-and-risk picture.",
                key_points=key_points,
                tools_used=[{"tool_name": "student_finance_and_performance_reasoning", "summary": "Combined finance, ERP, and prediction context to explain whether finance is affecting current performance pressure"}],
                limitations=[],
                closing="If you want, I can turn this into a simple priority order for what to fix first.",
            ),
            [{"tool_name": "student_finance_and_performance_reasoning", "summary": "Combined finance, ERP, and prediction context to explain whether finance is affecting current performance pressure"}],
            [],
            {"kind": "student_self", "student_id": student_id, "intent": "student_finance_vs_performance", "pending_student_follow_up": "student_action_list"},
        )

    if str(student_query.get("topic")) == "seriousness":
        latest_prediction = signal_bundle.get("latest_prediction")
        latest_erp_event = signal_bundle.get("latest_erp_event")
        latest_finance_event = signal_bundle.get("latest_finance_event")
        key_points: list[str] = []
        key_points.append("No, panic is not the right response, but this should be treated as a serious recovery period rather than something to ignore.")
        if current_semester_progress is not None:
            key_points.append(
                f"Attendance posture is still {str(current_semester_progress.overall_status or 'UNKNOWN').replace('_', ' ')} with current eligibility {current_semester_progress.current_eligibility or 'not available'}."
            )
        if latest_prediction is not None:
            prediction_label = "HIGH" if int(latest_prediction.final_predicted_class) == 1 else "LOW"
            key_points.append(f"Prediction posture is {prediction_label} at probability {float(latest_prediction.final_risk_probability):.4f}.")
        if latest_erp_event is not None:
            key_points.append(
                f"The main academic pressure is coursework quality: weighted assessment score {float(getattr(latest_erp_event, 'weighted_assessment_score', 0.0) or 0.0):.1f} and submission rate {float(getattr(latest_erp_event, 'assessment_submission_rate', 0.0) or 0.0):.2f}."
            )
        if latest_finance_event is not None and str(getattr(latest_finance_event, "payment_status", "") or "").lower() not in {"paid", "clear"}:
            key_points.append(
                f"Finance is adding extra pressure too: {str(getattr(latest_finance_event, 'payment_status', 'Unknown'))} with overdue amount {float(getattr(latest_finance_event, 'fee_overdue_amount', 0.0) or 0.0):.2f}."
            )
        key_points.append("The grounded takeaway is: take it seriously, act early, but do not assume failure is guaranteed from this snapshot alone.")
        return (
            build_grounded_response(
                opening="Here is the honest seriousness view from your current record.",
                key_points=key_points,
                tools_used=[{"tool_name": "student_seriousness_check", "summary": "Combined attendance, prediction, coursework, and finance context to answer an emotional seriousness question without panic framing"}],
                limitations=[],
                closing="If you want, I can turn this into a simple 'what to do first' action list.",
            ),
            [{"tool_name": "student_seriousness_check", "summary": "Combined attendance, prediction, coursework, and finance context to answer an emotional seriousness question without panic framing"}],
            [],
            {"kind": "student_self", "student_id": student_id, "intent": "student_seriousness_check", "pending_student_follow_up": "student_action_list"},
        )

    if str(student_query.get("topic")) == "label_reduction":
        return _answer_student_label_reduction_explanation(auth=auth, repository=repository)

    if str(student_query.get("topic")) == "multi_week_plan":
        return _answer_student_multi_week_plan(
            auth=auth,
            repository=repository,
            week_number=student_query.get("week") if isinstance(student_query.get("week"), int) else None,
        )

    if (
        str(last_context.get("intent") or "") == "student_weekly_focus"
        and _looks_like_affirmative_student_follow_up(lowered)
    ):
        return _answer_student_weekly_focus_breakdown(
            auth=auth,
            repository=repository,
        )

    if intent == "identity":
        return (
            build_grounded_response(
                opening=f"You are signed in as `{auth.role}` and this chat is bound to your own student record.",
                key_points=[
                    f"Authenticated subject: {auth.subject}",
                    f"Linked student_id: {student_id}",
                ],
                tools_used=[{"tool_name": "identity_scope", "summary": "Returned current authenticated student scope"}],
                limitations=[],
                closing="I will keep future answers limited to your own records.",
            ),
            [{"tool_name": "identity_scope", "summary": "Returned current authenticated student scope"}],
            [],
            {"kind": "student_self", "student_id": student_id, "intent": "identity"},
        )

    if intent == "help":
        help_points = _build_student_data_inventory_points(
            signal_bundle=signal_bundle,
            has_warning_history=bool(warnings),
            has_attendance_foundation=bool(current_semester_progress or current_subject_attendance),
        )
        return (
            build_grounded_response(
                opening="I can now see a grounded mix of student signals for your account, not just one narrow data slice.",
                key_points=help_points,
                tools_used=[{"tool_name": "student_copilot_help", "summary": "Returned current grounded student data inventory across prediction, attendance, LMS, ERP, finance, and warning context"}],
                limitations=["long-range academic planning is still a guided summary, not a full timetable generator"],
                closing="Try asking: 'what is my attendance right now?', 'which subject is weakest?', or 'what should I focus on first this week?'",
            ),
            [{"tool_name": "student_copilot_help", "summary": "Returned current grounded student data inventory across prediction, attendance, LMS, ERP, finance, and warning context"}],
            ["long-range academic planning is currently summary-guided rather than timetable-level"],
            {"kind": "student_self", "student_id": student_id, "intent": "help"},
        )

    if _looks_like_risk_layer_difference_request(lowered):
        return _build_risk_layer_difference_answer(
            scope_label="your own record",
            tool_prefix="student",
        )

    if intent == "student_self_risk":
        if latest_prediction is None:
            return (
                build_grounded_response(
                    opening="I could not find a prediction for your record yet.",
                    key_points=[
                        "This usually means scoring has not run yet",
                        "or the required LMS data is still missing",
                    ],
                    tools_used=[{"tool_name": "latest_prediction_lookup", "summary": "No prediction found"}],
                    limitations=["student has no prediction history"],
                ),
                [{"tool_name": "latest_prediction_lookup", "summary": "No prediction found"}],
                ["student has no prediction history"],
                {"kind": "student_self", "student_id": student_id, "intent": "student_self_risk"},
            )
        risk_level = "HIGH" if int(latest_prediction.final_predicted_class) == 1 else "LOW"
        pending_follow_up = str(last_context.get("pending_student_follow_up") or "").strip().lower()
        asks_lms_vs_risk = _looks_like_student_lms_request(lowered) and any(
            token in lowered
            for token in {
                "risk",
                "hurting",
                "helping",
                "affecting",
                "impact",
                "high",
                "alert",
            }
        )
        asks_finance_vs_risk = _looks_like_student_finance_request(lowered) and any(
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
        )
        asks_coursework_vs_risk = any(
            token in lowered
            for token in {
                "coursework",
                "assignment",
                "submission rate",
                "submissions",
                "weighted score",
                "erp pattern",
                "coursework pattern",
            }
        ) and any(
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
        )
        asks_attendance_vs_risk = any(
            token in lowered
            for token in {
                "attendance is good",
                "attendance is safe",
                "attendance looks good",
                "attendance looks safe",
                "attendance okay",
                "attendance ok",
                "good attendance",
                "safe attendance",
            }
        )
        key_points = [
            f"Final risk probability: {float(latest_prediction.final_risk_probability):.4f}",
            f"Prediction timestamp available in score history for student_id {student_id}",
        ]
        opening = f"Your latest risk level is {risk_level}."
        closing = "If you want, I can next turn this into a practical action list to help reduce that risk."
        if pending_follow_up == "lms_risk_explanation" or asks_lms_vs_risk:
            opening = "Here is how your current LMS pattern is affecting your risk."
            closing = "If you want, I can next turn this into a practical action list based on that LMS and coursework pattern."
        elif pending_follow_up == "finance_risk_explanation" or asks_finance_vs_risk:
            opening = "Here is how your current finance posture is affecting your risk."
            closing = "If you want, I can next turn this into a practical action list based on that finance and coursework pattern."
        elif pending_follow_up == "coursework_risk_explanation" or asks_coursework_vs_risk:
            opening = "Here is how your current coursework pattern is affecting your risk."
            closing = "If you want, I can next turn this into a practical action list based on that coursework pattern."
        if asks_attendance_vs_risk and current_semester_progress is not None:
            key_points.insert(
                0,
                f"Attendance view: overall semester status is {str(current_semester_progress.overall_status or 'UNKNOWN').replace('_', ' ')} with {int(current_semester_progress.subjects_below_75_count or 0)} subject(s) below 75% and {int(current_semester_progress.subjects_below_65_count or 0)} subject(s) below 65%.",
            )
        key_points.extend(
            _build_cross_signal_reasoning_points(
                signal_bundle=signal_bundle,
                current_semester_progress=current_semester_progress,
                include_availability_gap=True,
            )[:5]
        )
        return (
            build_grounded_response(
                opening=opening,
                key_points=key_points,
                tools_used=[
                    {"tool_name": "latest_prediction_lookup", "summary": "Returned latest student prediction"},
                    {"tool_name": "student_cross_signal_reasoning", "summary": "Explained current risk using prediction, LMS, ERP, finance, and attendance signals when available"},
                ],
                limitations=[],
                closing=closing,
            ),
            [
                {"tool_name": "latest_prediction_lookup", "summary": "Returned latest student prediction"},
                {"tool_name": "student_cross_signal_reasoning", "summary": "Explained current risk using prediction, LMS, ERP, finance, and attendance signals when available"},
            ],
            [],
            {
                "kind": "student_self",
                "student_id": student_id,
                "intent": "student_self_risk",
                "pending_student_follow_up": (
                    "coursework_quality_evaluation"
                    if pending_follow_up == "coursework_risk_explanation" or asks_coursework_vs_risk
                    else (
                    "student_action_list"
                    if _student_response_type_for_context(
                        memory_context={"intent": "student_self_risk"},
                        lowered=lowered,
                    )
                    == "explanation"
                    else "risk_explanation_continuation"
                    )
                ),
            },
        )

    if intent == "student_self_warning":
        active_warning = next(
            (row for row in warnings if row.resolution_status is None),
            None,
        )
        if active_warning is None:
            return (
                build_grounded_response(
                    opening="I do not see any active student warning on your record right now.",
                    tools_used=[{"tool_name": "student_warning_history_lookup", "summary": "No active warning found"}],
                    limitations=[],
                ),
                [{"tool_name": "student_warning_history_lookup", "summary": "No active warning found"}],
                [],
                {"kind": "student_self", "student_id": student_id, "intent": "student_self_warning"},
            )
        return (
            build_grounded_response(
                opening="You currently have an active student warning.",
                key_points=[
                    f"Warning type: {active_warning.warning_type}",
                    f"Delivery status: {active_warning.delivery_status}",
                ],
                tools_used=[{"tool_name": "student_warning_history_lookup", "summary": "Returned active student warning"}],
                limitations=[],
            ),
            [{"tool_name": "student_warning_history_lookup", "summary": "Returned active student warning"}],
            [],
            {"kind": "student_self", "student_id": student_id, "intent": "student_self_warning"},
        )

    if intent == "student_self_profile":
        if profile is None:
            return (
                build_grounded_response(
                    opening="I could not find your student profile yet.",
                    tools_used=[{"tool_name": "student_profile_lookup", "summary": "No profile found"}],
                    limitations=["student profile missing"],
                ),
                [{"tool_name": "student_profile_lookup", "summary": "No profile found"}],
                ["student profile missing"],
                {"kind": "student_self", "student_id": student_id, "intent": "student_self_profile"},
            )
        return (
            build_grounded_response(
                opening="Here is the profile contact summary I found.",
                key_points=[
                    f"Student email: {profile.student_email or 'not available'}",
                    f"Faculty contact: {profile.faculty_name or 'not assigned'}",
                    f"Counsellor contact: {getattr(profile, 'counsellor_name', None) or 'not assigned'}",
                ],
                tools_used=[{"tool_name": "student_profile_lookup", "summary": "Returned student profile contact summary"}],
                limitations=[],
            ),
            [{"tool_name": "student_profile_lookup", "summary": "Returned student profile contact summary"}],
            [],
            {"kind": "student_self", "student_id": student_id, "intent": "student_self_profile"},
        )

    if intent == "student_self_attendance":
        if _looks_like_student_lms_request(lowered):
            lms_events = signal_bundle.get("lms_events") or []
            intelligence = signal_bundle.get("intelligence") or {}
            lms_summary = intelligence.get("lms_summary") or {}
            if not lms_events or not lms_summary:
                return (
                    build_grounded_response(
                        opening="I do not have enough LMS activity detail on your record yet.",
                        key_points=[
                            "Current LMS engagement events are not available for this student record.",
                            "Once LMS activity is present, I can summarize clicks, resources, and recent engagement trend directly.",
                        ],
                        tools_used=[{"tool_name": "student_lms_activity_lookup", "summary": "No LMS activity data was available for the student"}],
                        limitations=["student LMS activity data missing"],
                    ),
                    [{"tool_name": "student_lms_activity_lookup", "summary": "No LMS activity data was available for the student"}],
                    ["student LMS activity data missing"],
                    {"kind": "student_self", "student_id": student_id, "intent": "student_self_attendance"},
                )

            active_days_7d = len(
                {
                    str(getattr(event, "event_time", None).date())
                    for event in lms_events
                    if getattr(event, "event_time", None) is not None
                    and getattr(event, "event_time", None) >= datetime.now(timezone.utc) - timedelta(days=7)
                }
            )
            active_days_14d = len(
                {
                    str(getattr(event, "event_time", None).date())
                    for event in lms_events
                    if getattr(event, "event_time", None) is not None
                    and getattr(event, "event_time", None) >= datetime.now(timezone.utc) - timedelta(days=14)
                }
            )
            resource_type_counts = lms_summary.get("resource_type_counts_7d") or {}
            resource_summary = (
                ", ".join(f"{resource_type}: {count}" for resource_type, count in sorted(resource_type_counts.items())[:4])
                if resource_type_counts
                else "No resource-type mix is available for the latest 7-day window."
            )
            key_points = [
                f"LMS clicks in the last 7 days: {int(lms_summary.get('lms_clicks_7d', 0) or 0)}.",
                f"LMS clicks in the last 14 days: {int(lms_summary.get('lms_clicks_14d', 0) or 0)}.",
                f"Unique LMS resources touched in the last 7 days: {int(lms_summary.get('lms_unique_resources_7d', 0) or 0)}.",
                f"Active LMS login days in the last 7 days: {active_days_7d}.",
                f"Active LMS login days in the last 14 days: {active_days_14d}.",
                f"Recent LMS engagement change versus the prior 7-day window: {float(lms_summary.get('lms_7d_vs_14d_percent_change', 0.0) or 0.0):+.2f}.",
                f"Low-engagement LMS events in the last 7 days: {int(lms_summary.get('low_engagement_events_7d', 0) or 0)}.",
                f"Resource mix in the latest 7-day LMS window: {resource_summary}.",
            ]
            key_points.extend(
                _build_cross_signal_reasoning_points(
                    signal_bundle=signal_bundle,
                    current_semester_progress=current_semester_progress,
                    include_availability_gap=False,
                    include_stability=False,
                )[:2]
            )
            return (
                build_grounded_response(
                    opening="Here is your current LMS activity and engagement picture.",
                    key_points=key_points,
                    tools_used=[
                        {"tool_name": "student_lms_activity_lookup", "summary": "Returned current LMS engagement metrics and recent resource activity"},
                        {"tool_name": "student_cross_signal_reasoning", "summary": "Connected LMS engagement to the broader prediction and academic context"},
                    ],
                    limitations=[],
                    closing="If you want, I can next explain whether this LMS pattern is helping or hurting your current risk.",
                ),
                [
                    {"tool_name": "student_lms_activity_lookup", "summary": "Returned current LMS engagement metrics and recent resource activity"},
                    {"tool_name": "student_cross_signal_reasoning", "summary": "Connected LMS engagement to the broader prediction and academic context"},
                ],
                [],
                {
                    "kind": "student_self",
                    "student_id": student_id,
                    "intent": "student_self_attendance",
                    "pending_student_follow_up": "lms_risk_explanation",
                },
            )
        if _looks_like_student_erp_request(lowered):
            latest_erp_event = signal_bundle.get("latest_erp_event")
            intelligence = signal_bundle.get("intelligence") or {}
            erp_summary = intelligence.get("erp_summary") or {}
            erp_history = signal_bundle.get("erp_history") or []
            asks_gpa_detail = any(token in lowered for token in {"gpa", "cgpa", "grade point"})
            if latest_erp_event is None and not erp_summary:
                return (
                    build_grounded_response(
                        opening="I do not have enough ERP academic-performance detail on your record yet.",
                        key_points=[
                            "Current ERP coursework metrics are not available for this student record.",
                            "Once ERP data is present, I can summarize submission rate, weighted score, and late submissions directly.",
                        ],
                        tools_used=[{"tool_name": "student_erp_activity_lookup", "summary": "No ERP academic-performance data was available for the student"}],
                        limitations=["student ERP academic-performance data missing"],
                    ),
                    [{"tool_name": "student_erp_activity_lookup", "summary": "No ERP academic-performance data was available for the student"}],
                    ["student ERP academic-performance data missing"],
                    {"kind": "student_self", "student_id": student_id, "intent": "student_self_attendance"},
                )

            latest_context = getattr(latest_erp_event, "context_fields", None) or {}
            latest_cgpa = latest_context.get("cgpa") if isinstance(latest_context, dict) else None
            previous_cgpa = None
            for historical_event in erp_history[1:]:
                historical_context = getattr(historical_event, "context_fields", None) or {}
                if isinstance(historical_context, dict) and historical_context.get("cgpa") is not None:
                    previous_cgpa = historical_context.get("cgpa")
                    break
            if latest_cgpa is None:
                academic_rows = repository.get_student_academic_records(student_id)
                cgpa_values = [getattr(row, "cgpa", None) for row in academic_rows if getattr(row, "cgpa", None) is not None]
                if cgpa_values:
                    latest_cgpa = cgpa_values[-1]
                    if len(cgpa_values) >= 2:
                        previous_cgpa = cgpa_values[-2]
            submission_rate = float(
                (
                    erp_summary.get("assessment_submission_rate")
                    if erp_summary
                    else getattr(latest_erp_event, "assessment_submission_rate", 0.0)
                )
                or 0.0
            )
            weighted_score = float(
                (
                    erp_summary.get("weighted_assessment_score")
                    if erp_summary
                    else getattr(latest_erp_event, "weighted_assessment_score", 0.0)
                )
                or 0.0
            )
            late_submissions = int(
                (
                    erp_summary.get("late_submission_count")
                    if erp_summary
                    else getattr(latest_erp_event, "late_submission_count", 0)
                )
                or 0
            )
            if asks_gpa_detail and latest_cgpa is None and previous_cgpa is None:
                return (
                    build_grounded_response(
                        opening="I do not have enough GPA/CGPA detail on your record yet.",
                        key_points=[
                            f"Current submission rate in ERP is {submission_rate:.2f}.",
                            f"Current weighted assessment score is {weighted_score:.1f}.",
                            "The current imported ERP snapshot does not expose a GPA/CGPA value for this student yet.",
                        ],
                        tools_used=[
                            {"tool_name": "student_erp_activity_lookup", "summary": "Checked current ERP academic-performance data and found no GPA/CGPA value"},
                        ],
                        limitations=["student GPA/CGPA data missing from the current academic snapshot"],
                    ),
                    [
                        {"tool_name": "student_erp_activity_lookup", "summary": "Checked current ERP academic-performance data and found no GPA/CGPA value"},
                    ],
                    ["student GPA/CGPA data missing from the current academic snapshot"],
                    {
                        "kind": "student_self",
                        "student_id": student_id,
                        "intent": "student_self_attendance",
                        "pending_student_follow_up": "coursework_risk_explanation",
                    },
                )
            completed_assessments = erp_summary.get("total_assessments_completed")
            key_points = [
                f"Current submission rate in ERP is {submission_rate:.2f}.",
                f"Current weighted assessment score is {weighted_score:.1f}.",
                f"Late submissions currently recorded in ERP: {late_submissions}.",
            ]
            if latest_cgpa is not None:
                key_points.append(f"Current GPA/CGPA visible in ERP is {float(latest_cgpa):.2f}.")
            if previous_cgpa is not None:
                key_points.append(f"Previous GPA/CGPA visible in ERP history is {float(previous_cgpa):.2f}.")
            if completed_assessments is not None:
                key_points.append(f"Completed assessments currently visible in ERP: {int(float(completed_assessments or 0.0))}.")
            key_points.extend(
                _build_cross_signal_reasoning_points(
                    signal_bundle=signal_bundle,
                    current_semester_progress=current_semester_progress,
                    include_availability_gap=False,
                    include_stability=False,
                )[:2]
            )
            return (
                build_grounded_response(
                    opening="Here is your current ERP academic-performance picture.",
                    key_points=key_points,
                    tools_used=[
                        {"tool_name": "student_erp_activity_lookup", "summary": "Returned current ERP coursework metrics including submission rate and weighted score"},
                        {"tool_name": "student_cross_signal_reasoning", "summary": "Connected ERP academic-performance metrics to the broader prediction context"},
                    ],
                    limitations=[],
                    closing="If you want, I can next explain whether this ERP pattern is helping or hurting your current risk.",
                ),
                [
                    {"tool_name": "student_erp_activity_lookup", "summary": "Returned current ERP coursework metrics including submission rate and weighted score"},
                    {"tool_name": "student_cross_signal_reasoning", "summary": "Connected ERP academic-performance metrics to the broader prediction context"},
                ],
                [],
                {
                    "kind": "student_self",
                    "student_id": student_id,
                    "intent": "student_self_attendance",
                    "pending_student_follow_up": "coursework_risk_explanation",
                },
            )
        if _looks_like_student_finance_request(lowered):
            latest_finance_event = signal_bundle.get("latest_finance_event")
            prediction = signal_bundle.get("latest_prediction")
            if latest_finance_event is None:
                return (
                    build_grounded_response(
                        opening="I do not have enough finance detail on your record yet.",
                        key_points=[
                            "Current finance-status data is not available for this student record.",
                            "Once finance data is present, I can summarize payment status, delay, and overdue amount directly.",
                        ],
                        tools_used=[{"tool_name": "student_finance_lookup", "summary": "No finance data was available for the student"}],
                        limitations=["student finance data missing"],
                    ),
                    [{"tool_name": "student_finance_lookup", "summary": "No finance data was available for the student"}],
                    ["student finance data missing"],
                    {"kind": "student_self", "student_id": student_id, "intent": "student_self_attendance"},
                )

            payment_status = str(getattr(latest_finance_event, "payment_status", None) or "not available")
            delay_days = int(getattr(latest_finance_event, "fee_delay_days", 0) or 0)
            overdue_amount = float(getattr(latest_finance_event, "fee_overdue_amount", 0.0) or 0.0)
            key_points = [
                f"Current finance payment status is {payment_status}.",
                f"Current fee delay is {delay_days} day(s).",
                f"Current overdue amount is {overdue_amount:.2f}.",
            ]
            if prediction is not None:
                key_points.append(
                    f"Current finance modifier on your prediction is {float(getattr(prediction, 'finance_modifier', 0.0) or 0.0):+.2f}."
                )
            key_points.extend(
                _build_cross_signal_reasoning_points(
                    signal_bundle=signal_bundle,
                    current_semester_progress=current_semester_progress,
                    include_availability_gap=False,
                    include_stability=False,
                )[:2]
            )
            return (
                build_grounded_response(
                    opening="Here is your current finance posture.",
                    key_points=key_points,
                    tools_used=[
                        {"tool_name": "student_finance_lookup", "summary": "Returned current finance status including delay and overdue amount"},
                        {"tool_name": "student_cross_signal_reasoning", "summary": "Connected finance posture to the broader prediction context"},
                    ],
                    limitations=[],
                    closing="If you want, I can next explain whether this finance posture is helping or hurting your current risk.",
                ),
                [
                    {"tool_name": "student_finance_lookup", "summary": "Returned current finance status including delay and overdue amount"},
                    {"tool_name": "student_cross_signal_reasoning", "summary": "Connected finance posture to the broader prediction context"},
                ],
                [],
                {
                    "kind": "student_self",
                    "student_id": student_id,
                    "intent": "student_self_attendance",
                    "pending_student_follow_up": "finance_risk_explanation",
                },
            )
        if _looks_like_student_coursework_metric_request(lowered):
            latest_erp_event = signal_bundle.get("latest_erp_event")
            intelligence = signal_bundle.get("intelligence") or {}
            erp_summary = intelligence.get("erp_summary") or {}
            if latest_erp_event is None and not erp_summary:
                return (
                    build_grounded_response(
                        opening="I do not have enough coursework submission detail on your record yet.",
                        key_points=[
                            "Current ERP coursework metrics are not available.",
                            "Once ERP academic-performance data is present, I can answer assignment submission rate directly.",
                        ],
                        tools_used=[{"tool_name": "student_coursework_metric_lookup", "summary": "No ERP coursework metrics were available for the student"}],
                        limitations=["student coursework metric data missing"],
                    ),
                    [{"tool_name": "student_coursework_metric_lookup", "summary": "No ERP coursework metrics were available for the student"}],
                    ["student coursework metric data missing"],
                    {"kind": "student_self", "student_id": student_id, "intent": "student_self_attendance"},
                )

            submission_rate = float(
                (
                    erp_summary.get("assessment_submission_rate")
                    if erp_summary
                    else getattr(latest_erp_event, "assessment_submission_rate", 0.0)
                )
                or 0.0
            )
            weighted_score = float(
                (
                    erp_summary.get("weighted_assessment_score")
                    if erp_summary
                    else getattr(latest_erp_event, "weighted_assessment_score", 0.0)
                )
                or 0.0
            )
            late_submissions = int(
                (
                    erp_summary.get("late_submission_count")
                    if erp_summary
                    else getattr(latest_erp_event, "late_submission_count", 0)
                )
                or 0
            )
            completed_assessments = erp_summary.get("total_assessments_completed")

            key_points = [
                f"Your current assignment submission rate is {submission_rate:.2f}.",
                f"Current weighted assessment score is {weighted_score:.1f}.",
                f"Late submissions currently recorded: {late_submissions}.",
            ]
            if completed_assessments is not None:
                key_points.append(f"Completed assessments currently visible: {int(float(completed_assessments or 0.0))}.")
            key_points.extend(
                _build_cross_signal_reasoning_points(
                    signal_bundle=signal_bundle,
                    current_semester_progress=current_semester_progress,
                    include_availability_gap=False,
                    include_stability=False,
                )[:2]
            )
            return (
                build_grounded_response(
                    opening="Here is your current assignment and submission position.",
                    key_points=key_points,
                    tools_used=[
                        {"tool_name": "student_coursework_metric_lookup", "summary": "Returned current ERP coursework metrics including assignment submission rate"},
                        {"tool_name": "student_cross_signal_reasoning", "summary": "Connected coursework metrics to the broader prediction and academic context"},
                    ],
                    limitations=[],
                    closing="If you want, I can next explain whether this coursework pattern is helping or hurting your current risk.",
                ),
                [
                    {"tool_name": "student_coursework_metric_lookup", "summary": "Returned current ERP coursework metrics including assignment submission rate"},
                    {"tool_name": "student_cross_signal_reasoning", "summary": "Connected coursework metrics to the broader prediction and academic context"},
                ],
                [],
                {
                    "kind": "student_self",
                    "student_id": student_id,
                    "intent": "student_self_attendance",
                    "pending_student_follow_up": "coursework_risk_explanation",
                },
            )
        if current_semester_progress is None and not current_subject_attendance:
            return (
                build_grounded_response(
                    opening="I do not have enough attendance detail on your record yet.",
                    key_points=[
                        "Current subject-wise attendance is not available.",
                        "Once the institution import includes academic attendance detail, I can answer this properly.",
                    ],
                    tools_used=[{"tool_name": "student_attendance_lookup", "summary": "No student attendance foundation records were found"}],
                    limitations=["student attendance foundation data missing"],
                ),
                [{"tool_name": "student_attendance_lookup", "summary": "No student attendance foundation records were found"}],
                ["student attendance foundation data missing"],
                {"kind": "student_self", "student_id": student_id, "intent": "student_self_attendance"},
            )
        weakest_subject = next(
            (row for row in current_subject_attendance if row.subject_attendance_percent is not None),
            None,
        )
        academic_burden = build_academic_burden_summary(
            academic_rows=repository.get_student_academic_records(student_id),
            attendance_rows=repository.get_student_subject_attendance_records(student_id),
        )
        key_points = []
        if current_semester_progress is not None and current_semester_progress.overall_attendance_percent is not None:
            key_points.append(
                f"Overall attendance for your current visible semester is {float(current_semester_progress.overall_attendance_percent):.2f}%."
            )
        if academic_progress is not None:
            key_points.append(
                f"Current academic position: year {academic_progress.current_year or 'unknown'}, semester {academic_progress.current_semester or 'unknown'}, mode {academic_progress.semester_mode or 'regular coursework'}."
            )
        if weakest_subject is not None:
            key_points.append(
                f"Weakest visible subject right now: {weakest_subject.subject_name} at {float(weakest_subject.subject_attendance_percent or 0.0):.2f}% with status {str(weakest_subject.subject_status or 'UNKNOWN').replace('_', ' ')}."
            )
        if current_subject_attendance:
            key_points.append(
                "Visible subject snapshot: "
                + "; ".join(
                    f"{row.subject_name} {float(row.subject_attendance_percent or 0.0):.2f}% ({str(row.subject_status or 'UNKNOWN').replace('_', ' ')})"
                    for row in current_subject_attendance[:4]
                )
            )
        if bool(academic_burden["has_active_burden"]):
            key_points.append(
                f"Carry-forward academic burden is still active: {academic_burden['summary']} Monitoring cadence: {str(academic_burden['monitoring_cadence']).replace('_', ' ').title()}."
            )
        key_points.extend(
            _build_cross_signal_reasoning_points(
                signal_bundle=signal_bundle,
                current_semester_progress=current_semester_progress,
                include_availability_gap=False,
                include_stability=False,
            )[:3]
        )
        return (
            build_grounded_response(
                opening="Here is the attendance data I currently have for you.",
                key_points=key_points,
                tools_used=[
                    {"tool_name": "student_attendance_lookup", "summary": "Returned current semester attendance, weakest subject, and subject-wise student attendance"},
                    {"tool_name": "student_cross_signal_reasoning", "summary": "Reconciled attendance posture with broader prediction, LMS, ERP, and finance signals when available"},
                ],
                limitations=[],
                closing="If you want, I can next tell you whether this puts you in safe, I-grade, or R-grade territory.",
            ),
            [
                {"tool_name": "student_attendance_lookup", "summary": "Returned current semester attendance, weakest subject, and subject-wise student attendance"},
                {"tool_name": "student_cross_signal_reasoning", "summary": "Reconciled attendance posture with broader prediction, LMS, ERP, and finance signals when available"},
            ],
            [],
            {
                "kind": "student_self",
                "student_id": student_id,
                "intent": "student_self_attendance",
                "pending_student_follow_up": "attendance_territory",
            },
        )

    if intent == "student_self_subject_risk":
        if current_semester_progress is None and not current_subject_attendance:
            return (
                build_grounded_response(
                    opening="I do not have enough attendance-risk detail on your record yet.",
                    key_points=[
                        "I-grade and R-grade evaluation depends on current subject-wise attendance records.",
                    ],
                    tools_used=[{"tool_name": "student_subject_risk_lookup", "summary": "No attendance-risk rows were found for the student"}],
                    limitations=["student attendance-risk data missing"],
                ),
                [{"tool_name": "student_subject_risk_lookup", "summary": "No attendance-risk rows were found for the student"}],
                ["student attendance-risk data missing"],
                {"kind": "student_self", "student_id": student_id, "intent": "student_self_subject_risk"},
            )
        academic_burden = build_academic_burden_summary(
            academic_rows=repository.get_student_academic_records(student_id),
            attendance_rows=repository.get_student_subject_attendance_records(student_id),
        )
        intelligence = signal_bundle.get("intelligence") or {}
        latest_finance_event = signal_bundle.get("latest_finance_event")
        latest_erp_event = signal_bundle.get("latest_erp_event")
        weakest_subject = next(
            (row for row in current_subject_attendance if row.subject_attendance_percent is not None),
            None,
        )
        r_grade_subjects = [row for row in current_subject_attendance if str(row.subject_status or "").upper() == "R_GRADE"]
        i_grade_subjects = [row for row in current_subject_attendance if str(row.subject_status or "").upper() == "I_GRADE"]
        asks_uncleared_burden = any(
            token in lowered
            for token in {
                "uncleared",
                "unresolved",
                "still have",
                "still carrying",
                "pending",
                "cleared",
                "clear that grade",
                "older sem",
                "older sems",
                "older semester",
                "older semesters",
                "previous sem",
                "previous semester",
            }
        )
        asks_i_grade_status = any(
            token in lowered
            for token in {
                "do i have i grade risk",
                "i grade risk",
                "i-grade risk",
                "condonation",
            }
        )
        asks_r_grade_status = any(
            token in lowered
            for token in {
                "do i have r grade risk",
                "r grade risk",
                "r-grade risk",
                "repeat grade",
                "repeat subject",
            }
        )
        asks_weakest_subject = any(
            token in lowered
            for token in {
                "weakest subject",
                "what subject is in trouble",
                "hurting me most",
                "hurting most",
                "lowest attendance",
                "which subject is weakest",
                "what exactly is hurting me most right now",
            }
        )
        asks_main_problem = "what exactly is hurting me most right now" in lowered or "what is main problem" in lowered
        asks_action_first = any(
            token in lowered
            for token in {
                "what should i do first",
                "what do i do first",
                "what should i focus on first",
                "what do i focus on first",
                "what should i do now",
                "what should i focus on now",
            }
        )
        asks_end_sem = any(
            token in lowered
            for token in {
                "end sem",
                "end-sem",
                "eligible for end sem",
                "eligible for end-sem",
            }
        )
        asks_safety_check = any(
            token in lowered
            for token in {
                "am i safe",
                "should i worry",
                "should i be worried",
                "am i okay",
                "safe or should i worry",
            }
        )
        asks_cause_or_driver = any(
            token in lowered
            for token in {
                "what is causing my current risk",
                "what caused this",
                "what caused it",
                "what caused my risk",
                "why is my performance low",
                "what is affecting my results",
                "why is my gpa dropping",
                "what is going wrong",
                "what is main problem",
                "what is my biggest weakness",
                "which is affecting me more",
                "compare my lms and gpa",
                "how is my attendance and assignments together",
            }
        )
        asks_recovery_feasibility = any(
            token in lowered
            for token in {
                "can i still recover",
                "can i still recover from my current risk",
                "can i recover fully",
                "is it too late for me",
            }
        )
        asks_timeline = any(
            token in lowered
            for token in {
                "how long might recovery take from my current risk",
                "how long will it take",
                "how much time i have",
                "how fast can i improve",
            }
        )
        pending_student_follow_up = str(last_context.get("pending_student_follow_up") or "").strip().lower()
        asks_coursework_consequence_followup = pending_student_follow_up == "coursework_consequence_follow_up" and any(
            token in lowered
            for token in {
                "will my risk increase",
                "will risk increase",
                "by how much",
            }
        )
        asks_assignment_only = any(
            token in lowered
            for token in {
                "would only fixing assignments be enough to reduce my current risk",
                "what if i only fix assignments",
                "is that enough",
            }
        )
        asks_assignment_sufficiency_followup = pending_student_follow_up == "assignment_sufficiency_follow_up" and any(
            token in lowered
            for token in {
                "is that enough",
                "would only fixing assignments be enough to reduce my current risk",
            }
        )
        asks_consequence = any(
            token in lowered
            for token in {
                "what happens if i do not improve my current risk drivers",
                "will i fail if my current risk drivers do not improve",
                "what is the worst case if my current risk drivers do not improve",
                "what happens if i miss my next assignment submission",
                "will missing coursework increase my current risk",
                "how much could missing coursework raise my current risk",
                "what happens if i don't improve",
                "what happens if i dont improve",
                "what happens if i ignore this",
                "if i do not clear this what happens",
                "if i dont clear this what happens",
                "what happens if i do not clear this",
                "what happens if i dont clear this",
                "will i fail",
                "what is worst case",
                "what if i stop studying",
            }
        )
        asks_relative_position = any(
            token in lowered
            for token in {
                "am i worse than others",
                "is my situation normal",
                "how serious is it",
                "how serious is my situation",
                "am i going to fail",
                "should i panic",
            }
        )
        asks_worst_case = "what is worst case" in lowered or "what is the worst case if my current risk drivers do not improve" in lowered
        asks_fail_outcome = "will i fail" in lowered or "will i fail if my current risk drivers do not improve" in lowered
        asks_attendance_importance = "does attendance really matter" in lowered
        asks_lms_importance = "is lms important" in lowered
        asks_safe_attendance_but_high_alert = _looks_like_student_safe_but_high_alert_question(lowered)
        if str(last_context.get("pending_student_follow_up") or "").strip().lower() == "coursework_risk_explanation":
            opening = "Here is how your current coursework pattern is affecting your risk."
        elif asks_i_grade_status:
            opening = (
                "Yes, I can see I-grade attendance risk in your visible record."
                if i_grade_subjects
                else "I do not currently see I-grade attendance risk in your visible record."
            )
        elif asks_r_grade_status:
            opening = (
                "Yes, I can see R-grade attendance risk in your visible record."
                if r_grade_subjects
                else "I do not currently see R-grade attendance risk in your visible record."
            )
        elif asks_uncleared_burden:
            if bool(academic_burden["has_active_burden"]):
                opening = "Yes, you still have uncleared academic burden linked to earlier I-grade or R-grade outcomes."
            else:
                opening = "I do not currently see any uncleared I-grade or R-grade subjects on your visible record."
        elif asks_recovery_feasibility:
            opening = "Yes, you can still recover from the current HIGH-risk posture, but it will need steady improvement in the signals dragging you down."
        elif asks_timeline:
            opening = "Here is the grounded time-and-recovery view from your current record."
        elif asks_assignment_sufficiency_followup:
            opening = "No, assignments alone would still not be enough on your current record."
        elif asks_assignment_only:
            opening = "Here is the grounded view on whether assignments alone would be enough to reduce your current risk."
        elif asks_coursework_consequence_followup:
            opening = "Yes, weaker coursework would likely push your current risk upward."
            if "by how much" in lowered:
                opening = "Here is the grounded magnitude view if coursework slips further."
        elif asks_consequence:
            opening = "Here is the grounded consequence view if the current risk drivers do not improve."
            if asks_worst_case:
                opening = "Here is the grounded worst-case view if the current risk drivers stay weak."
            elif asks_fail_outcome:
                opening = "Here is the grounded failure-risk view from your current record."
        elif asks_attendance_importance:
            opening = "Yes, attendance still matters a lot, even if it is not the only thing affecting your risk."
        elif asks_lms_importance:
            opening = "Yes, LMS behavior matters, but it works as a supporting signal rather than the only driver."
        elif asks_main_problem:
            opening = "Here is the main problem to focus on first."
        elif asks_cause_or_driver:
            opening = "Here is what is currently driving your risk most strongly."
        elif asks_relative_position:
            opening = "Here is the honest seriousness view from your current record."
        elif asks_weakest_subject and asks_action_first and weakest_subject is not None:
            opening = "Here is what is hurting you most right now and what you should do first."
        elif asks_safe_attendance_but_high_alert:
            opening = "Here is why you can still be in a HIGH alert posture even though current attendance looks SAFE."
        elif asks_safety_check:
            opening = "Here is the honest safety check from your current visible record."
        elif asks_end_sem:
            opening = "Here is your current end-sem eligibility position."
        elif asks_weakest_subject and weakest_subject is not None:
            opening = "Here is the subject that is currently hurting you most in the visible attendance data."
        else:
            opening = "Here is your current attendance-risk position."
        key_points = []
        if asks_weakest_subject and weakest_subject is not None:
            key_points.append(
                f"Weakest visible subject: {weakest_subject.subject_name} at {float(weakest_subject.subject_attendance_percent or 0.0):.2f}% with status {str(weakest_subject.subject_status or 'UNKNOWN').replace('_', ' ')}."
            )
        if asks_i_grade_status and not i_grade_subjects:
            key_points.append("No visible subject is currently in I-grade attendance risk on the latest semester record.")
        if asks_r_grade_status and not r_grade_subjects:
            key_points.append("No visible subject is currently in R-grade attendance risk on the latest semester record.")
        if asks_main_problem:
            key_points.append(
                "Main problem to focus on first: the broader academic-performance and submission pattern is currently hurting you more than attendance itself."
            )
        if asks_weakest_subject and asks_action_first and weakest_subject is not None:
            action_label = (
                "recover it urgently because it is already in R-grade risk"
                if str(weakest_subject.subject_status or "").upper() == "R_GRADE"
                else "protect it first before it slips further"
                if str(weakest_subject.subject_status or "").upper() == "I_GRADE"
                else "keep it from slipping further, because it is still your weakest visible subject"
            )
            key_points.append(f"First focus: {weakest_subject.subject_name}. You should {action_label}.")
        if r_grade_subjects:
            key_points.append(
                "R-grade risk subjects: "
                + "; ".join(
                    f"{row.subject_name} {float(row.subject_attendance_percent or 0.0):.2f}%"
                    for row in r_grade_subjects
                )
            )
        if i_grade_subjects:
            key_points.append(
                "I-grade risk subjects: "
                + "; ".join(
                    f"{row.subject_name} {float(row.subject_attendance_percent or 0.0):.2f}%"
                    for row in i_grade_subjects
                )
            )
        if current_semester_progress is not None and not asks_uncleared_burden:
            if asks_safety_check or asks_safe_attendance_but_high_alert:
                key_points.append(
                    f"Attendance view: overall semester status is {str(current_semester_progress.overall_status or 'UNKNOWN').replace('_', ' ')} with {int(current_semester_progress.subjects_below_75_count or 0)} subject(s) below 75% and {int(current_semester_progress.subjects_below_65_count or 0)} subject(s) below 65%."
                )
            else:
                key_points.append(
                    f"Overall semester status: {str(current_semester_progress.overall_status or 'UNKNOWN').replace('_', ' ')} with {int(current_semester_progress.subjects_below_75_count or 0)} subject(s) below 75% and {int(current_semester_progress.subjects_below_65_count or 0)} subject(s) below 65%."
                )
            eligibility_text = current_semester_progress.current_eligibility or "not available"
            if asks_end_sem:
                key_points.append(f"End-sem eligibility: {eligibility_text}.")
            else:
                key_points.append(f"Current eligibility view: {eligibility_text}.")
        if (
            asks_safety_check
            or asks_safe_attendance_but_high_alert
            or asks_cause_or_driver
            or asks_recovery_feasibility
            or asks_timeline
            or asks_consequence
            or asks_attendance_importance
            or asks_lms_importance
            or asks_relative_position
            or str(last_context.get("pending_student_follow_up") or "").strip().lower() == "coursework_risk_explanation"
        ) and latest_prediction is not None:
            prediction_label = "HIGH" if int(latest_prediction.final_predicted_class) == 1 else "LOW"
            key_points.append(f"Latest prediction risk view: {prediction_label} at probability {float(latest_prediction.final_risk_probability):.4f}.")
            key_points.extend(
                _build_cross_signal_reasoning_points(
                    signal_bundle=signal_bundle,
                    current_semester_progress=current_semester_progress,
                    include_availability_gap=True,
                )[:4]
            )
        if asks_recovery_feasibility:
            key_points.append(
                "Your current attendance posture is still SAFE, which means the record does not show an immediate attendance-collapse scenario."
            )
            key_points.append(
                "The stronger current pressure is coming from coursework and broader academic-performance signals, so recovery depends more on sustained academic improvement than on one isolated attendance fix."
            )
        if asks_timeline:
            key_points.append(
                "Risk recovery usually takes sustained improvement over multiple weeks, not just one good day or one completed task."
            )
            key_points.append(
                "The HIGH label should come down only after the weaker academic and submission signals start improving consistently."
            )
        if asks_assignment_sufficiency_followup:
            key_points.append(
                "Assignments are a major part of the fix, but they are still only one part of the current pressure picture."
            )
            key_points.append(
                "You would still need to improve the broader academic-performance pattern and reduce finance pressure if you want the HIGH label to come down reliably."
            )
            if latest_finance_event is not None and str(getattr(latest_finance_event, "payment_status", "") or "").lower() not in {"paid", "clear"}:
                key_points.append(
                    f"Finance is still an active drag right now: {str(getattr(latest_finance_event, 'payment_status', 'Unknown'))} with overdue amount {float(getattr(latest_finance_event, 'fee_overdue_amount', 0.0) or 0.0):.2f}."
                )
            if latest_erp_event is not None:
                key_points.append(
                    f"The academic-performance side still matters too because your weighted assessment score is {float(getattr(latest_erp_event, 'weighted_assessment_score', 0.0) or 0.0):.1f}."
                )
        elif asks_assignment_only:
            key_points.append(
                "Improving assignments would definitely help, because coursework and academic performance are among the strongest current drivers."
            )
            key_points.append(
                "But assignments alone would usually not be the full answer while finance pressure and broader performance weakness are still visible on the record."
            )
        if asks_coursework_consequence_followup:
            key_points.append(
                "Directionally, yes: missing coursework would push the risk upward because coursework and academic performance are already visible pressure areas in your record."
            )
            key_points.append(
                "I cannot promise an exact numeric jump from one missed submission alone, but it would move the signal in the wrong direction rather than the right one."
            )
        if asks_consequence:
            key_points.append(
                "If the current academic-performance and submission signals do not improve, the HIGH-risk posture is more likely to persist instead of cooling down on its own."
            )
            key_points.append(
                "That can make future warning pressure, academic decline, and subject-level stress harder to recover from later."
            )
            if "what happens if i miss my next assignment submission" in lowered:
                key_points.append(
                    "Missing the next assignment would usually make the coursework picture weaker because submission consistency is already one of the visible pressure areas."
                )
            if any(
                token in lowered
                for token in {
                    "if i do not clear this what happens",
                    "if i dont clear this what happens",
                    "what happens if i do not clear this",
                    "what happens if i dont clear this",
                }
            ):
                key_points.append(
                    "If an I-grade or R-grade issue remains uncleared, it can keep academic burden active longer and make later recovery more difficult."
                )
                key_points.append(
                    "That is why uncleared burden should be treated as something to resolve early, not something to leave sitting in the background."
                )
            if "will missing coursework increase my current risk" in lowered or "how much could missing coursework raise my current risk" in lowered:
                key_points.append(
                    "I cannot promise an exact numeric jump from one missed submission alone, but directionally it would push the risk upward rather than downward."
                )
            if asks_fail_outcome:
                key_points.append(
                    "I cannot say failure is guaranteed from this snapshot alone, but continuing decline would clearly move you in the wrong direction."
                )
            if asks_worst_case:
                key_points.append(
                    "Worst case, the current warning pressure stays active, performance weakness deepens, and later attendance or subject-level issues become harder to reverse."
                )
        if asks_attendance_importance:
            key_points.append(
                "Attendance directly affects end-sem eligibility and I-grade/R-grade territory, so it remains a core retention signal."
            )
            key_points.append(
                "In your current record, attendance looks SAFE, but that does not cancel the broader coursework and performance pressure keeping the risk high."
            )
        if asks_lms_importance:
            key_points.append(
                "LMS is useful because it shows engagement consistency, resource use, and short-term academic activity."
            )
            key_points.append(
                "But LMS alone does not outweigh weak coursework or academic-performance signals, which is why a student can still look active online and remain high risk."
            )
        if asks_relative_position:
            key_points.append(
                "I cannot rank you precisely against every other student from this answer alone, but a HIGH prediction means your current posture should be treated as serious rather than comfortably normal."
            )
        if asks_cause_or_driver and latest_prediction is None:
            key_points.append("I do not have a latest prediction row to break down finer driver weights, so I am grounding this answer from attendance and academic posture only.")
        if bool(academic_burden["has_active_burden"]):
            key_points.append(f"Uncleared burden summary: {academic_burden['summary']}")
            if academic_burden["active_r_grade_subjects"]:
                key_points.append(
                    "R-grade subjects that should still be treated as uncleared until the repeat requirement is actually completed: "
                    + "; ".join(
                        f"{item['subject_name']} ({item['effective_result_status']})"
                        for item in academic_burden["active_r_grade_subjects"][:5]
                    )
                )
            if academic_burden["active_i_grade_subjects"]:
                key_points.append(
                    "I-grade subjects that should still be treated as uncleared until clearance is actually completed: "
                    + "; ".join(
                        f"{item['subject_name']} ({item['effective_result_status']})"
                        for item in academic_burden["active_i_grade_subjects"][:5]
                    )
                )
        if asks_uncleared_burden and not bool(academic_burden["has_active_burden"]):
            key_points.append("That means your currently visible academic record does not show any pending I-grade or pending R-grade clearance items.")
            if current_semester_progress is not None:
                key_points.append(
                    f"Current semester posture is {str(current_semester_progress.overall_status or 'UNKNOWN').replace('_', ' ')} with {int(current_semester_progress.subjects_below_75_count or 0)} subject(s) below 75% and {int(current_semester_progress.subjects_below_65_count or 0)} subject(s) below 65%."
                )
        if not key_points:
            key_points.append("I do not currently see any visible I-grade or R-grade subjects in your latest imported attendance data.")
        return (
            build_grounded_response(
                opening=opening,
                key_points=key_points,
                tools_used=[{"tool_name": "student_subject_risk_lookup", "summary": "Returned current I-grade, R-grade, and semester eligibility risk summary"}],
                limitations=[],
                closing="If you want, I can turn this into a simple 'what to do first' action list.",
            ),
            [{"tool_name": "student_subject_risk_lookup", "summary": "Returned current I-grade, R-grade, and semester eligibility risk summary"}],
            [],
            {
                "kind": "student_self",
                "student_id": student_id,
                "intent": "student_self_subject_risk",
                "pending_student_follow_up": (
                    "coursework_consequence_follow_up"
                    if asks_coursework_consequence_followup
                    or any(
                        token in lowered
                        for token in {
                            "what happens if i miss my next assignment submission",
                            "will missing coursework increase my current risk",
                            "how much could missing coursework raise my current risk",
                        }
                    )
                    else (
                        "student_action_list"
                        if asks_assignment_sufficiency_followup
                        else (
                            "assignment_sufficiency_follow_up"
                            if asks_assignment_only
                            else (
                                "risk_explanation_continuation"
                                if asks_safety_check or asks_relative_position or asks_recovery_feasibility
                                else "student_action_list"
                            )
                        )
                    )
                ),
            },
        )

    if intent == "student_self_plan":
        return _answer_student_plan_request(
            auth=auth,
            repository=repository,
            lowered=lowered,
            last_context=last_context,
        )

    return (
        build_grounded_response(
            opening=(
                "I can’t help with that request." if _is_sensitive_request(lowered) else "I didn’t fully match that to a student intent yet."
            ),
            key_points=(
                ["I cannot share passwords or secrets."]
                if _is_sensitive_request(lowered)
                else [
                    "latest risk or warning status",
                    "current attendance and subject-wise status",
                    "profile and assigned support contacts",
                    *(
                        [f"Did you mean: {', '.join(_build_intent_suggestions('student', lowered))}?"]
                        if _build_intent_suggestions("student", lowered)
                        else []
                    ),
                ]
            ),
            tools_used=[{"tool_name": "student_intent_router", "summary": f"Routed unsupported student intent `{intent}`"}],
            limitations=["student question is outside the current grounded student intent set"],
        ),
        [{"tool_name": "student_intent_router", "summary": f"Routed unsupported student intent `{intent}`"}],
        ["student question is outside the current grounded student intent set"],
        {
            "kind": "student_self",
            "student_id": student_id,
            "intent": "unsupported",
            "last_follow_up": bool(memory.get("is_follow_up")),
        },
    )


def _answer_student_weekly_focus(
    *,
    auth: AuthContext,
    repository: EventRepository,
) -> tuple[str, list[dict], list[str], dict]:
    if auth.student_id is None:
        return (
            "Your student account is missing a linked student record, so I cannot suggest next steps yet.",
            [],
            ["student token is missing student_id binding"],
            {"kind": "student_self", "student_id": None, "intent": "student_weekly_focus"},
        )

    student_id = auth.student_id
    latest_prediction = repository.get_latest_prediction_for_student(student_id)
    warnings = repository.get_student_warning_history_for_student(student_id)
    current_semester_progress = repository.get_latest_student_semester_progress_record(student_id)
    current_subject_attendance = repository.get_current_student_subject_attendance_records(student_id)
    signal_bundle = _load_student_signal_bundle(repository=repository, student_id=student_id)

    if latest_prediction is None:
        return (
            build_grounded_response(
                opening="I could not find your latest progress snapshot yet.",
                key_points=[
                    "That usually means scoring has not run yet or the required LMS data is still missing.",
                    "Once your latest prediction is available, I can suggest the most useful focus area for this week.",
                ],
                tools_used=[{"tool_name": "student_weekly_focus", "summary": "No prediction was available for student weekly focus guidance"}],
                limitations=["student has no prediction history"],
            ),
            [{"tool_name": "student_weekly_focus", "summary": "No prediction was available for student weekly focus guidance"}],
            ["student has no prediction history"],
            {"kind": "student_self", "student_id": student_id, "intent": "student_weekly_focus"},
        )

    recommended_actions = list(getattr(latest_prediction, "recommended_actions", None) or [])
    active_warning = next((row for row in warnings if row.resolution_status is None), None)
    risk_level = "high" if int(latest_prediction.final_predicted_class) == 1 else "low"
    r_grade_subjects = [row for row in current_subject_attendance if str(row.subject_status or "").upper() == "R_GRADE"]
    i_grade_subjects = [row for row in current_subject_attendance if str(row.subject_status or "").upper() == "I_GRADE"]

    if r_grade_subjects:
        first = r_grade_subjects[0]
        return (
            build_grounded_response(
                opening=f"For this week, your first focus should be: urgently recover {first.subject_name}.",
                key_points=[
                    f"{first.subject_name} is currently at {float(first.subject_attendance_percent or 0.0):.2f}% and is in R-grade risk.",
                    "R-grade risk should come before lower-priority academic cleanup because it can lead to repeating the subject.",
                    "After that, move to the next low-attendance or warning-linked subject on your record.",
                ],
                tools_used=[{"tool_name": "student_weekly_focus", "summary": "Used current subject attendance and policy status to prioritize an R-grade-risk subject first"}],
                limitations=[],
                closing="If you want, I can also break this into attendance, coursework, and overall recovery priorities.",
            ),
            [{"tool_name": "student_weekly_focus", "summary": "Used current subject attendance and policy status to prioritize an R-grade-risk subject first"}],
            [],
            {
                "kind": "student_self",
                "student_id": student_id,
                "intent": "student_weekly_focus",
                "pending_student_follow_up": "weekly_focus_breakdown",
            },
        )

    if i_grade_subjects:
        first = i_grade_subjects[0]
        return (
            build_grounded_response(
                opening=f"For this week, your first focus should be: protect {first.subject_name} from slipping further.",
                key_points=[
                    f"{first.subject_name} is currently at {float(first.subject_attendance_percent or 0.0):.2f}% and is in I-grade risk.",
                    "That means this subject should be treated as your first attendance priority before lighter academic tasks.",
                    "Once that is stabilized, move to coursework and any other warning-linked actions.",
                ],
                tools_used=[{"tool_name": "student_weekly_focus", "summary": "Used current subject attendance and policy status to prioritize an I-grade-risk subject first"}],
                limitations=[],
                closing="If you want, I can also break this into attendance, coursework, and overall recovery priorities.",
            ),
            [{"tool_name": "student_weekly_focus", "summary": "Used current subject attendance and policy status to prioritize an I-grade-risk subject first"}],
            [],
            {
                "kind": "student_self",
                "student_id": student_id,
                "intent": "student_weekly_focus",
                "pending_student_follow_up": "weekly_focus_breakdown",
            },
        )

    if recommended_actions:
        primary = recommended_actions[0]
        title = str(primary.get("title") or "Follow the top recommended action")
        rationale = str(primary.get("rationale") or "This is the strongest grounded action available from your latest student record.")
        supporting_points: list[str] = [rationale]
        if active_warning is not None:
            supporting_points.append("You also have an active warning, so this should be treated as your first priority.")
        if len(recommended_actions) > 1:
            next_title = str(recommended_actions[1].get("title") or "").strip()
            if next_title:
                supporting_points.append(f"After that, the next useful step would be: {next_title}.")
        supporting_points.extend(
            _build_cross_signal_reasoning_points(
                signal_bundle=signal_bundle,
                current_semester_progress=current_semester_progress,
                include_availability_gap=False,
                include_stability=False,
                include_triggers=False,
            )[:2]
        )
        return (
            build_grounded_response(
                opening=f"For this week, your first focus should be: {title}.",
                key_points=supporting_points,
                tools_used=[{"tool_name": "student_weekly_focus", "summary": "Used the latest student prediction and recommended actions to suggest a weekly priority"}],
                limitations=[],
                closing="If you want, I can also break this into attendance, coursework, or overall recovery priorities.",
            ),
            [{"tool_name": "student_weekly_focus", "summary": "Used the latest student prediction and recommended actions to suggest a weekly priority"}],
            [],
            {
                "kind": "student_self",
                "student_id": student_id,
                "intent": "student_weekly_focus",
                "pending_student_follow_up": "weekly_focus_breakdown",
            },
        )

    fallback_points = [
        f"Your latest grounded risk level is {risk_level}.",
        f"Current risk probability: {float(latest_prediction.final_risk_probability):.4f}",
    ]
    fallback_points.extend(
        _build_cross_signal_reasoning_points(
            signal_bundle=signal_bundle,
            current_semester_progress=current_semester_progress,
            include_availability_gap=True,
            include_stability=False,
            include_triggers=False,
        )[:3]
    )
    if current_semester_progress is not None and current_semester_progress.overall_attendance_percent is not None:
        fallback_points.append(
            f"Current overall attendance: {float(current_semester_progress.overall_attendance_percent):.2f}%."
        )
    if active_warning is not None:
        fallback_points.append("Because you have an active warning, start with the most immediate academic or attendance issue on your record.")
    return (
        build_grounded_response(
            opening="I do not see a specific action bundle on your latest record, but I can still suggest the safest first step.",
            key_points=fallback_points,
            tools_used=[{"tool_name": "student_weekly_focus", "summary": "Used the latest student prediction to suggest a conservative weekly priority"}],
            limitations=["no recommended action bundle was available on the latest prediction"],
            closing="If you want, ask me whether you should focus first on attendance, warnings, or overall recovery.",
        ),
        [{"tool_name": "student_weekly_focus", "summary": "Used the latest student prediction to suggest a conservative weekly priority"}],
        ["no recommended action bundle was available on the latest prediction"],
        {
            "kind": "student_self",
            "student_id": student_id,
            "intent": "student_weekly_focus",
            "pending_student_follow_up": "weekly_focus_breakdown",
        },
    )


def _answer_student_plan_request(
    *,
    auth: AuthContext,
    repository: EventRepository,
    lowered: str,
    last_context: dict,
) -> tuple[str, list[dict], list[str], dict]:
    focus = _detect_student_plan_focus(lowered=lowered, last_context=last_context)
    if focus == "label_reduction":
        return _answer_student_label_reduction_explanation(auth=auth, repository=repository)
    if focus == "multi_week":
        return _answer_student_multi_week_plan(auth=auth, repository=repository, week_number=None)
    if focus.startswith("week_"):
        try:
            week_number = int(focus.split("_", 1)[1])
        except ValueError:
            week_number = None
        return _answer_student_multi_week_plan(auth=auth, repository=repository, week_number=week_number)
    if focus == "day_by_day":
        return _answer_student_day_by_day_plan(auth=auth, repository=repository)
    if focus in {"recovery", "attendance", "coursework", "priorities"}:
        return _answer_student_priority_focus(auth=auth, repository=repository, focus=focus)
    if focus == "breakdown":
        return _answer_student_weekly_focus_breakdown(auth=auth, repository=repository)
    return _answer_student_weekly_focus(auth=auth, repository=repository)


def _answer_student_weekly_focus_breakdown(
    *,
    auth: AuthContext,
    repository: EventRepository,
) -> tuple[str, list[dict], list[str], dict]:
    if auth.student_id is None:
        return (
            "Your student account is missing a linked student record, so I cannot break that down yet.",
            [],
            ["student token is missing student_id binding"],
            {"kind": "student_self", "student_id": None, "intent": "student_weekly_focus_breakdown"},
        )

    student_id = auth.student_id
    latest_prediction = repository.get_latest_prediction_for_student(student_id)
    warnings = repository.get_student_warning_history_for_student(student_id)
    current_semester_progress = repository.get_latest_student_semester_progress_record(student_id)
    current_subject_attendance = repository.get_current_student_subject_attendance_records(student_id)
    active_warning = next((row for row in warnings if row.resolution_status is None), None)
    signal_bundle = _load_student_signal_bundle(repository=repository, student_id=student_id)

    if latest_prediction is None:
        return (
            build_grounded_response(
                opening="I still do not have enough grounded student data to break that into weekly priorities yet.",
                key_points=[
                    "Your latest prediction snapshot is not available yet.",
                    "Once scoring is available, I can separate your focus into attendance, coursework, and overall recovery.",
                ],
                tools_used=[{"tool_name": "student_weekly_focus_breakdown", "summary": "Could not build a student weekly breakdown because no latest prediction was available"}],
                limitations=["student has no prediction history"],
            ),
            [{"tool_name": "student_weekly_focus_breakdown", "summary": "Could not build a student weekly breakdown because no latest prediction was available"}],
            ["student has no prediction history"],
            {"kind": "student_self", "student_id": student_id, "intent": "student_weekly_focus_breakdown"},
        )

    recommended_actions = list(getattr(latest_prediction, "recommended_actions", None) or [])
    risk_level = "high" if int(latest_prediction.final_predicted_class) == 1 else "low"

    attendance_priority = "Keep attendance stable and avoid missing scheduled academic activity."
    coursework_priority = "Finish pending coursework and LMS tasks before adding anything new."
    recovery_priority = (
        "Treat recovery as a structured week: complete the top recommended action first, then clear the next academic blocker."
    )

    for action in recommended_actions:
        title = str(action.get("title") or "")
        rationale = str(action.get("rationale") or "")
        combined = f"{title} {rationale}".lower()
        if any(token in combined for token in {"attendance", "class", "absence", "present"}):
            attendance_priority = title or attendance_priority
        if any(token in combined for token in {"assignment", "coursework", "lms", "task", "submission"}):
            coursework_priority = title or coursework_priority
        if any(token in combined for token in {"re-engagement", "recovery", "warning", "risk"}):
            recovery_priority = title or recovery_priority

    if current_subject_attendance:
        weakest = next((row for row in current_subject_attendance if row.subject_attendance_percent is not None), None)
        if weakest is not None:
            attendance_priority = (
                f"Protect {weakest.subject_name} first because it is currently at {float(weakest.subject_attendance_percent or 0.0):.2f}% "
                f"with status {str(weakest.subject_status or 'UNKNOWN').replace('_', ' ')}."
            )
    if current_semester_progress is not None and str(current_semester_progress.overall_status or "").upper() == "SHORTAGE":
        recovery_priority = (
            f"Your overall semester attendance is under the required threshold, so this week should be treated as recovery-first, not optional improvement."
        )

    key_points = [
        f"Attendance: {attendance_priority}",
        f"Coursework: {coursework_priority}",
        f"Overall recovery: {recovery_priority}",
    ]
    if active_warning is not None:
        key_points.append("You also have an active warning, so finish the most urgent academic item first before moving to lower-priority tasks.")
    key_points.append(f"Your current grounded risk posture is {risk_level}, so consistency this week matters more than volume.")
    key_points.extend(
        _build_cross_signal_reasoning_points(
            signal_bundle=signal_bundle,
            current_semester_progress=current_semester_progress,
            include_availability_gap=False,
            include_stability=False,
            include_triggers=False,
        )[:2]
    )

    return (
        build_grounded_response(
            opening="Here is the breakdown for this week, using your own current student context.",
            key_points=key_points,
            tools_used=[{"tool_name": "student_weekly_focus_breakdown", "summary": "Used the latest student prediction, warnings, and recommended actions to break weekly focus into attendance, coursework, and recovery"}],
            limitations=[],
            closing="If you want, I can next turn this into a simple day-by-day plan for the week.",
        ),
        [{"tool_name": "student_weekly_focus_breakdown", "summary": "Used the latest student prediction, warnings, and recommended actions to break weekly focus into attendance, coursework, and recovery"}],
        [],
        {
            "kind": "student_self",
            "student_id": student_id,
            "intent": "student_weekly_focus_breakdown",
            "pending_student_follow_up": "day_by_day_plan",
        },
    )


def _answer_student_priority_focus(
    *,
    auth: AuthContext,
    repository: EventRepository,
    focus: str,
) -> tuple[str, list[dict], list[str], dict]:
    if auth.student_id is None:
        return (
            "Your student account is missing a linked student record, so I cannot build a focused recovery plan yet.",
            [],
            ["student token is missing student_id binding"],
            {"kind": "student_self", "student_id": None, "intent": "student_recovery_focus"},
        )

    student_id = auth.student_id
    latest_prediction = repository.get_latest_prediction_for_student(student_id)
    current_semester_progress = repository.get_latest_student_semester_progress_record(student_id)
    current_subject_attendance = repository.get_current_student_subject_attendance_records(student_id)
    warnings = repository.get_student_warning_history_for_student(student_id)
    signal_bundle = _load_student_signal_bundle(repository=repository, student_id=student_id)
    active_warning = next((row for row in warnings if row.resolution_status is None), None)

    if latest_prediction is None:
        return _answer_student_weekly_focus(auth=auth, repository=repository)

    weakest = next((row for row in current_subject_attendance if row.subject_attendance_percent is not None), None)
    intelligence = signal_bundle.get("intelligence") or {}
    drivers = intelligence.get("drivers") or []
    top_driver_evidence = [str(driver.get("evidence") or "").strip() for driver in drivers[:3] if driver.get("evidence")]
    latest_finance_event = signal_bundle.get("latest_finance_event")
    latest_erp_event = signal_bundle.get("latest_erp_event")

    if focus == "attendance":
        opening = "Here is the attendance-focused priority plan from your current grounded record."
        key_points = []
        if weakest is not None:
            key_points.append(
                f"Protect {weakest.subject_name} first because it is your weakest visible subject at {float(weakest.subject_attendance_percent or 0.0):.2f}%."
            )
        if current_semester_progress is not None:
            key_points.append(
                f"Current semester posture is {str(current_semester_progress.overall_status or 'UNKNOWN').replace('_', ' ')} with {int(current_semester_progress.subjects_below_75_count or 0)} subject(s) below 75% and {int(current_semester_progress.subjects_below_65_count or 0)} subject(s) below 65%."
            )
        key_points.append("Do not let attendance slip while you are fixing the broader academic-risk signals, because a second problem layer will make recovery harder.")
        if active_warning is not None:
            key_points.append("Because you already have an active warning, keep attendance stable while you clear the academic and submission issues driving risk.")
        closing = "If you want, I can turn this into a simple day-by-day plan for the week."
    elif focus == "coursework":
        opening = "Here is the coursework-focused priority plan from your current grounded record."
        submission_rate = float(getattr(latest_erp_event, "assessment_submission_rate", 0.0) or 0.0) if latest_erp_event is not None else None
        weighted_score = float(getattr(latest_erp_event, "weighted_assessment_score", 0.0) or 0.0) if latest_erp_event is not None else None
        key_points = []
        if submission_rate is not None:
            key_points.append(f"Your current submission rate is {submission_rate:.2f}, so the first coursework priority is to stop any further missed or delayed submissions.")
        if weighted_score is not None:
            key_points.append(f"Your weighted assessment score is {weighted_score:.1f}, so improving assessed coursework quality is one of the fastest ways to improve the model view of your record.")
        if top_driver_evidence:
            key_points.append("Current coursework-related drivers: " + "; ".join(top_driver_evidence[:2]))
        key_points.append("Finish the highest-impact pending academic task first before spreading effort across many smaller tasks.")
        closing = "If you want, I can turn this into a simple day-by-day plan for the week."
    elif focus == "priorities":
        opening = "Here are your grounded recovery priorities in order."
        key_points = []
        if latest_erp_event is not None:
            weighted_score = float(getattr(latest_erp_event, "weighted_assessment_score", 0.0) or 0.0)
            submission_rate = float(getattr(latest_erp_event, "assessment_submission_rate", 0.0) or 0.0)
            key_points.append(
                f"Top priority: improve assessed coursework quality first because your weighted assessment score is {weighted_score:.1f} and your submission rate is {submission_rate:.2f}."
            )
        elif top_driver_evidence:
            key_points.append(f"Top priority: address the strongest current driver first: {top_driver_evidence[0]}.")
        else:
            key_points.append("Top priority: fix the strongest academic blocker first before spreading effort across smaller tasks.")
        if latest_finance_event is not None and str(getattr(latest_finance_event, "payment_status", "") or "").lower() not in {"paid", "clear"}:
            key_points.append(
                f"Second priority: reduce finance pressure because the current status is {str(getattr(latest_finance_event, 'payment_status', 'Unknown'))} with overdue amount {float(getattr(latest_finance_event, 'fee_overdue_amount', 0.0) or 0.0):.2f}."
            )
        lms_summary = intelligence.get("lms_summary") or {}
        if lms_summary:
            key_points.append(
                f"Next priority: keep LMS engagement consistent beyond the current {int(lms_summary.get('lms_clicks_7d', 0) or 0)} clicks and {int(lms_summary.get('lms_unique_resources_7d', 0) or 0)} resources in 7 days."
            )
        if weakest is not None:
            key_points.append(
                f"Attendance protection stays in the priority list too: keep {weakest.subject_name} above its current {float(weakest.subject_attendance_percent or 0.0):.2f}%."
            )
        if active_warning is not None:
            key_points.append("Because you already have an active warning, complete the top academic fix first before moving to lower-priority improvements.")
        closing = "If you want, I can turn the top priority into a simple day-by-day weekly plan."
    else:
        opening = "Here is the grounded path to reduce your current HIGH alert posture."
        key_points = [
            "The HIGH label does not go away manually. It comes down when the grounded signals improve in the next scoring cycle.",
            "Your fastest recovery path is to improve the non-attendance drivers that are still pushing risk upward, not only to keep attendance SAFE.",
        ]
        if top_driver_evidence:
            key_points.append("Main risk drivers to reduce first: " + "; ".join(top_driver_evidence[:3]))
        if latest_erp_event is not None:
            key_points.append(
                f"Academic-performance priority: improve assessed performance from the current weighted score of {float(getattr(latest_erp_event, 'weighted_assessment_score', 0.0) or 0.0):.1f} and keep submissions timely."
            )
        lms_summary = intelligence.get("lms_summary") or {}
        if lms_summary:
            key_points.append(
                f"Engagement priority: keep LMS activity consistent beyond the current {int(lms_summary.get('lms_clicks_7d', 0) or 0)} clicks and {int(lms_summary.get('lms_unique_resources_7d', 0) or 0)} resources in 7 days."
            )
        if latest_finance_event is not None and str(getattr(latest_finance_event, "payment_status", "") or "").lower() not in {"paid", "clear"}:
            key_points.append(
                f"Finance priority: resolve the current payment pressure ({str(getattr(latest_finance_event, 'payment_status', 'Unknown'))}, overdue amount {float(getattr(latest_finance_event, 'fee_overdue_amount', 0.0) or 0.0):.2f}) because finance is currently increasing your final risk."
            )
        if weakest is not None:
            key_points.append(
                f"Attendance should stay protected while you recover: your weakest visible subject is {weakest.subject_name} at {float(weakest.subject_attendance_percent or 0.0):.2f}%."
            )
        if active_warning is not None:
            key_points.append("Because you already have an active warning, treat this as a guided recovery period and clear the highest-impact academic blocker first.")
        closing = "If you want, I can break this into attendance, coursework, or a day-by-day weekly recovery plan."

    return (
        build_grounded_response(
            opening=opening,
            key_points=key_points,
            tools_used=[{"tool_name": "student_recovery_focus", "summary": "Used prediction, LMS, ERP, finance, warning, and attendance signals to build a focused student recovery plan"}],
            limitations=[],
            closing=closing,
        ),
        [{"tool_name": "student_recovery_focus", "summary": "Used prediction, LMS, ERP, finance, warning, and attendance signals to build a focused student recovery plan"}],
        [],
        {
            "kind": "student_self",
            "student_id": student_id,
            "intent": "student_recovery_focus",
            "focus": focus,
            "pending_student_follow_up": "day_by_day_plan",
        },
    )


def _answer_student_day_by_day_plan(
    *,
    auth: AuthContext,
    repository: EventRepository,
) -> tuple[str, list[dict], list[str], dict]:
    if auth.student_id is None:
        return (
            "Your student account is missing a linked student record, so I cannot turn this into a weekly plan yet.",
            [],
            ["student token is missing student_id binding"],
            {"kind": "student_self", "student_id": None, "intent": "student_day_by_day_plan"},
        )

    student_id = auth.student_id
    latest_prediction = repository.get_latest_prediction_for_student(student_id)
    current_subject_attendance = repository.get_current_student_subject_attendance_records(student_id)
    signal_bundle = _load_student_signal_bundle(repository=repository, student_id=student_id)
    latest_finance_event = signal_bundle.get("latest_finance_event")
    latest_erp_event = signal_bundle.get("latest_erp_event")
    weakest = next((row for row in current_subject_attendance if row.subject_attendance_percent is not None), None)
    warnings = repository.get_student_warning_history_for_student(student_id)
    active_warning = next((row for row in warnings if row.resolution_status is None), None)

    if latest_prediction is None:
        return _answer_student_weekly_focus(auth=auth, repository=repository)

    day_points = [
        "Day 1: review the highest-impact academic blocker and list the one assessed task you need to fix first.",
        "Day 2: complete or improve the most important pending coursework item before adding new tasks.",
        "Day 3: spend focused time on LMS study engagement and the weakest academic area on your record.",
    ]
    if weakest is not None:
        day_points.append(
            f"Day 4: protect {weakest.subject_name} so your weakest visible subject does not slip below its current {float(weakest.subject_attendance_percent or 0.0):.2f}%."
        )
    if latest_finance_event is not None and str(getattr(latest_finance_event, "payment_status", "") or "").lower() not in {"paid", "clear"}:
        day_points.append("Day 5: resolve or clarify the finance issue on your record so it stops adding avoidable pressure to your final risk.")
    else:
        day_points.append("Day 5: review what improved this week and repeat the strongest academic habit next week.")
    if latest_erp_event is not None:
        day_points.append(
            f"Checkpoint: your current weighted assessment score is {float(getattr(latest_erp_event, 'weighted_assessment_score', 0.0) or 0.0):.1f}, so academic-quality improvement matters more than doing many small low-impact tasks."
        )
    if active_warning is not None:
        day_points.append("Because you have an active warning, treat the first completed academic fix this week as non-negotiable.")

    return (
        build_grounded_response(
            opening="Here is a simple grounded day-by-day recovery plan for this week.",
            key_points=day_points,
            tools_used=[{"tool_name": "student_day_by_day_plan", "summary": "Turned the current student risk, attendance, ERP, LMS, and finance context into a day-by-day recovery plan"}],
            limitations=[],
            closing="If you want, I can next explain which of these steps is most likely to help remove the HIGH risk label first.",
        ),
        [{"tool_name": "student_day_by_day_plan", "summary": "Turned the current student risk, attendance, ERP, LMS, and finance context into a day-by-day recovery plan"}],
        [],
        {
            "kind": "student_self",
            "student_id": student_id,
            "intent": "student_day_by_day_plan",
            "pending_student_follow_up": "risk_label_reduction_explanation",
        },
    )


def _answer_student_label_reduction_explanation(
    *,
    auth: AuthContext,
    repository: EventRepository,
) -> tuple[str, list[dict], list[str], dict]:
    if auth.student_id is None:
        return (
            "Your student account is missing a linked student record, so I cannot explain the strongest recovery lever yet.",
            [],
            ["student token is missing student_id binding"],
            {"kind": "student_self", "student_id": None, "intent": "student_label_reduction_explanation"},
        )

    student_id = auth.student_id
    signal_bundle = _load_student_signal_bundle(repository=repository, student_id=student_id)
    latest_prediction = signal_bundle.get("latest_prediction")
    latest_erp_event = signal_bundle.get("latest_erp_event")
    latest_finance_event = signal_bundle.get("latest_finance_event")
    current_subject_attendance = repository.get_current_student_subject_attendance_records(student_id)
    weakest = next((row for row in current_subject_attendance if row.subject_attendance_percent is not None), None)
    intelligence = signal_bundle.get("intelligence") or {}
    drivers = intelligence.get("drivers") or []
    top_driver_evidence = [str(driver.get("evidence") or "").strip() for driver in drivers[:3] if driver.get("evidence")]

    key_points: list[str] = []
    if latest_erp_event is not None:
        weighted_score = float(getattr(latest_erp_event, "weighted_assessment_score", 0.0) or 0.0)
        submission_rate = float(getattr(latest_erp_event, "assessment_submission_rate", 0.0) or 0.0)
        key_points.append(
            f"The single strongest lever right now is improving assessed coursework quality first, because your weighted assessment score is {weighted_score:.1f} and your submission rate is {submission_rate:.2f}."
        )
    elif top_driver_evidence:
        key_points.append(f"The strongest recovery lever right now is the top visible driver: {top_driver_evidence[0]}.")
    else:
        key_points.append("The strongest recovery lever right now is fixing the highest-impact academic blocker first.")

    if latest_finance_event is not None and str(getattr(latest_finance_event, "payment_status", "") or "").lower() not in {"paid", "clear"}:
        key_points.append(
            f"Second lever: reduce finance drag because the current status is {str(getattr(latest_finance_event, 'payment_status', 'Unknown'))} with overdue amount {float(getattr(latest_finance_event, 'fee_overdue_amount', 0.0) or 0.0):.2f}."
        )
    if weakest is not None:
        key_points.append(
            f"Keep attendance protected while you recover: your weakest visible subject is {weakest.subject_name} at {float(weakest.subject_attendance_percent or 0.0):.2f}%."
        )
    if latest_prediction is not None:
        key_points.append(
            f"The HIGH label should come down only after the next scoring cycle sees stronger coursework quality and lower overall pressure than the current probability {float(latest_prediction.final_risk_probability):.4f}."
        )
    if len(top_driver_evidence) > 1:
        key_points.append("Visible supporting drivers after coursework: " + "; ".join(top_driver_evidence[1:3]))

    return (
        build_grounded_response(
            opening="Here is the step most likely to help remove the HIGH risk label first.",
            key_points=key_points,
            tools_used=[{"tool_name": "student_label_reduction_explanation", "summary": "Explained the strongest grounded recovery lever using coursework, finance, attendance, and prediction context"}],
            limitations=[],
            closing="If you want, I can now turn this into a week-by-week recovery plan instead of a one-week checklist.",
        ),
        [{"tool_name": "student_label_reduction_explanation", "summary": "Explained the strongest grounded recovery lever using coursework, finance, attendance, and prediction context"}],
        [],
        {
            "kind": "student_self",
            "student_id": student_id,
            "intent": "student_label_reduction_explanation",
            "pending_student_follow_up": "multi_week_plan",
        },
    )


def _answer_student_multi_week_plan(
    *,
    auth: AuthContext,
    repository: EventRepository,
    week_number: int | None,
) -> tuple[str, list[dict], list[str], dict]:
    if auth.student_id is None:
        return (
            "Your student account is missing a linked student record, so I cannot build a multi-week recovery plan yet.",
            [],
            ["student token is missing student_id binding"],
            {"kind": "student_self", "student_id": None, "intent": "student_multi_week_plan"},
        )

    student_id = auth.student_id
    signal_bundle = _load_student_signal_bundle(repository=repository, student_id=student_id)
    latest_erp_event = signal_bundle.get("latest_erp_event")
    latest_finance_event = signal_bundle.get("latest_finance_event")
    current_subject_attendance = repository.get_current_student_subject_attendance_records(student_id)
    weakest = next((row for row in current_subject_attendance if row.subject_attendance_percent is not None), None)

    week_1 = [
        "Week 1: stabilize the highest-impact academic blocker and complete the most important coursework fix first.",
        "Week 1: do not let new missed submissions appear while you are still recovering the weakest academic signal.",
    ]
    week_2 = [
        "Week 2: consolidate the first academic fix by improving one more assessed coursework item instead of starting too many smaller tasks.",
        "Week 2: review whether the same blocker is still dragging your score down and correct it before the next scoring cycle.",
    ]
    week_3 = [
        "Week 3: keep the academic gains stable, protect attendance, and make sure the same risk drivers are not returning.",
        "Week 3: move from emergency recovery into consistency, so the next model cycle sees sustained improvement rather than a one-off spike.",
    ]

    if weakest is not None:
        week_1.append(
            f"Attendance protection in Week 1: keep {weakest.subject_name} above {float(weakest.subject_attendance_percent or 0.0):.2f}% while you fix the academic side."
        )
        week_2.append(
            f"Attendance check in Week 2: make sure {weakest.subject_name} does not slip while coursework pressure is still being repaired."
        )
    if latest_erp_event is not None:
        week_1.append(
            f"Current academic anchor: your weighted assessment score is {float(getattr(latest_erp_event, 'weighted_assessment_score', 0.0) or 0.0):.1f}, so quality improvement matters more than low-impact busy work."
        )
    if latest_finance_event is not None and str(getattr(latest_finance_event, "payment_status", "") or "").lower() not in {"paid", "clear"}:
        week_2.append(
            f"Week 2 finance cleanup: reduce the current {str(getattr(latest_finance_event, 'payment_status', 'Unknown'))} pressure so it stops adding avoidable risk drag."
        )

    if week_number == 2:
        opening = "Here is what you should do in the second week of recovery."
        key_points = week_2 + ["Use Week 2 to reinforce the first improvement, not to restart from zero."]
    elif week_number == 3:
        opening = "Here is what you should do in the third week of recovery."
        key_points = week_3 + ["Week 3 is about keeping the recovery stable enough that the next risk cycle can actually reward it."]
    elif week_number == 4:
        opening = "Here is what you should do in the fourth week of recovery."
        key_points = [
            "Week 4: review whether the strongest drivers have genuinely cooled down, not just shifted temporarily.",
            "Week 4: keep the new academic and attendance habits consistent so the next cycle does not reopen the same pressure pattern.",
        ]
    else:
        opening = "Here is a grounded week-by-week recovery plan."
        key_points = week_1 + week_2 + week_3

    return (
        build_grounded_response(
            opening=opening,
            key_points=key_points,
            tools_used=[{"tool_name": "student_multi_week_plan", "summary": "Built a staged student recovery plan across multiple weeks using coursework, finance, attendance, and prediction context"}],
            limitations=[],
            closing="If you want, I can next narrow this into just attendance, coursework, or finance priorities.",
        ),
        [{"tool_name": "student_multi_week_plan", "summary": "Built a staged student recovery plan across multiple weeks using coursework, finance, attendance, and prediction context"}],
        [],
        {
            "kind": "student_self",
            "student_id": student_id,
            "intent": "student_multi_week_plan",
            "pending_student_follow_up": "multi_week_plan",
        },
    )


def _build_academic_scope_summary(
    *,
    repository: EventRepository,
    student_ids: set[int] | None = None,
) -> dict:
    snapshot = build_academic_pressure_snapshot(
        repository,
        student_ids=student_ids,
        subject_limit=6,
        bucket_limit=6,
        top_student_limit=8,
    )
    return {
        "total_students": int(snapshot["total_students"]),
        "total_students_with_overall_shortage": int(snapshot["total_students_with_overall_shortage"]),
        "total_students_with_i_grade_risk": int(snapshot["total_students_with_i_grade_risk"]),
        "total_students_with_r_grade_risk": int(snapshot["total_students_with_r_grade_risk"]),
        "top_students": list(snapshot["top_students"]),
        "top_subjects": list(snapshot["top_subjects"]),
        "branch_pressure": list(snapshot["branch_pressure"]),
        "semester_pressure": list(snapshot["semester_pressure"]),
        "ranked_branches": [
            {
                "branch": item["bucket_label"],
                "students": item["total_students"],
                "overall_shortage": item["students_with_overall_shortage"],
                "i_grade": item["students_with_i_grade_risk"],
                "r_grade": item["students_with_r_grade_risk"],
            }
            for item in snapshot["branch_pressure"]
        ],
    }


def _build_attendance_risk_totals(
    *,
    repository: EventRepository,
    student_ids: set[int] | None = None,
) -> dict[str, int]:
    semester_rows = repository.get_latest_student_semester_progress_records_for_students(student_ids)
    return {
        "total_students": len(semester_rows),
        "total_students_with_overall_shortage": sum(
            1 for row in semester_rows if str(row.overall_status or "").strip().upper() == "SHORTAGE"
        ),
        "total_students_with_i_grade_risk": sum(1 for row in semester_rows if bool(row.has_i_grade_risk)),
        "total_students_with_r_grade_risk": sum(1 for row in semester_rows if bool(row.has_r_grade_risk)),
    }


def _build_active_burden_scope_summary(
    *,
    repository: EventRepository,
    student_ids: set[int] | None = None,
) -> dict[str, int]:
    student_scope = None if student_ids is None else {int(student_id) for student_id in student_ids}
    if student_scope == set():
        return {
            "total_students_with_active_academic_burden": 0,
            "total_students_with_active_i_grade_burden": 0,
            "total_students_with_active_r_grade_burden": 0,
        }

    academic_rows = repository.get_student_academic_records_for_students(student_scope)
    attendance_rows = repository.get_current_student_subject_attendance_records_for_students(student_scope)
    academic_by_student: dict[int, list[StudentAcademicRecord]] = {}
    attendance_by_student: dict[int, list[StudentSubjectAttendanceRecord]] = {}

    for row in academic_rows:
        academic_by_student.setdefault(int(row.student_id), []).append(row)
    for row in attendance_rows:
        attendance_by_student.setdefault(int(row.student_id), []).append(row)

    all_student_ids = set(academic_by_student) | set(attendance_by_student)
    total_active_burden = 0
    total_active_i_grade_burden = 0
    total_active_r_grade_burden = 0

    for student_id in all_student_ids:
        summary = build_academic_burden_summary(
            academic_rows=academic_by_student.get(student_id, []),
            attendance_rows=attendance_by_student.get(student_id, []),
        )
        if summary["has_active_burden"]:
            total_active_burden += 1
        if summary["has_active_i_grade_burden"]:
            total_active_i_grade_burden += 1
        if summary["has_active_r_grade_burden"]:
            total_active_r_grade_burden += 1

    return {
        "total_students_with_active_academic_burden": total_active_burden,
        "total_students_with_active_i_grade_burden": total_active_i_grade_burden,
        "total_students_with_active_r_grade_burden": total_active_r_grade_burden,
    }


def _build_active_burden_student_rows(
    *,
    repository: EventRepository,
    student_ids: set[int] | None = None,
) -> list[dict[str, object]]:
    academic_query = repository.db.query(StudentAcademicRecord)
    attendance_query = repository.db.query(StudentSubjectAttendanceRecord)
    if student_ids:
        academic_query = academic_query.filter(StudentAcademicRecord.student_id.in_(student_ids))
        attendance_query = attendance_query.filter(StudentSubjectAttendanceRecord.student_id.in_(student_ids))

    academic_rows = academic_query.all()
    attendance_rows = attendance_query.all()
    academic_by_student: dict[int, list[StudentAcademicRecord]] = {}
    attendance_by_student: dict[int, list[StudentSubjectAttendanceRecord]] = {}

    for row in academic_rows:
        academic_by_student.setdefault(int(row.student_id), []).append(row)
    for row in attendance_rows:
        attendance_by_student.setdefault(int(row.student_id), []).append(row)

    all_student_ids = set(academic_by_student) | set(attendance_by_student)
    results: list[dict[str, object]] = []
    for student_id in all_student_ids:
        summary = build_academic_burden_summary(
            academic_rows=academic_by_student.get(student_id, []),
            attendance_rows=attendance_by_student.get(student_id, []),
        )
        if not summary["has_active_burden"]:
            continue
        results.append(
            {
                "student_id": student_id,
                "summary": str(summary["summary"]),
                "monitoring_cadence": str(summary["monitoring_cadence"]),
                "active_i_grade_count": len(summary["active_i_grade_subjects"]),
                "active_r_grade_count": len(summary["active_r_grade_subjects"]),
            }
        )
    results.sort(
        key=lambda item: (
            0 if item["monitoring_cadence"] == "WEEKLY" else 1,
            -int(item["active_r_grade_count"]),
            -int(item["active_i_grade_count"]),
            int(item["student_id"]),
        )
    )
    return results


def _build_prediction_and_attendance_breakdown(
    *,
    repository: EventRepository,
    student_ids: set[int] | None = None,
) -> dict:
    profiles = repository.get_imported_student_profiles()
    if student_ids:
        profiles = [row for row in profiles if int(row.student_id) in student_ids]
    progress_rows = repository.get_student_academic_progress_records_for_students(student_ids)
    semester_rows = repository.get_latest_student_semester_progress_records_for_students(student_ids)
    latest_predictions = repository.get_latest_predictions_for_all_students()
    if student_ids:
        latest_predictions = [
            row for row in latest_predictions if int(row.student_id) in student_ids
        ]

    profile_by_student = {int(row.student_id): row for row in profiles}
    progress_by_student = {int(row.student_id): row for row in progress_rows}
    semester_by_student = {int(row.student_id): row for row in semester_rows}
    prediction_by_student = {int(row.student_id): row for row in latest_predictions}

    semester_buckets: dict[str, dict[str, int]] = {}
    year_buckets: dict[str, dict[str, int]] = {}
    branch_buckets: dict[str, dict[str, int]] = {}
    gender_buckets: dict[str, dict[str, int]] = {}
    age_band_buckets: dict[str, dict[str, int]] = {}
    batch_buckets: dict[str, dict[str, int]] = {}
    program_type_buckets: dict[str, dict[str, int]] = {}
    category_buckets: dict[str, dict[str, int]] = {}
    region_buckets: dict[str, dict[str, int]] = {}
    income_buckets: dict[str, dict[str, int]] = {}
    outcome_buckets: dict[str, dict[str, int]] = {}

    def _ensure_bucket(source: dict[str, dict[str, int]], label: str) -> dict[str, int]:
        return source.setdefault(
            label,
            {
                "total_students": 0,
                "prediction_high_risk": 0,
                "overall_shortage": 0,
                "i_grade_risk": 0,
                "r_grade_risk": 0,
            },
        )

    all_student_ids = set(progress_by_student) | set(semester_by_student) | set(prediction_by_student)
    for student_id in sorted(all_student_ids):
        profile = profile_by_student.get(student_id)
        progress = progress_by_student.get(student_id)
        semester = semester_by_student.get(student_id)
        prediction = prediction_by_student.get(student_id)

        profile_context = getattr(profile, "profile_context", None) or {}
        year_value = getattr(semester, "year", None) or getattr(progress, "current_year", None)
        semester_value = getattr(semester, "semester", None) or getattr(progress, "current_semester", None)
        branch_value = (
            getattr(progress, "branch", None)
            or getattr(semester, "branch", None)
            or profile_context.get("branch")
        )
        gender_value = getattr(profile, "gender", None) or profile_context.get("gender")
        age_band_value = getattr(profile, "age_band", None) or profile_context.get("age_band")
        batch_value = profile_context.get("batch")
        program_type_value = (
            getattr(progress, "program_type", None)
            or profile_context.get("program_type")
        )
        category_value = profile_context.get("category")
        region_value = profile_context.get("region")
        income_value = profile_context.get("income")
        outcome_value = (
            getattr(progress, "current_academic_status", None)
            or profile_context.get("outcome_status")
            or profile_context.get("status")
        )

        year_label = f"Year {int(year_value)}" if year_value is not None else "Unknown Year"
        if year_value is not None and semester_value is not None:
            semester_label = f"Year {int(year_value)} Sem {int(semester_value)}"
        elif semester_value is not None:
            semester_label = f"Sem {int(semester_value)}"
        else:
            semester_label = "Unknown Semester"
        branch_label = str(branch_value).strip() if branch_value not in (None, "") else "Unknown Branch"
        gender_label = str(gender_value).strip() if gender_value not in (None, "") else "Unknown Gender"
        age_band_label = str(age_band_value).strip() if age_band_value not in (None, "") else "Unknown Age Band"
        batch_label = str(batch_value).strip() if batch_value not in (None, "") else "Unknown Batch"
        program_type_label = str(program_type_value).strip() if program_type_value not in (None, "") else "Unknown Program"
        category_label = str(category_value).strip() if category_value not in (None, "") else "Unknown Category"
        region_label = str(region_value).strip() if region_value not in (None, "") else "Unknown Region"
        income_label = str(income_value).strip() if income_value not in (None, "") else "Unknown Income"
        outcome_label = str(outcome_value).strip() if outcome_value not in (None, "") else "Unknown Status"

        year_bucket = _ensure_bucket(year_buckets, year_label)
        semester_bucket = _ensure_bucket(semester_buckets, semester_label)
        branch_bucket = _ensure_bucket(branch_buckets, branch_label)
        gender_bucket = _ensure_bucket(gender_buckets, gender_label)
        age_band_bucket = _ensure_bucket(age_band_buckets, age_band_label)
        batch_bucket = _ensure_bucket(batch_buckets, batch_label)
        program_type_bucket = _ensure_bucket(program_type_buckets, program_type_label)
        category_bucket = _ensure_bucket(category_buckets, category_label)
        region_bucket = _ensure_bucket(region_buckets, region_label)
        income_bucket = _ensure_bucket(income_buckets, income_label)
        outcome_bucket = _ensure_bucket(outcome_buckets, outcome_label)

        for bucket in (
            year_bucket,
            semester_bucket,
            branch_bucket,
            gender_bucket,
            age_band_bucket,
            batch_bucket,
            program_type_bucket,
            category_bucket,
            region_bucket,
            income_bucket,
            outcome_bucket,
        ):
            bucket["total_students"] += 1
            if prediction is not None and int(getattr(prediction, "final_predicted_class", 0)) == 1:
                bucket["prediction_high_risk"] += 1
            if semester is not None and str(getattr(semester, "overall_status", "") or "").strip().upper() == "SHORTAGE":
                bucket["overall_shortage"] += 1
            if semester is not None and bool(getattr(semester, "has_i_grade_risk", False)):
                bucket["i_grade_risk"] += 1
            if semester is not None and bool(getattr(semester, "has_r_grade_risk", False)):
                bucket["r_grade_risk"] += 1

    def _sorted_items(source: dict[str, dict[str, int]]) -> list[dict[str, int | str]]:
        return sorted(
            [
                {"bucket_label": label, **values}
                for label, values in source.items()
            ],
            key=lambda item: (
                int(item["prediction_high_risk"]),
                int(item["r_grade_risk"]),
                int(item["i_grade_risk"]),
                int(item["overall_shortage"]),
                int(item["total_students"]),
            ),
            reverse=True,
        )

    return {
        "semester_breakdown": _sorted_items(semester_buckets),
        "year_breakdown": _sorted_items(year_buckets),
        "branch_breakdown": _sorted_items(branch_buckets),
        "gender_breakdown": _sorted_items(gender_buckets),
        "age_band_breakdown": _sorted_items(age_band_buckets),
        "batch_breakdown": _sorted_items(batch_buckets),
        "program_type_breakdown": _sorted_items(program_type_buckets),
        "category_breakdown": _sorted_items(category_buckets),
        "region_breakdown": _sorted_items(region_buckets),
        "income_breakdown": _sorted_items(income_buckets),
        "outcome_status_breakdown": _sorted_items(outcome_buckets),
    }


def _grouped_breakdown_rows_for_dimension(*, risk_breakdown: dict, grouped_by: str) -> list[dict[str, object]]:
    if not grouped_by:
        return []
    return list(risk_breakdown.get(f"{grouped_by}_breakdown") or [])


def _resolve_role_focus_bucket(
    *,
    risk_breakdown: dict,
    last_context: dict,
) -> tuple[str | None, dict[str, object] | None]:
    grouped_by = str(last_context.get("grouped_by") or "").strip().lower()
    if not grouped_by:
        return None, None
    rows = _grouped_breakdown_rows_for_dimension(risk_breakdown=risk_breakdown, grouped_by=grouped_by)
    if not rows:
        return grouped_by, None
    requested_focus = str(last_context.get("focus_bucket") or "").strip().lower()
    if requested_focus:
        for row in rows:
            bucket_label = str(row.get("bucket_label") or "").strip()
            if bucket_label.lower() == requested_focus:
                return grouped_by, row
    return grouped_by, rows[0]


def _build_lightweight_counsellor_queue_items(
    *,
    profiles: list[object],
    latest_predictions: dict[int, object],
    student_ids: set[int] | None = None,
    limit: int = 5,
) -> list[object]:
    scoped_ids = None if student_ids is None else {int(student_id) for student_id in student_ids}
    ranked_profiles = []
    for profile in profiles:
        student_id = int(getattr(profile, "student_id"))
        if scoped_ids is not None and student_id not in scoped_ids:
            continue
        prediction = latest_predictions.get(student_id)
        probability = float(getattr(prediction, "final_risk_probability", 0.0) or 0.0)
        predicted_class = int(getattr(prediction, "final_predicted_class", 0) or 0)
        if predicted_class == 1:
            priority_label = "HIGH"
            sla_status = "active"
        else:
            priority_label = "WATCH"
            sla_status = "monitoring"
        ranked_profiles.append(
            (
                probability,
                student_id,
                SimpleNamespace(
                    student_id=student_id,
                    priority_label=priority_label,
                    sla_status=sla_status,
                    final_risk_probability=probability,
                ),
            )
        )
    ranked_profiles.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked_profiles[:limit]]


def _answer_role_operational_actions(
    *,
    role: str,
    scope_label: str,
    repository: EventRepository,
    auth: AuthContext,
    planner: dict,
    last_context: dict,
    academic_summary: dict,
    burden_summary: dict,
    risk_breakdown: dict,
    queue_items: list[object],
) -> tuple[str, list[dict], list[str], dict]:
    tool_prefix = "admin" if role == "admin" else "counsellor"
    original_lowered = str(planner.get("original_message") or "").strip().lower()
    grouped_by, focus_bucket = _resolve_role_focus_bucket(
        risk_breakdown=risk_breakdown,
        last_context=last_context,
    )
    top_subject = academic_summary["top_subjects"][0] if academic_summary.get("top_subjects") else None
    top_branch = academic_summary["branch_pressure"][0] if academic_summary.get("branch_pressure") else None
    top_semester = academic_summary["semester_pressure"][0] if academic_summary.get("semester_pressure") else None
    top_queue_items = queue_items[:3]

    if role == "counsellor":
        asks_help = "help" in original_lowered
        asks_intervention = "intervention" in original_lowered
        asks_reduce_risk = "reduce" in original_lowered or "their risk" in original_lowered
        asks_needed_actions = "actions are needed" in original_lowered
        opening = "Here is the grounded operational action list for your current counsellor scope."
        if asks_help:
            opening = "Here is the grounded support plan for helping the highest-pressure students in your counsellor scope."
        elif asks_intervention:
            opening = "Here is the grounded intervention plan for the students currently needing the fastest counsellor action."
        elif asks_reduce_risk:
            opening = "Here is the grounded risk-reduction plan for your current counsellor scope."
        elif asks_needed_actions:
            opening = "Here are the grounded actions currently needed across your counsellor scope."
        key_points: list[str] = []
        if focus_bucket is not None and grouped_by:
            key_points.append(
                f"Start with the most pressured `{grouped_by}` bucket in your current view: `{focus_bucket['bucket_label']}`. "
                f"It currently shows prediction high risk {int(focus_bucket.get('prediction_high_risk') or 0)}, "
                f"overall shortage {int(focus_bucket.get('overall_shortage') or 0)}, "
                f"I-grade risk {int(focus_bucket.get('i_grade_risk') or 0)}, and "
                f"R-grade risk {int(focus_bucket.get('r_grade_risk') or 0)}."
            )
        elif top_branch is not None:
            key_points.append(
                f"Start with the most pressured branch in your scoped cohort: `{top_branch['bucket_label']}`."
            )
        if top_queue_items:
            queue_line = (
                "; ".join(
                    f"student_id {int(item.student_id)} ({item.priority_label.lower()} priority, {item.sla_status.lower()} SLA)"
                    for item in top_queue_items
                )
            )
            if asks_help:
                key_points.append(
                    "Start by personally checking in with these students first and pinning one concrete blocker for each: "
                    + queue_line
                )
            elif asks_intervention:
                key_points.append(
                    "Intervene first on the current queue leaders, because they already sit at the front of the operational risk line: "
                    + queue_line
                )
            elif asks_reduce_risk:
                key_points.append(
                    "Risk will come down fastest if you move these queue leaders first, because they currently carry the strongest immediate pressure: "
                    + queue_line
                )
            elif asks_needed_actions:
                key_points.append(
                    "Immediate action queue: "
                    + queue_line
                )
            else:
                key_points.append(
                    "This week, review the top queue students first: "
                    + queue_line
                )
        if int(burden_summary.get("total_students_with_active_r_grade_burden") or 0) > 0:
            if asks_intervention:
                key_points.append(
                    f"Treat unresolved R-grade cases as your strictest intervention lane. Right now {int(burden_summary.get('total_students_with_active_r_grade_burden') or 0)} students still need weekly monitoring."
                )
            elif asks_reduce_risk:
                key_points.append(
                    f"One of the clearest risk-reduction moves is to keep unresolved R-grade cases on weekly monitoring. That currently affects {int(burden_summary.get('total_students_with_active_r_grade_burden') or 0)} students in your scope."
                )
            else:
                key_points.append(
                    f"Keep unresolved R-grade cases on weekly monitoring. Right now that affects {int(burden_summary.get('total_students_with_active_r_grade_burden') or 0)} students in your scope."
                )
        if int(burden_summary.get("total_students_with_active_i_grade_burden") or 0) > 0:
            if asks_help:
                key_points.append(
                    f"Keep unresolved I-grade cases on supportive monthly review so students do not silently drift. That currently affects {int(burden_summary.get('total_students_with_active_i_grade_burden') or 0)} students in your scope."
                )
            else:
                key_points.append(
                    f"Keep unresolved I-grade cases on at least monthly review. Right now that affects {int(burden_summary.get('total_students_with_active_i_grade_burden') or 0)} students in your scope."
                )
        if top_subject is not None:
            if asks_reduce_risk:
                key_points.append(
                    f"Another risk-reduction lever is attendance recovery around `{top_subject['subject_name']}`, because it is currently pulling {int(top_subject['students_below_threshold'])} students below threshold."
                )
            elif asks_intervention:
                key_points.append(
                    f"Use `{top_subject['subject_name']}` as the first intervention hotspot, because it is currently pulling {int(top_subject['students_below_threshold'])} students below threshold."
                )
            else:
                key_points.append(
                    f"Coordinate attendance recovery around `{top_subject['subject_name']}` first, because it is currently pulling {int(top_subject['students_below_threshold'])} students below threshold."
                )
        if asks_help:
            key_points.append(
                "When you contact each student, lead with one concrete support move: attendance recovery, coursework completion, or burden-clearance follow-up. Avoid vague encouragement without a named blocker."
            )
        elif asks_intervention:
            key_points.append(
                "Make each intervention explicit: one blocker, one owner, one next review date. Avoid generic counselling notes that do not change student behavior."
            )
        elif asks_reduce_risk:
            key_points.append(
                "To reduce risk, convert each contact into one measurable improvement target: a coursework catch-up, an attendance recovery step, or a burden-clearance follow-up."
            )
        elif asks_needed_actions:
            key_points.append(
                "Across the scope, the needed actions are: move the queue first, sustain burden monitoring, and turn every student contact into one measurable next step."
            )
        else:
            key_points.append(
                "Turn each contacted student into one concrete next action: attendance recovery, coursework completion, or burden-clearance follow-up. Avoid generic check-ins without a named blocker."
            )
        closing = "If you want, I can narrow this into a bucket-specific counsellor action list or list the exact students to contact first."
        if asks_help:
            closing = "If you want, I can narrow this into a student-by-student support list for the first outreach round."
        elif asks_intervention:
            closing = "If you want, I can narrow this into a sharper intervention list with the exact students to act on first."
        elif asks_reduce_risk:
            closing = "If you want, I can narrow this into the highest-impact risk-reduction moves for the top students first."
    else:
        opening = "Here is the grounded institution-level action list from the current retention picture."
        key_points = []
        if focus_bucket is not None and grouped_by:
            key_points.append(
                f"Start with the most pressured `{grouped_by}` bucket in the current view: `{focus_bucket['bucket_label']}`. "
                f"It currently shows prediction high risk {int(focus_bucket.get('prediction_high_risk') or 0)}, "
                f"overall shortage {int(focus_bucket.get('overall_shortage') or 0)}, "
                f"I-grade risk {int(focus_bucket.get('i_grade_risk') or 0)}, and "
                f"R-grade risk {int(focus_bucket.get('r_grade_risk') or 0)}."
            )
        elif top_branch is not None:
            key_points.append(
                f"Start with the most pressured branch right now: `{top_branch['bucket_label']}`."
            )
        if top_queue_items:
            key_points.append(
                "First operational move: clear the intervention gap on the top queue students: "
                + "; ".join(
                    f"student_id {int(item.student_id)} ({item.priority_label.lower()} priority, probability {float(item.final_risk_probability):.4f})"
                    for item in top_queue_items
                )
            )
        if top_subject is not None:
            key_points.append(
                f"Academic operations move: escalate `{top_subject['subject_name']}` first, because it is the top attendance hotspot with {int(top_subject['students_below_threshold'])} students below threshold."
            )
        if top_semester is not None:
            key_points.append(
                f"Governance move: review the semester slice `{top_semester['bucket_label']}` because it currently has the strongest visible attendance-policy pressure."
            )
        if int(burden_summary.get("total_students_with_active_r_grade_burden") or 0) > 0:
            key_points.append(
                f"Carry-forward governance: keep unresolved R-grade burden on weekly review across the institution. That currently affects {int(burden_summary.get('total_students_with_active_r_grade_burden') or 0)} students."
            )
        if int(burden_summary.get("total_students_with_active_i_grade_burden") or 0) > 0:
            key_points.append(
                f"Carry-forward governance: keep unresolved I-grade burden on monthly audit until subjects are actually cleared. That currently affects {int(burden_summary.get('total_students_with_active_i_grade_burden') or 0)} students."
            )
        closing = "If you want, I can narrow this into a branch-specific, semester-specific, or subject-specific admin action list."

    tools_used = [
        {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Mapped the role question into a grounded operational advisory plan"},
        {"tool_name": f"{tool_prefix}_operational_action_advisor", "summary": f"Combined queue, attendance pressure, and carry-forward burden into an action list for {scope_label}"},
    ]
    return (
        build_grounded_response(
            opening=opening,
            key_points=key_points,
            tools_used=tools_used,
            limitations=[],
            closing=closing,
        ),
        tools_used,
        [],
        {
            "kind": "cohort" if role == "counsellor" else "import_coverage",
            "intent": f"{tool_prefix}_operational_actions",
            "role_scope": tool_prefix,
            "student_ids": list(last_context.get("student_ids") or []),
            "grouped_by": grouped_by or "",
            "bucket_values": list(last_context.get("bucket_values") or []),
            "focus_bucket": str(focus_bucket.get("bucket_label") or "").strip() if focus_bucket is not None else "",
            "pending_role_follow_up": "operational_actions",
            "planner_version": str(planner.get("version") or COPILOT_SYSTEM_PROMPT_VERSION),
        },
    )


def _build_grouped_risk_breakdown_answer(
    *,
    scope_label: str,
    lowered: str,
    planner: dict,
    risk_breakdown: dict,
    prediction_high_risk_count: int,
    overall_shortage_count: int,
    i_grade_count: int,
    r_grade_count: int,
    tool_prefix: str,
) -> tuple[str, list[dict], list[str], dict]:
    requested_grouping = list(planner.get("grouping") or [])
    requested_metrics = list(planner.get("metrics") or [])
    if not requested_grouping:
        if any(token in lowered for token in {"semester", "sem"}):
            requested_grouping.append("semester")
        if "year" in lowered:
            requested_grouping.append("year")
    if not requested_metrics:
        requested_metrics = ["prediction_high_risk", "overall_shortage", "i_grade_risk", "r_grade_risk"]

    include_prediction = "prediction_high_risk" in requested_metrics
    include_overall = "overall_shortage" in requested_metrics
    include_i_grade = "i_grade_risk" in requested_metrics
    include_r_grade = "r_grade_risk" in requested_metrics
    requested_section_count = max(1, len(requested_grouping))
    shared_limit = 2 if requested_section_count >= 3 else 3 if requested_section_count == 2 else 5
    section_metadata = {
        "semester": ("Semester-wise breakdown:", "semester_breakdown", shared_limit),
        "year": ("Year-wise breakdown:", "year_breakdown", shared_limit),
        "branch": ("Branch-wise breakdown:", "branch_breakdown", shared_limit),
        "gender": ("Gender-wise breakdown:", "gender_breakdown", shared_limit),
        "age_band": ("Age-band-wise breakdown:", "age_band_breakdown", shared_limit),
        "batch": ("Batch-wise breakdown:", "batch_breakdown", shared_limit),
        "program_type": ("Program-wise breakdown:", "program_type_breakdown", shared_limit),
        "category": ("Category-wise breakdown:", "category_breakdown", shared_limit),
        "region": ("Region-wise breakdown:", "region_breakdown", shared_limit),
        "income": ("Income-wise breakdown:", "income_breakdown", shared_limit),
        "outcome_status": ("Status-wise breakdown:", "outcome_status_breakdown", shared_limit),
    }

    def _format_bucket(item: dict[str, int | str]) -> str:
        parts = []
        if include_prediction:
            parts.append(f"prediction high risk {item['prediction_high_risk']}")
        if include_overall:
            parts.append(f"overall shortage {item['overall_shortage']}")
        if include_i_grade:
            parts.append(f"I-grade {item['i_grade_risk']}")
        if include_r_grade:
            parts.append(f"R-grade {item['r_grade_risk']}")
        if not parts:
            parts.append(f"prediction high risk {item['prediction_high_risk']}")
        return f"{item['bucket_label']}: " + ", ".join(parts) + "."

    key_points: list[str] = []
    for grouping_key in requested_grouping:
        metadata = section_metadata.get(grouping_key)
        if metadata is None:
            continue
        heading, breakdown_key, limit = metadata
        rows = risk_breakdown.get(breakdown_key) or []
        key_points.append(heading)
        key_points.extend(_format_bucket(item) for item in rows[:limit])

    if include_prediction and (include_overall or include_i_grade or include_r_grade):
        opening = (
            f"I am separating two different layers for {scope_label}. "
            f"Prediction high risk is currently {prediction_high_risk_count} students from the risk model, "
            f"while the attendance-policy layer shows {overall_shortage_count} overall-shortage students, "
            f"{i_grade_count} with I-grade risk, and {r_grade_count} with R-grade risk."
        )
        key_points.insert(
            0,
            "Generic 'high risk' can mean either the prediction model or the attendance-policy risk layer, so I am showing both separately.",
        )
    elif include_prediction:
        opening = f"Here is the grouped prediction-high-risk breakdown for {scope_label}."
    else:
        opening = f"Here is the grouped attendance-policy risk breakdown for {scope_label}."

    tools_used = [
        {"tool_name": f"{tool_prefix}_intent_router", "summary": "Routed a grouped academic risk breakdown request"},
        {"tool_name": f"{tool_prefix}_prediction_and_attendance_breakdown", "summary": "Grouped prediction risk and attendance-policy risk by the requested academic dimensions"},
    ]
    content_lines = [opening, "", "What I found:"]
    for point in key_points:
        content_lines.append(f"- {point}")
    content_lines.extend(
        [
            "",
            "If you want, I can next list the exact students inside any one grouped bucket or turn this into an operational action list.",
        ]
    )
    content = "\n".join(content_lines)
    memory_context = {
        "kind": f"{tool_prefix}_academic",
        "intent": "grouped_risk_breakdown",
        "pending_role_follow_up": "operational_actions",
    }
    if len(requested_grouping) == 1:
        grouping_key = requested_grouping[0]
        metadata = section_metadata.get(grouping_key)
        rows = risk_breakdown.get(metadata[1], []) if metadata is not None else []
        memory_context = {
            "kind": "import_coverage",
            "intent": "grouped_risk_breakdown",
            "grouped_by": grouping_key,
            "bucket_values": [str(item.get("bucket_label", "")).strip() for item in rows if str(item.get("bucket_label", "")).strip()],
            "role_scope": tool_prefix,
            "pending_role_follow_up": "operational_actions",
        }
    return (
        content,
        tools_used,
        [],
        memory_context,
    )


def _answer_admin_operational_actions_fast(
    *,
    planner: dict,
    last_context: dict,
    risk_breakdown: dict,
    latest_predictions: list[object],
) -> tuple[str, list[dict], list[str], dict]:
    lowered = str(planner.get("normalized_message") or planner.get("original_message") or "").strip().lower()
    original_lowered = str(planner.get("original_message") or lowered).strip().lower()
    previous_action_stage = int(last_context.get("action_stage") or 1)
    generic_progression = lowered in {"ok", "okay", "continue", "proceed", "then", "what next", "more"}
    grouped_by, focus_bucket = _resolve_role_focus_bucket(
        risk_breakdown=risk_breakdown,
        last_context=last_context,
    )
    top_branch = (risk_breakdown.get("branch_breakdown") or [None])[0]
    top_semester = (risk_breakdown.get("semester_breakdown") or [None])[0]
    branch_specific_requested = any(
        token in lowered
        for token in {
            "branch-specific",
            "branch specific",
            "highest-pressure branch",
            "highest pressure branch",
        }
    )
    semester_specific_requested = any(
        token in lowered
        for token in {
            "semester-specific",
            "semester specific",
            "highest-pressure semester",
            "highest pressure semester",
        }
    )
    strategic_plan_requested = any(
        token in original_lowered or token in lowered
        for token in {
            "give strategic plan",
            "give strategic roadmap",
            "strategic plan",
            "strategic roadmap",
        }
    )
    branch_priority_requested = any(
        token in original_lowered
        for token in {
            "which branch should we prioritize",
            "which branch needs urgent attention",
            "where should we focus",
            "where should we take action first",
        }
    )
    if generic_progression and str(last_context.get("intent") or "").strip().lower() == "admin_operational_actions":
        if previous_action_stage >= 2:
            semester_specific_requested = True
            branch_specific_requested = False
        else:
            branch_specific_requested = True
    elif (
        str(last_context.get("intent") or "").strip().lower() == "admin_operational_actions"
        and previous_action_stage >= 2
        and "branch-specific admin action list" in lowered
    ):
        semester_specific_requested = True
        branch_specific_requested = False
    top_high_risk = sorted(
        [
            row
            for row in latest_predictions
            if int(getattr(row, "final_predicted_class", 0) or 0) == 1
        ],
        key=lambda row: (
            -float(getattr(row, "final_risk_probability", 0.0) or 0.0),
            int(getattr(row, "student_id", 0) or 0),
        ),
    )[:3]

    key_points: list[str] = []
    if branch_specific_requested and top_branch is not None:
        grouped_by = "branch"
        focus_bucket = top_branch
        key_points.append(
            f"Focus the next admin pass on branch `{top_branch['bucket_label']}` first. It currently shows prediction high risk {int(top_branch.get('prediction_high_risk') or 0)}, overall shortage {int(top_branch.get('overall_shortage') or 0)}, I-grade risk {int(top_branch.get('i_grade_risk') or 0)}, and R-grade risk {int(top_branch.get('r_grade_risk') or 0)}."
        )
    elif semester_specific_requested and top_semester is not None:
        grouped_by = "semester"
        focus_bucket = top_semester
        key_points.append(
            f"Focus the next admin pass on semester slice `{top_semester['bucket_label']}` first. It currently shows prediction high risk {int(top_semester.get('prediction_high_risk') or 0)}, overall shortage {int(top_semester.get('overall_shortage') or 0)}, I-grade risk {int(top_semester.get('i_grade_risk') or 0)}, and R-grade risk {int(top_semester.get('r_grade_risk') or 0)}."
        )
    elif focus_bucket is not None and grouped_by:
        key_points.append(
            f"Start with the most pressured `{grouped_by}` bucket in the current view: `{focus_bucket['bucket_label']}`. "
            f"It currently shows prediction high risk {int(focus_bucket.get('prediction_high_risk') or 0)}, "
            f"overall shortage {int(focus_bucket.get('overall_shortage') or 0)}, "
            f"I-grade risk {int(focus_bucket.get('i_grade_risk') or 0)}, and "
            f"R-grade risk {int(focus_bucket.get('r_grade_risk') or 0)}."
        )
    elif top_branch is not None:
        key_points.append(
            f"Start with the most pressured branch right now: `{top_branch['bucket_label']}`."
        )
    if top_high_risk:
        key_points.append(
            "First operational move: review the top prediction high-risk students first: "
            + "; ".join(
                f"student_id {int(getattr(row, 'student_id', 0) or 0)} (probability {float(getattr(row, 'final_risk_probability', 0.0) or 0.0):.4f})"
                for row in top_high_risk
            )
        )
    if top_semester is not None:
        key_points.append(
            f"Academic operations move: review the semester slice `{top_semester['bucket_label']}` because it currently shows overall shortage {int(top_semester.get('overall_shortage') or 0)}, I-grade risk {int(top_semester.get('i_grade_risk') or 0)}, and R-grade risk {int(top_semester.get('r_grade_risk') or 0)}."
        )
    key_points.append(
        "Operational strategy should focus on concrete blockers first: the highest-risk students needing intervention, the most pressured bucket in the current view, and the branch or semester slice where attendance-policy burden is stacking up."
    )
    opening = "Here is the grounded institution-level action list from the current retention picture."
    if branch_specific_requested:
        opening = "Here is the branch-specific admin action list from the current retention picture."
    elif semester_specific_requested:
        opening = "Here is the semester-specific admin action list from the current retention picture."
    elif strategic_plan_requested:
        opening = "Here is the grounded strategic admin plan from the current retention picture."
    elif branch_priority_requested:
        opening = "Here is the grounded admin priority call from the current retention picture."
    action_stage = 1
    if branch_specific_requested:
        action_stage = 2
    elif semester_specific_requested:
        action_stage = 3
    if generic_progression and previous_action_stage >= 3:
        action_stage = 4
        opening = "Here is the implementation-stage admin action plan from the current retention picture."
        key_points.append(
            "Implementation stage: assign owners for the focused branch or semester slice, set the next review checkpoint now, and measure whether the concentrated pressure is actually shrinking after intervention."
        )
        key_points.append(
            "Governance move: track whether the same hotspot and top-risk students are still dominating the picture in the next cycle; if they are, escalate rather than repeating the same plan passively."
        )
    if strategic_plan_requested:
        key_points.append(
            "Strategic roadmap: first stabilize the highest-pressure bucket, then review whether the shared hotspot weakens, then widen intervention only after the concentrated pressure starts shrinking."
        )
        key_points.append(
            "Admin checkpoint sequence: 1. immediate pressure triage, 2. next-cycle bucket review, 3. escalation for buckets that remain stubborn, 4. institution-wide widening only after the first hotspot improves."
        )
    if branch_priority_requested:
        key_points.append(
            "Priority call: focus first on the bucket carrying the most visible concentrated strain instead of spreading effort thinly across every branch at once."
        )
    return (
        build_grounded_response(
            opening=opening,
            key_points=key_points,
            tools_used=[
                {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Mapped the admin question into a grounded operational advisory plan"},
                {"tool_name": "admin_operational_action_advisor", "summary": "Combined current risk buckets and top prediction-high-risk students into an institution action list"},
            ],
            limitations=[],
            closing=(
                "If you want, I can narrow this further into a semester-specific or subject-specific admin action list."
                if branch_specific_requested
                else "If you want, I can narrow this into a branch-specific, semester-specific, or subject-specific admin action list."
            ),
        ),
        [
            {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Mapped the admin question into a grounded operational advisory plan"},
            {"tool_name": "admin_operational_action_advisor", "summary": "Combined current risk buckets and top prediction-high-risk students into an institution action list"},
        ],
        [],
        {
            "kind": "import_coverage",
            "intent": "admin_operational_actions",
            "role_scope": "admin",
            "grouped_by": grouped_by or "",
            "bucket_values": list(last_context.get("bucket_values") or []),
            "focus_bucket": str(focus_bucket.get("bucket_label") or "").strip() if focus_bucket is not None else "",
            "pending_role_follow_up": "operational_actions",
            "planner_version": str(planner.get("version") or COPILOT_SYSTEM_PROMPT_VERSION),
            "action_stage": action_stage,
        },
    )


def _answer_admin_operational_explanation_fast(
    *,
    last_context: dict,
    risk_breakdown: dict,
    latest_predictions: list[object],
) -> tuple[str, list[dict], list[str], dict]:
    grouped_by = str(last_context.get("grouped_by") or "").strip().lower()
    focus_bucket = str(last_context.get("focus_bucket") or "").strip()
    top_branch = (risk_breakdown.get("branch_breakdown") or [None])[0]
    top_semester = (risk_breakdown.get("semester_breakdown") or [None])[0]
    high_risk_count = sum(
        1
        for row in latest_predictions
        if int(getattr(row, "final_predicted_class", 0) or 0) == 1
    )
    key_points: list[str] = [
        f"Current high-risk students across the institution: {high_risk_count}.",
    ]
    if grouped_by == "branch" and focus_bucket and top_branch is not None:
        key_points.append(
            f"Focused branch view: `{focus_bucket}` is still the current pressure bucket because prediction high risk, overall shortage, and carry-forward attendance burden are clustering there together."
        )
        key_points.append(
            f"Current branch pressure snapshot: prediction high risk {int(top_branch.get('prediction_high_risk') or 0)}, overall shortage {int(top_branch.get('overall_shortage') or 0)}, I-grade risk {int(top_branch.get('i_grade_risk') or 0)}, and R-grade risk {int(top_branch.get('r_grade_risk') or 0)}."
        )
    elif grouped_by == "semester" and focus_bucket and top_semester is not None:
        key_points.append(
            f"Focused semester view: `{focus_bucket}` is still the current pressure bucket because academic-policy strain is concentrated there rather than being evenly spread."
        )
        key_points.append(
            f"Current semester pressure snapshot: prediction high risk {int(top_semester.get('prediction_high_risk') or 0)}, overall shortage {int(top_semester.get('overall_shortage') or 0)}, I-grade risk {int(top_semester.get('i_grade_risk') or 0)}, and R-grade risk {int(top_semester.get('r_grade_risk') or 0)}."
        )
    else:
        key_points.append(
            "Main pattern: the institution-level priority queue is being driven by overlapping prediction pressure, attendance-policy strain, and unresolved academic burden rather than by one isolated metric."
        )
    key_points.append(
        "That is why the right response is staged: explain the pressure concentration first, then act on the dominant bucket, then check whether the same concentration is actually shrinking."
    )
    return (
        build_grounded_response(
            opening="Here is the grounded explanation behind the current admin action thread.",
            key_points=key_points,
            tools_used=[
                {"tool_name": "conversation_memory", "summary": "Reused the same admin action thread already in focus"},
                {"tool_name": "institution_reasoning_summary", "summary": "Explained why the current admin priority bucket remains the focus"},
            ],
            limitations=[],
        ),
        [
            {"tool_name": "conversation_memory", "summary": "Reused the same admin action thread already in focus"},
            {"tool_name": "institution_reasoning_summary", "summary": "Explained why the current admin priority bucket remains the focus"},
        ],
        [],
        {
            "kind": "import_coverage",
            "intent": "institution_health_explanation",
            "role_scope": "admin",
            "grouped_by": grouped_by,
            "focus_bucket": focus_bucket,
            "pending_role_follow_up": "operational_actions",
        },
    )


def _answer_admin_trend_snapshot_fast(
    *,
    repository: EventRepository,
    lowered: str,
    risk_breakdown: dict,
    latest_predictions: list[object],
) -> tuple[str, list[dict], list[str], dict]:
    history_rows = repository.get_all_prediction_history()
    recent_entry_count, recent_entry_ids = _compute_recent_high_risk_entries(
        history_rows=history_rows,
        window_days=30,
    )
    top_branch = (risk_breakdown.get("branch_breakdown") or [None])[0]
    opening = "Here is the grounded 30-day institution trend snapshot."
    key_points = [
        f"Students newly entering high risk in the last 30 days: {recent_entry_count}.",
        f"Current prediction high-risk students right now: {sum(1 for row in latest_predictions if int(getattr(row, 'final_predicted_class', 0) or 0) == 1)}.",
    ]
    if "performance" in lowered:
        opening = "Here is the grounded current performance-trend snapshot for the institution."
        key_points.append(
            "This is a current trend view from recent risk-entry pressure and academic strain, not a full term-over-term GPA history layer."
        )
    elif any(token in lowered for token in {"dropout", "rising"}):
        opening = "Here is the grounded dropout-risk trend snapshot for the institution."
        key_points.append(
            "The safest current proxy for rising dropout pressure is whether new high-risk entries keep appearing alongside attendance-policy strain."
        )
    elif "current vs previous term" in lowered:
        opening = "Here is the grounded current-versus-prior snapshot I can support right now."
        key_points.append(
            "A strict term-over-term comparison layer is not fully built here, so this answer is grounded in the latest 30-day risk-entry pressure plus the current institution posture."
        )
    if top_branch is not None:
        key_points.append(
            f"Most pressured branch in the current snapshot: {top_branch['bucket_label']} with prediction high risk {int(top_branch.get('prediction_high_risk') or 0)}, overall shortage {int(top_branch.get('overall_shortage') or 0)}, I-grade risk {int(top_branch.get('i_grade_risk') or 0)}, and R-grade risk {int(top_branch.get('r_grade_risk') or 0)}."
        )
    if recent_entry_ids:
        key_points.append("Recent-entry sample: " + ", ".join(str(item) for item in recent_entry_ids[:5]))
    return (
        build_grounded_response(
            opening=opening,
            key_points=key_points,
            tools_used=[
                {"tool_name": "admin_intent_router", "summary": "Routed an institution trend-style admin request"},
                {"tool_name": "prediction_history_window", "summary": "Computed a recent high-risk-entry trend snapshot for the institution"},
            ],
            limitations=[],
        ),
        [
            {"tool_name": "admin_intent_router", "summary": "Routed an institution trend-style admin request"},
            {"tool_name": "prediction_history_window", "summary": "Computed a recent high-risk-entry trend snapshot for the institution"},
        ],
        [],
        {
            "kind": "admin_governance",
            "intent": "institution_trend_snapshot",
            "role_scope": "admin",
        },
    )


def _extract_grouping_follow_up_request(lowered: str) -> list[str]:
    grouping: list[str] = []
    if any(token in lowered for token in {"semester wise", "semester-wise", "sem wise", "sem-wise", "by semester"}):
        grouping.append("semester")
    if any(token in lowered for token in {"year wise", "year-wise", "by year"}):
        grouping.append("year")
    if any(token in lowered for token in {"branch wise", "branch-wise", "department wise", "department-wise", "by branch"}):
        grouping.append("branch")
    if any(token in lowered for token in {"gender wise", "gender-wise", "by gender"}):
        grouping.append("gender")
    if any(token in lowered for token in {"age band wise", "age-band-wise", "by age band", "age group wise"}):
        grouping.append("age_band")
    if any(token in lowered for token in {"batch wise", "batch-wise", "by batch"}):
        grouping.append("batch")
    if any(token in lowered for token in {"program wise", "program-wise", "programme wise", "programme-wise", "by program"}):
        grouping.append("program_type")
    if any(token in lowered for token in {"category wise", "category-wise", "by category"}):
        grouping.append("category")
    if any(token in lowered for token in {"region wise", "region-wise", "by region"}):
        grouping.append("region")
    if any(token in lowered for token in {"income wise", "income-wise", "by income"}):
        grouping.append("income")
    if any(token in lowered for token in {"status wise", "status-wise", "outcome wise", "outcome-wise", "by status"}):
        grouping.append("outcome_status")
    return grouping


def _extract_requested_top_limit(lowered: str) -> int | None:
    lowered = str(lowered or "").strip().lower()
    digit_match = re.search(r"\btop\s+(\d{1,2})\b", lowered) or re.search(r"\bfirst\s+(\d{1,2})\b", lowered)
    if digit_match:
        return int(digit_match.group(1))
    word_map = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    for word, value in word_map.items():
        if f"top {word}" in lowered or f"first {word}" in lowered:
            return value
    return None


def _looks_like_counsellor_assigned_students_request(lowered: str) -> bool:
    lowered = str(lowered or "").strip().lower()
    if lowered in {
        "students",
        "students?",
        "my students",
        "assigned students",
        "my assigned students",
        "show my students",
        "show my assigned students",
    }:
        return True
    if any(
        phrase in lowered
        for phrase in {
            "show my assigned students",
            "show my students",
            "list my students",
            "list my assigned students",
            "who are my students",
            "who all are my students",
            "who all are under me",
            "which students are assigned to me",
            "show assigned students",
            "who are under me",
        }
    ):
        return True
    return False


def _looks_like_counsellor_student_action_request(lowered: str) -> bool:
    lowered = str(lowered or "").strip().lower()
    if "student" not in lowered:
        return False
    return any(
        phrase in lowered
        for phrase in {
            "what should i do for student",
            "what action should i take for student",
            "what should i do about student",
            "how should i respond for student",
            "how should i help student",
            "what can i do for student",
            "what should we do for student",
        }
    )


def _looks_like_counsellor_student_reasoning_request(lowered: str) -> bool:
    lowered = str(lowered or "").strip().lower()
    if "student" not in lowered:
        return False
    if "attendance" in lowered and any(token in lowered for token in {"risk", "risky", "high risk", "high-risk", "alert"}):
        return True
    return any(
        phrase in lowered
        for phrase in {
            "why is student",
            "why student",
            "why is this student",
            "what caused student",
            "what caused this student",
            "what is causing student",
            "what is causing this student",
            "why risky",
            "why high risk",
            "why at risk",
        }
    )


def _looks_like_risk_layer_difference_request(lowered: str) -> bool:
    mentions_prediction = any(token in lowered for token in {"prediction risk", "prediction", "model risk", "ml risk"})
    mentions_attendance = any(token in lowered for token in {"attendance risk", "attendance", "policy risk", "academic risk"})
    asks_difference = any(
        token in lowered
        for token in {
            "difference",
            "different",
            "what does",
            "what is",
            "what's the difference",
            "mean",
            "separate",
        }
    )
    return mentions_prediction and mentions_attendance and asks_difference


def _build_risk_layer_difference_answer(
    *,
    scope_label: str,
    prediction_high_risk_count: int | None = None,
    overall_shortage_count: int | None = None,
    i_grade_count: int | None = None,
    r_grade_count: int | None = None,
    burden_summary: dict | None = None,
    tool_prefix: str,
) -> tuple[str, list[dict], list[str], dict]:
    key_points = [
        "Prediction risk comes from the retention model. It estimates how likely students are to become serious retention cases based on the available signals.",
        "Attendance-policy risk comes from academic rules. That includes overall shortage, I-grade risk, and R-grade risk based on attendance thresholds.",
        "Active academic burden is different again. It means an earlier I-grade or R-grade consequence is still uncleared, so the student may still need monitoring even if current-semester performance improves.",
    ]
    if prediction_high_risk_count is not None and overall_shortage_count is not None and i_grade_count is not None and r_grade_count is not None:
        key_points.append(
            f"Current scope snapshot: prediction high risk {prediction_high_risk_count}, overall shortage {overall_shortage_count}, I-grade risk {i_grade_count}, R-grade risk {r_grade_count}."
        )
    if burden_summary and burden_summary.get("total_students_with_active_academic_burden") is not None:
        key_points.append(
            "Carry-forward burden snapshot: "
            f"{int(burden_summary.get('total_students_with_active_academic_burden') or 0)} students still have active academic burden, "
            f"including {int(burden_summary.get('total_students_with_active_i_grade_burden') or 0)} unresolved I-grade and "
            f"{int(burden_summary.get('total_students_with_active_r_grade_burden') or 0)} unresolved R-grade cases."
        )
    return (
        build_grounded_response(
            opening=f"I separate those ideas for {scope_label} because they are related, but not the same thing.",
            key_points=key_points,
            tools_used=[
                {"tool_name": f"{tool_prefix}_risk_layer_explainer", "summary": "Explained the difference between prediction risk, attendance-policy risk, and carry-forward academic burden"},
            ],
            limitations=[],
        ),
        [
            {"tool_name": f"{tool_prefix}_risk_layer_explainer", "summary": "Explained the difference between prediction risk, attendance-policy risk, and carry-forward academic burden"},
        ],
        [],
        {"kind": f"{tool_prefix}_academic", "intent": "risk_layer_difference"},
    )


def _build_scoped_comparison_answer(
    *,
    scope_label: str,
    repository: EventRepository,
    profiles: list[object],
    latest_predictions_by_student: dict[int, object],
    planner: dict,
    lowered: str,
    tool_prefix: str,
) -> tuple[str, list[dict], list[str], dict] | None:
    compare_dimension = str(planner.get("comparison", {}).get("dimension") or "").strip()
    compare_values = [str(value).strip() for value in (planner.get("comparison", {}).get("values") or []) if str(value).strip()]
    if not compare_dimension:
        return None
    if not compare_values and compare_dimension in {
        "branch",
        "gender",
        "age_band",
        "batch",
        "program_type",
        "category",
        "region",
        "income",
    }:
        compare_values = _ordered_unique_context_values(profiles=profiles, key=compare_dimension)
    if not compare_values and compare_dimension == "outcome_status":
        compare_values = ["Dropped", "Graduated", "Studying"]
    if not compare_values:
        return None

    rows: list[dict[str, object]] = []
    for value in compare_values:
        grouped_subset = _filter_profiles_for_admin_query(
            profiles=profiles,
            outcome_status=value if compare_dimension == "outcome_status" else planner.get("filters", {}).get("outcome_status"),
            branch=value if compare_dimension == "branch" else _single_filter_value(planner, "branches"),
            gender=value if compare_dimension == "gender" else _single_filter_value(planner, "genders"),
            age_band=value if compare_dimension == "age_band" else _single_filter_value(planner, "age_bands"),
            batch=value if compare_dimension == "batch" else _single_filter_value(planner, "batches"),
            program_type=value if compare_dimension == "program_type" else _single_filter_value(planner, "program_types"),
            category=value if compare_dimension == "category" else _single_filter_value(planner, "categories"),
            region=value if compare_dimension == "region" else _single_filter_value(planner, "regions"),
            income=value if compare_dimension == "income" else _single_filter_value(planner, "incomes"),
        )
        student_ids = {int(profile.student_id) for profile in grouped_subset}
        subset_count = len(grouped_subset)
        academic_summary = _build_academic_scope_summary(repository=repository, student_ids=student_ids or None)
        burden_summary = _build_active_burden_scope_summary(repository=repository, student_ids=student_ids or None)
        prediction_high_risk_count = sum(
            1
            for student_id in student_ids
            if latest_predictions_by_student.get(student_id) is not None
            and int(getattr(latest_predictions_by_student[student_id], "final_predicted_class", 0)) == 1
        )
        prediction_rate = (prediction_high_risk_count / subset_count * 100.0) if subset_count else 0.0
        overall_rate = (academic_summary["total_students_with_overall_shortage"] / subset_count * 100.0) if subset_count else 0.0
        i_grade_rate = (academic_summary["total_students_with_i_grade_risk"] / subset_count * 100.0) if subset_count else 0.0
        r_grade_rate = (academic_summary["total_students_with_r_grade_risk"] / subset_count * 100.0) if subset_count else 0.0
        burden_rate = (
            burden_summary["total_students_with_active_academic_burden"] / subset_count * 100.0
            if subset_count
            else 0.0
        )
        attention_index = prediction_rate + overall_rate + i_grade_rate + (2.0 * r_grade_rate) + burden_rate
        strongest_driver_label = max(
            [
                ("prediction high risk", prediction_rate),
                ("overall shortage", overall_rate),
                ("I-grade risk", i_grade_rate),
                ("R-grade risk", r_grade_rate),
                ("active academic burden", burden_rate),
            ],
            key=lambda item: item[1],
        )[0]
        rows.append(
            {
                "value": value,
                "subset_count": subset_count,
                "prediction_high_risk_count": prediction_high_risk_count,
                "overall_shortage_count": academic_summary["total_students_with_overall_shortage"],
                "i_grade_count": academic_summary["total_students_with_i_grade_risk"],
                "r_grade_count": academic_summary["total_students_with_r_grade_risk"],
                "active_burden_count": burden_summary["total_students_with_active_academic_burden"],
                "prediction_rate": prediction_rate,
                "overall_rate": overall_rate,
                "i_grade_rate": i_grade_rate,
                "r_grade_rate": r_grade_rate,
                "burden_rate": burden_rate,
                "attention_index": attention_index,
                "strongest_driver_label": strongest_driver_label,
            }
        )

    rows.sort(key=lambda item: (-float(item["attention_index"]), -int(item["subset_count"]), str(item["value"]).lower()))
    if not rows:
        return None

    if planner.get("user_goal") == "attention_analysis":
        leader = rows[0]
        runner_up = rows[1] if len(rows) > 1 else None
        key_points = [
            f"`{leader['value']}` needs attention first with an attention index of {float(leader['attention_index']):.1f}.",
            (
                f"Why: prediction high risk {int(leader['prediction_high_risk_count'])}, overall shortage {int(leader['overall_shortage_count'])}, "
                f"I-grade risk {int(leader['i_grade_count'])}, R-grade risk {int(leader['r_grade_count'])}, "
                f"active burden {int(leader['active_burden_count'])}. The strongest pressure inside this bucket is {leader['strongest_driver_label']}."
            ),
        ]
        if runner_up is not None:
            key_points.append(
                f"Next most pressured bucket: `{runner_up['value']}` with attention index {float(runner_up['attention_index']):.1f}."
            )
        return (
            build_grounded_response(
                opening=f"I ranked the requested `{compare_dimension}` buckets by current retention attention pressure inside {scope_label}.",
                key_points=key_points,
                tools_used=[
                    {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Built an attention-ranking plan from the counsellor/admin prompt"},
                    {"tool_name": f"{tool_prefix}_scoped_attention_index", "summary": f"Ranked scoped {compare_dimension} buckets using prediction, attendance, and unresolved-burden pressure"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Built an attention-ranking plan from the counsellor/admin prompt"},
                {"tool_name": f"{tool_prefix}_scoped_attention_index", "summary": f"Ranked scoped {compare_dimension} buckets using prediction, attendance, and unresolved-burden pressure"},
            ],
            [],
            {
                "kind": "import_coverage",
                "intent": "attention_analysis_summary",
                "grouped_by": compare_dimension,
                "bucket_values": compare_values,
                "role_scope": tool_prefix,
                "analysis_mode": "attention_ranking",
                "focus_bucket": str(leader.get("value") or "").strip(),
                "pending_role_follow_up": "operational_actions",
            },
        )

    if planner.get("user_goal") == "diagnostic_comparison":
        leader = rows[0]
        runner_up = rows[1] if len(rows) > 1 else None
        key_points = [
            f"`{leader['value']}` is showing the strongest retention pressure with a diagnostic attention index of {float(leader['attention_index']):.1f}.",
            f"Primary driver: {leader['strongest_driver_label']}.",
            (
                f"Why: prediction high risk {float(leader['prediction_rate']):.1f}%, overall shortage {float(leader['overall_rate']):.1f}%, "
                f"I-grade risk {float(leader['i_grade_rate']):.1f}%, R-grade risk {float(leader['r_grade_rate']):.1f}%, "
                f"active burden {float(leader['burden_rate']):.1f}%."
            ),
        ]
        if runner_up is not None:
            key_points.append(
                f"Next diagnostic bucket: `{runner_up['value']}` with attention index {float(runner_up['attention_index']):.1f}."
            )
        return (
            build_grounded_response(
                opening=f"I diagnosed the requested `{compare_dimension}` buckets inside {scope_label} to explain which cohort is worse and why.",
                key_points=key_points,
                tools_used=[
                    {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Built a diagnostic comparison plan from the natural-language prompt"},
                    {"tool_name": f"{tool_prefix}_scoped_diagnostic_driver", "summary": f"Compared scoped {compare_dimension} buckets across prediction, attendance, and carry-forward burden"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Built a diagnostic comparison plan from the natural-language prompt"},
                {"tool_name": f"{tool_prefix}_scoped_diagnostic_driver", "summary": f"Compared scoped {compare_dimension} buckets across prediction, attendance, and carry-forward burden"},
            ],
            [],
            {
                "kind": "import_coverage",
                "intent": "diagnostic_comparison_summary",
                "grouped_by": compare_dimension,
                "bucket_values": compare_values,
                "role_scope": tool_prefix,
                "analysis_mode": "diagnostic_comparison",
                "focus_bucket": str(leader.get("value") or "").strip(),
                "pending_role_follow_up": "operational_actions",
            },
        )

    key_points = [
        (
            f"{row['value']}: prediction high risk {int(row['prediction_high_risk_count'])}, overall shortage {int(row['overall_shortage_count'])}, "
            f"I-grade risk {int(row['i_grade_count'])}, R-grade risk {int(row['r_grade_count'])}, active burden {int(row['active_burden_count'])}."
        )
        for row in rows
    ]
    if len(rows) > 1:
        leader = rows[0]
        trailer = rows[-1]
        key_points.extend(
            [
                f"Highest attention pressure: `{leader['value']}` with index {float(leader['attention_index']):.1f}.",
                f"Lowest attention pressure: `{trailer['value']}` with index {float(trailer['attention_index']):.1f}.",
            ]
        )
    return (
        build_grounded_response(
            opening=f"I compared the requested `{compare_dimension}` buckets inside {scope_label}.",
            key_points=key_points,
            tools_used=[
                {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Built a structured comparison plan from the natural-language prompt"},
                {"tool_name": f"{tool_prefix}_scoped_comparison", "summary": f"Compared scoped {compare_dimension} buckets across prediction, attendance, and unresolved burden"},
            ],
            limitations=[],
        ),
        [
            {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Built a structured comparison plan from the natural-language prompt"},
            {"tool_name": f"{tool_prefix}_scoped_comparison", "summary": f"Compared scoped {compare_dimension} buckets across prediction, attendance, and unresolved burden"},
        ],
        [],
        {
            "kind": "import_coverage",
            "intent": "comparison_summary",
            "grouped_by": compare_dimension,
            "bucket_values": compare_values,
            "role_scope": tool_prefix,
            "analysis_mode": str(planner.get("analysis_mode") or "comparison"),
        },
    )


def _build_counsellor_student_sample_lines(
    *,
    profiles: list[object],
    latest_predictions_by_student: dict[int, object],
    limit: int,
) -> list[str]:
    lines: list[str] = []
    for profile in profiles[:limit]:
        student_id = int(profile.student_id)
        external_ref = str(getattr(profile, "external_student_ref", None) or "no ref")
        branch = _profile_context_value(profile, "branch") or "unknown branch"
        prediction = latest_predictions_by_student.get(student_id)
        if prediction is not None:
            risk_label = "HIGH" if int(getattr(prediction, "final_predicted_class", 0)) == 1 else "LOW"
            lines.append(
                f"student_id {student_id} ({external_ref}): {branch}, current prediction {risk_label} at {float(getattr(prediction, 'final_risk_probability', 0.0) or 0.0):.4f}"
            )
        else:
            lines.append(f"student_id {student_id} ({external_ref}): {branch}, no prediction available yet")
    return lines


def _build_counsellor_student_reasoning_answer(
    *,
    student_id: int,
    lowered: str,
    profile: object,
    prediction: object | None,
    semester_progress: object | None,
    subject_rows: list[object],
    academic_progress: object | None,
    academic_burden: dict,
    signal_bundle: dict,
) -> tuple[str, list[dict], list[str], dict]:
    key_points: list[str] = []
    if prediction is not None:
        risk_label = "HIGH" if int(getattr(prediction, "final_predicted_class", 0)) == 1 else "LOW"
        key_points.append(
            f"Latest prediction view: {risk_label} at probability {float(getattr(prediction, 'final_risk_probability', 0.0) or 0.0):.4f}."
        )
    if semester_progress is not None and semester_progress.overall_attendance_percent is not None:
        key_points.append(
            f"Attendance view: overall semester status is {str(semester_progress.overall_status or 'UNKNOWN').replace('_', ' ')} at {float(semester_progress.overall_attendance_percent):.2f}%."
        )
    weakest_subject = next((row for row in subject_rows if row.subject_attendance_percent is not None), None)
    if weakest_subject is not None and weakest_subject.subject_attendance_percent is not None:
        key_points.append(
            f"Weakest visible subject: {weakest_subject.subject_name} at {float(weakest_subject.subject_attendance_percent):.2f}%."
        )
    key_points.extend(
        _build_cross_signal_reasoning_points(
            signal_bundle=signal_bundle,
            current_semester_progress=semester_progress,
            include_availability_gap=True,
            include_reconciliation_notice=True,
            include_stability=False,
        )[:5]
    )
    if academic_progress is not None:
        key_points.append(
            f"Academic position: year {academic_progress.current_year or 'unknown'}, semester {academic_progress.current_semester or 'unknown'}, branch {academic_progress.branch or 'unknown'}."
        )
    if bool(academic_burden.get("has_active_burden")):
        key_points.append(f"Active academic burden: {academic_burden['summary']}.")
    opening = f"Here is the grounded risk explanation for student_id {student_id} inside your counsellor scope."
    if any(phrase in lowered for phrase in {"what caused student", "what caused this student", "what is causing student", "what is causing this student"}):
        opening = f"Here are the grounded causes currently driving risk for student_id {student_id} inside your counsellor scope."
        key_points.insert(0, "Cause summary: the strongest visible pressure is coming from academic performance and submission behavior, not attendance shortage alone.")
    return (
        build_grounded_response(
            opening=opening,
            key_points=key_points,
            tools_used=[
                {"tool_name": "student_profile_lookup", "summary": "Returned the scoped student profile for explanation"},
                {"tool_name": "student_cross_signal_reasoning", "summary": "Explained the student using prediction, LMS, ERP, finance, attendance, and burden signals"},
            ],
            limitations=[],
            closing="If you want, I can next turn this into a specific action plan for this same student.",
        ),
        [
            {"tool_name": "student_profile_lookup", "summary": "Returned the scoped student profile for explanation"},
            {"tool_name": "student_cross_signal_reasoning", "summary": "Explained the student using prediction, LMS, ERP, finance, attendance, and burden signals"},
        ],
        [],
        {
            "kind": "student_drilldown",
            "student_id": student_id,
            "intent": "counsellor_student_reasoning",
            "pending_role_follow_up": "student_specific_action",
            "default_follow_up_rewrite": f"what action should i take for student {student_id}",
        },
    )


def _build_counsellor_student_action_answer(
    *,
    student_id: int,
    lowered: str,
    prediction: object | None,
    semester_progress: object | None,
    subject_rows: list[object],
    academic_burden: dict,
    signal_bundle: dict,
    active_warning: object | None,
) -> tuple[str, list[dict], list[str], dict]:
    asks_next_stage = _looks_like_generic_progression_follow_up(lowered) or any(
        phrase in lowered
        for phrase in {
            "what next",
            "what else should i do",
            "what else do i do",
            "how should i monitor this student",
            "what should i monitor next",
            "and then",
            "more",
        }
    )
    key_points: list[str] = []
    recommended_actions = list(getattr(prediction, "recommended_actions", None) or []) if prediction is not None else []
    weakest_subject = next((row for row in subject_rows if row.subject_attendance_percent is not None), None)
    latest_finance_event = signal_bundle.get("latest_finance_event")
    latest_erp_event = signal_bundle.get("latest_erp_event")

    if asks_next_stage:
        if bool(academic_burden.get("has_active_r_grade_burden")):
            key_points.append("Keep this student on at least weekly monitoring because unresolved R-grade burden is still active.")
        elif bool(academic_burden.get("has_active_i_grade_burden")):
            key_points.append("Keep this student on at least monthly monitoring because unresolved I-grade burden is still active.")
        if weakest_subject is not None and weakest_subject.subject_attendance_percent is not None:
            key_points.append(
                f"Next monitoring focus: keep checking {weakest_subject.subject_name} because it remains the weakest visible subject at {float(weakest_subject.subject_attendance_percent):.2f}%."
            )
        if latest_finance_event is not None and str(getattr(latest_finance_event, "payment_status", "") or "").lower() not in {"paid", "clear"}:
            key_points.append(
                f"Escalation follow-up: coordinate support around the current payment pressure ({str(getattr(latest_finance_event, 'payment_status', 'Unknown'))}) so finance does not keep pulling the student backward."
            )
        if latest_erp_event is not None:
            key_points.append(
                f"Academic checkpoint: review whether assessed work has improved from the current weighted score of {float(getattr(latest_erp_event, 'weighted_assessment_score', 0.0) or 0.0):.1f} and whether submission consistency is holding."
            )
        if active_warning is not None:
            key_points.append("Close the loop on the active warning with one named checkpoint rather than an open-ended reminder.")
        if semester_progress is not None and semester_progress.overall_status:
            key_points.append(
                f"Attendance posture to keep protected during follow-up: {str(semester_progress.overall_status).replace('_', ' ')}."
            )
        opening = f"Here is the next grounded follow-up plan for student_id {student_id} inside your counsellor scope."
    else:
        if active_warning is not None:
            key_points.append("Start with the active warning first so the student does not drift further while you intervene.")
        if recommended_actions:
            primary = str(recommended_actions[0].get("title") or "").strip()
            if primary:
                key_points.append(f"First action: {primary}.")
            secondary = str(recommended_actions[1].get("title") or "").strip() if len(recommended_actions) > 1 else ""
            if secondary:
                key_points.append(f"Next action: {secondary}.")
        if bool(academic_burden.get("has_active_r_grade_burden")):
            key_points.append("Keep this student on at least weekly monitoring because unresolved R-grade burden is still active.")
        elif bool(academic_burden.get("has_active_i_grade_burden")):
            key_points.append("Keep this student on at least monthly monitoring because unresolved I-grade burden is still active.")
        if weakest_subject is not None and weakest_subject.subject_attendance_percent is not None:
            key_points.append(
                f"Subject focus: stabilize {weakest_subject.subject_name} first because it is the weakest visible subject at {float(weakest_subject.subject_attendance_percent):.2f}%."
            )
        if latest_finance_event is not None and str(getattr(latest_finance_event, "payment_status", "") or "").lower() not in {"paid", "clear"}:
            key_points.append(
                f"Finance follow-up: coordinate support around the current payment pressure ({str(getattr(latest_finance_event, 'payment_status', 'Unknown'))})."
            )
        if latest_erp_event is not None:
            key_points.append(
                f"Coursework focus: improve assessed work from the current weighted score of {float(getattr(latest_erp_event, 'weighted_assessment_score', 0.0) or 0.0):.1f} and prevent further missed submissions."
            )
        if semester_progress is not None and semester_progress.overall_status:
            key_points.append(
                f"Attendance posture to protect while intervening: {str(semester_progress.overall_status).replace('_', ' ')}."
            )
        opening = f"Here is the first grounded action plan for student_id {student_id} inside your counsellor scope."
    return (
        build_grounded_response(
            opening=opening,
            key_points=key_points,
            tools_used=[
                {"tool_name": "student_profile_lookup", "summary": "Reused the scoped student drilldown context"},
                {"tool_name": "counsellor_student_action_plan", "summary": "Turned the student risk, coursework, finance, attendance, and burden signals into a counsellor action list"},
            ],
            limitations=[],
        ),
        [
            {"tool_name": "student_profile_lookup", "summary": "Reused the scoped student drilldown context"},
            {"tool_name": "counsellor_student_action_plan", "summary": "Turned the student risk, coursework, finance, attendance, and burden signals into a counsellor action list"},
        ],
        [],
        {
            "kind": "student_drilldown",
            "student_id": student_id,
            "intent": "counsellor_student_action_plan",
            "pending_role_follow_up": "student_specific_action",
            "default_follow_up_rewrite": f"what action should i take for student {student_id}",
        },
    )


def _answer_counsellor_fresh_filter_request(
    *,
    repository: EventRepository,
    profiles: list[object],
    latest_predictions: dict[int, object],
    lowered: str,
) -> tuple[str, list[dict], list[str], dict]:
    selected_branch = next(
        (
            str(_profile_context_value(profile, "branch") or "").strip()
            for profile in profiles
            if str(_profile_context_value(profile, "branch") or "").strip()
            and str(_profile_context_value(profile, "branch") or "").strip().lower() in lowered
        ),
        "",
    )
    selected_year: int | None = None
    if "final year" in lowered:
        year_values = [int(_profile_current_year(profile) or 0) for profile in profiles if int(_profile_current_year(profile) or 0) > 0]
        selected_year = max(year_values) if year_values else None
    else:
        year_match = re.search(r"\b([1-9])(?:st|nd|rd|th)\s+year\b", lowered)
        if year_match is not None:
            selected_year = int(year_match.group(1))

    wants_only_high_risk = "only high risk" in lowered or "only high-risk" in lowered
    wants_low_attendance = "low attendance" in lowered
    wants_low_assignments = "low assignments" in lowered

    scoped_student_ids = [int(profile.student_id) for profile in profiles]
    semester_by_student = {
        int(row.student_id): row
        for row in repository.get_latest_student_semester_progress_records_for_students(
            scoped_student_ids or None
        )
    }
    latest_erp_by_student = {
        int(row.student_id): row
        for row in repository.get_latest_erp_events_for_students(scoped_student_ids or None)
    }

    matched_profiles: list[object] = []
    sample_lines: list[str] = []
    for profile in profiles:
        student_id = int(profile.student_id)
        semester_progress = semester_by_student.get(student_id)
        prediction = latest_predictions.get(student_id)
        latest_erp_event = latest_erp_by_student.get(student_id)
        submission_rate = float(getattr(latest_erp_event, "assessment_submission_rate", 0.0) or 0.0) if latest_erp_event is not None else 0.0

        matches = True
        reasons: list[str] = []
        if selected_branch and str(_profile_context_value(profile, "branch") or "").strip().lower() != selected_branch.lower():
            matches = False
        if selected_year is not None and int(_profile_current_year(profile) or 0) != selected_year:
            matches = False
        if wants_only_high_risk and not (
            prediction is not None and int(getattr(prediction, "final_predicted_class", 0) or 0) == 1
        ):
            matches = False
        if wants_low_attendance and not (
            semester_progress is not None
            and (
                float(getattr(semester_progress, "overall_attendance_percent", 0.0) or 0.0) < 75.0
                or str(getattr(semester_progress, "overall_status", "") or "").strip().upper() != "SAFE"
            )
        ):
            matches = False
        if wants_low_assignments and not (latest_erp_event is not None and submission_rate < 0.75):
            matches = False

        if not matches:
            continue

        matched_profiles.append(profile)
        if selected_branch:
            reasons.append(f"branch {selected_branch}")
        if selected_year is not None:
            reasons.append(f"year {selected_year}")
        if wants_only_high_risk:
            reasons.append("currently high risk")
        if wants_low_attendance and semester_progress is not None:
            reasons.append(
                f"attendance {float(getattr(semester_progress, 'overall_attendance_percent', 0.0) or 0.0):.1f}%"
            )
        if wants_low_assignments and latest_erp_event is not None:
            reasons.append(f"submission rate {submission_rate:.2f}")
        if len(sample_lines) < 10:
            sample_lines.append(
                f"student_id {student_id} ({getattr(profile, 'external_student_ref', None) or 'no ref'}): "
                + (", ".join(reasons) if reasons else "matched the requested filter")
            )

    opening = f"I found {len(matched_profiles)} students inside your counsellor scope matching that filter."
    if selected_branch:
        opening = f"I found {len(matched_profiles)} students in `{selected_branch}` inside your counsellor scope."
    elif selected_year is not None:
        opening = f"I found {len(matched_profiles)} students in year {selected_year} inside your counsellor scope."
    elif wants_only_high_risk:
        opening = f"I found {len(matched_profiles)} currently high-risk students inside your counsellor scope."
    elif wants_low_attendance:
        opening = f"I found {len(matched_profiles)} low-attendance students inside your counsellor scope."
    elif wants_low_assignments:
        opening = f"I found {len(matched_profiles)} students with low assignment submission inside your counsellor scope."

    return (
        build_grounded_response(
            opening=opening,
            key_points=sample_lines or ["No students currently match that exact filter inside your counsellor scope."],
            tools_used=[{"tool_name": "counsellor_scoped_filter", "summary": "Applied a fresh counsellor subset filter using branch/year/risk/attendance/coursework signals"}],
            limitations=["I am showing up to 10 sample students in-chat to keep the filtered result readable."],
            closing="If you want, I can next explain this filtered set, show the top 5 inside it, or turn it into a counsellor action list.",
        ),
        [{"tool_name": "counsellor_scoped_filter", "summary": "Applied a fresh counsellor subset filter using branch/year/risk/attendance/coursework signals"}],
        ["I am showing up to 10 sample students in-chat to keep the filtered result readable."],
        {
            "kind": "cohort",
            "intent": "counsellor_filtered_subset",
            "student_ids": [int(profile.student_id) for profile in matched_profiles],
            "role_scope": "counsellor",
            "pending_role_follow_up": "operational_actions",
            "response_type": "data",
            "last_topic": "filtered_students",
        },
    )


def _answer_counsellor_question(
    *,
    auth: AuthContext,
    repository: EventRepository,
    lowered: str,
    intent: str,
    memory: dict,
    query_plan: dict | None = None,
) -> tuple[str, list[dict], list[str], dict]:
    planner = query_plan or {}
    original_lowered = str(planner.get("original_message") or lowered).strip().lower()
    explicit_student_id = _extract_student_id(original_lowered)
    counsellor_profiles = repository.get_imported_student_profiles_for_counsellor_identity(
        subject=auth.subject,
        display_name=auth.display_name,
    )
    owned_student_ids = {int(profile.student_id) for profile in counsellor_profiles}
    academic_summary = None
    risk_breakdown = None
    burden_summary = None
    semester_progress_by_student = None
    latest_erp_by_student = None
    latest_lms_by_student = None
    latest_finance_by_student = None
    scoped_prediction_loader = getattr(repository, "get_latest_predictions_for_students", None)
    if callable(scoped_prediction_loader):
        prediction_rows = scoped_prediction_loader(owned_student_ids or None)
    else:
        prediction_rows = [
            row
            for row in repository.get_latest_predictions_for_all_students()
            if not owned_student_ids or int(row.student_id) in owned_student_ids
        ]
    latest_predictions = {int(row.student_id): row for row in prediction_rows}
    high_risk_rows = [row for row in latest_predictions.values() if int(row.final_predicted_class) == 1]
    faculty_summary = None

    def _academic_summary():
        nonlocal academic_summary
        if academic_summary is None:
            academic_summary = _build_academic_scope_summary(
                repository=repository,
                student_ids=owned_student_ids or None,
            )
        return academic_summary

    def _risk_breakdown():
        nonlocal risk_breakdown
        if risk_breakdown is None:
            risk_breakdown = _build_prediction_and_attendance_breakdown(
                repository=repository,
                student_ids=owned_student_ids or None,
            )
        return risk_breakdown

    def _burden_summary():
        nonlocal burden_summary
        if burden_summary is None:
            burden_summary = _build_active_burden_scope_summary(
                repository=repository,
                student_ids=owned_student_ids or None,
            )
        return burden_summary

    def _semester_progress_by_student():
        nonlocal semester_progress_by_student
        if semester_progress_by_student is None:
            semester_progress_by_student = {
                int(row.student_id): row
                for row in repository.get_latest_student_semester_progress_records_for_students(owned_student_ids or None)
            }
        return semester_progress_by_student

    def _latest_erp_by_student():
        nonlocal latest_erp_by_student
        if latest_erp_by_student is None:
            latest_erp_by_student = repository.get_latest_erp_events_for_students(owned_student_ids or None)
        return latest_erp_by_student

    def _latest_lms_by_student():
        nonlocal latest_lms_by_student
        if latest_lms_by_student is None:
            latest_lms_by_student = repository.get_latest_lms_event_days_for_students(owned_student_ids or None)
        return latest_lms_by_student

    def _latest_finance_by_student():
        nonlocal latest_finance_by_student
        if latest_finance_by_student is None:
            latest_finance_by_student = repository.get_latest_finance_events_for_students(owned_student_ids or None)
        return latest_finance_by_student

    def _faculty_summary():
        nonlocal faculty_summary
        if faculty_summary is None:
            faculty_summary = get_faculty_summary(db=repository.db, auth=auth)
        return faculty_summary

    last_context = memory.get("last_context") or {}
    counsellor_query = _classify_counsellor_query(lowered=original_lowered, last_context=last_context)
    query_topic = str(counsellor_query.get("topic") or "generic")
    if intent == "cohort_summary" and _looks_like_counsellor_assigned_students_request(original_lowered):
        sample_profiles = sorted(
            counsellor_profiles,
            key=lambda profile: (
                -float(getattr(latest_predictions.get(int(profile.student_id)), "final_risk_probability", 0.0) or 0.0),
                int(profile.student_id),
            ),
        )
        sample_lines = _build_counsellor_student_sample_lines(
            profiles=sample_profiles,
            latest_predictions_by_student=latest_predictions,
            limit=10,
        )
        if "list" in original_lowered:
            opening = f"Here is the current assigned-student list for your counsellor scope ({len(counsellor_profiles)} students)."
        elif "under me" in original_lowered:
            opening = f"These are the students currently under your counsellor scope ({len(counsellor_profiles)} total)."
        else:
            opening = f"I found {len(counsellor_profiles)} students currently assigned to your counsellor scope."
        return (
            build_grounded_response(
                opening=opening,
                key_points=sample_lines,
                tools_used=[
                    {"tool_name": "counsellor_assignment_scope", "summary": "Returned the students currently assigned to this counsellor identity"},
                ],
                limitations=["I am showing up to 10 students in-chat to keep the list readable."],
                closing="If you want, I can next show only the currently high-risk students or turn this into a counsellor action list.",
            ),
            [
                {"tool_name": "counsellor_assignment_scope", "summary": "Returned the students currently assigned to this counsellor identity"},
            ],
            ["I am showing up to 10 students in-chat to keep the list readable."],
            {
                "kind": "import_coverage",
                "intent": "counsellor_assigned_students",
                "student_ids": [int(profile.student_id) for profile in counsellor_profiles],
                "role_scope": "counsellor",
                "pending_role_follow_up": "operational_actions",
            },
        )
    if (
        query_topic not in {"priority", "factor_reasoning", "fresh_filter"}
        and intent != "student_drilldown"
        and explicit_student_id is None
    ):
        memory_follow_up = _maybe_answer_role_follow_up(
            role="counsellor",
            repository=repository,
            intent=intent,
            memory=memory,
            profiles=counsellor_profiles,
        )
        if memory_follow_up is not None:
            return memory_follow_up
    if planner.get("user_goal") == "role_action_request" or _should_continue_role_operational_actions(
        lowered=lowered,
        memory=memory,
        last_context=last_context,
    ):
        scoped_queue = _build_lightweight_counsellor_queue_items(
            profiles=counsellor_profiles,
            latest_predictions=latest_predictions,
            student_ids=set(last_context.get("student_ids") or []) or owned_student_ids or None,
        )
        return _answer_role_operational_actions(
            role="counsellor",
            scope_label="your current counsellor scope",
            repository=repository,
            auth=auth,
            planner=planner,
            last_context=last_context,
            academic_summary=_academic_summary(),
            burden_summary=_burden_summary(),
            risk_breakdown=_risk_breakdown(),
            queue_items=scoped_queue,
        )
    follow_up_grouping = _extract_grouping_follow_up_request(lowered)
    if str(last_context.get("intent") or "") == "grouped_risk_breakdown" and follow_up_grouping:
            return _build_grouped_risk_breakdown_answer(
                scope_label="your current counsellor scope",
                lowered=lowered,
                planner={
                    "grouping": follow_up_grouping,
                    "metrics": ["prediction_high_risk", "overall_shortage", "i_grade_risk", "r_grade_risk"],
                },
                risk_breakdown=_risk_breakdown(),
                prediction_high_risk_count=len(high_risk_rows),
                overall_shortage_count=_academic_summary()["total_students_with_overall_shortage"],
                i_grade_count=_academic_summary()["total_students_with_i_grade_risk"],
                r_grade_count=_academic_summary()["total_students_with_r_grade_risk"],
                tool_prefix="counsellor",
            )

    if _looks_like_risk_layer_difference_request(lowered):
        return _build_risk_layer_difference_answer(
            scope_label="your current counsellor scope",
            prediction_high_risk_count=len(high_risk_rows),
            overall_shortage_count=_academic_summary()["total_students_with_overall_shortage"],
            i_grade_count=_academic_summary()["total_students_with_i_grade_risk"],
            r_grade_count=_academic_summary()["total_students_with_r_grade_risk"],
            burden_summary=_burden_summary(),
            tool_prefix="counsellor",
        )

    if planner.get("user_goal") == "priority_queue" or query_topic == "priority":
        ranked_high_risk_profiles = [
            profile
            for profile in counsellor_profiles
            if latest_predictions.get(int(profile.student_id)) is not None
            and int(getattr(latest_predictions[int(profile.student_id)], "final_predicted_class", 0)) == 1
        ]
        ranked_high_risk_profiles.sort(
            key=lambda profile: (
                -float(getattr(latest_predictions[int(profile.student_id)], "final_risk_probability", 0.0) or 0.0),
                int(profile.student_id),
            )
        )
        top_items = ranked_high_risk_profiles[:5]
        sample_lines = _build_counsellor_student_sample_lines(
            profiles=ranked_high_risk_profiles,
            latest_predictions_by_student=latest_predictions,
            limit=5,
        )
        academic_summary = _academic_summary()
        burden_summary = _burden_summary()
        top_subject = academic_summary["top_subjects"][0] if academic_summary["top_subjects"] else None
        focus_like = "focus on" in original_lowered
        prioritize_like = "prioritize" in original_lowered
        trouble_like = "in trouble" in original_lowered
        struggling_like = any(token in original_lowered for token in {"struggling", "not doing well"}) or trouble_like
        urgent_like = "urgent" in original_lowered
        serious_like = "serious" in original_lowered
        critical_like = any(token in original_lowered for token in {"critical"}) or urgent_like or serious_like
        opening = "Here are the students in your counsellor scope who currently need attention first."
        lead_point = "Attention summary: this is the current highest-pressure student set inside your counsellor scope."
        if focus_like:
            opening = "Here is where you should focus first inside your current counsellor scope."
            lead_point = "Focus order: start with the most pressured students before spreading effort across the full cohort."
        elif prioritize_like:
            opening = "Here is the student-priority view inside your current counsellor scope."
            lead_point = "Priority order: this ranking shows which student should be treated first inside the current pressure queue."
        elif urgent_like:
            opening = "Here are the students in your counsellor scope who need urgent help right now."
            lead_point = "Urgent-help summary: these are the students who should be contacted fastest to avoid deeper escalation."
        elif serious_like:
            opening = "Here are the students in your counsellor scope who are in the most serious condition right now."
            lead_point = "Serious-condition summary: these cases are already sitting close to the sharp end of the current risk-and-burden picture."
        elif critical_like:
            opening = "Here are the critical cases in your current counsellor scope right now."
            lead_point = "Critical-case summary: these students sit closest to the current intervention threshold and should not be left unattended."
        elif trouble_like:
            opening = "Here are the students in your counsellor scope who are currently in trouble."
            lead_point = "Trouble signal: these students are not just under mild pressure, they are the cases most likely to worsen without timely support."
        elif struggling_like:
            opening = "Here are the students in your counsellor scope who are currently struggling most."
            lead_point = "Struggle summary: the visible pressure is clustering in a small high-risk group rather than being evenly spread."
        key_points = [
            lead_point,
            *sample_lines,
            f"Current prediction high-risk students in this scoped attention view: {len(ranked_high_risk_profiles)}.",
            f"Unresolved I-grade burden still needing monitoring: {burden_summary['total_students_with_active_i_grade_burden']}.",
            f"Unresolved R-grade burden still needing monitoring: {burden_summary['total_students_with_active_r_grade_burden']}.",
            (
                f"Immediate attendance-pressure hotspot: {top_subject['subject_name']} is currently pulling {top_subject['students_below_threshold']} students below threshold."
                if top_subject is not None
                else None
            ),
        ]
        key_points = [point for point in key_points if point]
        return (
            build_grounded_response(
                opening=opening,
                key_points=key_points,
                tools_used=[
                    {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Interpreted a natural-language counsellor request into a priority-queue plan"},
                    {"tool_name": "counsellor_high_risk_count", "summary": "Ranked the current high-risk students in counsellor scope"},
                    {"tool_name": "counsellor_academic_scope_summary", "summary": "Added attendance-pressure and carry-forward burden context for the same counsellor scope"},
                ],
                limitations=[],
                closing=(
                    "If you want, I can next turn this into a counsellor action plan."
                    if focus_like
                    else "If you want, I can next explain one student or turn this into a counsellor action plan."
                ),
            ),
            [
                {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Interpreted a natural-language counsellor request into a priority-queue plan"},
                {"tool_name": "counsellor_high_risk_count", "summary": "Ranked the current high-risk students in counsellor scope"},
                {"tool_name": "counsellor_academic_scope_summary", "summary": "Added attendance-pressure and carry-forward burden context for the same counsellor scope"},
            ],
            [],
            {
                "kind": "cohort",
                "intent": "counsellor_priority_follow_up",
                "student_ids": [int(profile.student_id) for profile in top_items],
                "scope": "counsellor_attention_summary",
                "role_scope": "counsellor",
                "pending_role_follow_up": "operational_actions",
                "response_type": "action" if focus_like else "data",
                "last_topic": "high_risk_students",
                "planner_version": str(planner.get("version") or COPILOT_SYSTEM_PROMPT_VERSION),
            },
        )

    if planner.get("comparison", {}).get("enabled"):
        comparison_answer = _build_scoped_comparison_answer(
            scope_label="your current counsellor scope",
            repository=repository,
            profiles=counsellor_profiles,
            latest_predictions_by_student=latest_predictions,
            planner=planner,
            lowered=lowered,
            tool_prefix="counsellor",
        )
        if comparison_answer is not None:
            return comparison_answer

    if query_topic == "fresh_filter":
        return _answer_counsellor_fresh_filter_request(
            repository=repository,
            profiles=counsellor_profiles,
            latest_predictions=latest_predictions,
            lowered=original_lowered,
        )

    if intent == "identity":
        return (
            build_grounded_response(
                opening=f"You are signed in as `{auth.role}` and this chat stays role-bound.",
                key_points=[f"Authenticated subject: {auth.subject}"],
                tools_used=[{"tool_name": "identity_scope", "summary": "Returned current authenticated counsellor scope"}],
                limitations=[],
                closing="As later phases arrive, I will still respect role boundaries.",
            ),
            [{"tool_name": "identity_scope", "summary": "Returned current authenticated counsellor scope"}],
            [],
            {"kind": "identity", "intent": "identity"},
        )

    if intent == "help":
        return (
            build_grounded_response(
                opening="I can currently help with a focused counsellor question set.",
                key_points=[
                    "high-risk cohort counts",
                    "student drilldowns by student_id",
                    "urgent follow-up and priority-queue visibility",
                    "attendance shortage, I-grade risk, and R-grade risk inside your assigned cohort",
                    "subjects that are pulling the most students below policy",
                ],
                tools_used=[{"tool_name": "counsellor_copilot_help", "summary": "Returned current counsellor copilot capabilities"}],
                limitations=[],
                closing="Try asking: 'which students have R-grade risk?', 'which subjects are causing most attendance issues?', or 'show details for student 880001'.",
            ),
            [{"tool_name": "counsellor_copilot_help", "summary": "Returned current counsellor copilot capabilities"}],
            [],
            {"kind": "help", "intent": "help"},
        )

    if intent == "cohort_summary" and _looks_like_counsellor_assigned_students_request(lowered):
        sample_profiles = sorted(
            counsellor_profiles,
            key=lambda profile: (
                -float(getattr(latest_predictions.get(int(profile.student_id)), "final_risk_probability", 0.0) or 0.0),
                int(profile.student_id),
            ),
        )
        sample_lines = _build_counsellor_student_sample_lines(
            profiles=sample_profiles,
            latest_predictions_by_student=latest_predictions,
            limit=10,
        )
        if "list" in original_lowered:
            opening = f"Here is the current assigned-student list for your counsellor scope ({len(counsellor_profiles)} students)."
        elif "under me" in original_lowered:
            opening = f"These are the students currently under your counsellor scope ({len(counsellor_profiles)} total)."
        else:
            opening = f"I found {len(counsellor_profiles)} students currently assigned to your counsellor scope."
        return (
            build_grounded_response(
                opening=opening,
                key_points=sample_lines,
                tools_used=[
                    {"tool_name": "counsellor_assignment_scope", "summary": "Returned the students currently assigned to this counsellor identity"},
                ],
                limitations=["I am showing up to 10 students in-chat to keep the list readable."],
                closing="If you want, I can next show only the currently high-risk students or turn this into a counsellor action list.",
            ),
            [
                {"tool_name": "counsellor_assignment_scope", "summary": "Returned the students currently assigned to this counsellor identity"},
            ],
            ["I am showing up to 10 students in-chat to keep the list readable."],
            {
                "kind": "import_coverage",
                "intent": "counsellor_assigned_students",
                "student_ids": [int(profile.student_id) for profile in counsellor_profiles],
                "role_scope": "counsellor",
                "pending_role_follow_up": "operational_actions",
            },
        )

    if query_topic in {"fresh_filter", "factor_reasoning"} or intent in {
        "cohort_summary",
        "unsupported",
        "imported_subset_follow_up",
        "counsellor_filtered_subset",
        "imported_subset_high_risk_only",
    }:
        fresh_filter_prompt = original_lowered.startswith("only ") or original_lowered.startswith("show only ")
        if fresh_filter_prompt:
            selected_branch = next(
                (
                    str(_profile_context_value(profile, "branch") or "").strip()
                    for profile in counsellor_profiles
                    if str(_profile_context_value(profile, "branch") or "").strip()
                    and str(_profile_context_value(profile, "branch") or "").strip().lower() in original_lowered
                ),
                "",
            )
            selected_year: int | None = None
            if "final year" in original_lowered:
                year_values = [
                    int(_profile_current_year(profile) or 0)
                    for profile in counsellor_profiles
                    if int(_profile_current_year(profile) or 0) > 0
                ]
                selected_year = max(year_values) if year_values else None
            else:
                year_match = re.search(r"\b([1-9])(?:st|nd|rd|th)\s+year\b", original_lowered)
                if year_match is not None:
                    selected_year = int(year_match.group(1))
            wants_only_high_risk = "only high risk" in original_lowered or "only high-risk" in original_lowered
            wants_low_attendance = "low attendance" in original_lowered
            wants_low_assignments = "low assignments" in original_lowered
            if selected_branch or selected_year is not None or wants_only_high_risk or wants_low_attendance or wants_low_assignments:
                semester_by_student = _semester_progress_by_student()
                latest_erp_by_student = _latest_erp_by_student()
                matched_profiles: list[object] = []
                sample_lines: list[str] = []
                for profile in counsellor_profiles:
                    student_id = int(profile.student_id)
                    semester_progress = semester_by_student.get(student_id)
                    prediction = latest_predictions.get(student_id)
                    latest_erp_event = latest_erp_by_student.get(student_id)
                    submission_rate = float(getattr(latest_erp_event, "assessment_submission_rate", 0.0) or 0.0) if latest_erp_event is not None else 0.0
                    matches = True
                    reasons: list[str] = []
                    if selected_branch and str(_profile_context_value(profile, "branch") or "").strip().lower() != selected_branch.lower():
                        matches = False
                    if selected_year is not None and int(_profile_current_year(profile) or 0) != selected_year:
                        matches = False
                    if wants_only_high_risk and not (
                        prediction is not None and int(getattr(prediction, "final_predicted_class", 0) or 0) == 1
                    ):
                        matches = False
                    if wants_low_attendance and not (
                        semester_progress is not None
                        and (
                            float(getattr(semester_progress, "overall_attendance_percent", 0.0) or 0.0) < 75.0
                            or str(getattr(semester_progress, "overall_status", "") or "").strip().upper() != "SAFE"
                        )
                    ):
                        matches = False
                    if wants_low_assignments and not (latest_erp_event is not None and submission_rate < 0.75):
                        matches = False
                    if matches:
                        if selected_branch:
                            reasons.append(f"branch {selected_branch}")
                        if selected_year is not None:
                            reasons.append(f"year {selected_year}")
                        if wants_only_high_risk:
                            reasons.append("prediction HIGH")
                        if wants_low_attendance and semester_progress is not None:
                            reasons.append(
                                f"attendance {float(getattr(semester_progress, 'overall_attendance_percent', 0.0) or 0.0):.1f}%"
                            )
                        if wants_low_assignments and latest_erp_event is not None:
                            reasons.append(f"assignment submission rate {submission_rate:.2f}")
                        matched_profiles.append(profile)
                        if len(sample_lines) < 5:
                            external_ref = str(getattr(profile, "external_student_ref", None) or "no ref")
                            sample_lines.append(
                                f"student_id {student_id} ({external_ref}): " + ", ".join(reasons or ["matched the current filter"])
                            )
                filter_parts: list[str] = []
                if selected_branch:
                    filter_parts.append(selected_branch)
                if selected_year is not None:
                    filter_parts.append(f"year {selected_year}")
                if wants_only_high_risk:
                    filter_parts.append("high-risk")
                if wants_low_attendance:
                    filter_parts.append("low-attendance")
                if wants_low_assignments:
                    filter_parts.append("low-assignment")
                filter_label = ", ".join(filter_parts) if filter_parts else "requested subset"
                return (
                    build_grounded_response(
                        opening=f"I found {len(matched_profiles)} matching students in your counsellor scope for the `{filter_label}` filter.",
                        key_points=sample_lines or ["No students currently match that exact filter in your scoped cohort."],
                        tools_used=[
                            {"tool_name": "counsellor_filter_scan", "summary": "Applied a fresh counsellor subset filter over the scoped cohort"},
                        ],
                        limitations=["I am showing up to 5 matching students in-chat to keep the filtered view readable."],
                        closing="If you want, I can next explain these students, show the top 5 inside this filtered set, or turn this subset into a counsellor action list.",
                    ),
                    [
                        {"tool_name": "counsellor_filter_scan", "summary": "Applied a fresh counsellor subset filter over the scoped cohort"},
                    ],
                    ["I am showing up to 5 matching students in-chat to keep the filtered view readable."],
                    {
                        "kind": "import_coverage",
                        "intent": "counsellor_filtered_subset",
                        "student_ids": [int(profile.student_id) for profile in matched_profiles],
                        "role_scope": "counsellor",
                        "pending_role_follow_up": "operational_actions",
                    },
                )
        if planner.get("user_goal") == "grouped_risk_breakdown":
            academic_summary = _academic_summary()
            return _build_grouped_risk_breakdown_answer(
                scope_label="your current counsellor scope",
                lowered=lowered,
                planner=planner,
                risk_breakdown=_risk_breakdown(),
                prediction_high_risk_count=len(high_risk_rows),
                overall_shortage_count=academic_summary["total_students_with_overall_shortage"],
                i_grade_count=academic_summary["total_students_with_i_grade_risk"],
                r_grade_count=academic_summary["total_students_with_r_grade_risk"],
                tool_prefix="counsellor",
            )
        if any(
            phrase in lowered
            for phrase in {
                "good attendance but high risk",
                "low lms but good marks",
                "high lms but low performance",
                "hidden risk students",
                "students affected by finance",
            }
        ):
            needs_attendance_only = "good attendance but high risk" in lowered or "hidden risk students" in lowered
            needs_lms_and_erp = "low lms but good marks" in lowered or "high lms but low performance" in lowered
            needs_finance = "students affected by finance" in lowered
            semester_by_student = _semester_progress_by_student() if (needs_attendance_only or needs_lms_and_erp) else {}
            latest_erp_by_student = _latest_erp_by_student() if needs_lms_and_erp else {}
            latest_lms_by_student = _latest_lms_by_student() if needs_lms_and_erp else {}
            latest_finance_by_student = _latest_finance_by_student() if needs_finance else {}
            matched_profiles: list[object] = []
            sample_lines: list[str] = []
            for profile in counsellor_profiles:
                student_id = int(profile.student_id)
                prediction = latest_predictions.get(student_id)
                semester_progress = semester_by_student.get(student_id)
                latest_erp_event = latest_erp_by_student.get(student_id) if latest_erp_by_student else None
                latest_lms_event = latest_lms_by_student.get(student_id) if latest_lms_by_student else None
                latest_finance_event = latest_finance_by_student.get(student_id) if latest_finance_by_student else None
                safe_attendance = bool(
                    semester_progress is not None
                    and (
                        str(getattr(semester_progress, "overall_status", "") or "").strip().upper() == "SAFE"
                        or float(getattr(semester_progress, "overall_attendance_percent", 0.0) or 0.0) >= 75.0
                    )
                )
                predicted_high = bool(
                    prediction is not None
                    and int(getattr(prediction, "final_predicted_class", 0) or 0) == 1
                )
                weighted_score = float(getattr(latest_erp_event, "weighted_assessment_score", 0.0) or 0.0) if latest_erp_event is not None else 0.0
                lms_clicks = int(getattr(latest_lms_event, "clicks_last_7d", 0) or 0) if latest_lms_event is not None else 0
                finance_affected = bool(
                    latest_finance_event is not None
                    and str(getattr(latest_finance_event, "payment_status", "") or "").strip().lower() not in {"paid", "clear"}
                ) or bool(
                    prediction is not None and float(getattr(prediction, "finance_modifier", 0.0) or 0.0) > 0.0
                )

                match = False
                reason = ""
                if "good attendance but high risk" in lowered or "hidden risk students" in lowered:
                    match = safe_attendance and predicted_high
                    if match:
                        reason = "SAFE attendance but still model-high-risk from broader non-attendance signals"
                elif "low lms but good marks" in lowered:
                    match = lms_clicks < 100 and weighted_score >= 60.0
                    if match:
                        reason = f"low LMS activity ({lms_clicks} clicks/7d) despite a weighted score of {weighted_score:.1f}"
                elif "high lms but low performance" in lowered:
                    match = lms_clicks >= 100 and weighted_score < 50.0
                    if match:
                        reason = f"strong LMS activity ({lms_clicks} clicks/7d) but weak weighted score of {weighted_score:.1f}"
                elif "students affected by finance" in lowered:
                    match = finance_affected
                    if match:
                        finance_status = str(getattr(latest_finance_event, "payment_status", "Unknown")) if latest_finance_event is not None else "Finance modifier only"
                        reason = f"finance pressure is active ({finance_status})"

                if match:
                    matched_profiles.append(profile)
                    if len(sample_lines) < 5:
                        external_ref = str(getattr(profile, "external_student_ref", None) or "no ref")
                        sample_lines.append(f"student_id {student_id} ({external_ref}): {reason}.")

            if "good attendance but high risk" in lowered:
                opening = f"I found {len(matched_profiles)} students in your current counsellor scope with SAFE-looking attendance but current model HIGH risk."
            elif "low lms but good marks" in lowered:
                opening = f"I found {len(matched_profiles)} students in your current counsellor scope with low LMS activity but comparatively better assessed marks."
            elif "high lms but low performance" in lowered:
                opening = f"I found {len(matched_profiles)} students in your current counsellor scope with strong LMS activity but weaker academic performance."
            elif "students affected by finance" in lowered:
                opening = f"I found {len(matched_profiles)} students in your current counsellor scope where finance pressure is still affecting the risk picture."
            else:
                opening = f"I found {len(matched_profiles)} hidden-risk students in your current counsellor scope."

            closing = "If you want, I can next rank these students, explain the common pattern, or turn this into a counsellor action list."
            return (
                build_grounded_response(
                    opening=opening,
                    key_points=sample_lines or ["No students currently match that exact cross-feature pattern in your scoped cohort."],
                    tools_used=[
                        {"tool_name": "counsellor_cross_feature_scan", "summary": "Scanned the scoped cohort for a specific cross-feature risk pattern using attendance, LMS, ERP, finance, and prediction data"},
                    ],
                    limitations=["I am showing up to 5 matching students in-chat to keep the answer readable."],
                    closing=closing,
                ),
                [
                    {"tool_name": "counsellor_cross_feature_scan", "summary": "Scanned the scoped cohort for a specific cross-feature risk pattern using attendance, LMS, ERP, finance, and prediction data"},
                ],
                ["I am showing up to 5 matching students in-chat to keep the answer readable."],
                {
                    "kind": "cohort",
                    "intent": "cohort_summary",
                    "student_ids": [int(profile.student_id) for profile in matched_profiles],
                    "scope": "counsellor_cross_feature_subset",
                    "pending_role_follow_up": "operational_actions",
                },
            )
        if any(
            phrase in lowered
            for phrase in {
                "compare attendance and assignments for risky students",
                "compare assignments and attendance for risky students",
            }
        ):
            high_risk_profiles = [
                profile
                for profile in counsellor_profiles
                if latest_predictions.get(int(profile.student_id)) is not None
                and int(getattr(latest_predictions[int(profile.student_id)], "final_predicted_class", 0) or 0) == 1
            ]
            progress_by_student = _semester_progress_by_student()
            latest_erp_by_student = _latest_erp_by_student()
            attendance_pressure_count = 0
            assignment_pressure_count = 0
            sample_lines: list[str] = []
            for profile in high_risk_profiles[:5]:
                student_id = int(profile.student_id)
                progress_row = progress_by_student.get(student_id)
                latest_erp_event = latest_erp_by_student.get(student_id)
                overall_status = str(getattr(progress_row, "overall_status", "") or "").strip().upper() if progress_row is not None else ""
                attendance_pressure = overall_status not in {"", "SAFE"} or bool(getattr(progress_row, "has_i_grade_risk", False)) or bool(getattr(progress_row, "has_r_grade_risk", False))
                submission_rate = float(getattr(latest_erp_event, "assessment_submission_rate", 0.0) or 0.0) if latest_erp_event is not None else 0.0
                assignment_pressure = submission_rate < 0.75
                if attendance_pressure:
                    attendance_pressure_count += 1
                if assignment_pressure:
                    assignment_pressure_count += 1
                sample_lines.append(
                    f"student_id {student_id}: attendance pressure={'yes' if attendance_pressure else 'no'}, assignments pressure={'yes' if assignment_pressure else 'no'}, submission rate={submission_rate:.2f}."
                )
            stronger_driver = "assignments" if assignment_pressure_count >= attendance_pressure_count else "attendance"
            return (
                build_grounded_response(
                    opening="Here is the grounded compare view for attendance and assignments across risky students in your counsellor scope.",
                    key_points=[
                        f"Attendance pressure is currently visible in {attendance_pressure_count} of {len(high_risk_profiles)} risky students.",
                        f"Assignments pressure is currently visible in {assignment_pressure_count} of {len(high_risk_profiles)} risky students.",
                        f"Pressure comparison: {stronger_driver} is the more common visible driver across this risky subset right now.",
                        *sample_lines,
                    ],
                    tools_used=[
                        {"tool_name": "counsellor_risky_subset_compare", "summary": "Compared attendance-policy pressure and assignment submission pressure across the current risky subset"},
                    ],
                    limitations=["I am showing up to 5 risky students in-chat to keep the comparison readable."],
                ),
                [
                    {"tool_name": "counsellor_risky_subset_compare", "summary": "Compared attendance-policy pressure and assignment submission pressure across the current risky subset"},
                ],
                ["I am showing up to 5 risky students in-chat to keep the comparison readable."],
                {
                    "kind": "cohort",
                    "intent": "counsellor_risky_subset_compare",
                    "student_ids": [int(profile.student_id) for profile in high_risk_profiles],
                    "role_scope": "counsellor",
                    "pending_role_follow_up": "operational_actions",
                },
            )
        if "which students are improving vs declining" in lowered:
            progress_by_student = _semester_progress_by_student()
            latest_erp_by_student = _latest_erp_by_student()
            improving_lines: list[str] = []
            declining_lines: list[str] = []
            for profile in counsellor_profiles:
                student_id = int(profile.student_id)
                progress_row = progress_by_student.get(student_id)
                latest_prediction = latest_predictions.get(student_id)
                latest_erp_event = latest_erp_by_student.get(student_id)
                weighted_score = float(getattr(latest_erp_event, "weighted_assessment_score", 0.0) or 0.0) if latest_erp_event is not None else 0.0
                overall_status = str(getattr(progress_row, "overall_status", "") or "").strip().upper() if progress_row is not None else ""
                predicted_high = latest_prediction is not None and int(getattr(latest_prediction, "final_predicted_class", 0) or 0) == 1
                if not predicted_high and overall_status == "SAFE" and weighted_score >= 60.0 and len(improving_lines) < 3:
                    improving_lines.append(f"student_id {student_id}: improving view with SAFE attendance and weighted score {weighted_score:.1f}.")
                elif (predicted_high or overall_status not in {"", "SAFE"} or weighted_score < 50.0) and len(declining_lines) < 3:
                    declining_lines.append(f"student_id {student_id}: declining view with current pressure from risk/attendance/coursework signals.")
            return (
                build_grounded_response(
                    opening="Here is the grounded improving-versus-declining view for students in your counsellor scope.",
                    key_points=[
                        f"Matching students in improving view: {len(improving_lines)} shown.",
                        *improving_lines,
                        f"Matching students in declining view: {len(declining_lines)} shown.",
                        *declining_lines,
                    ],
                    tools_used=[
                        {"tool_name": "counsellor_student_trend_split", "summary": "Split the scoped students into improving-versus-declining buckets using current risk, attendance, and coursework pressure"},
                    ],
                    limitations=["This is a current grounded posture split, not a long historical trend model."],
                ),
                [
                    {"tool_name": "counsellor_student_trend_split", "summary": "Split the scoped students into improving-versus-declining buckets using current risk, attendance, and coursework pressure"},
                ],
                ["This is a current grounded posture split, not a long historical trend model."],
                {
                    "kind": "cohort",
                    "intent": "counsellor_student_trend_split",
                    "role_scope": "counsellor",
                    "pending_role_follow_up": "operational_actions",
                },
            )
        if any(
            phrase in lowered
            for phrase in {
                "why are many students struggling",
                "what is main issue in my students",
                "what is main problem in my students",
                "why are they performing poorly",
                "which students are not doing well",
                "who is in trouble",
                "is situation serious",
                "should i worry about my group",
                "are things getting worse",
                "which student will fail",
                "what is biggest issue across my students",
                "which factor is affecting most students",
                "which group is performing worst",
                "which department has more risk",
                "are my students improving",
                "is risk increasing in my group",
            }
        ):
            academic_summary = _academic_summary()
            burden_summary = _burden_summary()
            top_subject = academic_summary["top_subjects"][0] if academic_summary["top_subjects"] else None
            top_branch = academic_summary["branch_pressure"][0] if academic_summary["branch_pressure"] else None
            opening = "Here is the grounded explanation for the main pressure across your current counsellor scope."
            key_points = [
                f"Current prediction high-risk students in your scope: {len(high_risk_rows)}.",
                f"I-grade attendance risk in the same scope: {academic_summary['total_students_with_i_grade_risk']}.",
                f"R-grade attendance risk in the same scope: {academic_summary['total_students_with_r_grade_risk']}.",
            ]
            if any(phrase in lowered for phrase in {"main issue", "main problem"}):
                opening = "Here is the grounded explanation for the main issue across your current counsellor scope."
                key_points.insert(0, "Main issue summary: academic strain and attendance-policy pressure are compounding each other across the same cohort.")
            elif "what is biggest issue across my students" in lowered or "biggest issue" in lowered:
                opening = "Here is the grounded explanation for the biggest issue across your current counsellor scope."
                key_points.insert(0, "Biggest-issue view: the same students are being hit by overlapping academic strain, attendance-policy pressure, and carry-forward burden, so support demand is clustering instead of spreading evenly.")
            elif "which factor is affecting most students" in lowered:
                opening = "Here is the grounded view of the factor affecting the most students in your current counsellor scope."
                key_points.insert(0, "Most-common-factor view: attendance-policy pressure is touching the widest share of students, while prediction-high risk remains concentrated in the sharper pressure cluster.")
            elif any(phrase in lowered for phrase in {"performing poorly", "struggling", "not doing well", "in trouble"}):
                opening = "Here is why multiple students in your current counsellor scope are under pressure right now."
                key_points.insert(0, "Performance explanation: the pressure is concentrated in a small high-risk cohort, but attendance-policy strain and unresolved burden are widening the support load.")
            elif any(phrase in lowered for phrase in {"improving", "getting worse"}):
                opening = "Here is the grounded improvement-versus-pressure view for your current counsellor scope."
                key_points.insert(0, "Trend caution: this answer is based on the current grounded pressure snapshot, so it is strongest for current posture rather than long-range historical trend scoring.")
            elif "which department has more risk" in lowered:
                opening = "Here is the grounded department-risk comparison inside your current counsellor scope."
                key_points.insert(0, "Department-risk view: branch pressure is not evenly spread, and one department is currently carrying the heavier attendance-policy and risk load.")
            elif "which group is performing worst" in lowered:
                opening = "Here is the grounded explanation for the most pressured subgroup in your current counsellor scope."
                key_points.insert(0, "Worst-group view: one subgroup is currently absorbing more visible academic strain than the rest of the scoped cohort.")
            elif "is risk increasing in my group" in lowered:
                opening = "Here is the grounded risk-direction view for your current counsellor scope."
                key_points.insert(0, "Risk-direction caution: this is a current pressure reading, so it answers whether your group looks more pressured now rather than proving a long historical trend.")
            elif "should i worry about my group" in lowered:
                opening = "Here is the grounded group-risk seriousness view for your current counsellor scope."
                key_points.insert(0, "Worry-level view: the situation is serious enough to need active prioritization, but it is still actionable because the pressure is concentrated in identifiable students and hotspots rather than being uniformly severe everywhere.")
            elif "which student will fail" in lowered:
                opening = "Here is the grounded consequence view for the highest-pressure students in your current counsellor scope."
                key_points.insert(0, "Failure-risk view: no grounded system should promise one exact failure outcome, but the students sitting at the top of the current high-risk and burden cluster are the ones most likely to deteriorate first if support is delayed.")
            elif "who will fail if ignored" in lowered:
                opening = "Here is the grounded consequence view if the current counsellor pressure cluster is ignored."
                key_points.insert(0, "Consequence view: no model can promise exactly who will fail, but the highest-pressure students are the ones most likely to deteriorate first if support is withheld.")
            if top_subject is not None:
                key_points.append(
                    f"The strongest visible attendance-pressure hotspot right now is {top_subject['subject_name']}, where {top_subject['students_below_threshold']} students are below threshold."
                )
            if top_branch is not None:
                key_points.append(
                    f"The most pressured branch in your current scope is {top_branch['bucket_label']} with {top_branch['students_with_overall_shortage']} overall-shortage cases."
                )
            if burden_summary["total_students_with_active_academic_burden"]:
                key_points.append(
                    f"Carry-forward burden is also active: {burden_summary['total_students_with_active_i_grade_burden']} unresolved I-grade and {burden_summary['total_students_with_active_r_grade_burden']} unresolved R-grade cases still need monitoring."
                )
            key_points.append(
                "The main pattern is broader than one metric alone: current risk pressure is being reinforced by academic strain, attendance-policy pressure, and unresolved burden inside the same counsellor scope."
            )
            return (
                build_grounded_response(
                    opening=opening,
                    key_points=key_points,
                    tools_used=[
                        {"tool_name": "counsellor_intent_router", "summary": "Routed a counsellor cohort-explanation request"},
                        {"tool_name": "counsellor_academic_scope_summary", "summary": "Explained the main academic and attendance pressure across the scoped cohort"},
                    ],
                    limitations=[],
                    closing="If you want, I can next turn this into a counsellor action plan or narrow it to one branch, year, or student subset.",
                ),
                [
                    {"tool_name": "counsellor_intent_router", "summary": "Routed a counsellor cohort-explanation request"},
                    {"tool_name": "counsellor_academic_scope_summary", "summary": "Explained the main academic and attendance pressure across the scoped cohort"},
                ],
                [],
                {
                    "kind": "cohort",
                    "intent": "cohort_summary",
                    "student_ids": [int(row.student_id) for row in high_risk_rows],
                    "role_scope": "counsellor",
                    "pending_role_follow_up": "operational_actions",
                    "response_type": "explanation",
                    "last_topic": "cohort_summary",
                },
            )
        if any(
            token in lowered
            for token in {
                "weekly monitoring",
                "monthly monitoring",
                "doing fine now",
                "unresolved burden",
                "still needs weekly monitoring",
                "still need weekly monitoring",
                "still needs monthly monitoring",
                "still need monthly monitoring",
            }
        ):
            burden_rows = _build_active_burden_student_rows(
                repository=repository,
                student_ids=owned_student_ids or None,
            )
            weekly_rows = [row for row in burden_rows if row["monitoring_cadence"] == "WEEKLY"]
            monthly_rows = [row for row in burden_rows if row["monitoring_cadence"] == "MONTHLY"]
            sample_rows = weekly_rows[:5] if weekly_rows else monthly_rows[:5]
            return (
                build_grounded_response(
                    opening=(
                        f"Yes. Even if some students look better in the current semester, unresolved academic burden can still keep them on monitoring inside your current counsellor scope."
                    ),
                    key_points=[
                        f"Weekly monitoring cases from unresolved R-grade burden: {len(weekly_rows)}.",
                        f"Monthly monitoring cases from unresolved I-grade burden: {len(monthly_rows)}.",
                        *[
                            f"student_id {int(item['student_id'])}: {item['summary']} ({str(item['monitoring_cadence']).replace('_', ' ')})"
                            for item in sample_rows
                        ],
                    ],
                    tools_used=[
                        {"tool_name": "counsellor_intent_router", "summary": "Routed a counsellor unresolved-burden monitoring question"},
                        {"tool_name": "counsellor_active_burden_summary", "summary": "Summarized students who still need weekly or monthly monitoring because of uncleared I/R-grade burden"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "counsellor_intent_router", "summary": "Routed a counsellor unresolved-burden monitoring question"},
                    {"tool_name": "counsellor_active_burden_summary", "summary": "Summarized students who still need weekly or monthly monitoring because of uncleared I/R-grade burden"},
                ],
                [],
                {"kind": "cohort", "intent": "counsellor_active_burden_monitoring"},
            )
        if any(token in lowered for token in {"branch", "department"}) and any(
            token in lowered for token in {"attention", "pressure", "worst", "highest"}
        ):
            academic_summary = _academic_summary()
            top_branch = academic_summary["branch_pressure"][0] if academic_summary["branch_pressure"] else None
            if top_branch is not None:
                return (
                    build_grounded_response(
                        opening=f"The branch needing the most counsellor attention in your current scope is {top_branch['bucket_label']}.",
                        key_points=[
                            f"It currently shows {top_branch['students_with_overall_shortage']} students below overall attendance, {top_branch['students_with_i_grade_risk']} students with I-grade risk, and {top_branch['students_with_r_grade_risk']} students with R-grade risk.",
                            (
                                f"Average visible overall attendance there is {float(top_branch['average_overall_attendance_percent']):.2f}%."
                                if top_branch["average_overall_attendance_percent"] is not None
                                else "Average visible overall attendance is not available for this branch yet."
                            ),
                        ],
                        tools_used=[
                            {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor branch-pressure question"},
                            {"tool_name": "counsellor_academic_scope_summary", "summary": "Compared branch-level attendance pressure inside counsellor scope"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor branch-pressure question"},
                        {"tool_name": "counsellor_academic_scope_summary", "summary": "Compared branch-level attendance pressure inside counsellor scope"},
                    ],
                    [],
                    {"kind": "cohort", "intent": "counsellor_branch_pressure"},
                )
        if any(token in lowered for token in {"semester", "sem"}) and any(
            token in lowered for token in {"attention", "pressure", "worst", "highest"}
        ):
            academic_summary = _academic_summary()
            top_semester = academic_summary["semester_pressure"][0] if academic_summary["semester_pressure"] else None
            if top_semester is not None:
                return (
                    build_grounded_response(
                        opening=f"The semester slice needing the most counsellor attention right now is {top_semester['bucket_label']}.",
                        key_points=[
                            f"It currently shows {top_semester['students_with_overall_shortage']} students below overall attendance, {top_semester['students_with_i_grade_risk']} students with I-grade risk, and {top_semester['students_with_r_grade_risk']} students with R-grade risk.",
                            (
                                f"Average visible overall attendance there is {float(top_semester['average_overall_attendance_percent']):.2f}%."
                                if top_semester["average_overall_attendance_percent"] is not None
                                else "Average visible overall attendance is not available for this semester slice yet."
                            ),
                        ],
                        tools_used=[
                            {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor semester-pressure question"},
                            {"tool_name": "counsellor_academic_scope_summary", "summary": "Compared semester-level attendance pressure inside counsellor scope"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor semester-pressure question"},
                        {"tool_name": "counsellor_academic_scope_summary", "summary": "Compared semester-level attendance pressure inside counsellor scope"},
                    ],
                    [],
                    {"kind": "cohort", "intent": "counsellor_semester_pressure"},
                )
        if any(token in lowered for token in {"i grade", "i-grade", "condonation"}):
            academic_summary = _academic_summary()
            burden_summary = _burden_summary()
            top_items = [
                item
                for item in academic_summary["top_students"]
                if item["has_i_grade_risk"]
            ][:5]
            return (
                build_grounded_response(
                    opening=(
                        f"There are {academic_summary['total_students_with_i_grade_risk']} students in your current counsellor scope with current-semester I-grade attendance risk, "
                        f"and {burden_summary['total_students_with_active_i_grade_burden']} students still carry an unresolved I-grade burden."
                    ),
                    key_points=[
                        *[
                            f"student_id {item['student_id']}: weakest subject {item['weakest_subject_name']} at {item['weakest_subject_percent']:.2f}%."
                            for item in top_items
                            if item["weakest_subject_percent"] is not None
                        ],
                        (
                            f"Monitoring note: these unresolved I-grade cases should stay on at least monthly counsellor review until the subject is actually cleared."
                            if burden_summary["total_students_with_active_i_grade_burden"]
                            else "No unresolved I-grade carry-forward burden is currently active in your scoped cohort."
                        ),
                    ],
                    tools_used=[
                        {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor I-grade cohort request"},
                        {"tool_name": "counsellor_academic_scope_summary", "summary": "Summarized current I-grade risk inside the counsellor-assigned academic cohort"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor I-grade cohort request"},
                    {"tool_name": "counsellor_academic_scope_summary", "summary": "Summarized current I-grade risk inside the counsellor-assigned academic cohort"},
                ],
                [],
                {"kind": "cohort", "intent": "counsellor_i_grade_summary"},
            )
        if any(token in lowered for token in {"r grade", "r-grade", "repeat grade", "repeat subject"}):
            academic_summary = _academic_summary()
            burden_summary = _burden_summary()
            top_items = [
                item
                for item in academic_summary["top_students"]
                if item["has_r_grade_risk"]
            ][:5]
            return (
                build_grounded_response(
                    opening=(
                        f"There are {academic_summary['total_students_with_r_grade_risk']} students in your current counsellor scope with current-semester R-grade attendance risk, "
                        f"and {burden_summary['total_students_with_active_r_grade_burden']} students still carry an unresolved R-grade burden."
                    ),
                    key_points=[
                        *[
                            f"student_id {item['student_id']}: weakest subject {item['weakest_subject_name']} at {item['weakest_subject_percent']:.2f}% and needs immediate recovery attention."
                            for item in top_items
                            if item["weakest_subject_percent"] is not None
                        ],
                        (
                            f"Monitoring note: these unresolved R-grade cases should stay on at least weekly counsellor review until the repeat-grade subject is actually cleared."
                            if burden_summary["total_students_with_active_r_grade_burden"]
                            else "No unresolved R-grade carry-forward burden is currently active in your scoped cohort."
                        ),
                    ],
                    tools_used=[
                        {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor R-grade cohort request"},
                        {"tool_name": "counsellor_academic_scope_summary", "summary": "Summarized current R-grade risk inside the counsellor-assigned academic cohort"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor R-grade cohort request"},
                    {"tool_name": "counsellor_academic_scope_summary", "summary": "Summarized current R-grade risk inside the counsellor-assigned academic cohort"},
                ],
                [],
                {"kind": "cohort", "intent": "counsellor_r_grade_summary"},
            )
        if any(token in lowered for token in {"attendance", "subject", "policy", "below 75"}):
            academic_summary = _academic_summary()
            burden_summary = _burden_summary()
            top_subjects = academic_summary["top_subjects"][:5]
            return (
                build_grounded_response(
                    opening=(
                        f"In your current counsellor scope, {academic_summary['total_students_with_overall_shortage']} students are below the overall attendance requirement, "
                        f"{academic_summary['total_students_with_i_grade_risk']} have I-grade risk, {academic_summary['total_students_with_r_grade_risk']} have R-grade risk, and "
                        f"{burden_summary['total_students_with_active_academic_burden']} still carry unresolved academic burden from earlier I/R grade outcomes."
                    ),
                    key_points=[
                        *[
                            f"{item['subject_name']}: {item['students_below_threshold']} students below threshold, including {item['r_grade_students']} R-grade and {item['i_grade_students']} I-grade cases."
                            for item in top_subjects
                        ],
                        (
                            f"Carry-forward monitoring: {burden_summary['total_students_with_active_i_grade_burden']} unresolved I-grade and {burden_summary['total_students_with_active_r_grade_burden']} unresolved R-grade students remain on counsellor monitoring."
                            if burden_summary["total_students_with_active_academic_burden"]
                            else "No unresolved carry-forward academic burden is currently active in your scoped cohort."
                        ),
                        *(
                            [
                                f"Most pressured branch in your current scope: {academic_summary['branch_pressure'][0]['bucket_label']}."
                            ]
                            if academic_summary["branch_pressure"]
                            else []
                        ),
                    ],
                    tools_used=[
                        {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor academic-attendance cohort request"},
                        {"tool_name": "counsellor_academic_scope_summary", "summary": "Summarized subject pressure and attendance-policy risk inside the counsellor cohort"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor academic-attendance cohort request"},
                    {"tool_name": "counsellor_academic_scope_summary", "summary": "Summarized subject pressure and attendance-policy risk inside the counsellor cohort"},
                ],
                [],
                {"kind": "cohort", "intent": "counsellor_attendance_pressure_summary"},
            )
        if any(token in lowered for token in {"urgent", "priority", "follow-up", "followup", "overdue"}):
            ranked_high_risk_profiles = [
                profile
                for profile in counsellor_profiles
                if latest_predictions.get(int(profile.student_id)) is not None
                and int(getattr(latest_predictions[int(profile.student_id)], "final_predicted_class", 0)) == 1
            ]
            ranked_high_risk_profiles.sort(
                key=lambda profile: (
                    -float(getattr(latest_predictions[int(profile.student_id)], "final_risk_probability", 0.0) or 0.0),
                    int(profile.student_id),
                )
            )
            top_items = ranked_high_risk_profiles[:5]
            sample_lines = _build_counsellor_student_sample_lines(
                profiles=ranked_high_risk_profiles,
                latest_predictions_by_student=latest_predictions,
                limit=5,
            )
            burden_summary = _burden_summary()
            return (
                build_grounded_response(
                    opening="Here are the most urgent cases in your current counsellor scope.",
                    key_points=[
                        *sample_lines,
                        f"Current prediction high-risk students in this urgent view: {len(ranked_high_risk_profiles)}.",
                        f"Unresolved R-grade burden still needing weekly monitoring: {burden_summary['total_students_with_active_r_grade_burden']}.",
                    ],
                    tools_used=[
                        {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor urgent-follow-up request"},
                        {"tool_name": "counsellor_high_risk_count", "summary": "Ranked the current high-risk students in counsellor scope"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor urgent-follow-up request"},
                    {"tool_name": "counsellor_high_risk_count", "summary": "Ranked the current high-risk students in counsellor scope"},
                ],
                [],
                {
                    "kind": "cohort",
                    "intent": "counsellor_priority_follow_up",
                    "student_ids": [int(profile.student_id) for profile in top_items],
                    "scope": "counsellor_attention_summary",
                    "response_type": "data",
                    "last_topic": "high_risk_students",
                },
            )
        if (
            "high risk" in lowered
            or "high-risk" in lowered
            or "most critical" in original_lowered
            or "worst performing" in original_lowered
            or "worst student" in original_lowered
            or "top 5" in original_lowered
            or "top 3" in original_lowered
            or str(planner.get("normalized_message") or "").strip().lower() in {"show top 3 risky students", "show top 5 risky students"}
            or str(planner.get("normalized_message") or "").strip().lower() == "which students are high risk"
        ) and not any(
            phrase in lowered
            for phrase in {
                "compare attendance and assignments for risky students",
                "compare assignments and attendance for risky students",
            }
        ):
            academic_summary = _academic_summary()
            ranked_high_risk_profiles = [
                profile
                for profile in counsellor_profiles
                if latest_predictions.get(int(profile.student_id)) is not None
                and int(getattr(latest_predictions[int(profile.student_id)], "final_predicted_class", 0)) == 1
            ]
            ranked_high_risk_profiles.sort(
                key=lambda profile: (
                    -float(getattr(latest_predictions[int(profile.student_id)], "final_risk_probability", 0.0) or 0.0),
                    int(profile.student_id),
                )
            )
            sample_lines = _build_counsellor_student_sample_lines(
                profiles=ranked_high_risk_profiles,
                latest_predictions_by_student=latest_predictions,
                limit=_extract_requested_top_limit(original_lowered) or 5,
            )
            count_like = any(token in original_lowered for token in {"how many", "count", "number"})
            requested_top_limit = _extract_requested_top_limit(original_lowered)
            asks_top_5 = "top 5" in original_lowered
            asks_top_3 = "top 3" in original_lowered
            asks_most_critical = "most critical" in original_lowered
            asks_worst_performing = "worst performing" in original_lowered or "worst student" in original_lowered
            top_like = asks_top_5 or asks_top_3 or asks_most_critical or asks_worst_performing or requested_top_limit is not None
            if count_like:
                if "danger" in original_lowered:
                    opening = f"The number of students currently in danger inside your counsellor scope is {len(high_risk_rows)}."
                    closing = "If you want, I can next list the exact student IDs in danger or turn this into a counsellor action list."
                elif "total" in original_lowered:
                    opening = f"The total number of currently high-risk students inside your counsellor scope is {len(high_risk_rows)}."
                    closing = "If you want, I can next break this count down into exact student IDs or a counsellor action list."
                else:
                    opening = f"There are currently {len(high_risk_rows)} students in the latest prediction high-risk cohort inside your counsellor scope."
                    closing = "If you want, I can next list the exact student IDs or turn this into a counsellor action list."
                key_points = [
                    f"I-grade risk in the same scope: {academic_summary['total_students_with_i_grade_risk']}.",
                    f"R-grade risk in the same scope: {academic_summary['total_students_with_r_grade_risk']}.",
                ]
            elif top_like:
                display_limit = requested_top_limit or 5
                opening = f"Here are the top {display_limit} current risk-priority students in your counsellor scope ({len(ranked_high_risk_profiles)} matched right now)."
                if asks_most_critical:
                    opening = f"Here are the most critical students in your counsellor scope right now (showing up to 5, currently {len(ranked_high_risk_profiles)} matched)."
                elif asks_worst_performing:
                    opening = f"Here are the students currently performing worst from a grounded risk-and-pressure view in your counsellor scope (showing up to 5, currently {len(ranked_high_risk_profiles)} matched)."
                elif asks_top_3:
                    opening = f"Here are the top 3 current risk-priority students in your counsellor scope ({len(ranked_high_risk_profiles)} matched right now)."
                header = "Top 5 view:"
                if requested_top_limit == 3:
                    header = "Top 3 view:"
                if asks_most_critical:
                    header = "Most-critical view:"
                elif asks_worst_performing:
                    header = "Worst-performing risk view:"
                key_points = [
                    header,
                    *sample_lines,
                    (
                        "These students are being treated as most critical because they sit at the top of the current prediction-pressure queue."
                        if asks_most_critical
                        else "This view blends current prediction pressure with visible academic-risk signals rather than raw marks alone."
                        if asks_worst_performing
                        else None
                    ),
                    f"I-grade risk in the same scope: {academic_summary['total_students_with_i_grade_risk']}.",
                    f"R-grade risk in the same scope: {academic_summary['total_students_with_r_grade_risk']}.",
                ]
                key_points = [point for point in key_points if point]
                closing = "If you want, I can next explain one student or turn this ranking into a counsellor action list."
            elif "danger" in original_lowered:
                opening = f"Here are the students currently in danger inside your counsellor scope ({len(high_risk_rows)} in the latest prediction high-risk cohort)."
                key_points = [
                    *sample_lines,
                    f"I-grade risk in the same scope: {academic_summary['total_students_with_i_grade_risk']}.",
                    f"R-grade risk in the same scope: {academic_summary['total_students_with_r_grade_risk']}.",
                ]
                closing = "If you want, I can next explain one student, show only one bucket like CSE, or turn this into a counsellor action list."
            elif "show" in original_lowered:
                opening = f"Here is the current high-risk student view inside your counsellor scope ({len(high_risk_rows)} matched)."
                key_points = [
                    *sample_lines,
                    f"I-grade risk in the same scope: {academic_summary['total_students_with_i_grade_risk']}.",
                    f"R-grade risk in the same scope: {academic_summary['total_students_with_r_grade_risk']}.",
                ]
                closing = "If you want, I can next explain one student, show only one bucket like CSE, or turn this into a counsellor action list."
            elif "list" in original_lowered:
                opening = f"Here is the current risky-student list inside your counsellor scope ({len(high_risk_rows)} matched)."
                key_points = [
                    *sample_lines,
                    f"I-grade risk in the same scope: {academic_summary['total_students_with_i_grade_risk']}.",
                    f"R-grade risk in the same scope: {academic_summary['total_students_with_r_grade_risk']}.",
                ]
                closing = "If you want, I can next explain one student, show only one bucket like CSE, or turn this into a counsellor action list."
            else:
                opening = f"There are currently {len(high_risk_rows)} students in the latest prediction high-risk cohort inside your counsellor scope."
                key_points = [
                    *sample_lines,
                    f"I-grade risk in the same scope: {academic_summary['total_students_with_i_grade_risk']}.",
                    f"R-grade risk in the same scope: {academic_summary['total_students_with_r_grade_risk']}.",
                ]
                closing = "If you want, I can next explain one student, show only one bucket like CSE, or turn this into a counsellor action list."
            return (
                build_grounded_response(
                    opening=opening,
                    key_points=key_points,
                    tools_used=[
                        {"tool_name": "counsellor_high_risk_count", "summary": "Counted and ranked the current high-risk students in counsellor scope"},
                        {"tool_name": "counsellor_academic_scope_summary", "summary": "Added attendance-policy pressure context for the same counsellor scope"},
                    ],
                    limitations=["I am showing up to 5 students in-chat to keep the high-risk list readable."],
                    closing=closing,
                ),
                [
                    {"tool_name": "counsellor_high_risk_count", "summary": "Counted and ranked the current high-risk students in counsellor scope"},
                    {"tool_name": "counsellor_academic_scope_summary", "summary": "Added attendance-policy pressure context for the same counsellor scope"},
                ],
                ["I am showing up to 5 students in-chat to keep the high-risk list readable."],
                {
                    "kind": "import_coverage",
                    "intent": "counsellor_high_risk_students",
                    "student_ids": [int(profile.student_id) for profile in ranked_high_risk_profiles],
                    "role_scope": "counsellor",
                    "pending_role_follow_up": "operational_actions",
                },
            )
        return (
            build_grounded_response(
                opening=(
                    f"There are currently {len(high_risk_rows)} students in the latest high-risk cohort assigned to your counsellor scope, "
                    f"along with {_academic_summary()['total_students_with_i_grade_risk']} students showing I-grade attendance risk and "
                    f"{_academic_summary()['total_students_with_r_grade_risk']} showing R-grade risk."
                ),
                tools_used=[
                    {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor cohort summary intent"},
                    {"tool_name": "counsellor_high_risk_count", "summary": "Counted latest high-risk students in counsellor scope"},
                    {"tool_name": "counsellor_academic_scope_summary", "summary": "Added academic policy pressure counts for the same counsellor scope"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor cohort summary intent"},
                {"tool_name": "counsellor_high_risk_count", "summary": "Counted latest high-risk students in counsellor scope"},
                {"tool_name": "counsellor_academic_scope_summary", "summary": "Added academic policy pressure counts for the same counsellor scope"},
            ],
            [],
            {
                "kind": "cohort",
                "intent": "cohort_summary",
                "student_ids": [int(row.student_id) for row in high_risk_rows],
                "scope": "latest_high_risk_predictions_assigned",
            },
        )

    student_id = explicit_student_id if intent == "student_drilldown" else None
    if student_id is None:
        student_id = _student_id_from_memory(memory)
    should_reuse_student = (
        bool(memory.get("is_follow_up"))
        and student_id is not None
        and (
            memory.get("wants_contact_focus")
            or memory.get("wants_risk_focus")
            or str(last_context.get("pending_role_follow_up") or "").strip().lower() == "student_specific_action"
        )
    )
    if (intent == "student_drilldown" or should_reuse_student) and student_id is not None:
        profile = repository.get_student_profile(student_id)
        prediction = repository.get_latest_prediction_for_student(student_id)
        if profile is None:
            return (
                f"I could not find a student profile for student_id {student_id}.",
                [{"tool_name": "student_profile_lookup", "summary": "No profile found for requested student"}],
                [],
                {"kind": "student_drilldown", "student_id": student_id, "intent": "student_drilldown"},
            )
        if owned_student_ids and student_id not in owned_student_ids:
            return (
                build_grounded_response(
                    opening=f"I found student_id {student_id}, but that student is outside your counsellor assignment scope.",
                    key_points=["I can only show counsellor drilldowns for students currently assigned to your counsellor profile scope."],
                    tools_used=[
                        {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor student drilldown intent"},
                        {"tool_name": "assignment_scope_guard", "summary": "Blocked drilldown outside counsellor assignment scope"},
                    ],
                    limitations=["counsellor drilldowns stay limited to assigned students"],
                ),
                [
                    {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor student drilldown intent"},
                    {"tool_name": "assignment_scope_guard", "summary": "Blocked drilldown outside counsellor assignment scope"},
                ],
                ["counsellor drilldowns stay limited to assigned students"],
                {"kind": "student_drilldown", "student_id": student_id, "intent": "student_drilldown_out_of_scope"},
            )
        parts: list[str] = []
        if prediction is not None:
            parts.append(
                f"latest risk probability: {float(prediction.final_risk_probability):.4f}"
            )
        else:
            parts.append("no prediction available yet")
        academic_progress = repository.get_student_academic_progress_record(student_id)
        semester_progress = repository.get_latest_student_semester_progress_record(student_id)
        subject_rows = repository.get_current_student_subject_attendance_records(student_id)
        signal_bundle = _load_student_signal_bundle(repository=repository, student_id=student_id)
        parts.extend(
            _build_cross_signal_reasoning_points(
                signal_bundle=signal_bundle,
                current_semester_progress=semester_progress,
                include_availability_gap=True,
                include_reconciliation_notice=False,
                include_stability=False,
            )[:4]
        )
        academic_burden = build_academic_burden_summary(
            academic_rows=repository.get_student_academic_records(student_id),
            attendance_rows=repository.get_student_subject_attendance_records(student_id),
        )
        active_warning = repository.get_active_student_warning_for_student(student_id)
        weakest_subject = next(
            (row for row in subject_rows if row.subject_attendance_percent is not None),
            None,
        )
        if _looks_like_counsellor_student_action_request(lowered) or (
            bool(memory.get("is_follow_up"))
            and str(last_context.get("pending_role_follow_up") or "").strip().lower() == "student_specific_action"
        ):
            return _build_counsellor_student_action_answer(
                student_id=student_id,
                lowered=lowered,
                prediction=prediction,
                semester_progress=semester_progress,
                subject_rows=subject_rows,
                academic_burden=academic_burden,
                signal_bundle=signal_bundle,
                active_warning=active_warning,
            )
        if _looks_like_counsellor_student_reasoning_request(lowered):
            return _build_counsellor_student_reasoning_answer(
                student_id=student_id,
                lowered=lowered,
                profile=profile,
                prediction=prediction,
                semester_progress=semester_progress,
                subject_rows=subject_rows,
                academic_progress=academic_progress,
                academic_burden=academic_burden,
                signal_bundle=signal_bundle,
            )
        if semester_progress is not None and semester_progress.overall_attendance_percent is not None:
            parts.append(
                f"overall attendance: {float(semester_progress.overall_attendance_percent):.2f}% ({semester_progress.overall_status or 'unknown'})"
            )
        if semester_progress is not None and bool(semester_progress.has_r_grade_risk):
            parts.append("student currently has R-grade attendance risk")
        elif semester_progress is not None and bool(semester_progress.has_i_grade_risk):
            parts.append("student currently has I-grade attendance risk")
        if weakest_subject is not None and weakest_subject.subject_attendance_percent is not None:
            parts.append(
                f"weakest subject: {weakest_subject.subject_name} at {float(weakest_subject.subject_attendance_percent):.2f}%"
            )
        if academic_progress is not None and academic_progress.semester_mode:
            parts.append(f"semester mode: {academic_progress.semester_mode}")
        if academic_progress is not None:
            parts.append(
                f"academic position: year {academic_progress.current_year or 'unknown'}, semester {academic_progress.current_semester or 'unknown'}, branch {academic_progress.branch or 'unknown'}"
            )
            if academic_progress.total_backlogs is not None:
                parts.append(f"reported backlogs: {int(academic_progress.total_backlogs)}")
        if semester_progress is not None:
            parts.append(
                f"subjects below 75%: {int(semester_progress.subjects_below_75_count or 0)}; subjects below 65%: {int(semester_progress.subjects_below_65_count or 0)}"
            )
            if semester_progress.current_eligibility:
                parts.append(f"current eligibility: {semester_progress.current_eligibility}")
        if bool(academic_burden["has_active_burden"]):
            parts.append(f"active academic burden: {academic_burden['summary']}")
            parts.append(
                f"recommended monitoring cadence: {str(academic_burden['monitoring_cadence']).replace('_', ' ').title()}"
            )
        parts.extend(
            [
                f"email: {profile.student_email or 'not available'}",
                f"faculty: {profile.faculty_name or 'not assigned'}",
                f"counsellor: {getattr(profile, 'counsellor_name', None) or 'not assigned'}",
            ]
        )
        return (
            build_grounded_response(
                opening=f"I found a student drilldown for student_id {student_id}.",
                key_points=parts,
                tools_used=[
                    {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor student drilldown intent"},
                    {"tool_name": "student_profile_lookup", "summary": "Returned student profile details"},
                    {"tool_name": "latest_prediction_lookup", "summary": "Returned latest student prediction if available"},
                    {"tool_name": "student_cross_signal_reasoning", "summary": "Explained the student drilldown using prediction, LMS, ERP, finance, attendance, and burden signals when available"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor student drilldown intent"},
                {"tool_name": "student_profile_lookup", "summary": "Returned student profile details"},
                {"tool_name": "latest_prediction_lookup", "summary": "Returned latest student prediction if available"},
                {"tool_name": "student_cross_signal_reasoning", "summary": "Explained the student drilldown using prediction, LMS, ERP, finance, attendance, and burden signals when available"},
            ],
            [],
            {"kind": "student_drilldown", "student_id": student_id, "intent": "student_drilldown"},
        )

    return (
        build_grounded_response(
            opening=(
                "I can’t help with that request." if _is_sensitive_request(lowered) else "I didn’t fully match that to a counsellor intent yet."
            ),
            key_points=(
                ["I cannot share passwords or secrets."]
                if _is_sensitive_request(lowered)
                else [
                    "high-risk cohort counts",
                    "student drilldowns by student_id",
                    "attendance policy pressure, including I-grade and R-grade risk",
                    *(
                        [f"Did you mean: {', '.join(_build_intent_suggestions('counsellor', lowered))}?"]
                        if _build_intent_suggestions("counsellor", lowered)
                        else []
                    ),
                ]
            ),
            tools_used=[{"tool_name": "counsellor_intent_router", "summary": f"Routed unsupported counsellor intent `{intent}`"}],
            limitations=["counsellor question is outside the current supported cohort, attendance, or drilldown set"],
        ),
        [{"tool_name": "counsellor_intent_router", "summary": f"Routed unsupported counsellor intent `{intent}`"}],
        ["counsellor question is outside the current supported cohort, attendance, or drilldown set"],
        {"kind": "unsupported", "intent": "unsupported"},
    )


def _answer_admin_question(
    *,
    auth: AuthContext,
    repository: EventRepository,
    lowered: str,
    intent: str,
    memory: dict,
    query_plan: dict | None = None,
) -> tuple[str, list[dict], list[str], dict]:
    profiles = repository.get_imported_student_profiles()
    academic_summary: dict | None = None
    attendance_totals: dict[str, int] | None = None
    risk_breakdown: dict | None = None
    latest_predictions: list[object] | None = None
    high_risk_rows: list[object] | None = None
    interventions: list[object] | None = None
    warning_events: list[object] | None = None
    admin_signal_snapshot: dict | None = None

    def _get_academic_summary() -> dict:
        nonlocal academic_summary
        if academic_summary is None:
            academic_summary = _build_academic_scope_summary(repository=repository)
        return academic_summary

    def _get_attendance_totals() -> dict[str, int]:
        nonlocal attendance_totals
        if attendance_totals is None:
            attendance_totals = _build_attendance_risk_totals(repository=repository)
        return attendance_totals

    def _get_risk_breakdown() -> dict:
        nonlocal risk_breakdown
        if risk_breakdown is None:
            risk_breakdown = _build_prediction_and_attendance_breakdown(repository=repository)
        return risk_breakdown

    def _get_latest_predictions() -> list[object]:
        nonlocal latest_predictions
        if latest_predictions is None:
            latest_predictions = repository.get_latest_predictions_for_all_students()
        return latest_predictions

    def _get_high_risk_rows() -> list[object]:
        nonlocal high_risk_rows
        if high_risk_rows is None:
            high_risk_rows = [row for row in _get_latest_predictions() if int(row.final_predicted_class) == 1]
        return high_risk_rows

    def _get_interventions() -> list[object]:
        nonlocal interventions
        if interventions is None:
            interventions = repository.get_all_intervention_actions()
        return interventions

    def _get_warning_events() -> list[object]:
        nonlocal warning_events
        if warning_events is None:
            warning_events = repository.get_all_student_warning_events()
        return warning_events

    def _get_admin_signal_snapshot() -> dict:
        nonlocal admin_signal_snapshot
        if admin_signal_snapshot is not None:
            return admin_signal_snapshot

        high_risk_ids = [int(getattr(row, "student_id", 0) or 0) for row in _get_high_risk_rows()[:10] if int(getattr(row, "student_id", 0) or 0) > 0]
        profiles_by_student = {int(getattr(profile, "student_id", 0) or 0): profile for profile in profiles}
        snapshot = {
            "evaluated_students": len(high_risk_ids),
            "erp_pressure_count": 0,
            "lms_pressure_count": 0,
            "finance_pressure_count": 0,
            "safe_attendance_high_risk_count": 0,
            "driver_counts": {},
            "hidden_branch_counts": {},
        }
        for student_id in high_risk_ids:
            signal_bundle = _load_student_signal_bundle(repository=repository, student_id=student_id)
            intelligence = signal_bundle.get("intelligence") or {}
            risk_type = intelligence.get("risk_type") or {}
            primary_type = str(risk_type.get("primary_type") or "").strip()
            if primary_type:
                snapshot["driver_counts"][primary_type] = int(snapshot["driver_counts"].get(primary_type, 0) or 0) + 1

            latest_prediction = signal_bundle.get("latest_prediction")
            latest_erp_event = signal_bundle.get("latest_erp_event")
            latest_finance_event = signal_bundle.get("latest_finance_event")
            lms_summary = intelligence.get("lms_summary") or {}

            weighted_score = float(getattr(latest_erp_event, "weighted_assessment_score", 0.0) or 0.0) if latest_erp_event is not None else 0.0
            submission_rate = float(getattr(latest_erp_event, "assessment_submission_rate", 0.0) or 0.0) if latest_erp_event is not None else 0.0
            if latest_erp_event is not None and (weighted_score < 40.0 or submission_rate < 0.85):
                snapshot["erp_pressure_count"] = int(snapshot["erp_pressure_count"] or 0) + 1

            lms_clicks = int(lms_summary.get("lms_clicks_7d", 0) or 0)
            lms_resources = int(lms_summary.get("lms_unique_resources_7d", 0) or 0)
            if lms_summary and (lms_clicks < 40 or lms_resources < 4):
                snapshot["lms_pressure_count"] = int(snapshot["lms_pressure_count"] or 0) + 1

            finance_modifier = float(getattr(latest_prediction, "finance_modifier", 0.0) or 0.0) if latest_prediction is not None else 0.0
            finance_status = str(getattr(latest_finance_event, "payment_status", "") or "").strip().lower()
            overdue_amount = float(getattr(latest_finance_event, "fee_overdue_amount", 0.0) or 0.0) if latest_finance_event is not None else 0.0
            if finance_modifier > 0.0 or finance_status not in {"", "paid", "clear"} or overdue_amount > 0.0:
                snapshot["finance_pressure_count"] = int(snapshot["finance_pressure_count"] or 0) + 1

            academic_progress = repository.get_latest_student_semester_progress_record(student_id)
            overall_status = str(getattr(academic_progress, "overall_status", "") or "").strip().upper()
            if overall_status == "SAFE":
                snapshot["safe_attendance_high_risk_count"] = int(snapshot["safe_attendance_high_risk_count"] or 0) + 1
                branch_name = _profile_context_value(profiles_by_student.get(student_id), "branch") or "Unknown"
                snapshot["hidden_branch_counts"][branch_name] = int(snapshot["hidden_branch_counts"].get(branch_name, 0) or 0) + 1

        admin_signal_snapshot = snapshot
        return snapshot

    planner = query_plan or {}
    last_context = memory.get("last_context") or {}
    normalized_message = str(planner.get("normalized_message") or lowered).strip().lower()
    original_message_lowered = str(planner.get("original_message") or lowered).strip().lower()
    admin_query = _classify_admin_query(lowered=original_message_lowered, last_context=last_context)
    admin_query_topic = str(admin_query.get("topic") or "generic").strip().lower()
    if admin_query_topic == "institution_health" and planner.get("user_goal") != "institution_health_explanation":
        planner = {
            **planner,
            "user_goal": "institution_health_explanation",
            "normalized_message": original_message_lowered,
        }
        normalized_message = original_message_lowered
    if any(
        phrase in original_message_lowered
        for phrase in {
            "is risk increasing over time",
            "how is trend of student performance",
            "is dropout risk rising",
            "compare current vs previous term",
        }
    ):
        return _answer_admin_trend_snapshot_fast(
            repository=repository,
            lowered=original_message_lowered,
            risk_breakdown=_get_risk_breakdown(),
            latest_predictions=_get_latest_predictions(),
        )
    if any(
        phrase in original_message_lowered
        for phrase in {
            "what is biggest issue overall",
            "what is biggest weakness overall",
            "what is most critical area",
            "is situation critical",
            "are we in danger",
            "should we be worried",
            "is performance normal",
            "which factor affects most students",
            "which branch has improving vs declining performance",
        }
    ):
        planner = {
            **planner,
            "user_goal": "institution_health_explanation",
            "normalized_message": original_message_lowered,
        }
    follow_up_grouping = _extract_grouping_follow_up_request(lowered)
    if follow_up_grouping and str(last_context.get("pending_role_follow_up") or "").strip().lower() == "operational_actions":
        return _build_grouped_risk_breakdown_answer(
            scope_label="the institution",
            lowered=lowered,
            planner={
                "grouping": follow_up_grouping,
                "metrics": ["prediction_high_risk", "overall_shortage", "i_grade_risk", "r_grade_risk"],
            },
            risk_breakdown=_get_risk_breakdown(),
            prediction_high_risk_count=len(_get_high_risk_rows()),
            overall_shortage_count=_get_attendance_totals()["total_students_with_overall_shortage"],
            i_grade_count=_get_attendance_totals()["total_students_with_i_grade_risk"],
            r_grade_count=_get_attendance_totals()["total_students_with_r_grade_risk"],
            tool_prefix="admin",
        )
    if str(last_context.get("intent") or "") == "institution_health_explanation":
        stripped_lowered = lowered.strip().lower()
        if stripped_lowered in {"ok", "okay", "continue", "proceed", "then", "what next", "more"} or any(
            token in stripped_lowered
            for token in {
                "how to fix",
                "what should we do",
                "solution plan",
                "full solution plan",
                "strategic plan",
            }
        ):
            return _answer_admin_operational_actions_fast(
                planner={**planner, "normalized_message": "show institutional operational priorities"},
                last_context=last_context,
                risk_breakdown=_get_risk_breakdown(),
                latest_predictions=_get_latest_predictions(),
            )
        if any(
            token in stripped_lowered
            for token in {
                "why",
                "cause",
                "causes",
                "happening",
                "main factor",
                "main cause",
                "explain",
            }
        ):
            planner = {**planner, "user_goal": "institution_health_explanation"}
    if str(last_context.get("intent") or "").strip().lower() == "admin_operational_actions" and any(
        token in lowered.strip().lower()
        for token in {
            "why",
            "cause",
            "causes",
            "main factor",
            "main cause",
            "explain",
            "what is affecting them",
            "why is that happening",
        }
    ):
        return _answer_admin_operational_explanation_fast(
            last_context=last_context,
            risk_breakdown=_get_risk_breakdown(),
            latest_predictions=_get_latest_predictions(),
        )
    if (
        planner.get("user_goal") == "role_action_request"
        or _looks_like_role_operational_request(original_message_lowered)
        or _should_continue_role_operational_actions(
            lowered=lowered,
            memory=memory,
            last_context=last_context,
        )
    ):
        return _answer_admin_operational_actions_fast(
            planner=planner,
            last_context=last_context,
            risk_breakdown=_get_risk_breakdown(),
            latest_predictions=_get_latest_predictions(),
        )
    admin_default_topic_reset = lowered.strip().lower() in {
        "risk",
        "trend",
        "stats",
        "analysis",
        "report",
        "performance",
    } or original_message_lowered in {
        "risk",
        "trend",
        "stats",
        "analysis",
        "report",
        "performance",
    }
    if planner.get("user_goal") != "institution_health_explanation":
        if not admin_default_topic_reset and admin_query_topic not in {"institution_health", "fresh_grouped", "strategy"}:
            memory_follow_up = _maybe_answer_role_follow_up(
                role="admin",
                repository=repository,
                intent=intent,
                memory=memory,
                profiles=profiles,
            )
            if memory_follow_up is not None:
                return memory_follow_up
    if (
        not admin_default_topic_reset
        and admin_query_topic not in {"institution_health", "fresh_grouped", "strategy"}
        and planner.get("user_goal") != "institution_health_explanation"
        and (
            str(last_context.get("role_scope") or "").strip().lower() == "admin"
            or str(last_context.get("kind") or "").strip().lower() == "import_coverage"
        )
    ):
        lowered_stripped = lowered.strip().lower()
        if _looks_like_admin_contextual_follow_up(lowered=lowered_stripped, last_context=last_context):
            forced_memory = dict(memory)
            forced_memory["is_follow_up"] = True
            forced_follow_up = _maybe_answer_role_follow_up(
                role="admin",
                repository=repository,
                intent=intent,
                memory=forced_memory,
                profiles=profiles,
            )
            if forced_follow_up is not None:
                return forced_follow_up

    if _looks_like_risk_layer_difference_request(lowered):
        return _build_risk_layer_difference_answer(
            scope_label="the institution",
            prediction_high_risk_count=len(_get_high_risk_rows()),
            overall_shortage_count=_get_attendance_totals()["total_students_with_overall_shortage"],
            i_grade_count=_get_attendance_totals()["total_students_with_i_grade_risk"],
            r_grade_count=_get_attendance_totals()["total_students_with_r_grade_risk"],
            tool_prefix="admin",
        )

    if planner.get("user_goal") == "institution_student_count" or normalized_message == "show institution student count":
        total_students = len(profiles)
        scored_students = sum(
            1
            for profile in profiles
            if repository.get_latest_prediction_for_student(int(profile.student_id)) is not None
        )
        return (
            build_grounded_response(
                opening=f"There are {total_students} active imported students currently visible at the institution level.",
                key_points=[
                    f"Students with prediction scores available: {scored_students}.",
                    f"Students still unscored: {max(total_students - scored_students, 0)}.",
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin institution student-count request"},
                    {"tool_name": "import_coverage_summary", "summary": "Computed institution student counts from imported profiles and available scores"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin institution student-count request"},
                {"tool_name": "import_coverage_summary", "summary": "Computed institution student counts from imported profiles and available scores"},
            ],
            [],
            {"kind": "import_coverage", "intent": "institution_student_count"},
        )

    if planner.get("user_goal") == "grouped_student_count" or normalized_message == "show branch wise student count":
        branch_counts: dict[str, int] = {}
        for profile in profiles:
            branch = _profile_context_value(profile, "branch") or "Unknown"
            branch_counts[branch] = branch_counts.get(branch, 0) + 1
        ordered_counts = sorted(branch_counts.items(), key=lambda item: (-item[1], item[0]))
        return (
            build_grounded_response(
                opening="Here is the branch-wise student count across the institution.",
                key_points=[f"{branch}: {count} students." for branch, count in ordered_counts],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin grouped student-count request"},
                    {"tool_name": "institution_branch_count", "summary": "Counted imported students by branch"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin grouped student-count request"},
                {"tool_name": "institution_branch_count", "summary": "Counted imported students by branch"},
            ],
            [],
            {"kind": "admin_academic", "intent": "admin_branch_student_count"},
        )

    if planner.get("user_goal") == "risk_distribution" or normalized_message == "show institution risk distribution":
        low_count = 0
        medium_count = 0
        high_count = 0
        for row in _get_latest_predictions():
            probability = float(getattr(row, "final_risk_probability", 0.0) or 0.0)
            if probability >= 0.67:
                high_count += 1
            elif probability >= 0.34:
                medium_count += 1
            else:
                low_count += 1
        return (
            build_grounded_response(
                opening="Here is the current prediction risk distribution across the institution.",
                key_points=[
                    f"Low prediction-risk students: {low_count}.",
                    f"Medium prediction-risk students: {medium_count}.",
                    f"High prediction-risk students: {high_count}.",
                    f"Attendance-policy context alongside that: {_get_attendance_totals()['total_students_with_i_grade_risk']} students with I-grade risk and {_get_attendance_totals()['total_students_with_r_grade_risk']} with R-grade risk.",
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin institution risk-distribution request"},
                    {"tool_name": "prediction_distribution_summary", "summary": "Bucketed current prediction probabilities into low, medium, and high institution counts"},
                ],
                limitations=["Low/medium/high are based on current prediction-probability bands rather than formal academic policy categories."],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin institution risk-distribution request"},
                {"tool_name": "prediction_distribution_summary", "summary": "Bucketed current prediction probabilities into low, medium, and high institution counts"},
            ],
            ["Low/medium/high are based on current prediction-probability bands rather than formal academic policy categories."],
            {"kind": "admin_academic", "intent": "admin_risk_distribution"},
        )

    if planner.get("user_goal") == "institution_report" or normalized_message == "show institution report":
        academic_summary = _get_academic_summary()
        return (
            build_grounded_response(
                opening="Here is the current institution report snapshot.",
                key_points=[
                    f"Imported active students currently visible: {len(profiles)}.",
                    f"Prediction high-risk students: {len(_get_high_risk_rows())}.",
                    f"Overall attendance-shortage cases: {_get_attendance_totals()['total_students_with_overall_shortage']}.",
                    f"I-grade attendance risk: {_get_attendance_totals()['total_students_with_i_grade_risk']}.",
                    f"R-grade attendance risk: {_get_attendance_totals()['total_students_with_r_grade_risk']}.",
                    *(
                        [f"Most pressured branch right now: {academic_summary['branch_pressure'][0]['bucket_label']}."]
                        if academic_summary.get("branch_pressure")
                        else []
                    ),
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin institution report request"},
                    {"tool_name": "institution_snapshot_summary", "summary": "Combined current institution counts and pressure indicators into one report snapshot"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin institution report request"},
                {"tool_name": "institution_snapshot_summary", "summary": "Combined current institution counts and pressure indicators into one report snapshot"},
            ],
            [],
            {"kind": "admin_governance", "intent": "institution_report"},
        )

    if planner.get("user_goal") == "institution_health_explanation":
        academic_summary = _get_academic_summary()
        top_branch = academic_summary["branch_pressure"][0] if academic_summary.get("branch_pressure") else None
        top_subject = academic_summary["top_subjects"][0] if academic_summary.get("top_subjects") else None
        signal_snapshot = _get_admin_signal_snapshot()
        driver_counts = dict(signal_snapshot.get("driver_counts") or {})
        dominant_driver = None
        if driver_counts:
            dominant_driver = max(driver_counts.items(), key=lambda item: (int(item[1]), str(item[0])))[0]
        opening = "Here is the grounded institution-health explanation right now."
        key_points = [
            f"Current prediction high-risk students: {len(_get_high_risk_rows())}.",
            f"Attendance-policy pressure is still substantial: {_get_attendance_totals()['total_students_with_i_grade_risk']} students with I-grade risk and {_get_attendance_totals()['total_students_with_r_grade_risk']} with R-grade risk.",
            "Main pattern: current prediction risk and attendance-policy pressure are concentrated in overlapping parts of the institution rather than being isolated one-off cases.",
        ]
        if "problematic" in lowered:
            opening = "Here is the grounded view of the most problematic institutional area right now."
        elif any(token in lowered for token in {"doing okay", "going well", "under control"}):
            opening = "Here is the grounded institution-health check right now."
        elif "are we in danger" in lowered:
            opening = "Here is the grounded danger-level check for the institution right now."
            key_points.append("This is serious enough to require active management, but it is still a pressure-management problem rather than a reason to panic blindly.")
        elif "should we be worried" in lowered:
            opening = "Here is the grounded worry-check for the institution right now."
            key_points.append("Yes, this deserves attention, but the useful response is focused intervention on the most pressured buckets rather than generic alarm.")
        elif "is performance normal" in lowered:
            opening = "Here is the grounded normal-versus-pressure check for current institutional performance."
            key_points.append("This is not a comfortably normal picture, because the same pressure is clustering in visible high-risk and attendance-burden pockets.")
        elif "is situation critical" in lowered:
            opening = "Here is the grounded criticality check for the institution right now."
            key_points.append("The current posture should be treated as critical enough for active intervention planning, especially in the most pressured branch and hotspot areas.")
        elif "compare lms vs erp impact" in lowered:
            opening = "Here is the grounded comparison between LMS and ERP impact in the current institution risk picture."
            key_points = [
                f"Among the current high-risk students I could evaluate in detail, ERP and coursework pressure is visible in {int(signal_snapshot.get('erp_pressure_count') or 0)} cases, while LMS-engagement pressure is visible in {int(signal_snapshot.get('lms_pressure_count') or 0)} cases.",
                "That means ERP-side academic performance is currently the stronger institution-level drag than LMS alone.",
                "In practice, weak weighted scores and submission consistency are showing up more often than pure LMS inactivity in the current high-risk cohort.",
            ]
        elif "how finance is affecting risk" in lowered:
            opening = "Here is the grounded finance-to-risk explanation at the institution level."
            key_points = [
                f"Finance pressure is still visible inside the current high-risk cohort: {int(signal_snapshot.get('finance_pressure_count') or 0)} of the evaluated high-risk students show a finance drag through modifier pressure, overdue amount, or unresolved payment status.",
                "So finance is not the whole story institution-wide, but it is clearly amplifying risk for a meaningful subset of already vulnerable students.",
                "The grounded operational meaning is that finance support should be treated as a risk-reduction lever, not only as an administrative side issue.",
            ]
        elif (
            "which factor impacts performance most" in lowered
            or "which factor is affecting students most" in lowered
            or "which factor affects most students" in lowered
            or "what is biggest issue overall" in lowered
            or "what is biggest weakness overall" in lowered
        ):
            opening = "Here is the grounded view of the strongest institution-level factor affecting student performance right now."
            if dominant_driver is not None:
                key_points = [
                    f"The most common dominant driver inside the current high-risk cohort is {_format_risk_type_label(dominant_driver)}.",
                    f"ERP-side academic-performance pressure is visible in {int(signal_snapshot.get('erp_pressure_count') or 0)} of the evaluated high-risk cases, which is why coursework quality and submission consistency are still the main institutional weakness.",
                    f"Finance pressure is contributing in {int(signal_snapshot.get('finance_pressure_count') or 0)} cases, while LMS pressure is visible in {int(signal_snapshot.get('lms_pressure_count') or 0)} cases.",
                ]
            else:
                key_points = [
                    "The strongest visible factor is still academic-performance pressure rather than one isolated operational issue.",
                    f"ERP-side academic-performance pressure is visible in {int(signal_snapshot.get('erp_pressure_count') or 0)} of the evaluated high-risk cases.",
                ]
        elif "hidden risk across departments" in lowered or "which branch has good attendance but high risk" in lowered:
            hidden_branch_counts = dict(signal_snapshot.get("hidden_branch_counts") or {})
            top_hidden_branch = None
            if hidden_branch_counts:
                top_hidden_branch = max(hidden_branch_counts.items(), key=lambda item: (int(item[1]), str(item[0])))[0]
            opening = "Here is the grounded hidden-risk explanation across the currently visible institution scope."
            key_points = [
                f"There are {int(signal_snapshot.get('safe_attendance_high_risk_count') or 0)} currently high-risk students whose latest semester attendance posture still looks SAFE, so this is not only an attendance problem.",
                "That is the hidden-risk pattern: students can look stable on visible attendance while ERP, LMS, or finance signals still keep prediction risk elevated.",
            ]
            if top_hidden_branch is not None:
                key_points.append(
                    f"The most visible branch carrying that pattern right now is {top_hidden_branch}."
                )
        if top_branch is not None:
            key_points.append(
                f"Most pressured branch right now: {top_branch['bucket_label']} with {top_branch['students_with_overall_shortage']} overall-shortage cases."
            )
        if top_subject is not None:
            key_points.append(
                f"Most visible attendance hotspot right now: {top_subject['subject_name']} affecting {top_subject['students_below_threshold']} students."
            )
        return (
            build_grounded_response(
                opening=opening,
                key_points=key_points,
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin institution-health explanation request"},
                    {"tool_name": "institution_health_summary", "summary": "Explained the current institution posture using risk, attendance pressure, and hotspot signals"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin institution-health explanation request"},
                {"tool_name": "institution_health_summary", "summary": "Explained the current institution posture using risk, attendance pressure, and hotspot signals"},
            ],
            [],
            {"kind": "admin_governance", "intent": "institution_health_explanation"},
        )

    if planner.get("user_goal") == "filtered_branch_explanation":
        branch_name = str((planner.get("filters") or {}).get("branches", ["Unknown"])[0] or "Unknown")
        branch_profiles = [
            profile
            for profile in profiles
            if (_profile_context_value(profile, "branch") or "").strip().lower() == branch_name.lower()
        ]
        branch_ids = {int(profile.student_id) for profile in branch_profiles}
        latest_predictions_by_student = {int(row.student_id): row for row in _get_latest_predictions()}
        branch_high_risk = [
            student_id
            for student_id in branch_ids
            if latest_predictions_by_student.get(student_id) is not None
            and int(getattr(latest_predictions_by_student[student_id], "final_predicted_class", 0) or 0) == 1
        ]
        progress_rows = repository.get_latest_student_semester_progress_records_for_students(branch_ids)
        i_grade_count = sum(1 for row in progress_rows if bool(getattr(row, "has_i_grade_risk", False)))
        r_grade_count = sum(1 for row in progress_rows if bool(getattr(row, "has_r_grade_risk", False)))
        shortage_count = sum(1 for row in progress_rows if str(getattr(row, "overall_status", "") or "").strip().upper() not in {"", "SAFE"})
        return (
            build_grounded_response(
                opening=f"Here is the grounded explanation for why {branch_name} is under pressure right now.",
                key_points=[
                    f"Matching students in {branch_name}: {len(branch_profiles)}.",
                    f"Current prediction high-risk students in {branch_name}: {len(branch_high_risk)}.",
                    f"Attendance-policy strain in {branch_name}: {shortage_count} overall-shortage cases, {i_grade_count} I-grade cases, and {r_grade_count} R-grade cases.",
                    "Main pattern: prediction pressure and attendance-policy strain are overlapping inside the same branch, which is why the branch still looks high risk overall.",
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin filtered-branch explanation request"},
                    {"tool_name": "branch_risk_reasoning", "summary": "Explained one branch using branch-scoped risk and attendance-pressure counts"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin filtered-branch explanation request"},
                {"tool_name": "branch_risk_reasoning", "summary": "Explained one branch using branch-scoped risk and attendance-pressure counts"},
            ],
            [],
            {"kind": "admin_governance", "intent": "filtered_branch_explanation", "branch": branch_name},
        )

    if planner.get("user_goal") == "priority_queue":
        queue_response = get_faculty_priority_queue(db=repository.db, auth=auth)
        top_items = queue_response.queue[:5]
        return (
            build_grounded_response(
                opening=f"There are {queue_response.total_students} students in the current priority queue.",
                key_points=[
                    *[
                        (
                            f"student_id {item.student_id}: {item.priority_label} priority, "
                            f"probability {item.final_risk_probability:.4f}, reason: {item.queue_reason}"
                        )
                        for item in top_items
                    ],
                ],
                tools_used=[
                    {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Interpreted a natural-language attention request into a priority-queue plan"},
                    {"tool_name": "faculty_priority_queue", "summary": "Returned faculty priority queue"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Interpreted a natural-language attention request into a priority-queue plan"},
                {"tool_name": "faculty_priority_queue", "summary": "Returned faculty priority queue"},
            ],
            [],
            {
                "kind": "admin_governance",
                "intent": "admin_priority_queue_summary",
                "student_ids": [int(item.student_id) for item in top_items],
                "planner_version": str(planner.get("version") or COPILOT_SYSTEM_PROMPT_VERSION),
            },
        )

    if (
        any(token in lowered for token in {"newly entered risk", "just entered risk", "entered risk lately", "lately"})
        and "risk" in lowered
        and _parse_time_window_days(lowered) is None
    ):
        return (
            build_grounded_response(
                opening="I can answer that, but I need one comparison window first.",
                key_points=[
                    "Which time window should I use for this comparison?",
                    "For example: last 7 days, last 14 days, or last 30 days.",
                ],
                tools_used=[{"tool_name": "admin_intent_router", "summary": "Asked for a time window before resolving a newly-entered-risk admin query"}],
                limitations=["newly-entered risk questions need a comparison window before grounded counting can continue"],
            ),
            [{"tool_name": "admin_intent_router", "summary": "Asked for a time window before resolving a newly-entered-risk admin query"}],
            ["newly-entered risk questions need a comparison window before grounded counting can continue"],
            {"kind": "planner", "intent": "planner_clarification"},
        )

    if intent == "help":
        return (
            build_grounded_response(
                opening="I can currently help with both institutional governance questions and academic attendance pressure questions.",
                key_points=[
                    "import coverage and scoring readiness",
                    "institution-wide high-risk, escalation, and follow-up posture",
                    "overall shortage, I-grade risk, and R-grade risk counts",
                    "subject hotspots and branch-level attendance pressure",
                ],
                tools_used=[{"tool_name": "admin_copilot_help", "summary": "Returned current admin copilot capabilities"}],
                limitations=[],
                closing="Try asking: 'which branch needs attention first?', 'how many students have R-grade risk?', or 'which subjects are causing most attendance issues?'.",
            ),
            [{"tool_name": "admin_copilot_help", "summary": "Returned current admin copilot capabilities"}],
            [],
            {"kind": "help", "intent": "help"},
        )

    if planner.get("comparison", {}).get("enabled"):
        compare_dimension = str(planner.get("comparison", {}).get("dimension") or "").strip()
        compare_values = list(planner.get("comparison", {}).get("values") or [])
        if not compare_values and compare_dimension in {"branch", "gender", "age_band", "batch", "program_type", "category", "region", "income"}:
            compare_values = _ordered_unique_context_values(profiles=profiles, key=compare_dimension)
        if not compare_values and compare_dimension == "outcome_status":
            compare_values = ["Dropped", "Graduated", "Studying"]
        if compare_dimension and compare_values:
            metric_kinds = list(planner.get("metrics") or ["risk"])
            if not metric_kinds:
                metric_kinds = ["risk"]
            trend_metric_kinds = {"recent_entry_risk_trend", "warning_trend", "intervention_trend"}
            derived_metric_kinds = {
                "dropped_risk_overlap",
                "warning_intervention_gap",
                "dropped_warning_overlap",
                "high_risk_warning_overlap",
                "high_risk_intervention_gap",
                "unresolved_risk_burden",
            }
            latest_predictions_by_student = {int(row.student_id): row for row in _get_latest_predictions()}
            history_rows = repository.get_all_prediction_history()
            intervention_student_ids = {
                int(getattr(row, "student_id"))
                for row in _get_interventions()
                if getattr(row, "student_id", None) is not None
            }
            active_warning_student_ids = {
                int(profile.student_id)
                for profile in profiles
                if repository.get_active_student_warning_for_student(int(profile.student_id)) is not None
            }
            recent_warning_events = _filter_rows_by_window(
                rows=_get_warning_events(),
                time_attr="sent_at",
                window_days=int(planner.get("time_window_days") or 30),
            )
            recent_intervention_events = _filter_rows_by_window(
                rows=_get_interventions(),
                time_attr="created_at",
                window_days=int(planner.get("time_window_days") or 30),
            )
            current_warning_window, previous_warning_window = _split_rows_by_consecutive_windows(
                rows=_get_warning_events(),
                time_attr="sent_at",
                window_days=int(planner.get("time_window_days") or 30),
            )
            current_intervention_window, previous_intervention_window = _split_rows_by_consecutive_windows(
                rows=_get_interventions(),
                time_attr="created_at",
                window_days=int(planner.get("time_window_days") or 30),
            )
            has_multi_metric = len(metric_kinds) > 1
            comparison_rows: dict[str, list[dict[str, object]]] = {metric: [] for metric in metric_kinds}
            key_points: list[str] = []
            for value in compare_values:
                grouped_subset = _filter_profiles_for_admin_query(
                    profiles=profiles,
                    outcome_status=value if compare_dimension == "outcome_status" else planner.get("filters", {}).get("outcome_status"),
                    branch=value if compare_dimension == "branch" else _single_filter_value(planner, "branches"),
                    gender=value if compare_dimension == "gender" else _single_filter_value(planner, "genders"),
                    age_band=value if compare_dimension == "age_band" else _single_filter_value(planner, "age_bands"),
                    batch=value if compare_dimension == "batch" else _single_filter_value(planner, "batches"),
                    program_type=value if compare_dimension == "program_type" else _single_filter_value(planner, "program_types"),
                    category=value if compare_dimension == "category" else _single_filter_value(planner, "categories"),
                    region=value if compare_dimension == "region" else _single_filter_value(planner, "regions"),
                    income=value if compare_dimension == "income" else _single_filter_value(planner, "incomes"),
                )
                subset_count = len(grouped_subset)
                grouped_ids = {int(profile.student_id) for profile in grouped_subset}
                warning_count = sum(1 for student_id in grouped_ids if student_id in active_warning_student_ids)
                warning_rate = (warning_count / subset_count * 100.0) if subset_count else 0.0
                covered_count = sum(1 for student_id in grouped_ids if student_id in intervention_student_ids)
                coverage_percent = (covered_count / subset_count * 100.0) if subset_count else 0.0
                risk_student_ids = {
                    student_id
                    for student_id in grouped_ids
                    if (
                        latest_predictions_by_student.get(student_id) is not None
                        and int(latest_predictions_by_student[student_id].final_predicted_class) == 1
                    )
                }
                risk_count = len(risk_student_ids)
                risk_rate = (risk_count / subset_count * 100.0) if subset_count else 0.0
                dropped_ids = {
                    int(profile.student_id)
                    for profile in grouped_subset
                    if _profile_outcome_status(profile) == "Dropped"
                }
                dropped_warning_count = sum(1 for student_id in dropped_ids if student_id in active_warning_student_ids)
                dropped_warning_rate = (dropped_warning_count / subset_count * 100.0) if subset_count else 0.0
                high_risk_warning_count = sum(1 for student_id in risk_student_ids if student_id in active_warning_student_ids)
                high_risk_warning_rate = (high_risk_warning_count / subset_count * 100.0) if subset_count else 0.0
                covered_high_risk_count = sum(1 for student_id in risk_student_ids if student_id in intervention_student_ids)
                uncovered_high_risk_count = max(risk_count - covered_high_risk_count, 0)
                high_risk_intervention_gap_rate = (uncovered_high_risk_count / subset_count * 100.0) if subset_count else 0.0
                unresolved_risk_burden_rate = (
                    risk_rate
                    + max(warning_rate - coverage_percent, 0.0)
                    + high_risk_intervention_gap_rate
                )
                if has_multi_metric or "count" in metric_kinds:
                    key_points.append(f"{value} matching students: {subset_count}")
                    comparison_rows.setdefault("count", []).append(
                        {"value": value, "count": subset_count, "rate": float(subset_count), "label": "matching students"}
                    )
                if "recent_warning_events" in metric_kinds:
                    warning_event_count = sum(
                        1 for row in recent_warning_events if int(getattr(row, "student_id")) in grouped_ids
                    )
                    warning_event_rate = (warning_event_count / subset_count * 100.0) if subset_count else 0.0
                    key_points.append(
                        f"{value} warning events in the last {int(planner.get('time_window_days') or 30)} days: "
                        f"{warning_event_count} ({warning_event_rate:.1f}% of subset)"
                    )
                    comparison_rows["recent_warning_events"].append(
                        {
                            "value": value,
                            "count": warning_event_count,
                            "rate": warning_event_rate,
                            "label": f"warning events in the last {int(planner.get('time_window_days') or 30)} days",
                        }
                    )
                if "warning_trend" in metric_kinds:
                    window_days = int(planner.get("time_window_days") or 30)
                    if window_days >= 60:
                        windows = _trailing_window_specs(total_days=window_days)
                        counts = _count_rows_in_windows(
                            rows=_get_warning_events(),
                            time_attr="sent_at",
                            windows=windows,
                            allowed_student_ids=grouped_ids,
                        )
                        warning_delta, series_summary = _window_series_summary(
                            counts=counts,
                            subset_count=subset_count,
                            total_days=window_days,
                        )
                        key_points.append(f"{value} long-horizon warning series over the last {window_days} days: {series_summary}")
                        key_points.append(
                            f"{value} long-horizon warning trend: {_trend_direction(warning_delta)} {abs(warning_delta):.1f} percentage points from the earliest to latest window"
                        )
                        current_warning_count = counts[-1] if counts else 0
                    else:
                        current_warning_count = sum(
                            1 for row in current_warning_window if int(getattr(row, "student_id")) in grouped_ids
                        )
                        previous_warning_count = sum(
                            1 for row in previous_warning_window if int(getattr(row, "student_id")) in grouped_ids
                        )
                        current_warning_rate = (current_warning_count / subset_count * 100.0) if subset_count else 0.0
                        previous_warning_rate = (previous_warning_count / subset_count * 100.0) if subset_count else 0.0
                        warning_delta = current_warning_rate - previous_warning_rate
                        key_points.append(
                            f"{value} warning events in the last {window_days} days: "
                            f"{current_warning_count} ({current_warning_rate:.1f}% of subset)"
                        )
                        key_points.append(
                            f"{value} warning events in the previous {window_days} days: "
                            f"{previous_warning_count} ({previous_warning_rate:.1f}% of subset)"
                        )
                        key_points.append(
                            f"{value} warning trend: {_trend_direction(warning_delta)} {abs(warning_delta):.1f} percentage points versus the previous window"
                        )
                    comparison_rows["warning_trend"].append(
                        {
                            "value": value,
                            "count": current_warning_count,
                            "rate": warning_delta,
                            "label": "warning trend versus the previous window",
                        }
                    )
                if "recent_intervention_events" in metric_kinds:
                    intervention_event_count = sum(
                        1 for row in recent_intervention_events if int(getattr(row, "student_id")) in grouped_ids
                    )
                    intervention_event_rate = (intervention_event_count / subset_count * 100.0) if subset_count else 0.0
                    key_points.append(
                        f"{value} intervention actions in the last {int(planner.get('time_window_days') or 30)} days: "
                        f"{intervention_event_count} ({intervention_event_rate:.1f}% of subset)"
                    )
                    comparison_rows["recent_intervention_events"].append(
                        {
                            "value": value,
                            "count": intervention_event_count,
                            "rate": intervention_event_rate,
                            "label": f"intervention actions in the last {int(planner.get('time_window_days') or 30)} days",
                        }
                    )
                if "intervention_trend" in metric_kinds:
                    window_days = int(planner.get("time_window_days") or 30)
                    if window_days >= 60:
                        windows = _trailing_window_specs(total_days=window_days)
                        intervention_counts = _count_rows_in_windows(
                            rows=_get_interventions(),
                            time_attr="created_at",
                            windows=windows,
                            allowed_student_ids=grouped_ids,
                        )
                        intervention_delta, series_summary = _window_series_summary(
                            counts=intervention_counts,
                            subset_count=subset_count,
                            total_days=window_days,
                        )
                        latest_count = intervention_counts[-1] if intervention_counts else 0
                        key_points.append(
                            f"{value} long-horizon intervention series over the last {window_days} days: {series_summary}"
                        )
                        key_points.append(
                            f"{value} long-horizon intervention trend: {_trend_direction(intervention_delta)} {abs(intervention_delta):.1f} percentage points from the earliest to latest window"
                        )
                    else:
                        current_intervention_student_ids = {
                            int(getattr(row, "student_id"))
                            for row in current_intervention_window
                            if int(getattr(row, "student_id")) in grouped_ids
                        }
                        previous_intervention_student_ids = {
                            int(getattr(row, "student_id"))
                            for row in previous_intervention_window
                            if int(getattr(row, "student_id")) in grouped_ids
                        }
                        current_intervention_coverage = (
                            len(current_intervention_student_ids) / subset_count * 100.0 if subset_count else 0.0
                        )
                        previous_intervention_coverage = (
                            len(previous_intervention_student_ids) / subset_count * 100.0 if subset_count else 0.0
                        )
                        intervention_delta = current_intervention_coverage - previous_intervention_coverage
                        latest_count = len(current_intervention_student_ids)
                        key_points.append(
                            f"{value} intervention coverage in the last {window_days} days: "
                            f"{current_intervention_coverage:.1f}% ({len(current_intervention_student_ids)} of {subset_count} students)"
                        )
                        key_points.append(
                            f"{value} intervention coverage in the previous {window_days} days: "
                            f"{previous_intervention_coverage:.1f}% ({len(previous_intervention_student_ids)} of {subset_count} students)"
                        )
                        key_points.append(
                            f"{value} intervention trend: {_trend_direction(intervention_delta)} {abs(intervention_delta):.1f} percentage points versus the previous window"
                        )
                    comparison_rows["intervention_trend"].append(
                        {
                            "value": value,
                            "count": latest_count,
                            "rate": intervention_delta,
                            "label": "intervention coverage trend versus the previous window",
                        }
                    )
                if "recent_entry_risk" in metric_kinds:
                    recent_entry_count, recent_entry_ids = _compute_recent_high_risk_entries(
                        history_rows=[row for row in history_rows if int(getattr(row, "student_id")) in grouped_ids],
                        window_days=int(planner.get("time_window_days") or 30),
                    )
                    entry_rate = (recent_entry_count / subset_count * 100.0) if subset_count else 0.0
                    key_points.append(
                        f"{value} newly high-risk students in the last {int(planner.get('time_window_days') or 30)} days: "
                        f"{recent_entry_count} ({entry_rate:.1f}% of subset)"
                    )
                    if recent_entry_ids:
                        key_points.append(
                            f"{value} recent-entry sample: {', '.join(str(item) for item in recent_entry_ids[:5])}"
                        )
                    comparison_rows["recent_entry_risk"].append(
                        {
                            "value": value,
                            "count": recent_entry_count,
                            "rate": entry_rate,
                            "label": f"newly high-risk students in the last {int(planner.get('time_window_days') or 30)} days",
                        }
                    )
                if "recent_entry_risk_trend" in metric_kinds:
                    grouped_history = [row for row in history_rows if int(getattr(row, "student_id")) in grouped_ids]
                    window_days = int(planner.get("time_window_days") or 30)
                    if window_days >= 60:
                        windows = _trailing_window_specs(total_days=window_days)
                        entry_counts = _high_risk_entries_in_windows(
                            history_rows=grouped_history,
                            windows=windows,
                        )
                        recent_entry_delta, series_summary = _window_series_summary(
                            counts=entry_counts,
                            subset_count=subset_count,
                            total_days=window_days,
                        )
                        now = datetime.now(timezone.utc)
                        latest_segment_days = max(window_days // len(windows), 1)
                        current_entry_count, current_entry_ids = _compute_recent_high_risk_entries_between(
                            history_rows=grouped_history,
                            window_start=now - timedelta(days=latest_segment_days),
                            window_end=now,
                        )
                        key_points.append(
                            f"{value} long-horizon risk-entry series over the last {window_days} days: {series_summary}"
                        )
                        if current_entry_ids:
                            key_points.append(
                                f"{value} recent-entry sample: {', '.join(str(item) for item in current_entry_ids[:5])}"
                            )
                        key_points.append(
                            f"{value} long-horizon risk-entry trend: {_trend_direction(recent_entry_delta)} {abs(recent_entry_delta):.1f} percentage points from the earliest to latest window"
                        )
                    else:
                        now = datetime.now(timezone.utc)
                        current_start = now - timedelta(days=window_days)
                        previous_start = current_start - timedelta(days=window_days)
                        current_entry_count, current_entry_ids = _compute_recent_high_risk_entries_between(
                            history_rows=grouped_history,
                            window_start=current_start,
                            window_end=now,
                        )
                        previous_entry_count, _ = _compute_recent_high_risk_entries_between(
                            history_rows=grouped_history,
                            window_start=previous_start,
                            window_end=current_start,
                        )
                        current_entry_rate = (current_entry_count / subset_count * 100.0) if subset_count else 0.0
                        previous_entry_rate = (previous_entry_count / subset_count * 100.0) if subset_count else 0.0
                        recent_entry_delta = current_entry_rate - previous_entry_rate
                        key_points.append(
                            f"{value} newly high-risk students in the last {window_days} days: "
                            f"{current_entry_count} ({current_entry_rate:.1f}% of subset)"
                        )
                        key_points.append(
                            f"{value} newly high-risk students in the previous {window_days} days: "
                            f"{previous_entry_count} ({previous_entry_rate:.1f}% of subset)"
                        )
                        if current_entry_ids:
                            key_points.append(
                                f"{value} recent-entry sample: {', '.join(str(item) for item in current_entry_ids[:5])}"
                            )
                        key_points.append(
                            f"{value} risk-entry trend: {_trend_direction(recent_entry_delta)} {abs(recent_entry_delta):.1f} percentage points versus the previous window"
                        )
                    comparison_rows["recent_entry_risk_trend"].append(
                        {
                            "value": value,
                            "count": current_entry_count,
                            "rate": recent_entry_delta,
                            "label": "recent high-risk-entry trend versus the previous window",
                        }
                    )
                if "risk" in metric_kinds:
                    if has_multi_metric:
                        key_points.append(f"{value} prediction high risk students: {risk_count} ({risk_rate:.1f}% of subset)")
                    else:
                        key_points.append(f"{value} prediction high risk students: {risk_count}")
                    comparison_rows["risk"].append(
                        {"value": value, "count": risk_count, "rate": risk_rate if has_multi_metric else float(risk_count), "label": "prediction high risk students"}
                    )
                if "dropped_risk_overlap" in metric_kinds:
                    overlap_count = sum(
                        1
                        for profile in grouped_subset
                        if _profile_outcome_status(profile) == "Dropped"
                        and (
                            latest_predictions_by_student.get(int(profile.student_id)) is not None
                            and int(latest_predictions_by_student[int(profile.student_id)].final_predicted_class) == 1
                        )
                    )
                    overlap_rate = (overlap_count / subset_count * 100.0) if subset_count else 0.0
                    key_points.append(
                        f"{value} dropped-to-risk overlap: {overlap_count} students ({overlap_rate:.1f}% of subset)"
                    )
                    comparison_rows["dropped_risk_overlap"].append(
                        {
                            "value": value,
                            "count": overlap_count,
                            "rate": overlap_rate,
                            "label": "dropped-to-risk overlap",
                        }
                    )
                if "dropped_warning_overlap" in metric_kinds:
                    key_points.append(
                        f"{value} dropped-to-warning overlap: {dropped_warning_count} students ({dropped_warning_rate:.1f}% of subset)"
                    )
                    comparison_rows["dropped_warning_overlap"].append(
                        {
                            "value": value,
                            "count": dropped_warning_count,
                            "rate": dropped_warning_rate,
                            "label": "dropped-to-warning overlap",
                        }
                    )
                if "high_risk_warning_overlap" in metric_kinds:
                    key_points.append(
                        f"{value} high-risk-to-warning overlap: {high_risk_warning_count} students ({high_risk_warning_rate:.1f}% of subset)"
                    )
                    comparison_rows["high_risk_warning_overlap"].append(
                        {
                            "value": value,
                            "count": high_risk_warning_count,
                            "rate": high_risk_warning_rate,
                            "label": "high-risk-to-warning overlap",
                        }
                    )
                if "warnings" in metric_kinds:
                    if has_multi_metric or "rate" in lowered:
                        key_points.append(f"{value} students with an active warning: {warning_count} ({warning_rate:.1f}% of subset)")
                    else:
                        key_points.append(f"{value} students with an active warning: {warning_count}")
                    comparison_rows["warnings"].append(
                        {"value": value, "count": warning_count, "rate": warning_rate if (has_multi_metric or "rate" in lowered) else float(warning_count), "label": "students with an active warning"}
                    )
                if "intervention_coverage" in metric_kinds:
                    key_points.append(
                        f"{value} intervention coverage: {coverage_percent:.1f}% ({covered_count} of {subset_count} students)"
                    )
                    comparison_rows["intervention_coverage"].append(
                        {"value": value, "count": covered_count, "rate": coverage_percent, "label": "intervention coverage"}
                    )
                if "warning_intervention_gap" in metric_kinds:
                    gap_rate = warning_rate - coverage_percent
                    key_points.append(
                        f"{value} warning-to-intervention gap: {gap_rate:+.1f} percentage points "
                        f"(warnings {warning_rate:.1f}% vs intervention coverage {coverage_percent:.1f}%)"
                    )
                    comparison_rows["warning_intervention_gap"].append(
                        {
                            "value": value,
                            "count": warning_count - covered_count,
                            "rate": gap_rate,
                            "label": "warning-to-intervention gap",
                        }
                    )
                if "high_risk_intervention_gap" in metric_kinds:
                    key_points.append(
                        f"{value} high-risk-to-intervention gap: {uncovered_high_risk_count} students ({high_risk_intervention_gap_rate:.1f}% of subset) still high-risk without intervention"
                    )
                    comparison_rows["high_risk_intervention_gap"].append(
                        {
                            "value": value,
                            "count": uncovered_high_risk_count,
                            "rate": high_risk_intervention_gap_rate,
                            "label": "high-risk-to-intervention gap",
                        }
                    )
                if "unresolved_risk_burden" in metric_kinds:
                    key_points.append(
                        f"{value} unresolved risk burden: {unresolved_risk_burden_rate:.1f} composite pressure points "
                        f"(risk {risk_rate:.1f}% + support gap {max(warning_rate - coverage_percent, 0.0):+.1f} + uncovered high-risk {high_risk_intervention_gap_rate:.1f}%)"
                    )
                    comparison_rows["unresolved_risk_burden"].append(
                        {
                            "value": value,
                            "count": uncovered_high_risk_count,
                            "rate": unresolved_risk_burden_rate,
                            "label": "unresolved risk burden",
                        }
                    )
                if "counsellor_coverage" in metric_kinds:
                    assigned_profiles = [
                        profile for profile in grouped_subset if str(getattr(profile, "counsellor_name", "") or "").strip()
                    ]
                    assigned_count = len(assigned_profiles)
                    counsellor_coverage = (assigned_count / subset_count * 100.0) if subset_count else 0.0
                    counsellor_names = sorted(
                        {
                            str(getattr(profile, "counsellor_name", "")).strip()
                            for profile in assigned_profiles
                            if str(getattr(profile, "counsellor_name", "") or "").strip()
                        }
                    )
                    counsellor_label = ", ".join(counsellor_names[:3]) if counsellor_names else "no assigned counsellor"
                    key_points.append(
                        f"{value} counsellor coverage: {counsellor_coverage:.1f}% ({assigned_count} of {subset_count} students assigned)"
                    )
                    key_points.append(f"{value} counsellor sample: {counsellor_label}")
                    comparison_rows["counsellor_coverage"].append(
                        {"value": value, "count": assigned_count, "rate": counsellor_coverage, "label": "counsellor coverage"}
                    )

            metric_summary_labels = {
                "count": "matching students",
                "recent_warning_events": f"warning events in the last {int(planner.get('time_window_days') or 30)} days",
                "recent_intervention_events": f"intervention actions in the last {int(planner.get('time_window_days') or 30)} days",
                "recent_entry_risk": f"newly high-risk students in the last {int(planner.get('time_window_days') or 30)} days",
                "warning_trend": "warning trend versus the previous window",
                "intervention_trend": "intervention coverage trend versus the previous window",
                "recent_entry_risk_trend": "recent high-risk-entry trend versus the previous window",
                "dropped_risk_overlap": "dropped-to-risk overlap",
                "dropped_warning_overlap": "dropped-to-warning overlap",
                "high_risk_warning_overlap": "high-risk-to-warning overlap",
                "high_risk_intervention_gap": "high-risk-to-intervention gap",
                "unresolved_risk_burden": "unresolved risk burden",
                "warning_intervention_gap": "warning-to-intervention gap",
                "risk": "prediction high risk students",
                "warnings": "students with an active warning",
                "intervention_coverage": "intervention coverage",
                "counsellor_coverage": "counsellor coverage",
            }
            if planner.get("user_goal") == "attention_analysis":
                attention_rows = _build_attention_rank_rows(comparison_rows)
                if attention_rows:
                    leader = attention_rows[0]
                    runner_up = attention_rows[1] if len(attention_rows) > 1 else None
                    attention_points = [
                        f"`{leader['value']}` needs attention first with an attention index of {leader['score']:.1f}.",
                        f"Why: {leader['why']}.",
                    ]
                    if runner_up is not None:
                        attention_points.append(
                            f"Next most pressured bucket: `{runner_up['value']}` with attention index {runner_up['score']:.1f}."
                        )
                    for row in attention_rows[: min(3, len(attention_rows))]:
                        attention_points.append(f"{row['value']} snapshot: {row['summary']}")
                    return (
                        build_grounded_response(
                            opening=f"I ranked the requested `{compare_dimension}` buckets by current retention attention pressure.",
                            key_points=attention_points,
                            tools_used=[
                                {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Built a domain reasoning plan for which cohort needs attention most"},
                                {"tool_name": "attention_index_orchestrator", "summary": f"Orchestrated risk, gap, and trend analytics across the requested {compare_dimension} buckets"},
                            ],
                            limitations=[],
                        ),
                        [
                            {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Built a domain reasoning plan for which cohort needs attention most"},
                            {"tool_name": "attention_index_orchestrator", "summary": f"Orchestrated risk, gap, and trend analytics across the requested {compare_dimension} buckets"},
                        ],
                        [],
                        {
                            "kind": "import_coverage",
                            "intent": "attention_analysis_summary",
                            "grouped_by": compare_dimension,
                            "bucket_values": compare_values,
                            "planner_version": str(planner.get("version") or COPILOT_SYSTEM_PROMPT_VERSION),
                            "analysis_mode": "attention_ranking",
                            "orchestration_steps": list(planner.get("orchestration_steps") or []),
                            "focus_bucket": str(leader.get("value") or "").strip(),
                            "pending_role_follow_up": "operational_actions",
                        },
                    )
            if planner.get("user_goal") == "diagnostic_comparison":
                diagnostic_rows = _build_diagnostic_rank_rows(comparison_rows)
                if diagnostic_rows:
                    leader = diagnostic_rows[0]
                    runner_up = diagnostic_rows[1] if len(diagnostic_rows) > 1 else None
                    diagnostic_points = [
                        f"`{leader['value']}` is showing the strongest retention pressure with a diagnostic score of {leader['score']:.1f}.",
                        f"Primary driver: {leader['driver']}.",
                        f"Why: {leader['why']}.",
                    ]
                    if runner_up is not None:
                        diagnostic_points.append(
                            f"Next diagnostic bucket: `{runner_up['value']}` with score {runner_up['score']:.1f}."
                        )
                    for row in diagnostic_rows[: min(3, len(diagnostic_rows))]:
                        diagnostic_points.append(f"{row['value']} diagnostic snapshot: {row['summary']}")
                    return (
                        build_grounded_response(
                            opening=f"I diagnosed the requested `{compare_dimension}` buckets to explain the strongest grounded retention drivers.",
                            key_points=diagnostic_points,
                            tools_used=[
                                {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Built a deeper diagnostic plan from the natural-language retention question"},
                                {"tool_name": "diagnostic_driver_orchestrator", "summary": f"Orchestrated risk, gap, and support-burden analytics across the requested {compare_dimension} buckets"},
                            ],
                            limitations=[],
                        ),
                        [
                            {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Built a deeper diagnostic plan from the natural-language retention question"},
                            {"tool_name": "diagnostic_driver_orchestrator", "summary": f"Orchestrated risk, gap, and support-burden analytics across the requested {compare_dimension} buckets"},
                        ],
                        [],
                        {
                            "kind": "import_coverage",
                            "intent": "diagnostic_comparison_summary",
                            "grouped_by": compare_dimension,
                            "bucket_values": compare_values,
                            "planner_version": str(planner.get("version") or COPILOT_SYSTEM_PROMPT_VERSION),
                            "analysis_mode": "diagnostic_comparison",
                            "orchestration_steps": list(planner.get("orchestration_steps") or []),
                            "focus_bucket": str(leader.get("value") or "").strip(),
                            "pending_role_follow_up": "operational_actions",
                        },
                    )
            for metric_kind in metric_kinds:
                metric_rows = comparison_rows.get(metric_kind) or []
                if not metric_rows:
                    continue
                ordered_counts = sorted(
                    metric_rows,
                    key=lambda item: (-float(item["rate"]), -int(item["count"]), str(item["value"]).lower()),
                )
                leader = ordered_counts[0]
                trailer = ordered_counts[-1]
                metric_label = metric_summary_labels.get(metric_kind, "comparison metric")
                if metric_kind in trend_metric_kinds:
                    if len(ordered_counts) == 1:
                        continue
                    if metric_kind == "intervention_trend":
                        key_points.append(
                            f"Most improved {metric_label}: `{leader['value']}` with {float(leader['rate']):+.1f} percentage points"
                        )
                        key_points.append(
                            f"Largest decline in {metric_label}: `{trailer['value']}` with {float(trailer['rate']):+.1f} percentage points"
                        )
                    else:
                        key_points.append(
                            f"Most worsening {metric_label}: `{leader['value']}` with {float(leader['rate']):+.1f} percentage points"
                        )
                        key_points.append(
                            f"Biggest improvement in {metric_label}: `{trailer['value']}` with {float(trailer['rate']):+.1f} percentage points"
                        )
                    continue
                if metric_kind in derived_metric_kinds:
                    if metric_kind in {"dropped_risk_overlap", "dropped_warning_overlap", "high_risk_warning_overlap", "high_risk_intervention_gap"}:
                        key_points.append(
                            f"Worst {metric_label}: `{leader['value']}` with {float(leader['rate']):.1f}%"
                        )
                        if len(ordered_counts) > 1:
                            key_points.append(
                                f"Lowest {metric_label}: `{trailer['value']}` with {float(trailer['rate']):.1f}%"
                            )
                    elif metric_kind == "unresolved_risk_burden":
                        key_points.append(
                            f"Highest {metric_label}: `{leader['value']}` with {float(leader['rate']):.1f} composite points"
                        )
                        if len(ordered_counts) > 1:
                            key_points.append(
                                f"Lowest {metric_label}: `{trailer['value']}` with {float(trailer['rate']):.1f} composite points"
                            )
                    else:
                        key_points.append(
                            f"Largest {metric_label}: `{leader['value']}` with {float(leader['rate']):+.1f} percentage points"
                        )
                        if len(ordered_counts) > 1:
                            key_points.append(
                                f"Smallest {metric_label}: `{trailer['value']}` with {float(trailer['rate']):+.1f} percentage points"
                            )
                    continue
                if metric_kind in {"intervention_coverage", "counsellor_coverage"} or has_multi_metric:
                    key_points.append(
                        f"Highest {metric_label}: `{leader['value']}` with {float(leader['rate']):.1f}%"
                    )
                    if len(ordered_counts) > 1:
                        key_points.append(
                            f"Lowest {metric_label}: `{trailer['value']}` with {float(trailer['rate']):.1f}%"
                        )
                else:
                    key_points.append(f"Highest {metric_label}: `{leader['value']}` with {int(leader['count'])}")
                    if len(ordered_counts) > 1:
                        key_points.append(f"Lowest {metric_label}: `{trailer['value']}` with {int(trailer['count'])}")

            tool_name = "imported_profile_filter"
            tool_summary = f"Compared matching students across the requested {compare_dimension} buckets"
            if "risk" in metric_kinds:
                tool_name = "subset_risk_summary"
                tool_summary = f"Compared current risk state across the requested {compare_dimension} buckets"
            if "dropped_risk_overlap" in metric_kinds:
                tool_name = "subset_risk_summary"
                tool_summary = f"Compared dropped-to-risk overlap across the requested {compare_dimension} buckets"
            if "dropped_warning_overlap" in metric_kinds:
                tool_name = "warning_status_summary"
                tool_summary = f"Compared dropped-to-warning overlap across the requested {compare_dimension} buckets"
            if "high_risk_warning_overlap" in metric_kinds:
                tool_name = "warning_status_summary"
                tool_summary = f"Compared high-risk-to-warning overlap across the requested {compare_dimension} buckets"
            if "high_risk_intervention_gap" in metric_kinds:
                tool_name = "intervention_summary"
                tool_summary = f"Compared high-risk-to-intervention gaps across the requested {compare_dimension} buckets"
            if "unresolved_risk_burden" in metric_kinds:
                tool_name = "diagnostic_driver_orchestrator"
                tool_summary = f"Compared unresolved risk burden across the requested {compare_dimension} buckets"
            if "warning_intervention_gap" in metric_kinds:
                tool_name = "intervention_summary"
                tool_summary = f"Compared warning-to-intervention gaps across the requested {compare_dimension} buckets"
            if "recent_entry_risk" in metric_kinds:
                tool_name = "prediction_history_window"
                tool_summary = f"Compared recent high-risk entries across the requested {compare_dimension} buckets"
            if "recent_warning_events" in metric_kinds:
                tool_name = "warning_status_summary"
                tool_summary = f"Compared recent warning events across the requested {compare_dimension} buckets"
            if "recent_intervention_events" in metric_kinds:
                tool_name = "intervention_summary"
                tool_summary = f"Compared recent intervention actions across the requested {compare_dimension} buckets"
            if "warning_trend" in metric_kinds:
                tool_name = "warning_status_summary"
                tool_summary = f"Compared recent warning trends across the requested {compare_dimension} buckets"
            if "intervention_trend" in metric_kinds:
                tool_name = "intervention_summary"
                tool_summary = f"Compared recent intervention coverage trends across the requested {compare_dimension} buckets"
            if "recent_entry_risk_trend" in metric_kinds:
                tool_name = "prediction_history_window"
                tool_summary = f"Compared recent high-risk-entry trends across the requested {compare_dimension} buckets"
            if "warnings" in metric_kinds:
                tool_name = "warning_status_summary"
                tool_summary = f"Compared active warning coverage across the requested {compare_dimension} buckets"
            if "intervention_coverage" in metric_kinds:
                tool_name = "intervention_summary"
                tool_summary = f"Compared intervention coverage across the requested {compare_dimension} buckets"
            if "counsellor_coverage" in metric_kinds and len(metric_kinds) == 1:
                tool_name = "counsellor_subset_summary"
                tool_summary = f"Compared counsellor coverage across the requested {compare_dimension} buckets"
            opening = f"I compared the imported cohort across the requested `{compare_dimension}` buckets."
            if any(metric in metric_kinds for metric in trend_metric_kinds):
                if len(compare_values) == 1:
                    opening = f"I checked the recent `{compare_dimension}` trend for the requested imported subset."
                else:
                    opening = f"I compared recent `{compare_dimension}` trends across the requested imported cohort buckets."
            return (
                build_grounded_response(
                    opening=opening,
                    key_points=key_points,
                    tools_used=[
                        {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Built a structured comparison plan from the natural-language admin question"},
                        {"tool_name": tool_name, "summary": tool_summary},
                    ],
                    limitations=[
                        *(
                            ["Planner interpreted a trend-style phrase as a current-state comparison because historical trend comparison by dimension is not built yet."]
                            if ("lately" in lowered or "recent" in lowered) and not any(metric in metric_kinds for metric in trend_metric_kinds)
                            else []
                        )
                    ],
                ),
                [
                    {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Built a structured comparison plan from the natural-language admin question"},
                    {"tool_name": tool_name, "summary": tool_summary},
                ],
                [
                    *(
                        ["Planner interpreted a trend-style phrase as a current-state comparison because historical trend comparison by dimension is not built yet."]
                        if ("lately" in lowered or "recent" in lowered) and not any(metric in metric_kinds for metric in trend_metric_kinds)
                        else []
                    )
                ],
                {
                    "kind": "import_coverage",
                    "intent": "comparison_summary",
                    "grouped_by": compare_dimension,
                    "bucket_values": compare_values,
                    "planner_version": str(planner.get("version") or COPILOT_SYSTEM_PROMPT_VERSION),
                    "analysis_mode": str(planner.get("analysis_mode") or "comparison"),
                    "orchestration_steps": list(planner.get("orchestration_steps") or []),
                },
            )

    outcome_mentions = _extract_outcome_mentions(lowered)
    direct_outcome = outcome_mentions[0] if len(outcome_mentions) == 1 else None
    branch_mentions = _extract_profile_context_mentions(
        lowered=lowered,
        profiles=profiles,
        key="branch",
    )
    branch_filter = branch_mentions[0] if len(branch_mentions) == 1 else None
    category_mentions = _extract_profile_context_mentions(
        lowered=lowered,
        profiles=profiles,
        key="category",
    )
    category_filter = category_mentions[0] if len(category_mentions) == 1 else None
    region_mentions = _extract_profile_context_mentions(
        lowered=lowered,
        profiles=profiles,
        key="region",
    )
    region_filter = region_mentions[0] if len(region_mentions) == 1 else None
    income_mentions = _extract_profile_context_mentions(
        lowered=lowered,
        profiles=profiles,
        key="income",
    )
    income_filter = income_mentions[0] if len(income_mentions) == 1 else None
    subset_asks = _extract_subset_asks(lowered)
    wants_current_risk_count = subset_asks["risk"]
    wants_counsellor_summary = subset_asks["counsellors"]
    wants_warning_summary = subset_asks["warnings"]
    if _has_conflicting_metric_request(lowered):
        return (
            build_grounded_response(
                opening="I can help with that cohort question, but the metric part of your request conflicts with itself.",
                key_points=[
                    "You asked me to both show and negate the same metric in one turn.",
                    "Please choose one direction, for example: `show warnings` or `exclude the warned students`.",
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin grouped metric request"},
                    {"tool_name": "metric_conflict_guard", "summary": "Detected a contradictory metric request and asked for clarification"},
                ],
                limitations=["conflicting metric instructions need clarification before I can compute the right cohort summary"],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin grouped metric request"},
                {"tool_name": "metric_conflict_guard", "summary": "Detected a contradictory metric request and asked for clarification"},
            ],
            ["conflicting metric instructions need clarification before I can compute the right cohort summary"],
            {
                "kind": "import_coverage",
                "intent": "metric_conflict_clarification",
                "role_scope": "admin",
            },
        )
    filter_summary = _build_filter_summary(
        outcome_status=direct_outcome,
        branch=branch_filter,
        category=category_filter,
        region=region_filter,
        income=income_filter,
    )
    non_outcome_filter_summary = _build_filter_summary(
        outcome_status=None,
        branch=branch_filter,
        category=category_filter,
        region=region_filter,
        income=income_filter,
    )
    non_branch_filter_summary = _build_filter_summary(
        outcome_status=direct_outcome,
        branch=None,
        category=category_filter,
        region=region_filter,
        income=income_filter,
    )
    non_category_filter_summary = _build_filter_summary(
        outcome_status=direct_outcome,
        branch=branch_filter,
        category=None,
        region=region_filter,
        income=income_filter,
    )
    non_region_filter_summary = _build_filter_summary(
        outcome_status=direct_outcome,
        branch=branch_filter,
        category=category_filter,
        region=None,
        income=income_filter,
    )
    non_income_filter_summary = _build_filter_summary(
        outcome_status=direct_outcome,
        branch=branch_filter,
        category=category_filter,
        region=region_filter,
        income=None,
    )
    has_context_filters = any(
        value is not None for value in (branch_filter, category_filter, region_filter, income_filter)
    )
    wants_subset_planner = wants_current_risk_count or wants_counsellor_summary or wants_warning_summary

    multi_bucket_filters = [
        ("branch", branch_mentions),
        ("category", category_mentions),
        ("region", region_mentions),
        ("income", income_mentions),
    ]
    comparison_dimensions = [
        ("outcome_status", outcome_mentions),
        *multi_bucket_filters,
    ]
    compare_dimensions = [
        key for key, values in comparison_dimensions if len(values) > 1 and _wants_comparison(lowered)
    ]
    if len(compare_dimensions) > 1:
        return (
            build_grounded_response(
                opening="I can compare cohorts for you, but I need one comparison dimension at a time.",
                key_points=[
                    f"I detected more than one comparison dimension: {', '.join(compare_dimensions)}.",
                    "Please choose one, such as branch, category, region, income, or outcome status.",
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin comparison request"},
                    {"tool_name": "comparison_clarifier", "summary": "Asked the user to choose a single comparison dimension"},
                ],
                limitations=["comparison mode currently supports one grouping dimension at a time"],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin comparison request"},
                {"tool_name": "comparison_clarifier", "summary": "Asked the user to choose a single comparison dimension"},
            ],
            ["comparison mode currently supports one grouping dimension at a time"],
            {"kind": "import_coverage", "intent": "comparison_clarification", "role_scope": "admin"},
        )
    if len(compare_dimensions) == 1:
        compare_dimension = compare_dimensions[0]
        compare_values = next(values for key, values in comparison_dimensions if key == compare_dimension)
        latest_predictions_by_student = {int(row.student_id): row for row in _get_latest_predictions()}
        metric_label = "matching students"
        tool_name = "imported_profile_filter"
        tool_summary = f"Compared imported students by {compare_dimension}"
        key_points: list[str] = []
        counts_by_value: list[tuple[str, int]] = []
        for value in compare_values:
            grouped_subset = _filter_profiles_for_admin_query(
                profiles=profiles,
                outcome_status=value if compare_dimension == "outcome_status" else direct_outcome,
                branch=value if compare_dimension == "branch" else branch_filter,
                category=value if compare_dimension == "category" else category_filter,
                region=value if compare_dimension == "region" else region_filter,
                income=value if compare_dimension == "income" else income_filter,
            )
            count_value = len(grouped_subset)
            if wants_current_risk_count:
                metric_label = "prediction high risk students"
                tool_name = "subset_risk_summary"
                tool_summary = f"Compared current risk state across {compare_dimension} buckets"
                count_value = sum(
                    1
                    for profile in grouped_subset
                    if (
                        latest_predictions_by_student.get(int(profile.student_id)) is not None
                        and int(latest_predictions_by_student[int(profile.student_id)].final_predicted_class) == 1
                    )
                )
            elif wants_warning_summary:
                metric_label = "students with an active warning"
                tool_name = "warning_status_summary"
                tool_summary = f"Compared active warning coverage across {compare_dimension} buckets"
                count_value = sum(
                    1
                    for profile in grouped_subset
                    if repository.get_active_student_warning_for_student(int(profile.student_id)) is not None
                )
            counts_by_value.append((value, count_value))
            key_points.append(f"{value} {metric_label}: {count_value}")
        leader_value, leader_count = max(counts_by_value, key=lambda item: item[1])
        trailer_value, trailer_count = min(counts_by_value, key=lambda item: item[1])
        key_points.append(f"Highest {metric_label}: `{leader_value}` with {leader_count}")
        if len(counts_by_value) > 1:
            key_points.append(f"Lowest {metric_label}: `{trailer_value}` with {trailer_count}")
        return (
            build_grounded_response(
                opening=f"I compared the imported cohort across the requested `{compare_dimension}` buckets.",
                key_points=key_points,
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin comparison request"},
                    {"tool_name": tool_name, "summary": tool_summary},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin comparison request"},
                {"tool_name": tool_name, "summary": tool_summary},
            ],
            [],
            {
                "kind": "import_coverage",
                "intent": "comparison_summary",
                "grouped_by": compare_dimension,
                "bucket_values": compare_values,
                "student_ids": [],
                "outcome_status": direct_outcome if compare_dimension != "outcome_status" else None,
                "branch": branch_filter if compare_dimension != "branch" else None,
                "category": category_filter if compare_dimension != "category" else None,
                "region": region_filter if compare_dimension != "region" else None,
                "income": income_filter if compare_dimension != "income" else None,
                "role_scope": "admin",
            },
        )
    multi_bucket_keys = [key for key, values in multi_bucket_filters if len(values) > 1]
    if len(multi_bucket_keys) > 2:
        return (
            build_grounded_response(
                opening="I can group by multiple filters, but I need to do it one dimension at a time.",
                key_points=[
                    f"I detected multiple multi-bucket filters in the same query: {', '.join(multi_bucket_keys)}.",
                    "Please choose up to two grouping dimensions so I can keep the grouped summary readable.",
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin multi-bucket filter request"},
                    {"tool_name": "filter_conflict_guard", "summary": "Detected conflicting multi-bucket filters and asked for clarification"},
                ],
                limitations=["multi-bucket grouping is currently capped at two dimensions in one answer"],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin multi-bucket filter request"},
                {"tool_name": "filter_conflict_guard", "summary": "Detected conflicting multi-bucket filters and asked for clarification"},
            ],
            ["multi-bucket grouping is currently capped at two dimensions in one answer"],
            {
                "kind": "import_coverage",
                "intent": "multi_bucket_filter_conflict_clarification",
                "role_scope": "admin",
            },
        )
    if len(multi_bucket_keys) == 2:
        latest_predictions_by_student = {int(row.student_id): row for row in _get_latest_predictions()}
        grouped_value_map = {
            "branch": branch_mentions,
            "category": category_mentions,
            "region": region_mentions,
            "income": income_mentions,
        }
        primary_dimension, secondary_dimension = multi_bucket_keys
        primary_values = grouped_value_map[primary_dimension]
        secondary_values = grouped_value_map[secondary_dimension]
        key_points: list[str] = []
        for primary_value in primary_values:
            for secondary_value in secondary_values:
                grouped_subset = _filter_profiles_for_admin_query(
                    profiles=profiles,
                    outcome_status=direct_outcome,
                    branch=primary_value if primary_dimension == "branch" else (secondary_value if secondary_dimension == "branch" else branch_filter),
                    category=primary_value if primary_dimension == "category" else (secondary_value if secondary_dimension == "category" else category_filter),
                    region=primary_value if primary_dimension == "region" else (secondary_value if secondary_dimension == "region" else region_filter),
                    income=primary_value if primary_dimension == "income" else (secondary_value if secondary_dimension == "income" else income_filter),
                )
                bucket_label = f"{primary_value} / {secondary_value}"
                key_points.append(f"{bucket_label} students: {len(grouped_subset)}")
                if wants_subset_planner:
                    if wants_current_risk_count:
                        high_risk_count = sum(
                            1
                            for profile in grouped_subset
                            if (
                                latest_predictions_by_student.get(int(profile.student_id)) is not None
                                and int(latest_predictions_by_student[int(profile.student_id)].final_predicted_class) == 1
                            )
                        )
                        key_points.append(f"{bucket_label} prediction high risk students: {high_risk_count}")
                    if wants_warning_summary:
                        warning_count = sum(
                            1
                            for profile in grouped_subset
                            if repository.get_active_student_warning_for_student(int(profile.student_id)) is not None
                        )
                        key_points.append(f"{bucket_label} students with an active warning: {warning_count}")
                    if wants_counsellor_summary:
                        counsellor_lines = _subset_counsellor_lines(grouped_subset)
                        key_points.extend(
                            [f"{bucket_label} {line}" for line in counsellor_lines]
                            or [f"{bucket_label} Counsellor: not assigned / no email"]
                        )
                else:
                    sample_lines = [
                        f"{bucket_label} {int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'})"
                        for profile in grouped_subset[:3]
                    ]
                    key_points.extend(sample_lines or [f"No students matched `{bucket_label}` for this filter."])
        grouped_student_ids = [
            int(profile.student_id)
            for primary_value in primary_values
            for secondary_value in secondary_values
            for profile in _filter_profiles_for_admin_query(
                profiles=profiles,
                outcome_status=direct_outcome,
                branch=primary_value if primary_dimension == "branch" else (secondary_value if secondary_dimension == "branch" else branch_filter),
                category=primary_value if primary_dimension == "category" else (secondary_value if secondary_dimension == "category" else category_filter),
                region=primary_value if primary_dimension == "region" else (secondary_value if secondary_dimension == "region" else region_filter),
                income=primary_value if primary_dimension == "income" else (secondary_value if secondary_dimension == "income" else income_filter),
            )
        ]
        return (
            build_grounded_response(
                opening=(
                    f"I grouped the imported cohort by {primary_dimension} and {secondary_dimension}"
                    f"{f' for {filter_summary}' if filter_summary else ''}."
                ),
                key_points=key_points,
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin multi-dimension grouping request"},
                    {"tool_name": "imported_profile_filter", "summary": "Grouped imported students across two institutional dimensions"},
                    *(
                        [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for each grouped bucket"}]
                        if wants_current_risk_count
                        else []
                    ),
                    *(
                        [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for each grouped bucket"}]
                        if wants_warning_summary
                        else []
                    ),
                    *(
                        [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for each grouped bucket"}]
                        if wants_counsellor_summary
                        else []
                    ),
                ],
                limitations=["I am showing a condensed grouped summary in-chat to keep the response readable"],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin multi-dimension grouping request"},
                {"tool_name": "imported_profile_filter", "summary": "Grouped imported students across two institutional dimensions"},
                *(
                    [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for each grouped bucket"}]
                    if wants_current_risk_count
                    else []
                ),
                *(
                    [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for each grouped bucket"}]
                    if wants_warning_summary
                    else []
                ),
                *(
                    [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for each grouped bucket"}]
                    if wants_counsellor_summary
                    else []
                ),
            ],
            ["I am showing a condensed grouped summary in-chat to keep the response readable"],
            {
                "kind": "import_coverage",
                "intent": "multi_dimension_grouped_summary",
                "student_ids": grouped_student_ids,
                "grouped_by": primary_dimension,
                "bucket_values": primary_values,
                "secondary_grouped_by": secondary_dimension,
                "secondary_bucket_values": secondary_values,
                "outcome_status": direct_outcome,
                "branch": None if "branch" in multi_bucket_keys else branch_filter,
                "category": None if "category" in multi_bucket_keys else category_filter,
                "region": None if "region" in multi_bucket_keys else region_filter,
                "income": None if "income" in multi_bucket_keys else income_filter,
                "role_scope": "admin",
            },
        )

    if len(branch_mentions) > 1:
        grouped_profiles: list[tuple[str, list[object]]] = [
            (
                branch_value,
                _filter_profiles_for_admin_query(
                    profiles=profiles,
                    outcome_status=direct_outcome,
                    branch=branch_value,
                    category=category_filter,
                    region=region_filter,
                    income=income_filter,
                ),
            )
            for branch_value in branch_mentions
        ]
        latest_predictions_by_student = {int(row.student_id): row for row in _get_latest_predictions()}
        key_points: list[str] = []
        for branch_value, grouped_subset in grouped_profiles:
            key_points.append(f"{branch_value} students: {len(grouped_subset)}")
            if wants_subset_planner:
                if wants_current_risk_count:
                    high_risk_count = sum(
                        1
                        for profile in grouped_subset
                        if (
                            latest_predictions_by_student.get(int(profile.student_id)) is not None
                            and int(latest_predictions_by_student[int(profile.student_id)].final_predicted_class) == 1
                        )
                    )
                    key_points.append(f"{branch_value} prediction high risk students: {high_risk_count}")
                if wants_warning_summary:
                    warning_count = sum(
                        1
                        for profile in grouped_subset
                        if repository.get_active_student_warning_for_student(int(profile.student_id)) is not None
                    )
                    key_points.append(f"{branch_value} students with an active warning: {warning_count}")
                if wants_counsellor_summary:
                    key_points.extend(_bucket_counsellor_lines(branch_value, grouped_subset))
            else:
                sample_lines = [
                    f"{int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'})"
                    for profile in grouped_subset[:5]
                ]
                key_points.extend(sample_lines or [f"No students matched `{branch_value}` for this filter."])
        return (
            build_grounded_response(
                opening=(
                    "I grouped the imported cohort by each requested branch"
                    f"{f' for {non_branch_filter_summary}' if non_branch_filter_summary else ''}."
                ),
                key_points=key_points,
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin branch filter request"},
                    {
                        "tool_name": "imported_profile_filter",
                        "summary": "Grouped imported students by branch and institutional profile fields",
                    },
                    *(
                        [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for each branch bucket"}]
                        if wants_current_risk_count
                        else []
                    ),
                    *(
                        [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for each branch bucket"}]
                        if wants_warning_summary
                        else []
                    ),
                    *(
                        [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for each branch bucket"}]
                        if wants_counsellor_summary
                        else []
                    ),
                ],
                limitations=[
                    "I am showing a condensed grouped summary in-chat to keep the response readable"
                ],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin branch filter request"},
                {
                    "tool_name": "imported_profile_filter",
                    "summary": "Grouped imported students by branch and institutional profile fields",
                },
                *(
                    [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for each branch bucket"}]
                    if wants_current_risk_count
                    else []
                ),
                *(
                    [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for each branch bucket"}]
                    if wants_warning_summary
                    else []
                ),
                *(
                    [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for each branch bucket"}]
                    if wants_counsellor_summary
                    else []
                ),
            ],
            ["I am showing a condensed grouped summary in-chat to keep the response readable"],
            {
                "kind": "import_coverage",
                "intent": "multi_branch_grouped_summary",
                "student_ids": [
                    int(profile.student_id)
                    for _, grouped_subset in grouped_profiles
                    for profile in grouped_subset
                ],
                "grouped_by": "branch",
                "bucket_values": [value for value, _ in grouped_profiles],
                "outcome_status": direct_outcome,
                "category": category_filter,
                "region": region_filter,
                "income": income_filter,
                "role_scope": "admin",
            },
        )

    if len(category_mentions) > 1:
        grouped_profiles: list[tuple[str, list[object]]] = [
            (
                category_value,
                _filter_profiles_for_admin_query(
                    profiles=profiles,
                    outcome_status=direct_outcome,
                    branch=branch_filter,
                    category=category_value,
                    region=region_filter,
                    income=income_filter,
                ),
            )
            for category_value in category_mentions
        ]
        latest_predictions_by_student = {int(row.student_id): row for row in _get_latest_predictions()}
        key_points: list[str] = []
        for category_value, grouped_subset in grouped_profiles:
            key_points.append(f"{category_value} students: {len(grouped_subset)}")
            if wants_subset_planner:
                if wants_current_risk_count:
                    high_risk_count = sum(
                        1
                        for profile in grouped_subset
                        if (
                            latest_predictions_by_student.get(int(profile.student_id)) is not None
                            and int(latest_predictions_by_student[int(profile.student_id)].final_predicted_class) == 1
                        )
                    )
                    key_points.append(f"{category_value} prediction high risk students: {high_risk_count}")
                if wants_warning_summary:
                    warning_count = sum(
                        1
                        for profile in grouped_subset
                        if repository.get_active_student_warning_for_student(int(profile.student_id)) is not None
                    )
                    key_points.append(f"{category_value} students with an active warning: {warning_count}")
                if wants_counsellor_summary:
                    key_points.extend(_bucket_counsellor_lines(category_value, grouped_subset))
            else:
                sample_lines = [
                    f"{int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'})"
                    for profile in grouped_subset[:5]
                ]
                key_points.extend(sample_lines or [f"No students matched `{category_value}` for this filter."])
        return (
            build_grounded_response(
                opening=(
                    "I grouped the imported cohort by each requested category"
                    f"{f' for {non_category_filter_summary}' if non_category_filter_summary else ''}."
                ),
                key_points=key_points,
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin category filter request"},
                    {
                        "tool_name": "imported_profile_filter",
                        "summary": "Grouped imported students by category and institutional profile fields",
                    },
                    *(
                        [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for each category bucket"}]
                        if wants_current_risk_count
                        else []
                    ),
                    *(
                        [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for each category bucket"}]
                        if wants_warning_summary
                        else []
                    ),
                    *(
                        [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for each category bucket"}]
                        if wants_counsellor_summary
                        else []
                    ),
                ],
                limitations=[
                    "I am showing a condensed grouped summary in-chat to keep the response readable"
                ],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin category filter request"},
                {
                    "tool_name": "imported_profile_filter",
                    "summary": "Grouped imported students by category and institutional profile fields",
                },
                *(
                    [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for each category bucket"}]
                    if wants_current_risk_count
                    else []
                ),
                *(
                    [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for each category bucket"}]
                    if wants_warning_summary
                    else []
                ),
                *(
                    [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for each category bucket"}]
                    if wants_counsellor_summary
                    else []
                ),
            ],
            ["I am showing a condensed grouped summary in-chat to keep the response readable"],
            {
                "kind": "import_coverage",
                "intent": "multi_category_grouped_summary",
                "student_ids": [
                    int(profile.student_id)
                    for _, grouped_subset in grouped_profiles
                    for profile in grouped_subset
                ],
                "grouped_by": "category",
                "bucket_values": [value for value, _ in grouped_profiles],
                "outcome_status": direct_outcome,
                "branch": branch_filter,
                "region": region_filter,
                "income": income_filter,
                "role_scope": "admin",
            },
        )

    if len(region_mentions) > 1:
        grouped_profiles: list[tuple[str, list[object]]] = [
            (
                region_value,
                _filter_profiles_for_admin_query(
                    profiles=profiles,
                    outcome_status=direct_outcome,
                    branch=branch_filter,
                    category=category_filter,
                    region=region_value,
                    income=income_filter,
                ),
            )
            for region_value in region_mentions
        ]
        latest_predictions_by_student = {int(row.student_id): row for row in _get_latest_predictions()}
        key_points: list[str] = []
        for region_value, grouped_subset in grouped_profiles:
            key_points.append(f"{region_value} students: {len(grouped_subset)}")
            if wants_subset_planner:
                if wants_current_risk_count:
                    high_risk_count = sum(
                        1
                        for profile in grouped_subset
                        if (
                            latest_predictions_by_student.get(int(profile.student_id)) is not None
                            and int(latest_predictions_by_student[int(profile.student_id)].final_predicted_class) == 1
                        )
                    )
                    key_points.append(f"{region_value} prediction high risk students: {high_risk_count}")
                if wants_warning_summary:
                    warning_count = sum(
                        1
                        for profile in grouped_subset
                        if repository.get_active_student_warning_for_student(int(profile.student_id)) is not None
                    )
                    key_points.append(f"{region_value} students with an active warning: {warning_count}")
                if wants_counsellor_summary:
                    key_points.extend(_bucket_counsellor_lines(region_value, grouped_subset))
            else:
                sample_lines = [
                    f"{int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'})"
                    for profile in grouped_subset[:5]
                ]
                key_points.extend(sample_lines or [f"No students matched `{region_value}` for this filter."])
        return (
            build_grounded_response(
                opening=(
                    "I grouped the imported cohort by each requested region"
                    f"{f' for {non_region_filter_summary}' if non_region_filter_summary else ''}."
                ),
                key_points=key_points,
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin region filter request"},
                    {
                        "tool_name": "imported_profile_filter",
                        "summary": "Grouped imported students by region and institutional profile fields",
                    },
                    *(
                        [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for each region bucket"}]
                        if wants_current_risk_count
                        else []
                    ),
                    *(
                        [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for each region bucket"}]
                        if wants_warning_summary
                        else []
                    ),
                    *(
                        [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for each region bucket"}]
                        if wants_counsellor_summary
                        else []
                    ),
                ],
                limitations=[
                    "I am showing a condensed grouped summary in-chat to keep the response readable"
                ],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin region filter request"},
                {
                    "tool_name": "imported_profile_filter",
                    "summary": "Grouped imported students by region and institutional profile fields",
                },
                *(
                    [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for each region bucket"}]
                    if wants_current_risk_count
                    else []
                ),
                *(
                    [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for each region bucket"}]
                    if wants_warning_summary
                    else []
                ),
                *(
                    [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for each region bucket"}]
                    if wants_counsellor_summary
                    else []
                ),
            ],
            ["I am showing a condensed grouped summary in-chat to keep the response readable"],
            {
                "kind": "import_coverage",
                "intent": "multi_region_grouped_summary",
                "student_ids": [
                    int(profile.student_id)
                    for _, grouped_subset in grouped_profiles
                    for profile in grouped_subset
                ],
                "grouped_by": "region",
                "bucket_values": [value for value, _ in grouped_profiles],
                "outcome_status": direct_outcome,
                "branch": branch_filter,
                "category": category_filter,
                "income": income_filter,
                "role_scope": "admin",
            },
        )

    if len(income_mentions) > 1:
        grouped_profiles: list[tuple[str, list[object]]] = [
            (
                income_value,
                _filter_profiles_for_admin_query(
                    profiles=profiles,
                    outcome_status=direct_outcome,
                    branch=branch_filter,
                    category=category_filter,
                    region=region_filter,
                    income=income_value,
                ),
            )
            for income_value in income_mentions
        ]
        latest_predictions_by_student = {int(row.student_id): row for row in _get_latest_predictions()}
        key_points: list[str] = []
        for income_value, grouped_subset in grouped_profiles:
            key_points.append(f"{income_value} students: {len(grouped_subset)}")
            if wants_subset_planner:
                if wants_current_risk_count:
                    high_risk_count = sum(
                        1
                        for profile in grouped_subset
                        if (
                            latest_predictions_by_student.get(int(profile.student_id)) is not None
                            and int(latest_predictions_by_student[int(profile.student_id)].final_predicted_class) == 1
                        )
                    )
                    key_points.append(f"{income_value} prediction high risk students: {high_risk_count}")
                if wants_warning_summary:
                    warning_count = sum(
                        1
                        for profile in grouped_subset
                        if repository.get_active_student_warning_for_student(int(profile.student_id)) is not None
                    )
                    key_points.append(f"{income_value} students with an active warning: {warning_count}")
                if wants_counsellor_summary:
                    key_points.extend(_bucket_counsellor_lines(income_value, grouped_subset))
            else:
                sample_lines = [
                    f"{int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'})"
                    for profile in grouped_subset[:5]
                ]
                key_points.extend(sample_lines or [f"No students matched `{income_value}` for this filter."])
        return (
            build_grounded_response(
                opening=(
                    "I grouped the imported cohort by each requested income band"
                    f"{f' for {non_income_filter_summary}' if non_income_filter_summary else ''}."
                ),
                key_points=key_points,
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin income filter request"},
                    {
                        "tool_name": "imported_profile_filter",
                        "summary": "Grouped imported students by income and institutional profile fields",
                    },
                    *(
                        [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for each income bucket"}]
                        if wants_current_risk_count
                        else []
                    ),
                    *(
                        [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for each income bucket"}]
                        if wants_warning_summary
                        else []
                    ),
                    *(
                        [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for each income bucket"}]
                        if wants_counsellor_summary
                        else []
                    ),
                ],
                limitations=[
                    "I am showing a condensed grouped summary in-chat to keep the response readable"
                ],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin income filter request"},
                {
                    "tool_name": "imported_profile_filter",
                    "summary": "Grouped imported students by income and institutional profile fields",
                },
                *(
                    [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for each income bucket"}]
                    if wants_current_risk_count
                    else []
                ),
                *(
                    [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for each income bucket"}]
                    if wants_warning_summary
                    else []
                ),
                *(
                    [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for each income bucket"}]
                    if wants_counsellor_summary
                    else []
                ),
            ],
            ["I am showing a condensed grouped summary in-chat to keep the response readable"],
            {
                "kind": "import_coverage",
                "intent": "multi_income_grouped_summary",
                "student_ids": [
                    int(profile.student_id)
                    for _, grouped_subset in grouped_profiles
                    for profile in grouped_subset
                ],
                "grouped_by": "income",
                "bucket_values": [value for value, _ in grouped_profiles],
                "outcome_status": direct_outcome,
                "branch": branch_filter,
                "category": category_filter,
                "region": region_filter,
                "role_scope": "admin",
            },
        )

    if len(outcome_mentions) > 1:
        grouped_profiles: list[tuple[str, list[object]]] = [
            (
                outcome_status,
                _filter_profiles_for_admin_query(
                    profiles=profiles,
                    outcome_status=outcome_status,
                    branch=branch_filter,
                    category=category_filter,
                    region=region_filter,
                    income=income_filter,
                ),
            )
            for outcome_status in outcome_mentions
        ]
        latest_predictions_by_student = {int(row.student_id): row for row in _get_latest_predictions()}
        key_points: list[str] = []
        for outcome_status, grouped_subset in grouped_profiles:
            key_points.append(f"{outcome_status} students: {len(grouped_subset)}")
            if wants_subset_planner:
                if wants_current_risk_count:
                    high_risk_count = sum(
                        1
                        for profile in grouped_subset
                        if (
                            latest_predictions_by_student.get(int(profile.student_id)) is not None
                            and int(latest_predictions_by_student[int(profile.student_id)].final_predicted_class) == 1
                        )
                    )
                    key_points.append(f"{outcome_status} prediction high risk students: {high_risk_count}")
                if wants_warning_summary:
                    warning_count = sum(
                        1
                        for profile in grouped_subset
                        if repository.get_active_student_warning_for_student(int(profile.student_id)) is not None
                    )
                    key_points.append(f"{outcome_status} students with an active warning: {warning_count}")
                if wants_counsellor_summary:
                    key_points.extend(_bucket_counsellor_lines(outcome_status, grouped_subset))
            else:
                sample_lines = [
                    f"{int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'})"
                    for profile in grouped_subset[:5]
                ]
                key_points.extend(sample_lines or [f"No students matched `{outcome_status}` for this filter."])
        return (
            build_grounded_response(
                opening=(
                    "I grouped the imported cohort by each requested outcome status"
                    f"{f' for {non_outcome_filter_summary}' if non_outcome_filter_summary else ''}."
                ),
                key_points=key_points,
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin outcome filter request"},
                    {
                        "tool_name": "imported_profile_filter",
                        "summary": "Grouped imported students by outcome status and institutional profile fields",
                    },
                    *(
                        [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for each outcome-status bucket"}]
                        if wants_current_risk_count
                        else []
                    ),
                    *(
                        [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for each outcome-status bucket"}]
                        if wants_warning_summary
                        else []
                    ),
                    *(
                        [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for each outcome-status bucket"}]
                        if wants_counsellor_summary
                        else []
                    ),
                ],
                limitations=[
                    "I am showing a condensed grouped summary in-chat to keep the response readable"
                ],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin outcome filter request"},
                {
                    "tool_name": "imported_profile_filter",
                    "summary": "Grouped imported students by outcome status and institutional profile fields",
                },
                *(
                    [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for each outcome-status bucket"}]
                    if wants_current_risk_count
                    else []
                ),
                *(
                    [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for each outcome-status bucket"}]
                    if wants_warning_summary
                    else []
                ),
                *(
                    [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for each outcome-status bucket"}]
                    if wants_counsellor_summary
                    else []
                ),
            ],
            ["I am showing a condensed grouped summary in-chat to keep the response readable"],
            {
                "kind": "import_coverage",
                "intent": "multi_outcome_grouped_summary",
                "student_ids": [
                    int(profile.student_id)
                    for _, grouped_subset in grouped_profiles
                    for profile in grouped_subset
                ],
                "grouped_by": "outcome_status",
                "bucket_values": [value for value, _ in grouped_profiles],
                "branch": branch_filter,
                "category": category_filter,
                "region": region_filter,
                "income": income_filter,
                "role_scope": "admin",
            },
        )

    if (direct_outcome is not None or has_context_filters) and _looks_like_compound_subset_query(lowered) and not wants_subset_planner:
        return (
            build_grounded_response(
                opening=f"I understood the filtered subset for {filter_summary or 'the requested criteria'}, but I need one more detail.",
                key_points=[
                    "Do you want current high-risk count, active warning count, counsellor coverage, or a combination of those?",
                    "Example: 'show dropped students in CSE and tell me how many are high risk'",
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin compound subset query"},
                    {"tool_name": "subset_query_clarifier", "summary": "Asked for the missing subset metric or summary target"},
                ],
                limitations=["compound subset query is missing the requested metric or summary target"],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin compound subset query"},
                {"tool_name": "subset_query_clarifier", "summary": "Asked for the missing subset metric or summary target"},
            ],
            ["compound subset query is missing the requested metric or summary target"],
            {
                "kind": "import_coverage",
                "intent": "compound_subset_clarification",
                "outcome_status": direct_outcome,
                "branch": branch_filter,
                "category": category_filter,
                "region": region_filter,
                "income": income_filter,
                "role_scope": "admin",
            },
        )

    if (direct_outcome is not None or has_context_filters) and wants_subset_planner:
        matching_profiles = _filter_profiles_for_admin_query(
            profiles=profiles,
            outcome_status=direct_outcome,
            branch=branch_filter,
            category=category_filter,
            region=region_filter,
            income=income_filter,
        )
        latest_predictions_by_student = {
            int(row.student_id): row for row in _get_latest_predictions()
        }
        high_risk_subset = [
            profile
            for profile in matching_profiles
            if (
                latest_predictions_by_student.get(int(profile.student_id)) is not None
                and int(latest_predictions_by_student[int(profile.student_id)].final_predicted_class) == 1
            )
        ]
        active_warning_count = sum(
            1
            for profile in matching_profiles
            if repository.get_active_student_warning_for_student(int(profile.student_id)) is not None
        )
        sample_lines: list[str] = [f"Matching students: {len(matching_profiles)}"]
        if wants_current_risk_count:
            sample_lines.append(f"Currently high-risk students: {len(high_risk_subset)}")
        if wants_warning_summary:
            sample_lines.append(f"Students with an active warning: {active_warning_count}")
        if wants_counsellor_summary:
            sample_lines.extend(_subset_counsellor_lines(matching_profiles))
        if not wants_counsellor_summary and wants_current_risk_count:
            sample_lines.extend(
                [
                    f"{int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'})"
                    for profile in high_risk_subset[:10]
                ]
            )
        return (
            build_grounded_response(
                opening=(
                    f"I analyzed the filtered imported subset for {filter_summary or 'the requested criteria'}."
                ),
                key_points=sample_lines or ["No students matched this filtered subset."],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin compound subset query"},
                    {"tool_name": "imported_profile_filter", "summary": "Filtered imported students by outcome status and institutional profile fields"},
                    *(
                        [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for the filtered subset"}]
                        if wants_current_risk_count
                        else []
                    ),
                    *(
                        [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for the filtered subset"}]
                        if wants_warning_summary
                        else []
                    ),
                    *(
                        [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for the filtered subset"}]
                        if wants_counsellor_summary
                        else []
                    ),
                ],
                limitations=(
                    ["I am showing a condensed subset summary in-chat to keep the response readable"]
                    if len(sample_lines) > 6
                    else []
                ),
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin compound subset query"},
                {"tool_name": "imported_profile_filter", "summary": "Filtered imported students by outcome status and institutional profile fields"},
                *(
                    [{"tool_name": "subset_risk_summary", "summary": "Checked current risk state for the filtered subset"}]
                    if wants_current_risk_count
                    else []
                ),
                *(
                    [{"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for the filtered subset"}]
                    if wants_warning_summary
                    else []
                ),
                *(
                    [{"tool_name": "counsellor_subset_summary", "summary": "Summarized counsellor coverage for the filtered subset"}]
                    if wants_counsellor_summary
                    else []
                ),
            ],
            (
                ["I am showing a condensed subset summary in-chat to keep the response readable"]
                if len(sample_lines) > 6
                else []
            ),
            {
                "kind": "import_coverage",
                "intent": "compound_filtered_subset_summary",
                "student_ids": [int(profile.student_id) for profile in matching_profiles],
                "outcome_status": direct_outcome,
                "branch": branch_filter,
                "category": category_filter,
                "region": region_filter,
                "income": income_filter,
                "role_scope": "admin",
            },
        )
    if direct_outcome is not None:
        matching_profiles = _filter_profiles_for_admin_query(
            profiles=profiles,
            outcome_status=direct_outcome,
            branch=branch_filter,
            category=category_filter,
            region=region_filter,
            income=income_filter,
        )
        fresh_counsellor_filter = role == "counsellor" and (
            lowered_message.startswith("only ") or lowered_message.startswith("show only ")
        )
        if fresh_counsellor_filter:
            selected_branch = next(
                (
                    str(_profile_context_value(profile, "branch") or "").strip()
                    for profile in matching_profiles
                    if str(_profile_context_value(profile, "branch") or "").strip()
                    and str(_profile_context_value(profile, "branch") or "").strip().lower() in lowered_message
                ),
                "",
            )
            selected_year: int | None = None
            if "final year" in lowered_message:
                year_values = [int(_profile_current_year(profile) or 0) for profile in matching_profiles if int(_profile_current_year(profile) or 0) > 0]
                selected_year = max(year_values) if year_values else None
            else:
                year_match = re.search(r"\b([1-9])(?:st|nd|rd|th)\s+year\b", lowered_message)
                if year_match is not None:
                    selected_year = int(year_match.group(1))
            wants_only_high_risk = "only high risk" in lowered_message or "only high-risk" in lowered_message
            wants_low_attendance = "low attendance" in lowered_message
            wants_low_assignments = "low assignments" in lowered_message
            if selected_branch or selected_year is not None or wants_only_high_risk or wants_low_attendance or wants_low_assignments:
                semester_by_student = {
                    int(row.student_id): row
                    for row in repository.get_latest_student_semester_progress_records_for_students(
                        [int(profile.student_id) for profile in matching_profiles]
                    )
                }
                latest_predictions = {
                    int(row.student_id): row for row in repository.get_latest_predictions_for_all_students()
                }
                refined_profiles: list[object] = []
                refined_lines: list[str] = []
                for profile in matching_profiles:
                    student_id = int(profile.student_id)
                    semester_progress = semester_by_student.get(student_id)
                    prediction = latest_predictions.get(student_id)
                    latest_erp_event = _load_student_signal_bundle(repository=repository, student_id=student_id).get("latest_erp_event")
                    submission_rate = (
                        float(getattr(latest_erp_event, "assessment_submission_rate", 0.0) or 0.0)
                        if latest_erp_event is not None
                        else 0.0
                    )
                    matches = True
                    reasons: list[str] = []
                    if selected_branch and str(_profile_context_value(profile, "branch") or "").strip().lower() != selected_branch.lower():
                        matches = False
                    if selected_year is not None and int(_profile_current_year(profile) or 0) != selected_year:
                        matches = False
                    if wants_only_high_risk and not (
                        prediction is not None and int(getattr(prediction, "final_predicted_class", 0) or 0) == 1
                    ):
                        matches = False
                    if wants_low_attendance and not (
                        semester_progress is not None
                        and (
                            float(getattr(semester_progress, "overall_attendance_percent", 0.0) or 0.0) < 75.0
                            or str(getattr(semester_progress, "overall_status", "") or "").strip().upper() != "SAFE"
                        )
                    ):
                        matches = False
                    if wants_low_assignments and not (latest_erp_event is not None and submission_rate < 0.75):
                        matches = False
                    if matches:
                        if selected_branch:
                            reasons.append(f"branch {selected_branch}")
                        if selected_year is not None:
                            reasons.append(f"year {selected_year}")
                        if wants_only_high_risk:
                            reasons.append("prediction HIGH")
                        if wants_low_attendance and semester_progress is not None:
                            reasons.append(f"attendance {float(getattr(semester_progress, 'overall_attendance_percent', 0.0) or 0.0):.1f}%")
                        if wants_low_assignments and latest_erp_event is not None:
                            reasons.append(f"assignment submission rate {submission_rate:.2f}")
                        refined_profiles.append(profile)
                        if len(refined_lines) < 5:
                            refined_lines.append(
                                f"student_id {student_id} ({getattr(profile, 'external_student_ref', None) or 'no ref'}): "
                                + ", ".join(reasons or ["matched the current filter"])
                            )
                filter_parts: list[str] = []
                if selected_branch:
                    filter_parts.append(selected_branch)
                if selected_year is not None:
                    filter_parts.append(f"year {selected_year}")
                if wants_only_high_risk:
                    filter_parts.append("high-risk")
                if wants_low_attendance:
                    filter_parts.append("low-attendance")
                if wants_low_assignments:
                    filter_parts.append("low-assignment")
                filter_label = ", ".join(filter_parts) if filter_parts else "requested subset"
                return (
                    build_grounded_response(
                        opening=f"I refined the same counsellor subset using the `{filter_label}` filter.",
                        key_points=refined_lines or ["No students currently match that exact filter inside the same subset."],
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset already in focus"},
                            {"tool_name": "counsellor_filter_scan", "summary": "Applied a fresh counsellor filter over the remembered subset"},
                        ],
                        limitations=["I am showing up to 5 matching students in-chat to keep the filtered view readable."],
                        closing="If you want, I can next explain these students, rank the most critical ones, or turn this subset into a counsellor action list.",
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset already in focus"},
                        {"tool_name": "counsellor_filter_scan", "summary": "Applied a fresh counsellor filter over the remembered subset"},
                    ],
                    ["I am showing up to 5 matching students in-chat to keep the filtered view readable."],
                    {
                        "kind": "import_coverage",
                        "intent": "counsellor_filtered_subset",
                        "student_ids": [int(profile.student_id) for profile in refined_profiles],
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                    },
                )
        sample_lines = [
            f"{int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'})"
            for profile in matching_profiles[:10]
        ]
        return (
            build_grounded_response(
                opening=(
                    f"I found {len(matching_profiles)} imported students with outcome status "
                    f"`{direct_outcome}`"
                    f"{f' for {filter_summary}' if filter_summary else ''}."
                ),
                key_points=[
                    f"Matching students: {len(matching_profiles)}",
                    *sample_lines,
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin outcome-status request"},
                    {
                        "tool_name": "imported_profile_filter",
                        "summary": (
                            "Filtered imported students by outcome status and institutional profile fields"
                            if has_context_filters
                            else "Filtered imported students by outcome status"
                        ),
                    },
                ],
                limitations=[
                    "I am showing up to 10 sample students in-chat to keep the response readable"
                ],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin outcome-status request"},
                {
                    "tool_name": "imported_profile_filter",
                    "summary": (
                        "Filtered imported students by outcome status and institutional profile fields"
                        if has_context_filters
                        else "Filtered imported students by outcome status"
                    ),
                },
            ],
            ["I am showing up to 10 sample students in-chat to keep the response readable"],
            {
                "kind": "import_coverage",
                "intent": "imported_subset_follow_up",
                "student_ids": [int(profile.student_id) for profile in matching_profiles],
                "outcome_status": direct_outcome,
                "branch": branch_filter,
                "category": category_filter,
                "region": region_filter,
                "income": income_filter,
                "role_scope": "admin",
            },
        )

    if intent == "identity":
        return (
            build_grounded_response(
                opening=f"You are signed in as `{auth.role}` and this chat is operating in institution-scoped admin mode.",
                key_points=[f"Authenticated subject: {auth.subject}"],
                tools_used=[{"tool_name": "identity_scope", "summary": "Returned current authenticated admin scope"}],
                limitations=[],
            ),
            [{"tool_name": "identity_scope", "summary": "Returned current authenticated admin scope"}],
            [],
            {"kind": "identity", "intent": "identity"},
        )

    if intent == "help":
        return (
            build_grounded_response(
                opening="I can currently help with a focused admin question set.",
                key_points=[
                    "imported cohort coverage",
                    "high-risk cohort counts",
                    "governance checks for overdue, unresolved, reopened, and repeated-risk cases",
                    "intervention effectiveness and false-alert feedback",
                    "student drilldowns by student_id",
                ],
                tools_used=[{"tool_name": "admin_copilot_help", "summary": "Returned current admin copilot capabilities"}],
                limitations=["per-counsellor scorecards are still a later hardening phase"],
                closing="Try asking: 'which cases are overdue?', 'any unresolved escalations?', or 'show details for student 880001'.",
            ),
            [{"tool_name": "admin_copilot_help", "summary": "Returned current admin copilot capabilities"}],
            ["CB6 governance summaries are stronger, but per-counsellor scorecards are still a later phase"],
            {"kind": "help", "intent": "help"},
        )

    if intent == "cohort_summary":
        has_entry_word = any(token in lowered for token in {"entered", "enter", "entering"})
        has_entry_qualifier = any(
            token in lowered
            for token in {
                "risk",
                "high risk",
                "high-risk",
                "initial",
                "newly",
                "just entered",
                "recently entered",
            }
        )
        is_dangerous_zone = "dangerous zone" in lowered
        wants_recent_entry = has_entry_word and has_entry_qualifier and not is_dangerous_zone
        window_days = _parse_time_window_days(lowered) if wants_recent_entry else None
        if wants_recent_entry and window_days is not None:
            history_rows = repository.get_all_prediction_history()
            entry_count, sample_ids = _compute_recent_high_risk_entries(
                history_rows=history_rows,
                window_days=window_days,
            )
            return (
                build_grounded_response(
                    opening=f"{entry_count} students newly entered high risk in the last {window_days} days.",
                    key_points=[
                        *(
                            [f"Sample student_ids: {', '.join(str(item) for item in sample_ids)}"]
                            if sample_ids
                            else ["No sample student_ids available for this window."]
                        )
                    ],
                    tools_used=[
                        {"tool_name": "admin_intent_router", "summary": "Routed admin cohort trend request"},
                        {"tool_name": "prediction_history_window", "summary": "Computed new high-risk entries for the requested window"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "admin_intent_router", "summary": "Routed admin cohort trend request"},
                    {"tool_name": "prediction_history_window", "summary": "Computed new high-risk entries for the requested window"},
                ],
                [],
                {
                    "kind": "cohort",
                    "intent": "cohort_recent_entry",
                    "student_ids": sample_ids,
                    "scope": f"recent_entry_{window_days}d",
                },
            )
        if planner.get("user_goal") == "grouped_risk_breakdown":
            return _build_grouped_risk_breakdown_answer(
                scope_label="the institution",
                lowered=lowered,
                planner=planner,
                risk_breakdown=_get_risk_breakdown(),
                prediction_high_risk_count=len(_get_high_risk_rows()),
                overall_shortage_count=_get_attendance_totals()["total_students_with_overall_shortage"],
                i_grade_count=_get_attendance_totals()["total_students_with_i_grade_risk"],
                r_grade_count=_get_attendance_totals()["total_students_with_r_grade_risk"],
                tool_prefix="admin",
            )
        if "high risk" in lowered and any(token in lowered for token in {"semester", "sem", "year"}):
            risk_breakdown = _get_risk_breakdown()
            semester_lines = [
                (
                    f"{item['bucket_label']}: prediction high risk {item['prediction_high_risk']}, "
                    f"overall shortage {item['overall_shortage']}, "
                    f"I-grade {item['i_grade_risk']}, R-grade {item['r_grade_risk']}."
                )
                for item in risk_breakdown["semester_breakdown"][:6]
            ]
            year_lines = [
                (
                    f"{item['bucket_label']}: prediction high risk {item['prediction_high_risk']}, "
                    f"overall shortage {item['overall_shortage']}, "
                    f"I-grade {item['i_grade_risk']}, R-grade {item['r_grade_risk']}."
                )
                for item in risk_breakdown["year_breakdown"][:4]
            ]
            return (
                build_grounded_response(
                    opening=(
                        "I should separate two different things here. "
                        f"`Prediction high risk` currently means {len(_get_high_risk_rows())} students from the risk model, "
                        f"while the attendance-policy layer currently shows {_get_attendance_totals()['total_students_with_i_grade_risk']} students with I-grade risk and "
                        f"{_get_attendance_totals()['total_students_with_r_grade_risk']} with R-grade risk."
                    ),
                    key_points=[
                        "If you mean institution high-risk only from the prediction model, that count is the prediction-high-risk column below.",
                        "If you want attendance-driven academic risk too, use the overall-shortage, I-grade, and R-grade columns below.",
                        "Semester-wise breakdown:",
                        *semester_lines,
                        "Year-wise breakdown:",
                        *year_lines,
                    ],
                    tools_used=[
                        {"tool_name": "admin_intent_router", "summary": "Routed admin high-risk breakdown request with semester/year scope"},
                        {"tool_name": "institution_prediction_and_attendance_breakdown", "summary": "Combined prediction-high-risk counts with semester and year attendance-risk breakdown"},
                    ],
                    limitations=[],
                    closing="If you want, I can next list the exact student IDs under any one semester or year bucket.",
                ),
                [
                    {"tool_name": "admin_intent_router", "summary": "Routed admin high-risk breakdown request with semester/year scope"},
                    {"tool_name": "institution_prediction_and_attendance_breakdown", "summary": "Combined prediction-high-risk counts with semester and year attendance-risk breakdown"},
                ],
                [],
                {"kind": "admin_academic", "intent": "admin_high_risk_semester_year_breakdown"},
            )
        if any(token in lowered for token in {"branch needs attention", "which branch", "attention first"}):
            academic_summary = _get_academic_summary()
            top_branch = academic_summary["branch_pressure"][0] if academic_summary["branch_pressure"] else None
            if top_branch is not None:
                return (
                    build_grounded_response(
                        opening=f"{top_branch['bucket_label']} currently needs attention first based on the current attendance-policy pressure in the uploaded academic data.",
                        key_points=[
                            f"R-grade risk students: {top_branch['students_with_r_grade_risk']}",
                            f"I-grade risk students: {top_branch['students_with_i_grade_risk']}",
                            f"Overall shortage students: {top_branch['students_with_overall_shortage']}",
                            f"Students represented in this branch summary: {top_branch['total_students']}",
                            (
                                f"Average visible overall attendance in this branch is {float(top_branch['average_overall_attendance_percent']):.2f}%."
                                if top_branch["average_overall_attendance_percent"] is not None
                                else "Average visible overall attendance is not available for this branch yet."
                            ),
                        ],
                        tools_used=[
                            {"tool_name": "admin_intent_router", "summary": "Routed admin branch-attention request"},
                            {"tool_name": "institution_academic_scope_summary", "summary": "Ranked branch-level attendance pressure from current academic records"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "admin_intent_router", "summary": "Routed admin branch-attention request"},
                        {"tool_name": "institution_academic_scope_summary", "summary": "Ranked branch-level attendance pressure from current academic records"},
                    ],
                    [],
                    {"kind": "admin_academic", "intent": "admin_branch_attention_summary"},
                )
        if any(token in lowered for token in {"semester", "sem"}) and any(token in lowered for token in {"attention", "pressure", "worst", "highest"}):
            academic_summary = _get_academic_summary()
            top_semester = academic_summary["semester_pressure"][0] if academic_summary["semester_pressure"] else None
            if top_semester is not None:
                return (
                    build_grounded_response(
                        opening=f"{top_semester['bucket_label']} currently needs attention first among the visible semester slices.",
                        key_points=[
                            f"R-grade risk students: {top_semester['students_with_r_grade_risk']}",
                            f"I-grade risk students: {top_semester['students_with_i_grade_risk']}",
                            f"Overall shortage students: {top_semester['students_with_overall_shortage']}",
                            f"Students represented in this semester summary: {top_semester['total_students']}",
                            (
                                f"Average visible overall attendance in this semester slice is {float(top_semester['average_overall_attendance_percent']):.2f}%."
                                if top_semester["average_overall_attendance_percent"] is not None
                                else "Average visible overall attendance is not available for this semester slice yet."
                            ),
                        ],
                        tools_used=[
                            {"tool_name": "admin_intent_router", "summary": "Routed admin semester-attention request"},
                            {"tool_name": "institution_academic_scope_summary", "summary": "Ranked semester-level attendance pressure from current academic records"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "admin_intent_router", "summary": "Routed admin semester-attention request"},
                        {"tool_name": "institution_academic_scope_summary", "summary": "Ranked semester-level attendance pressure from current academic records"},
                    ],
                    [],
                    {"kind": "admin_academic", "intent": "admin_semester_attention_summary"},
                )
        if any(token in lowered for token in {"i grade", "i-grade", "condonation"}):
            academic_summary = _get_academic_summary()
            return (
                build_grounded_response(
                    opening=f"There are currently {academic_summary['total_students_with_i_grade_risk']} students with I-grade attendance risk across the institution.",
                    key_points=[
                        *[
                            f"{item['subject_name']}: {item['i_grade_students']} I-grade students."
                            for item in academic_summary["top_subjects"]
                            if item["i_grade_students"] > 0
                        ][:5],
                    ],
                    tools_used=[
                        {"tool_name": "admin_intent_router", "summary": "Routed admin I-grade institution summary request"},
                        {"tool_name": "institution_academic_scope_summary", "summary": "Summarized institution-wide I-grade exposure"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "admin_intent_router", "summary": "Routed admin I-grade institution summary request"},
                    {"tool_name": "institution_academic_scope_summary", "summary": "Summarized institution-wide I-grade exposure"},
                ],
                [],
                {"kind": "admin_academic", "intent": "admin_i_grade_summary"},
            )
        if any(token in lowered for token in {"r grade", "r-grade", "repeat grade", "repeat subject"}):
            academic_summary = _get_academic_summary()
            return (
                build_grounded_response(
                    opening=f"There are currently {academic_summary['total_students_with_r_grade_risk']} students with R-grade attendance risk across the institution.",
                    key_points=[
                        *[
                            f"{item['subject_name']}: {item['r_grade_students']} R-grade students."
                            for item in academic_summary["top_subjects"]
                            if item["r_grade_students"] > 0
                        ][:5],
                    ],
                    tools_used=[
                        {"tool_name": "admin_intent_router", "summary": "Routed admin R-grade institution summary request"},
                        {"tool_name": "institution_academic_scope_summary", "summary": "Summarized institution-wide R-grade exposure"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "admin_intent_router", "summary": "Routed admin R-grade institution summary request"},
                    {"tool_name": "institution_academic_scope_summary", "summary": "Summarized institution-wide R-grade exposure"},
                ],
                [],
                {"kind": "admin_academic", "intent": "admin_r_grade_summary"},
            )
        if any(token in lowered for token in {"attendance", "subject", "below 75", "policy"}):
            academic_summary = _get_academic_summary()
            return (
                build_grounded_response(
                    opening=(
                        f"These subjects are currently causing the most attendance issues across the institution. "
                        f"Right now, {academic_summary['total_students_with_overall_shortage']} students are below the overall attendance requirement, "
                        f"{academic_summary['total_students_with_i_grade_risk']} have I-grade risk, and {academic_summary['total_students_with_r_grade_risk']} have R-grade risk."
                    ),
                    key_points=[
                        *[
                            f"{item['subject_name']}: {item['students_below_threshold']} students below policy, with {item['r_grade_students']} R-grade and {item['i_grade_students']} I-grade cases."
                            for item in academic_summary["top_subjects"][:5]
                        ],
                        *(
                            [f"Most pressured branch right now: {academic_summary['branch_pressure'][0]['bucket_label']}."]
                            if academic_summary["branch_pressure"]
                            else []
                        ),
                        *(
                            [f"Most pressured semester slice right now: {academic_summary['semester_pressure'][0]['bucket_label']}."]
                            if academic_summary["semester_pressure"]
                            else []
                        ),
                    ],
                    tools_used=[
                        {"tool_name": "admin_intent_router", "summary": "Routed admin institution attendance-pressure request"},
                        {"tool_name": "institution_academic_scope_summary", "summary": "Summarized institution-wide attendance policy pressure and subject hotspots"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "admin_intent_router", "summary": "Routed admin institution attendance-pressure request"},
                    {"tool_name": "institution_academic_scope_summary", "summary": "Summarized institution-wide attendance policy pressure and subject hotspots"},
                ],
                [],
                {"kind": "admin_academic", "intent": "admin_attendance_pressure_summary"},
            )
        return (
            build_grounded_response(
                opening=(
                    f"There are {len(_get_high_risk_rows())} currently high-risk students, "
                    f"{_get_attendance_totals()['total_students_with_i_grade_risk']} students with I-grade attendance risk, and "
                    f"{_get_attendance_totals()['total_students_with_r_grade_risk']} with R-grade attendance risk across the institution."
                ),
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin institution cohort summary intent"},
                    {"tool_name": "institution_academic_scope_summary", "summary": "Added institution-wide attendance policy posture to the cohort summary"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin institution cohort summary intent"},
                {"tool_name": "institution_academic_scope_summary", "summary": "Added institution-wide attendance policy posture to the cohort summary"},
            ],
            [],
            {"kind": "admin_academic", "intent": "cohort_summary"},
        )

    if intent == "import_coverage":
        scored_students = sum(
            1
            for profile in profiles
            if repository.get_latest_prediction_for_student(int(profile.student_id)) is not None
        )
        total_students = len(profiles)
        return (
            build_grounded_response(
                opening=f"Imported cohort coverage: {total_students} imported students, {scored_students} scored, and {max(total_students - scored_students, 0)} unscored.",
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin import coverage intent"},
                    {"tool_name": "import_coverage_summary", "summary": "Computed imported cohort coverage summary"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin import coverage intent"},
                {"tool_name": "import_coverage_summary", "summary": "Computed imported cohort coverage summary"},
            ],
            [],
            {
                "kind": "import_coverage",
                "intent": "import_coverage",
                "student_ids": [int(profile.student_id) for profile in profiles],
            },
        )

    if intent == "admin_governance":
        faculty_summary = get_faculty_summary(db=repository.db, auth=auth)
        priority_queue = get_faculty_priority_queue(db=repository.db, auth=auth)
        intervention_effectiveness = get_intervention_effectiveness_analytics(
            db=repository.db,
            auth=auth,
        )
        governance_answer = _build_admin_governance_answer(
            lowered=lowered,
            interventions=_get_interventions(),
            faculty_summary=faculty_summary,
            priority_queue=priority_queue,
            intervention_effectiveness=intervention_effectiveness,
        )
        if governance_answer is not None:
            return governance_answer
        resolved = sum(
            1 for row in _get_interventions() if str(row.action_status).strip().lower() == "resolved"
        )
        return (
            build_grounded_response(
                opening=f"There are {len(_get_interventions())} logged intervention actions and {resolved} of them are marked resolved.",
                key_points=[
                    "This is an early governance signal",
                    "a full counsellor performance scorecard is still a later phase",
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin governance intent"},
                    {"tool_name": "intervention_summary", "summary": "Summarized intervention activity for admin"},
                ],
                limitations=["full counsellor performance scoring is not built yet"],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin governance intent"},
                {"tool_name": "intervention_summary", "summary": "Summarized intervention activity for admin"},
            ],
            ["CB3 provides only a basic counsellor-duty summary, not a full performance scorecard"],
            {"kind": "admin_governance", "intent": "admin_governance"},
        )

    if intent == "cohort_summary":
        has_entry_word = any(token in lowered for token in {"entered", "enter", "entering"})
        has_entry_qualifier = any(
            token in lowered
            for token in {
                "risk",
                "high risk",
                "high-risk",
                "initial",
                "newly",
                "just entered",
                "recently entered",
            }
        )
        is_dangerous_zone = "dangerous zone" in lowered
        wants_recent_entry = has_entry_word and has_entry_qualifier and not is_dangerous_zone
        window_days = _parse_time_window_days(lowered) if wants_recent_entry else None
        if wants_recent_entry and window_days is None:
            return (
                build_grounded_response(
                    opening="Which time window should I use to calculate newly high-risk entries?",
                    key_points=[
                        "You can say: last 7 days, last 14 days, or last 30 days.",
                        "Example: 'how many students just entered risk in the last 7 days'",
                    ],
                    tools_used=[{"tool_name": "admin_intent_router", "summary": "Routed admin cohort summary intent"}],
                    limitations=["time-window not specified for recent-entry request"],
                ),
                [{"tool_name": "admin_intent_router", "summary": "Routed admin cohort summary intent"}],
                ["time-window not specified for recent-entry request"],
                {"kind": "cohort", "intent": "cohort_summary", "scope": "time_window_missing"},
            )

        if wants_recent_entry and window_days is not None:
            history_rows = repository.get_all_prediction_history()
            entry_count, sample_ids = _compute_recent_high_risk_entries(
                history_rows=history_rows,
                window_days=window_days,
            )
            return (
                build_grounded_response(
                    opening=f"{entry_count} students newly entered high risk in the last {window_days} days.",
                    key_points=[
                        *(
                            [f"Sample student_ids: {', '.join(str(item) for item in sample_ids)}"]
                            if sample_ids
                            else ["No sample student_ids available for this window."]
                        )
                    ],
                    tools_used=[
                        {"tool_name": "admin_intent_router", "summary": "Routed admin cohort summary intent"},
                        {"tool_name": "prediction_history_window", "summary": "Computed new high-risk entries for window"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "admin_intent_router", "summary": "Routed admin cohort summary intent"},
                    {"tool_name": "prediction_history_window", "summary": "Computed new high-risk entries for window"},
                ],
                [],
                {
                    "kind": "cohort",
                    "intent": "cohort_recent_entry",
                    "student_ids": sample_ids,
                    "scope": f"recent_entry_{window_days}d",
                },
            )

        return (
            build_grounded_response(
                opening=f"There are currently {len(_get_high_risk_rows())} students in the latest high-risk cohort and {len(profiles)} imported students in the Vignan-linked profile set.",
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin cohort summary intent"},
                    {"tool_name": "admin_risk_summary", "summary": "Summarized high-risk and imported cohort counts"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin cohort summary intent"},
                {"tool_name": "admin_risk_summary", "summary": "Summarized high-risk and imported cohort counts"},
            ],
            [],
            {
                "kind": "cohort",
                "intent": "cohort_summary",
                "student_ids": [int(row.student_id) for row in _get_high_risk_rows()],
                "scope": "latest_high_risk_predictions",
            },
        )

    student_id = _extract_student_id(lowered) if intent == "student_drilldown" else None
    if intent == "student_drilldown" and student_id is not None:
        profile = repository.get_student_profile(student_id)
        prediction = repository.get_latest_prediction_for_student(student_id)
        if profile is None:
            return (
                f"I could not find a student profile for student_id {student_id}.",
                [{"tool_name": "student_profile_lookup", "summary": "No profile found for requested student"}],
                [],
                {"kind": "student_drilldown", "student_id": student_id, "intent": "student_drilldown"},
            )
        latest_probability = (
            f"{float(prediction.final_risk_probability):.4f}"
            if prediction is not None
            else "not available"
        )
        academic_progress = repository.get_student_academic_progress_record(student_id)
        semester_progress = repository.get_latest_student_semester_progress_record(student_id)
        subject_rows = repository.get_current_student_subject_attendance_records(student_id)
        signal_bundle = _load_student_signal_bundle(repository=repository, student_id=student_id)
        weakest_subject = next(
            (row for row in subject_rows if row.subject_attendance_percent is not None),
            None,
        )
        key_points = [
            f"latest risk probability: {latest_probability}",
        ]
        key_points.extend(
            _build_cross_signal_reasoning_points(
                signal_bundle=signal_bundle,
                current_semester_progress=semester_progress,
                include_availability_gap=True,
                include_reconciliation_notice=False,
                include_stability=False,
            )[:4]
        )
        key_points.extend(
            [
            (
                f"academic position: year {academic_progress.current_year or 'unknown'}, semester {academic_progress.current_semester or 'unknown'}, branch {academic_progress.branch or 'unknown'}"
                if academic_progress is not None
                else "academic position is not available"
            ),
            (
                f"overall attendance: {float(semester_progress.overall_attendance_percent):.2f}% ({semester_progress.overall_status or 'unknown'})"
                if semester_progress is not None and semester_progress.overall_attendance_percent is not None
                else "overall attendance is not available"
            ),
            (
                f"subjects below 75%: {int(semester_progress.subjects_below_75_count or 0)}; subjects below 65%: {int(semester_progress.subjects_below_65_count or 0)}"
                if semester_progress is not None
                else "subject-threshold counts are not available"
            ),
            (
                f"weakest subject: {weakest_subject.subject_name} at {float(weakest_subject.subject_attendance_percent or 0.0):.2f}% ({weakest_subject.subject_status or 'unknown'})"
                if weakest_subject is not None
                else "weakest-subject detail is not available"
            ),
            ]
        )
        key_points.extend(
            [
                f"email: {profile.student_email or 'not available'}",
                f"faculty: {profile.faculty_name or 'not assigned'}",
                f"counsellor: {getattr(profile, 'counsellor_name', None) or 'not assigned'}",
            ]
        )
        return (
            build_grounded_response(
                opening=f"I found a student drilldown for student_id {student_id}.",
                key_points=key_points,
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin student drilldown intent"},
                    {"tool_name": "student_profile_lookup", "summary": "Returned student profile details"},
                    {"tool_name": "latest_prediction_lookup", "summary": "Returned latest student prediction if available"},
                    {"tool_name": "student_cross_signal_reasoning", "summary": "Explained the student drilldown using prediction, LMS, ERP, finance, attendance, and burden signals when available"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin student drilldown intent"},
                {"tool_name": "student_profile_lookup", "summary": "Returned student profile details"},
                {"tool_name": "latest_prediction_lookup", "summary": "Returned latest student prediction if available"},
                {"tool_name": "student_cross_signal_reasoning", "summary": "Explained the student drilldown using prediction, LMS, ERP, finance, attendance, and burden signals when available"},
            ],
            [],
            {"kind": "student_drilldown", "student_id": student_id, "intent": "student_drilldown"},
        )

    return (
        build_grounded_response(
            opening=(
                "I can’t help with that request." if _is_sensitive_request(lowered) else "I didn’t fully match that to an admin intent yet."
            ),
            key_points=(
                ["I cannot share passwords or secrets."]
                if _is_sensitive_request(lowered)
                else [
                    "import coverage",
                    "cohort summaries",
                    "attendance policy pressure, including I-grade and R-grade risk",
                    "branch and subject hotspot summaries",
                    "basic governance summaries",
                    "student drilldowns by student_id",
                    *(
                        [f"Did you mean: {', '.join(_build_intent_suggestions('admin', lowered))}?"]
                        if _build_intent_suggestions("admin", lowered)
                        else []
                    ),
                ]
            ),
            tools_used=[{"tool_name": "admin_intent_router", "summary": f"Routed unsupported admin intent `{intent}`"}],
            limitations=["admin question is outside the current supported governance, attendance-pressure, import, or drilldown set"],
        ),
        [{"tool_name": "admin_intent_router", "summary": f"Routed unsupported admin intent `{intent}`"}],
        ["admin question is outside the current supported governance, attendance-pressure, import, or drilldown set"],
        {"kind": "unsupported", "intent": "unsupported"},
    )


def _extract_student_id(text: str) -> int | None:
    match = re.search(r"\b(88\d{4,})\b", text)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _student_id_from_memory(memory: dict) -> int | None:
    last_context = memory.get("last_context") or {}
    student_id = last_context.get("student_id")
    if isinstance(student_id, int):
        return student_id
    return None


def _maybe_answer_role_follow_up(
    *,
    role: str,
    repository: EventRepository,
    intent: str,
    memory: dict,
    profiles: list[object],
) -> tuple[str, list[dict], list[str], dict] | None:
    last_context = memory.get("last_context") or {}
    last_kind = str(last_context.get("kind") or "")
    requested_outcome = memory.get("requested_outcome_status") or last_context.get("outcome_status")
    window_days = memory.get("window_days")

    if last_kind == "student_drilldown" and memory.get("is_follow_up"):
        student_id = _student_id_from_memory(memory)
        if student_id is None:
            return None
        profile = repository.get_student_profile(student_id)
        prediction = repository.get_latest_prediction_for_student(student_id)
        if profile is None:
            return None
        if memory.get("wants_contact_focus"):
            return (
                build_grounded_response(
                    opening=f"I kept the same student in focus: student_id {student_id}.",
                    key_points=[
                        f"Student email: {profile.student_email or 'not available'}",
                        f"Faculty email: {profile.faculty_email or 'not available'}",
                        f"Counsellor email: {getattr(profile, 'counsellor_email', None) or 'not available'}",
                        f"Parent contact: {profile.parent_email or profile.parent_phone or 'not available'}",
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the last student drilldown context"},
                        {"tool_name": "student_profile_lookup", "summary": "Returned contact details for the same student"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the last student drilldown context"},
                    {"tool_name": "student_profile_lookup", "summary": "Returned contact details for the same student"},
                ],
                [],
                {
                    "kind": "student_drilldown",
                    "student_id": student_id,
                    "intent": "student_drilldown_contact_follow_up",
                    "role_scope": role,
                },
            )
        if memory.get("wants_risk_focus") and prediction is not None:
            return (
                build_grounded_response(
                    opening=f"I kept the same student in focus: student_id {student_id}.",
                    key_points=[
                        f"Final risk probability: {float(prediction.final_risk_probability):.4f}",
                        f"Final predicted class: {int(prediction.final_predicted_class)}",
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the last student drilldown context"},
                        {"tool_name": "latest_prediction_lookup", "summary": "Returned prediction details for the same student"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the last student drilldown context"},
                    {"tool_name": "latest_prediction_lookup", "summary": "Returned prediction details for the same student"},
                ],
                [],
                {
                    "kind": "student_drilldown",
                    "student_id": student_id,
                    "intent": "student_drilldown_risk_follow_up",
                    "role_scope": role,
                },
            )

    if role == "admin" and last_kind == "admin_academic" and memory.get("is_follow_up"):
        lowered_message = str(memory.get("lowered_message") or "")
        if any(token in lowered_message for token in {"why", "explain", "because", "cause", "reason"}):
            latest_predictions = {
                int(row.student_id): row for row in repository.get_latest_predictions_for_all_students()
            }
            progress_rows = repository.get_latest_student_semester_progress_records_for_students(
                [int(profile.student_id) for profile in profiles]
            )
            shortage_count = sum(
                1
                for row in progress_rows
                if str(getattr(row, "overall_status", "") or "").strip().upper() == "SHORTAGE"
            )
            i_grade_count = sum(1 for row in progress_rows if bool(getattr(row, "has_i_grade_risk", False)))
            r_grade_count = sum(1 for row in progress_rows if bool(getattr(row, "has_r_grade_risk", False)))
            return (
                build_grounded_response(
                    opening="Here is the grounded explanation behind the current institution-level priorities.",
                    key_points=[
                        f"Current high-risk students across the institution: {sum(1 for row in latest_predictions.values() if int(getattr(row, 'final_predicted_class', 0) or 0) == 1)}.",
                        f"Current attendance-policy strain: {shortage_count} overall-shortage cases, {i_grade_count} I-grade cases, and {r_grade_count} R-grade cases.",
                        "Main pattern: institution-wide risk is not coming from one isolated metric, but from prediction pressure overlapping with attendance-policy strain and unresolved academic burden.",
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the same admin academic snapshot already in focus"},
                        {"tool_name": "institution_reasoning_summary", "summary": "Explained why the current institution risk posture still needs attention"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the same admin academic snapshot already in focus"},
                    {"tool_name": "institution_reasoning_summary", "summary": "Explained why the current institution risk posture still needs attention"},
                ],
                [],
                {
                    "kind": "import_coverage",
                    "intent": "institution_health_explanation",
                    "role_scope": role,
                    "pending_role_follow_up": "operational_actions",
                    "response_type": "explanation",
                    "last_topic": "institution_health",
                },
            )
        if any(token in lowered_message for token in {"then", "what next", "continue", "more", "ok"}):
            return _answer_admin_operational_actions_fast(
                planner={"normalized_message": "show institutional operational priorities"},
                last_context=last_context,
                risk_breakdown=_build_admin_risk_breakdown(repository=repository, profiles=profiles),
                latest_predictions={int(row.student_id): row for row in repository.get_latest_predictions_for_all_students()},
            )

    if (
        role == "counsellor"
        and last_kind == "cohort"
        and memory.get("is_follow_up")
        and last_context.get("student_ids")
        and (
            str(last_context.get("pending_role_follow_up") or "").strip().lower() == "operational_actions"
            or str(last_context.get("scope") or "").strip().lower() == "counsellor_attention_summary"
            or str(last_context.get("intent") or "").strip().lower()
            in {
                "cohort_summary",
                "counsellor_priority_follow_up",
                "counsellor_subset_reasoning_follow_up",
                "counsellor_subset_priority_follow_up",
                "counsellor_student_trend_split",
            }
        )
    ):
        remembered_ids = {int(value) for value in (last_context.get("student_ids") or [])}
        matching_profiles = [profile for profile in profiles if int(profile.student_id) in remembered_ids]
        if matching_profiles:
            lowered_follow_up = str(memory.get("lowered_message") or "")
            scoped_ids = {int(profile.student_id) for profile in matching_profiles}
            latest_predictions = {
                int(row.student_id): row
                for row in repository.get_latest_predictions_for_students(scoped_ids or None)
            }
            ranked_profiles = sorted(
                matching_profiles,
                key=lambda profile: (
                    -float(getattr(latest_predictions.get(int(profile.student_id)), "final_risk_probability", 0.0) or 0.0),
                    int(profile.student_id),
                ),
            )
            top_subset = ranked_profiles[:3]
            subject_rows = repository.get_current_student_subject_attendance_records_for_students(
                [int(profile.student_id) for profile in matching_profiles]
            )
            subject_pressure: dict[str, int] = {}
            for row in subject_rows:
                status = str(getattr(row, "subject_status", "") or "").strip().upper()
                if status in {"I_GRADE", "R_GRADE"}:
                    subject_name = str(getattr(row, "subject_name", "") or "Unknown")
                    subject_pressure[subject_name] = subject_pressure.get(subject_name, 0) + 1
            top_subject_name = ""
            top_subject_count = 0
            if subject_pressure:
                top_subject_name, top_subject_count = max(subject_pressure.items(), key=lambda item: (item[1], item[0]))
            if any(
                phrase in lowered_follow_up
                for phrase in {
                    "why is that happening",
                    "what is main factor",
                    "what is common issue",
                    "common issue",
                    "main issue",
                    "main problem",
                    "how urgent is it",
                    "what if no action is taken",
                    "what happens if i delay",
                    "what if i ignore low risk",
                    "what if i only focus on top 3",
                    "which student will fail",
                    "who will fail if ignored",
                    "is that enough",
                    "is that okay",
                    "why",
                }
            ):
                opening = "Here is the grounded explanation for the same counsellor subset already in focus."
                if "how urgent" in lowered_follow_up:
                    opening = "Here is the grounded urgency view for the same counsellor subset already in focus."
                elif any(phrase in lowered_follow_up for phrase in {"what if no action is taken", "what happens if i delay", "what if i ignore low risk", "which student will fail", "who will fail if ignored"}):
                    opening = "Here is the grounded consequence view if this counsellor subset is not acted on in time."
                key_points = [
                    f"Subset size still in focus: {len(matching_profiles)}.",
                    "Main pattern: the same students still sit under compounded pressure from current prediction risk, attendance-policy strain, and carry-forward academic burden.",
                ]
                if top_subset:
                    key_points.append(
                        "Highest-pressure students still in focus: "
                        + "; ".join(
                            f"student_id {int(profile.student_id)} at {float(getattr(latest_predictions.get(int(profile.student_id)), 'final_risk_probability', 0.0) or 0.0):.4f}"
                            for profile in top_subset
                        )
                    )
                if top_subject_name:
                    key_points.append(
                        f"Shared hotspot inside this subset: `{top_subject_name}` is currently affecting {top_subject_count} students."
                    )
                if any(phrase in lowered_follow_up for phrase in {"what is common issue", "common issue"}):
                    key_points.append(
                        "Common-issue view: the same students are repeating one shared pressure pattern rather than failing for unrelated reasons."
                    )
                if "what is main factor" in lowered_follow_up:
                    key_points.append(
                        "Main-factor view: the dominant driver here is not attendance alone, but the stacked interaction between visible prediction pressure and unresolved academic strain."
                    )
                if "how urgent" in lowered_follow_up:
                    key_points.append("Urgency view: this subset still needs near-term action, not passive monitoring.")
                if "what if i ignore low risk" in lowered_follow_up:
                    key_points.append("If you ignore the lower-risk students completely, that can be a temporary prioritization choice, but it is not enough on its own because unattended students can still drift upward and join the same pressure queue later.")
                if "what if i only focus on top 3" in lowered_follow_up:
                    key_points.append("Focusing on the top 3 first is a reasonable first move, but it should be treated as the first intervention layer, not the full plan for the entire pressured subset.")
                if any(phrase in lowered_follow_up for phrase in {"what if no action is taken", "what happens if i delay", "what if i ignore low risk", "which student will fail", "who will fail if ignored", "is that okay"}):
                    key_points.append("If no action is taken, the same high-pressure students are more likely to stay stuck in the current risk posture and become harder to recover later.")
                if "is that enough" in lowered_follow_up:
                    key_points.append("That is usually not enough by itself, because the next layer of pressured students still needs monitoring and the shared hotspot still needs active follow-through.")
                return (
                    build_grounded_response(
                        opening=opening,
                        key_points=key_points,
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset from the previous action answer"},
                            {"tool_name": "subset_reasoning_summary", "summary": "Explained the remembered subset using visible risk and attendance pressure"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset from the previous action answer"},
                        {"tool_name": "subset_reasoning_summary", "summary": "Explained the remembered subset using visible risk and attendance pressure"},
                    ],
                    [],
                    {
                        "kind": "cohort",
                        "intent": "counsellor_subset_reasoning_follow_up",
                        "student_ids": [int(profile.student_id) for profile in matching_profiles],
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                        "response_type": "explanation",
                        "last_topic": "counsellor_subset_reasoning_follow_up",
                    },
                )
            if any(
                phrase in lowered_follow_up
                for phrase in {
                    "which student is most critical",
                    "who is most critical",
                    "which students are worst",
                    "who is worst student",
                    "who",
                }
            ):
                sample_lines = [
                    f"student_id {int(profile.student_id)} at {float(getattr(latest_predictions.get(int(profile.student_id)), 'final_risk_probability', 0.0) or 0.0):.4f}"
                    for profile in top_subset
                ]
                return (
                    build_grounded_response(
                        opening="Here are the most critical students inside the same counsellor subset already in focus.",
                        key_points=[f"Subset size: {len(matching_profiles)}", *sample_lines],
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset from the previous action answer"},
                            {"tool_name": "subset_risk_summary", "summary": "Ranked the remembered subset by visible prediction pressure"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset from the previous action answer"},
                        {"tool_name": "subset_risk_summary", "summary": "Ranked the remembered subset by visible prediction pressure"},
                    ],
                    [],
                    {
                        "kind": "cohort",
                        "intent": "counsellor_subset_priority_follow_up",
                        "student_ids": [int(profile.student_id) for profile in matching_profiles],
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                        "response_type": "data",
                        "last_topic": "high_risk_students",
                    },
                )
            if any(
                phrase in lowered_follow_up
                for phrase in {
                    "what should i do first",
                    "what should i do for them",
                    "how to fix it",
                    "how can i fix it",
                    "give solution plan",
                    "give me action plan",
                    "how to prioritize students",
                    "how fast should i act",
                    "what is best strategy",
                    "give weekly plan",
                    "what next",
                    "what else should i do",
                    "continue",
                    "then",
                    "more",
                    "ok",
                }
            ):
                previous_action_stage = int(last_context.get("action_stage") or 1)
                is_second_stage_follow_up = (
                    str(last_context.get("intent") or "").strip().lower() == "counsellor_subset_action_follow_up"
                    and lowered_follow_up in {"continue", "more", "then", "ok"}
                    and previous_action_stage < 2
                )
                is_third_stage_follow_up = (
                    str(last_context.get("intent") or "").strip().lower() == "counsellor_subset_action_follow_up"
                    and lowered_follow_up in {"continue", "more", "then", "ok"}
                    and previous_action_stage >= 2
                )
                opening = "Here is the grounded counsellor action plan for the same subset already in focus."
                if "weekly plan" in lowered_follow_up:
                    opening = "Here is the grounded weekly plan for the same subset already in focus."
                elif "how to prioritize students" in lowered_follow_up:
                    opening = "Here is the grounded prioritization plan for the same subset already in focus."
                elif is_third_stage_follow_up:
                    opening = "Here is the grounded accountability plan for the same counsellor subset already in focus."
                elif is_second_stage_follow_up:
                    opening = "Here is the grounded second-stage counsellor plan for the same subset already in focus."
                key_points = []
                if top_subset:
                    key_points.append("First move these students in order: " + "; ".join(f"student_id {int(profile.student_id)}" for profile in top_subset))
                if top_subject_name:
                    key_points.append(f"Use `{top_subject_name}` as the first shared hotspot for intervention in this subset.")
                key_points.append("Turn each student contact into one concrete blocker-removal step: attendance recovery, coursework catch-up, or burden-clearance follow-up.")
                if "how to prioritize students" in lowered_follow_up or "best strategy" in lowered_follow_up:
                    key_points.append("Prioritize by visible prediction pressure first, then unresolved burden, then shared academic hotspot.")
                if "how fast should i act" in lowered_follow_up:
                    key_points.append("Timing: start this week, because delay lets the same pressure cluster harden around the highest-risk students.")
                if "weekly plan" in lowered_follow_up:
                    key_points.append("Weekly cadence: day 1 identify blockers, day 2-3 clear academic follow-ups, day 4 review burden cases, day 5 re-rank the queue.")
                if is_third_stage_follow_up:
                    key_points = [
                        "Third-stage move: turn the follow-up work into explicit accountability checks instead of repeating intervention steps.",
                        "Track which students cleared the named blocker, which students stalled, and which students need escalation beyond ordinary follow-up.",
                        *(
                            [f"Use `{top_subject_name}` as the checkpoint for whether the shared pressure is actually falling, not just whether messages were sent."]
                            if top_subject_name
                            else []
                        ),
                        "Close the loop by re-ranking the subset again and dropping resolved students out of the active pressure list.",
                    ]
                if is_second_stage_follow_up:
                    key_points = [
                        "Second-stage move: review who actually responded to the first contact and escalate the non-moving cases.",
                        "Do not reuse the same first-step script blindly; switch the slowest-moving students into a tighter follow-up cadence.",
                        *(
                            [f"Use `{top_subject_name}` as the shared checkpoint when measuring whether the subset is improving."]
                            if top_subject_name
                            else []
                        ),
                        "Re-rank the queue after the next review cycle so the next action round reflects movement, not the old snapshot.",
                    ]
                return (
                    build_grounded_response(
                        opening=opening,
                        key_points=key_points,
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset from the previous action answer"},
                            {"tool_name": "subset_action_plan", "summary": "Turned the remembered subset into a grounded counsellor action plan"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset from the previous action answer"},
                        {"tool_name": "subset_action_plan", "summary": "Turned the remembered subset into a grounded counsellor action plan"},
                    ],
                    [],
                    {
                        "kind": "cohort",
                        "intent": "counsellor_subset_action_follow_up",
                        "student_ids": [int(profile.student_id) for profile in matching_profiles],
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                        "response_type": "action",
                        "last_topic": "counsellor_subset_action_follow_up",
                        "action_stage": 3 if is_third_stage_follow_up else (2 if is_second_stage_follow_up else 1),
                    },
                )

    if last_kind == "import_coverage" and memory.get("is_follow_up"):
        if role == "counsellor" and any(
            phrase in str(memory.get("lowered_message") or "")
            for phrase in {
                "which students are high risk",
                "show high risk students",
                "list all risky students",
                "who are in danger",
                "show my assigned students",
                "list my students",
                "who are my students",
                "who all are my students",
                "who are under me",
                "who all are under me",
                "show top 5 risky students",
                "give me most critical students",
                "who are worst performing",
                "how many students are high risk",
                "total risky students count",
                "number of students in danger",
                "what should i do for high risk students",
                "how can i help them",
                "what intervention should i take",
                "how to reduce their risk",
                "what actions are needed",
            }
        ):
            return None
        lowered_message = (
            str(memory.get("lowered_message") or "")
            .replace("’", "'")
            .replace("‘", "'")
        )
        if (
            role == "admin"
            and str(last_context.get("intent") or "").strip().lower() == "admin_operational_actions"
            and not str(last_context.get("grouped_by") or "").strip()
            and not list(last_context.get("bucket_values") or [])
        ):
            latest_predictions = {
                int(row.student_id): row for row in repository.get_latest_predictions_for_all_students()
            }
            progress_rows = repository.get_latest_student_semester_progress_records_for_students(
                [int(profile.student_id) for profile in profiles]
            )
            progress_by_student = {int(row.student_id): row for row in progress_rows}
            subject_rows = repository.get_current_student_subject_attendance_records_for_students(
                [int(profile.student_id) for profile in profiles]
            )
            branch_high_risk_counts: dict[str, int] = {}
            subject_pressure: dict[str, int] = {}
            shortage_count = 0
            i_grade_count = 0
            r_grade_count = 0
            for profile in profiles:
                student_id = int(profile.student_id)
                prediction = latest_predictions.get(student_id)
                if prediction is not None and int(getattr(prediction, "final_predicted_class", 0) or 0) == 1:
                    branch_name = _profile_context_value(profile, "branch") or "Unknown"
                    branch_high_risk_counts[branch_name] = branch_high_risk_counts.get(branch_name, 0) + 1
                progress = progress_by_student.get(student_id)
                if progress is not None:
                    overall_status = str(getattr(progress, "overall_status", "") or "").strip().upper()
                    if overall_status == "SHORTAGE":
                        shortage_count += 1
                    if bool(getattr(progress, "has_i_grade_risk", False)):
                        i_grade_count += 1
                    if bool(getattr(progress, "has_r_grade_risk", False)):
                        r_grade_count += 1
            for row in subject_rows:
                status = str(getattr(row, "subject_status", "") or "").strip().upper()
                if status in {"I_GRADE", "R_GRADE"}:
                    subject_name = str(getattr(row, "subject_name", "") or "Unknown")
                    subject_pressure[subject_name] = subject_pressure.get(subject_name, 0) + 1
            top_branch_name = ""
            top_branch_count = 0
            if branch_high_risk_counts:
                top_branch_name, top_branch_count = max(branch_high_risk_counts.items(), key=lambda item: (item[1], item[0]))
            top_subject_name = ""
            top_subject_count = 0
            if subject_pressure:
                top_subject_name, top_subject_count = max(subject_pressure.items(), key=lambda item: (item[1], item[0]))
            if any(
                phrase in lowered_message
                for phrase in {
                    "why",
                    "why is that happening",
                    "what is main cause",
                    "what is main factor",
                    "what is affecting them",
                    "explain",
                    "risk",
                }
            ):
                return (
                    build_grounded_response(
                        opening="Here is the grounded explanation behind the current institution-level priorities.",
                        key_points=[
                            f"Current high-risk students across the institution: {sum(1 for row in latest_predictions.values() if int(getattr(row, 'final_predicted_class', 0) or 0) == 1)}.",
                            f"Current attendance-policy strain: {shortage_count} overall-shortage cases, {i_grade_count} I-grade cases, and {r_grade_count} R-grade cases.",
                            *(
                                [f"Most pressured branch right now: {top_branch_name} with {top_branch_count} high-risk students."]
                                if top_branch_name
                                else []
                            ),
                            *(
                                [f"Top shared academic hotspot: `{top_subject_name}` is currently affecting {top_subject_count} students."]
                                if top_subject_name
                                else []
                            ),
                            "Main pattern: the current priority queue is being driven by combined prediction pressure, attendance-policy strain, and unresolved academic burden rather than by a single isolated signal.",
                        ],
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the institution-level operational context from the previous admin answer"},
                            {"tool_name": "institution_reasoning_summary", "summary": "Explained the current institution priorities using visible risk, burden, and subject pressure"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the institution-level operational context from the previous admin answer"},
                        {"tool_name": "institution_reasoning_summary", "summary": "Explained the current institution priorities using visible risk, burden, and subject pressure"},
                    ],
                    [],
                    {
                        "kind": "import_coverage",
                        "intent": "institution_health_explanation",
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                    },
                )
            if any(
                phrase in lowered_message
                for phrase in {
                    "what should we do",
                    "what should we fix first",
                    "what actions should we take",
                    "how to fix",
                    "how fast should we act",
                    "how long will it take to improve",
                    "can we reduce risk quickly",
                    "how much improvement is possible",
                    "can we recover in 1 semester",
                    "what is realistic timeline",
                    "give detailed plan",
                    "give strategic plan",
                    "give strategic roadmap",
                    "give full solution plan",
                    "full solution plan",
                    "what next",
                    "then",
                    "continue",
                    "more",
                    "ok",
                }
            ):
                key_points = [
                    "First move: address the most pressured branch and the strongest shared academic hotspot before broad institution-wide expansion.",
                    *(
                        [f"Start with {top_branch_name}, because it currently carries the heaviest visible high-risk concentration."]
                        if top_branch_name
                        else []
                    ),
                    *(
                        [f"Use `{top_subject_name}` as the first academic intervention target because it is the strongest shared hotspot right now."]
                        if top_subject_name
                        else []
                    ),
                    "Operational sequence: stabilize high-risk students, clear unresolved burden cases, then review the next cohort slice in the following cycle.",
                    *(
                        ["Timing: start in the current week; visible institutional improvement should be reviewed after the next academic monitoring cycle rather than expected instantly."]
                        if any(phrase in lowered_message for phrase in {"how fast should we act", "how long will it take to improve"})
                        else []
                    ),
                    *(
                        ["Near-term reduction is possible, but the realistic goal is to shrink concentrated pressure pockets first rather than expecting institution-wide recovery at once."]
                        if "can we reduce risk quickly" in lowered_message
                        else []
                    ),
                    *(
                        ["Improvement potential is strongest in the currently concentrated hotspots because those give the highest return per intervention cycle."]
                        if "how much improvement is possible" in lowered_message
                        else []
                    ),
                    *(
                        ["A one-semester recovery is realistic for the first visible pressure pockets, but full institutional normalization usually needs multiple review cycles."]
                        if any(phrase in lowered_message for phrase in {"can we recover in 1 semester", "what is realistic timeline"})
                        else []
                    ),
                ]
                return (
                    build_grounded_response(
                        opening="Here is the grounded second-stage institution action plan.",
                        key_points=key_points,
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the institution-level operational context from the previous admin answer"},
                            {"tool_name": "institution_action_plan", "summary": "Turned the current institution priorities into a staged admin plan"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the institution-level operational context from the previous admin answer"},
                        {"tool_name": "institution_action_plan", "summary": "Turned the current institution priorities into a staged admin plan"},
                    ],
                    [],
                    {
                        "kind": "import_coverage",
                        "intent": "admin_operational_actions",
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                    },
                )
        if (
            role == "admin"
            and str(last_context.get("intent") or "").strip().lower() == "institution_health_explanation"
            and not str(last_context.get("grouped_by") or "").strip()
            and not list(last_context.get("bucket_values") or [])
        ):
            latest_predictions = {
                int(row.student_id): row for row in repository.get_latest_predictions_for_all_students()
            }
            progress_rows = repository.get_latest_student_semester_progress_records_for_students(
                [int(profile.student_id) for profile in profiles]
            )
            shortage_count = sum(
                1
                for row in progress_rows
                if str(getattr(row, "overall_status", "") or "").strip().upper() == "SHORTAGE"
            )
            i_grade_count = sum(1 for row in progress_rows if bool(getattr(row, "has_i_grade_risk", False)))
            r_grade_count = sum(1 for row in progress_rows if bool(getattr(row, "has_r_grade_risk", False)))
            if any(
                phrase in lowered_message
                for phrase in {
                    "why",
                    "cause",
                    "causes",
                    "happening",
                    "main factor",
                    "main cause",
                    "explain",
                }
            ):
                return (
                    build_grounded_response(
                        opening="Here is the grounded institution-health explanation for the same issue already in focus.",
                        key_points=[
                            f"Current high-risk students across the institution: {sum(1 for row in latest_predictions.values() if int(getattr(row, 'final_predicted_class', 0) or 0) == 1)}.",
                            f"Attendance-policy strain visible alongside that: {shortage_count} overall-shortage cases, {i_grade_count} I-grade cases, and {r_grade_count} R-grade cases.",
                            "Main pattern: the institution still has overlapping prediction pressure and policy strain, which is why the same hidden-risk concern remains operationally important.",
                        ],
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the same institution-health topic already in focus"},
                            {"tool_name": "institution_reasoning_summary", "summary": "Explained the same institution-health issue without resetting the conversation"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the same institution-health topic already in focus"},
                        {"tool_name": "institution_reasoning_summary", "summary": "Explained the same institution-health issue without resetting the conversation"},
                    ],
                    [],
                    {
                        "kind": "import_coverage",
                        "intent": "institution_health_explanation",
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                    },
                )
            if any(
                phrase in lowered_message
                for phrase in {
                    "what should we do",
                    "how to fix",
                    "full solution plan",
                    "give full solution plan",
                    "solution plan",
                    "strategic plan",
                    "strategic roadmap",
                    "what next",
                    "then",
                    "continue",
                    "more",
                    "ok",
                }
            ):
                return (
                    build_grounded_response(
                        opening="Here is the grounded institution action plan for the same health issue already in focus.",
                        key_points=[
                            "First move: target the visible hidden-risk pockets before broadening the plan to the whole institution.",
                            "Operational move: stabilize the highest-pressure branch, clear unresolved burden-heavy cases, then review the next institutional slice in the following cycle.",
                            "This should be handled as staged recovery work, not as a one-shot intervention.",
                        ],
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the same institution-health topic already in focus"},
                            {"tool_name": "institution_action_plan", "summary": "Turned the same institution-health issue into a follow-up action plan"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the same institution-health topic already in focus"},
                        {"tool_name": "institution_action_plan", "summary": "Turned the same institution-health issue into a follow-up action plan"},
                    ],
                    [],
                    {
                        "kind": "import_coverage",
                        "intent": "admin_operational_actions",
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                    },
                )
        if role == "admin" and str(last_context.get("intent") or "").strip().lower() == "imported_subset_risk_follow_up":
            matching_profiles = _resolve_memory_subset_profiles(
                profiles=profiles,
                last_context=last_context,
                requested_outcome=requested_outcome,
            )
            if matching_profiles:
                latest_predictions = {
                    int(row.student_id): row for row in repository.get_latest_predictions_for_all_students()
                }
                subset_high_risk_count = sum(
                    1
                    for profile in matching_profiles
                    if int(getattr(latest_predictions.get(int(profile.student_id)), "final_predicted_class", 0) or 0) == 1
                )
                if any(phrase in lowered_message for phrase in {"why", "explain", "more"}):
                    return (
                        build_grounded_response(
                            opening="Here is the grounded explanation for the same institution subset already in focus.",
                            key_points=[
                                f"Matching students still in focus: {len(matching_profiles)}.",
                                f"Current high-risk students inside this subset: {subset_high_risk_count}.",
                                "Main pattern: this subset still carries visible prediction pressure, so it stays relevant for institutional action instead of being just a background statistic.",
                            ],
                            tools_used=[
                                {"tool_name": "conversation_memory", "summary": "Reused the same institution subset from the previous risk answer"},
                                {"tool_name": "subset_reasoning_summary", "summary": "Explained why the remembered institution subset still matters"},
                            ],
                            limitations=[],
                        ),
                        [
                            {"tool_name": "conversation_memory", "summary": "Reused the same institution subset from the previous risk answer"},
                            {"tool_name": "subset_reasoning_summary", "summary": "Explained why the remembered institution subset still matters"},
                        ],
                        [],
                        {
                            "kind": "import_coverage",
                            "intent": "admin_subset_reasoning_follow_up",
                            "student_ids": [int(profile.student_id) for profile in matching_profiles],
                            "role_scope": role,
                            "pending_role_follow_up": "operational_actions",
                        },
                    )
                if any(phrase in lowered_message for phrase in {"then", "what next", "continue", "ok"}):
                    return (
                        build_grounded_response(
                            opening="Here is the grounded next-step institution action list for the same subset already in focus.",
                            key_points=[
                                f"Keep this subset in focus first because it still contains {subset_high_risk_count} currently high-risk students.",
                                "Operational move: review the strongest pressure cases, clear burden-heavy cases, then re-rank the same subset after the next monitoring cycle.",
                            ],
                            tools_used=[
                                {"tool_name": "conversation_memory", "summary": "Reused the same institution subset from the previous risk answer"},
                                {"tool_name": "subset_action_plan", "summary": "Converted the remembered risk subset into a next-step admin plan"},
                            ],
                            limitations=[],
                        ),
                        [
                            {"tool_name": "conversation_memory", "summary": "Reused the same institution subset from the previous risk answer"},
                            {"tool_name": "subset_action_plan", "summary": "Converted the remembered risk subset into a next-step admin plan"},
                        ],
                        [],
                        {
                            "kind": "import_coverage",
                            "intent": "admin_subset_action_follow_up",
                            "student_ids": [int(profile.student_id) for profile in matching_profiles],
                            "role_scope": role,
                            "pending_role_follow_up": "operational_actions",
                        },
                    )
        matching_profiles = _resolve_memory_subset_profiles(
            profiles=profiles,
            last_context=last_context,
            requested_outcome=requested_outcome,
        )
        if not matching_profiles:
            return None
        grouped_by = str(last_context.get("grouped_by") or "").strip()
        bucket_values = [
            str(value).strip()
            for value in (last_context.get("bucket_values") or [])
            if str(value).strip()
        ]
        requested_bucket_values, excluded_bucket_values = _parse_group_bucket_edit(
            lowered=lowered_message,
            bucket_values=bucket_values,
        )
        if grouped_by == "year" and not requested_bucket_values and bucket_values:
            if any(token in lowered_message for token in {"1st year", "first year"}):
                requested_bucket_values = [value for value in bucket_values if value.strip().lower() == "year 1"]
            elif "final year" in lowered_message:
                numeric_years = []
                for value in bucket_values:
                    match = re.search(r"year\s+(\d+)", value.lower())
                    if match is not None:
                        numeric_years.append((int(match.group(1)), value))
                if numeric_years:
                    requested_bucket_values = [max(numeric_years, key=lambda item: item[0])[1]]
            else:
                year_match = re.search(r"\b([1-9])(?:st|nd|rd|th)\s+year\b", lowered_message)
                if year_match is not None:
                    requested_bucket_values = [
                        value
                        for value in bucket_values
                        if value.strip().lower() == f"year {int(year_match.group(1))}"
                    ]
        other_group_mentions = _extract_other_group_mentions(
            lowered=lowered_message,
            profiles=profiles,
            grouped_by=grouped_by,
        )
        ambiguous_counsellor_reference = _extract_ambiguous_counsellor_reference(
            lowered=lowered_message,
            profiles=matching_profiles,
        )
        mixed_bucket_counsellor_reference = _extract_mixed_counsellor_reference(
            lowered=lowered_message,
            profiles=profiles,
        )
        vague_bucket_reference = any(
            token in lowered_message
            for token in {
                "that group",
                "this group",
                "that bucket",
                "this bucket",
                "that one",
                "this one",
                "only those",
                "remove that group",
                "remove that one",
                "not this bucket",
            }
        )
        conflicting_bucket_request = bool(set(value.lower() for value in requested_bucket_values) & set(value.lower() for value in excluded_bucket_values))
        conflicting_metric_request = (
            (memory.get("wants_warning_focus") and memory.get("wants_exclude_warning_subset"))
            or (memory.get("wants_risk_focus") and memory.get("wants_exclude_high_risk_subset"))
        )
        if conflicting_bucket_request:
            return (
                build_grounded_response(
                    opening="I can keep working with the same grouped result, but your bucket instruction conflicts with itself.",
                    key_points=[
                        "You asked me to both keep and exclude the same bucket in one turn.",
                        "Please choose one direction: keep only that bucket, or exclude it from the grouped result.",
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the last grouped cohort context"},
                        {"tool_name": "grouped_bucket_conflict_guard", "summary": "Detected contradictory bucket-edit instructions and asked for clarification"},
                    ],
                    limitations=["conflicting bucket-edit instructions need clarification before I change the grouped cohort"],
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the last grouped cohort context"},
                    {"tool_name": "grouped_bucket_conflict_guard", "summary": "Detected contradictory bucket-edit instructions and asked for clarification"},
                ],
                ["conflicting bucket-edit instructions need clarification before I change the grouped cohort"],
                {
                    "kind": "import_coverage",
                    "intent": "grouped_bucket_conflict_clarification",
                    "student_ids": [int(profile.student_id) for profile in matching_profiles],
                    "grouped_by": grouped_by,
                    "bucket_values": bucket_values,
                    "role_scope": role,
                },
            )
        if conflicting_metric_request:
            return (
                build_grounded_response(
                    opening="I can keep working with the same subset, but your metric instruction conflicts with itself.",
                    key_points=[
                        "You asked me to show a metric and exclude the same slice in one turn.",
                        "Please choose whether you want the metric itself, or whether you want me to remove that slice from the cohort.",
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the last filtered subset context"},
                        {"tool_name": "subset_conflict_guard", "summary": "Detected contradictory metric and exclusion instructions"},
                    ],
                    limitations=["conflicting metric and exclusion instructions need clarification before I continue"],
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the last filtered subset context"},
                    {"tool_name": "subset_conflict_guard", "summary": "Detected contradictory metric and exclusion instructions"},
                ],
                ["conflicting metric and exclusion instructions need clarification before I continue"],
                {
                    "kind": "import_coverage",
                    "intent": "metric_conflict_clarification",
                    "student_ids": [int(profile.student_id) for profile in matching_profiles],
                    "grouped_by": grouped_by,
                    "bucket_values": bucket_values,
                    "role_scope": role,
                },
            )
        if grouped_by and other_group_mentions and not requested_bucket_values and not excluded_bucket_values:
            other_dimensions = ", ".join(
                f"{dimension} ({', '.join(values)})" for dimension, values in other_group_mentions.items()
            )
            return (
                build_grounded_response(
                    opening="I still have the previous grouped result in memory, but your follow-up is switching to a different dimension.",
                    key_points=[
                        f"The current grouped result is by `{grouped_by}`, but I detected: {other_dimensions}.",
                        "Please tell me whether you want me to keep the current grouping, or start a new filter/grouping on the new dimension.",
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the last grouped cohort context"},
                        {"tool_name": "dimension_switch_guard", "summary": "Detected a grouped follow-up that switched dimensions and asked for clarification"},
                    ],
                    limitations=["dimension-switch follow-ups need clarification so I do not silently change the grouping logic"],
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the last grouped cohort context"},
                    {"tool_name": "dimension_switch_guard", "summary": "Detected a grouped follow-up that switched dimensions and asked for clarification"},
                ],
                ["dimension-switch follow-ups need clarification so I do not silently change the grouping logic"],
                {
                    "kind": "import_coverage",
                    "intent": "dimension_switch_clarification",
                    "student_ids": [int(profile.student_id) for profile in matching_profiles],
                    "grouped_by": grouped_by,
                    "bucket_values": bucket_values,
                    "role_scope": role,
                },
            )
        if ambiguous_counsellor_reference is not None and not requested_bucket_values and not excluded_bucket_values:
            return (
                build_grounded_response(
                    opening="I can keep working with the same grouped result, but that reference is ambiguous.",
                    key_points=[
                        f"`{ambiguous_counsellor_reference}` matches a counsellor name in the current subset.",
                        "If you mean the counsellor, say `under counsellor {name}`.",
                        f"If you mean a `{grouped_by}` bucket, name that bucket directly.",
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the last grouped cohort context"},
                        {"tool_name": "ambiguity_guard", "summary": "Detected an ambiguous person-style reference and asked for clarification"},
                    ],
                    limitations=["ambiguous person references need clarification before I filter the grouped cohort"],
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the last grouped cohort context"},
                    {"tool_name": "ambiguity_guard", "summary": "Detected an ambiguous person-style reference and asked for clarification"},
                ],
                ["ambiguous person references need clarification before I filter the grouped cohort"],
                {
                    "kind": "import_coverage",
                    "intent": "ambiguous_reference_clarification",
                    "student_ids": [int(profile.student_id) for profile in matching_profiles],
                    "grouped_by": grouped_by,
                    "bucket_values": bucket_values,
                    "role_scope": role,
                },
            )
        if mixed_bucket_counsellor_reference is not None and (requested_bucket_values or excluded_bucket_values):
            return (
                build_grounded_response(
                    opening="I can keep working with the same grouped result, but your follow-up mixes a bucket name with a person-style reference.",
                    key_points=[
                        f"`{mixed_bucket_counsellor_reference}` looks like a counsellor reference in the current subset.",
                        "If you mean the counsellor, say `under counsellor {name}`.",
                        f"If you only mean the `{grouped_by}` bucket, send just that bucket name or bucket edit.",
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the last grouped cohort context"},
                        {"tool_name": "ambiguity_guard", "summary": "Detected a mixed bucket-plus-counsellor follow-up and asked for clarification"},
                    ],
                    limitations=["mixed bucket and counsellor references need clarification before I filter the grouped cohort"],
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the last grouped cohort context"},
                    {"tool_name": "ambiguity_guard", "summary": "Detected a mixed bucket-plus-counsellor follow-up and asked for clarification"},
                ],
                ["mixed bucket and counsellor references need clarification before I filter the grouped cohort"],
                {
                    "kind": "import_coverage",
                    "intent": "mixed_reference_clarification",
                    "student_ids": [int(profile.student_id) for profile in matching_profiles],
                    "grouped_by": grouped_by,
                    "bucket_values": bucket_values,
                    "role_scope": role,
                },
            )
        if vague_bucket_reference and not requested_bucket_values and not excluded_bucket_values:
            return (
                build_grounded_response(
                    opening="I still have the previous grouped result in memory, but I cannot tell which bucket you mean.",
                    key_points=[
                        f"Current `{grouped_by}` buckets in memory: {', '.join(bucket_values)}.",
                        "Please name the bucket you want me to keep or exclude.",
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the last grouped cohort context"},
                        {"tool_name": "bucket_reference_guard", "summary": "Detected a vague bucket reference and asked for clarification"},
                    ],
                    limitations=["vague bucket references need a named bucket before I can continue"],
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the last grouped cohort context"},
                    {"tool_name": "bucket_reference_guard", "summary": "Detected a vague bucket reference and asked for clarification"},
                ],
                ["vague bucket references need a named bucket before I can continue"],
                {
                    "kind": "import_coverage",
                    "intent": "vague_bucket_clarification",
                    "student_ids": [int(profile.student_id) for profile in matching_profiles],
                    "grouped_by": grouped_by,
                    "bucket_values": bucket_values,
                    "role_scope": role,
                },
            )
        exclude_bucket_requested = bool(excluded_bucket_values)
        selected_bucket_values = list(requested_bucket_values or excluded_bucket_values)
        bucket_selection_label = None
        if requested_bucket_values:
            if len(requested_bucket_values) == 1:
                bucket_selection_label = f"kept only the `{requested_bucket_values[0]}` bucket from the previous grouped result."
            else:
                bucket_selection_label = (
                    "kept only these buckets from the previous grouped result: "
                    + ", ".join(f"`{value}`" for value in requested_bucket_values)
                    + "."
                )
        elif excluded_bucket_values:
            if len(excluded_bucket_values) == 1:
                bucket_selection_label = f"excluded the `{excluded_bucket_values[0]}` bucket from the previous grouped result."
            else:
                bucket_selection_label = (
                    "excluded these buckets from the previous grouped result: "
                    + ", ".join(f"`{value}`" for value in excluded_bucket_values)
                    + "."
                )

        if requested_bucket_values and not exclude_bucket_requested:
            allowed_bucket_values = {value.lower() for value in requested_bucket_values}
            matching_profiles = [
                profile
                for profile in matching_profiles
                if (
                    (_profile_outcome_status(profile) or "").strip().lower() in allowed_bucket_values
                    if grouped_by == "outcome_status"
                    else (
                        any(
                            (re.search(r"year\s+(\d+)", value.lower()) is not None)
                            and int(getattr(profile, "current_year", 0) or 0) == int(re.search(r"year\s+(\d+)", value.lower()).group(1))
                            for value in requested_bucket_values
                        )
                        if grouped_by == "year"
                        else (_profile_context_value(profile, grouped_by) or "").strip().lower() in allowed_bucket_values
                    )
                )
            ]
        if excluded_bucket_values:
            blocked_bucket_values = {value.lower() for value in excluded_bucket_values}
            matching_profiles = [
                profile
                for profile in matching_profiles
                if (
                    (_profile_outcome_status(profile) or "").strip().lower() not in blocked_bucket_values
                    if grouped_by == "outcome_status"
                    else (
                        all(
                            (re.search(r"year\s+(\d+)", value.lower()) is None)
                            or int(getattr(profile, "current_year", 0) or 0) != int(re.search(r"year\s+(\d+)", value.lower()).group(1))
                            for value in excluded_bucket_values
                        )
                        if grouped_by == "year"
                        else (_profile_context_value(profile, grouped_by) or "").strip().lower() not in blocked_bucket_values
                    )
                )
            ]
        summary_tool = None
        if requested_bucket_values or excluded_bucket_values:
            summary_tool = (
                {"tool_name": "grouped_bucket_focus", "summary": "Excluded the requested bucket set from the previous grouped result"}
                if exclude_bucket_requested
                else {"tool_name": "grouped_bucket_focus", "summary": "Focused the previous grouped result on the requested bucket set"}
            )
        if role == "admin" and grouped_by in {"branch", "year"}:
            latest_predictions = {
                int(row.student_id): row for row in repository.get_latest_predictions_for_all_students()
            }
            subset_high_risk_count = sum(
                1
                for profile in matching_profiles
                if (
                    latest_predictions.get(int(profile.student_id)) is not None
                    and int(latest_predictions[int(profile.student_id)].final_predicted_class) == 1
                )
            )
            subset_progress = repository.get_latest_student_semester_progress_records_for_students(
                [int(profile.student_id) for profile in matching_profiles]
            )
            shortage_count = sum(
                1 for row in subset_progress if str(getattr(row, "overall_status", "") or "").strip().upper() not in {"", "SAFE"}
            )
            i_grade_count = sum(1 for row in subset_progress if bool(getattr(row, "has_i_grade_risk", False)))
            r_grade_count = sum(1 for row in subset_progress if bool(getattr(row, "has_r_grade_risk", False)))
            top_subset = sorted(
                matching_profiles,
                key=lambda profile: (
                    -float(getattr(latest_predictions.get(int(profile.student_id)), "final_risk_probability", 0.0) or 0.0),
                    int(profile.student_id),
                ),
            )[:3]
            subject_rows = repository.get_current_student_subject_attendance_records_for_students(
                [int(profile.student_id) for profile in matching_profiles]
            )
            subject_pressure: dict[str, int] = {}
            for row in subject_rows:
                status = str(getattr(row, "subject_status", "") or "").strip().upper()
                if status in {"I_GRADE", "R_GRADE"}:
                    subject_name = str(getattr(row, "subject_name", "") or "Unknown")
                    subject_pressure[subject_name] = subject_pressure.get(subject_name, 0) + 1
            top_subject_name = ""
            top_subject_count = 0
            if subject_pressure:
                top_subject_name, top_subject_count = max(subject_pressure.items(), key=lambda item: (item[1], item[0]))

            compare_target_bucket = ""
            all_bucket_values = list(bucket_values)
            if grouped_by == "branch":
                all_bucket_values = sorted(
                    {
                        str(_profile_context_value(profile, "branch") or "Unknown").strip()
                        for profile in profiles
                        if str(_profile_context_value(profile, "branch") or "").strip()
                    }
                )
            elif grouped_by == "year":
                all_bucket_values = sorted(
                    {
                        f"Year {int(getattr(profile, 'current_year', 0) or 0)}"
                        for profile in profiles
                        if int(getattr(profile, "current_year", 0) or 0) > 0
                    }
                )
            if "compare with " in lowered_message and all_bucket_values:
                base_bucket = selected_bucket_values[0] if selected_bucket_values else (bucket_values[0] if bucket_values else "")
                for bucket_value in all_bucket_values:
                    if bucket_value.lower() in lowered_message and bucket_value.lower() != str(base_bucket).lower():
                        compare_target_bucket = bucket_value
                        break
                if base_bucket and compare_target_bucket:
                    def _bucket_profiles(bucket_value: str) -> list[object]:
                        normalized_bucket = str(bucket_value).strip().lower()
                        if grouped_by == "year":
                            match = re.search(r"year\s+(\d+)", normalized_bucket)
                            if match is None:
                                return []
                            year_value = int(match.group(1))
                            return [
                                profile
                                for profile in profiles
                                if int(getattr(profile, "current_year", 0) or 0) == year_value
                            ]
                        return [
                            profile
                            for profile in profiles
                            if str(_profile_context_value(profile, grouped_by) or "").strip().lower() == normalized_bucket
                        ]

                    base_profiles = _bucket_profiles(base_bucket)
                    target_profiles = _bucket_profiles(compare_target_bucket)

                    def _count_high_risk(rows: list[object]) -> int:
                        return sum(
                            1
                            for profile in rows
                            if int(getattr(latest_predictions.get(int(profile.student_id)), "final_predicted_class", 0) or 0) == 1
                        )

                    return (
                        build_grounded_response(
                            opening=f"Here is the grounded comparison between `{base_bucket}` and `{compare_target_bucket}` inside the same `{grouped_by}` view.",
                            key_points=[
                                f"{base_bucket}: {len(base_profiles)} students, {_count_high_risk(base_profiles)} currently high-risk.",
                                f"{compare_target_bucket}: {len(target_profiles)} students, {_count_high_risk(target_profiles)} currently high-risk.",
                                "You can now ask why one bucket is worse, what the main factor is, or what we should fix first.",
                            ],
                            tools_used=[
                                {"tool_name": "conversation_memory", "summary": "Reused the same grouped admin view already in focus"},
                                {"tool_name": "subset_comparison_summary", "summary": "Compared two remembered admin buckets inside the same grouped dimension"},
                            ],
                            limitations=[],
                        ),
                        [
                            {"tool_name": "conversation_memory", "summary": "Reused the same grouped admin view already in focus"},
                            {"tool_name": "subset_comparison_summary", "summary": "Compared two remembered admin buckets inside the same grouped dimension"},
                        ],
                        [],
                        {
                            "kind": "import_coverage",
                            "intent": "comparison_summary",
                            "student_ids": [int(profile.student_id) for profile in base_profiles + target_profiles],
                            "grouped_by": grouped_by,
                            "bucket_values": [str(base_bucket), str(compare_target_bucket)],
                            "role_scope": role,
                            "pending_role_follow_up": "operational_actions",
                        },
                    )

            if any(
                phrase in lowered_message
                for phrase in {
                    "which branch has highest risk",
                    "which branch is worst",
                    "which branch is worst affected",
                    "what is most critical area",
                }
            ):
                label = (
                    ", ".join(selected_bucket_values)
                    if selected_bucket_values
                    else f"current grouped `{grouped_by}` subset"
                )
                return (
                    build_grounded_response(
                        opening=f"Here is the grounded ranking view for {label}.",
                        key_points=[
                            *([bucket_selection_label] if bucket_selection_label else []),
                            f"Matching students: {len(matching_profiles)}",
                            f"Current prediction high-risk students: {subset_high_risk_count}",
                            f"Attendance-policy strain: {shortage_count} overall-shortage, {i_grade_count} I-grade, {r_grade_count} R-grade.",
                        ],
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the same grouped admin subset already in focus"},
                            {"tool_name": "subset_risk_summary", "summary": "Ranked the current admin subset using visible risk and attendance strain"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the same grouped admin subset already in focus"},
                        {"tool_name": "subset_risk_summary", "summary": "Ranked the current admin subset using visible risk and attendance strain"},
                    ],
                    [],
                    {
                        "kind": "import_coverage",
                        "intent": "admin_subset_priority_follow_up",
                        "student_ids": [int(profile.student_id) for profile in matching_profiles],
                        "grouped_by": grouped_by,
                        "bucket_values": selected_bucket_values or bucket_values,
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                    },
                )
            if any(
                phrase in lowered_message
                for phrase in {
                    "why is that happening",
                    "what is main cause",
                    "what is main factor",
                    "what is affecting them",
                    "why is first year worse",
                    "why",
                    "how urgent is it",
                    "what if we ignore this",
                    "can situation get worse",
                    "what if we do not act",
                    "what if we don't act",
                    "what if we dont act",
                    "what if no action is taken",
                    "what is worst case scenario",
                    "explain",
                }
            ):
                asks_factor_breakdown = any(
                    phrase in lowered_message
                    for phrase in {
                        "what is affecting them",
                        "what is main factor",
                        "what is main cause",
                    }
                )
                opening = "Here is the grounded explanation for the same admin subset already in focus."
                if "how urgent is it" in lowered_message:
                    opening = "Here is the grounded urgency view for the same admin subset already in focus."
                elif asks_factor_breakdown:
                    opening = "Here is the grounded factor breakdown for the same admin subset already in focus."
                elif any(
                    phrase in lowered_message
                    for phrase in {
                        "what if we ignore this",
                        "can situation get worse",
                        "what if we do not act",
                        "what if we don't act",
                        "what if we dont act",
                        "what if no action is taken",
                        "what is worst case scenario",
                    }
                ):
                    opening = "Here is the grounded consequence view if this admin subset is not acted on in time."
                key_points = [
                    *([bucket_selection_label] if bucket_selection_label else []),
                    f"Current prediction high-risk students in this subset: {subset_high_risk_count} out of {len(matching_profiles)}.",
                    f"Attendance-policy strain in this subset: {shortage_count} overall-shortage cases, {i_grade_count} I-grade cases, and {r_grade_count} R-grade cases.",
                    (
                        "Dominant factor view: the subset is being pulled most strongly by overlapping prediction pressure and academic-policy strain, not by one isolated attendance metric."
                        if asks_factor_breakdown
                        else "Main pattern: prediction pressure and academic-policy strain are stacking inside the same subset rather than one isolated metric acting alone."
                    ),
                ]
                if top_subject_name:
                    key_points.append(
                        (
                            f"Strongest shared driver in this subset: `{top_subject_name}` is currently affecting {top_subject_count} students."
                            if asks_factor_breakdown
                            else f"Shared hotspot in this subset: `{top_subject_name}` is currently affecting {top_subject_count} students."
                        )
                    )
                if top_subset:
                    key_points.append(
                        (
                            "Most affected visible sample in this subset: "
                            if asks_factor_breakdown
                            else "Highest-pressure sample in this subset: "
                        )
                        + "; ".join(
                            f"student_id {int(profile.student_id)} at {float(getattr(latest_predictions.get(int(profile.student_id)), 'final_risk_probability', 0.0) or 0.0):.4f}"
                            for profile in top_subset
                        )
                    )
                if "how urgent is it" in lowered_message:
                    key_points.append("Urgency view: this subset should be treated as near-term institutional work, not a backlog item.")
                if any(
                    phrase in lowered_message
                    for phrase in {
                        "what if we ignore this",
                        "can situation get worse",
                        "what if we do not act",
                        "what if we don't act",
                        "what if we dont act",
                        "what if no action is taken",
                        "what is worst case scenario",
                    }
                ):
                    key_points.append("If no action is taken, the same high-pressure students are more likely to remain stuck and become harder to recover later.")
                return (
                    build_grounded_response(
                        opening=opening,
                        key_points=key_points,
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the same grouped admin subset already in focus"},
                            {"tool_name": "subset_reasoning_summary", "summary": "Explained the current admin subset using visible risk and academic strain"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the same grouped admin subset already in focus"},
                        {"tool_name": "subset_reasoning_summary", "summary": "Explained the current admin subset using visible risk and academic strain"},
                    ],
                    [],
                    {
                        "kind": "import_coverage",
                        "intent": "admin_subset_reasoning_follow_up",
                        "student_ids": [int(profile.student_id) for profile in matching_profiles],
                        "grouped_by": grouped_by,
                        "bucket_values": selected_bucket_values or bucket_values,
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                        "response_type": "explanation",
                        "last_topic": "admin_subset_reasoning_follow_up",
                    },
                )
            if any(
                phrase in lowered_message
                for phrase in {
                    "what should we fix first",
                    "what should we do",
                    "how to fix it",
                    "what actions should we take",
                    "can we reduce risk quickly",
                    "how much improvement is possible",
                    "how long will it take to improve",
                    "give detailed plan",
                    "give full solution plan",
                    "give strategic plan",
                    "give strategic roadmap",
                    "how fast should we act",
                    "can we recover in 1 semester",
                    "what is realistic timeline",
                    "which branch needs urgent attention",
                    "where should we focus",
                    "which group needs immediate attention",
                    "which branch should we prioritize",
                    "what next",
                    "then",
                    "continue",
                    "more",
                    "ok",
                }
            ):
                previous_action_stage = int(last_context.get("action_stage") or 1)
                action_stage = previous_action_stage
                if str(last_context.get("intent") or "").strip().lower() == "admin_subset_action_follow_up" and lowered_message in {"continue", "more", "ok", "then"}:
                    action_stage = min(previous_action_stage + 1, 3)
                opening = "Here is the grounded admin action plan for the same subset already in focus."
                if "can we reduce risk quickly" in lowered_message:
                    opening = "Here is the grounded near-term risk-reduction plan for the same admin subset already in focus."
                elif "give detailed plan" in lowered_message:
                    opening = "Here is the grounded detailed admin plan for the same subset already in focus."
                elif action_stage >= 2 and lowered_message in {"continue", "more", "ok", "then"}:
                    opening = "Here is the grounded next-stage admin action plan for the same subset already in focus."
                return (
                    build_grounded_response(
                        opening=opening,
                        key_points=[
                            *([bucket_selection_label] if bucket_selection_label else []),
                            f"Start with this subset first because it currently contains {subset_high_risk_count} high-risk students and {shortage_count} visible attendance-policy cases.",
                            *(
                                [
                                    "First pressure points to tackle: "
                                    + "; ".join(f"student_id {int(profile.student_id)}" for profile in top_subset)
                                ]
                                if top_subset
                                else []
                            ),
                            *(
                                [f"Use `{top_subject_name}` as the first academic hotspot because it is the strongest shared pressure point in this subset."]
                                if top_subject_name
                                else []
                            ),
                            "Operational move: coordinate academic recovery, follow up unresolved burden cases, and re-rank this subset after the next review cycle.",
                            *(
                                ["Quick-win view: immediate reduction comes from stabilizing the highest-pressure students and the strongest shared hotspot before broadening the intervention."]
                                if "can we reduce risk quickly" in lowered_message
                                else []
                            ),
                            *(
                                ["Timing: begin in the current review cycle so the subset does not harden into a longer-running backlog."]
                                if any(phrase in lowered_message for phrase in {"how fast should we act", "how long will it take to improve"})
                                else []
                            ),
                            *(
                                ["A one-semester improvement is realistic for the first visible pressure pockets, but full normalization usually needs more than one review cycle."]
                                if any(phrase in lowered_message for phrase in {"can we recover in 1 semester", "what is realistic timeline"})
                                else []
                            ),
                            *(
                                ["The fastest visible improvement comes from fixing the concentrated hotspot first, then re-ranking the remaining subset in the next cycle."]
                                if "how much improvement is possible" in lowered_message
                                else []
                            ),
                            *(
                                [
                                    "Next-stage plan: after the first intervention pass, shift into close monitoring, hotspot re-checks, and escalation review for any students who do not improve."
                                ]
                                if action_stage >= 2 and lowered_message in {"continue", "more", "ok", "then"}
                                else []
                            ),
                            *(
                                [
                                    "Accountability view: define the next review checkpoint now so the same subset can be re-ranked and narrowed again instead of staying in a static watchlist."
                                ]
                                if action_stage >= 3 and lowered_message in {"continue", "more", "ok", "then"}
                                else []
                            ),
                            *(
                                [
                                    "Detailed plan: 1. stabilize the top high-risk students, 2. intervene on the shared hotspot, 3. clear unresolved burden-heavy cases, 4. review the same subset in the next monitoring cycle."
                                ]
                                if "give detailed plan" in lowered_message
                                else []
                            ),
                        ],
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the same grouped admin subset already in focus"},
                            {"tool_name": "subset_action_plan", "summary": "Turned the current admin subset into a grounded institutional action plan"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the same grouped admin subset already in focus"},
                        {"tool_name": "subset_action_plan", "summary": "Turned the current admin subset into a grounded institutional action plan"},
                    ],
                    [],
                    {
                        "kind": "import_coverage",
                        "intent": "admin_subset_action_follow_up",
                        "student_ids": [int(profile.student_id) for profile in matching_profiles],
                        "grouped_by": grouped_by,
                        "bucket_values": selected_bucket_values or bucket_values,
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                        "response_type": "action",
                        "last_topic": "admin_subset_action_follow_up",
                        "action_stage": action_stage,
                    },
                )
        requested_top_limit = _extract_requested_top_limit(lowered_message)
        if requested_top_limit is not None:
            latest_predictions = {
                int(row.student_id): row for row in repository.get_latest_predictions_for_all_students()
            }
            ranked_profiles = sorted(
                matching_profiles,
                key=lambda profile: (
                    -float(getattr(latest_predictions.get(int(profile.student_id)), "final_risk_probability", 0.0) or 0.0),
                    int(profile.student_id),
                ),
            )
            limited_profiles = ranked_profiles[:requested_top_limit]
            sample_lines = [
                (
                    f"student_id {int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'}): "
                    f"prediction probability {float(getattr(latest_predictions.get(int(profile.student_id)), 'final_risk_probability', 0.0) or 0.0):.4f}"
                    if latest_predictions.get(int(profile.student_id)) is not None
                    else f"student_id {int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'}): no prediction available yet"
                )
                for profile in limited_profiles
            ]
            return (
                build_grounded_response(
                    opening=f"I kept the same subset and reduced it to the top {requested_top_limit} students by current visible prediction risk.",
                    key_points=[
                        *([bucket_selection_label] if bucket_selection_label else []),
                        f"Matching students after the top-{requested_top_limit} cut: {len(limited_profiles)}",
                        *(
                            sample_lines
                            if sample_lines
                            else ["No students remained after applying that top-N cut."]
                        ),
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the last filtered subset context"},
                        *([summary_tool] if summary_tool else []),
                        {"tool_name": "subset_risk_summary", "summary": "Ranked the current subset by visible prediction probability and returned the top-N students"},
                    ],
                    limitations=["I am showing only the requested top-N students in-chat."],
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the last filtered subset context"},
                    *([summary_tool] if summary_tool else []),
                    {"tool_name": "subset_risk_summary", "summary": "Ranked the current subset by visible prediction probability and returned the top-N students"},
                ],
                ["I am showing only the requested top-N students in-chat."],
                {
                    "kind": "import_coverage",
                    "intent": "imported_subset_top_n_follow_up",
                    "student_ids": [int(profile.student_id) for profile in limited_profiles],
                    "outcome_status": requested_outcome or last_context.get("outcome_status"),
                    "grouped_by": grouped_by,
                    "bucket_values": (
                        [value for value in bucket_values if value.lower() not in {item.lower() for item in excluded_bucket_values}]
                        if exclude_bucket_requested
                        else requested_bucket_values if requested_bucket_values else bucket_values
                    ),
                    "role_scope": role,
                    "pending_role_follow_up": str(last_context.get("pending_role_follow_up") or ""),
                },
            )
        subset_edit_requested = any(
            memory.get(flag)
            for flag in (
                "wants_only_high_risk_subset",
                "wants_only_warning_subset",
                "wants_exclude_high_risk_subset",
                "wants_exclude_warning_subset",
                "wants_counsellor_subset",
            )
        )
        if subset_edit_requested:
            conflicting_subset_request = (
                (memory.get("wants_only_high_risk_subset") and memory.get("wants_exclude_high_risk_subset"))
                or (memory.get("wants_only_warning_subset") and memory.get("wants_exclude_warning_subset"))
            )
            if conflicting_subset_request:
                return (
                    build_grounded_response(
                        opening="I can keep working with the same filtered subset, but your last instruction conflicts with itself.",
                        key_points=[
                            "You asked me to both keep and exclude the same slice of students.",
                            "Please choose one direction: keep only that slice, or exclude it from the current subset.",
                        ],
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the last filtered subset context"},
                            {"tool_name": "subset_conflict_guard", "summary": "Detected contradictory subset-edit instructions and asked for clarification"},
                        ],
                        limitations=["conflicting subset-edit instructions need clarification before I narrow the cohort"],
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the last filtered subset context"},
                        {"tool_name": "subset_conflict_guard", "summary": "Detected contradictory subset-edit instructions and asked for clarification"},
                    ],
                    ["conflicting subset-edit instructions need clarification before I narrow the cohort"],
                    {
                        "kind": "import_coverage",
                        "intent": "subset_conflict_clarification",
                        "student_ids": [int(profile.student_id) for profile in matching_profiles],
                        "outcome_status": requested_outcome or last_context.get("outcome_status"),
                        "branch": last_context.get("branch"),
                        "category": last_context.get("category"),
                        "region": last_context.get("region"),
                        "income": last_context.get("income"),
                        "role_scope": role,
                    },
                )
            latest_predictions = {
                int(row.student_id): row for row in repository.get_latest_predictions_for_all_students()
            }
            active_warning_ids = {
                int(profile.student_id)
                for profile in matching_profiles
                if repository.get_active_student_warning_for_student(int(profile.student_id)) is not None
            }

            narrowed_profiles = list(matching_profiles)
            operation_labels: list[str] = []
            tool_summaries: list[dict[str, str]] = [
                {"tool_name": "conversation_memory", "summary": "Reused the last filtered subset context"},
            ]
            intent_parts: list[str] = []

            if requested_bucket_values and not exclude_bucket_requested:
                operation_labels.append((bucket_selection_label or "").rstrip("."))
                tool_summaries.append(
                    {
                        "tool_name": "grouped_bucket_focus",
                        "summary": "Focused the previous grouped result on the requested bucket set",
                    }
                )
                intent_parts.append("bucket_focus")
            if excluded_bucket_values:
                operation_labels.append((bucket_selection_label or "").rstrip("."))
                tool_summaries.append(
                    {
                        "tool_name": "grouped_bucket_focus",
                        "summary": "Excluded the requested bucket set from the previous grouped result",
                    }
                )
                intent_parts.append("bucket_exclude")

            if memory.get("wants_counsellor_subset"):
                requested_counsellor_name = str(memory.get("requested_counsellor_name") or "").strip().lower()
                narrowed_profiles = [
                    profile
                    for profile in narrowed_profiles
                    if requested_counsellor_name
                    and requested_counsellor_name
                    in str(getattr(profile, "counsellor_name", "") or "").strip().lower()
                ]
                counsellor_label = memory.get("requested_counsellor_name") or "the requested counsellor"
                operation_labels.append(f"kept only students under counsellor `{counsellor_label}`")
                tool_summaries.append(
                    {
                        "tool_name": "counsellor_subset_summary",
                        "summary": "Narrowed the previous subset by counsellor assignment",
                    }
                )
                intent_parts.append("counsellor_narrow")

            if memory.get("wants_only_high_risk_subset"):
                narrowed_profiles = [
                    profile
                    for profile in narrowed_profiles
                    if (
                        latest_predictions.get(int(profile.student_id)) is not None
                        and int(latest_predictions[int(profile.student_id)].final_predicted_class) == 1
                    )
                ]
                operation_labels.append("kept only the students currently classified as high risk")
                tool_summaries.append(
                    {
                        "tool_name": "subset_risk_summary",
                        "summary": "Narrowed the previous subset to currently high-risk students",
                    }
                )
                intent_parts.append("high_risk_only")

            if memory.get("wants_only_warning_subset"):
                narrowed_profiles = [
                    profile for profile in narrowed_profiles if int(profile.student_id) in active_warning_ids
                ]
                operation_labels.append("kept only the students who currently have an active warning")
                tool_summaries.append(
                    {
                        "tool_name": "warning_status_summary",
                        "summary": "Narrowed the previous subset to students with active warnings",
                    }
                )
                intent_parts.append("warning_only")

            if memory.get("wants_exclude_high_risk_subset"):
                narrowed_profiles = [
                    profile
                    for profile in narrowed_profiles
                    if (
                        latest_predictions.get(int(profile.student_id)) is None
                        or int(latest_predictions[int(profile.student_id)].final_predicted_class) != 1
                    )
                ]
                operation_labels.append("excluded the students currently classified as high risk")
                tool_summaries.append(
                    {
                        "tool_name": "subset_risk_summary",
                        "summary": "Excluded the currently high-risk students from the previous subset",
                    }
                )
                intent_parts.append("exclude_high_risk")

            if memory.get("wants_exclude_warning_subset"):
                narrowed_profiles = [
                    profile for profile in narrowed_profiles if int(profile.student_id) not in active_warning_ids
                ]
                operation_labels.append("excluded the students with active warnings")
                tool_summaries.append(
                    {
                        "tool_name": "warning_status_summary",
                        "summary": "Excluded the active-warning students from the previous subset",
                    }
                )
                intent_parts.append("exclude_warning")

            sample_lines = [
                f"{int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'})"
                for profile in narrowed_profiles[:10]
            ]
            opening = (
                "I updated the same filtered subset and applied all of the requested narrowing and exclusion steps."
                if len(operation_labels) > 1
                else "I updated the same filtered subset based on your follow-up."
            )
            key_points = [
                *[label[:1].upper() + label[1:] + "." for label in operation_labels],
                f"Matching students: {len(narrowed_profiles)}",
                *(
                    sample_lines
                    if sample_lines
                    else ["No students remained after applying those subset conditions."]
                ),
            ]
            limitations = (
                ["I am showing up to 10 sample students in-chat to keep the response readable"]
                if sample_lines
                else []
            )
            return (
                build_grounded_response(
                    opening=opening,
                    key_points=key_points,
                    tools_used=tool_summaries,
                    limitations=limitations,
                ),
                tool_summaries,
                limitations,
                {
                    "kind": "import_coverage",
                    "intent": "imported_subset_" + "_".join(intent_parts or ["edited_follow_up"]),
                    "student_ids": [int(profile.student_id) for profile in narrowed_profiles],
                    "outcome_status": requested_outcome or last_context.get("outcome_status"),
                    "branch": last_context.get("branch"),
                    "category": last_context.get("category"),
                    "region": last_context.get("region"),
                    "income": last_context.get("income"),
                    "grouped_by": grouped_by,
                    "bucket_values": (
                        [value for value in bucket_values if value.lower() not in {item.lower() for item in excluded_bucket_values}]
                        if excluded_bucket_values
                        else requested_bucket_values if requested_bucket_values else bucket_values
                    ),
                    "role_scope": role,
                    "pending_role_follow_up": str(last_context.get("pending_role_follow_up") or ""),
                },
            )
        if selected_bucket_values and not (
            memory.get("wants_contact_focus")
            or memory.get("wants_warning_focus")
            or memory.get("wants_risk_focus")
        ):
            opening = (
                (bucket_selection_label[:1].upper() + bucket_selection_label[1:])
                if bucket_selection_label
                else "I updated the previous grouped result."
            )
            sample_lines = [
                f"{int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'})"
                for profile in matching_profiles[:10]
            ]
            return (
                build_grounded_response(
                    opening=opening,
                    key_points=[
                        *(
                            [f"focused the previous grouped result on the `{requested_bucket_values[0]}` bucket"]
                            if requested_bucket_values and len(requested_bucket_values) == 1 and not exclude_bucket_requested
                            else []
                        ),
                        f"Matching students: {len(matching_profiles)}",
                        *(
                            sample_lines
                            if sample_lines
                            else ["No students matched that bucket inside the previous grouped result."]
                        ),
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the last grouped cohort context"},
                        summary_tool,
                    ],
                    limitations=(
                        ["I am showing up to 10 sample students in-chat to keep the response readable"]
                        if sample_lines
                        else []
                    ),
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the last grouped cohort context"},
                    summary_tool,
                ],
                (
                    ["I am showing up to 10 sample students in-chat to keep the response readable"]
                    if sample_lines
                    else []
                ),
                {
                    "kind": "import_coverage",
                    "intent": "grouped_bucket_focus_follow_up",
                    "student_ids": [int(profile.student_id) for profile in matching_profiles],
                    "outcome_status": requested_outcome or last_context.get("outcome_status"),
                    "branch": last_context.get("branch"),
                    "category": last_context.get("category"),
                    "region": last_context.get("region"),
                    "income": last_context.get("income"),
                    "grouped_by": grouped_by,
                    "bucket_values": (
                        [value for value in bucket_values if value.lower() not in {item.lower() for item in excluded_bucket_values}]
                        if exclude_bucket_requested
                        else requested_bucket_values
                    ),
                    "role_scope": role,
                    "pending_role_follow_up": str(last_context.get("pending_role_follow_up") or ""),
                },
            )
        if memory.get("wants_contact_focus"):
            sample_lines = _subset_counsellor_lines(matching_profiles, limit=10)
            return (
                build_grounded_response(
                    opening=_cohort_follow_up_opening(
                        requested_outcome=requested_outcome,
                        focus_label="summarized their counsellor coverage",
                    ),
                    key_points=[
                        *([bucket_selection_label] if bucket_selection_label else []),
                        f"Matching students: {len(matching_profiles)}",
                        *sample_lines,
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the last import coverage cohort"},
                        *(
                            [summary_tool]
                            if selected_bucket_values
                            else []
                        ),
                        {"tool_name": "imported_profile_filter", "summary": "Filtered imported students by outcome status"},
                    ],
                    limitations=["I am showing up to 10 sample students in-chat to keep the response readable"],
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the last import coverage cohort"},
                    *(
                        [summary_tool]
                        if selected_bucket_values
                        else []
                    ),
                    {"tool_name": "imported_profile_filter", "summary": "Filtered imported students by outcome status"},
                ],
                ["I am showing up to 10 sample students in-chat to keep the response readable"],
                {
                    "kind": "import_coverage",
                    "intent": "imported_subset_counsellor_follow_up",
                    "student_ids": [int(profile.student_id) for profile in matching_profiles],
                    "outcome_status": requested_outcome,
                    "grouped_by": grouped_by,
                    "bucket_values": (
                        [value for value in bucket_values if value.lower() not in {item.lower() for item in excluded_bucket_values}]
                        if exclude_bucket_requested
                        else requested_bucket_values if requested_bucket_values else bucket_values
                    ),
                    "role_scope": role,
                },
            )
        lowered_follow_up = lowered_message
        if role == "counsellor":
            latest_predictions = {
                int(row.student_id): row for row in repository.get_latest_predictions_for_all_students()
            }
            ranked_profiles = sorted(
                matching_profiles,
                key=lambda profile: (
                    -float(getattr(latest_predictions.get(int(profile.student_id)), "final_risk_probability", 0.0) or 0.0),
                    int(profile.student_id),
                ),
            )
            top_subset = ranked_profiles[:3]
            subject_rows = repository.get_current_student_subject_attendance_records_for_students(
                [int(profile.student_id) for profile in matching_profiles]
            )
            subject_pressure: dict[str, int] = {}
            for row in subject_rows:
                status = str(getattr(row, "subject_status", "") or "").strip().upper()
                if status in {"I_GRADE", "R_GRADE"}:
                    subject_name = str(getattr(row, "subject_name", "") or "Unknown")
                    subject_pressure[subject_name] = subject_pressure.get(subject_name, 0) + 1
            top_subject_name = ""
            top_subject_count = 0
            if subject_pressure:
                top_subject_name, top_subject_count = max(
                    subject_pressure.items(),
                    key=lambda item: (item[1], item[0]),
                )
            subset_high_risk_count = sum(
                1
                for profile in matching_profiles
                if (
                    latest_predictions.get(int(profile.student_id)) is not None
                    and int(getattr(latest_predictions[int(profile.student_id)], "final_predicted_class", 0) or 0) == 1
                )
            )
            if any(
                phrase in lowered_follow_up
                for phrase in {
                    "which student is most critical",
                    "who is most critical",
                    "which students are worst",
                    "who is worst student",
                    "who",
                }
            ):
                sample_lines = [
                    (
                        f"student_id {int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'}): "
                        f"current prediction {float(getattr(latest_predictions.get(int(profile.student_id)), 'final_risk_probability', 0.0) or 0.0):.4f}"
                    )
                    for profile in top_subset
                ]
                return (
                    build_grounded_response(
                        opening="Here are the most critical students inside the same counsellor subset already in focus.",
                        key_points=[
                            f"Subset size: {len(matching_profiles)}",
                            *(
                                sample_lines
                                if sample_lines
                                else ["No students are currently available inside that subset."]
                            ),
                        ],
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset already in focus"},
                            {"tool_name": "subset_risk_summary", "summary": "Ranked the current subset by visible prediction pressure"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset already in focus"},
                        {"tool_name": "subset_risk_summary", "summary": "Ranked the current subset by visible prediction pressure"},
                    ],
                    [],
                    {
                        "kind": "import_coverage",
                        "intent": "counsellor_subset_priority_follow_up",
                        "student_ids": [int(profile.student_id) for profile in matching_profiles],
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                    },
                )
            if any(
                phrase in lowered_follow_up
                for phrase in {
                    "why are they high risk",
                    "why is that happening",
                    "what is common issue",
                    "common issue",
                    "what is the common issue",
                    "what is the main problem",
                    "what is main factor",
                    "how urgent is it",
                    "what if no action is taken",
                    "what happens if i delay",
                    "what if i ignore low risk",
                    "what if i only focus on top 3",
                    "which student will fail",
                    "who will fail if ignored",
                    "is that enough",
                    "is that okay",
                    "why",
                }
            ):
                opening = "Here is the grounded explanation for the same counsellor subset already in focus."
                if "how urgent" in lowered_follow_up:
                    opening = "Here is the grounded urgency view for the same counsellor subset already in focus."
                elif any(phrase in lowered_follow_up for phrase in {"what if no action is taken", "what happens if i delay", "what if i ignore low risk", "which student will fail", "who will fail if ignored"}):
                    opening = "Here is the grounded consequence view if this counsellor subset is not acted on in time."
                key_points = [
                    f"Current high-risk students inside this subset: {subset_high_risk_count} out of {len(matching_profiles)}.",
                ]
                if top_subset:
                    key_points.append(
                        "Top pressure students in the same subset: "
                        + "; ".join(
                            f"student_id {int(profile.student_id)} at {float(getattr(latest_predictions.get(int(profile.student_id)), 'final_risk_probability', 0.0) or 0.0):.4f}"
                            for profile in top_subset
                        )
                    )
                if top_subject_name:
                    key_points.append(
                        f"Common pressure hotspot in this subset: `{top_subject_name}` is currently pulling {top_subject_count} students into visible attendance-policy strain."
                    )
                if any(phrase in lowered_follow_up for phrase in {"what is common issue", "common issue", "what is the common issue"}):
                    key_points.append(
                        "Common-issue view: the shared problem is not one isolated student, but the same pressure pattern repeating across the subset through coursework strain, attendance-policy pressure, and carry-forward burden."
                    )
                if "what is main factor" in lowered_follow_up:
                    key_points.append(
                        "Main-factor view: the strongest driver in this subset is the compounded interaction between prediction pressure and academic strain, not a single isolated attendance metric."
                    )
                key_points.append(
                    "Main pattern: the same subset is under pressure because prediction risk, attendance-policy pressure, and carry-forward academic strain are stacking on the same students rather than one metric acting alone."
                )
                if "how urgent" in lowered_follow_up:
                    key_points.append(
                        "Urgency view: this subset should be treated as near-term work, not a backlog item, because the highest-pressure students are already concentrated at the top of the current queue."
                    )
                if "what if i ignore low risk" in lowered_follow_up:
                    key_points.append(
                        "If you ignore the lower-risk students completely, that can be a temporary prioritization choice, but it is not enough on its own because unattended students can still drift upward and join the same pressure queue later."
                    )
                if "what if i only focus on top 3" in lowered_follow_up:
                    key_points.append(
                        "Focusing on the top 3 first is a sensible starting move, but it should be followed by a second pass across the remaining pressured students so the same hotspot does not refill the queue."
                    )
                if any(phrase in lowered_follow_up for phrase in {"what if no action is taken", "what happens if i delay", "what if i ignore low risk", "which student will fail", "who will fail if ignored", "is that okay"}):
                    key_points.append(
                        "If no action is taken, the same high-pressure students are more likely to stay stuck in the current risk posture and become harder to recover later."
                    )
                if "is that enough" in lowered_follow_up:
                    key_points.append(
                        "That is not usually enough on its own, because the remainder of the subset still needs monitoring and the shared hotspot still needs coordinated follow-up."
                    )
                return (
                    build_grounded_response(
                        opening=opening,
                        key_points=key_points,
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset already in focus"},
                            {"tool_name": "subset_reasoning_summary", "summary": "Explained the current subset using visible prediction pressure and academic strain"},
                        ],
                        limitations=[],
                        closing="If you want, I can next turn this same subset into a counsellor action plan or rank the most critical students again.",
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset already in focus"},
                        {"tool_name": "subset_reasoning_summary", "summary": "Explained the current subset using visible prediction pressure and academic strain"},
                    ],
                    [],
                    {
                        "kind": "import_coverage",
                        "intent": "counsellor_subset_reasoning_follow_up",
                        "student_ids": [int(profile.student_id) for profile in matching_profiles],
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                        "response_type": "explanation",
                        "last_topic": "counsellor_subset_reasoning_follow_up",
                    },
                )
            if any(
                phrase in lowered_follow_up
                for phrase in {
                    "what should i do first",
                    "what should i do for them",
                    "how to fix it",
                    "how can i fix it",
                    "give solution plan",
                    "give me action plan",
                    "how to prioritize students",
                    "how fast should i act",
                    "what is best strategy",
                    "give weekly plan",
                    "then",
                    "what next",
                    "what else should i do",
                    "continue",
                    "more",
                    "ok",
                }
            ):
                previous_action_stage = int(last_context.get("action_stage") or 1)
                is_second_stage_follow_up = (
                    str(last_context.get("intent") or "").strip().lower() == "counsellor_subset_action_follow_up"
                    and lowered_follow_up in {"continue", "more", "then", "ok"}
                    and previous_action_stage < 2
                )
                is_third_stage_follow_up = (
                    str(last_context.get("intent") or "").strip().lower() == "counsellor_subset_action_follow_up"
                    and lowered_follow_up in {"continue", "more", "then", "ok"}
                    and previous_action_stage >= 2
                )
                opening = "Here is the grounded counsellor action plan for the same subset already in focus."
                if "weekly plan" in lowered_follow_up:
                    opening = "Here is the grounded weekly plan for the same subset already in focus."
                elif "how to prioritize students" in lowered_follow_up:
                    opening = "Here is the grounded prioritization plan for the same subset already in focus."
                elif is_third_stage_follow_up:
                    opening = "Here is the grounded accountability plan for the same counsellor subset already in focus."
                elif is_second_stage_follow_up:
                    opening = "Here is the grounded second-stage counsellor plan for the same subset already in focus."
                key_points = []
                if top_subset:
                    key_points.append(
                        "First move the highest-pressure students in this order: "
                        + "; ".join(
                            f"student_id {int(profile.student_id)}"
                            for profile in top_subset
                        )
                    )
                if top_subject_name:
                    key_points.append(
                        f"Use `{top_subject_name}` as the first academic hotspot because it is the strongest shared pressure point in this subset."
                    )
                key_points.append(
                    "Turn each student contact into one concrete blocker-removal step: attendance recovery, coursework catch-up, or burden-clearance follow-up."
                )
                if "weekly plan" in lowered_follow_up:
                    key_points.append(
                        "Weekly cadence: day 1 identify blockers, day 2-3 clear academic follow-ups, day 4 review burden cases, day 5 re-rank the queue."
                    )
                elif "prioritize" in lowered_follow_up or "best strategy" in lowered_follow_up:
                    key_points.append(
                        "Prioritize by current prediction pressure first, then unresolved burden, then shared academic hotspot."
                    )
                elif "how fast should i act" in lowered_follow_up:
                    key_points.append(
                        "Timing: start this week, because waiting lets the same pressure cluster harden around the highest-risk students."
                    )
                if is_third_stage_follow_up:
                    key_points = [
                        "Third-stage move: convert the follow-up work into explicit accountability checks for the same subset.",
                        "Track who cleared the named blocker, who is still stalled, and who needs escalation beyond ordinary follow-up.",
                        *(
                            [f"Keep `{top_subject_name}` as the shared checkpoint for whether the subset is genuinely improving."]
                            if top_subject_name
                            else []
                        ),
                        "Re-rank the same subset again after the next review cycle and remove students who have clearly moved out of the active pressure pattern.",
                    ]
                if is_second_stage_follow_up:
                    key_points = [
                        "Second-stage move: after the first contacts, review who actually responded and who still needs escalation.",
                        "Escalate non-moving cases into a tighter follow-up cadence instead of repeating the same first-contact script.",
                        *(
                            [f"Keep `{top_subject_name}` as the shared checkpoint when reviewing whether the subset is actually improving."]
                            if top_subject_name
                            else []
                        ),
                        "Re-rank the subset after the next review cycle so the queue reflects movement, not just the original pressure snapshot.",
                    ]
                return (
                    build_grounded_response(
                        opening=opening,
                        key_points=key_points,
                        tools_used=[
                            {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset already in focus"},
                            {"tool_name": "subset_action_plan", "summary": "Turned the current subset into a grounded counsellor action plan"},
                        ],
                        limitations=[],
                    ),
                    [
                        {"tool_name": "conversation_memory", "summary": "Reused the same counsellor subset already in focus"},
                        {"tool_name": "subset_action_plan", "summary": "Turned the current subset into a grounded counsellor action plan"},
                    ],
                    [],
                    {
                        "kind": "import_coverage",
                        "intent": "counsellor_subset_action_follow_up",
                        "student_ids": [int(profile.student_id) for profile in matching_profiles],
                        "role_scope": role,
                        "pending_role_follow_up": "operational_actions",
                        "response_type": "action",
                        "last_topic": "counsellor_subset_action_follow_up",
                        "action_stage": 3 if is_third_stage_follow_up else (2 if is_second_stage_follow_up else 1),
                    },
                )
        if memory.get("wants_warning_focus"):
            active_warning_count = sum(
                1
                for profile in matching_profiles
                if repository.get_active_student_warning_for_student(int(profile.student_id)) is not None
            )
            return (
                build_grounded_response(
                    opening=_cohort_follow_up_opening(
                        requested_outcome=requested_outcome,
                        focus_label="checked active warning coverage",
                    ),
                    key_points=[
                        *([bucket_selection_label] if bucket_selection_label else []),
                        f"Matching students: {len(matching_profiles)}",
                        f"Students with an active warning: {active_warning_count}",
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the last import coverage cohort"},
                        *(
                            [summary_tool]
                            if selected_bucket_values
                            else []
                        ),
                        {"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for the current subset"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the last import coverage cohort"},
                    *(
                        [summary_tool]
                        if selected_bucket_values
                        else []
                    ),
                    {"tool_name": "warning_status_summary", "summary": "Checked active warning coverage for the current subset"},
                ],
                [],
                {
                    "kind": "import_coverage",
                    "intent": "imported_subset_warning_follow_up",
                    "student_ids": [int(profile.student_id) for profile in matching_profiles],
                    "outcome_status": requested_outcome,
                    "grouped_by": grouped_by,
                    "bucket_values": (
                        [value for value in bucket_values if value.lower() not in {item.lower() for item in excluded_bucket_values}]
                        if exclude_bucket_requested
                        else requested_bucket_values if requested_bucket_values else bucket_values
                    ),
                    "role_scope": role,
                },
            )
        if memory.get("wants_risk_focus"):
            latest_predictions = {
                int(row.student_id): row for row in repository.get_latest_predictions_for_all_students()
            }
            high_risk_count = sum(
                1
                for profile in matching_profiles
                if (
                    latest_predictions.get(int(profile.student_id)) is not None
                    and int(latest_predictions[int(profile.student_id)].final_predicted_class) == 1
                )
            )
            return (
                build_grounded_response(
                    opening=_cohort_follow_up_opening(
                        requested_outcome=requested_outcome,
                        focus_label="checked their current risk coverage",
                    ),
                    key_points=[
                        *([bucket_selection_label] if bucket_selection_label else []),
                        f"Matching students: {len(matching_profiles)}",
                        f"Students currently classified as high risk: {high_risk_count}",
                    ],
                    tools_used=[
                        {"tool_name": "conversation_memory", "summary": "Reused the last import coverage cohort"},
                        *(
                            [summary_tool]
                            if selected_bucket_values
                            else []
                        ),
                        {"tool_name": "subset_risk_summary", "summary": "Checked current risk state for the current subset"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "conversation_memory", "summary": "Reused the last import coverage cohort"},
                    *(
                        [summary_tool]
                        if selected_bucket_values
                        else []
                    ),
                    {"tool_name": "subset_risk_summary", "summary": "Checked current risk state for the current subset"},
                ],
                [],
                {
                    "kind": "import_coverage",
                    "intent": "imported_subset_risk_follow_up",
                    "student_ids": [int(profile.student_id) for profile in matching_profiles],
                    "outcome_status": requested_outcome,
                    "grouped_by": grouped_by,
                    "bucket_values": (
                        [value for value in bucket_values if value.lower() not in {item.lower() for item in excluded_bucket_values}]
                        if exclude_bucket_requested
                        else requested_bucket_values if requested_bucket_values else bucket_values
                    ),
                    "role_scope": role,
                },
            )
        sample_lines = [
            f"{int(profile.student_id)} ({getattr(profile, 'external_student_ref', None) or 'no ref'})"
            for profile in matching_profiles[:10]
        ]
        return (
            build_grounded_response(
                opening=_cohort_follow_up_opening(
                    requested_outcome=requested_outcome,
                    focus_label="kept the same imported subset in focus",
                ),
                key_points=[
                    f"Matching students: {len(matching_profiles)}",
                    *sample_lines,
                ],
                tools_used=[
                    {"tool_name": "conversation_memory", "summary": "Reused the last import coverage cohort"},
                    {"tool_name": "imported_profile_filter", "summary": "Filtered imported students by outcome status"},
                ],
                limitations=["I am showing up to 10 sample students in-chat to keep the response readable"],
            ),
            [
                {"tool_name": "conversation_memory", "summary": "Reused the last import coverage cohort"},
                {"tool_name": "imported_profile_filter", "summary": "Filtered imported students by outcome status"},
            ],
            ["I am showing up to 10 sample students in-chat to keep the response readable"],
            {
                "kind": "import_coverage",
                "intent": "imported_subset_follow_up",
                "student_ids": [int(profile.student_id) for profile in matching_profiles],
                "outcome_status": requested_outcome,
                "role_scope": role,
            },
        )

    if (
        last_kind == "cohort"
        and memory.get("is_follow_up")
        and str(last_context.get("scope") or "") == "time_window_missing"
        and isinstance(window_days, int)
        and role == "admin"
    ):
        history_rows = repository.get_all_prediction_history()
        entry_count, sample_ids = _compute_recent_high_risk_entries(
            history_rows=history_rows,
            window_days=window_days,
        )
        return (
            build_grounded_response(
                opening=f"{entry_count} students newly entered high risk in the last {window_days} days.",
                key_points=[
                    *(
                        [f"Sample student_ids: {', '.join(str(item) for item in sample_ids)}"]
                        if sample_ids
                        else ["No sample student_ids available for this window."]
                    )
                ],
                tools_used=[
                    {"tool_name": "conversation_memory", "summary": "Reused the pending recent-entry question"},
                    {"tool_name": "prediction_history_window", "summary": "Computed new high-risk entries for window"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "conversation_memory", "summary": "Reused the pending recent-entry question"},
                {"tool_name": "prediction_history_window", "summary": "Computed new high-risk entries for window"},
            ],
            [],
            {
                "kind": "cohort",
                "intent": "cohort_recent_entry",
                "student_ids": sample_ids,
                "scope": f"recent_entry_{window_days}d",
                "role_scope": role,
            },
        )
    return None


def _profile_outcome_status(profile: object) -> str | None:
    profile_context = getattr(profile, "profile_context", None) or {}
    registration = profile_context.get("registration")
    if not isinstance(registration, dict):
        return None
    value = registration.get("final_status")
    if value in (None, ""):
        return None
    return str(value)


def _profile_current_year(profile: object) -> int | None:
    raw_value = getattr(profile, "current_year", None)
    if raw_value not in (None, ""):
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            pass
    profile_context = getattr(profile, "profile_context", None) or {}
    registration = profile_context.get("registration") or {}
    raw_value = registration.get("current_year")
    if raw_value in (None, ""):
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _profile_context_value(profile: object, key: str) -> str | None:
    profile_context = getattr(profile, "profile_context", None) or {}
    if key == "gender":
        value = getattr(profile, "gender", None) or profile_context.get(key)
    elif key == "branch":
        value = getattr(profile, "branch", None) or profile_context.get(key)
    elif key == "age_band":
        value = getattr(profile, "age_band", None) or profile_context.get(key)
    elif key == "program_type":
        value = getattr(profile, "program_type", None) or profile_context.get(key)
    else:
        value = profile_context.get(key)
    if value in (None, ""):
        return None
    return str(value)


def _extract_profile_context_filter(*, lowered: str, profiles: list[object], key: str) -> str | None:
    matches = _extract_profile_context_mentions(
        lowered=lowered,
        profiles=profiles,
        key=key,
    )
    return matches[0] if matches else None


def _ordered_unique_context_values(*, profiles: list[object], key: str) -> list[str]:
    values = {
        str(_profile_context_value(profile, key)).strip()
        for profile in profiles
        if _profile_context_value(profile, key) not in (None, "")
    }
    return sorted(values, key=lambda item: _context_sort_key(key=key, value=item))


def _context_sort_key(*, key: str, value: str) -> tuple[float, str]:
    lowered = value.strip().lower()
    if key == "region":
        preferred = {"urban": 0.0, "rural": 1.0}
        return (preferred.get(lowered, 99.0), lowered)
    if key == "category":
        preferred = {"sc": 0.0, "st": 1.0, "bc": 2.0, "obc": 3.0, "oc": 4.0, "general": 5.0}
        return (preferred.get(lowered, 99.0), lowered)
    if key == "income":
        match = re.search(r"(\d+(?:\.\d+)?)", lowered)
        if match is not None:
            try:
                return (float(match.group(1)), lowered)
            except ValueError:
                pass
    return (99.0, lowered)


def _single_filter_value(planner: dict, key: str) -> str | None:
    values = planner.get("filters", {}).get(key) or []
    return values[0] if len(values) == 1 else None


def _extract_profile_context_mentions(*, lowered: str, profiles: list[object], key: str) -> list[str]:
    known_values = {
        str(value).strip()
        for value in (_profile_context_value(profile, key) for profile in profiles)
        if value not in (None, "")
    }
    matches_with_pos: list[tuple[int, str]] = []
    for value in known_values:
        match = re.search(rf"\b{re.escape(value.lower())}\b", lowered)
        if match is None:
            continue
        matches_with_pos.append((match.start(), value))
    matches_with_pos.sort(key=lambda item: (item[0], len(item[1])))
    return [value for _, value in matches_with_pos]


def _filter_profiles_for_admin_query(
    *,
    profiles: list[object],
    outcome_status: str | None,
    branch: str | None,
    gender: str | None = None,
    age_band: str | None = None,
    batch: str | None = None,
    program_type: str | None = None,
    category: str | None,
    region: str | None,
    income: str | None,
) -> list[object]:
    filtered = list(profiles)
    if outcome_status is not None:
        filtered = [profile for profile in filtered if _profile_outcome_status(profile) == outcome_status]
    if branch is not None:
        filtered = [
            profile for profile in filtered if (_profile_context_value(profile, "branch") or "").strip().lower() == branch.lower()
        ]
    if gender is not None:
        filtered = [
            profile for profile in filtered if (_profile_context_value(profile, "gender") or "").strip().lower() == gender.lower()
        ]
    if age_band is not None:
        filtered = [
            profile for profile in filtered if (_profile_context_value(profile, "age_band") or "").strip().lower() == age_band.lower()
        ]
    if batch is not None:
        filtered = [
            profile for profile in filtered if (_profile_context_value(profile, "batch") or "").strip().lower() == batch.lower()
        ]
    if program_type is not None:
        filtered = [
            profile for profile in filtered if (_profile_context_value(profile, "program_type") or "").strip().lower() == program_type.lower()
        ]
    if category is not None:
        filtered = [
            profile for profile in filtered if (_profile_context_value(profile, "category") or "").strip().lower() == category.lower()
        ]
    if region is not None:
        filtered = [
            profile for profile in filtered if (_profile_context_value(profile, "region") or "").strip().lower() == region.lower()
        ]
    if income is not None:
        filtered = [
            profile for profile in filtered if (_profile_context_value(profile, "income") or "").strip().lower() == income.lower()
        ]
    return filtered


def _build_filter_summary(
    *,
    outcome_status: str | None,
    branch: str | None,
    category: str | None,
    region: str | None,
    income: str | None,
) -> str:
    parts = []
    if outcome_status is not None:
        parts.append(f"outcome status `{outcome_status}`")
    if branch is not None:
        parts.append(f"branch `{branch}`")
    if category is not None:
        parts.append(f"category `{category}`")
    if region is not None:
        parts.append(f"region `{region}`")
    if income is not None:
        parts.append(f"income `{income}`")
    return " and ".join(parts)


def _extract_subset_asks(lowered: str) -> dict[str, bool]:
    return {
        "risk": any(
            token in lowered
            for token in {
                "risk",
                "high risk",
                "high-risk",
                "risky",
                "at risk",
                "current risk",
                "danger zone",
                "dangerous zone",
                "danger cases",
            }
        ),
        "warnings": any(
            token in lowered for token in {"warning", "warnings", "alert", "alerts", "flagged", "flagged students"}
        ),
        "counsellors": any(
            token in lowered
            for token in {
                "counsellor",
                "counsellors",
                "counselor",
                "counselors",
                "mentor",
                "mentors",
                "assigned person",
                "assigned people",
                "mentor list",
            }
        ),
    }


def _looks_like_compound_subset_query(lowered: str) -> bool:
    stripped = lowered.strip()
    return any(token in lowered for token in {" and ", " also ", " along with ", " as well as "}) or stripped.endswith(" and")


def _subset_counsellor_lines(profiles: list[object], limit: int = 5) -> list[str]:
    seen: set[tuple[str, str]] = set()
    entries: list[tuple[str, str]] = []
    for profile in profiles:
        name = str(getattr(profile, "counsellor_name", None) or "not assigned")
        email = str(getattr(profile, "counsellor_email", None) or "no email")
        key = (name, email)
        if key in seen:
            continue
        seen.add(key)
        entries.append((name.lower(), f"Counsellor: {name} / {email}"))
        if len(entries) >= limit:
            break
    return [line for _, line in sorted(entries, key=lambda item: item[0])]


def _bucket_counsellor_lines(bucket_label: str, profiles: list[object], limit: int = 3) -> list[str]:
    lines = _subset_counsellor_lines(profiles, limit=limit)
    if not lines:
        return [f"{bucket_label} Counsellor: not assigned / no email"]
    return [f"{bucket_label} {line}" for line in lines]


def _resolve_memory_subset_profiles(
    *,
    profiles: list[object],
    last_context: dict,
    requested_outcome: str | None,
) -> list[object]:
    subset_ids = last_context.get("student_ids")
    if isinstance(subset_ids, list) and subset_ids:
        id_set = {int(value) for value in subset_ids}
        candidate_profiles = [
            profile for profile in profiles if int(getattr(profile, "student_id")) in id_set
        ]
    else:
        candidate_profiles = _filter_profiles_for_admin_query(
            profiles=profiles,
            outcome_status=requested_outcome or last_context.get("outcome_status"),
            branch=last_context.get("branch"),
            category=last_context.get("category"),
            region=last_context.get("region"),
            income=last_context.get("income"),
        )

    if requested_outcome:
        candidate_profiles = [
            profile
            for profile in candidate_profiles
            if _profile_outcome_status(profile) == requested_outcome
        ]
    return candidate_profiles


def _extract_requested_bucket_values(*, lowered: str, grouped_by: str, bucket_values: list[str]) -> list[str]:
    if not grouped_by or not bucket_values:
        return []
    matches_with_pos: list[tuple[int, str]] = []
    for value in bucket_values:
        match = re.search(rf"\b{re.escape(value.lower())}\b", lowered)
        if match is None:
            continue
        matches_with_pos.append((match.start(), value))
    matches_with_pos.sort(key=lambda item: (item[0], len(item[1])))
    return [value for _, value in matches_with_pos]


def _extract_requested_bucket_value(*, lowered: str, grouped_by: str, bucket_values: list[str]) -> str | None:
    requested_values = _extract_requested_bucket_values(
        lowered=lowered,
        grouped_by=grouped_by,
        bucket_values=bucket_values,
    )
    return requested_values[0] if requested_values else None


def _parse_group_bucket_edit(
    *,
    lowered: str,
    bucket_values: list[str],
) -> tuple[list[str], list[str]]:
    mentioned_values = _extract_requested_bucket_values(
        lowered=lowered,
        grouped_by="grouped_bucket",
        bucket_values=bucket_values,
    )
    if not mentioned_values:
        return [], []

    exclude_match = re.search(r"\b(except|exclude|excluding|without)\b", lowered)
    only_match = re.search(r"\b(only|just)\b", lowered)
    focus_values: list[str] = []
    exclude_values: list[str] = []

    for value in mentioned_values:
        match = re.search(rf"\b{re.escape(value.lower())}\b", lowered)
        if match is None:
            continue
        start = match.start()
        if exclude_match is not None and start > exclude_match.start():
            exclude_values.append(value)
            continue
        if only_match is not None and start > only_match.start():
            focus_values.append(value)
            continue

    if exclude_match is not None and not exclude_values:
        exclude_values = list(mentioned_values)
    if not focus_values and not exclude_values:
        focus_values = list(mentioned_values)
    return focus_values, exclude_values


def _extract_other_group_mentions(
    *,
    lowered: str,
    profiles: list[object],
    grouped_by: str,
) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    for key in ("branch", "gender", "age_band", "batch", "program_type", "category", "region", "income"):
        if key == grouped_by:
            continue
        mentions = _extract_profile_context_mentions(lowered=lowered, profiles=profiles, key=key)
        if mentions:
            results[key] = mentions
    if grouped_by != "outcome_status":
        outcome_mentions = _extract_outcome_mentions(lowered)
        if outcome_mentions:
            results["outcome_status"] = outcome_mentions
    return results


def _extract_ambiguous_counsellor_reference(*, lowered: str, profiles: list[object]) -> str | None:
    if any(token in lowered for token in {"counsellor", "counselor", "mentor", "assigned person"}):
        return None
    bare_only_match = re.search(r"^\s*(?:only|just|except|exclude|without)\s+([a-z][a-z\s\.]+?)\s*$", lowered)
    if bare_only_match is None:
        return None
    candidate = bare_only_match.group(1).strip().lower()
    if not candidate:
        return None
    for profile in profiles:
        counsellor_name = str(getattr(profile, "counsellor_name", "") or "").strip().lower()
        if candidate and candidate in counsellor_name:
            return bare_only_match.group(1).strip()
    return None


def _extract_mixed_counsellor_reference(*, lowered: str, profiles: list[object]) -> str | None:
    if any(token in lowered for token in {"under counsellor", "under counselor"}):
        return None
    ignored_tokens = {"counsellor", "counselor", "dr", "mr", "ms", "mrs"}
    for profile in profiles:
        counsellor_name = str(getattr(profile, "counsellor_name", "") or "").strip()
        if not counsellor_name:
            continue
        lowered_name = counsellor_name.lower()
        if lowered_name in lowered:
            return counsellor_name
        for token in lowered_name.replace(".", " ").split():
            if token in ignored_tokens:
                continue
            if token and re.search(rf"\b{re.escape(token)}\b", lowered):
                return counsellor_name
    return None


def _wants_comparison(lowered: str) -> bool:
    return any(token in lowered for token in {"compare ", "comparison", "versus", " vs ", " vs. "})


def _has_conflicting_metric_request(lowered: str) -> bool:
    return any(
        pair[0] in lowered and pair[1] in lowered
        for pair in {
            ("warning", "not warning"),
            ("warnings", "not warnings"),
            ("warning", "without warning"),
            ("warnings", "without warnings"),
            ("risk", "not risk"),
            ("risk", "without risk"),
            ("counsellor", "not counsellor"),
            ("counsellors", "not counsellors"),
        }
    )


def _profile_matches_group_bucket(*, profile: object, grouped_by: str, bucket_value: str) -> bool:
    if grouped_by == "outcome_status":
        return (_profile_outcome_status(profile) or "").strip().lower() == bucket_value.lower()
    return (_profile_context_value(profile, grouped_by) or "").strip().lower() == bucket_value.lower()


def _cohort_follow_up_opening(*, requested_outcome: str | None, focus_label: str) -> str:
    if requested_outcome:
        return (
            f"I kept the imported cohort filtered to outcome status `{requested_outcome}` and {focus_label}."
        )
    return f"I kept the same imported subset in focus and {focus_label}."


def _resolve_direct_outcome_request(lowered: str) -> str | None:
    outcome_mentions = _extract_outcome_mentions(lowered)
    return outcome_mentions[0] if len(outcome_mentions) == 1 else None


def _extract_outcome_mentions(lowered: str) -> list[str]:
    if "student" not in lowered:
        return []
    mentions: list[str] = []
    if "dropped" in lowered or "dropout" in lowered or "dropouts" in lowered:
        mentions.append("Dropped")
    if "graduated" in lowered or "graduates" in lowered:
        mentions.append("Graduated")
    if "studying" in lowered or "continuing" in lowered:
        mentions.append("Studying")
    return mentions


def _is_sensitive_request(lowered: str) -> bool:
    return any(token in lowered for token in _SENSITIVE_REQUEST_TOKENS)


def _friendly_intent_label(intent: str) -> str:
    return {
        "import_coverage": "import coverage",
        "admin_governance": "governance summaries",
        "cohort_summary": "cohort or risk summaries",
        "student_drilldown": "student drilldown by student_id",
        "student_self_risk": "your latest risk",
        "student_self_warning": "your warning status",
        "student_self_profile": "your profile contact details",
        "student_self_attendance": "your attendance and subject-wise attendance",
        "student_self_subject_risk": "your I-grade, R-grade, or end-sem eligibility status",
        "student_self_plan": "your weekly or short-term focus plan",
        "help": "copilot help",
        "identity": "who am I / role info",
    }.get(intent, intent)


def _build_intent_suggestions(role: str, message: str) -> list[str]:
    suggestions = suggest_copilot_intents(role=role, message=message, limit=3)
    if not suggestions:
        return []
    return [_friendly_intent_label(item["intent"]) for item in suggestions]


def _parse_time_window_days(message: str) -> int | None:
    lowered = message.lower()
    match = re.search(r"\b(\d{1,3})\s*(day|days|d)\b", lowered)
    if match:
        return int(match.group(1))
    if "last week" in lowered or "past week" in lowered:
        return 7
    if "last month" in lowered or "past month" in lowered:
        return 30
    if "last 24 hours" in lowered or "past 24 hours" in lowered or "last day" in lowered:
        return 1
    return None


def _filter_rows_by_window(
    *,
    rows: list[object],
    time_attr: str,
    window_days: int,
) -> list[object]:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=window_days)
    filtered: list[object] = []
    for row in rows:
        event_time = getattr(row, time_attr, None)
        if event_time is None:
            continue
        if getattr(event_time, "tzinfo", None) is None:
            now = datetime.now()
            window_start = now - timedelta(days=window_days)
        if event_time >= window_start:
            filtered.append(row)
    return filtered


def _split_rows_by_consecutive_windows(
    *,
    rows: list[object],
    time_attr: str,
    window_days: int,
) -> tuple[list[object], list[object]]:
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=window_days)
    previous_start = current_start - timedelta(days=window_days)
    current_rows: list[object] = []
    previous_rows: list[object] = []
    for row in rows:
        event_time = getattr(row, time_attr, None)
        if event_time is None:
            continue
        if getattr(event_time, "tzinfo", None) is None:
            now = datetime.now()
            current_start = now - timedelta(days=window_days)
            previous_start = current_start - timedelta(days=window_days)
        if event_time >= current_start:
            current_rows.append(row)
        elif event_time >= previous_start:
            previous_rows.append(row)
    return current_rows, previous_rows


def _trailing_window_specs(*, total_days: int) -> list[tuple[datetime, datetime]]:
    window_count = 4 if total_days >= 120 else 3
    segment_days = max(total_days // window_count, 1)
    now = datetime.now(timezone.utc)
    windows: list[tuple[datetime, datetime]] = []
    for index in range(window_count):
        window_end = now - timedelta(days=segment_days * index)
        window_start = window_end - timedelta(days=segment_days)
        windows.append((window_start, window_end))
    windows.reverse()
    return windows


def _count_rows_in_windows(
    *,
    rows: list[object],
    time_attr: str,
    windows: list[tuple[datetime, datetime]],
    allowed_student_ids: set[int],
) -> list[int]:
    counts = [0 for _ in windows]
    for row in rows:
        event_time = getattr(row, time_attr, None)
        student_id = getattr(row, "student_id", None)
        if event_time is None or student_id is None:
            continue
        student_id_int = int(student_id)
        if student_id_int not in allowed_student_ids:
            continue
        normalized_time = event_time
        normalized_windows = windows
        if getattr(event_time, "tzinfo", None) is None:
            normalized_windows = [
                (window_start.replace(tzinfo=None), window_end.replace(tzinfo=None))
                for window_start, window_end in windows
            ]
        for index, (window_start, window_end) in enumerate(normalized_windows):
            if window_start <= normalized_time < window_end:
                counts[index] += 1
                break
    return counts


def _high_risk_entries_in_windows(
    *,
    history_rows: list[object],
    windows: list[tuple[datetime, datetime]],
) -> list[int]:
    return [
        _compute_recent_high_risk_entries_between(
            history_rows=history_rows,
            window_start=window_start,
            window_end=window_end,
        )[0]
        for window_start, window_end in windows
    ]


def _window_series_summary(*, counts: list[int], subset_count: int, total_days: int) -> tuple[float, str]:
    if not counts:
        return 0.0, "No long-horizon history was available."
    segment_days = max(total_days // len(counts), 1)
    rates = [(count / subset_count * 100.0) if subset_count else 0.0 for count in counts]
    delta = rates[-1] - rates[0]
    parts = [
        f"{segment_days}d window {index + 1}: {count} ({rate:.1f}%)"
        for index, (count, rate) in enumerate(zip(counts, rates, strict=False))
    ]
    return delta, "; ".join(parts)


def _compute_recent_high_risk_entries_between(
    *,
    history_rows: list[object],
    window_start: datetime,
    window_end: datetime,
) -> tuple[int, list[int]]:
    latest_in_window: dict[int, object] = {}
    previous_before_window: dict[int, object] = {}

    for row in history_rows:
        student_id = int(getattr(row, "student_id"))
        created_at = getattr(row, "created_at", None)
        if created_at is None:
            continue
        if getattr(created_at, "tzinfo", None) is None:
            window_start = window_start.replace(tzinfo=None)
            window_end = window_end.replace(tzinfo=None)
        if window_start <= created_at < window_end:
            latest_in_window.setdefault(student_id, row)
        elif created_at < window_start:
            previous_before_window.setdefault(student_id, row)

    newly_high_risk_ids: list[int] = []
    for student_id, latest_row in latest_in_window.items():
        latest_class = int(getattr(latest_row, "final_predicted_class", 0))
        if latest_class != 1:
            continue
        previous_row = previous_before_window.get(student_id)
        if previous_row is None:
            newly_high_risk_ids.append(student_id)
            continue
        previous_class = int(getattr(previous_row, "final_predicted_class", 0))
        if previous_class == 0:
            newly_high_risk_ids.append(student_id)

    return len(newly_high_risk_ids), newly_high_risk_ids[:10]


def _trend_direction(delta: float) -> str:
    if delta > 0.05:
        return "up"
    if delta < -0.05:
        return "down"
    return "flat"


def _compute_recent_high_risk_entries(
    *,
    history_rows: list[object],
    window_days: int,
) -> tuple[int, list[int]]:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=window_days)
    return _compute_recent_high_risk_entries_between(
        history_rows=history_rows,
        window_start=window_start,
        window_end=now,
    )


def _build_attention_rank_rows(comparison_rows: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
    bucket_map: dict[str, dict[str, float]] = {}
    for metric_kind, rows in comparison_rows.items():
        for row in rows:
            value = str(row.get("value") or "").strip()
            if not value:
                continue
            bucket_map.setdefault(value, {})[metric_kind] = float(row.get("rate") or 0.0)

    ranked_rows: list[dict[str, object]] = []
    for value, metrics in bucket_map.items():
        risk_rate = metrics.get("risk", 0.0)
        warning_gap = max(metrics.get("warning_intervention_gap", 0.0), 0.0)
        risk_entry_trend = max(metrics.get("recent_entry_risk_trend", 0.0), 0.0)
        warning_trend = max(metrics.get("warning_trend", 0.0), 0.0)
        high_risk_gap = max(metrics.get("high_risk_intervention_gap", 0.0), 0.0)

        score = (
            (risk_rate * 1.0)
            + (warning_gap * 0.8)
            + (risk_entry_trend * 1.2)
            + (warning_trend * 0.6)
            + (high_risk_gap * 0.9)
        )

        reasons: list[tuple[float, str]] = []
        if risk_rate > 0:
            reasons.append((risk_rate, f"current high-risk rate {risk_rate:.1f}%"))
        if warning_gap > 0:
            reasons.append((warning_gap, f"warning-to-intervention gap {warning_gap:+.1f} points"))
        if risk_entry_trend > 0:
            reasons.append((risk_entry_trend, f"recent risk-entry trend {risk_entry_trend:+.1f} points"))
        if warning_trend > 0:
            reasons.append((warning_trend, f"warning trend {warning_trend:+.1f} points"))
        if high_risk_gap > 0:
            reasons.append((high_risk_gap, f"high-risk students without intervention {high_risk_gap:.1f}%"))
        reasons.sort(key=lambda item: (-item[0], item[1]))
        summary_parts = [
            f"risk {risk_rate:.1f}%",
            f"warning gap {warning_gap:+.1f}",
            f"risk-entry trend {risk_entry_trend:+.1f}",
        ]
        if high_risk_gap > 0:
            summary_parts.append(f"uncovered high-risk {high_risk_gap:.1f}%")
        ranked_rows.append(
            {
                "value": value,
                "score": score,
                "why": ", ".join(reason for _, reason in reasons[:3]) if reasons else "its pressure signals are currently the highest in the comparison set",
                "summary": ", ".join(summary_parts),
            }
        )

    ranked_rows.sort(key=lambda item: (-float(item["score"]), str(item["value"]).lower()))
    return ranked_rows


def _build_diagnostic_rank_rows(comparison_rows: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
    bucket_map: dict[str, dict[str, float]] = {}
    for metric_kind, rows in comparison_rows.items():
        for row in rows:
            value = str(row.get("value") or "").strip()
            if not value:
                continue
            bucket_map.setdefault(value, {})[metric_kind] = float(row.get("rate") or 0.0)

    ranked_rows: list[dict[str, object]] = []
    for value, metrics in bucket_map.items():
        unresolved_burden = metrics.get("unresolved_risk_burden", 0.0)
        risk_rate = metrics.get("risk", 0.0)
        warning_gap = max(metrics.get("warning_intervention_gap", 0.0), 0.0)
        high_risk_gap = max(metrics.get("high_risk_intervention_gap", 0.0), 0.0)
        risk_entry_trend = max(metrics.get("recent_entry_risk_trend", 0.0), 0.0)
        warning_rate = metrics.get("warnings", 0.0)
        intervention_coverage = metrics.get("intervention_coverage", 0.0)

        score = (
            (unresolved_burden * 1.2)
            + (risk_rate * 0.9)
            + (warning_gap * 1.0)
            + (high_risk_gap * 1.1)
            + (risk_entry_trend * 1.0)
        )

        reasons: list[tuple[float, str]] = []
        if unresolved_burden > 0:
            reasons.append((unresolved_burden, f"unresolved risk burden {unresolved_burden:.1f}"))
        if high_risk_gap > 0:
            reasons.append((high_risk_gap, f"high-risk students without intervention {high_risk_gap:.1f}%"))
        if warning_gap > 0:
            reasons.append((warning_gap, f"warning-to-intervention gap {warning_gap:+.1f} points"))
        if risk_entry_trend > 0:
            reasons.append((risk_entry_trend, f"recent risk-entry trend {risk_entry_trend:+.1f} points"))
        if risk_rate > 0:
            reasons.append((risk_rate, f"current high-risk rate {risk_rate:.1f}%"))
        reasons.sort(key=lambda item: (-item[0], item[1]))

        driver = reasons[0][1] if reasons else "its grounded retention pressure is currently the highest in the comparison set"
        summary_parts = [
            f"unresolved burden {unresolved_burden:.1f}",
            f"risk {risk_rate:.1f}%",
            f"warning gap {warning_gap:+.1f}",
            f"intervention coverage {intervention_coverage:.1f}%",
        ]
        if warning_rate > 0:
            summary_parts.append(f"warnings {warning_rate:.1f}%")
        if risk_entry_trend > 0:
            summary_parts.append(f"risk-entry trend {risk_entry_trend:+.1f}")
        ranked_rows.append(
            {
                "value": value,
                "score": score,
                "driver": driver,
                "why": ", ".join(reason for _, reason in reasons[:3]) if reasons else driver,
                "summary": ", ".join(summary_parts),
            }
        )

    ranked_rows.sort(key=lambda item: (-float(item["score"]), str(item["value"]).lower()))
    return ranked_rows


def _build_admin_governance_answer(
    *,
    lowered: str,
    interventions: list[object],
    faculty_summary,
    priority_queue,
    intervention_effectiveness,
) -> tuple[str, list[dict], list[str], dict] | None:
    if any(token in lowered for token in {"overdue", "follow-up", "followup", "reminder", "critical unattended"}):
        top_cases = faculty_summary.critical_unattended_case_students[:5]
        return (
            build_grounded_response(
                opening=(
                    f"There are {faculty_summary.total_critical_unattended_cases} critical unattended cases "
                    f"and {faculty_summary.total_followup_reminders_sent} follow-up reminders sent."
                ),
                key_points=[
                    *[
                        f"student_id {item.student_id}: {item.note or 'Follow-up reminder already sent and still awaiting action.'}"
                        for item in top_cases
                    ],
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin overdue follow-up intent"},
                    {"tool_name": "faculty_summary", "summary": "Returned faculty summary follow-up signals"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin overdue follow-up intent"},
                {"tool_name": "faculty_summary", "summary": "Returned faculty summary follow-up signals"},
            ],
            [],
            {
                "kind": "admin_governance",
                "intent": "admin_overdue_followup_summary",
                "student_ids": [int(item.student_id) for item in top_cases],
            },
        )

    if any(token in lowered for token in {"unresolved", "unhandled", "escalation"}):
        top_cases = faculty_summary.unhandled_escalation_students[:5]
        return (
            build_grounded_response(
                opening=(
                    f"There are {faculty_summary.total_unhandled_escalations} unhandled escalations and "
                    f"{faculty_summary.total_escalated_cases} total escalated cases."
                ),
                key_points=[
                    *[
                        f"student_id {item.student_id}: {item.note or 'Escalated but no faculty intervention logged yet.'}"
                        for item in top_cases
                    ],
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin unresolved-escalation intent"},
                    {"tool_name": "faculty_summary", "summary": "Returned faculty escalation status summary"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin unresolved-escalation intent"},
                {"tool_name": "faculty_summary", "summary": "Returned faculty escalation status summary"},
            ],
            [],
            {
                "kind": "admin_governance",
                "intent": "admin_unhandled_escalation_summary",
                "student_ids": [int(item.student_id) for item in top_cases],
            },
        )

    if any(token in lowered for token in {"reopened", "repeated"}):
        top_cases = faculty_summary.reopened_case_students[:5] or faculty_summary.repeated_risk_students[:5]
        return (
            build_grounded_response(
                opening=(
                    f"There are {faculty_summary.total_reopened_cases} reopened cases and "
                    f"{faculty_summary.total_repeated_risk_students} repeated-risk students."
                ),
                key_points=[
                    *[
                        f"student_id {item.student_id}: {item.note or 'Repeated high-risk pattern detected.'}"
                        for item in top_cases
                    ],
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin repeated-risk governance intent"},
                    {"tool_name": "faculty_summary", "summary": "Returned reopened and repeated-risk summary"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin repeated-risk governance intent"},
                {"tool_name": "faculty_summary", "summary": "Returned reopened and repeated-risk summary"},
            ],
            [],
            {
                "kind": "admin_governance",
                "intent": "admin_repeated_risk_summary",
                "student_ids": [int(item.student_id) for item in top_cases],
            },
        )

    if any(token in lowered for token in {"priority", "queue", "urgent"}):
        top_cases = priority_queue.queue[:5]
        return (
            build_grounded_response(
                opening=f"There are {priority_queue.total_students} students in the current priority queue.",
                key_points=[
                    *[
                        (
                            f"student_id {item.student_id}: {item.priority_label} priority, "
                            f"probability {item.final_risk_probability:.4f}, reason: {item.queue_reason}"
                        )
                        for item in top_cases
                    ],
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin priority-queue governance intent"},
                    {"tool_name": "faculty_priority_queue", "summary": "Returned faculty priority queue"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin priority-queue governance intent"},
                {"tool_name": "faculty_priority_queue", "summary": "Returned faculty priority queue"},
            ],
            [],
            {
                "kind": "admin_governance",
                "intent": "admin_priority_queue_summary",
                "student_ids": [int(item.student_id) for item in top_cases],
            },
        )

    if any(
        token in lowered
        for token in {
            "false alert",
            "false-alert",
            "effectiveness",
            "effective",
            "intervention",
            "interventions",
            "duty",
            "performance",
        }
    ):
        top_action_types = intervention_effectiveness.action_effectiveness[:5]
        return (
            build_grounded_response(
                opening=(
                    f"Intervention review coverage is {intervention_effectiveness.review_coverage_percent:.1f}% "
                    f"with a false-alert rate of {intervention_effectiveness.false_alert_rate_percent:.1f}%."
                ),
                key_points=[
                    *[
                        (
                            f"{item.action_status}: review rate {item.review_rate:.1f}%, "
                            f"effectiveness {item.effectiveness_score:.1f}%, summary: {item.summary}"
                        )
                        for item in top_action_types
                    ],
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin intervention-effectiveness intent"},
                    {"tool_name": "intervention_effectiveness", "summary": "Returned intervention effectiveness analytics"},
                ],
                limitations=["This is system-level intervention effectiveness, not a per-counsellor scorecard yet"],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin intervention-effectiveness intent"},
                {"tool_name": "intervention_effectiveness", "summary": "Returned intervention effectiveness analytics"},
            ],
            ["This is system-level intervention effectiveness, not a per-counsellor scorecard yet"],
            {
                "kind": "admin_governance",
                "intent": "admin_intervention_effectiveness_summary",
            },
        )

    return None


# ── 4-tier risk listing chatbot helpers ─────────────────────────────


def _detect_risk_tier_listing_request(lowered: str) -> str | None:
    """Return 'HIGH', 'MEDIUM', 'LOW', 'SAFE', or None."""
    tier_patterns = {
        "HIGH": [
            "high risk", "high-risk", "show high", "list high", "who are high",
            "high r", "highrisk", "how many high",
        ],
        "MEDIUM": [
            "medium risk", "medium-risk", "show medium", "list medium", "who are medium",
            "medium r", "mediumrisk", "how many medium", "moderate risk",
        ],
        "LOW": [
            "low risk", "low-risk", "show low", "list low", "who are low",
            "low r", "lowrisk", "how many low",
        ],
        "SAFE": [
            "safe student", "show safe", "list safe", "who are safe",
            "safe risk", "no risk",
        ],
    }
    # Check for tier-listing intent (not just mentioning the word)
    listing_signals = [
        "show", "list", "who", "how many", "give me", "tell me",
        "which student", "display", "get me", "risk student",
        "risk r", " r$",  # handles truncated queries like "medium r"
    ]
    has_listing_signal = any(s in lowered for s in listing_signals) or lowered.strip().endswith(" r")

    for tier, patterns in tier_patterns.items():
        if any(p in lowered for p in patterns):
            if has_listing_signal or lowered.strip() in patterns:
                return tier
    return None


def _answer_risk_tier_listing(
    *,
    tier: str,
    auth: AuthContext,
    repository: EventRepository,
) -> tuple[str, list[dict], list[str], dict]:
    from src.api.risk_classification import classify_risk_level

    all_predictions = repository.get_latest_predictions_for_all_students()
    imported_ids = {
        int(p.student_id) for p in repository.get_imported_student_profiles()
    }

    tier_students: list[dict] = []
    tier_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "SAFE": 0}

    for prediction in all_predictions:
        sid = int(prediction.student_id)
        if sid not in imported_ids:
            continue
        level = classify_risk_level(float(prediction.final_risk_probability))
        tier_counts[level] = tier_counts.get(level, 0) + 1
        if level == tier:
            profile = repository.get_student_profile(sid)
            branch = "unknown"
            latest_erp = repository.get_latest_erp_event(sid)
            if latest_erp:
                ctx = getattr(latest_erp, "context_fields", None) or {}
                branch = ctx.get("branch") or ctx.get("department") or "unknown"
            if profile:
                profile_ctx = getattr(profile, "profile_context", None) or {}
                branch = profile_ctx.get("branch") or branch

            counsellor = getattr(profile, "counsellor_name", None) or "Unassigned"
            prob = float(prediction.final_risk_probability)

            tier_students.append({
                "student_id": sid,
                "probability": prob,
                "branch": branch,
                "counsellor": counsellor,
            })

    tier_students.sort(key=lambda s: -s["probability"])
    shown = tier_students[:10]
    total = len(tier_students)

    tier_label = {"HIGH": "High Risk", "MEDIUM": "Medium Risk", "LOW": "Low Risk", "SAFE": "Safe"}.get(tier, tier)

    overview_line = (
        f"Institution-wide breakdown: "
        f"HIGH={tier_counts['HIGH']}, MEDIUM={tier_counts['MEDIUM']}, "
        f"LOW={tier_counts['LOW']}, SAFE={tier_counts['SAFE']}."
    )

    if total == 0:
        return (
            build_grounded_response(
                opening=f"There are currently **0 {tier_label}** students in the system.",
                key_points=[overview_line],
                closing="You can ask about a different tier or check the dashboard for the full breakdown.",
                tools_used=[{"tool_name": "risk_tier_listing", "summary": f"Queried all predictions for {tier} tier students"}],
                limitations=[],
            ),
            [{"tool_name": "risk_tier_listing", "summary": f"Queried all predictions for {tier} tier students"}],
            [],
            {"kind": "risk_tier_listing", "intent": f"list_{tier.lower()}_risk_students", "tier": tier},
        )

    student_lines = []
    for s in shown:
        student_lines.append(
            f"**Student {s['student_id']}** — {s['probability']*100:.1f}% risk probability · "
            f"Branch: {s['branch']} · Counsellor: {s['counsellor']}"
        )

    key_points = [
        f"**{total} students** are currently classified as **{tier_label}**.",
        overview_line,
    ]
    key_points.extend(student_lines)
    if total > 10:
        key_points.append(f"... and {total - 10} more. Visit the **Students** page in the dashboard for the full list.")

    return (
        build_grounded_response(
            opening=f"Here are the **{tier_label}** students ({total} total):",
            key_points=key_points,
            closing="You can ask me about a specific student by ID, or click the tier cards on the dashboard to see the full directory.",
            tools_used=[{"tool_name": "risk_tier_listing", "summary": f"Queried all predictions and filtered {total} students in the {tier} tier"}],
            limitations=["Showing up to 10 students in chat. Visit the Students page for the full paginated list."] if total > 10 else [],
        ),
        [{"tool_name": "risk_tier_listing", "summary": f"Queried all predictions and filtered {total} students in the {tier} tier"}],
        ["Showing up to 10 students in chat."] if total > 10 else [],
        {"kind": "risk_tier_listing", "intent": f"list_{tier.lower()}_risk_students", "tier": tier, "total_found": total},
    )
