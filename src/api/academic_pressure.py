from __future__ import annotations

from typing import Any

from src.db.repository import EventRepository


def build_academic_pressure_snapshot_from_rows(
    *,
    academic_progress_rows: list[object],
    semester_rows: list[object],
    subject_rows: list[object],
    subject_limit: int = 8,
    bucket_limit: int = 8,
    top_student_limit: int = 8,
) -> dict[str, Any]:
    progress_by_student: dict[int, object] = {}
    for row in academic_progress_rows:
        progress_by_student.setdefault(int(row.student_id), row)
    semester_by_student = {int(row.student_id): row for row in semester_rows}
    subjects_by_student: dict[int, list[object]] = {}
    for row in subject_rows:
        subjects_by_student.setdefault(int(row.student_id), []).append(row)

    top_students: list[dict[str, Any]] = []
    subject_buckets: dict[str, dict[str, float | int]] = {}
    branch_buckets: dict[str, dict[str, float | int]] = {}
    semester_buckets: dict[str, dict[str, float | int]] = {}

    for student_id, progress in progress_by_student.items():
        semester = semester_by_student.get(student_id)
        subject_list = subjects_by_student.get(student_id, [])
        weakest_subject = next(
            (row for row in subject_list if row.subject_attendance_percent is not None),
            None,
        )
        top_students.append(
            {
                "student_id": student_id,
                "branch": str(progress.branch or "Unknown"),
                "overall_status": str(getattr(semester, "overall_status", "") or "UNKNOWN"),
                "has_i_grade_risk": bool(getattr(semester, "has_i_grade_risk", False)),
                "has_r_grade_risk": bool(getattr(semester, "has_r_grade_risk", False)),
                "weakest_subject_name": str(getattr(weakest_subject, "subject_name", "") or "Unknown Subject"),
                "weakest_subject_percent": (
                    float(getattr(weakest_subject, "subject_attendance_percent", 0.0))
                    if weakest_subject is not None and getattr(weakest_subject, "subject_attendance_percent", None) is not None
                    else None
                ),
                "current_overall_attendance_percent": (
                    float(getattr(semester, "overall_attendance_percent", 0.0))
                    if semester is not None and getattr(semester, "overall_attendance_percent", None) is not None
                    else None
                ),
            }
        )

        branch_label = str(progress.branch or "Unknown Branch")
        branch_bucket = branch_buckets.setdefault(
            branch_label,
            {
                "total_students": 0,
                "students_with_overall_shortage": 0,
                "students_with_i_grade_risk": 0,
                "students_with_r_grade_risk": 0,
                "attendance_sum": 0.0,
                "attendance_count": 0,
            },
        )
        branch_bucket["total_students"] = int(branch_bucket["total_students"]) + 1
        overall_percent = getattr(semester, "overall_attendance_percent", None)
        if overall_percent is not None:
            branch_bucket["attendance_sum"] = float(branch_bucket["attendance_sum"]) + float(overall_percent)
            branch_bucket["attendance_count"] = int(branch_bucket["attendance_count"]) + 1
        if semester is not None and str(semester.overall_status or "").strip().upper() == "SHORTAGE":
            branch_bucket["students_with_overall_shortage"] = int(branch_bucket["students_with_overall_shortage"]) + 1
        if semester is not None and bool(semester.has_i_grade_risk):
            branch_bucket["students_with_i_grade_risk"] = int(branch_bucket["students_with_i_grade_risk"]) + 1
        if semester is not None and bool(semester.has_r_grade_risk):
            branch_bucket["students_with_r_grade_risk"] = int(branch_bucket["students_with_r_grade_risk"]) + 1

        semester_year = getattr(semester, "year", None) or getattr(progress, "current_year", None)
        semester_number = getattr(semester, "semester", None) or getattr(progress, "current_semester", None)
        semester_mode = str(getattr(semester, "semester_mode", None) or getattr(progress, "semester_mode", None) or "").strip()
        semester_label = "Unknown Semester"
        if semester_year and semester_number:
            semester_label = f"Year {int(semester_year)} Sem {int(semester_number)}"
        elif semester_number:
            semester_label = f"Sem {int(semester_number)}"
        elif semester_year:
            semester_label = f"Year {int(semester_year)}"
        if semester_mode in {"internship", "project_review"}:
            semester_label = f"{semester_label} ({semester_mode.replace('_', ' ')})"

        semester_bucket = semester_buckets.setdefault(
            semester_label,
            {
                "total_students": 0,
                "students_with_overall_shortage": 0,
                "students_with_i_grade_risk": 0,
                "students_with_r_grade_risk": 0,
                "attendance_sum": 0.0,
                "attendance_count": 0,
            },
        )
        semester_bucket["total_students"] = int(semester_bucket["total_students"]) + 1
        if overall_percent is not None:
            semester_bucket["attendance_sum"] = float(semester_bucket["attendance_sum"]) + float(overall_percent)
            semester_bucket["attendance_count"] = int(semester_bucket["attendance_count"]) + 1
        if semester is not None and str(semester.overall_status or "").strip().upper() == "SHORTAGE":
            semester_bucket["students_with_overall_shortage"] = int(semester_bucket["students_with_overall_shortage"]) + 1
        if semester is not None and bool(semester.has_i_grade_risk):
            semester_bucket["students_with_i_grade_risk"] = int(semester_bucket["students_with_i_grade_risk"]) + 1
        if semester is not None and bool(semester.has_r_grade_risk):
            semester_bucket["students_with_r_grade_risk"] = int(semester_bucket["students_with_r_grade_risk"]) + 1

    for row in subject_rows:
        subject_name = str(row.subject_name or "").strip() or "Unknown Subject"
        bucket = subject_buckets.setdefault(
            subject_name,
            {
                "total_students": 0,
                "students_below_threshold": 0,
                "i_grade_students": 0,
                "r_grade_students": 0,
                "attendance_sum": 0.0,
                "attendance_count": 0,
            },
        )
        bucket["total_students"] = int(bucket["total_students"]) + 1
        percent = getattr(row, "subject_attendance_percent", None)
        if percent is not None:
            bucket["attendance_sum"] = float(bucket["attendance_sum"]) + float(percent)
            bucket["attendance_count"] = int(bucket["attendance_count"]) + 1
        status = str(getattr(row, "subject_status", "") or "").strip().upper()
        if status in {"I_GRADE", "R_GRADE"}:
            bucket["students_below_threshold"] = int(bucket["students_below_threshold"]) + 1
        if status == "I_GRADE":
            bucket["i_grade_students"] = int(bucket["i_grade_students"]) + 1
        elif status == "R_GRADE":
            bucket["r_grade_students"] = int(bucket["r_grade_students"]) + 1

    top_students.sort(
        key=lambda item: (
            int(bool(item["has_r_grade_risk"])),
            int(bool(item["has_i_grade_risk"])),
            int(str(item["overall_status"]).upper() == "SHORTAGE"),
            -(float(item["weakest_subject_percent"]) if item["weakest_subject_percent"] is not None else 101.0),
        ),
        reverse=True,
    )

    top_subjects = sorted(
        [
            {
                "subject_name": subject_name,
                "total_students": int(values["total_students"]),
                "students_below_threshold": int(values["students_below_threshold"]),
                "i_grade_students": int(values["i_grade_students"]),
                "r_grade_students": int(values["r_grade_students"]),
                "average_attendance_percent": (
                    round(float(values["attendance_sum"]) / int(values["attendance_count"]), 2)
                    if int(values["attendance_count"]) > 0
                    else None
                ),
                "summary": (
                    f"{int(values['students_below_threshold'])} students are below policy threshold in {subject_name}, "
                    f"including {int(values['r_grade_students'])} R-grade cases and {int(values['i_grade_students'])} I-grade cases."
                ),
            }
            for subject_name, values in subject_buckets.items()
        ],
        key=lambda item: (
            item["r_grade_students"],
            item["students_below_threshold"],
            -(item["average_attendance_percent"] or 0.0),
        ),
        reverse=True,
    )[:subject_limit]

    def _sorted_bucket_items(source: dict[str, dict[str, float | int]]) -> list[dict[str, Any]]:
        return sorted(
            [
                {
                    "bucket_label": label,
                    "total_students": int(values["total_students"]),
                    "students_with_overall_shortage": int(values["students_with_overall_shortage"]),
                    "students_with_i_grade_risk": int(values["students_with_i_grade_risk"]),
                    "students_with_r_grade_risk": int(values["students_with_r_grade_risk"]),
                    "average_overall_attendance_percent": (
                        round(float(values["attendance_sum"]) / int(values["attendance_count"]), 2)
                        if int(values["attendance_count"]) > 0
                        else None
                    ),
                    "summary": (
                        f"{label}: {int(values['students_with_overall_shortage'])} students are below overall attendance, "
                        f"{int(values['students_with_i_grade_risk'])} have I-grade risk, and "
                        f"{int(values['students_with_r_grade_risk'])} have R-grade risk."
                    ),
                }
                for label, values in source.items()
            ],
            key=lambda item: (
                item["students_with_r_grade_risk"],
                item["students_with_overall_shortage"],
                item["students_with_i_grade_risk"],
                -(item["average_overall_attendance_percent"] or 0.0),
            ),
            reverse=True,
        )[:bucket_limit]

    return {
        "total_students": len(progress_by_student),
        "total_students_with_overall_shortage": sum(
            1 for row in semester_rows if str(row.overall_status or "").strip().upper() == "SHORTAGE"
        ),
        "total_students_with_i_grade_risk": sum(1 for row in semester_rows if bool(row.has_i_grade_risk)),
        "total_students_with_r_grade_risk": sum(1 for row in semester_rows if bool(row.has_r_grade_risk)),
        "top_students": top_students[:top_student_limit],
        "top_subjects": top_subjects,
        "branch_pressure": _sorted_bucket_items(branch_buckets),
        "semester_pressure": _sorted_bucket_items(semester_buckets),
    }


def build_academic_pressure_snapshot(
    repository: EventRepository,
    *,
    student_ids: set[int] | None = None,
    subject_limit: int = 8,
    bucket_limit: int = 8,
    top_student_limit: int = 8,
) -> dict[str, Any]:
    academic_progress_rows = repository.get_student_academic_progress_records_for_students(student_ids)
    semester_rows = repository.get_latest_student_semester_progress_records_for_students(student_ids)
    subject_rows = repository.get_current_student_subject_attendance_records_for_students(student_ids)
    return build_academic_pressure_snapshot_from_rows(
        academic_progress_rows=academic_progress_rows,
        semester_rows=semester_rows,
        subject_rows=subject_rows,
        subject_limit=subject_limit,
        bucket_limit=bucket_limit,
        top_student_limit=top_student_limit,
    )
