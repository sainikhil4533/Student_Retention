from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.db.database import SessionLocal
from src.db.models import StudentAcademicRecord


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize imported academic rows so unresolved I/R-grade subjects remain pending until cleared."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show how many rows would change without writing updates.",
    )
    return parser.parse_args()


def _normalize_uncleared_token(value: str | None) -> str | None:
    parsed = str(value or "").strip().upper()
    if not parsed:
        return None
    normalized = parsed.replace("-", "_").replace(" ", "_")
    if normalized in {"R", "R_GRADE", "REPEAT", "REPEAT_GRADE"}:
        return "R_GRADE"
    if normalized in {"I", "I_GRADE", "INCOMPLETE"}:
        return "I_GRADE"
    return None


def _effective_outcome(record: StudentAcademicRecord) -> tuple[str | None, str | None, bool]:
    effective_marker = (
        _normalize_uncleared_token(record.attendance_linked_status)
        or _normalize_uncleared_token(record.grade)
        or _normalize_uncleared_token(record.result_status)
    )
    if effective_marker == "R_GRADE":
        return "R", "Pending R-grade clearance", True
    if effective_marker == "I_GRADE":
        return "I", "Pending I-grade clearance", True
    return record.grade, record.result_status, False


def main() -> None:
    args = parse_args()
    started_at = time.perf_counter()
    db = SessionLocal()
    try:
        rows = (
            db.query(StudentAcademicRecord)
            .order_by(
                StudentAcademicRecord.student_id.asc(),
                StudentAcademicRecord.semester.asc(),
                StudentAcademicRecord.id.asc(),
            )
            .all()
        )
        updated_count = 0
        pending_i_count = 0
        pending_r_count = 0

        for row in rows:
            effective_grade, effective_result_status, overridden = _effective_outcome(row)
            if not overridden:
                continue
            if row.grade == effective_grade and row.result_status == effective_result_status:
                if effective_grade == "I":
                    pending_i_count += 1
                elif effective_grade == "R":
                    pending_r_count += 1
                continue

            updated_count += 1
            if effective_grade == "I":
                pending_i_count += 1
            elif effective_grade == "R":
                pending_r_count += 1

            if not args.dry_run:
                context = dict(row.context_fields or {})
                context["raw_grade_before_backfill"] = row.grade
                context["raw_result_status_before_backfill"] = row.result_status
                context["burden_status_backfilled"] = True
                row.grade = effective_grade
                row.result_status = effective_result_status
                row.context_fields = context

        if not args.dry_run:
            db.commit()

        print(
            "[academic.backfill] completed "
            f"total_rows={len(rows)} updated_rows={updated_count} "
            f"pending_i_rows={pending_i_count} pending_r_rows={pending_r_count} "
            f"dry_run={args.dry_run} elapsed={time.perf_counter() - started_at:.2f}s",
            flush=True,
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
