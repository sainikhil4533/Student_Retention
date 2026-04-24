"""
Chatbot Engine v3 - Two-tier architecture with follow-up tracking.

Tier 1: Deterministic (always available, no API cost)
  - Handles direct data questions, counts, comparisons, distributions, student listings

Tier 2: LLM AI (when available, for reasoning/strategy/explanation)
  - Falls back to Tier 1 with CONTEXTUAL answer if API fails
"""

from __future__ import annotations

import json
import os
import re
import time
import traceback
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

# ── LLM Configuration ────────────────────────────────────────────
_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
_LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))
_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
_GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


# ── LLM Helpers ───────────────────────────────────────────────────

def _is_llm_available() -> bool:
    if _LLM_PROVIDER == "groq":
        return bool(os.getenv("GROQ_API_KEY", ""))
    return bool(os.getenv("GEMINI_API_KEY", ""))


def _call_llm_text(*, prompt: str, max_tokens: int = 1500) -> str:
    """Call the configured LLM and return plain text response."""
    if _LLM_PROVIDER == "groq":
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        resp = client.chat.completions.create(
            model=_GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    else:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel(_GEMINI_MODEL)
        resp = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=0.3,
            ),
        )
        return resp.text.strip()


def _call_llm_with_retries(*, prompt: str, max_tokens: int = 1500) -> str:
    last_error: Exception | None = None
    for attempt in range(1, _LLM_MAX_RETRIES + 1):
        try:
            print(f"[chatbot] LLM attempt {attempt}/{_LLM_MAX_RETRIES}", flush=True)
            return _call_llm_text(prompt=prompt, max_tokens=max_tokens)
        except Exception as e:
            last_error = e
            err_text = str(e).lower()
            non_retriable = ("billing", "api key", "permission", "unauthenticated", "not found", "invalid auth", "insufficient_quota")
            if any(m in err_text for m in non_retriable):
                print(f"[chatbot] Non-retriable LLM error: {e}", flush=True)
                break
            if attempt < _LLM_MAX_RETRIES:
                if "429" in err_text or "rate limit" in err_text or "exhausted" in err_text:
                    delay = 12.0
                    print(f"[chatbot] Rate limited, retry in {delay}s...", flush=True)
                else:
                    delay = 2.0 * (2 ** (attempt - 1))
                    print(f"[chatbot] Retry in {delay}s: {e}", flush=True)
                time.sleep(delay)
    raise last_error  # type: ignore[misc]


# ── Data Context Builder ──────────────────────────────────────────

def build_admin_data_context(repository) -> dict:
    """Build comprehensive institutional data snapshot."""
    from src.api.risk_classification import classify_risk_level
    from src.api.institutional_analytics import resolve_department_label
    from src.api.attendance_engine import build_attendance_summary

    all_predictions = repository.get_latest_predictions_for_all_students()
    imported_profiles = repository.get_imported_student_profiles()
    imported_ids = {int(p.student_id) for p in imported_profiles}

    risk_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "SAFE": 0}
    branch_data: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "SAFE": 0,
        "prob_sum": 0.0, "att_sum": 0.0, "att_count": 0,
    })
    year_data: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "SAFE": 0, "prob_sum": 0.0,
    })
    students_detail: list[dict] = []
    total_students = 0
    prob_sum = 0.0
    att_total = 0.0
    att_count = 0
    grade_counts: dict[str, int] = defaultdict(int)
    backlog_students = 0

    for prediction in all_predictions:
        sid = int(prediction.student_id)
        if sid not in imported_ids:
            continue

        total_students += 1
        prob = float(prediction.final_risk_probability)
        prob_sum += prob
        level = classify_risk_level(prob)
        risk_counts[level] += 1

        profile = repository.get_student_profile(sid)
        erp = repository.get_latest_erp_event(sid)
        branch = resolve_department_label(profile, erp)
        context = getattr(erp, "context_fields", None) or {}

        # Year/Semester
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

        # Attendance
        att_pct = None
        att_flag = False
        try:
            att_summary = build_attendance_summary(context)
            raw = att_summary.get("attendance_ratio")
            if raw is not None:
                att_pct = round(float(raw) * 100, 1) if float(raw) <= 1 else round(float(raw), 1)
                att_total += att_pct
                att_count += 1
                branch_data[branch]["att_sum"] += att_pct
                branch_data[branch]["att_count"] += 1
            att_flag = att_summary.get("attendance_flag", False)
        except Exception:
            pass

        # Grades / backlogs from context
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

        # Branch + year aggregation
        branch_data[branch]["total"] += 1
        branch_data[branch][level] += 1
        branch_data[branch]["prob_sum"] += prob

        year_data[year_label]["total"] += 1
        year_data[year_label][level] += 1
        year_data[year_label]["prob_sum"] += prob

        # Counsellor
        counsellor = getattr(profile, "counsellor_name", None) or "Unassigned"

        # Student IDs
        reg_id = getattr(profile, "external_student_ref", None) or str(sid)

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
            "counsellor": counsellor,
        })

    students_detail.sort(key=lambda s: s["probability"], reverse=True)

    # Branch summary
    branch_summary = []
    for bname, bd in sorted(branch_data.items()):
        if bname.startswith(("unknown", "unassigned")):
            continue
        avg_p = bd["prob_sum"] / bd["total"] if bd["total"] else 0
        avg_a = bd["att_sum"] / bd["att_count"] if bd["att_count"] else None
        branch_summary.append({
            "branch": bname, "total": bd["total"],
            "high": bd["HIGH"], "medium": bd["MEDIUM"], "low": bd["LOW"], "safe": bd["SAFE"],
            "avg_risk_probability": round(avg_p, 4),
            "avg_attendance": round(avg_a, 1) if avg_a else None,
            "high_risk_pct": round(bd["HIGH"] / bd["total"] * 100, 1) if bd["total"] else 0,
        })
    branch_summary.sort(key=lambda b: b["high_risk_pct"], reverse=True)

    # Year summary
    year_summary = []
    for yname, yd in sorted(year_data.items()):
        if yname == "unknown":
            continue
        avg_p = yd["prob_sum"] / yd["total"] if yd["total"] else 0
        year_summary.append({
            "year": yname, "total": yd["total"],
            "high": yd["HIGH"], "medium": yd["MEDIUM"], "low": yd["LOW"], "safe": yd["SAFE"],
            "avg_risk_probability": round(avg_p, 4),
        })

    # Counsellor workload
    c_load: dict[str, dict] = defaultdict(lambda: {"total": 0, "high": 0})
    for s in students_detail:
        c_load[s["counsellor"]]["total"] += 1
        if s["risk_level"] == "HIGH":
            c_load[s["counsellor"]]["high"] += 1
    counsellor_summary = [
        {"name": cn, **cd}
        for cn, cd in sorted(c_load.items(), key=lambda x: x[1]["high"], reverse=True)
    ]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_students": total_students,
        "risk_distribution": risk_counts,
        "avg_risk_probability": round(prob_sum / total_students, 4) if total_students else 0,
        "avg_attendance": round(att_total / att_count, 1) if att_count else None,
        "grade_distribution": dict(grade_counts) if grade_counts else None,
        "backlog_students": backlog_students,
        "branch_wise": branch_summary,
        "year_wise": year_summary,
        "counsellor_workload": counsellor_summary,
        "students": students_detail,
    }


# ── Counsellor Data Context Builder ──────────────────────────────

def build_counsellor_data_context(repository, subject: str, display_name: str | None) -> dict:
    """Build comprehensive data context filtered to the counsellor's assigned students."""
    from src.api.risk_classification import classify_risk_level
    from src.api.institutional_analytics import resolve_department_label
    from src.api.attendance_engine import build_attendance_summary

    imported_profiles = repository.get_imported_student_profiles_for_counsellor_identity(
        subject=subject, display_name=display_name,
    )
    imported_ids = {int(p.student_id) for p in imported_profiles}
    all_predictions = repository.get_latest_predictions_for_all_students()
    profile_lookup = {int(p.student_id): p for p in imported_profiles}

    risk_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "SAFE": 0}
    students_detail: list[dict] = []
    total_students = 0
    prob_sum = 0.0
    att_total = 0.0
    att_count = 0
    total_interventions = 0
    backlog_student_count = 0

    for prediction in all_predictions:
        sid = int(prediction.student_id)
        if sid not in imported_ids:
            continue
        total_students += 1
        prob = float(prediction.final_risk_probability)
        prob_sum += prob
        level = classify_risk_level(prob)
        risk_counts[level] += 1

        profile = profile_lookup.get(sid)
        erp = repository.get_latest_erp_event(sid)
        branch = resolve_department_label(profile, erp)
        context = getattr(erp, "context_fields", None) or {}

        att_pct = None
        try:
            att_summary = build_attendance_summary(context)
            raw = att_summary.get("attendance_ratio")
            if raw is not None:
                att_pct = round(float(raw) * 100, 1) if float(raw) <= 1 else round(float(raw), 1)
                att_total += att_pct
                att_count += 1
        except Exception:
            pass

        # Grade / backlogs
        grade = context.get("grade") or context.get("final_grade") or context.get("result")
        backlogs = context.get("backlogs") or context.get("backlog_count") or context.get("arrears")
        cgpa = context.get("cgpa")
        if backlogs:
            try:
                if int(backlogs) > 0:
                    backlog_student_count += 1
            except (TypeError, ValueError):
                pass

        # Subject-wise attendance deficits (subjects below 75%)
        subjects_at_risk = []
        try:
            subj_records = repository.get_current_student_subject_attendance_records(sid)
            for rec in subj_records:
                if rec.subject_attendance_percent is not None and rec.subject_attendance_percent < 75:
                    subjects_at_risk.append({
                        "subject": rec.subject_name,
                        "attendance_pct": rec.subject_attendance_percent,
                        "grade_consequence": rec.grade_consequence,
                    })
        except Exception:
            pass

        # Intervention history
        interventions = []
        try:
            intv_list = repository.get_intervention_history_for_student(sid)
            for intv in intv_list[:3]:  # last 3 interventions
                total_interventions += 1
                interventions.append({
                    "status": intv.action_status,
                    "actor": intv.actor_name,
                    "notes": (intv.notes or "")[:100],
                    "outcome": intv.outcome_status,
                    "date": str(getattr(intv, "created_at", "")),
                })
        except Exception:
            pass

        # Financial status
        fee_overdue = None
        try:
            fin = repository.get_latest_finance_event(sid)
            if fin and fin.fee_overdue_amount:
                fee_overdue = round(float(fin.fee_overdue_amount), 2)
        except Exception:
            pass

        # AI insights from prediction
        ai_insights = getattr(prediction, "ai_insights", None)
        recommended_actions = getattr(prediction, "recommended_actions", None)

        reg_id = getattr(profile, "external_student_ref", None) or str(sid)
        students_detail.append({
            "id": sid,
            "reg_id": str(reg_id),
            "name": getattr(profile, "display_name", None) or f"Student {sid}",
            "branch": branch,
            "risk_level": level,
            "probability": round(prob, 4),
            "attendance": att_pct,
            "grade": grade,
            "cgpa": cgpa,
            "backlogs": backlogs,
            "subjects_at_risk": subjects_at_risk,
            "interventions": interventions,
            "fee_overdue": fee_overdue,
            "ai_insights": ai_insights,
            "recommended_actions": recommended_actions,
        })

    students_detail.sort(key=lambda s: s["probability"], reverse=True)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_students": total_students,
        "risk_distribution": risk_counts,
        "avg_risk_probability": round(prob_sum / total_students, 4) if total_students else 0,
        "avg_attendance": round(att_total / att_count, 1) if att_count else None,
        "backlog_student_count": backlog_student_count,
        "total_interventions": total_interventions,
        "students": students_detail,
    }


# ── Student Data Context Builder ─────────────────────────────────

def build_student_data_context(repository, student_id: int) -> dict:
    """Build comprehensive personal data context locked to a single student."""
    from src.api.risk_classification import classify_risk_level
    from src.api.attendance_engine import build_attendance_summary

    prediction = repository.get_latest_prediction_for_student(student_id)
    profile = repository.get_student_profile(student_id)
    erp = repository.get_latest_erp_event(student_id)
    context = getattr(erp, "context_fields", None) or {}

    prob = float(prediction.final_risk_probability) if prediction else 0.0
    level = classify_risk_level(prob) if prediction else "SAFE"

    # ── Attendance ──
    att_pct = None
    try:
        att_summary = build_attendance_summary(context)
        raw = att_summary.get("attendance_ratio")
        if raw is not None:
            att_pct = round(float(raw) * 100, 1) if float(raw) <= 1 else round(float(raw), 1)
    except Exception:
        pass

    # ── Subject-wise attendance ──
    subject_attendance = []
    try:
        subj_records = repository.get_current_student_subject_attendance_records(student_id)
        for rec in subj_records:
            subject_attendance.append({
                "subject": rec.subject_name,
                "subject_code": rec.subject_code,
                "attendance_pct": rec.subject_attendance_percent,
                "status": rec.subject_status,
                "grade_consequence": rec.grade_consequence,
                "end_sem_eligible": rec.end_sem_eligible,
                "classes_conducted": rec.classes_conducted,
                "classes_attended": rec.classes_attended,
                "trend": rec.trend,
            })
    except Exception:
        pass

    # ── LMS engagement ──
    lms_summary = {}
    try:
        from src.api.feature_summaries import build_lms_summary_from_events
        lms_events = repository.get_lms_events_for_student(student_id)
        if lms_events:
            lms_summary = build_lms_summary_from_events(lms_events)
    except Exception:
        pass

    # ── Assessment / ERP details ──
    assessment = {}
    if erp:
        assessment = {
            "submission_rate": round(float(erp.assessment_submission_rate or 0) * 100, 1),
            "weighted_score": round(float(erp.weighted_assessment_score or 0), 1),
            "late_submissions": int(erp.late_submission_count or 0),
            "total_completed": int(erp.total_assessments_completed or 0),
            "score_trend": round(float(erp.assessment_score_trend or 0), 2),
            "cgpa": context.get("cgpa"),
            "backlog_count": context.get("backlog_count"),
        }

    # ── Financial status ──
    finance = {}
    try:
        fin_event = repository.get_latest_finance_event(student_id)
        if fin_event:
            finance = {
                "fee_overdue": round(float(fin_event.fee_overdue_amount or 0), 2),
                "delay_days": int(fin_event.fee_delay_days or 0),
                "payment_status": fin_event.payment_status or "unknown",
            }
    except Exception:
        pass

    # ── AI insights & recommended actions from prediction ──
    ai_insights = None
    recommended_actions = None
    risk_trend = None
    stability = None
    trigger_alerts = None
    if prediction:
        ai_insights = getattr(prediction, "ai_insights", None)
        recommended_actions = getattr(prediction, "recommended_actions", None)
        risk_trend = getattr(prediction, "risk_trend", None)
        stability = getattr(prediction, "stability", None)
        trigger_alerts = getattr(prediction, "trigger_alerts", None)

    # ── Academic progress ──
    academic_progress = {}
    try:
        progress = repository.get_student_academic_progress_record(student_id)
        if progress:
            academic_progress = {
                "branch": progress.branch,
                "current_year": progress.current_year,
                "current_semester": progress.current_semester,
                "academic_status": progress.current_academic_status,
                "standing": progress.standing_label,
                "total_backlogs": progress.total_backlogs,
            }
    except Exception:
        pass

    # ── Semester progress ──
    semester_progress = {}
    try:
        sem = repository.get_latest_student_semester_progress_record(student_id)
        if sem:
            semester_progress = {
                "overall_attendance_pct": sem.overall_attendance_percent,
                "subjects_below_75": sem.subjects_below_75_count,
                "subjects_below_65": sem.subjects_below_65_count,
                "has_i_grade_risk": sem.has_i_grade_risk,
                "has_r_grade_risk": sem.has_r_grade_risk,
                "eligibility": sem.current_eligibility,
            }
    except Exception:
        pass

    grade = context.get("grade") or context.get("final_grade") or context.get("result")
    backlogs = context.get("backlogs") or context.get("backlog_count") or context.get("arrears")

    return {
        "id": student_id,
        "reg_id": getattr(profile, "external_student_ref", None) or str(student_id) if profile else str(student_id),
        "name": getattr(profile, "display_name", None) or f"Student {student_id}" if profile else f"Student {student_id}",
        "risk_level": level,
        "probability": round(prob, 4),
        "attendance": att_pct,
        "grade": grade,
        "backlogs": backlogs,
        "semester": context.get("semester_number"),
        "year": context.get("year_of_study") or context.get("academic_year"),
        "subject_attendance": subject_attendance,
        "lms_engagement": lms_summary,
        "assessment": assessment,
        "finance": finance,
        "ai_insights": ai_insights,
        "recommended_actions": recommended_actions,
        "risk_trend": risk_trend,
        "stability": stability,
        "trigger_alerts": trigger_alerts,
        "academic_progress": academic_progress,
        "semester_progress": semester_progress,
    }


# ── Data context cache ────────────────────────────────────────────
_context_cache: dict[str, Any] = {"data": None, "timestamp": 0.0}
_counsellor_cache: dict[str, Any] = {}   # keyed by subject
_student_cache: dict[str, Any] = {}      # keyed by student_id
_CACHE_TTL = 300


def get_admin_data_context(repository) -> dict:
    now = time.time()
    if _context_cache["data"] and (now - _context_cache["timestamp"]) < _CACHE_TTL:
        return _context_cache["data"]
    print("[chatbot] Building admin data context...", flush=True)
    ctx = build_admin_data_context(repository)
    _context_cache["data"] = ctx
    _context_cache["timestamp"] = now
    print(f"[chatbot] Context ready: {ctx['total_students']} students", flush=True)
    return ctx


def get_counsellor_data_context(repository, subject: str, display_name: str | None) -> dict:
    now = time.time()
    cached = _counsellor_cache.get(subject)
    if cached and (now - cached["timestamp"]) < _CACHE_TTL:
        return cached["data"]
    print("[chatbot] Building counsellor data context...", flush=True)
    ctx = build_counsellor_data_context(repository, subject, display_name)
    _counsellor_cache[subject] = {"data": ctx, "timestamp": now}
    print(f"[chatbot] Counsellor context ready: {ctx['total_students']} students", flush=True)
    return ctx


def get_student_data_context(repository, student_id: int) -> dict:
    now = time.time()
    cached = _student_cache.get(student_id)
    if cached and (now - cached["timestamp"]) < _CACHE_TTL:
        return cached["data"]
    print(f"[chatbot] Building student data context for {student_id}...", flush=True)
    ctx = build_student_data_context(repository, student_id)
    _student_cache[student_id] = {"data": ctx, "timestamp": now}
    return ctx


# ── Follow-up context tracker ────────────────────────────────────
_session_context: dict[int, dict] = {}


def _get_session_ctx(session_id: int) -> dict:
    if session_id not in _session_context:
        _session_context[session_id] = {
            "last_category": None,
            "last_filter": None,
            "last_answer": None,
            "last_result_set": None,   # full list of results for pagination
            "last_offset": 0,          # current pagination offset
            "last_page_size": 10,      # items per page
        }
    return _session_context[session_id]


def _update_session_ctx(session_id: int, **kwargs):
    ctx = _get_session_ctx(session_id)
    ctx.update(kwargs)


def _paginate_next(session_id: int, formatter, title: str = "Results") -> str | None:
    """Return the next page of results from the stored result set."""
    sctx = _get_session_ctx(session_id)
    result_set = sctx.get("last_result_set")
    if not result_set:
        return None
    offset = sctx.get("last_offset", 0)
    page_size = sctx.get("last_page_size", 10)
    next_offset = offset + page_size
    if next_offset >= len(result_set):
        return f"That's all — you've seen all **{len(result_set)}** results."
    page = result_set[next_offset:next_offset + page_size]
    sctx["last_offset"] = next_offset
    remaining = len(result_set) - next_offset - len(page)
    answer = formatter(page, offset=next_offset, total=len(result_set))
    if remaining > 0:
        answer += f"\n\n_Showing {next_offset + 1}-{next_offset + len(page)} of {len(result_set)}. Say **\"more\"** to see next {min(remaining, page_size)}._"
    else:
        answer += f"\n\n_Showing {next_offset + 1}-{next_offset + len(page)} of {len(result_set)}. That's all._"
    sctx["last_answer"] = answer
    return answer



# ── Formatting helpers ────────────────────────────────────────────

def _fmt_risk_overview(ctx: dict) -> str:
    rd = ctx["risk_distribution"]
    t = ctx["total_students"]
    if not t:
        return "No students are currently being tracked."
    lines = [
        f"**Institutional Risk Overview** ({t} students)\n",
        f"- HIGH Risk: {rd['HIGH']} students ({rd['HIGH']/t*100:.1f}%)",
        f"- MEDIUM Risk: {rd['MEDIUM']} students ({rd['MEDIUM']/t*100:.1f}%)",
        f"- LOW Risk: {rd['LOW']} students ({rd['LOW']/t*100:.1f}%)",
        f"- SAFE: {rd['SAFE']} students ({rd['SAFE']/t*100:.1f}%)",
        f"\nAverage Risk Probability: {ctx['avg_risk_probability']:.0%}",
    ]
    if ctx.get("avg_attendance"):
        lines.append(f"Average Attendance: {ctx['avg_attendance']}%")
    return "\n".join(lines)


def _fmt_branch_table(branches: list) -> str:
    if not branches:
        return "No branch/department data available."
    lines = ["**Branch-Wise Risk Breakdown:**\n"]
    for b in branches:
        att = f" | Att: {b['avg_attendance']}%" if b.get("avg_attendance") else ""
        lines.append(
            f"- **{b['branch']}**: {b['total']} students | "
            f"HIGH: {b['high']} ({b['high_risk_pct']}%) | "
            f"MED: {b['medium']} | LOW: {b['low']} | SAFE: {b['safe']}{att}"
        )
    return "\n".join(lines)


def _fmt_year_table(years: list) -> str:
    if not years:
        return "No year-wise data available."
    lines = ["**Year-Wise Risk Breakdown:**\n"]
    for y in years:
        lines.append(
            f"- **{y['year']}**: {y['total']} students | "
            f"HIGH: {y['high']} | MED: {y['medium']} | LOW: {y['low']} | SAFE: {y['safe']} | "
            f"Avg Risk: {y['avg_risk_probability']:.0%}"
        )
    return "\n".join(lines)


def _detect_output_mode(msg: str) -> str:
    """Detect what format the user wants the output in."""
    if any(w in msg for w in ("name only", "names only", "just names", "only names", "give names")):
        return "names_only"
    if any(w in msg for w in ("id only", "ids only", "registration id", "reg id", "just ids", "only ids")):
        return "ids_only"
    return "full"


def _fmt_student_list(students: list, limit: int = 10, title: str = "Students", output_mode: str = "full") -> str:
    if not students:
        return "No students found matching the criteria."
    if output_mode == "count_only":
        return f"**{len(students)} students** match the criteria."
    shown = students[:limit]
    if output_mode == "names_only":
        lines = [f"**{title}** ({len(students)} total, showing {len(shown)}):\n"]
        for i, s in enumerate(shown, 1):
            lines.append(f"{i}. {s['name']}")
        return "\n".join(lines)
    if output_mode == "ids_only":
        lines = [f"**{title}** ({len(students)} total, showing {len(shown)}):\n"]
        for i, s in enumerate(shown, 1):
            lines.append(f"{i}. {s.get('reg_id', s['id'])}")
        return "\n".join(lines)
    lines = [f"**{title}** ({len(students)} total, showing top {len(shown)}):\n"]
    for i, s in enumerate(shown, 1):
        att = f" | Att: {s['attendance']}%" if s.get("attendance") is not None else ""
        lines.append(
            f"{i}. **{s['name']}** (ID: {s.get('reg_id', s['id'])}) - "
            f"{s['risk_level']} Risk ({s['probability']:.0%}){att}"
        )
    return "\n".join(lines)


def _extract_risk_filter(msg: str) -> str | None:
    """Extract risk level from message text."""
    if "high" in msg:
        return "HIGH"
    if "medium" in msg or "moderate" in msg:
        return "MEDIUM"
    if "low" in msg:
        return "LOW"
    if "safe" in msg:
        return "SAFE"
    return None


def _extract_branch_filter(msg: str, branches: list) -> str | None:
    """Extract branch name from message."""
    for b in branches:
        bname = b["branch"].lower().replace("_", " ")
        if bname in msg or bname.replace(" ", "") in msg.replace(" ", ""):
            return b["branch"]
    return None


# ── Tier 1: Admin Deterministic Answer Engine ─────────────────────

def generate_deterministic_answer(message: str, ctx: dict, chat_history: list[dict], session_id: int, repository=None):
    """
    Try to answer with data alone. Returns None only for questions that
    truly need AI reasoning (why, strategy, complex analysis).
    """
    msg = message.lower().strip()
    sctx = _get_session_ctx(session_id)
    output_mode = _detect_output_mode(msg)

    # ──────────── FOLLOW-UP HANDLING ────────────
    if msg in ("ok", "okay", "yes", "continue", "go on", "more", "next", "and", "then", "show more", "next page"):
        def _page_fmt(page, offset=0, total=0):
            lines = []
            for i, s in enumerate(page, offset + 1):
                att = f" | Att: {s['attendance']}%" if s.get('attendance') is not None else ''
                lines.append(f"{i}. **{s['name']}** (ID: {s.get('reg_id', s['id'])}) - {s['risk_level']} Risk ({s['probability']:.0%}){att}")
            return "\n".join(lines)
        paged = _paginate_next(session_id, _page_fmt)
        if paged:
            return paged
        prev = sctx.get("last_answer")
        if prev:
            return prev
        return _fmt_risk_overview(ctx)

    # ──────────── COUNTING QUESTIONS ────────────
    is_count_q = any(k in msg for k in (
        "how many", "count", "total", "number of",
        "give count", "tell count", "students are",
    ))

    if is_count_q:
        # PRIORITY 1: Attendance-related counts
        if any(k in msg for k in ("attendance", "absent", "low attendance")):
            flagged = [s for s in ctx["students"] if s.get("attendance_flag") or (s.get("attendance") is not None and s["attendance"] < 75)]
            answer = f"**{len(flagged)} students** have attendance below 75%."
            _update_session_ctx(session_id, last_category="attendance", last_filter=None, last_answer=answer)
            return answer

        # PRIORITY 2: Backlog counts
        if any(k in msg for k in ("backlog", "arrear", "detained")):
            answer = f"**{ctx['backlog_students']} students** have backlogs/arrears."
            _update_session_ctx(session_id, last_category="backlogs", last_filter=None, last_answer=answer)
            return answer

        # PRIORITY 3: Grade counts
        if any(k in msg for k in ("i grade", "r grade", "grade", "grades")):
            gd = ctx.get("grade_distribution")
            if gd:
                lines = ["**Grade Distribution:**\n"]
                for g, c in sorted(gd.items()):
                    lines.append(f"- **{g}** grade: {c} students")
                answer = "\n".join(lines)
            else:
                answer = (
                    "Grade-specific data (I-grade, R-grade) is not directly stored in the current dataset. "
                    "The system predicts dropout risk based on **17 features**: LMS engagement, "
                    "assessment scores, submission rates, and attendance.\n\n"
                    f"Students classified as **HIGH risk (>=50%)** are most likely to face academic failure. "
                    f"Currently **{ctx['risk_distribution']['HIGH']} students** are at HIGH risk."
                )
            _update_session_ctx(session_id, last_category="grades", last_filter=None, last_answer=answer)
            return answer

        # PRIORITY 4: Multiple risk levels mentioned
        mentioned_levels = []
        for lv in ("high", "medium", "low", "safe"):
            if lv in msg:
                mentioned_levels.append(lv.upper())
        if len(mentioned_levels) >= 2:
            answer = _fmt_risk_overview(ctx)
            _update_session_ctx(session_id, last_category="risk_overview", last_filter=None, last_answer=answer)
            return answer

        # PRIORITY 5: Single risk level
        risk_filter = _extract_risk_filter(msg)
        if risk_filter:
            count = ctx["risk_distribution"][risk_filter]
            answer = f"There are **{count} {risk_filter} risk students** out of {ctx['total_students']} total."
            _update_session_ctx(session_id, last_category="count",
                                last_filter={"risk_level": risk_filter}, last_answer=answer)
            return answer

        # PRIORITY 6: Generic student count
        if any(w in msg for w in ("student", "active", "total", "all")):
            answer = f"There are **{ctx['total_students']} students** currently tracked in the retention system."
            _update_session_ctx(session_id, last_category="count", last_filter=None, last_answer=answer)
            return answer

    # ──────────── STUDENT LISTING QUESTIONS ────────────
    wants_list = any(k in msg for k in (
        "show", "list", "give details", "give me details", "give list",
        "give me the list", "details", "top", "ids", "registration",
        "names", "who are", "which students", "tell me about",
    ))

    if wants_list:
        top_match = re.search(r"top\s*(\d+)", msg)
        limit = int(top_match.group(1)) if top_match else 10

        risk_filter = _extract_risk_filter(msg)
        if risk_filter:
            filtered = [s for s in ctx["students"] if s["risk_level"] == risk_filter]
            answer = _fmt_student_list(filtered, limit=limit, title=f"{risk_filter} Risk Students", output_mode=output_mode)
            if len(filtered) > limit:
                answer += f"\n\n_Showing 1-{limit} of {len(filtered)}. Say **\"more\"** to see the next page._"
            _update_session_ctx(session_id, last_category="student_list",
                                last_filter={"risk_level": risk_filter}, last_answer=answer,
                                last_result_set=filtered, last_offset=0)
            return answer

        if any(w in msg for w in ("among them", "of them", "from them", "of those", "among those")):
            prev_filter = (sctx.get("last_filter") or {}).get("risk_level")
            if prev_filter:
                filtered = [s for s in ctx["students"] if s["risk_level"] == prev_filter]
                answer = _fmt_student_list(filtered, limit=limit, title=f"Top {limit} {prev_filter} Risk Students", output_mode=output_mode)
                _update_session_ctx(session_id, last_category="student_list",
                                    last_filter={"risk_level": prev_filter}, last_answer=answer,
                                    last_result_set=filtered, last_offset=0)
                return answer

        branch_filter = _extract_branch_filter(msg, ctx["branch_wise"])
        if branch_filter:
            filtered = [s for s in ctx["students"] if s["branch"] == branch_filter]
            answer = _fmt_student_list(filtered, limit=limit, title=f"Students in {branch_filter}", output_mode=output_mode)
            if len(filtered) > limit:
                answer += f"\n\n_Showing 1-{limit} of {len(filtered)}. Say **\"more\"** to see the next page._"
            _update_session_ctx(session_id, last_category="student_list",
                                last_filter={"branch": branch_filter}, last_answer=answer,
                                last_result_set=filtered, last_offset=0)
            return answer

        all_students = ctx["students"]
        answer = _fmt_student_list(all_students, limit=limit, title="Students by Highest Risk", output_mode=output_mode)
        if len(all_students) > limit:
            answer += f"\n\n_Showing 1-{limit} of {len(all_students)}. Say **\"more\"** to see the next page._"
        _update_session_ctx(session_id, last_category="student_list", last_filter=None, last_answer=answer,
                            last_result_set=all_students, last_offset=0)
        return answer

    # ──────────── BRANCH-WISE ────────────
    if any(k in msg for k in ("branch wise", "branch-wise", "by branch", "per branch",
                               "by department", "per department", "department wise",
                               "department-wise", "branch risk", "risk by department",
                               "risk by branch", "break it by branch", "branch count",
                               "branch breakdown")):
        answer = _fmt_branch_table(ctx["branch_wise"])
        _update_session_ctx(session_id, last_category="branch_wise", last_filter=None, last_answer=answer)
        return answer

    # ──────────── YEAR-WISE ────────────
    if any(k in msg for k in ("year wise", "year-wise", "by year", "per year", "risk by year",
                               "year breakdown", "semester wise", "year performance")):
        answer = _fmt_year_table(ctx["year_wise"])
        _update_session_ctx(session_id, last_category="year_wise", last_filter=None, last_answer=answer)
        return answer

    # ──────────── RISK DISTRIBUTION / OVERVIEW ────────────
    if any(k in msg for k in ("risk distribution", "risk breakdown", "overview",
                               "show risk", "risk summary")):
        answer = _fmt_risk_overview(ctx)
        _update_session_ctx(session_id, last_category="risk_overview", last_filter=None, last_answer=answer)
        return answer

    # ──────────── AMBIGUOUS SHORT INPUTS ────────────
    if msg in ("stats", "statistics", "overview", "summary", "report", "risk",
               "performance", "analysis", "trend", "data", "info", "status",
               "health", "dashboard"):
        answer = _fmt_risk_overview(ctx) + "\n\n" + _fmt_branch_table(ctx["branch_wise"])
        _update_session_ctx(session_id, last_category="risk_overview", last_filter=None, last_answer=answer)
        return answer

    # ──────────── BACKLOG / GRADE QUESTIONS ────────────
    if any(k in msg for k in ("backlog", "arrear", "detained", "backlogs")):
        answer = f"**{ctx['backlog_students']} students** have backlogs/arrears in the system."
        gd = ctx.get("grade_distribution")
        if gd:
            answer += "\n\n**Grade Distribution:**\n"
            for g, c in sorted(gd.items()):
                answer += f"- **{g}**: {c} students\n"
        _update_session_ctx(session_id, last_category="backlogs", last_filter=None, last_answer=answer)
        return answer

    if any(k in msg for k in ("i grade", "r grade", "grade", "grades", "result", "pass", "fail")):
        gd = ctx.get("grade_distribution")
        if gd:
            lines = ["**Grade Distribution:**\n"]
            for g, c in sorted(gd.items()):
                lines.append(f"- **{g}**: {c} students")
            answer = "\n".join(lines)
        else:
            answer = (
                "Grade-specific data (I-grade, R-grade) is not directly stored in the current dataset. "
                "The system predicts dropout risk based on **17 features**: LMS engagement (clicks, logins), "
                "assessment scores, submission rates, and attendance patterns.\n\n"
                "However, students classified as **HIGH risk (>=50% dropout probability)** are the ones most likely to end up with backlogs or fail grades.\n\n"
                f"Currently, there are **{ctx['risk_distribution']['HIGH']} HIGH risk students** who need immediate attention."
            )
        _update_session_ctx(session_id, last_category="grades", last_filter=None, last_answer=answer)
        return answer

    # ──────────── SPECIFIC BRANCH QUERY ────────────
    branch_filter = _extract_branch_filter(msg, ctx["branch_wise"])
    is_reasoning_q = any(w in msg for w in ("why", "how", "what", "compare", "vs", "versus"))
    if branch_filter and len(msg.split()) <= 4 and not is_reasoning_q:
        bd = next((b for b in ctx["branch_wise"] if b["branch"] == branch_filter), None)
        if bd:
            att = f"\n- Average Attendance: {bd['avg_attendance']}%" if bd.get('avg_attendance') else ""
            answer = (
                f"**{bd['branch']} Department Overview:**\n\n"
                f"- Total Students: **{bd['total']}**\n"
                f"- HIGH Risk: {bd['high']} ({bd['high_risk_pct']}%)\n"
                f"- MEDIUM Risk: {bd['medium']}\n"
                f"- LOW Risk: {bd['low']}\n"
                f"- SAFE: {bd['safe']}\n"
                f"- Average Risk Probability: {bd['avg_risk_probability']:.0%}{att}"
            )
            _update_session_ctx(session_id, last_category="branch_detail",
                                last_filter={"branch": branch_filter}, last_answer=answer)
            return answer

    # ──────────── NEEDS LLM (reasoning/strategy/comparison/explanation) ────────────
    return None


# ── Tier 1: Counsellor Deterministic Answer Engine ────────────────

def generate_counsellor_deterministic_answer(message: str, ctx: dict, chat_history: list[dict], session_id: int):
    """Deterministic answers for counsellor role."""
    msg = message.lower().strip()
    sctx = _get_session_ctx(session_id)

    students = ctx.get("students", [])
    rd = ctx.get("risk_distribution", {})
    total = ctx.get("total_students", 0)

    # Follow-up: pagination or repeat
    if msg in ("ok", "okay", "yes", "continue", "go on", "more", "next", "show more", "next page"):
        def _page_fmt(page, offset=0, total=0):
            lines = []
            for i, s in enumerate(page, offset + 1):
                att = f" | Att: {s['attendance']}%" if s.get("attendance") is not None else ""
                lines.append(f"{i}. **{s['name']}** - {s['risk_level']} Risk ({s['probability']:.0%}){att}")
            return "\n".join(lines)
        paged = _paginate_next(session_id, _page_fmt)
        if paged:
            return paged
        prev = sctx.get("last_answer")
        if prev:
            return prev

    # "among them" / "of those" follow-up
    if any(w in msg for w in ("among them", "of them", "from them", "of those", "among those")):
        prev_filter = (sctx.get("last_filter") or {}).get("risk_level")
        if prev_filter:
            filtered = [s for s in students if s["risk_level"] == prev_filter]
            risk_filter = _extract_risk_filter(msg)
            if risk_filter and risk_filter != prev_filter:
                filtered = [s for s in students if s["risk_level"] == risk_filter]
            answer = _fmt_student_list(filtered, limit=10, title=f"Your {prev_filter} Risk Students")
            _update_session_ctx(session_id, last_category="student_list",
                                last_filter={"risk_level": prev_filter}, last_answer=answer,
                                last_result_set=filtered, last_offset=0)
            return answer

    # Specific student lookup by name or ID
    if any(k in msg for k in ("tell me about", "details of", "info on", "about student",
                               "what about", "how is", "status of", "profile of")):
        for s in students:
            sname = (s.get("name") or "").lower()
            sreg = str(s.get("reg_id", "")).lower()
            sid = str(s.get("id", "")).lower()
            if sname and sname in msg or sreg and sreg in msg or sid in msg:
                lines = [f"**Student Profile: {s['name']}** (ID: {s.get('reg_id', s['id'])})\n"]
                lines.append(f"- **Risk:** {s['risk_level']} ({s['probability']:.0%})")
                lines.append(f"- **Branch:** {s.get('branch', 'N/A')}")
                if s.get("attendance") is not None:
                    lines.append(f"- **Attendance:** {s['attendance']}%")
                if s.get("cgpa"):
                    lines.append(f"- **CGPA:** {s['cgpa']}")
                if s.get("backlogs"):
                    lines.append(f"- **Backlogs:** {s['backlogs']}")
                if s.get("fee_overdue"):
                    lines.append(f"- **Fee Overdue:** ₹{s['fee_overdue']}")
                if s.get("subjects_at_risk"):
                    subjs = ", ".join(f"{sr['subject']} ({sr['attendance_pct']}%)" for sr in s["subjects_at_risk"][:4])
                    lines.append(f"- **Subjects at Risk:** {subjs}")
                if s.get("interventions"):
                    latest = s["interventions"][0]
                    lines.append(f"- **Last Intervention:** {latest['status']} by {latest['actor']} ({latest['outcome']})")
                if s.get("recommended_actions"):
                    recs = s["recommended_actions"]
                    if isinstance(recs, list) and recs:
                        lines.append(f"\n**AI Recommendation:** {recs[0]}")
                answer = "\n".join(lines)
                _update_session_ctx(session_id, last_category="student_detail", last_answer=answer)
                return answer

    # Risk overview for counsellor's cohort
    if msg in ("stats", "overview", "summary", "report", "risk", "status", "dashboard"):
        lines = [
            f"**Your Student Cohort Overview** ({total} students)\n",
            f"- HIGH Risk: {rd.get('HIGH', 0)}",
            f"- MEDIUM Risk: {rd.get('MEDIUM', 0)}",
            f"- LOW Risk: {rd.get('LOW', 0)}",
            f"- SAFE: {rd.get('SAFE', 0)}",
        ]
        if ctx.get("avg_attendance"):
            lines.append(f"\nAverage Attendance: {ctx['avg_attendance']}%")
        if ctx.get("backlog_student_count"):
            lines.append(f"Students with Backlogs: {ctx['backlog_student_count']}")
        if ctx.get("total_interventions"):
            lines.append(f"Recent Interventions: {ctx['total_interventions']}")
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="risk_overview", last_answer=answer)
        return answer

    # Backlogs
    if any(k in msg for k in ("backlog", "arrear", "fail", "detained")):
        backlog_students = []
        for s in students:
            try:
                if s.get("backlogs") and int(s["backlogs"]) > 0:
                    backlog_students.append(s)
            except (ValueError, TypeError):
                pass
        if not backlog_students:
            return "You currently have no students with recorded backlogs."
        lines = [f"**Students with Backlogs** ({len(backlog_students)} total):\n"]
        for i, s in enumerate(backlog_students[:10], 1):
            lines.append(f"{i}. **{s['name']}** - {s['backlogs']} backlogs (Risk: {s['probability']:.0%})")
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="backlogs", last_answer=answer)
        return answer

    # Interventions
    if any(k in msg for k in ("intervention", "warning", "action", "history")):
        total_intv = ctx.get("total_interventions", 0)
        if not total_intv:
            return "No recent interventions recorded for your students."
        lines = [f"**Recent Interventions** ({total_intv} recorded recently):\n"]
        shown = 0
        for s in students:
            for inv in s.get("interventions", []):
                if shown >= 10: break
                lines.append(f"- **{s['name']}**: {inv['status']} by {inv['actor']} ({inv['outcome']})")
                shown += 1
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="interventions", last_answer=answer)
        return answer

    # Finance / Fees
    if any(k in msg for k in ("fee", "finance", "due", "overdue", "payment", "unpaid")):
        fee_students = [s for s in students if s.get("fee_overdue") and s["fee_overdue"] > 0]
        if not fee_students:
            return "No students in your cohort have overdue fees."
        lines = [f"**Students with Overdue Fees** ({len(fee_students)} total):\n"]
        total_due = 0
        for i, s in enumerate(fee_students[:10], 1):
            lines.append(f"{i}. **{s['name']}** - ₹{s['fee_overdue']} overdue")
            total_due += s["fee_overdue"]
        lines.append(f"\n*Total Overdue (Top 10): ₹{total_due}*")
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="finance", last_answer=answer)
        return answer

    # Attendance — threshold-aware (must come before generic attendance check)
    # Handles: "more than 80%", "above 90%", "less than 65%", "below 75%", etc.
    _att_threshold_match = re.search(
        r"(more than|above|greater than|over|at least|minimum)\s*(\d+(?:\.\d+)?)\s*%|"
        r"(\d+(?:\.\d+)?)\s*%\s*(or more|and above|and more|plus)",
        msg,
    )
    _att_below_match = re.search(
        r"(less than|below|under|at most|maximum)\s*(\d+(?:\.\d+)?)\s*%|"
        r"(\d+(?:\.\d+)?)\s*%\s*(or less|and below|and under)",
        msg,
    )

    is_att_query = any(k in msg for k in (
        "attendance", "absent", "shortage", "attendance report", "attendance issue",
        "below 75", "above 75", "low attendance",
    ))

    if is_att_query and _att_threshold_match:
        # "more than X%" / "above X%" query
        grps = _att_threshold_match.groups()
        threshold = float(grps[1] if grps[1] is not None else grps[2])
        filtered = [s for s in students if s.get("attendance") is not None and s["attendance"] > threshold]
        filtered.sort(key=lambda s: s.get("attendance", 0), reverse=True)
        if not filtered:
            max_att = max((s.get("attendance", 0) for s in students if s.get("attendance") is not None), default=0)
            best = next((s for s in students if s.get("attendance") == max_att), None)
            answer = (
                f"None of the students in your cohort have an attendance more than {threshold}%. "
                f"The highest attendance recorded is {max_att}% by Student {best['id']} "
                f"(ID: {best.get('reg_id', 'N/A')}) with a risk level of {best['risk_level']} "
                f"({best['probability']:.0%})."
            ) if best else f"None of the students have attendance above {threshold}%."
        else:
            lines = [f"**Students with Attendance > {threshold}%** ({len(filtered)} total):\n"]
            for i, s in enumerate(filtered[:10], 1):
                lines.append(f"{i}. **{s['name']}** (ID: {s.get('reg_id', s['id'])}) - {s['attendance']}% (Risk: {s['probability']:.0%})")
            answer = "\n".join(lines)
            if len(filtered) > 10:
                answer += f"\n\n_Showing 1-10 of {len(filtered)}. Say **\"more\"** to see the next page._"
        _update_session_ctx(session_id, last_category="attendance", last_answer=answer,
                            last_result_set=filtered, last_offset=0)
        return answer

    if is_att_query and _att_below_match:
        # "less than X%" / "below X%" query
        grps = _att_below_match.groups()
        threshold = float(grps[1] if grps[1] is not None else grps[2])
        filtered = [s for s in students if s.get("attendance") is not None and s["attendance"] < threshold]
        filtered.sort(key=lambda s: s.get("attendance", 100))
        if not filtered:
            answer = f"All your students have attendance at or above {threshold}%."
        else:
            lines = [f"**Students with Attendance < {threshold}%** ({len(filtered)} total):\n"]
            for i, s in enumerate(filtered[:10], 1):
                lines.append(f"{i}. **{s['name']}** (ID: {s.get('reg_id', s['id'])}) - {s['attendance']}% (Risk: {s['probability']:.0%})")
            answer = "\n".join(lines)
            if len(filtered) > 10:
                answer += f"\n\n_Showing 1-10 of {len(filtered)}. Say **\"more\"** to see the next page._"
        _update_session_ctx(session_id, last_category="attendance", last_answer=answer,
                            last_result_set=filtered, last_offset=0)
        return answer

    # Attendance shortages — generic fallback (no specific threshold → show <75% by default)
    if is_att_query:
        low_att = [s for s in students if s.get("attendance") is not None and s["attendance"] < 75]
        if not low_att:
            answer = "All your students currently have attendance above 75%."
        else:
            low_att.sort(key=lambda s: s.get("attendance", 100))
            lines = [f"**Students with Low Attendance (<75%)** ({len(low_att)} total):\n"]
            for i, s in enumerate(low_att[:10], 1):
                lines.append(f"{i}. **{s['name']}** - {s['attendance']}% (Risk: {s['probability']:.0%})")
            answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="attendance", last_answer=answer)
        return answer

    # Subject-wise attendance shortages
    if any(k in msg for k in ("subject", "subject wise", "subject-wise", "which subject",
                               "deficit", "subject attendance", "subject shortage")):
        students_with_deficits = [s for s in students if s.get("subjects_at_risk")]
        if not students_with_deficits:
            answer = "No students currently have subject-level attendance shortages."
        else:
            lines = [f"**Students with Subject-Level Attendance Shortages** ({len(students_with_deficits)} total):\n"]
            for s in students_with_deficits[:8]:
                subjs = ", ".join(f"{sr['subject']} ({sr['attendance_pct']}%)" for sr in s["subjects_at_risk"][:3])
                lines.append(f"- **{s['name']}**: {subjs}")
            lines.append("\n_Note: These are current-semester attendance warnings. Students can still recover by attending remaining classes._")
            answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="subject_deficits", last_answer=answer)
        return answer

    # AI Insights / Recommendations
    if any(k in msg for k in ("insight", "recommend", "advice", "what should", "improve",
                               "ai suggest", "action plan")):
        students_with_recs = [s for s in students if s.get("recommended_actions")]
        if not students_with_recs:
            lines = [
                "**General Recommended Actions:**\n",
                "- Schedule 1-on-1 sessions with all HIGH risk students",
                "- Monitor attendance weekly for students below 75%",
                "- Contact parents of students with consecutive absences",
            ]
            answer = "\n".join(lines)
        else:
            lines = ["**AI-Generated Recommendations:**\n"]
            for s in students_with_recs[:5]:
                recs = s["recommended_actions"]
                top_rec = recs[0] if isinstance(recs, list) and recs else str(recs)
                lines.append(f"- **{s['name']}** ({s['risk_level']}): {top_rec}")
            answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="insights", last_answer=answer)
        return answer

    # Who needs attention / top risk
    if any(k in msg for k in ("who is failing", "top risk", "who needs attention",
                               "who should i", "give list", "priority", "urgent",
                               "at risk", "failing", "danger")):
        if not students:
            return "No students are currently assigned to you."
        lines = ["**Students Needing Your Attention:**\n"]
        for i, s in enumerate(students[:10], 1):
            att = f" | Att: {s['attendance']}%" if s.get("attendance") is not None else ""
            bl = f" | Backlogs: {s['backlogs']}" if s.get("backlogs") else ""
            lines.append(f"{i}. **{s['name']}** ({s.get('branch', '')}) - Risk: {s['probability']:.0%}{att}{bl}")
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="student_list", last_answer=answer)
        return answer

    # Count questions
    if any(k in msg for k in ("how many", "count", "total", "number")):
        risk_filter = _extract_risk_filter(msg)
        if risk_filter:
            count = rd.get(risk_filter, 0)
            answer = f"You have **{count} {risk_filter} risk students** in your cohort (out of {total} total)."
            _update_session_ctx(session_id, last_category="count", last_filter={"risk_level": risk_filter}, last_answer=answer)
            return answer
        answer = f"You have **{total} students** assigned to your cohort."
        _update_session_ctx(session_id, last_category="count", last_answer=answer)
        return answer

    # Show / list
    if any(k in msg for k in ("show", "list", "details", "names", "who are")):
        risk_filter = _extract_risk_filter(msg)
        if risk_filter:
            filtered = [s for s in students if s["risk_level"] == risk_filter]
            answer = _fmt_student_list(filtered, limit=10, title=f"Your {risk_filter} Risk Students")
            if len(filtered) > 10:
                answer += f"\n\n_Showing 1-10 of {len(filtered)}. Say **\"more\"** to see the next page._"
            _update_session_ctx(session_id, last_category="student_list", last_filter={"risk_level": risk_filter},
                                last_answer=answer, last_result_set=filtered, last_offset=0)
            return answer
        answer = _fmt_student_list(students, limit=10, title="Your Students by Risk")
        if len(students) > 10:
            answer += f"\n\n_Showing 1-10 of {len(students)}. Say **\"more\"** to see the next page._"
        _update_session_ctx(session_id, last_category="student_list", last_answer=answer,
                            last_result_set=students, last_offset=0)
        return answer

    return None


# ── Tier 1: Student Deterministic Answer Engine ───────────────────

def generate_student_deterministic_answer(message: str, ctx: dict, chat_history: list[dict], session_id: int):
    """Deterministic answers for student role."""
    msg = message.lower().strip()
    sctx = _get_session_ctx(session_id)

    # Follow-up: pagination or repeat
    if msg in ("ok", "okay", "yes", "continue", "go on", "more", "next", "show more", "next page"):
        def _page_fmt(page, offset=0, total=0):
            lines = []
            for i, s in enumerate(page, offset + 1):
                warn = " ⚠️" if s.get("attendance_pct", 100) < 75 else ""
                lines.append(f"{i}. **{s['subject']}**: {s.get('attendance_pct')}%{warn}")
            return "\n".join(lines)
        paged = _paginate_next(session_id, _page_fmt)
        if paged:
            return paged
        prev = sctx.get("last_answer")
        if prev:
            return prev

    # "why" / "explain" contextual drill-down
    if any(k in msg for k in ("why", "explain", "reason", "cause", "how come")):
        last_cat = sctx.get("last_category")
        if last_cat == "risk":
            insights = ctx.get("ai_insights")
            recs = ctx.get("recommended_actions")
            lines = ["**Why your risk level is what it is:**\n"]
            if insights and isinstance(insights, dict):
                driver = insights.get("primary_driver", "")
                if driver:
                    lines.append(f"- **Primary Factor:** {driver}")
                for k, v in insights.items():
                    if k != "primary_driver" and v:
                        lines.append(f"- {k.replace('_', ' ').title()}: {v}")
            else:
                lines.append("- Risk is calculated from attendance patterns, LMS engagement, and assessment performance.")
            if recs and isinstance(recs, list):
                lines.append("\n**To improve:**")
                for r in recs[:3]:
                    lines.append(f"- {r}")
            answer = "\n".join(lines)
            _update_session_ctx(session_id, last_category="risk_why", last_answer=answer)
            return answer
        elif last_cat == "attendance":
            subs = ctx.get("subject_attendance", [])
            low = [s for s in subs if s.get("attendance_pct", 100) < 75]
            if low:
                lines = ["**Subjects pulling your attendance down:**\n"]
                for s in low:
                    lines.append(f"- **{s['subject']}**: {s.get('attendance_pct')}% ({s.get('classes_attended')}/{s.get('classes_conducted')} classes)")
                answer = "\n".join(lines)
            else:
                answer = "Your attendance across all subjects appears to be above threshold. Keep it up!"
            _update_session_ctx(session_id, last_category="attendance_why", last_answer=answer)
            return answer
        # For other categories, fall through to LLM
        return None

    # Risk status
    if any(k in msg for k in ("my risk", "am i in danger", "am i safe", "my situation",
                               "risk level", "my status", "how am i doing", "my score",
                               "my performance", "how is my")):
        level = ctx.get("risk_level", "UNKNOWN")
        prob = ctx.get("probability", 0)
        trend = ctx.get("risk_trend")
        lines = [f"Your current predicted academic risk level is **{level}** (Probability: {prob:.0%})."]
        
        if trend and "direction" in trend:
            lines.append(f"Trend: Your risk is **{trend['direction']}** compared to last assessment.")
            
        if level == "HIGH":
            lines.append("\nThis means you need **immediate attention**. Please reach out to your counsellor and focus on improving attendance and submissions.")
        elif level == "MEDIUM":
            lines.append("\nYou're at moderate risk. Keep up your attendance and stay on top of assignments to improve your standing.")
        elif level in ("LOW", "SAFE"):
            lines.append("\nYou're doing well! Keep maintaining your current academic habits.")
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="risk", last_answer=answer)
        return answer

    # Subject Attendance
    if "subject" in msg and any(k in msg for k in ("attendance", "absent", "missed", "shortage", "classes")):
        subs = ctx.get("subject_attendance", [])
        if not subs:
            return "I don't have subject-wise attendance data for you right now."
        lines = ["**Your Subject-Wise Attendance:**\n"]
        for s in subs:
            warn = " ⚠️" if s.get("attendance_pct", 100) < 75 else ""
            lines.append(f"- **{s['subject']}**: {s.get('attendance_pct')}%{warn} (Attended {s.get('classes_attended')}/{s.get('classes_conducted')})")
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="subject_attendance", last_answer=answer)
        return answer

    # Overall Attendance
    if any(k in msg for k in ("attendance", "absent", "present", "classes")):
        att = ctx.get("attendance")
        if att is not None:
            answer = f"Your overall attendance is currently **{att}%**."
            if att < 75:
                answer += "\n\n**Warning:** Your attendance is below the 75% threshold. This may affect your exam eligibility."
            else:
                answer += "\nYour attendance is above the required threshold."
        else:
            answer = "Attendance data is not currently available for your profile."
        _update_session_ctx(session_id, last_category="attendance", last_answer=answer)
        return answer

    # LMS / Engagement
    if any(k in msg for k in ("lms", "login", "click", "engagement", "activity", "online", "portal")):
        lms = ctx.get("lms_engagement", {})
        if not lms:
            return "I don't have recent LMS activity data for you."
        lines = [
            "**Your Recent LMS Engagement:**\n",
            f"- Clicks (last 7 days): **{lms.get('lms_clicks_7d', 0)}**",
            f"- Clicks (last 14 days): **{lms.get('lms_clicks_14d', 0)}**",
            f"- Unique resources accessed: **{lms.get('lms_unique_resources_7d', 0)}**"
        ]
        pct_change = lms.get('lms_7d_vs_14d_percent_change', 0)
        if pct_change < 0:
            lines.append(f"\n⚠️ Your activity dropped by {abs(pct_change*100):.0f}% this week.")
        elif pct_change > 0:
            lines.append(f"\n📈 Great job! Your activity increased by {pct_change*100:.0f}% this week.")
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="lms", last_answer=answer)
        return answer

    # Assignments / Grades
    if any(k in msg for k in ("assignment", "submission", "score", "cgpa", "marks", "grade", "assessment", "late")):
        assess = ctx.get("assessment", {})
        cgpa = assess.get("cgpa") or ctx.get("cgpa")
        if not assess and not cgpa:
            return "I don't have detailed assessment data for you right now."
        lines = ["**Your Academic Performance:**\n"]
        if cgpa:
            lines.append(f"- **CGPA:** {cgpa}")
        if assess:
            lines.append(f"- Submission Rate: **{assess.get('submission_rate', 0)}%**")
            lines.append(f"- Late Submissions: **{assess.get('late_submissions', 0)}**")
            lines.append(f"- Assessments Completed: **{assess.get('total_completed', 0)}**")
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="grades", last_answer=answer)
        return answer

    # Backlogs
    if any(k in msg for k in ("backlog", "arrear", "fail", "detained")):
        backlogs = ctx.get("backlogs")
        if backlogs and int(backlogs) > 0:
            answer = f"You currently have **{backlogs} backlog(s)**. Please consult your counsellor for remedial options."
        else:
            answer = "No backlogs are currently recorded for your profile. Great job!"
        _update_session_ctx(session_id, last_category="backlogs", last_answer=answer)
        return answer

    # Finance / Fees
    if any(k in msg for k in ("fee", "finance", "due", "pay", "overdue")):
        fin = ctx.get("finance", {})
        if fin and fin.get("fee_overdue", 0) > 0:
            answer = (f"You have an overdue fee amount of **₹{fin['fee_overdue']}**.\n"
                      f"- Payment Status: {fin.get('payment_status', 'Unknown').title()}\n"
                      f"- Delay: {fin.get('delay_days', 0)} days.")
        else:
            answer = "You have no overdue fees at the moment."
        _update_session_ctx(session_id, last_category="finance", last_answer=answer)
        return answer

    # AI Insights / Recommendations
    if any(k in msg for k in ("insight", "recommend", "advice", "what should i do", "help", "improve")):
        recs = ctx.get("recommended_actions")
        insights = ctx.get("ai_insights")
        if not recs and not insights:
            return "I recommend keeping up your attendance and completing all assignments on time."
        lines = ["**AI Recommended Actions:**\n"]
        if recs:
            for r in recs:
                lines.append(f"- {r}")
        if insights and isinstance(insights, dict):
            lines.append(f"\n*Insight*: {insights.get('primary_driver', 'Maintain consistency.')}")
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="insights", last_answer=answer)
        return answer

    # Semester progress / Eligibility
    if any(k in msg for k in ("eligible", "eligibility", "exam", "end sem", "i grade", "r grade",
                               "semester progress", "can i sit", "allowed")):
        sem = ctx.get("semester_progress", {})
        if not sem:
            return "I don't have semester progress data for you right now."
        lines = ["**Your Semester Progress:**\n"]
        if sem.get("overall_attendance_pct") is not None:
            lines.append(f"- Overall Attendance: **{sem['overall_attendance_pct']}%**")
        if sem.get("subjects_below_75") is not None:
            lines.append(f"- Subjects below 75%: **{sem['subjects_below_75']}**")
        if sem.get("subjects_below_65") is not None:
            lines.append(f"- Subjects below 65%: **{sem['subjects_below_65']}**")
        if sem.get("has_i_grade_risk"):
            lines.append("\n⚠️ Your current semester attendance in one or more subjects is between 65–75%. If this continues, you may receive an **I-Grade** at semester end. You can still recover by attending remaining classes.")
        if sem.get("has_r_grade_risk"):
            lines.append("\n🚨 Your current semester attendance in one or more subjects has fallen below 65%. This puts you at risk of an **R-Grade** at semester end. Attend as many remaining classes as possible to recover.") 
        if sem.get("eligibility"):
            lines.append(f"\n**Current Eligibility:** {sem['eligibility']}")
        else:
            if not sem.get("has_i_grade_risk") and not sem.get("has_r_grade_risk"):
                lines.append("\n✅ You appear to be eligible for end-semester exams based on current data.")
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="eligibility", last_answer=answer)
        return answer

    # Academic progress (branch, year, standing)
    if any(k in msg for k in ("my branch", "my year", "what year", "which year", "my semester",
                               "which semester", "my standing", "academic progress", "my program",
                               "my department", "my course")):
        prog = ctx.get("academic_progress", {})
        if not prog:
            return "I don't have detailed academic progress records for you right now."
        lines = ["**Your Academic Progress:**\n"]
        if prog.get("branch"):
            lines.append(f"- **Branch:** {prog['branch']}")
        if prog.get("current_year"):
            lines.append(f"- **Year:** {prog['current_year']}")
        if prog.get("current_semester"):
            lines.append(f"- **Semester:** {prog['current_semester']}")
        if prog.get("academic_status"):
            lines.append(f"- **Status:** {prog['academic_status']}")
        if prog.get("standing"):
            lines.append(f"- **Standing:** {prog['standing']}")
        if prog.get("total_backlogs") is not None:
            lines.append(f"- **Total Backlogs:** {prog['total_backlogs']}")
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="academic_progress", last_answer=answer)
        return answer

    # Stability / Trigger Alerts
    if any(k in msg for k in ("stable", "stability", "trigger", "alert", "warning", "flag")):
        stability = ctx.get("stability")
        triggers = ctx.get("trigger_alerts")
        lines = []
        if stability and isinstance(stability, dict):
            label = stability.get("label", "Unknown")
            lines.append(f"**Risk Stability:** Your risk status is **{label}**.")
            if stability.get("detail"):
                lines.append(f"  _{stability['detail']}_")
        if triggers and isinstance(triggers, dict):
            active = [k for k, v in triggers.items() if v]
            if active:
                lines.append(f"\n⚠️ **Active Alerts:** {', '.join(active)}")
            else:
                lines.append("\n✅ No active trigger alerts on your profile.")
        if not lines:
            return "No stability or alert data is available for your profile at the moment."
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="stability", last_answer=answer)
        return answer

    # Overview / summary
    if msg in ("stats", "overview", "summary", "report", "status", "dashboard", "info"):
        lines = [
            f"**Your Academic Overview:**\n",
            f"- **Name:** {ctx.get('name', 'N/A')}",
            f"- **Risk Level:** {ctx.get('risk_level', 'UNKNOWN')} ({ctx.get('probability', 0):.0%})",
        ]
        if ctx.get("attendance") is not None:
            lines.append(f"- **Overall Attendance:** {ctx['attendance']}%")
        cgpa = ctx.get("assessment", {}).get("cgpa") or ctx.get("cgpa")
        if cgpa:
            lines.append(f"- **CGPA:** {cgpa}")
        if ctx.get("backlogs"):
            try:
                if int(ctx["backlogs"]) > 0:
                    lines.append(f"- **Backlogs:** {ctx['backlogs']}")
            except (ValueError, TypeError):
                pass
        answer = "\n".join(lines)
        _update_session_ctx(session_id, last_category="overview", last_answer=answer)
        return answer

    return None


# ── Tier 2: LLM Engine ─────────────────────────────────────────

_SYSTEM_PROMPTS = {
    "admin": (
        "You are the AI advisor for RetentionOS, an institutional student retention platform.\n"
        "You are speaking to an ADMIN. You answer ONLY from the real data below. NEVER make up numbers.\n\n"
        "RULES:\n"
        "1. Every answer must be grounded in the data provided.\n"
        "2. When explaining \"why\", analyze patterns across branches, attendance, risk rates.\n"
        "3. For strategy, be SPECIFIC with numbers: \"CSE has 8 HIGH risk students - deploy counsellor there first.\"\n"
        "4. For follow-ups (\"ok\", \"why\", \"continue\"), build on your previous answer.\n"
        "5. Use **bold** for key numbers, bullet points for lists.\n"
        "6. Be concise but complete. No unnecessary preamble.\n"
        "7. If data doesn't answer the question, say so honestly and explain what IS available.\n"
        "8. Never show raw JSON.\n"
    ),
    "counsellor": (
        "You are the AI advisor for RetentionOS, an institutional student retention platform.\n"
        "You are speaking to a COUNSELLOR. You ONLY have access to this counsellor's assigned students.\n\n"
        "RULES:\n"
        "1. Every answer must be grounded in the provided student data. NEVER make up numbers.\n"
        "2. Focus on ACTIONABLE advice: which students need immediate intervention and why.\n"
        "3. When discussing a student, reference their risk level, attendance, backlogs, CGPA, and any subject deficits.\n"
        "4. Use intervention history to avoid recommending already-taken actions.\n"
        "5. Highlight students with fee overdue as financial stress correlates with dropout risk.\n"
        "6. For follow-ups (\"ok\", \"why\", \"continue\"), build on your previous answer.\n"
        "7. Use **bold** for key numbers, bullet points for lists. Be concise and professional.\n"
        "8. If data doesn't answer the question, say so honestly and explain what IS available.\n"
        "9. Never show raw JSON. Never reveal data about students NOT in this counsellor's cohort.\n"
    ),
    "student": (
        "You are the AI advisor for RetentionOS, an institutional student retention platform.\n"
        "You are speaking directly to a STUDENT about THEIR OWN academic data.\n\n"
        "RULES:\n"
        "1. Never mention other students or aggregate statistics. This is a PRIVATE conversation.\n"
        "2. Every answer must be grounded in the student's data. NEVER make up numbers.\n"
        "3. You have access to: risk level, attendance (overall + subject-wise), LMS engagement,\n"
        "   assessment scores, CGPA, backlogs, financial status, semester progress, exam eligibility,\n"
        "   AI insights, and recommended actions.\n"
        "4. Be encouraging but HONEST. If they're at HIGH risk, don't sugarcoat it.\n"
        "5. Provide specific, actionable advice: \"Your Math attendance is 62% - attend the next 8 classes to reach 75%.\"\n"
        "6. Reference their LMS engagement trends and assessment submission rates when relevant.\n"
        "7. For follow-ups (\"ok\", \"why\", \"continue\"), build on your previous answer.\n"
        "8. Use **bold** for key numbers. Be supportive and constructive.\n"
        "9. If data doesn't answer the question, say so honestly and explain what IS available.\n"
        "10. Never show raw JSON.\n"
    ),
}


def _build_gemini_prompt(role: str, message: str, ctx: dict, chat_history: list[dict]) -> str:
    if role == "student":
        data = ctx
    elif role == "counsellor":
        data = {
            "total_students": ctx.get("total_students", 0),
            "risk_distribution": ctx.get("risk_distribution", {}),
            "avg_risk_probability": ctx.get("avg_risk_probability", 0),
            "avg_attendance": ctx.get("avg_attendance"),
            "backlog_student_count": ctx.get("backlog_student_count", 0),
            "total_interventions": ctx.get("total_interventions", 0),
            "top_risk_students": [
                {k: v for k, v in s.items() if k not in ("ai_insights", "recommended_actions")}
                for s in ctx.get("students", [])[:20]
            ],
        }
    else:
        data = {
            "total_students": ctx.get("total_students", 0),
            "risk_distribution": ctx.get("risk_distribution", {}),
            "avg_risk_probability": ctx.get("avg_risk_probability", 0),
            "avg_attendance": ctx.get("avg_attendance"),
            "backlog_students": ctx.get("backlog_students", 0),
            "grade_distribution": ctx.get("grade_distribution"),
            "branch_wise": ctx.get("branch_wise", []),
            "year_wise": ctx.get("year_wise", []),
            "counsellor_workload": ctx.get("counsellor_workload", [])[:5],
            "top_20_risk_students": [
                {k: v for k, v in s.items() if k != "attendance_flag"}
                for s in ctx.get("students", [])[:20]
            ],
        }

    recent = chat_history[-14:] if len(chat_history) > 14 else chat_history
    history = "\n".join(
        f"{m.get('role','user').upper()}: {m.get('content','')[:400]}"
        for m in recent
    )

    sys_prompt = _SYSTEM_PROMPTS.get(role, _SYSTEM_PROMPTS["admin"])

    return (
        f"{sys_prompt}\n\n"
        f"## DATA CONTEXT:\n{json.dumps(data, indent=2, default=str)}\n\n"
        f"## CONVERSATION HISTORY:\n{history or '(first message)'}\n\n"
        f"## USER: {message}\n\n"
        f"Respond directly and naturally."
    )


def generate_llm_answer(message: str, ctx: dict, chat_history: list[dict], role: str = "admin") -> str:
    prompt = _build_gemini_prompt(role, message, ctx, chat_history)
    return _call_llm_with_retries(prompt=prompt, max_tokens=1500)


# ── Contextual Fallback ──────────────────────────────────────────
def _smart_fallback(message: str, ctx: dict, session_id: int, role: str = "admin") -> str:
    """When LLM fails, give a contextual answer rather than generic overview."""
    msg = message.lower()

    if role == "student":
        level = ctx.get("risk_level", "UNKNOWN")
        prob = ctx.get("probability", 0)
        lines = [f"Your current risk level is **{level}** ({prob:.0%})."]
        att = ctx.get("attendance")
        if att is not None:
            lines.append(f"Your attendance is **{att}%**.")
        assess = ctx.get("assessment", {})
        if assess.get("cgpa"):
            lines.append(f"CGPA: **{assess['cgpa']}**")
        recs = ctx.get("recommended_actions")
        if recs:
            lines.append("\n**Quick Actions:**")
            for r in recs[:3]:
                lines.append(f"- {r}")
        lines.append("\n*For deeper analysis, please try again when the AI reasoning service is available.*")
        return "\n".join(lines)

    if role == "counsellor":
        rd = ctx.get("risk_distribution", {})
        total = ctx.get("total_students", 0)
        lines = [
            f"**Your Cohort Snapshot** ({total} students):\n",
            f"- HIGH Risk: **{rd.get('HIGH', 0)}**",
            f"- MEDIUM Risk: **{rd.get('MEDIUM', 0)}**",
            f"- LOW / SAFE: **{rd.get('LOW', 0) + rd.get('SAFE', 0)}**",
        ]
        if ctx.get("backlog_student_count"):
            lines.append(f"- Backlogs: **{ctx['backlog_student_count']} students**")
        if ctx.get("avg_attendance"):
            lines.append(f"- Avg Attendance: **{ctx['avg_attendance']}%**")
        lines.append("\n*For deeper analysis, please try again when the AI reasoning service is available.*")
        return "\n".join(lines)

    # Admin fallback
    if any(k in msg for k in ("what should", "how to", "strategy", "action", "plan",
                               "improve", "reduce", "fix", "solution")):
        worst = ctx["branch_wise"][0] if ctx.get("branch_wise") else None
        lines = [
            "**Data-Driven Action Items:**\n",
            f"- **{ctx['risk_distribution']['HIGH']} HIGH risk students** need immediate intervention",
        ]
        if worst:
            lines.append(f"- **{worst['branch']}** has the highest risk rate ({worst['high_risk_pct']}%) - prioritize here")
        lines.extend([
            "- Deploy counsellors to departments with highest HIGH risk counts",
            "- Schedule 1-on-1 sessions for all HIGH risk students within 7 days",
            "- Monitor LMS engagement - students who stop logging in are at highest risk",
            "\n*For a more detailed strategic plan, please try again when the AI reasoning service is available.*",
        ])
        return "\n".join(lines)

    if any(k in msg for k in ("why", "cause", "reason", "factor", "affecting", "declining")):
        lines = [
            "**Key Risk Patterns in the Data:**\n",
            f"- Overall average risk probability is **{ctx['avg_risk_probability']:.0%}**",
        ]
        if ctx.get("avg_attendance"):
            lines.append(f"- Average attendance is **{ctx['avg_attendance']}%**")
        if ctx.get("branch_wise"):
            worst = ctx["branch_wise"][0]
            best = ctx["branch_wise"][-1]
            lines.append(f"- Worst branch: **{worst['branch']}** at {worst['high_risk_pct']}% HIGH risk")
            lines.append(f"- Best branch: **{best['branch']}** at {best['high_risk_pct']}% HIGH risk")
        lines.append("\n*For deeper causal analysis, please try again when the AI reasoning service is available.*")
        return "\n".join(lines)

    return _fmt_risk_overview(ctx) + "\n\n*AI reasoning is temporarily unavailable. Showing data snapshot.*"


# ── Main Entry Point ──────────────────────────────────────────────

def generate_chatbot_response(
    *,
    role: str,
    message: str,
    repository,
    chat_history: list[dict],
    session_id: int = 0,
    auth_subject: str = "",
    auth_display_name: str | None = None,
    auth_student_id: int | None = None,
) -> dict:
    """
    Main entry point. Returns {"content": str, "source": str}.
    """
    # 1. Build role-specific data context
    try:
        if role in ("admin", "system"):
            ctx = get_admin_data_context(repository)
        elif role == "counsellor":
            ctx = get_counsellor_data_context(repository, auth_subject, auth_display_name)
        elif role == "student":
            if auth_student_id is None:
                return {"content": "Student ID not found in your session.", "source": "error"}
            ctx = get_student_data_context(repository, auth_student_id)
        else:
            return {"content": f"Role '{role}' is not supported.", "source": "error"}
    except Exception as e:
        print(f"[chatbot] Data context error: {e}", flush=True)
        traceback.print_exc()
        return {
            "content": "I'm unable to access institutional data right now. Please try again in a moment.",
            "source": "error",
        }

    # 2. Tier 1: Deterministic
    tier1 = None
    if role in ("admin", "system"):
        tier1 = generate_deterministic_answer(message, ctx, chat_history, session_id)
    elif role == "counsellor":
        tier1 = generate_counsellor_deterministic_answer(message, ctx, chat_history, session_id)
    elif role == "student":
        tier1 = generate_student_deterministic_answer(message, ctx, chat_history, session_id)

    if tier1 is not None:
        print(f"[chatbot] Tier 1 answered ({role})", flush=True)
        return {"content": tier1, "source": "deterministic"}

    # 3. Tier 2: LLM (Groq / Gemini)
    if _is_llm_available():
        try:
            answer = generate_llm_answer(message, ctx, chat_history, role=role)
            print(f"[chatbot] Tier 2 (LLM) answered ({role})", flush=True)
            _update_session_ctx(session_id, last_category="llm", last_answer=answer)
            return {"content": answer, "source": "llm"}
        except Exception as e:
            print(f"[chatbot] LLM failed: {e}", flush=True)

    # 4. Smart Fallback
    print(f"[chatbot] Smart fallback ({role})", flush=True)
    fallback = _smart_fallback(message, ctx, session_id, role=role)
    _update_session_ctx(session_id, last_category="fallback", last_answer=fallback)
    return {"content": fallback, "source": "deterministic_fallback"}
