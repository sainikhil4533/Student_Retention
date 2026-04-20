from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.auth import AuthContext
from src.api.copilot_intents import detect_copilot_intent
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_runtime import COPILOT_PHASE_LABEL, COPILOT_SYSTEM_PROMPT_VERSION
import src.api.copilot_semantic_planner as semantic_planner_module
from src.api.copilot_semantic_planner import plan_copilot_query_with_semantic_assist
from src.api.copilot_tools import generate_grounded_copilot_answer
from src.api.routes.copilot import _opening_message_for_role, _resolved_session_title
from src.db.database import SessionLocal
from src.db.repository import EventRepository


RoleName = Literal["student", "counsellor", "admin"]

CONTINUATION_REPLIES = {
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
}

TRANSIENT_INFRA_ERROR_SNIPPETS = {
    "dbhandler exited",
    "unable to check out connection from the pool due to timeout",
    "connection is bad",
    "connection not open",
    "terminating connection",
}


@dataclass
class TurnSpec:
    prompt: str
    expected_type: str | None = None
    expected_fragments: list[str] = field(default_factory=list)
    allow_clarification: bool = False


@dataclass
class ConversationSpec:
    role: RoleName
    label: str
    conversation: list[TurnSpec]


@dataclass
class FailureRecord:
    type: str
    message: str
    turn_index: int
    prompt: str


@dataclass
class TurnResult:
    prompt: str
    answer: str
    response_type: str
    last_topic: str
    last_intent: str
    failures: list[FailureRecord]
    metadata: dict


@dataclass
class ConversationResult:
    role: RoleName
    label: str
    passed: bool
    failure_count: int
    turns: list[TurnResult]


@dataclass
class DatasetContext:
    student_auth: AuthContext
    counsellor_auth: AuthContext
    admin_auth: AuthContext
    primary_student_id: int
    safe_high_risk_student_id: int
    common_branch: str
    secondary_branch: str
    common_gender: str
    common_batch: str


@dataclass
class _SessionRow:
    role: str
    metadata_json: dict


class InProcessChatbotClient:
    def __init__(
        self,
        repository: EventRepository,
        auth: AuthContext,
        *,
        deterministic_planner_only: bool = False,
    ) -> None:
        self.repository = repository
        self.auth = auth
        self.deterministic_planner_only = deterministic_planner_only
        self.session_messages: list[object] = []
        self.session_id = self._create_session()

    def _create_session(self) -> int:
        now = datetime.now(UTC)
        session = self.repository.create_copilot_chat_session(
            {
                "owner_subject": self.auth.subject,
                "owner_role": self.auth.role,
                "owner_student_id": self.auth.student_id,
                "display_name": self.auth.display_name,
                "title": _resolved_session_title(None, self.auth.role),
                "status": "active",
                "system_prompt_version": COPILOT_SYSTEM_PROMPT_VERSION,
                "last_message_at": now,
            }
        )
        assistant_message = self.repository.add_copilot_chat_message(
            {
                "session_id": int(session.id),
                "role": "assistant",
                "message_type": "text",
                "content": _opening_message_for_role(
                    role=self.auth.role,
                    display_name=self.auth.display_name,
                    opening_message=None,
                ),
                "metadata_json": {
                    "phase": COPILOT_PHASE_LABEL,
                    "response_mode": "foundation",
                },
            }
        )
        self.repository.update_copilot_chat_session(
            int(session.id),
            {"last_message_at": assistant_message.created_at or now},
        )
        self.session_messages = [assistant_message]
        return int(session.id)

    def _role_profiles(self) -> list[object]:
        if self.auth.role == "admin":
            return self.repository.get_imported_student_profiles()
        if self.auth.role == "counsellor":
            return self.repository.get_imported_student_profiles_for_counsellor_identity(
                subject=self.auth.subject,
                display_name=self.auth.display_name,
            )
        return []

    def send(self, prompt: str) -> dict:
        session_messages = list(self.session_messages)
        memory = resolve_copilot_memory_context(message=prompt, session_messages=session_messages)
        if self.deterministic_planner_only:
            original_provider_check = semantic_planner_module._semantic_planner_available
            original_cache_get = semantic_planner_module._get_cached_semantic_hint
            original_cache_store = semantic_planner_module._store_cached_semantic_hint
            semantic_planner_module._semantic_planner_available = lambda: False
            semantic_planner_module._get_cached_semantic_hint = lambda _cache_key: None
            semantic_planner_module._store_cached_semantic_hint = lambda _cache_key, _hint: None
            try:
                query_plan, semantic_planner = plan_copilot_query_with_semantic_assist(
                    role=self.auth.role,
                    message=prompt,
                    session_messages=session_messages,
                    profiles=self._role_profiles(),
                )
            finally:
                semantic_planner_module._semantic_planner_available = original_provider_check
                semantic_planner_module._get_cached_semantic_hint = original_cache_get
                semantic_planner_module._store_cached_semantic_hint = original_cache_store
        else:
            query_plan, semantic_planner = plan_copilot_query_with_semantic_assist(
                role=self.auth.role,
                message=prompt,
                session_messages=session_messages,
                profiles=self._role_profiles(),
            )
        grounded_answer, tools_used, limitations, memory_context = generate_grounded_copilot_answer(
            auth=self.auth,
            repository=self.repository,
            message=prompt,
            session_messages=session_messages,
            memory=memory,
            query_plan=query_plan.to_dict(),
        )
        detected_intent = detect_copilot_intent(role=self.auth.role, message=prompt)
        resolved_intent = str(memory_context.get("intent") or query_plan.primary_intent or detected_intent)
        memory_applied = bool(memory.get("is_follow_up")) or resolved_intent != detected_intent
        user_message = self.repository.add_copilot_chat_message(
            {
                "session_id": self.session_id,
                "role": "user",
                "message_type": "text",
                "content": prompt,
                "metadata_json": {
                    "owner_role": self.auth.role,
                    "owner_student_id": self.auth.student_id,
                    "memory_resolution": {
                        "is_follow_up": bool(memory.get("is_follow_up")),
                        "requested_outcome_status": memory.get("requested_outcome_status"),
                        "explicit_student_id": memory.get("explicit_student_id"),
                    },
                },
            }
        )
        assistant_message = self.repository.add_copilot_chat_message(
            {
                "session_id": self.session_id,
                "role": "assistant",
                "message_type": "text",
                "content": grounded_answer,
                "metadata_json": {
                    "phase": COPILOT_PHASE_LABEL,
                    "response_mode": "grounded_tool_answer",
                    "detected_intent": detected_intent,
                    "resolved_intent": resolved_intent,
                    "memory_applied": memory_applied,
                    "query_plan": query_plan.to_dict(),
                    "semantic_planner": semantic_planner,
                    "grounded_tools_used": tools_used,
                    "limitations": limitations,
                    "memory_context": memory_context,
                },
            }
        )
        self.repository.update_copilot_chat_session(
            self.session_id,
            {
                "last_message_at": assistant_message.created_at or datetime.now(UTC),
                "updated_at": assistant_message.created_at or datetime.now(UTC),
            },
        )
        self.session_messages.extend([user_message, assistant_message])
        return {
            "user_message_id": int(user_message.id),
            "assistant_message_id": int(assistant_message.id),
            "answer": grounded_answer,
            "query_plan": query_plan.to_dict(),
            "semantic_planner": semantic_planner,
            "memory_context": memory_context,
        }


def _normalize_answer(text: str) -> str:
    return " ".join(re.sub(r"\s+", " ", str(text or "").strip().lower()).split())


def _looks_like_unnecessary_clarification(answer: str) -> bool:
    lowered = str(answer or "").strip().lower()
    return (
        "clarification needed" in lowered
        or "could you please clarify" in lowered
        or "what specific analysis or comparison are you interested in" in lowered
        or "you can reply in a short way and i will continue from there" in lowered
    )


def _extract_student_ids(text: str) -> list[int]:
    return [int(value) for value in re.findall(r"\bstudent_id\s+(\d+)\b", str(text or "").lower())]


def _role_scope_student_ids(repository: EventRepository, auth: AuthContext) -> set[int]:
    if auth.role == "student":
        return {int(auth.student_id)} if auth.student_id is not None else set()
    if auth.role == "counsellor":
        profiles = repository.get_imported_student_profiles_for_counsellor_identity(
            subject=auth.subject,
            display_name=auth.display_name,
        )
        return {int(profile.student_id) for profile in profiles}
    return {int(profile.student_id) for profile in repository.get_imported_student_profiles()}


def _validate_turn(
    *,
    repository: EventRepository,
    auth: AuthContext,
    spec: TurnSpec,
    result: dict,
    previous_answer: str | None,
    previous_turn: TurnResult | None,
    turn_index: int,
) -> TurnResult:
    answer = str(result["answer"])
    memory_context = dict(result.get("memory_context") or {})
    response_type = str(memory_context.get("response_type") or "")
    last_topic = str(memory_context.get("last_topic") or "")
    last_intent = str(memory_context.get("last_intent") or "")
    failures: list[FailureRecord] = []

    if not spec.allow_clarification and _looks_like_unnecessary_clarification(answer):
        failures.append(
            FailureRecord(
                type="clarification_failure",
                message="The chatbot asked for clarification on a turn that should have continued or defaulted safely.",
                turn_index=turn_index,
                prompt=spec.prompt,
            )
        )

    if spec.expected_type and response_type != spec.expected_type:
        failures.append(
            FailureRecord(
                type="response_type_failure",
                message=f"Expected response_type `{spec.expected_type}` but got `{response_type or 'missing'}`.",
                turn_index=turn_index,
                prompt=spec.prompt,
            )
        )

    lowered_answer = answer.lower()
    for fragment in spec.expected_fragments:
        if fragment.lower() not in lowered_answer:
            failures.append(
                FailureRecord(
                    type="intent_failure",
                    message=f"Expected grounded fragment `{fragment}` was not present in the answer.",
                    turn_index=turn_index,
                    prompt=spec.prompt,
                )
            )

    if previous_answer is not None and _normalize_answer(answer) == _normalize_answer(previous_answer):
        failures.append(
            FailureRecord(
                type="repetition_failure",
                message="The chatbot repeated the same answer instead of moving the conversation forward.",
                turn_index=turn_index,
                prompt=spec.prompt,
            )
        )

    normalized_prompt = _normalize_answer(spec.prompt)
    if normalized_prompt in CONTINUATION_REPLIES and previous_turn is not None:
        if response_type == previous_turn.response_type and _normalize_answer(answer) == _normalize_answer(previous_turn.answer):
            failures.append(
                FailureRecord(
                    type="followup_failure",
                    message="A continuation prompt did not advance the conversation.",
                    turn_index=turn_index,
                    prompt=spec.prompt,
                )
            )

    mentioned_student_ids = _extract_student_ids(answer)
    allowed_student_ids = _role_scope_student_ids(repository, auth)
    if auth.role in {"student", "counsellor"}:
        out_of_scope_ids = [student_id for student_id in mentioned_student_ids if student_id not in allowed_student_ids]
        if out_of_scope_ids:
            failures.append(
                FailureRecord(
                    type="scope_failure",
                    message=f"Out-of-scope student ids leaked into the answer: {out_of_scope_ids[:5]}",
                    turn_index=turn_index,
                    prompt=spec.prompt,
                )
            )

    return TurnResult(
        prompt=spec.prompt,
        answer=answer,
        response_type=response_type,
        last_topic=last_topic,
        last_intent=last_intent,
        failures=failures,
        metadata={
            "memory_context": memory_context,
            "query_plan": result.get("query_plan"),
            "semantic_planner": result.get("semantic_planner"),
        },
    )


def _build_dataset_context(repository: EventRepository) -> DatasetContext:
    imported_profiles = repository.get_imported_student_profiles()
    if not imported_profiles:
        raise SystemExit("No imported student profiles were found.")

    latest_predictions = {
        int(row.student_id): row for row in repository.get_latest_predictions_for_all_students()
    }
    high_risk_profiles = [
        profile
        for profile in imported_profiles
        if latest_predictions.get(int(profile.student_id)) is not None
        and int(getattr(latest_predictions[int(profile.student_id)], "final_predicted_class", 0)) == 1
    ]
    if not high_risk_profiles:
        raise SystemExit("No high-risk imported student profiles were found.")
    high_risk_profiles.sort(
        key=lambda profile: (
            -float(getattr(latest_predictions[int(profile.student_id)], "final_risk_probability", 0.0) or 0.0),
            int(profile.student_id),
        )
    )
    primary_profile = high_risk_profiles[0]
    safe_high_risk_profile = next(
        (
            profile
            for profile in high_risk_profiles
            if (
                (semester := repository.get_latest_student_semester_progress_record(int(profile.student_id))) is not None
                and (
                    str(getattr(semester, "overall_status", "") or "").strip().upper() == "SAFE"
                    or float(getattr(semester, "overall_attendance_percent", 0.0) or 0.0) >= 75.0
                )
            )
        ),
        primary_profile,
    )

    scoped_name = Counter(  # type: ignore[name-defined]
        str(getattr(profile, "counsellor_name", "") or "").strip()
        for profile in imported_profiles
        if str(getattr(profile, "counsellor_name", "") or "").strip()
    ).most_common(1)
    if not scoped_name:
        raise SystemExit("No counsellor-assigned imported profiles were found.")
    counsellor_name = scoped_name[0][0]

    def _first_context_value(key: str) -> str:
        for profile in imported_profiles:
            value = str(((getattr(profile, "profile_context", None) or {}).get(key)) or "").strip()
            if value:
                return value
        return ""

    distinct_branches: list[str] = []
    for profile in imported_profiles:
        branch = str(((getattr(profile, "profile_context", None) or {}).get("branch")) or "").strip()
        if branch and branch not in distinct_branches:
            distinct_branches.append(branch)

    student_auth = AuthContext(
        role="student",
        subject=str(getattr(primary_profile, "register_no", None) or f"student.{int(primary_profile.student_id)}").lower(),
        student_id=int(primary_profile.student_id),
        display_name=str(getattr(primary_profile, "full_name", None) or getattr(primary_profile, "register_no", None) or f"Student {int(primary_profile.student_id)}"),
        auth_provider="local_institution_account",
    )
    counsellor_auth = AuthContext(
        role="counsellor",
        subject=counsellor_name,
        display_name=counsellor_name,
        auth_provider="local_institution_account",
    )
    admin_auth = AuthContext(
        role="admin",
        subject="admin.retention",
        display_name="Retention Admin",
        auth_provider="local_institution_account",
    )
    return DatasetContext(
        student_auth=student_auth,
        counsellor_auth=counsellor_auth,
        admin_auth=admin_auth,
        primary_student_id=int(primary_profile.student_id),
        safe_high_risk_student_id=int(safe_high_risk_profile.student_id),
        common_branch=_first_context_value("branch") or "CSE",
        secondary_branch=distinct_branches[1] if len(distinct_branches) > 1 else ((_first_context_value("branch") or "CSE") if (_first_context_value("branch") or "CSE") != "ECE" else "EEE"),
        common_gender=_first_context_value("gender") or "Male",
        common_batch=_first_context_value("batch") or "Batch 1",
    )


def _student_conversations() -> list[ConversationSpec]:
    conversations: list[ConversationSpec] = []

    def _single_turn_series(*, label_prefix: str, prompts: list[tuple[str, str]]) -> None:
        for index, (prompt, expected_type) in enumerate(prompts, start=1):
            conversations.append(
                ConversationSpec(
                    role="student",
                    label=f"{label_prefix}_{index:02d}",
                    conversation=[TurnSpec(prompt, expected_type)],
                )
            )

    _single_turn_series(
        label_prefix="student_direct_query",
        prompts=[
            ("what is my attendance", "data"),
            ("show my attendance percentage", "data"),
            ("how much attendance do i have", "data"),
            ("tell my attendance stats", "data"),
            ("what is my assignment submission rate", "data"),
            ("how many assignments did i submit", "data"),
            ("what is my assignment completion %", "data"),
            ("what is my current risk level", "data"),
            ("am i high risk or not", "data"),
            ("what is my risk status", "data"),
            ("show my lms activity", "data"),
            ("how active am i on lms", "data"),
            ("how many days did i login", "data"),
            ("what is my gpa", "data"),
            ("show my previous and current gpa", "data"),
        ],
    )

    _single_turn_series(
        label_prefix="student_natural_language",
        prompts=[
            ("am i doing good", "explanation"),
            ("how am i performing", "explanation"),
            ("is my performance okay", "explanation"),
            ("am i safe academically", "explanation"),
            ("am i in trouble", "explanation"),
            ("should i be worried", "explanation"),
            ("how bad is my situation", "explanation"),
            ("am i improving or getting worse", "explanation"),
        ],
    )

    _single_turn_series(
        label_prefix="student_ambiguous_default",
        prompts=[
            ("attendance", "data"),
            ("assignments", "data"),
            ("risk", "data"),
            ("status", "data"),
            ("performance", "data"),
            ("marks", "data"),
            ("progress", "data"),
        ],
    )

    _single_turn_series(
        label_prefix="student_explanation_query",
        prompts=[
            ("why am i high risk", "explanation"),
            ("what caused my risk", "explanation"),
            ("why is my performance low", "explanation"),
            ("what is affecting my results", "explanation"),
            ("why is my gpa dropping", "explanation"),
            ("what is going wrong", "explanation"),
        ],
    )

    _single_turn_series(
        label_prefix="student_action_query",
        prompts=[
            ("what should i do", "action"),
            ("how can i improve", "action"),
            ("how to reduce my risk", "action"),
            ("how to increase my gpa", "action"),
            ("how to improve assignments", "action"),
            ("what is the best way to recover", "action"),
            ("give me steps to improve", "action"),
        ],
    )

    _single_turn_series(
        label_prefix="student_cross_feature",
        prompts=[
            ("my attendance is good but why am i high risk", "explanation"),
            ("my lms activity is high but performance is low why", "explanation"),
            ("how are assignments affecting my risk", "explanation"),
            ("is finance affecting my performance", "explanation"),
            ("why is my gpa low even with good attendance", "explanation"),
        ],
    )

    _single_turn_series(
        label_prefix="student_emotional",
        prompts=[
            ("am i going to fail", "explanation"),
            ("can i still recover", "explanation"),
            ("is it too late for me", "explanation"),
            ("how serious is my situation", "explanation"),
            ("should i panic", "explanation"),
            ("what happens if i don't improve", "explanation"),
        ],
    )

    _single_turn_series(
        label_prefix="student_edge_query",
        prompts=[
            ("tell me honestly am i safe", "explanation"),
            ("should i worry about my future", "explanation"),
            ("is my situation normal", "explanation"),
            ("am i worse than others", "explanation"),
            ("what if i stop studying", "explanation"),
            ("does attendance really matter", "explanation"),
            ("is lms important", "explanation"),
        ],
    )

    _single_turn_series(
        label_prefix="student_mixed_query",
        prompts=[
            ("how is my attendance and assignments together", "explanation"),
            ("compare my lms and gpa", "explanation"),
            ("which is affecting me more assignments or attendance", "explanation"),
            ("what is my biggest weakness", "explanation"),
        ],
    )

    _single_turn_series(
        label_prefix="student_ir_grade",
        prompts=[
            ("do i have i grade risk", "explanation"),
            ("do i have r grade risk", "explanation"),
            ("do i still have any uncleared i grade or r grade subjects", "explanation"),
            ("if i have r grade risk what should i do first", "action"),
        ],
    )

    conversations.extend(
        [
            ConversationSpec(
                role="student",
                label="student_targeted_data_integrity_lms",
                conversation=[TurnSpec("show my lms activity", "data", ["lms clicks in the last 7 days"])],
            ),
            ConversationSpec(
                role="student",
                label="student_targeted_data_integrity_erp",
                conversation=[TurnSpec("what is my erp details", "data", ["weighted assessment score"])],
            ),
            ConversationSpec(
                role="student",
                label="student_targeted_data_integrity_gpa_current",
                conversation=[TurnSpec("what is my gpa", "data", ["gpa/cgpa"])],
            ),
            ConversationSpec(
                role="student",
                label="student_targeted_data_integrity_gpa_history",
                conversation=[TurnSpec("show my previous and current gpa", "data", ["gpa/cgpa"])],
            ),
            ConversationSpec(
                role="student",
                label="student_targeted_data_integrity_login_days",
                conversation=[TurnSpec("how many days did i login", "data", ["active lms login days"])],
            ),
            ConversationSpec(
                role="student",
                label="student_risk_action_consequence_chain",
                conversation=[
                    TurnSpec("why am i high risk", "explanation"),
                    TurnSpec("ok", "action"),
                    TurnSpec("what should i do", "action"),
                    TurnSpec("continue", "action"),
                    TurnSpec("which is most important", "action"),
                    TurnSpec("what happens if i ignore this", "explanation"),
                    TurnSpec("how fast can i improve", "explanation"),
                    TurnSpec("what if i only fix assignments", "explanation"),
                    TurnSpec("is that enough", "explanation"),
                    TurnSpec("what else should i do", "action"),
                    TurnSpec("give me a full recovery plan", "action"),
                ],
            ),
            ConversationSpec(
                role="student",
                label="student_assignments_followup_chain",
                conversation=[
                    TurnSpec("what is my assignment rate", "data"),
                    TurnSpec("ok", "explanation"),
                    TurnSpec("is it good or bad", "explanation"),
                    TurnSpec("why is it low", "explanation"),
                    TurnSpec("how can i improve it", "action"),
                    TurnSpec("how many assignments should i complete", "action"),
                    TurnSpec("what if i miss next one", "explanation"),
                    TurnSpec("will my risk increase", "explanation"),
                    TurnSpec("by how much", "explanation"),
                    TurnSpec("what should i prioritize now", "action"),
                    TurnSpec("give me a step by step plan", "action"),
                ],
            ),
            ConversationSpec(
                role="student",
                label="student_confusion_followup_chain",
                conversation=[
                    TurnSpec("risk", "data"),
                    TurnSpec("ok", "explanation"),
                    TurnSpec("continue", "action"),
                    TurnSpec("why", "explanation"),
                    TurnSpec("what next", "action"),
                    TurnSpec("ok", "action"),
                    TurnSpec("then", "action"),
                    TurnSpec("what should i do", "action"),
                    TurnSpec("continue", "action"),
                    TurnSpec("more", "action"),
                ],
            ),
            ConversationSpec(
                role="student",
                label="student_contradiction_reasoning_chain",
                conversation=[
                    TurnSpec("my attendance is good why risk", "explanation"),
                    TurnSpec("ok", "action"),
                    TurnSpec("explain more", "explanation"),
                    TurnSpec("what is main problem", "explanation"),
                    TurnSpec("how to fix that", "action"),
                    TurnSpec("what if i don't fix it", "explanation"),
                    TurnSpec("will i fail", "explanation"),
                    TurnSpec("how much time i have", "explanation"),
                    TurnSpec("can i recover fully", "explanation"),
                    TurnSpec("what should i do first", "action"),
                ],
            ),
            ConversationSpec(
                role="student",
                label="student_emotional_mix_chain",
                conversation=[
                    TurnSpec("am i in danger", "explanation"),
                    TurnSpec("ok", "explanation"),
                    TurnSpec("how serious is it", "explanation"),
                    TurnSpec("what caused this", "explanation"),
                    TurnSpec("can i fix it", "action"),
                    TurnSpec("how long will it take", "explanation"),
                    TurnSpec("what if i don't improve", "explanation"),
                    TurnSpec("will i fail", "explanation"),
                    TurnSpec("what is worst case", "explanation"),
                    TurnSpec("what should i do right now", "action"),
                ],
            ),
            ConversationSpec(
                role="student",
                label="student_burden_and_eligibility_chain",
                conversation=[
                    TurnSpec("do i still have any uncleared grade issue from older sems", "explanation"),
                    TurnSpec("ok", "action"),
                    TurnSpec("am i eligible for end sem", "explanation"),
                    TurnSpec("continue", "action"),
                    TurnSpec("what data do you have about me", "data"),
                ],
            ),
            ConversationSpec(
                role="student",
                label="student_ir_grade_followup_chain",
                conversation=[
                    TurnSpec("do i have i grade risk", "explanation"),
                    TurnSpec("ok", "action"),
                    TurnSpec("what subject is in trouble", "explanation"),
                    TurnSpec("what should i do first", "action"),
                    TurnSpec("if i do not clear this what happens", "explanation"),
                    TurnSpec("continue", "action"),
                    TurnSpec("am i eligible for end sem", "explanation"),
                ],
            ),
            ConversationSpec(
                role="student",
                label="student_topic_switch_chain",
                conversation=[
                    TurnSpec("am i falling into risk zone or not", "data"),
                    TurnSpec("what is my lms details", "data"),
                    TurnSpec("ok", "explanation"),
                    TurnSpec("what is my erp details", "data"),
                    TurnSpec("what is my finance details", "data"),
                    TurnSpec("continue", "explanation"),
                    TurnSpec("what is my gpa", "data"),
                ],
            ),
        ]
    )

    return conversations


def _counsellor_conversations(context: DatasetContext) -> list[ConversationSpec]:
    return [
        ConversationSpec(
            role="counsellor",
            label="counsellor_direct_query_variations_a",
            conversation=[
                TurnSpec("which students are high risk", "data", ["student_id"]),
                TurnSpec("show high risk students", "data"),
                TurnSpec("list all risky students", "data"),
                TurnSpec("who are in danger", "data"),
                TurnSpec("show my assigned students", "data", ["assigned to your counsellor scope"]),
                TurnSpec("list my students", "data"),
                TurnSpec("who are under me", "data"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_direct_query_variations_b",
            conversation=[
                TurnSpec("top 5 risky students", "data", ["top 5"]),
                TurnSpec("give me most critical students", "data"),
                TurnSpec("who are worst performing", "data"),
                TurnSpec("how many students are high risk", "data"),
                TurnSpec("total risky students count", "data"),
                TurnSpec("number of students in danger", "data"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_natural_language_queries",
            conversation=[
                TurnSpec("who needs attention", "data"),
                TurnSpec("which students are struggling", "data"),
                TurnSpec("any critical cases", "data"),
                TurnSpec("who should I focus on", "action"),
                TurnSpec("which students are not doing well", "data"),
                TurnSpec("who is in trouble", "data"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_ambiguous_defaults",
            conversation=[
                TurnSpec("students", "data"),
                TurnSpec("risk", "data"),
                TurnSpec("status", "data"),
                TurnSpec("list", "data"),
                TurnSpec("performance", "data"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_explanation_queries",
            conversation=[
                TurnSpec(f"why is student {context.primary_student_id} high risk", "explanation", ["grounded risk explanation"]),
                TurnSpec(f"what caused student {context.primary_student_id} risk", "explanation"),
                TurnSpec("why are many students struggling", "explanation"),
                TurnSpec("what is main issue in my students", "explanation"),
                TurnSpec("why are they performing poorly", "explanation"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_action_queries_a",
            conversation=[
                TurnSpec("what should I do for high risk students", "action", ["grounded operational action list"]),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_action_queries_a2",
            conversation=[
                TurnSpec("how can I help them", "action"),
                TurnSpec("what intervention should I take", "action"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_action_queries_b1",
            conversation=[
                TurnSpec("how to reduce their risk", "action"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_action_queries_b2",
            conversation=[
                TurnSpec("what actions are needed", "action"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_cross_feature_queries",
            conversation=[
                TurnSpec("which students have good attendance but high risk", "data"),
                TurnSpec("students with low lms but good marks", "data"),
                TurnSpec("students with high lms but low performance", "data"),
                TurnSpec("hidden risk students", "data"),
                TurnSpec("students affected by finance", "data"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_filtering_queries",
            conversation=[
                TurnSpec(f"show only {context.common_branch} students", "data"),
                TurnSpec("only final year", "data"),
                TurnSpec("only 3rd year", "data"),
                TurnSpec("only high risk", "data"),
                TurnSpec("only low attendance students", "data"),
                TurnSpec("only students with low assignments", "data"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_analytical_queries",
            conversation=[
                TurnSpec("which group is performing worst", "explanation"),
                TurnSpec("which department has more risk", "explanation"),
                TurnSpec("are my students improving", "explanation"),
                TurnSpec("is risk increasing in my group", "explanation"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_emotional_queries",
            conversation=[
                TurnSpec("who needs urgent help", "data"),
                TurnSpec("who is in serious condition", "data"),
                TurnSpec("which student should I prioritize", "data"),
                TurnSpec("who will fail if ignored", "explanation"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_grouped_followup_chain",
            conversation=[
                TurnSpec("show my students high risk branch wise", "explanation", ["branch-wise breakdown"]),
                TurnSpec(f"show only {context.common_branch}", "data", ["matching students"]),
                TurnSpec("what about top 5", "data", ["top 5"]),
                TurnSpec("continue", "action", ["grounded operational action list"]),
                TurnSpec("risk", "data"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_student_drilldown_chain",
            conversation=[
                TurnSpec(f"why is student {context.primary_student_id} high risk", "explanation", ["grounded risk explanation"]),
                TurnSpec("ok", "action", ["first grounded action plan"]),
                TurnSpec(
                    f"attendance is good but why is student {context.safe_high_risk_student_id} risky",
                    "explanation",
                    ["attendance view"],
                ),
                TurnSpec(f"what action should i take for student {context.primary_student_id}", "action", ["first grounded action plan"]),
                TurnSpec("continue", "action"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_scope_defaults_chain",
            conversation=[
                TurnSpec("students?", "data", ["assigned to your counsellor scope"]),
                TurnSpec("yes", "action", ["grounded operational action list"]),
                TurnSpec("which students have i grade risk", "data", ["i-grade"]),
                TurnSpec("which students have r grade risk", "data", ["r-grade"]),
                TurnSpec("even if they are doing fine now, who still needs weekly monitoring?", "data"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_chain_identify_analyze_act",
            conversation=[
                TurnSpec("which students are high risk", "data"),
                TurnSpec("ok", "action"),
                TurnSpec("show top 3", "data", ["top 3"]),
                TurnSpec("why are they high risk", "explanation"),
                TurnSpec("what is common issue", "explanation"),
                TurnSpec("what should I do first", "action"),
                TurnSpec("which student is most critical", "data"),
                TurnSpec("what happens if I delay", "explanation"),
                TurnSpec("how fast should I act", "action"),
                TurnSpec("give me action plan", "action"),
                TurnSpec("continue", "action"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_chain_filtering_reasoning",
            conversation=[
                TurnSpec("show risky students", "data"),
                TurnSpec(f"only {context.common_branch}", "data", ["matching students"]),
                TurnSpec("ok", "action"),
                TurnSpec(f"why are {context.common_branch} students risky", "explanation"),
                TurnSpec("what is main problem", "explanation"),
                TurnSpec("how to fix it", "action"),
                TurnSpec("which students need immediate help", "data"),
                TurnSpec("what if I only focus on top 3", "explanation"),
                TurnSpec("is that enough", "explanation"),
                TurnSpec("what else should I do", "action"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_chain_ambiguous_stress",
            conversation=[
                TurnSpec("students", "data"),
                TurnSpec("ok", "action"),
                TurnSpec("continue", "action"),
                TurnSpec("who", "data"),
                TurnSpec("why", "explanation"),
                TurnSpec("then", "action"),
                TurnSpec("what next", "action"),
                TurnSpec("ok", "action"),
                TurnSpec("continue", "action"),
                TurnSpec("more", "action"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_chain_cross_feature_reasoning",
            conversation=[
                TurnSpec("which students have good attendance but high risk", "data"),
                TurnSpec("ok", "action"),
                TurnSpec("why is that happening", "explanation"),
                TurnSpec("what is main factor", "explanation"),
                TurnSpec("how can I fix it", "action"),
                TurnSpec("which students are worst", "data"),
                TurnSpec("what should I do for them", "action"),
                TurnSpec("how urgent is it", "explanation"),
                TurnSpec("what if no action is taken", "explanation"),
                TurnSpec("give solution plan", "action"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_chain_priority_planning",
            conversation=[
                TurnSpec("who needs attention", "data"),
                TurnSpec("ok", "action"),
                TurnSpec("who is most critical", "data"),
                TurnSpec("why", "explanation"),
                TurnSpec("what should I do first", "action"),
                TurnSpec("how to prioritize students", "action"),
                TurnSpec("what if I ignore low risk", "explanation"),
                TurnSpec("is that okay", "explanation"),
                TurnSpec("what is best strategy", "action"),
                TurnSpec("give weekly plan", "action"),
            ],
        ),
        ConversationSpec(
            role="counsellor",
            label="counsellor_edge_and_mixed_queries",
            conversation=[
                TurnSpec("who is worst student", "data"),
                TurnSpec("which student will fail", "explanation"),
                TurnSpec("is situation serious", "explanation"),
                TurnSpec("should I worry about my group", "explanation"),
                TurnSpec("are things getting worse", "explanation"),
                TurnSpec("compare attendance and assignments for risky students", "explanation"),
                TurnSpec("which factor is affecting most students", "explanation"),
                TurnSpec("what is biggest issue across my students", "explanation"),
                TurnSpec("which students are improving vs declining", "data"),
            ],
        ),
    ]


def _admin_conversations(context: DatasetContext) -> list[ConversationSpec]:
    conversations: list[ConversationSpec] = []

    def _single_turn_series(*, label_prefix: str, prompts: list[tuple[str, str]]) -> None:
        for index, (prompt, expected_type) in enumerate(prompts, start=1):
            conversations.append(
                ConversationSpec(
                    role="admin",
                    label=f"{label_prefix}_{index:02d}",
                    conversation=[TurnSpec(prompt, expected_type)],
                )
            )

    _single_turn_series(
        label_prefix="admin_direct_query",
        prompts=[
            ("how many students are high risk", "data"),
            ("total number of risky students", "data"),
            ("give count of high risk students", "data"),
            ("total number of students", "data"),
            ("how many active students", "data"),
            ("branch wise student count", "data"),
            ("number of students per department", "data"),
            ("show risk distribution", "data"),
            ("how many low medium high risk students", "data"),
        ],
    )

    _single_turn_series(
        label_prefix="admin_natural_query",
        prompts=[
            ("how is overall performance", "explanation"),
            ("is everything going well", "explanation"),
            ("which area is problematic", "explanation"),
            ("are students doing okay", "explanation"),
            ("is the situation under control", "explanation"),
            ("performance", "explanation"),
        ],
    )

    _single_turn_series(
        label_prefix="admin_ambiguous_query",
        prompts=[
            ("analysis", "data"),
            ("report", "data"),
            ("risk", "data"),
        ],
    )

    _single_turn_series(
        label_prefix="admin_explanation_query",
        prompts=[
            (f"why is {context.common_branch} high risk", "explanation"),
            ("why are many students at risk", "explanation"),
            ("what is causing dropout risk", "explanation"),
            ("which factor is affecting students most", "explanation"),
            ("why is performance declining", "explanation"),
        ],
    )

    _single_turn_series(
        label_prefix="admin_strategy_query",
        prompts=[
            ("what should we do to reduce risk", "action"),
            ("how to improve student retention", "action"),
            ("what strategy should we follow", "action"),
            ("how can we reduce dropout rate", "action"),
            ("what actions should admin take", "action"),
            ("give improvement plan", "action"),
        ],
    )

    _single_turn_series(
        label_prefix="admin_cross_feature_query",
        prompts=[
            ("which branch has good attendance but high risk", "explanation"),
            ("compare lms vs erp impact", "explanation"),
            ("how finance is affecting risk", "explanation"),
            ("which factor impacts performance most", "explanation"),
            ("hidden risk across departments", "explanation"),
        ],
    )

    grouped_prompts: list[tuple[str, str]] = [
        ("branch wise risk", "explanation"),
        ("year wise performance", "explanation"),
        ("risk by department", "explanation"),
        ("risk by year", "explanation"),
        ("performance by branch", "explanation"),
        ("compare 1st year vs final year", "explanation"),
    ]
    if context.common_branch != context.secondary_branch:
        grouped_prompts.append((f"compare {context.common_branch} vs {context.secondary_branch}", "explanation"))
    _single_turn_series(
        label_prefix="admin_grouped_query",
        prompts=grouped_prompts,
    )

    conversations.extend([
        ConversationSpec(
            role="admin",
            label="admin_defaults_strategy_chain",
            conversation=[
                TurnSpec("stats", "data", ["currently high-risk students"]),
                TurnSpec("trend", "data", ["last 30 days"]),
                TurnSpec("what strategy should we take", "action", ["institution-level action list"]),
                TurnSpec("continue", "action", ["action list"]),
            ],
        ),
        ConversationSpec(
            role="admin",
            label="admin_grouped_subset_chain",
            conversation=[
                TurnSpec("branch-wise risk", "explanation", ["branch-wise breakdown"]),
                TurnSpec("only CSE", "data", ["matching students"]),
                TurnSpec("continue", "action", ["institution-level action list"]),
                TurnSpec("year wise also", "explanation"),
            ],
        ),
        ConversationSpec(
            role="admin",
            label="admin_hotspot_and_strategy_chain",
            conversation=[
                TurnSpec("which subjects are causing the most attendance issues", "explanation", ["causing the most attendance issues"]),
                TurnSpec("what strategy should we take", "action", ["institution-level action list"]),
                TurnSpec("risk", "data"),
                TurnSpec("trend", "data", ["last 30 days"]),
            ],
        ),
        ConversationSpec(
            role="admin",
            label="admin_trend_decision_and_edge_queries",
            conversation=[
                TurnSpec("is risk increasing over time", "data"),
                TurnSpec("how is trend of student performance", "data"),
                TurnSpec("is dropout risk rising", "data"),
                TurnSpec("compare current vs previous term", "data"),
                TurnSpec("which branch is worst", "explanation"),
                TurnSpec("where should we focus", "action"),
                TurnSpec("which department is struggling", "explanation"),
                TurnSpec("what is biggest issue overall", "explanation"),
                TurnSpec("where should we take action first", "action"),
                TurnSpec("which group needs immediate attention", "action"),
                TurnSpec("which branch should we prioritize", "action"),
                TurnSpec("what is most critical area", "explanation"),
                TurnSpec("which branch is failing completely", "explanation"),
                TurnSpec("is situation critical", "explanation"),
                TurnSpec("are we in danger", "explanation"),
                TurnSpec("should we be worried", "explanation"),
                TurnSpec("is performance normal", "explanation"),
                TurnSpec("compare attendance and risk across branches", "explanation"),
                TurnSpec("which factor affects most students", "explanation"),
                TurnSpec("which branch has improving vs declining performance", "explanation"),
                TurnSpec("what is biggest weakness overall", "explanation"),
            ],
        ),
        ConversationSpec(
            role="admin",
            label="admin_chain_analysis_comparison_strategy",
            conversation=[
                TurnSpec("branch wise risk", "explanation", ["branch-wise breakdown"]),
                TurnSpec("ok", "action"),
                TurnSpec(f"only {context.common_branch}", "data", ["matching students"]),
                TurnSpec(
                    f"compare with {context.secondary_branch}" if context.common_branch != context.secondary_branch else "compare 1st year vs final year",
                    "explanation",
                ),
                TurnSpec(
                    f"why is {context.common_branch} worse" if context.common_branch != context.secondary_branch else "why is first year worse",
                    "explanation",
                ),
                TurnSpec("what is main factor", "explanation"),
                TurnSpec("what should we fix first", "action"),
                TurnSpec("how long will it take to improve", "action"),
                TurnSpec("what if we don’t act", "explanation"),
                TurnSpec("which branch needs urgent attention", "action"),
                TurnSpec("give strategic plan", "action"),
            ],
        ),
        ConversationSpec(
            role="admin",
            label="admin_chain_data_breakdown_action",
            conversation=[
                TurnSpec("how many students are high risk", "data"),
                TurnSpec("ok", "action"),
                TurnSpec("break it by branch", "explanation"),
                TurnSpec("which branch has highest risk", "explanation"),
                TurnSpec("why", "explanation"),
                TurnSpec("what is affecting them", "explanation"),
                TurnSpec("what actions should we take", "action"),
                TurnSpec("can we reduce risk quickly", "action"),
                TurnSpec("how much improvement is possible", "action"),
                TurnSpec("give detailed plan", "action"),
            ],
        ),
        ConversationSpec(
            role="admin",
            label="admin_chain_ambiguous_stress",
            conversation=[
                TurnSpec("stats", "data"),
                TurnSpec("ok", "action"),
                TurnSpec("continue", "action"),
                TurnSpec("risk", "data"),
                TurnSpec("why", "explanation"),
                TurnSpec("then", "action"),
                TurnSpec("what next", "action"),
                TurnSpec("continue", "action"),
                TurnSpec("more", "action"),
                TurnSpec("explain", "explanation"),
            ],
        ),
        ConversationSpec(
            role="admin",
            label="admin_chain_cross_feature_deep_reasoning",
            conversation=[
                TurnSpec("which branch has good attendance but high risk", "explanation"),
                TurnSpec("ok", "action"),
                TurnSpec("why is that happening", "explanation"),
                TurnSpec("what is main cause", "explanation"),
                TurnSpec("how to fix it", "action"),
                TurnSpec("which branch is worst affected", "explanation"),
                TurnSpec("how urgent is it", "explanation"),
                TurnSpec("what if we ignore this", "explanation"),
                TurnSpec("can situation get worse", "explanation"),
                TurnSpec("give full solution plan", "action"),
            ],
        ),
        ConversationSpec(
            role="admin",
            label="admin_chain_strategy_consequence",
            conversation=[
                TurnSpec("which branch is worst", "explanation"),
                TurnSpec("ok", "action"),
                TurnSpec("why", "explanation"),
                TurnSpec("what should we do", "action"),
                TurnSpec("how fast should we act", "action"),
                TurnSpec("what if no action is taken", "explanation"),
                TurnSpec("what is worst case scenario", "explanation"),
                TurnSpec("can we recover in 1 semester", "action"),
                TurnSpec("what is realistic timeline", "action"),
                TurnSpec("give strategic roadmap", "action"),
            ],
        ),
    ])

    return conversations


def build_conversations(context: DatasetContext, role: RoleName | Literal["all"]) -> list[ConversationSpec]:
    all_specs = [
        *_student_conversations(),
        *_counsellor_conversations(context),
        *_admin_conversations(context),
    ]
    if role == "all":
        return all_specs
    return [spec for spec in all_specs if spec.role == role]


def filter_conversations_by_label(
    conversations: list[ConversationSpec],
    label_filter: str | None,
) -> list[ConversationSpec]:
    if not label_filter:
        return conversations
    normalized = label_filter.strip().lower()
    if normalized.endswith("*"):
        prefix = normalized[:-1]
        return [spec for spec in conversations if spec.label.strip().lower().startswith(prefix)]
    return [spec for spec in conversations if spec.label.strip().lower() == normalized]


def _auth_for_role(context: DatasetContext, role: RoleName) -> AuthContext:
    if role == "student":
        return context.student_auth
    if role == "counsellor":
        return context.counsellor_auth
    return context.admin_auth


def run_conversation_suite(
    *,
    role: RoleName | Literal["all"],
    label: str | None = None,
    deterministic_planner_only: bool = False,
) -> dict:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        context = _build_dataset_context(repository)
        conversations = filter_conversations_by_label(build_conversations(context, role), label)
        if label and not conversations:
            raise SystemExit(f"No conversation matched label: {label}")
        results: list[ConversationResult] = []
        failure_summary: dict[str, int] = {}

        for conversation in conversations:
            print(
                json.dumps(
                    {
                        "event": "conversation_start",
                        "role": conversation.role,
                        "label": conversation.label,
                        "turn_count": len(conversation.conversation),
                    }
                ),
                flush=True,
            )
            client = InProcessChatbotClient(
                repository=repository,
                auth=_auth_for_role(context, conversation.role),
                deterministic_planner_only=deterministic_planner_only,
            )
            previous_answer: str | None = None
            previous_turn: TurnResult | None = None
            turn_results: list[TurnResult] = []
            for index, turn in enumerate(conversation.conversation, start=1):
                print(
                    json.dumps(
                        {
                            "event": "turn_start",
                            "role": conversation.role,
                            "label": conversation.label,
                            "turn_index": index,
                            "prompt": turn.prompt,
                        }
                    ),
                    flush=True,
                )
                raw_result = client.send(turn.prompt)
                turn_result = _validate_turn(
                    repository=repository,
                    auth=_auth_for_role(context, conversation.role),
                    spec=turn,
                    result=raw_result,
                    previous_answer=previous_answer,
                    previous_turn=previous_turn,
                    turn_index=index,
                )
                turn_results.append(turn_result)
                previous_answer = turn_result.answer
                previous_turn = turn_result
                for failure in turn_result.failures:
                    failure_summary[failure.type] = failure_summary.get(failure.type, 0) + 1

            failure_count = sum(len(turn.failures) for turn in turn_results)
            results.append(
                ConversationResult(
                    role=conversation.role,
                    label=conversation.label,
                    passed=failure_count == 0,
                    failure_count=failure_count,
                    turns=turn_results,
                )
            )

        summary = {
            "role_filter": role,
            "generated_at": datetime.now(UTC).isoformat(),
            "conversation_count": len(results),
            "passed_conversations": sum(1 for item in results if item.passed),
            "failed_conversations": sum(1 for item in results if not item.passed),
            "failure_summary": failure_summary,
            "conversations": [
                {
                    "role": item.role,
                    "label": item.label,
                    "passed": item.passed,
                    "failure_count": item.failure_count,
                    "turns": [
                        {
                            "prompt": turn.prompt,
                            "response_type": turn.response_type,
                            "last_topic": turn.last_topic,
                            "last_intent": turn.last_intent,
                            "answer": turn.answer,
                            "failures": [asdict(failure) for failure in turn.failures],
                            "metadata": turn.metadata,
                        }
                        for turn in item.turns
                    ],
                }
                for item in results
            ],
        }
        return summary
    finally:
        db.close()


def _looks_like_transient_infra_error(exc: BaseException) -> bool:
    lowered = str(exc or "").strip().lower()
    return any(snippet in lowered for snippet in TRANSIENT_INFRA_ERROR_SNIPPETS)


def run_conversation_suite_with_retries(
    *,
    role: RoleName | Literal["all"],
    label: str | None = None,
    deterministic_planner_only: bool = False,
    max_attempts: int = 3,
) -> dict:
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return run_conversation_suite(
                role=role,
                label=label,
                deterministic_planner_only=deterministic_planner_only,
            )
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not _looks_like_transient_infra_error(exc):
                raise
            print(
                json.dumps(
                    {
                        "event": "infra_retry",
                        "role": role,
                        "label": label,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                ),
                flush=True,
            )
            time.sleep(float(attempt * 2))
    assert last_exc is not None
    raise last_exc


def _write_results(summary: dict) -> Path:
    output_dir = Path("tests") / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"chatbot_test_results_{summary['role_filter']}_{stamp}.json"
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return output_path


def _write_infrastructure_failure(*, role: str, label: str | None, exc: BaseException) -> Path:
    summary = {
        "role_filter": role,
        "label_filter": label,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "infrastructure_failure",
        "conversation_count": 0,
        "passed_conversations": 0,
        "failed_conversations": 0,
        "failure_summary": {"infrastructure_failure": 1},
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "traceback": traceback.format_exc(),
    }
    return _write_results(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run structured chatbot conversation simulations.")
    parser.add_argument(
        "--role",
        choices=["student", "counsellor", "admin", "all"],
        default="all",
        help="Role-specific pass to run.",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Optional conversation label to run in isolation.",
    )
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="Allow local semantic fallback but block external semantic-provider assistance during tests.",
    )
    args = parser.parse_args()

    try:
        summary = run_conversation_suite_with_retries(
            role=args.role,
            label=args.label,
            deterministic_planner_only=args.deterministic,
        )
        output_path = _write_results(summary)
        print(json.dumps(
            {
                "role_filter": summary["role_filter"],
                "conversation_count": summary["conversation_count"],
                "passed_conversations": summary["passed_conversations"],
                "failed_conversations": summary["failed_conversations"],
                "failure_summary": summary["failure_summary"],
                "results_file": str(output_path),
            },
            indent=2,
        ))
        if summary["failed_conversations"]:
            raise SystemExit(1)
    except SystemExit as exc:
        if exc.code in (0, 1, 2):
            raise
        output_path = _write_infrastructure_failure(role=args.role, label=args.label, exc=exc)
        print(json.dumps(
            {
                "role_filter": args.role,
                "label_filter": args.label,
                "status": "infrastructure_failure",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "results_file": str(output_path),
            },
            indent=2,
        ))
        raise SystemExit(2)
    except Exception as exc:
        output_path = _write_infrastructure_failure(role=args.role, label=args.label, exc=exc)
        print(json.dumps(
            {
                "role_filter": args.role,
                "label_filter": args.label,
                "status": "infrastructure_failure",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "results_file": str(output_path),
            },
            indent=2,
        ))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
