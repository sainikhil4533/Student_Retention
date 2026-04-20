from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from src.api.auth import AuthContext
from src.api.copilot_memory import resolve_copilot_memory_context
from src.api.copilot_planner import plan_copilot_query
from src.api.copilot_tools import generate_grounded_copilot_answer
from src.db.database import SessionLocal
from src.db.repository import EventRepository


@dataclass
class _SessionRow:
    role: str
    metadata_json: dict


def _run_turn(
    *,
    repository: EventRepository,
    auth: AuthContext,
    prompt: str,
    session_messages: list[_SessionRow],
) -> tuple[str, dict, dict]:
    profiles = repository.get_imported_student_profiles_for_counsellor_identity(
        subject=auth.subject,
        display_name=auth.display_name,
    )
    query_plan = plan_copilot_query(
        role=auth.role,
        message=prompt,
        session_messages=session_messages,
        profiles=profiles,
    )
    semantic_planner = {
        "provider": "deterministic_only",
        "status": "not_used",
        "rewritten_message": None,
    }
    memory = resolve_copilot_memory_context(message=prompt, session_messages=session_messages)
    answer, _tools_used, _limitations, memory_context = generate_grounded_copilot_answer(
        auth=auth,
        repository=repository,
        message=prompt,
        session_messages=session_messages,
        memory=memory,
        query_plan=query_plan.to_dict(),
    )
    session_messages.append(
        _SessionRow(
            role="assistant",
            metadata_json={
                "memory_context": memory_context,
                "semantic_planner": semantic_planner,
            },
        )
    )
    return answer, memory_context, semantic_planner


def main() -> None:
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        imported_profiles = repository.get_imported_student_profiles()
        if not imported_profiles:
            raise SystemExit("No imported student profiles were found.")

        scoped_name = Counter(
            str(getattr(profile, "counsellor_name", "") or "").strip()
            for profile in imported_profiles
            if str(getattr(profile, "counsellor_name", "") or "").strip()
        ).most_common(1)
        if not scoped_name:
            raise SystemExit("No counsellor-assigned imported profiles were found.")
        counsellor_name = scoped_name[0][0]
        counsellor_auth = AuthContext(
            role="counsellor",
            subject=counsellor_name,
            display_name=counsellor_name,
            auth_provider="local_institution_account",
        )

        scoped_profiles = repository.get_imported_student_profiles_for_counsellor_identity(
            subject=counsellor_auth.subject,
            display_name=counsellor_auth.display_name,
        )
        if not scoped_profiles:
            raise SystemExit("No counsellor-scoped profiles were found for the selected counsellor.")

        latest_predictions = {
            int(row.student_id): row for row in repository.get_latest_predictions_for_all_students()
        }
        high_risk_profiles = [
            profile
            for profile in scoped_profiles
            if latest_predictions.get(int(profile.student_id)) is not None
            and int(getattr(latest_predictions[int(profile.student_id)], "final_predicted_class", 0)) == 1
        ]
        if not high_risk_profiles:
            raise SystemExit("No high-risk students were found in the selected counsellor scope.")
        high_risk_profiles.sort(
            key=lambda profile: (
                -float(getattr(latest_predictions[int(profile.student_id)], "final_risk_probability", 0.0) or 0.0),
                int(profile.student_id),
            )
        )
        primary_student_id = int(high_risk_profiles[0].student_id)

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
            high_risk_profiles[0],
        )
        safe_high_risk_student_id = int(safe_high_risk_profile.student_id)

        branch_value = next(
            (
                str(((getattr(profile, "profile_context", None) or {}).get("branch")) or "").strip()
                for profile in scoped_profiles
                if str(((getattr(profile, "profile_context", None) or {}).get("branch")) or "").strip()
            ),
            "",
        )

        one_turn_cases = [
            (
                "assigned students default",
                "students?",
                ["assigned to your counsellor scope", "student_id"],
            ),
            (
                "generic risk default",
                "risk",
                ["prediction high-risk cohort", "student_id"],
            ),
            (
                "scoped drilldown explanation",
                f"why is student {primary_student_id} high risk",
                ["grounded risk explanation", "latest prediction view"],
            ),
            (
                "student action request",
                f"what action should i take for student {primary_student_id}",
                ["first grounded action plan", "first action"],
            ),
            (
                "safe attendance but risky",
                f"attendance is good but why is student {safe_high_risk_student_id} risky",
                ["grounded risk explanation", "attendance view"],
            ),
        ]

        for label, prompt, expected_fragments in one_turn_cases:
            answer, memory_context, semantic = _run_turn(
                repository=repository,
                auth=counsellor_auth,
                prompt=prompt,
                session_messages=[],
            )
            lowered = answer.lower()
            print(f"--- {label}: {prompt} ---")
            print(answer)
            print(memory_context)
            print(semantic)
            assert "clarification needed" not in lowered, f"Unexpected clarification for {label}"
            for fragment in expected_fragments:
                assert fragment.lower() in lowered, f"Missing fragment `{fragment}` for `{label}`"

        followup_session: list[_SessionRow] = []
        first_answer, first_memory, _ = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt=f"why is student {primary_student_id} high risk",
            session_messages=followup_session,
        )
        second_answer, second_memory, second_semantic = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="ok",
            session_messages=followup_session,
        )
        print("--- counsellor drilldown follow-up first turn ---")
        print(first_answer)
        print(first_memory)
        print("--- counsellor drilldown follow-up second turn ---")
        print(second_answer)
        print(second_memory)
        print(second_semantic)
        assert first_memory.get("pending_role_follow_up") == "student_specific_action"
        assert "first grounded action plan" in second_answer.lower()
        assert "clarification needed" not in second_answer.lower()

        grouped_session: list[_SessionRow] = []
        grouped_answer, grouped_memory, _ = _run_turn(
            repository=repository,
            auth=counsellor_auth,
            prompt="show my students high risk branch wise",
            session_messages=grouped_session,
        )
        print("--- counsellor grouped branch turn ---")
        print(grouped_answer)
        print(grouped_memory)
        assert "branch-wise breakdown" in grouped_answer.lower()

        if branch_value:
            filtered_answer, filtered_memory, filtered_semantic = _run_turn(
                repository=repository,
                auth=counsellor_auth,
                prompt=f"show only {branch_value}",
                session_messages=grouped_session,
            )
            print("--- counsellor grouped follow-up filter ---")
            print(filtered_answer)
            print(filtered_memory)
            print(filtered_semantic)
            assert "clarification needed" not in filtered_answer.lower()
            assert "matching students" in filtered_answer.lower()

            top_answer, top_memory, top_semantic = _run_turn(
                repository=repository,
                auth=counsellor_auth,
                prompt="what about top 5",
                session_messages=grouped_session,
            )
            print("--- counsellor grouped top-n follow-up ---")
            print(top_answer)
            print(top_memory)
            print(top_semantic)
            assert "top 5" in top_answer.lower()
            assert "clarification needed" not in top_answer.lower()
            assert top_memory.get("pending_role_follow_up") == "operational_actions"

            continue_answer, continue_memory, continue_semantic = _run_turn(
                repository=repository,
                auth=counsellor_auth,
                prompt="continue",
                session_messages=grouped_session,
            )
            print("--- counsellor grouped continue follow-up ---")
            print(continue_answer)
            print(continue_memory)
            print(continue_semantic)
            assert "grounded operational action list" in continue_answer.lower()
            assert continue_memory.get("response_type") == "action"
            assert continue_memory.get("last_topic") == "cohort_actions"

        print("Counsellor role hardening verification passed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
