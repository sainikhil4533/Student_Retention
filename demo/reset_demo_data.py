from __future__ import annotations

from pathlib import Path
import json
import sys

from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.db.database import engine


DEMO_DIR = PROJECT_ROOT / "demo"


def load_demo_student_ids() -> list[int]:
    students = json.loads((DEMO_DIR / "sample_students.json").read_text(encoding="utf-8"))
    return [int(student["student_id"]) for student in students]


def reset_demo_rows() -> dict[str, int]:
    student_ids = load_demo_student_ids()
    tables = [
        "guardian_alert_events",
        "intervention_actions",
        "alert_events",
        "student_warning_events",
        "prediction_history",
        "finance_events",
        "erp_events",
        "lms_events",
        "student_profiles",
    ]
    deleted_counts: dict[str, int] = {}

    with engine.begin() as connection:
        for table in tables:
            result = connection.execute(
                text(f"DELETE FROM {table} WHERE student_id = ANY(:student_ids)"),
                {"student_ids": student_ids},
            )
            deleted_counts[table] = int(result.rowcount or 0)

    return deleted_counts


def main() -> None:
    deleted_counts = reset_demo_rows()
    for table, count in deleted_counts.items():
        print(f"{table}: deleted {count} rows")


if __name__ == "__main__":
    main()
