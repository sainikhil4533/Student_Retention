from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

CHECKS = [
    "tmp_live_chatbot_prompt_sweep.py",
    "tmp_chatbot_followup_sweep.py",
    "tmp_chatbot_comparison_ambiguity_sweep.py",
    "tmp_live_chatbot_uat_sweep.py",
    "tmp_live_chatbot_mixed_role_sweep.py",
    "tmp_chatbot_cross_signal_sweep.py",
    "tmp_student_dynamic_action_verify.py",
    "tmp_role_operational_planner_verify.py",
    "tmp_student_lms_live_verify.py",
    "tmp_student_topic_switch_live_verify.py",
    "tmp_counsellor_topic_switch_live_verify.py",
    "tmp_admin_topic_switch_live_verify.py",
]


def main() -> None:
    failures: list[str] = []
    for script_name in CHECKS:
        script_path = ROOT / script_name
        print(f"[signoff] running {script_name}")
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(ROOT),
            check=False,
        )
        if completed.returncode != 0:
            failures.append(script_name)
            print(f"[signoff] failed {script_name} exit_code={completed.returncode}")
        else:
            print(f"[signoff] passed {script_name}")

    if failures:
        joined = ", ".join(failures)
        raise SystemExit(f"Chatbot signoff regression failed for: {joined}")

    print("Chatbot signoff regression passed.")


if __name__ == "__main__":
    main()
