from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime


def resolve_department_label(profile, erp_event) -> str:
    context = getattr(erp_event, "context_fields", None) or {}
    for key in ("programme", "program", "branch", "department", "department_name"):
        value = context.get(key)
        if value not in (None, ""):
            return str(value)
    code_module = getattr(erp_event, "code_module", None)
    if code_module not in (None, ""):
        return f"module_{code_module}"
    if profile is not None:
        education = getattr(profile, "highest_education", None)
        if education not in (None, ""):
            return f"education_{str(education).replace(' ', '_').lower()}"
    return "unassigned_department"


def resolve_semester_label(erp_event) -> str:
    context = getattr(erp_event, "context_fields", None) or {}
    semester_number = context.get("semester_number")
    if semester_number not in (None, ""):
        return f"semester_{semester_number}"
    year_of_study = context.get("year_of_study")
    if year_of_study not in (None, ""):
        return f"year_{year_of_study}"
    academic_phase = context.get("academic_phase")
    if academic_phase not in (None, ""):
        return str(academic_phase)
    code_presentation = getattr(erp_event, "code_presentation", None)
    if code_presentation not in (None, ""):
        return f"presentation_{code_presentation}"
    return "unknown_semester"


def build_institution_risk_overview(
    *,
    student_rows: list[dict],
) -> dict:
    generated_at = datetime.now(UTC)
    department_groups: dict[str, list[dict]] = defaultdict(list)
    semester_groups: dict[str, list[dict]] = defaultdict(list)
    category_groups: dict[str, list[dict]] = defaultdict(list)
    region_groups: dict[str, list[dict]] = defaultdict(list)
    income_groups: dict[str, list[dict]] = defaultdict(list)
    risk_type_groups: dict[str, int] = defaultdict(int)
    outcome_status_groups: dict[str, int] = defaultdict(int)
    heatmap_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)

    total_high_risk_students = 0
    total_medium_risk_students = 0
    total_low_risk_students = 0
    total_safe_students = 0
    total_critical_trigger_students = 0
    total_followup_overdue_students = 0
    total_guardian_escalation_students = 0
    total_reopened_cases = 0
    total_repeated_risk_students = 0

    for row in student_rows:
        department_label = str(row["department_label"])
        semester_label = str(row["semester_label"])
        department_groups[department_label].append(row)
        semester_groups[semester_label].append(row)
        category_groups[str(row.get("category_label") or "unknown_category")].append(row)
        region_groups[str(row.get("region_label") or "unknown_region")].append(row)
        income_groups[str(row.get("income_label") or "unknown_income")].append(row)
        heatmap_groups[(department_label, semester_label)].append(row)

        risk_type = str(row.get("risk_type") or "unavailable")
        risk_type_groups[risk_type] += 1
        outcome_status = str(row.get("outcome_status") or "unknown")
        outcome_status_groups[outcome_status] += 1

        if row["risk_level"] == "HIGH":
            total_high_risk_students += 1
        elif row["risk_level"] == "MEDIUM":
            total_medium_risk_students += 1
        elif row["risk_level"] == "LOW":
            total_low_risk_students += 1
        elif row["risk_level"] == "SAFE":
            total_safe_students += 1

        if row["has_critical_trigger"]:
            total_critical_trigger_students += 1
        if row["followup_overdue"]:
            total_followup_overdue_students += 1
        if row.get("has_guardian_escalation"):
            total_guardian_escalation_students += 1
        if row["is_reopened_case"]:
            total_reopened_cases += 1
        if row["is_repeated_risk_case"]:
            total_repeated_risk_students += 1

    def _bucket_summary(label: str, rows: list[dict]) -> dict:
        total_students = len(rows)
        high_risk_students = sum(1 for row in rows if row["risk_level"] == "HIGH")
        critical_trigger_students = sum(1 for row in rows if row["has_critical_trigger"])
        followup_overdue_students = sum(1 for row in rows if row["followup_overdue"])
        guardian_escalation_students = sum(
            1 for row in rows if row.get("has_guardian_escalation")
        )
        reopened_cases = sum(1 for row in rows if row["is_reopened_case"])
        repeated_risk_students = sum(1 for row in rows if row["is_repeated_risk_case"])
        avg_risk_probability = (
            round(
                sum(float(row["final_risk_probability"]) for row in rows) / total_students,
                4,
            )
            if total_students
            else 0.0
        )

        risk_type_distribution: dict[str, int] = defaultdict(int)
        for row in rows:
            risk_type_distribution[str(row.get("risk_type") or "unavailable")] += 1

        summary = (
            "High-risk concentration needs attention."
            if high_risk_students >= max(2, total_students // 2)
            else (
                "Critical triggers are appearing in this cohort."
                if critical_trigger_students
                else "This cohort is currently stable overall."
            )
        )

        return {
            "label": label,
            "total_students": total_students,
            "high_risk_students": high_risk_students,
            "critical_trigger_students": critical_trigger_students,
            "followup_overdue_students": followup_overdue_students,
            "guardian_escalation_students": guardian_escalation_students,
            "reopened_cases": reopened_cases,
            "repeated_risk_students": repeated_risk_students,
            "average_risk_probability": avg_risk_probability,
            "risk_type_distribution": dict(sorted(risk_type_distribution.items())),
            "summary": summary,
        }

    department_buckets = [
        _bucket_summary(label, rows)
        for label, rows in sorted(
            department_groups.items(),
            key=lambda item: (
                -sum(1 for row in item[1] if row["risk_level"] == "HIGH"),
                item[0],
            ),
        )
    ]
    semester_buckets = [
        _bucket_summary(label, rows)
        for label, rows in sorted(
            semester_groups.items(),
            key=lambda item: (
                -sum(1 for row in item[1] if row["risk_level"] == "HIGH"),
                item[0],
            ),
        )
    ]
    category_buckets = [
        _bucket_summary(label, rows)
        for label, rows in sorted(
            category_groups.items(),
            key=lambda item: (
                -sum(1 for row in item[1] if row["risk_level"] == "HIGH"),
                item[0],
            ),
        )
        if label not in ("unknown_category", "undefined")
    ]
    region_buckets = [
        _bucket_summary(label, rows)
        for label, rows in sorted(
            region_groups.items(),
            key=lambda item: (
                -sum(1 for row in item[1] if row["risk_level"] == "HIGH"),
                item[0],
            ),
        )
        if label not in ("unknown_region", "undefined")
    ]
    income_buckets = [
        _bucket_summary(label, rows)
        for label, rows in sorted(
            income_groups.items(),
            key=lambda item: (
                -sum(1 for row in item[1] if row["risk_level"] == "HIGH"),
                item[0],
            ),
        )
        if label not in ("unknown_income", "undefined")
    ]
    heatmap_cells = [
        {
            "department_label": department_label,
            "semester_label": semester_label,
            "total_students": len(rows),
            "high_risk_students": sum(1 for row in rows if row["risk_level"] == "HIGH"),
            "critical_trigger_students": sum(
                1 for row in rows if row["has_critical_trigger"]
            ),
            "guardian_escalation_students": sum(
                1 for row in rows if row.get("has_guardian_escalation")
            ),
            "average_risk_probability": round(
                sum(float(row["final_risk_probability"]) for row in rows) / len(rows),
                4,
            ),
        }
        for (department_label, semester_label), rows in sorted(heatmap_groups.items())
    ]

    top_risk_types = [
        {"risk_type": risk_type, "student_count": count}
        for risk_type, count in sorted(
            risk_type_groups.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    outcome_distribution = [
        {"outcome_status": status, "student_count": count}
        for status, count in sorted(
            outcome_status_groups.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]

    summary = (
        "Institutional risk concentration is rising in one or more cohorts."
        if total_high_risk_students >= max(2, len(student_rows) // 2 if student_rows else 0)
        else (
            "Operational follow-up is the main concern right now."
            if total_followup_overdue_students or total_reopened_cases
            else "Institution-wide risk remains manageable based on the current live cohort."
        )
    )

    return {
        "generated_at": generated_at,
        "total_students": len(student_rows),
        "total_high_risk_students": total_high_risk_students,
        "total_medium_risk_students": total_medium_risk_students,
        "total_low_risk_students": total_low_risk_students,
        "total_safe_students": total_safe_students,
        "total_critical_trigger_students": total_critical_trigger_students,
        "total_followup_overdue_students": total_followup_overdue_students,
        "total_guardian_escalation_students": total_guardian_escalation_students,
        "total_reopened_cases": total_reopened_cases,
        "total_repeated_risk_students": total_repeated_risk_students,
        "total_dropped_students": int(outcome_status_groups.get("Dropped", 0)),
        "total_studying_students": int(outcome_status_groups.get("Studying", 0)),
        "total_graduated_students": int(outcome_status_groups.get("Graduated", 0)),
        "department_buckets": department_buckets,
        "semester_buckets": semester_buckets,
        "category_buckets": category_buckets,
        "region_buckets": region_buckets,
        "income_buckets": income_buckets,
        "heatmap_cells": heatmap_cells,
        "top_risk_types": top_risk_types,
        "outcome_distribution": outcome_distribution,
        "summary": summary,
    }
