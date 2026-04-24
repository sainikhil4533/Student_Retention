"""
Chatbot Engine v3 — Smart Test Suite
Tests Tier 1 (deterministic) rapidly, Tier 2 (Gemini) with rate limiting.
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(override=True)

from src.db.database import SessionLocal
from src.db.repository import EventRepository
from src.api.chatbot_engine import generate_chatbot_response, _context_cache

PASS = 0
FAIL = 0
WARNINGS = 0
results = []

def _fresh_repo():
    db = SessionLocal()
    return db, EventRepository(db)

def test_q(question, session_id=0, expect_keywords=None, chat_history=None, label=""):
    global PASS, FAIL, WARNINGS
    db, repo = _fresh_repo()
    history = chat_history or []
    start = time.time()
    try:
        result = generate_chatbot_response(
            role="admin", message=question, repository=repo,
            chat_history=history, session_id=session_id,
        )
        elapsed = round(time.time() - start, 2)
        content = result["content"]
        source = result["source"]

        is_bad = False
        bad_reason = ""

        if not content or len(content.strip()) < 10:
            is_bad = True
            bad_reason = "Empty/short response"

        if expect_keywords:
            missing = [k for k in expect_keywords if k.lower() not in content.lower()]
            if missing:
                is_bad = True
                bad_reason = f"Missing: {missing}"

        if source == "error":
            is_bad = True
            bad_reason = "DB/system error"

        if is_bad:
            FAIL += 1
            status = "❌ FAIL"
        else:
            PASS += 1
            status = "✅ PASS"

        display = content[:120].replace("\n", " ").strip()
        if len(content) > 120:
            display += "..."
        print(f"  {status} [{source}] ({elapsed}s) Q: {question}")
        print(f"    A: {display}")
        if label:
            print(f"         {label}")
        if is_bad:
            print(f"         ⚠ {bad_reason}")
        
        results.append({"q": question, "status": status, "source": source, "content": content})
        return result
    except Exception as e:
        FAIL += 1
        print(f"  ❌ CRASH Q: {question} → {e}")
        results.append({"q": question, "status": "❌ CRASH", "source": "crash"})
        return None
    finally:
        try:
            db.rollback()
            db.close()
        except:
            pass


def run_chain(name, questions, session_id):
    print(f"\n  🔗 {name}")
    history = []
    for q in questions:
        result = test_q(q, session_id=session_id, chat_history=history)
        if result:
            history.append({"role": "user", "content": q})
            history.append({"role": "assistant", "content": result["content"]})


# ══════════════════════════════════════════════════════════════════
print("=" * 70)
print("🚀 CHATBOT ENGINE v3 — COMPREHENSIVE TEST SUITE")
print("=" * 70)

# ════════════════════════════════════════════════════════════════
# PART 1: TIER 1 TESTS (No Gemini needed — runs instantly)
# ════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("📊 PART 1: TIER 1 — DETERMINISTIC DATA TESTS (instant, no API)")
print("=" * 70)

print("\n🔹 1. Direct Count Questions")
test_q("how many students are high risk", expect_keywords=["HIGH", "8"])
test_q("total number of risky students", expect_keywords=["risk"])
test_q("give count of high risk students", expect_keywords=["HIGH"])
test_q("total number of students", expect_keywords=["100"])
test_q("how many active students", expect_keywords=["student"])

print("\n🔹 2. Branch/Department Breakdown")
test_q("branch wise student count", expect_keywords=["CSE"])
test_q("number of students per department", expect_keywords=["CSE"])
test_q("branch wise risk", expect_keywords=["CSE"])
test_q("risk by department", expect_keywords=["CSE"])
test_q("performance by branch", expect_keywords=["CSE"])

print("\n🔹 3. Risk Distribution")
test_q("show risk distribution", expect_keywords=["Risk"])
test_q("how many low medium high risk students", expect_keywords=["HIGH", "MEDIUM"])

print("\n🔹 4. Ambiguous Short Inputs (MUST NOT loop clarification)")
test_q("stats", expect_keywords=["Risk", "student"])
test_q("trend", expect_keywords=["Risk"])
test_q("analysis", expect_keywords=["Risk"])
test_q("report", expect_keywords=["Risk"])
test_q("risk", expect_keywords=["HIGH", "MEDIUM"])
test_q("performance", expect_keywords=["Risk"])

print("\n🔹 5. Student Listing")
test_q("show top 5 high risk students", expect_keywords=["HIGH"])
test_q("give details of medium risk students", expect_keywords=["MEDIUM"])
test_q("list all safe students")
test_q("who are the most at-risk students", expect_keywords=["Risk"])
test_q("give me registration ids of high risk students", expect_keywords=["HIGH"])

print("\n🔹 6. Backlog/Grade Questions")
test_q("how many students having backlogs", expect_keywords=["backlog"])
test_q("how many I grade students and how many R grade students", expect_keywords=["grade"])
test_q("show grade distribution", expect_keywords=["grade"])

print("\n🔹 7. Specific Branch Query")
test_q("compare cse vs ece", expect_keywords=["CSE"])
test_q("only CSE", expect_keywords=["CSE"])

print("\n🔹 8. Year-Wise")
test_q("year wise performance")
test_q("risk by year")

# ════════════════════════════════════════════════════════════════
# PART 2: FOLLOW-UP CHAIN TESTS (Tier 1 only — tests context tracking)
# ════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("🔗 PART 2: FOLLOW-UP CHAIN TESTS (context tracking, no API)")
print("=" * 70)

run_chain("Chain A: Count → Details → IDs", [
    "how many students are at medium risk",
    "can you give the details of top 10 among them",
    "show their registration ids",
], session_id=2001)

run_chain("Chain B: Branch → Drill Down", [
    "branch wise risk",
    "ok",
    "only CSE",
], session_id=2002)

run_chain("Chain C: Overview → Expand → List", [
    "stats",
    "ok",
    "continue",
    "risk",
], session_id=2003)

run_chain("Chain D: Count → Branch Breakdown", [
    "how many students are high risk",
    "ok",
    "break it by branch",
], session_id=2004)

# ════════════════════════════════════════════════════════════════
# PART 3: TIER 2 TESTS (Gemini AI — with rate limiting)
# Only tests 5 key Gemini questions to avoid quota exhaustion
# ════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("🤖 PART 3: TIER 2 — GEMINI AI TESTS (5 questions, rate-limited)")
print("   Free tier: ~15 requests/min, ~1500/day")
print("=" * 70)

gemini_questions = [
    ("how is overall performance", "Indirect/Natural"),
    ("why are many students at risk", "Explanation"),
    ("what should we do to reduce risk", "Strategy"),
    ("which branch has good attendance but high risk", "Cross-Feature"),
    ("which branch is worst and what should we prioritize", "Decision"),
    ("why is CSE worse", "Branch Reasoning"),
    ("give strategic plan", "Strategy Plan"),
    ("is the situation under control", "Judgment"),
]

for i, (q, label) in enumerate(gemini_questions):
    if i > 0:
        print(f"  ⏳ Waiting 12s for rate limit...")
        time.sleep(12)
    test_q(q, label=f"[{label}]")

# ════════════════════════════════════════════════════════════════
# PART 4: GEMINI FOLLOW-UP CHAIN (single deep chain)
# ════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("🔥 PART 4: DEEP GEMINI CHAIN (10-depth, rate-limited)")
print("=" * 70)

# Chain with mixed Tier 1 + Tier 2 questions
chain_questions = [
    "branch wise risk",           # Tier 1
    "ok",                         # Tier 1 follow-up
    "why is CSE worse",           # Tier 2
    "what is main factor",        # Tier 2
    "what should we fix first",   # Tier 2
    "how long will it take to improve",  # Tier 2
    "what if we don't act",       # Tier 2
    "give strategic plan",        # Tier 2
]

history = []
for i, q in enumerate(chain_questions):
    # Add delay before Gemini questions (index 2+)
    if i >= 2 and i > 2:
        print(f"  ⏳ Waiting 12s for rate limit...")
        time.sleep(12)
    db, repo = _fresh_repo()
    start = time.time()
    try:
        result = generate_chatbot_response(
            role="admin", message=q, repository=repo,
            chat_history=history, session_id=3001,
        )
        elapsed = round(time.time() - start, 2)
        content = result["content"]
        source = result["source"]
        display = content[:120].replace("\n", " ").strip()
        
        if source == "error" or len(content.strip()) < 10:
            FAIL += 1
            print(f"  ❌ FAIL [{source}] ({elapsed}s) Q: {q}")
        else:
            PASS += 1
            print(f"  ✅ PASS [{source}] ({elapsed}s) Q: {q}")
            
        if len(display) > 120:
            display = display[:120] + "..."
        print(f"    A: {display}")
        
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": content})
        results.append({"q": q, "status": "✅", "source": source, "content": content})
    except Exception as e:
        FAIL += 1
        print(f"  ❌ CRASH Q: {q} → {e}")
    finally:
        try:
            db.rollback()
            db.close()
        except:
            pass

# ════════════════════════════════════════════════════════════════
# PART 5: NEW DATA ROUTE TESTS (all Tier 1 — no rate limiting needed)
# ════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("📊 PART 5: NEW DATA ROUTES — Finance, LMS, CGPA, Eligibility")
print("=" * 70)

new_route_questions = [
    ("which students have fee overdue", "Fee Overdue"),
    ("show financial status", "Finance Overview"),
    ("which students are inactive", "LMS Inactive"),
    ("show lms engagement", "LMS Engagement"),
    ("students at i grade risk", "I-Grade Risk"),
    ("students with low attendance", "Low Attendance"),
    ("which students are not eligible for end sem", "Not Eligible"),
    ("show cgpa overview", "CGPA Overview"),
    ("tell me about student 880082", "Student Lookup"),
]

for q, label in new_route_questions:
    test_q(q, label=f"[{label}]")

# ════════════════════════════════════════════════════════════════
# PART 6: EDGE CASES — Ensure correct routing
# ════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("🧪 PART 6: EDGE CASES — Routing Correctness")
print("=" * 70)

edge_cases = [
    ("give me names of high risk students", "Names HIGH"),
    ("give me names of medium risk students", "Names MEDIUM"),
    ("give me names of low risk students", "Names LOW"),
    ("give me names of safe students", "Names SAFE"),
    ("how many students have backlogs", "Backlog Count"),
]

for q, label in edge_cases:
    test_q(q, label=f"[{label}]")

# ══════════════════════════════════════════════════════════════════
# FINAL REPORT
# ══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("🏆 FINAL TEST REPORT")
print("=" * 70)

total = PASS + FAIL
print(f"\n✅ PASS: {PASS}/{total}")
print(f"❌ FAIL: {FAIL}/{total}")
print(f"\nPass Rate: {PASS/total*100:.1f}%" if total else "No tests run")

# Count sources
sources = {}
for r in results:
    s = r.get("source", "unknown")
    sources[s] = sources.get(s, 0) + 1
print(f"\nResponse Sources:")
for s, c in sorted(sources.items()):
    print(f"  {s}: {c}")

if FAIL > 0:
    print(f"\n❌ FAILED:")
    for r in results:
        if "FAIL" in r.get("status", "") or "CRASH" in r.get("status", ""):
            print(f"  - {r['q']}")

print("\n" + "=" * 70)
print("TEST COMPLETE")
print("=" * 70)
