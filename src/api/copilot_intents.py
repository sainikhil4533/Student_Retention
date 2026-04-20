from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Literal

from src.api.auth import RoleName


CopilotIntent = Literal[
    "identity",
    "help",
    "student_self_risk",
    "student_self_warning",
    "student_self_profile",
    "student_self_attendance",
    "student_self_subject_risk",
    "student_self_plan",
    "student_drilldown",
    "cohort_summary",
    "import_coverage",
    "admin_governance",
    "unsupported",
]

_SENSITIVE_TOKENS = {
    "password",
    "passwords",
    "ssn",
    "social",
    "credit",
    "card",
    "bank",
    "account",
    "otp",
    "token",
    "secret",
}

_TOKEN_SYNONYMS = {
    "dangerous": ["high", "risk", "high_risk"],
    "zone": ["risk", "high_risk"],
    "dropout": ["dropped"],
    "dropouts": ["dropped"],
    "entered": ["newly", "initial"],
    "entering": ["newly", "initial"],
    "newly": ["initial", "recent"],
    "just": ["recent", "initial"],
    "urgent": ["priority", "overdue"],
    "followup": ["follow-up"],
    "follow": ["follow-up"],
    "escalations": ["escalation"],
    "counselor": ["counsellor"],
}

_INTENT_EXAMPLES: dict[str, dict[str, list[str]]] = {
    "student": {
        "student_self_risk": [
            "what is my risk",
            "am i at risk",
            "my risk score",
            "my prediction",
            "how risky am i",
        ],
        "student_self_warning": [
            "do i have a warning",
            "any warning for me",
            "active warning",
            "warning status",
        ],
        "student_self_profile": [
            "my profile",
            "my contact details",
            "my faculty contact",
            "my counsellor contact",
        ],
        "student_self_attendance": [
            "what is my attendance right now",
            "which data do you have of me",
            "which subject has low attendance",
            "subject wise attendance",
            "what is my attendance",
            "what is my assignment submission rate",
            "how is my assignment rate",
            "what is my submission rate",
            "what is my lms details",
            "give me my lms activity",
            "show me my lms activity",
            "what is my lms activity",
            "what is my erp details",
            "show me my erp details",
            "what is my finance details",
            "show me my finance status",
            "what is my gpa",
            "show my previous and current gpa",
            "how many days did i login",
            "performance",
            "marks",
            "progress",
        ],
        "student_self_subject_risk": [
            "do i have i grade risk",
            "do i have r grade risk",
            "which subject is hurting me most",
            "am i safe for end sem",
            "am i safe or should i worry",
            "am i in trouble",
            "should i be worried",
            "how bad is my situation",
            "am i doing good",
            "how am i performing",
            "is my performance okay",
            "am i improving or getting worse",
            "do i still have any uncleared grade issue from older sems",
            "my attendance is safe but why am i high risk",
            "why am i in high alert if attendance is safe",
        ],
        "student_self_plan": [
            "what should i focus on this week",
            "what should i focus on next week",
            "can you plan my next few weeks",
            "plan my routine for next few weeks",
            "what should i do first",
            "turn this into a simple day by day plan for the week",
            "give me a daily plan for the week",
            "how can i recover from high alert",
            "how can i recover from high risk",
            "how can i remove the high label risk",
            "how can i reduce my risk",
            "what should i do to reduce my high risk",
            "how to increase my gpa",
            "how to improve assignments",
            "show me my coursework priorities",
        ],
    },
    "counsellor": {
        "cohort_summary": [
            "students?",
            "show my assigned students",
            "which students are high risk",
            "how many high risk students",
            "urgent follow up cases",
            "priority queue",
            "students needing attention",
            "which students have i grade risk",
            "which students have r grade risk",
            "what should i do for high risk students",
            "what should i do first for my students",
            "show only cse",
            "what about top 5",
            "show high risk semester wise year wise",
            "show high risk branch wise",
            "show attendance risk branch wise",
            "show attendance risk gender wise",
            "show attendance risk batch wise",
            "show prediction high risk program wise",
            "show prediction high risk and attendance risk age band wise",
            "show prediction high risk and attendance risk semester wise and year wise",
            "which subjects are causing most attendance issues",
            "which branch needs attention first",
            "which semester needs attention first",
            "what should i do first for my students",
            "how should i respond to this risk",
            "what are my operational priorities",
        ],
        "student_drilldown": [
            "show details for student",
            "student drilldown",
            "why is student 880001 high risk",
            "attendance is good but why is student 880001 risky",
            "what action should i take for student 880001",
        ],
    },
    "admin": {
        "import_coverage": [
            "import coverage",
            "how many imported students",
            "scored vs unscored",
        ],
        "admin_governance": [
            "overdue follow up",
            "unhandled escalations",
            "reopened cases",
            "intervention effectiveness",
            "priority queue status",
            "which branch needs attention first",
            "what should we do first institution wide",
            "how do we reduce this",
            "what are the operational priorities",
        ],
        "cohort_summary": [
            "how many high risk",
            "cohort summary",
            "high risk overview",
            "dangerous zone",
            "entered into risk",
            "just entered risk",
            "newly high risk",
            "initial risk",
            "show high risk semester wise year wise",
            "show high risk branch wise",
            "show attendance risk branch wise",
            "show attendance risk gender wise",
            "show attendance risk batch wise",
            "show prediction high risk program wise",
            "show prediction high risk and attendance risk age band wise",
            "show prediction high risk and attendance risk semester wise and year wise",
            "how many students have i grade risk",
            "how many students have r grade risk",
            "which subjects are causing most attendance issues",
            "which semester needs attention first",
        ],
        "student_drilldown": [
            "show details for student",
            "student drilldown",
        ],
    },
}

_INTENT_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "student": {
        "student_self_risk": ["risk", "score", "prediction", "high_risk"],
        "student_self_warning": ["warning"],
        "student_self_profile": ["profile", "email", "contact", "faculty", "counsellor"],
        "student_self_attendance": ["attendance", "subject", "class", "present", "absent", "data", "information", "assignment", "submission", "coursework", "lms", "activity", "engagement", "erp", "finance", "fee", "payment", "dues", "gpa", "cgpa", "marks", "performance", "progress", "login"],
        "student_self_subject_risk": ["i_grade", "r_grade", "eligible", "subject", "weakest", "condonation", "repeat", "safe", "worry", "uncleared", "trouble", "danger", "serious", "panic", "worse", "future"],
        "student_self_plan": ["focus", "week", "routine", "plan", "next", "priority", "attendance", "first", "recover", "recovery", "reduce", "lower", "remove", "alert", "daily", "day_by", "day"],
        "help": ["help", "capabilities"],
        "identity": ["role", "who", "identity"],
    },
    "counsellor": {
        "cohort_summary": ["cohort", "summary", "high_risk", "priority", "overdue", "follow-up", "urgent", "attendance", "i_grade", "r_grade", "subject", "branch", "semester", "action", "operational", "respond", "reduce"],
        "student_drilldown": ["student", "details", "drilldown", "profile"],
        "help": ["help", "capabilities"],
        "identity": ["role", "who", "identity"],
    },
    "admin": {
        "import_coverage": ["import", "coverage", "scored", "unscored"],
        "admin_governance": [
            "overdue",
            "follow-up",
            "escalation",
            "reopened",
            "repeated",
            "priority",
            "queue",
            "intervention",
            "effectiveness",
            "action",
            "operational",
            "reduce",
            "respond",
        ],
        "cohort_summary": [
            "cohort",
            "summary",
            "high_risk",
            "risk",
            "dropped",
            "graduated",
            "studying",
            "newly",
            "initial",
            "recent",
            "dangerous",
            "attendance",
            "i_grade",
            "r_grade",
            "subject",
            "branch",
            "semester",
        ],
        "student_drilldown": ["student", "details", "drilldown", "profile"],
        "help": ["help", "capabilities"],
        "identity": ["role", "who", "identity"],
    },
}


def detect_copilot_intent(*, role: RoleName, message: str) -> CopilotIntent:
    lowered = str(message or "").strip().lower()

    if _is_sensitive_request(lowered):
        return "unsupported"

    if any(token in lowered for token in {"who am i", "my role", "what role"}):
        return "identity"
    if _is_help_request(lowered):
        return "help"

    if role == "student" and (
        any(token in lowered for token in {"lms", "engagement", "activity", "clicks", "resources"})
        and any(
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
    ):
        return "student_self_risk"

    if role == "counsellor" and lowered in {
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
        return "cohort_summary"

    semantic = _semantic_intent_match(role=role, message=lowered)
    if semantic is not None:
        return semantic

    token_match = _keyword_intent_match(role=role, message=lowered)
    if token_match is not None:
        return token_match

    if role == "student":
        if any(
            phrase in lowered
            for phrase in {
                "which semester i am in",
                "which semester am i in",
                "what semester am i in",
                "what semester am i in right now",
                "which year am i in",
                "current semester",
            }
        ):
            return "student_self_attendance"
        if (
            any(token in lowered for token in {"lms", "engagement", "activity", "clicks", "resources"})
            and any(
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
        ):
            return "student_self_risk"
        if (
            "attendance" in lowered
            and any(token in lowered for token in {"why", "but why", "how come", "then why"})
            and any(
                token in lowered
                for token in {
                    "risk",
                    "risky",
                    "at risk",
                    "high alert",
                    "high risk",
                    "put into high",
                    "why am i high",
                    "why high",
                }
            )
        ):
            return "student_self_subject_risk"
        if any(
            token in lowered
            for token in {
                "i grade",
                "r grade",
                "clear this",
                "do not clear this",
                "dont clear this",
                "end sem",
                "weakest subject",
                "subject is in trouble",
                "hurting me most",
                "hurting most",
                "lowest attendance",
                "condonation",
                "repeat grade",
                "am i safe",
                "should i worry",
                "am i in trouble",
                "how bad is my situation",
                "am i doing good",
                "how am i performing",
                "is my performance okay",
                "am i improving or getting worse",
                "uncleared grade issue",
                "older sem",
                "older sems",
            }
        ):
            return "student_self_subject_risk"
        if any(token in lowered for token in {"risk", "score", "prediction"}):
            return "student_self_risk"
        if "warning" in lowered:
            return "student_self_warning"
        if any(token in lowered for token in {"attendance", "subject wise", "subject-wise", "what data do you have", "which data do you have", "what information do you have", "assignment", "submission", "coursework", "lms", "activity", "engagement", "erp", "finance", "fee", "payment", "dues", "gpa", "cgpa", "marks", "performance", "progress", "login", "semester", "year am i in"}):
            return "student_self_attendance"
        if any(
            token in lowered
            for token in {
                "recover",
                "recovery",
                "remove high",
                "reduce my risk",
                "lower my risk",
                "remove the high",
                "get out of high alert",
                "come out of high alert",
                "how can i improve",
                "day by day",
                "day-by-day",
                "daily plan",
                "plan for the week",
                "this week",
                "increase my gpa",
                "improve assignments",
                "coursework priorities",
            }
        ):
            return "student_self_plan"
        if any(token in lowered for token in {"focus", "routine", "next week", "few weeks", "plan my", "what should i do first"}):
            return "student_self_plan"
        if any(token in lowered for token in {"profile", "email", "contact", "faculty", "counsellor"}):
            return "student_self_profile"
        return "unsupported"

    has_student_id = bool(re.search(r"\b(88\d{4,})\b", lowered))
    if has_student_id:
        return "student_drilldown"

    if role == "counsellor":
        if lowered.strip() in {
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
            return "cohort_summary"
        if any(
            token in lowered
            for token in {
                "how many",
                "count",
                "high risk",
                "drop",
                "cohort",
                "summary",
                "urgent",
                "follow-up",
                "followup",
                "priority",
                "overdue",
                "attendance",
                "i grade",
                "r grade",
                "subject",
                "branch",
                "semester",
                "weekly monitoring",
                "monthly monitoring",
                "doing fine now",
                "unresolved",
                "burden",
                "assigned",
                "students",
                "status",
                "list",
                "performance",
                "danger",
                "critical",
                "help them",
                "intervention",
                "actions needed",
                "reduce their risk",
                "struggling",
                "performing poorly",
                "not doing well",
                "in trouble",
                "main issue",
                "main problem",
                "biggest issue",
                "getting worse",
                "improving",
            }
        ):
            return "cohort_summary"
        return "unsupported"

    if any(token in lowered for token in {"import", "coverage", "scored", "unscored"}):
        return "import_coverage"
    if any(
        token in lowered
        for token in {
            "counsellor",
            "duty",
            "follow-up",
            "followup",
            "intervention",
            "resolved",
            "unresolved",
            "overdue",
            "reopened",
            "repeated",
            "priority",
            "queue",
            "escalation",
            "reminder",
            "false alert",
            "effectiveness",
        }
    ):
        return "admin_governance"
    if any(token in lowered for token in {"high risk", "risk", "drop", "cohort", "summary", "attendance", "i grade", "r grade", "subject", "branch", "semester", "trend", "stats"}):
        return "cohort_summary"
    return "unsupported"


def _is_help_request(lowered: str) -> bool:
    return any(
        token in lowered
        for token in {
            "help",
            "what can you do",
            "capabilities",
            "what all data you have",
            "what data you have",
            "what data do you have",
            "what information do you have",
            "what do you know about me",
            "what can i ask",
            "what can i ask you",
            "what all can i ask",
        }
    )


def _semantic_intent_match(*, role: RoleName, message: str) -> CopilotIntent | None:
    examples = _INTENT_EXAMPLES.get(role) or {}
    best_intent: CopilotIntent | None = None
    best_score = 0.0
    for intent, phrases in examples.items():
        for phrase in phrases:
            score = _similarity_ratio(message, phrase)
            if score > best_score:
                best_score = score
                best_intent = intent  # type: ignore[assignment]

    # Threshold tuned to be conservative; only return when meaning is close.
    if best_score >= 0.62:
        return best_intent
    return None


def suggest_copilot_intents(*, role: RoleName, message: str, limit: int = 3) -> list[dict]:
    lowered = str(message or "").strip().lower()
    tokens = _tokenize(lowered)
    examples = _INTENT_EXAMPLES.get(role) or {}
    keywords = _INTENT_KEYWORDS.get(role) or {}
    scored: list[tuple[str, float, list[str]]] = []

    for intent in set(examples.keys()) | set(keywords.keys()):
        phrase_score = _best_phrase_similarity(lowered, examples.get(intent, []))
        keyword_score, matched = _keyword_match_score(tokens, keywords.get(intent, []))
        score = max(phrase_score, keyword_score)
        if score > 0:
            scored.append((intent, score, matched))

    scored.sort(key=lambda item: item[1], reverse=True)
    suggestions = []
    for intent, score, matched in scored[: max(1, limit)]:
        suggestions.append({"intent": intent, "score": round(score, 3), "matched_keywords": matched})
    return suggestions


def _keyword_intent_match(*, role: RoleName, message: str) -> CopilotIntent | None:
    tokens = _tokenize(message)
    best_intent: CopilotIntent | None = None
    best_score = 0.0
    for intent, keywords in (_INTENT_KEYWORDS.get(role) or {}).items():
        score, _matched = _keyword_match_score(tokens, keywords)
        if score > best_score:
            best_score = score
            best_intent = intent  # type: ignore[assignment]
    if best_score >= 0.45:
        return best_intent
    return None


def _similarity_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _best_phrase_similarity(message: str, phrases: list[str]) -> float:
    best = 0.0
    for phrase in phrases:
        score = _similarity_ratio(message, phrase)
        if score > best:
            best = score
    return best


def _keyword_match_score(tokens: set[str], keywords: list[str]) -> tuple[float, list[str]]:
    if not keywords:
        return 0.0, []
    matched = [kw for kw in keywords if kw in tokens]
    score = len(matched) / max(1, len(keywords))
    return score, matched


def _tokenize(message: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", message)
    tokens: set[str] = set(words)
    for idx in range(len(words) - 1):
        tokens.add(f"{words[idx]}_{words[idx + 1]}")
    expanded = set(tokens)
    for token in list(tokens):
        for synonym in _TOKEN_SYNONYMS.get(token, []):
            expanded.add(synonym)
    if "dangerous" in expanded and "zone" in expanded:
        expanded.add("high_risk")
    if "entered" in expanded and "risk" in expanded:
        expanded.add("newly")
    return expanded


def _is_sensitive_request(message: str) -> bool:
    tokens = set(re.findall(r"[a-z0-9]+", message))
    return any(token in _SENSITIVE_TOKENS for token in tokens)
