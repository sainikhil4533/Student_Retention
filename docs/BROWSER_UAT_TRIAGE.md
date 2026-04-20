# Browser UAT Triage

Use this checklist in the live app. The goal is not to test infinite prompts. The goal is to catch real browser-side misses after the runner-based hardening work.

## Before You Start

Use the real frontend app from `frontend/`.

Build check:

```powershell
cd frontend
cmd /c npm run build
``` 

For live UAT, start the full system from the project root:

```powershell
python run_all.py --with-frontend
```

Then open the frontend URL shown by the dev server and test each role in a fresh chat session.

## Student

Run these in one session:

1. `attendance`
2. `assignment rate`
3. `risk`
4. `why am i high risk`
5. `ok`
6. `how can i improve`
7. `what is my lms details`
8. `what is my erp details`
9. `what is my finance details`
10. `my attendance is good but why am i high risk`
11. `continue`

What should hold:

- no unnecessary clarification loops
- `attendance`, `assignment rate`, and `risk` should default safely
- `ok` and `continue` should move the conversation forward
- LMS, ERP, and finance should switch topics cleanly
- action questions should give guidance instead of dumping the same data again

## Counsellor

Run these in one session:

1. `which students are high risk`
2. `ok`
3. `show only CSE`
4. `what about top 5`
5. `why is student 880001 high risk`
6. `what action should i take for student 880001`
7. `continue`
8. `which students have good attendance but high risk`
9. `who needs urgent help`
10. `which factor is affecting most students`

What should hold:

- the scope should stay within assigned students
- list -> explanation -> action chains should continue naturally
- filters and top-N follow-ups should keep the same context
- no repeated clarification for short prompts like `ok`
- fresh natural-language triage prompts should still resolve to real assigned-student analysis

## Admin

Run these in one session:

1. `stats`
2. `ok`
3. `continue`
4. `risk`
5. `why`
6. `then`
7. `branch wise risk`
8. `only CSE`
9. `compare 1st year vs final year`
10. `why is first year worse`
11. `what should we fix first`
12. `give strategic plan`
13. `is risk increasing over time`
14. `what is biggest issue overall`
15. `where should we take action first`

What should hold:

- short admin resets like `risk` should not get trapped in stale context
- grouped analysis should support subset and comparison follow-ups
- action turns should not repeat the previous answer
- trend and institution-health questions should answer directly instead of reopening clarification
- strategic follow-ups should become more specific as the chain continues

## How To Report A Miss

If anything feels wrong, send the exact conversation in this format:

```text
role: student/counsellor/admin
q1: ...
a1: ...
q2: ...
a2: ...
what felt wrong: ...
```

That lets us fix the behavior family directly instead of guessing.
