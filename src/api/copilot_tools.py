from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from src.api.auth import AuthContext
from src.api.copilot_intents import detect_copilot_intent, suggest_copilot_intents
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_response_builder import build_grounded_response
from src.api.copilot_runtime import COPILOT_PLANNER_TOOL_NAME, COPILOT_SYSTEM_PROMPT_VERSION
from src.api.routes.faculty import get_faculty_priority_queue, get_faculty_summary
from src.api.routes.interventions import get_intervention_effectiveness_analytics
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
    memory = memory or resolve_copilot_memory_context(
        message=message,
        session_messages=session_messages,
    )
    intent = str(planner.get("primary_intent") or detect_copilot_intent(role=auth.role, message=execution_message))

    if planner.get("refusal_reason"):
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

    if planner.get("clarification_needed"):
        clarification_question = str(planner.get("clarification_question") or "Can you clarify what you want me to compare or filter?")
        return (
            build_grounded_response(
                opening="I understood the retention-domain request, but I need one more detail before I run the backend query.",
                key_points=[
                    clarification_question,
                    "I will keep the current retention context once you answer, so you do not need to restate the full question.",
                ],
                tools_used=[{"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Structured the query into a CB22 plan and asked for clarification"}],
                limitations=["planner needs one missing detail before grounded tool execution can continue"],
            ),
            [{"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Structured the query into a CB22 plan and asked for clarification"}],
            ["planner needs one missing detail before grounded tool execution can continue"],
            {
                "kind": "planner",
                "intent": "planner_clarification",
                "planner_version": str(planner.get("version") or COPILOT_SYSTEM_PROMPT_VERSION),
            },
        )

    if auth.role == "student":
        return _answer_student_question(
            auth=auth,
            repository=repository,
            lowered=lowered,
            intent=intent,
            memory=memory,
        )
    if auth.role == "counsellor":
        return _answer_counsellor_question(
            auth=auth,
            repository=repository,
            lowered=lowered,
            intent=intent,
            memory=memory,
            query_plan=planner,
        )
    return _answer_admin_question(
        auth=auth,
        repository=repository,
        lowered=lowered,
        intent=intent,
        memory=memory,
        query_plan=planner,
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
        return (
            build_grounded_response(
                opening="I can already help with a focused set of grounded student questions.",
                key_points=[
                    "latest risk or score",
                    "active warning status",
                    "basic profile contact summary",
                ],
                tools_used=[{"tool_name": "student_copilot_help", "summary": "Returned current student copilot capabilities"}],
                limitations=["broad free-form academic advising is not connected yet"],
                closing="Try asking: 'what is my risk?' or 'do I have any warning?'",
            ),
            [{"tool_name": "student_copilot_help", "summary": "Returned current student copilot capabilities"}],
            ["CB3 supports routed student intents, but not broad free-form academic advising yet"],
            {"kind": "student_self", "student_id": student_id, "intent": "help"},
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
        return (
            build_grounded_response(
                opening=f"Your latest risk level is {risk_level}.",
                key_points=[
                    f"Final risk probability: {float(latest_prediction.final_risk_probability):.4f}",
                    f"Prediction timestamp available in score history for student_id {student_id}",
                ],
                tools_used=[{"tool_name": "latest_prediction_lookup", "summary": "Returned latest student prediction"}],
                limitations=[],
            ),
            [{"tool_name": "latest_prediction_lookup", "summary": "Returned latest student prediction"}],
            [],
            {"kind": "student_self", "student_id": student_id, "intent": "student_self_risk"},
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

    return (
        build_grounded_response(
            opening=(
                "I can’t help with that request." if _is_sensitive_request(lowered) else "I didn’t fully match that to a student intent yet."
            ),
            key_points=(
                ["I cannot share passwords or secrets."]
                if _is_sensitive_request(lowered)
                else [
                    "latest risk",
                    "active warning status",
                    "profile contact summary",
                    *(
                        [f"Did you mean: {', '.join(_build_intent_suggestions('student', lowered))}?"]
                        if _build_intent_suggestions("student", lowered)
                        else []
                    ),
                ]
            ),
            tools_used=[{"tool_name": "student_intent_router", "summary": f"Routed unsupported student intent `{intent}`"}],
            limitations=["student question is outside the current routed intent set"],
        ),
        [{"tool_name": "student_intent_router", "summary": f"Routed unsupported student intent `{intent}`"}],
        ["student question is outside the current routed intent set"],
        {
            "kind": "student_self",
            "student_id": student_id,
            "intent": "unsupported",
            "last_follow_up": bool(memory.get("is_follow_up")),
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
    counsellor_profiles = repository.get_imported_student_profiles_for_counsellor_identity(
        subject=auth.subject,
        display_name=auth.display_name,
    )
    owned_student_ids = {int(profile.student_id) for profile in counsellor_profiles}
    queue = repository.get_latest_predictions_for_all_students()
    latest_predictions = {
        int(row.student_id): row for row in queue if not owned_student_ids or int(row.student_id) in owned_student_ids
    }
    high_risk_rows = [row for row in latest_predictions.values() if int(row.final_predicted_class) == 1]
    memory_follow_up = _maybe_answer_role_follow_up(
        role="counsellor",
        repository=repository,
        intent=intent,
        memory=memory,
        profiles=counsellor_profiles,
    )
    if memory_follow_up is not None:
        return memory_follow_up

    if planner.get("user_goal") == "priority_queue":
        queue_response = get_faculty_priority_queue(db=repository.db, auth=auth)
        scoped_queue = [item for item in queue_response.queue if not owned_student_ids or int(item.student_id) in owned_student_ids]
        top_items = scoped_queue[:5]
        return (
            build_grounded_response(
                opening=f"There are {len(scoped_queue)} students in the current faculty priority queue assigned to your counsellor scope.",
                key_points=[
                    *[
                        (
                            f"student_id {item.student_id}: {item.priority_label} priority, "
                            f"SLA {item.sla_status}, reason: {item.queue_reason}"
                        )
                        for item in top_items
                    ],
                ],
                tools_used=[
                    {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Interpreted a natural-language counsellor request into a priority-queue plan"},
                    {"tool_name": "faculty_priority_queue", "summary": "Returned the counsellor-scoped faculty priority queue"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": COPILOT_PLANNER_TOOL_NAME, "summary": "Interpreted a natural-language counsellor request into a priority-queue plan"},
                {"tool_name": "faculty_priority_queue", "summary": "Returned the counsellor-scoped faculty priority queue"},
            ],
            [],
            {
                "kind": "cohort",
                "intent": "counsellor_priority_follow_up",
                "student_ids": [int(item.student_id) for item in top_items],
                "scope": "faculty_priority_queue_assigned",
                "planner_version": str(planner.get("version") or COPILOT_SYSTEM_PROMPT_VERSION),
            },
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
                ],
                tools_used=[{"tool_name": "counsellor_copilot_help", "summary": "Returned current counsellor copilot capabilities"}],
                limitations=[],
                closing="Try asking: 'how many high risk students are there?', 'who needs urgent follow-up?', or 'show details for student 880001'.",
            ),
            [{"tool_name": "counsellor_copilot_help", "summary": "Returned current counsellor copilot capabilities"}],
            [],
            {"kind": "help", "intent": "help"},
        )

    if intent == "cohort_summary":
        if any(token in lowered for token in {"urgent", "priority", "follow-up", "followup", "overdue"}):
            queue_response = get_faculty_priority_queue(db=repository.db, auth=auth)
            scoped_queue = [item for item in queue_response.queue if not owned_student_ids or int(item.student_id) in owned_student_ids]
            top_items = scoped_queue[:5]
            return (
                build_grounded_response(
                    opening=f"There are {len(scoped_queue)} students in the current faculty priority queue assigned to your counsellor scope.",
                    key_points=[
                        *[
                            (
                                f"student_id {item.student_id}: {item.priority_label} priority, "
                                f"SLA {item.sla_status}, reason: {item.queue_reason}"
                            )
                            for item in top_items
                        ],
                    ],
                    tools_used=[
                        {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor urgent-follow-up request"},
                        {"tool_name": "faculty_priority_queue", "summary": "Returned the counsellor-scoped faculty priority queue"},
                    ],
                    limitations=[],
                ),
                [
                    {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor urgent-follow-up request"},
                    {"tool_name": "faculty_priority_queue", "summary": "Returned the counsellor-scoped faculty priority queue"},
                ],
                [],
                {
                    "kind": "cohort",
                    "intent": "counsellor_priority_follow_up",
                    "student_ids": [int(item.student_id) for item in top_items],
                    "scope": "faculty_priority_queue_assigned",
                },
            )
        return (
            build_grounded_response(
                opening=f"There are currently {len(high_risk_rows)} students in the latest high-risk cohort assigned to your counsellor scope.",
                tools_used=[
                    {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor cohort summary intent"},
                    {"tool_name": "counsellor_high_risk_count", "summary": "Counted latest high-risk students in counsellor scope"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor cohort summary intent"},
                {"tool_name": "counsellor_high_risk_count", "summary": "Counted latest high-risk students in counsellor scope"},
            ],
            [],
            {
                "kind": "cohort",
                "intent": "cohort_summary",
                "student_ids": [int(row.student_id) for row in high_risk_rows],
                "scope": "latest_high_risk_predictions_assigned",
            },
        )

    student_id = _extract_student_id(lowered) if intent == "student_drilldown" else None
    if student_id is None:
        student_id = _student_id_from_memory(memory)
    should_reuse_student = (
        bool(memory.get("is_follow_up"))
        and student_id is not None
        and (memory.get("wants_contact_focus") or memory.get("wants_risk_focus"))
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
        parts = [
            f"Student {student_id}",
            f"email: {profile.student_email or 'not available'}",
            f"faculty: {profile.faculty_name or 'not assigned'}",
            f"counsellor: {getattr(profile, 'counsellor_name', None) or 'not assigned'}",
        ]
        if prediction is not None:
            parts.append(
                f"latest risk probability: {float(prediction.final_risk_probability):.4f}"
            )
        else:
            parts.append("no prediction available yet")
        return (
            build_grounded_response(
                opening=f"I found a student drilldown for student_id {student_id}.",
                key_points=parts[1:],
                tools_used=[
                    {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor student drilldown intent"},
                    {"tool_name": "student_profile_lookup", "summary": "Returned student profile details"},
                    {"tool_name": "latest_prediction_lookup", "summary": "Returned latest student prediction if available"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "counsellor_intent_router", "summary": "Routed counsellor student drilldown intent"},
                {"tool_name": "student_profile_lookup", "summary": "Returned student profile details"},
                {"tool_name": "latest_prediction_lookup", "summary": "Returned latest student prediction if available"},
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
                    *(
                        [f"Did you mean: {', '.join(_build_intent_suggestions('counsellor', lowered))}?"]
                        if _build_intent_suggestions("counsellor", lowered)
                        else []
                    ),
                ]
            ),
            tools_used=[{"tool_name": "counsellor_intent_router", "summary": f"Routed unsupported counsellor intent `{intent}`"}],
            limitations=["counsellor question is outside the current routed intent set"],
        ),
        [{"tool_name": "counsellor_intent_router", "summary": f"Routed unsupported counsellor intent `{intent}`"}],
        ["counsellor question is outside the current routed intent set"],
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
    latest_predictions = repository.get_latest_predictions_for_all_students()
    high_risk_rows = [row for row in latest_predictions if int(row.final_predicted_class) == 1]
    interventions = repository.get_all_intervention_actions()
    warning_events = repository.get_all_student_warning_events()
    memory_follow_up = _maybe_answer_role_follow_up(
        role="admin",
        repository=repository,
        intent=intent,
        memory=memory,
        profiles=profiles,
    )
    if memory_follow_up is not None:
        return memory_follow_up

    planner = query_plan or {}
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

    if planner.get("comparison", {}).get("enabled"):
        compare_dimension = str(planner.get("comparison", {}).get("dimension") or "").strip()
        compare_values = list(planner.get("comparison", {}).get("values") or [])
        if not compare_values and compare_dimension in {"branch", "category", "region", "income"}:
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
            latest_predictions_by_student = {int(row.student_id): row for row in latest_predictions}
            history_rows = repository.get_all_prediction_history()
            intervention_student_ids = {
                int(getattr(row, "student_id"))
                for row in interventions
                if getattr(row, "student_id", None) is not None
            }
            active_warning_student_ids = {
                int(profile.student_id)
                for profile in profiles
                if repository.get_active_student_warning_for_student(int(profile.student_id)) is not None
            }
            recent_warning_events = _filter_rows_by_window(
                rows=warning_events,
                time_attr="sent_at",
                window_days=int(planner.get("time_window_days") or 30),
            )
            recent_intervention_events = _filter_rows_by_window(
                rows=interventions,
                time_attr="created_at",
                window_days=int(planner.get("time_window_days") or 30),
            )
            current_warning_window, previous_warning_window = _split_rows_by_consecutive_windows(
                rows=warning_events,
                time_attr="sent_at",
                window_days=int(planner.get("time_window_days") or 30),
            )
            current_intervention_window, previous_intervention_window = _split_rows_by_consecutive_windows(
                rows=interventions,
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
                            rows=warning_events,
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
                            rows=interventions,
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
                        key_points.append(f"{value} currently high-risk students: {risk_count} ({risk_rate:.1f}% of subset)")
                    else:
                        key_points.append(f"{value} currently high-risk students: {risk_count}")
                    comparison_rows["risk"].append(
                        {"value": value, "count": risk_count, "rate": risk_rate if has_multi_metric else float(risk_count), "label": "currently high-risk students"}
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
                "risk": "currently high-risk students",
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
        latest_predictions_by_student = {int(row.student_id): row for row in latest_predictions}
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
                metric_label = "currently high-risk students"
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
        latest_predictions_by_student = {int(row.student_id): row for row in latest_predictions}
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
                        key_points.append(f"{bucket_label} currently high-risk students: {high_risk_count}")
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
        latest_predictions_by_student = {int(row.student_id): row for row in latest_predictions}
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
                    key_points.append(f"{branch_value} currently high-risk students: {high_risk_count}")
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
        latest_predictions_by_student = {int(row.student_id): row for row in latest_predictions}
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
                    key_points.append(f"{category_value} currently high-risk students: {high_risk_count}")
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
        latest_predictions_by_student = {int(row.student_id): row for row in latest_predictions}
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
                    key_points.append(f"{region_value} currently high-risk students: {high_risk_count}")
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
        latest_predictions_by_student = {int(row.student_id): row for row in latest_predictions}
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
                    key_points.append(f"{income_value} currently high-risk students: {high_risk_count}")
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
        latest_predictions_by_student = {int(row.student_id): row for row in latest_predictions}
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
                    key_points.append(f"{outcome_status} currently high-risk students: {high_risk_count}")
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
            int(row.student_id): row for row in latest_predictions
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
            interventions=interventions,
            faculty_summary=faculty_summary,
            priority_queue=priority_queue,
            intervention_effectiveness=intervention_effectiveness,
        )
        if governance_answer is not None:
            return governance_answer
        resolved = sum(
            1 for row in interventions if str(row.action_status).strip().lower() == "resolved"
        )
        return (
            build_grounded_response(
                opening=f"There are {len(interventions)} logged intervention actions and {resolved} of them are marked resolved.",
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
                opening=f"There are currently {len(high_risk_rows)} students in the latest high-risk cohort and {len(profiles)} imported students in the Vignan-linked profile set.",
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
                "student_ids": [int(row.student_id) for row in high_risk_rows],
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
        return (
            build_grounded_response(
                opening=f"I found a student drilldown for student_id {student_id}.",
                key_points=[
                    f"email: {profile.student_email or 'not available'}",
                    f"faculty: {profile.faculty_name or 'not assigned'}",
                    f"counsellor: {getattr(profile, 'counsellor_name', None) or 'not assigned'}",
                    f"latest risk probability: {latest_probability}",
                ],
                tools_used=[
                    {"tool_name": "admin_intent_router", "summary": "Routed admin student drilldown intent"},
                    {"tool_name": "student_profile_lookup", "summary": "Returned student profile details"},
                    {"tool_name": "latest_prediction_lookup", "summary": "Returned latest student prediction if available"},
                ],
                limitations=[],
            ),
            [
                {"tool_name": "admin_intent_router", "summary": "Routed admin student drilldown intent"},
                {"tool_name": "student_profile_lookup", "summary": "Returned student profile details"},
                {"tool_name": "latest_prediction_lookup", "summary": "Returned latest student prediction if available"},
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
            limitations=["admin question is outside the current routed intent set"],
        ),
        [{"tool_name": "admin_intent_router", "summary": f"Routed unsupported admin intent `{intent}`"}],
        ["admin question is outside the current routed intent set"],
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

    if last_kind == "import_coverage" and memory.get("is_follow_up"):
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
        lowered_message = str(memory.get("lowered_message") or "")
        requested_bucket_values, excluded_bucket_values = _parse_group_bucket_edit(
            lowered=lowered_message,
            bucket_values=bucket_values,
        )
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
        if other_group_mentions and not requested_bucket_values and not excluded_bucket_values:
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
                if (_profile_outcome_status(profile) if grouped_by == "outcome_status" else _profile_context_value(profile, grouped_by) or "").strip().lower() in allowed_bucket_values
            ]
        if excluded_bucket_values:
            blocked_bucket_values = {value.lower() for value in excluded_bucket_values}
            matching_profiles = [
                profile
                for profile in matching_profiles
                if (_profile_outcome_status(profile) if grouped_by == "outcome_status" else _profile_context_value(profile, grouped_by) or "").strip().lower() not in blocked_bucket_values
            ]
        summary_tool = None
        if requested_bucket_values or excluded_bucket_values:
            summary_tool = (
                {"tool_name": "grouped_bucket_focus", "summary": "Excluded the requested bucket set from the previous grouped result"}
                if exclude_bucket_requested
                else {"tool_name": "grouped_bucket_focus", "summary": "Focused the previous grouped result on the requested bucket set"}
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


def _profile_context_value(profile: object, key: str) -> str | None:
    profile_context = getattr(profile, "profile_context", None) or {}
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
    for key in ("branch", "category", "region", "income"):
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
