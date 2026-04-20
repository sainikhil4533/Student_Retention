from src.api.routes.admin_imports import (
    _build_policy_record,
    _build_profile_payload_generalized,
    _build_semester_progress_records,
    _build_student_academic_progress_record,
    _build_subject_attendance_records,
    _build_subject_catalog_index,
    _build_subject_catalog_record,
    _detect_institution_name,
    _evaluate_attendance_policy,
    _validate_institution_contract_columns,
)


def main() -> None:
    sheets = {
        "Admissions": [
            {
                "registerno": "STU001",
                "InstitutionName": "Example University",
                "Branch": "CSE",
                "Batch": "2025",
                "Gender": "Female",
                "AgeBand": "18-22",
                "Attempts": 0,
                "Category": "OC",
                "Region": "Urban",
            }
        ],
        "Registration": [
            {
                "registerno": "STU001",
                "Semester": 3,
                "FinalStatus": "Studying",
                "CurrentYear": 2,
                "SemesterMode": "regular_coursework",
            }
        ],
        "AttendancePolicy": [
            {
                "InstitutionName": "Example University",
                "PolicyYear": "2025",
                "OverallMinPercent": 75,
                "SubjectMinPercent": 75,
                "RGradeBelowPercent": 65,
                "IGradeMinPercent": 65,
                "IGradeMaxPercent": 74.99,
                "CondonationAllowed": "Yes",
                "SummerRepeatForR": "Yes",
                "RepeatInternalsForR": "Yes",
                "EndSemAllowedForI": "Yes",
                "EndSemAllowedForR": "No",
            }
        ],
        "SubjectCatalog": [
            {
                "InstitutionName": "Example University",
                "ProgramType": "UG",
                "Branch": "CSE",
                "Regulation": "R25",
                "Year": 2,
                "Semester": 3,
                "SubjectCode": "CS201",
                "SubjectName": "Database Management Systems",
                "SubjectType": "Theory",
                "Credits": 4,
                "IsElective": "No",
                "Active": "Yes",
            }
        ],
        "Attendance": [
            {
                "registerno": "STU001",
                "Semester": 3,
                "Year": 2,
                "Overall%": 72,
                "SubjectCode": "CS201",
                "Subject%": 62,
                "ConsecutiveAbs": 3,
                "MissedvDays": 4,
                "Trend": "Poor",
            }
        ],
    }

    missing = _validate_institution_contract_columns(sheets)
    assert not missing, f"Unexpected missing columns: {missing}"

    institution_name = _detect_institution_name(sheets)
    assert institution_name == "Example University"

    policy = _build_policy_record(sheets["AttendancePolicy"][0])
    r_grade = _evaluate_attendance_policy(overall_percent=72.0, subject_percent=62.0, policy=policy)
    i_grade = _evaluate_attendance_policy(overall_percent=78.0, subject_percent=70.0, policy=policy)
    safe = _evaluate_attendance_policy(overall_percent=82.0, subject_percent=88.0, policy=policy)

    assert r_grade["subject_status"] == "R_GRADE"
    assert i_grade["subject_status"] == "I_GRADE"
    assert safe["subject_status"] == "SAFE"

    catalog_records = [_build_subject_catalog_record(sheets["SubjectCatalog"][0])]
    catalog_index = _build_subject_catalog_index(catalog_records)

    progress = _build_student_academic_progress_record(
        student_id=880001,
        registerno="STU001",
        institution_name=institution_name,
        admissions_row=sheets["Admissions"][0],
        registration_row=sheets["Registration"][0],
        academic_progress_row=None,
    )
    assert progress is not None
    assert progress["current_semester"] == 3
    assert progress["current_year"] == 2

    profile = _build_profile_payload_generalized(
        student_id=880001,
        registerno="STU001",
        admissions_row=sheets["Admissions"][0],
        registration_row=sheets["Registration"][0],
        support_mapping_row=None,
        academic_progress_row=None,
        institution_name=institution_name,
    )
    assert profile["external_student_ref"] == "STU001"
    assert profile["profile_context"]["registration"]["semester"] == 3

    attendance_records = _build_subject_attendance_records(
        student_id=880001,
        registerno="STU001",
        institution_name=institution_name,
        admissions_row=sheets["Admissions"][0],
        attendance_rows=sheets["Attendance"],
        policy=policy,
        subject_catalog_index=catalog_index,
    )
    assert len(attendance_records) == 1
    assert attendance_records[0]["subject_name"] == "Database Management Systems"
    assert attendance_records[0]["subject_status"] == "R_GRADE"

    semester_progress = _build_semester_progress_records(
        student_id=880001,
        registerno="STU001",
        provided_rows=[],
        attendance_rows=attendance_records,
        registration_row=sheets["Registration"][0],
        academic_progress_row=None,
        policy=policy,
    )
    assert len(semester_progress) == 1
    assert semester_progress[0]["has_r_grade_risk"] is True
    assert semester_progress[0]["overall_status"] == "SHORTAGE"

    print("Generalized foundation verification passed.")


if __name__ == "__main__":
    main()
