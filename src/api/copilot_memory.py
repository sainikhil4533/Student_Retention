from __future__ import annotations

import re
from typing import Any


FOLLOW_UP_TOKENS = {
    "what about",
    "they ",
    "their ",
    "those ",
    "them ",
    "these ",
    "only ",
    "show only",
    "exclude ",
    "except ",
    "without ",
    "remove ",
}

SHORT_CONTINUATION_REPLIES = {
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
    "more",
}


FRESH_QUERY_PREFIXES = (
    "show ",
    "list ",
    "how many ",
    "which ",
    "give ",
    "tell me ",
    "display ",
    "compare ",
    "who ",
    "what ",
    "is ",
    "are ",
    "can you ",
    "do we ",
    "do i ",
    "am i ",
)

ROLE_TOPIC_RESET_TERMS = {
    "i grade",
    "r grade",
    "assigned students",
    "my assigned students",
    "what should i do",
    "what should we do",
    "strategy",
    "subjects",
    "trend",
    "stats",
    "what action",
    "operational priorities",
}


def resolve_copilot_memory_context(
    *,
    message: str,
    session_messages: list[object],
) -> dict[str, Any]:
    lowered = str(message or "").strip().lower()
    explicit_student_id = _extract_student_id(lowered)
    requested_outcome = _extract_outcome_status(lowered)
    wants_contact_focus = any(
        token in lowered
        for token in {
            "counsellor",
            "counsellors",
            "counselor",
            "counselors",
            "faculty",
            "email",
            "contact",
            "parent",
            "phone",
            "mentor",
            "mentors",
            "assigned person",
            "assigned people",
            "assigned mentor",
            "assigned mentors",
        }
    )
    wants_warning_focus = any(token in lowered for token in {"warning", "warnings", "flagged", "alert", "alerts"})
    wants_risk_focus = any(
        token in lowered
        for token in {"risk", "score", "prediction", "danger zone", "dangerous zone", "danger cases"}
    )
    wants_only_high_risk_subset = any(
        token in lowered
        for token in {
            "only the high-risk",
            "only high-risk",
            "only the high risk",
            "only high risk",
            "just the high-risk",
            "just the high risk",
            "only risky ones",
            "only risky students",
        }
    )
    wants_only_warning_subset = any(
        token in lowered
        for token in {
            "only the ones with warnings",
            "only the ones with warning",
            "only warnings",
            "only warning cases",
            "only warned students",
            "just the ones with warnings",
        }
    )
    wants_exclude_high_risk_subset = any(
        token in lowered
        for token in {
            "exclude the high-risk",
            "exclude high-risk",
            "exclude the high risk",
            "exclude high risk",
            "not the high-risk",
            "not the high risk",
            "remove the high-risk",
            "without the high-risk",
        }
    )
    wants_exclude_warning_subset = any(
        token in lowered
        for token in {
            "exclude the ones with warnings",
            "exclude warnings",
            "not the ones with warnings",
            "without warnings",
            "remove warning cases",
        }
    )
    wants_counsellor_subset = "under counsellor" in lowered or "under counselor" in lowered
    normalized = re.sub(r"[^\w\s]", " ", lowered).strip()
    normalized = " ".join(normalized.split())
    if wants_only_warning_subset or wants_exclude_warning_subset:
        wants_warning_focus = False
    if wants_only_high_risk_subset or wants_exclude_high_risk_subset:
        wants_risk_focus = False
    requested_counsellor_name = _extract_counsellor_name(lowered)
    window_days = _extract_time_window_days(lowered)
    is_follow_up = any(token in lowered for token in FOLLOW_UP_TOKENS) or lowered.startswith("and ")
    starts_new_query = lowered.startswith(FRESH_QUERY_PREFIXES)
    has_scope_shift_terms = any(
        token in lowered
        for token in {
            "students in ",
            "student in ",
            "dropped",
            "graduated",
            "studying",
            "urban",
            "rural",
            "cse",
            "ece",
            "sc ",
            "obc",
            "income",
            "category",
            "branch",
            "region",
        }
    )
    has_explicit_compare_or_rank = any(
        token in lowered
        for token in {
            "compare",
            "versus",
            " vs ",
            " vs. ",
            "which branch",
            "which department",
            "which departments",
            "which region",
            "which category",
            "which income",
            "needs attention",
            "under pressure",
            "falling behind",
            "worsening",
            "improving",
            "saw the most",
            "has the highest",
            "has the worst",
            "getting riskier",
        }
    )
    has_role_topic_reset = any(token in lowered for token in ROLE_TOPIC_RESET_TERMS)
    wants_group_bucket_edit = any(
        token in lowered
        for token in {
            "only ",
            "show only",
            "except ",
            "exclude ",
            "excluding ",
            "without ",
            "bucket",
            "that group",
            "this group",
            "that bucket",
            "this bucket",
            "that one",
            "this one",
            "only those",
            "remove that",
            "remove that one",
            "not this bucket",
        }
    )

    last_assistant_context: dict[str, Any] | None = None
    for row in reversed(session_messages):
        if str(getattr(row, "role", "")) != "assistant":
            continue
        metadata = getattr(row, "metadata_json", None) or {}
        memory_context = metadata.get("memory_context")
        if isinstance(memory_context, dict):
            last_assistant_context = memory_context
            break

    if (
        not is_follow_up
        and isinstance(last_assistant_context, dict)
        and normalized in SHORT_CONTINUATION_REPLIES
        and not starts_new_query
    ):
        is_follow_up = True

    if (
        not is_follow_up
        and isinstance(last_assistant_context, dict)
        and normalized in {"who", "why"}
        and str(last_assistant_context.get("kind") or "")
        in {"import_coverage", "cohort", "student_drilldown", "admin_academic"}
    ):
        is_follow_up = True

    if (
        not is_follow_up
        and isinstance(last_assistant_context, dict)
        and str(last_assistant_context.get("kind") or "")
        in {"import_coverage", "cohort", "student_drilldown", "admin_academic"}
        and any(
            phrase in normalized
            for phrase in {
                "common issue",
                "main issue",
                "main problem",
                "main factor",
                "why is that happening",
                "how urgent is it",
                "how fast should i act",
                "what if no action is taken",
                "what happens if i delay",
                "which students are worst",
                "which student is most critical",
                "who is most critical",
                "what should i do first",
                "what should i do for them",
                "how to fix it",
                "how can i fix it",
                "give solution plan",
                "give me action plan",
                "how to prioritize students",
                "what if i ignore low risk",
                "what if i only focus on top 3",
                "is that okay",
                "is that enough",
                "what else should i do",
                "what is best strategy",
                "give weekly plan",
            }
        )
    ):
        is_follow_up = True

    if (
        not is_follow_up
        and window_days is not None
        and isinstance(last_assistant_context, dict)
        and str(last_assistant_context.get("scope") or "") == "time_window_missing"
    ):
        is_follow_up = True

    if (
        isinstance(last_assistant_context, dict)
        and str(last_assistant_context.get("role_scope") or "").strip().lower() == "admin"
        and normalized in {"risk", "trend", "stats", "analysis", "report", "performance"}
    ):
        is_follow_up = False

    if (
        not is_follow_up
        and isinstance(last_assistant_context, dict)
        and str(last_assistant_context.get("intent") or "") == "compound_subset_clarification"
        and not starts_new_query
        and (
            wants_contact_focus
            or wants_warning_focus
            or wants_risk_focus
            or wants_only_high_risk_subset
            or wants_only_warning_subset
            or wants_exclude_high_risk_subset
            or wants_exclude_warning_subset
            or wants_counsellor_subset
        )
    ):
        is_follow_up = True

    if (
        not is_follow_up
        and (
            wants_only_high_risk_subset
            or wants_only_warning_subset
            or wants_exclude_high_risk_subset
            or wants_exclude_warning_subset
            or wants_counsellor_subset
        )
        and isinstance(last_assistant_context, dict)
        and str(last_assistant_context.get("kind") or "") == "import_coverage"
    ):
        is_follow_up = True

    if (
        not is_follow_up
        and isinstance(last_assistant_context, dict)
        and str(last_assistant_context.get("kind") or "") == "import_coverage"
        and str(last_assistant_context.get("grouped_by") or "")
        and (not starts_new_query or wants_group_bucket_edit)
        and (
            any(
                str(value).strip().lower() in lowered
                for value in (last_assistant_context.get("bucket_values") or [])
                if str(value).strip()
            )
            or wants_group_bucket_edit
        )
        and (
            wants_group_bucket_edit
            or wants_contact_focus
            or wants_warning_focus
            or wants_risk_focus
        )
    ):
        is_follow_up = True

    if (
        not is_follow_up
        and isinstance(last_assistant_context, dict)
        and str(last_assistant_context.get("kind") or "") == "import_coverage"
        and not explicit_student_id
        and not requested_outcome
        and not has_scope_shift_terms
        and (
            wants_contact_focus
            or wants_warning_focus
            or wants_risk_focus
            or wants_only_high_risk_subset
            or wants_only_warning_subset
            or wants_exclude_high_risk_subset
            or wants_exclude_warning_subset
        )
    ):
        is_follow_up = True

    # In longer chats we prefer a fresh analytical query over stale memory when the new
    # turn clearly restarts comparison/ranking/filtering work.
    if (
        is_follow_up
        and starts_new_query
        and (has_scope_shift_terms or has_explicit_compare_or_rank or explicit_student_id or requested_outcome or has_role_topic_reset)
        and not wants_group_bucket_edit
        and not (
            isinstance(last_assistant_context, dict)
            and str(last_assistant_context.get("scope") or "") == "time_window_missing"
        )
        and not (
            isinstance(last_assistant_context, dict)
            and str(last_assistant_context.get("intent") or "") == "compound_subset_clarification"
        )
        and not (
            isinstance(last_assistant_context, dict)
            and str(last_assistant_context.get("pending_role_follow_up") or "").strip().lower()
            in {"operational_actions", "student_specific_action"}
            and any(
                phrase in normalized
                for phrase in {
                    "what should i do first",
                    "what should i do for them",
                    "how can i fix it",
                    "give solution plan",
                    "give me action plan",
                    "how to prioritize students",
                    "how fast should i act",
                    "what else should i do",
                    "what is best strategy",
                    "give weekly plan",
                }
            )
        )
    ):
        is_follow_up = False

    fresh_subset_filter = normalized.startswith("only ") or normalized.startswith("show only ")
    if (
        is_follow_up
        and fresh_subset_filter
        and any(
            token in normalized
            for token in {
                "year",
                "final year",
                "low attendance",
                "low assignments",
                "high risk",
                "high-risk",
                "students",
            }
        )
    ):
        is_follow_up = False

    return {
        "is_follow_up": is_follow_up,
        "explicit_student_id": explicit_student_id,
        "requested_outcome_status": requested_outcome,
        "wants_contact_focus": wants_contact_focus,
        "wants_warning_focus": wants_warning_focus,
        "wants_risk_focus": wants_risk_focus,
        "wants_only_high_risk_subset": wants_only_high_risk_subset,
        "wants_only_warning_subset": wants_only_warning_subset,
        "wants_exclude_high_risk_subset": wants_exclude_high_risk_subset,
        "wants_exclude_warning_subset": wants_exclude_warning_subset,
        "wants_counsellor_subset": wants_counsellor_subset,
        "requested_counsellor_name": requested_counsellor_name,
        "window_days": window_days,
        "lowered_message": lowered,
        "last_context": last_assistant_context or {},
    }


def _extract_student_id(text: str) -> int | None:
    match = re.search(r"\b(88\d{4,})\b", text)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _extract_outcome_status(text: str) -> str | None:
    if "dropped" in text or "drop" in text:
        return "Dropped"
    if "graduated" in text or "graduate" in text:
        return "Graduated"
    if "studying" in text or "study" in text:
        return "Studying"
    return None


def _extract_time_window_days(text: str) -> int | None:
    match = re.search(r"\b(\d{1,3})\s*(day|days|d)\b", text)
    if match is not None:
        return int(match.group(1))
    number_only = re.search(r"^\s*(\d{1,3})\s*$", text)
    if number_only is not None:
        return int(number_only.group(1))
    if "last week" in text or "past week" in text:
        return 7
    if re.search(r"^\s*week\s*$", text):
        return 7
    if "last month" in text or "past month" in text:
        return 30
    if re.search(r"^\s*month\s*$", text):
        return 30
    if "last quarter" in text or "past quarter" in text or re.search(r"^\s*quarter\s*$", text):
        return 90
    if "last semester" in text or "past semester" in text or re.search(r"^\s*semester\s*$", text):
        return 180
    if "last day" in text or "last 24 hours" in text or "past 24 hours" in text:
        return 1
    if re.search(r"^\s*day\s*$", text):
        return 1
    return None


def _extract_counsellor_name(text: str) -> str | None:
    match = re.search(
        r"under (?:counsellor|counselor)\s+([a-z][a-z\s\.]+?)(?:\s+but\b|$)",
        text,
    )
    if match is None:
        return None
    value = match.group(1).strip()
    return value or None
