from __future__ import annotations

from types import SimpleNamespace

from src.api.copilot_tools import _answer_role_operational_actions


def _build_answer(original_message: str) -> tuple[str, dict]:
    answer, _tools, _limitations, memory = _answer_role_operational_actions(
        role="counsellor",
        scope_label="your current counsellor scope",
        repository=None,  # not used in the helper
        auth=None,  # not used in the helper
        planner={
            "version": "cb22",
            "original_message": original_message,
        },
        last_context={},
        academic_summary={
            "top_subjects": [
                {
                    "subject_name": "Big Data Analytics",
                    "students_below_threshold": 3,
                }
            ],
            "branch_pressure": [
                {
                    "bucket_label": "CSE",
                }
            ],
            "semester_pressure": [],
        },
        burden_summary={
            "total_students_with_active_r_grade_burden": 5,
            "total_students_with_active_i_grade_burden": 26,
        },
        risk_breakdown={},
        queue_items=[
            SimpleNamespace(student_id=880082, priority_label="HIGH", sla_status="WITHIN_MONITORING"),
            SimpleNamespace(student_id=880073, priority_label="HIGH", sla_status="WITHIN_MONITORING"),
            SimpleNamespace(student_id=880001, priority_label="HIGH", sla_status="WITHIN_MONITORING"),
        ],
    )
    return answer, memory


def main() -> None:
    help_answer, help_memory = _build_answer("how can I help them")
    intervention_answer, intervention_memory = _build_answer("what intervention should I take")
    reduce_answer, reduce_memory = _build_answer("how to reduce their risk")
    needed_answer, needed_memory = _build_answer("what actions are needed")

    help_lowered = help_answer.lower()
    intervention_lowered = intervention_answer.lower()
    reduce_lowered = reduce_answer.lower()
    needed_lowered = needed_answer.lower()

    assert "support plan" in help_lowered
    assert "personally checking in" in help_lowered
    assert "supportive monthly review" in help_lowered
    assert "student-by-student support list" in help_lowered

    assert "intervention plan" in intervention_lowered
    assert "intervene first on the current queue leaders" in intervention_lowered
    assert "strictest intervention lane" in intervention_lowered
    assert "one blocker, one owner, one next review date" in intervention_lowered

    assert "risk-reduction plan" in reduce_lowered
    assert "risk will come down fastest" in reduce_lowered
    assert "risk-reduction moves" in reduce_lowered
    assert "highest-impact risk-reduction moves" in reduce_lowered

    assert "actions currently needed" in needed_lowered
    assert "immediate action queue" in needed_lowered
    assert "the needed actions are" in needed_lowered

    assert help_answer != intervention_answer
    assert intervention_answer != reduce_answer
    assert reduce_answer != needed_answer

    for memory in [help_memory, intervention_memory, reduce_memory, needed_memory]:
        assert memory.get("pending_role_follow_up") == "operational_actions"
        assert memory.get("intent") == "counsellor_operational_actions"
        assert memory.get("role_scope") == "counsellor"

    print("Counsellor operational action mode verification passed.")


if __name__ == "__main__":
    main()
