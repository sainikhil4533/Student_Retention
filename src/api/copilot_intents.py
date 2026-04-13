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
    },
    "counsellor": {
        "cohort_summary": [
            "how many high risk students",
            "urgent follow up cases",
            "priority queue",
            "students needing attention",
        ],
        "student_drilldown": [
            "show details for student",
            "student drilldown",
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
        "help": ["help", "capabilities"],
        "identity": ["role", "who", "identity"],
    },
    "counsellor": {
        "cohort_summary": ["cohort", "summary", "high_risk", "priority", "overdue", "follow-up", "urgent"],
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

    semantic = _semantic_intent_match(role=role, message=lowered)
    if semantic is not None:
        return semantic

    token_match = _keyword_intent_match(role=role, message=lowered)
    if token_match is not None:
        return token_match

    if any(token in lowered for token in {"who am i", "my role", "what role"}):
        return "identity"
    if any(token in lowered for token in {"help", "what can you do", "capabilities"}):
        return "help"

    if role == "student":
        if any(token in lowered for token in {"risk", "score", "prediction"}):
            return "student_self_risk"
        if "warning" in lowered:
            return "student_self_warning"
        if any(token in lowered for token in {"profile", "email", "contact", "faculty", "counsellor"}):
            return "student_self_profile"
        return "unsupported"

    has_student_id = bool(re.search(r"\b(88\d{4,})\b", lowered))
    if has_student_id:
        return "student_drilldown"

    if role == "counsellor":
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
    if any(token in lowered for token in {"high risk", "risk", "drop", "cohort", "summary"}):
        return "cohort_summary"
    return "unsupported"


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
