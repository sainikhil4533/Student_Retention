import sys

NEW_CONTEXT_CODE = """

def build_counsellor_data_context(repository, subject: str, display_name: str | None) -> dict:
    from src.api.risk_classification import classify_risk_level
    from src.api.institutional_analytics import resolve_department_label
    from src.api.attendance_engine import build_attendance_summary

    imported_profiles = repository.get_imported_student_profiles_for_counsellor_identity(subject=subject, display_name=display_name)
    imported_ids = {int(p.student_id) for p in imported_profiles}
    all_predictions = repository.get_latest_predictions_for_all_students()

    risk_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "SAFE": 0}
    students_detail = []
    total_students = 0
    prob_sum = 0.0
    att_total = 0.0
    att_count = 0
    grade_counts = defaultdict(int)
    backlog_students = 0
    
    profile_lookup = {int(p.student_id): p for p in imported_profiles}

    for prediction in all_predictions:
        sid = int(prediction.student_id)
        if sid not in imported_ids:
            continue

        total_students += 1
        prob = float(prediction.final_risk_probability)
        prob_sum += prob
        level = classify_risk_level(prob)
        risk_counts[level] += 1

        profile = profile_lookup[sid]
        erp = repository.get_latest_erp_event(sid)
        branch = resolve_department_label(profile, erp)
        context = getattr(erp, "context_fields", None) or {}

        year_label = "unknown"
        for k in ("year_of_study", "academic_year", "year"):
            v = context.get(k)
            if v not in (None, ""):
                year_label = f"Year {v}"
                break
        sem_label = "unknown"
        sv = context.get("semester_number")
        if sv not in (None, ""):
            sem_label = f"Sem {sv}"

        att_pct = None
        att_flag = False
        try:
            att_summary = build_attendance_summary(context)
            raw = att_summary.get("attendance_ratio")
            if raw is not None:
                att_pct = round(float(raw) * 100, 1) if float(raw) <= 1 else round(float(raw), 1)
                att_total += att_pct
                att_count += 1
            att_flag = att_summary.get("attendance_flag", False)
        except Exception:
            pass

        grade = context.get("grade") or context.get("final_grade") or context.get("result")
        if grade:
            grade_counts[str(grade).upper()] += 1
            if str(grade).upper() in ("R", "F", "FAIL", "RA", "DETAINED"):
                backlog_students += 1

        backlogs = context.get("backlogs") or context.get("backlog_count") or context.get("arrears")
        if backlogs is not None:
            try:
                if int(backlogs) > 0:
                    backlog_students += 1
            except (TypeError, ValueError):
                pass

        reg_id = getattr(profile, "student_external_id", None) or str(sid)
        
        students_detail.append({
            "id": sid,
            "reg_id": str(reg_id),
            "name": getattr(profile, "display_name", None) or f"Student {sid}",
            "branch": branch,
            "year": year_label,
            "semester": sem_label,
            "risk_level": level,
            "probability": round(prob, 4),
            "attendance": att_pct,
            "attendance_flag": att_flag,
            "grade": grade,
        })

    students_detail.sort(key=lambda s: s["probability"], reverse=True)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_students": total_students,
        "risk_distribution": risk_counts,
        "avg_risk_probability": round(prob_sum / total_students, 4) if total_students else 0,
        "avg_attendance": round(att_total / att_count, 1) if att_count else None,
        "grade_distribution": dict(grade_counts) if grade_counts else None,
        "backlog_students": backlog_students,
        "students": students_detail,
    }

def get_counsellor_data_context(repository, subject: str, display_name: str | None) -> dict:
    return build_counsellor_data_context(repository, subject, display_name)

def build_student_data_context(repository, student_id: int) -> dict:
    from src.api.risk_classification import classify_risk_level
    from src.api.student_intelligence import build_current_student_intelligence

    prediction = repository.get_latest_prediction(student_id)
    profile = repository.get_student_profile(student_id)
    
    if not profile:
        return {"error": "Student profile not found."}

    prob = float(prediction.final_risk_probability) if prediction else 0.0
    level = classify_risk_level(prob) if prediction else "SAFE"
    
    intelligence = build_current_student_intelligence(repository, student_id)
    
    return {
        "id": student_id,
        "reg_id": getattr(profile, "student_external_id", None) or str(student_id),
        "name": getattr(profile, "display_name", None) or f"Student {student_id}",
        "risk_level": level,
        "probability": round(prob, 4),
        "attendance": intelligence.get("attendance", {}),
        "coursework": intelligence.get("coursework", {}),
        "academic": intelligence.get("academic", {}),
        "recent_interventions": intelligence.get("recent_interventions", []),
    }

def get_student_data_context(repository, student_id: int) -> dict:
    return build_student_data_context(repository, student_id)
"""

with open("src/api/chatbot_engine.py", "r") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if line.startswith("def get_admin_data_context"):
        insert_idx = i + 12
        break

lines.insert(insert_idx, NEW_CONTEXT_CODE)

with open("src/api/chatbot_engine.py", "w") as f:
    f.writelines(lines)
