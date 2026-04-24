import sys
import re
import json

with open("src/api/chatbot_engine.py", "r", encoding="utf-8") as f:
    content = f.read()

LLM_CODE = """
# ── Tier 2: LLM Engine ─────────────────────────────────────────

_SYSTEM_PROMPTS = {
    "admin": \"\"\"You are the AI advisor for RetentionOS, an institutional student retention platform.
You are speaking to an ADMIN. You answer ONLY from the real data below. NEVER make up numbers.

RULES:
1. Every answer must be grounded in the data provided.
2. When explaining "why", analyze patterns across branches, attendance, risk rates.
3. For strategy, be SPECIFIC with numbers: "CSE has 8 HIGH risk students — deploy counsellor there first."
4. For follow-ups ("ok", "why", "continue"), build on your previous answer.
5. Use **bold** for key numbers, bullet points for lists.
6. Be concise but complete. No unnecessary preamble.
7. If data doesn't answer the question, say so honestly and explain what IS available.
8. Never show raw JSON.
\"\"\",
    "counsellor": \"\"\"You are the AI advisor for RetentionOS.
You are speaking to a COUNSELLOR. You ONLY have access to the students assigned to this counsellor's department.
Answer ONLY using the provided context.
Focus heavily on identifying which students need immediate interventions.
\"\"\",
    "student": \"\"\"You are the AI advisor for RetentionOS.
You are speaking directly to a STUDENT. You only have access to their personal context.
Never mention other students.
Provide encouraging, highly personalized academic advice.
\"\"\"
}


def _build_gemini_prompt(role: str, message: str, ctx: dict, chat_history: list[dict]) -> str:
    import json
    if role == "student":
        data = ctx
    elif role == "counsellor":
        data = {
            "total_students": ctx.get("total_students", 0),
            "risk_distribution": ctx.get("risk_distribution", {}),
            "top_20_risk_students": ctx.get("students", [])[:20],
        }
    else:
        data = {
            "total_students": ctx.get("total_students", 0),
            "risk_distribution": ctx.get("risk_distribution", {}),
            "avg_risk_probability": ctx.get("avg_risk_probability", 0),
            "avg_attendance": ctx.get("avg_attendance"),
            "branch_wise": ctx.get("branch_wise", []),
            "year_wise": ctx.get("year_wise", []),
            "top_20_risk_students": [
                {k: v for k, v in s.items() if k != "attendance_flag"}
                for s in ctx.get("students", [])[:20]
            ],
        }

    recent = chat_history[-14:] if len(chat_history) > 14 else chat_history
    history = "\\n".join(
        f"{m.get('role','user').upper()}: {m.get('content','')[:400]}"
        for m in recent
    )

    sys_prompt = _SYSTEM_PROMPTS.get(role, _SYSTEM_PROMPTS["admin"])

    return (
        f"{sys_prompt}\\n\\n"
        f"## DATA CONTEXT:\\n{json.dumps(data, indent=2, default=str)}\\n\\n"
        f"## CONVERSATION HISTORY:\\n{history or '(first message)'}\\n\\n"
        f"## USER: {message}\\n\\n"
        f"Respond directly and naturally."
    )


def generate_llm_answer(message: str, ctx: dict, chat_history: list[dict], role: str = "admin") -> str:
    prompt = _build_gemini_prompt(role, message, ctx, chat_history)
    return _call_llm_with_retries(prompt=prompt, max_tokens=1500)


# ── Contextual Fallback ──────────────────────────────────────────
def _smart_fallback(message: str, ctx: dict, session_id: int, role: str = "admin") -> str:
    if role == "student":
        return f"Your current risk level is **{ctx.get('risk_level', 'UNKNOWN')}**. For more detailed analysis, please wait for the reasoning service to return."
    elif role == "counsellor":
        high_risk = ctx.get("risk_distribution", {}).get("HIGH", 0)
        return f"You currently have **{high_risk} HIGH risk students** needing attention. For a deeper breakdown, please wait for the reasoning service."
    
    msg = message.lower()
    if any(k in msg for k in ("what should", "how to", "strategy", "action", "plan",
                               "improve", "reduce", "fix", "solution")):
        return "**Data-Driven Action Items:**\\n- Monitor HIGH risk students.\\n*For a more detailed strategic plan, please try again when the AI reasoning service is available.*"

    return "Here is a snapshot of the current data.\\n*AI reasoning is temporarily unavailable. Showing data snapshot.*"


# ── Main Entry Point ──────────────────────────────────────────────

def generate_counsellor_deterministic_answer(message: str, ctx: dict, chat_history: list[dict], session_id: int):
    msg = message.lower()
    
    # Priority 1: Top N / Who is failing
    if any(k in msg for k in ("who is failing", "top risk", "who needs attention", "who should i", "give list")):
        students = ctx.get("students", [])
        if not students:
            return "No students currently assigned to you."
        lines = ["**Students Needing Attention:**\\n"]
        for i, s in enumerate(students[:10]):
            lines.append(f"{i+1}. **{s['name']}** ({s['branch']}) - Risk: {s['probability']:.1%} - Att: {s['attendance']}%")
        return "\\n".join(lines)
        
    return None

def generate_student_deterministic_answer(message: str, ctx: dict, chat_history: list[dict], session_id: int):
    msg = message.lower()
    
    # Priority 1: Risk
    if any(k in msg for k in ("my risk", "am i in danger", "safe", "worry", "situation")):
        return f"Your current predicted academic risk is **{ctx.get('risk_level', 'UNKNOWN')}** (Probability: {ctx.get('probability', 0):.1%})."
        
    # Priority 2: Attendance
    if any(k in msg for k in ("attendance", "absent", "present")):
        att = ctx.get("attendance", {})
        ratio = att.get("attendance_ratio", 0)
        return f"Your overall attendance is currently **{ratio*100:.1f}%**."
        
    return None

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
    
    # 1. Build Context
    try:
        if role == "admin" or role == "system":
            ctx = get_admin_data_context(repository)
        elif role == "counsellor":
            ctx = get_counsellor_data_context(repository, auth_subject, auth_display_name)
        elif role == "student":
            if auth_student_id is None:
                return {"content": "Student ID not found in session.", "source": "error"}
            ctx = get_student_data_context(repository, auth_student_id)
        else:
            return {"content": f"Role {role} is not supported.", "source": "error"}
    except Exception as e:
        print(f"[chatbot] Data context error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return {"content": "I'm unable to access your institutional data right now. Please try again.", "source": "error"}

    # 2. Deterministic Tier
    tier1 = None
    if role == "admin" or role == "system":
        tier1 = generate_deterministic_answer(message, ctx, chat_history, session_id)
    elif role == "counsellor":
        tier1 = generate_counsellor_deterministic_answer(message, ctx, chat_history, session_id)
    elif role == "student":
        tier1 = generate_student_deterministic_answer(message, ctx, chat_history, session_id)
        
    if tier1 is not None:
        print(f"[chatbot] ✓ Tier 1 answered ({role})", flush=True)
        return {"content": tier1, "source": "deterministic"}

    # 3. LLM Tier
    if _is_llm_available():
        try:
            answer = generate_llm_answer(message, ctx, chat_history, role=role)
            print(f"[chatbot] ✓ Tier 2 (LLM) answered ({role})", flush=True)
            _update_session_ctx(session_id, last_category="llm", last_answer=answer)
            return {"content": answer, "source": "llm"}
        except Exception as e:
            print(f"[chatbot] ✗ LLM failed: {e}", flush=True)

    # 4. Fallback
    print(f"[chatbot] → Smart fallback", flush=True)
    fallback = _smart_fallback(message, ctx, session_id, role=role)
    _update_session_ctx(session_id, last_category="fallback", last_answer=fallback)
    return {"content": fallback, "source": "deterministic_fallback"}
"""

start_idx = content.find("_ADMIN_SYSTEM_PROMPT =")
if start_idx != -1:
    new_content = content[:start_idx] + LLM_CODE
    with open("src/api/chatbot_engine.py", "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Replaced Engine successfully")
else:
    print("Could not find start idx")
