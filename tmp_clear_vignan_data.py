from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.db.database import engine


def load_vignan_student_ids() -> list[int]:
    query = text(
        """
        SELECT student_id
        FROM student_profiles
        WHERE external_student_ref IS NOT NULL
        ORDER BY student_id ASC
        """
    )
    with engine.begin() as connection:
        rows = connection.execute(query).fetchall()
    return [int(row[0]) for row in rows]


def clear_vignan_rows() -> tuple[list[int], dict[str, int]]:
    student_ids = load_vignan_student_ids()
    if not student_ids:
        return [], {}

    delete_statements = {
        "guardian_alert_events": text(
            "DELETE FROM guardian_alert_events WHERE student_id = ANY(:student_ids)"
        ),
        "intervention_actions": text(
            "DELETE FROM intervention_actions WHERE student_id = ANY(:student_ids)"
        ),
        "alert_events": text(
            "DELETE FROM alert_events WHERE student_id = ANY(:student_ids)"
        ),
        "student_warning_events": text(
            "DELETE FROM student_warning_events WHERE student_id = ANY(:student_ids)"
        ),
        "background_jobs": text(
            """
            DELETE FROM background_jobs
            WHERE NULLIF(payload->>'student_id', '') IS NOT NULL
              AND CAST(payload->>'student_id' AS INTEGER) = ANY(:student_ids)
            """
        ),
        "prediction_history": text(
            "DELETE FROM prediction_history WHERE student_id = ANY(:student_ids)"
        ),
        "finance_events": text(
            "DELETE FROM finance_events WHERE student_id = ANY(:student_ids)"
        ),
        "erp_events": text(
            "DELETE FROM erp_events WHERE student_id = ANY(:student_ids)"
        ),
        "lms_events": text(
            "DELETE FROM lms_events WHERE student_id = ANY(:student_ids)"
        ),
        "student_profiles": text(
            "DELETE FROM student_profiles WHERE student_id = ANY(:student_ids)"
        ),
    }

    deleted_counts: dict[str, int] = {}
    with engine.begin() as connection:
        for table, statement in delete_statements.items():
            result = connection.execute(statement, {"student_ids": student_ids})
            deleted_counts[table] = int(result.rowcount or 0)

    return student_ids, deleted_counts


def main() -> None:
    student_ids, deleted_counts = clear_vignan_rows()
    if not student_ids:
        print("No Vignan-imported student profiles were found. Nothing was deleted.")
        return

    print(f"Deleted Vignan cohort for {len(student_ids)} imported students.")
    for table, count in deleted_counts.items():
        print(f"{table}: deleted {count} rows")


if __name__ == "__main__":
    main()
