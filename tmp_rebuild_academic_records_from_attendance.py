from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import sys
import time

from sqlalchemy import delete


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.db.database import SessionLocal
from src.db.models import StudentAcademicRecord, StudentSubjectAttendanceRecord
from src.db.repository import EventRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild student academic records from subject attendance rows so uncleared I/R burdens persist at subject level."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show projected rebuilt row counts without writing changes.",
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


def _effective_outcome(
    *,
    raw_grade: str | None,
    raw_result_status: str | None,
    attendance_linked_status: str | None,
) -> tuple[str | None, str | None]:
    effective_marker = (
        _normalize_uncleared_token(attendance_linked_status)
        or _normalize_uncleared_token(raw_grade)
        or _normalize_uncleared_token(raw_result_status)
    )
    if effective_marker == "R_GRADE":
        return "R", "Pending R-grade clearance"
    if effective_marker == "I_GRADE":
        return "I", "Pending I-grade clearance"
    return raw_grade, raw_result_status


def _subject_key(*, semester: int | None, subject_code: str | None, subject_name: str | None) -> tuple[int | None, str]:
    return (semester, str(subject_code or subject_name or "").strip().lower())


def main() -> None:
    args = parse_args()
    started_at = time.perf_counter()
    db = SessionLocal()
    try:
        repository = EventRepository(db)
        profiles = repository.get_imported_student_profiles()
        total_students = len(profiles)
        rebuilt_rows = 0
        all_existing_rows = (
            db.query(StudentAcademicRecord)
            .order_by(
                StudentAcademicRecord.student_id.asc(),
                StudentAcademicRecord.semester.asc(),
                StudentAcademicRecord.id.asc(),
            )
            .all()
        )
        all_attendance_rows = (
            db.query(StudentSubjectAttendanceRecord)
            .order_by(
                StudentSubjectAttendanceRecord.student_id.asc(),
                StudentSubjectAttendanceRecord.semester.asc(),
                StudentSubjectAttendanceRecord.id.asc(),
            )
            .all()
        )
        attendance_by_student: dict[int, list[StudentSubjectAttendanceRecord]] = defaultdict(list)
        existing_by_student: dict[int, list[StudentAcademicRecord]] = defaultdict(list)
        for row in all_attendance_rows:
            attendance_by_student[int(row.student_id)].append(row)
        for row in all_existing_rows:
            existing_by_student[int(row.student_id)].append(row)

        all_rebuilt_records: list[dict] = []

        for index, profile in enumerate(profiles, start=1):
            student_id = int(profile.student_id)
            attendance_rows = attendance_by_student.get(student_id, [])
            existing_rows = existing_by_student.get(student_id, [])
            if not attendance_rows and not existing_rows:
                continue
            existing_by_key = {
                _subject_key(
                    semester=row.semester,
                    subject_code=getattr(row, "subject_code", None),
                    subject_name=getattr(row, "subject_name", None),
                ): row
                for row in existing_rows
            }
            semester_defaults: dict[int | None, dict[str, float | None]] = defaultdict(dict)
            for row in existing_rows:
                if row.semester not in semester_defaults:
                    semester_defaults[row.semester] = {
                        "cgpa": getattr(row, "cgpa", None),
                        "backlogs": getattr(row, "backlogs", None),
                    }

            rebuilt_records: list[dict] = []
            for attendance_row in attendance_rows:
                key = _subject_key(
                    semester=attendance_row.semester,
                    subject_code=getattr(attendance_row, "subject_code", None),
                    subject_name=getattr(attendance_row, "subject_name", None),
                )
                source_row = existing_by_key.get(key)
                raw_grade = getattr(source_row, "grade", None) if source_row is not None else None
                raw_result_status = getattr(source_row, "result_status", None) if source_row is not None else None
                attendance_linked_status = getattr(attendance_row, "subject_status", None)
                effective_grade, effective_result_status = _effective_outcome(
                    raw_grade=raw_grade,
                    raw_result_status=raw_result_status,
                    attendance_linked_status=attendance_linked_status,
                )
                existing_context = dict(getattr(source_row, "context_fields", None) or {}) if source_row is not None else {}
                existing_context["rebuilt_from_attendance"] = True
                rebuilt_records.append(
                    {
                        "student_id": student_id,
                        "external_student_ref": getattr(attendance_row, "external_student_ref", None),
                        "institution_name": getattr(attendance_row, "institution_name", None),
                        "branch": getattr(attendance_row, "branch", None),
                        "year": getattr(attendance_row, "year", None),
                        "semester": getattr(attendance_row, "semester", None),
                        "subject_code": getattr(attendance_row, "subject_code", None),
                        "subject_name": getattr(attendance_row, "subject_name", None),
                        "credits": getattr(source_row, "credits", None) if source_row is not None else None,
                        "internal_marks": getattr(source_row, "internal_marks", None) if source_row is not None else None,
                        "external_marks": getattr(source_row, "external_marks", None) if source_row is not None else None,
                        "total_marks": getattr(source_row, "total_marks", None) if source_row is not None else None,
                        "marks": getattr(source_row, "marks", None) if source_row is not None else None,
                        "grade": effective_grade,
                        "result_status": effective_result_status,
                        "attendance_linked_status": attendance_linked_status,
                        "cgpa": (
                            getattr(source_row, "cgpa", None)
                            if source_row is not None and getattr(source_row, "cgpa", None) is not None
                            else semester_defaults.get(getattr(attendance_row, "semester", None), {}).get("cgpa")
                        ),
                        "backlogs": (
                            getattr(source_row, "backlogs", None)
                            if source_row is not None and getattr(source_row, "backlogs", None) is not None
                            else semester_defaults.get(getattr(attendance_row, "semester", None), {}).get("backlogs")
                        ),
                        "context_fields": existing_context,
                    }
                )

            if not rebuilt_records:
                for row in existing_rows:
                    rebuilt_records.append(
                        {
                            "student_id": row.student_id,
                            "external_student_ref": row.external_student_ref,
                            "institution_name": row.institution_name,
                            "branch": row.branch,
                            "year": row.year,
                            "semester": row.semester,
                            "subject_code": row.subject_code,
                            "subject_name": row.subject_name,
                            "credits": row.credits,
                            "internal_marks": row.internal_marks,
                            "external_marks": row.external_marks,
                            "total_marks": row.total_marks,
                            "marks": row.marks,
                            "grade": row.grade,
                            "result_status": row.result_status,
                            "attendance_linked_status": row.attendance_linked_status,
                            "cgpa": row.cgpa,
                            "backlogs": row.backlogs,
                            "context_fields": dict(row.context_fields or {}),
                        }
                    )

            rebuilt_rows += len(rebuilt_records)
            all_rebuilt_records.extend(rebuilt_records)

            if index % 25 == 0 or index == total_students:
                print(
                    "[academic.rebuild] progress "
                    f"processed={index}/{total_students} rebuilt_students={index} "
                    f"rebuilt_rows={rebuilt_rows} dry_run={args.dry_run} "
                    f"elapsed={time.perf_counter() - started_at:.2f}s",
                    flush=True,
                )

        if not args.dry_run:
            db.execute(delete(StudentAcademicRecord))
            if all_rebuilt_records:
                db.bulk_insert_mappings(StudentAcademicRecord, all_rebuilt_records)
            db.commit()

        print(
            "[academic.rebuild] completed "
            f"total_students={total_students} rebuilt_students={total_students} "
            f"rebuilt_rows={rebuilt_rows} dry_run={args.dry_run} "
            f"elapsed={time.perf_counter() - started_at:.2f}s",
            flush=True,
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
