# Faculty Demo Script

## Goal
Demonstrate that the system works end to end:

`sample profile / LMS / ERP / finance data -> API ingestion -> PostgreSQL -> ML prediction -> external finance modifier -> prediction_history`

This demo uses simulated institutional data, but the system flow is the same as real deployment.

If authentication is enabled in the backend, first use `POST /auth/login` and authorize Swagger with the returned bearer token before testing protected endpoints.

---

## Before the Demo

### Terminal 1
Start the backend:

```powershell
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

### Terminal 2
Start the worker:

```powershell
python -m src.worker.runner
```

### Terminal 3
Keep these ready:

```powershell
python demo\reset_demo_data.py
python demo\run_demo.py
```

### Browser Tabs
Open:

- `http://127.0.0.1:8000/docs`
- Supabase Table Editor
- Demo sample files if needed

---

## Opening Line

"Today I am demonstrating a full student retention prediction system where simulated LMS, ERP, and finance data flow through the real backend, database, ML model, and prediction history pipeline."

---

## Explain the Data Rule

"The model is trained on OULAD data. In real deployment, live data would come from LMS, ERP, and finance systems. Since real institutional access requires permission, for demo I am using realistic sample data. But the system flow is exactly the same as real deployment."

---

## Step 1: Show Backend Health

Open `/docs`.

Show:

- `GET /health`
- `GET /config`

Say:

"This confirms the backend is live and the active champion model is `gradient_boosting` with threshold `0.55`."

Also say:

"The API and the worker are running separately. The API receives data and stores jobs, while the worker handles queued emails and scheduled monitoring."

---

## Step 2: Show the Architecture

Say:

"The live flow is:

`demo/sample data -> profile registration -> API ingestion -> PostgreSQL -> feature assembly -> ML prediction -> external finance modifier -> queued jobs -> worker execution -> prediction_history`"

---

## Step 3: Show the Demo Data Files Briefly

Open:

- [sample_students.json](c:\Users\Sai Nikhil\Desktop\Student_Retention\demo\sample_students.json)
- [sample_erp.json](c:\Users\Sai Nikhil\Desktop\Student_Retention\demo\sample_erp.json)
- [sample_finance.json](c:\Users\Sai Nikhil\Desktop\Student_Retention\demo\sample_finance.json)

Say:

"I prepared 3 students:

- low risk
- medium risk
- high risk

Each has profile, LMS, ERP, and finance records."

Do not spend too long here.

---

## Step 4: Run the Demo

In Terminal 3 first run:

```powershell
python demo\reset_demo_data.py
```

Say:

"This clears any old demo rows for the prepared sample students so the demo starts from a clean state."

Then run:

```powershell
python demo\run_demo.py
```

As it runs, say:

"For each student, the script is:

1. registering student profile data
2. ingesting LMS data
3. ingesting finance data
4. ingesting ERP data
5. auto-triggering scoring when meaningful data is ready
6. fetching the stored latest result
7. confirming prediction history"

---

## Step 5: Explain the Three Demo Results

### Low-Risk Student

"This student has strong academic performance, good LMS engagement, and no finance penalty, so the system predicts low risk."

### Medium-Risk Student

"This student has weaker academic indicators and a small finance modifier, but still remains below the final threshold."

### High-Risk Student

"This student has weak LMS behavior, low assessment performance, and a finance overdue signal, so the system predicts high risk."

---

## Step 6: Show Supabase Tables

Open Supabase Table Editor and show:

- `student_profiles`
- `lms_events`
- `erp_events`
- `finance_events`
- `prediction_history`

Filter a student like:

- `880003`

Say:

"This proves the ingested source data is being stored in the cloud database, and the final scored result is also stored in prediction history."

---

## Step 7: Explain the Most Important Columns

In `prediction_history`, explain:

- `base_risk_probability` = output from champion ML model
- `finance_modifier` = external finance adjustment
- `final_risk_probability` = base + modifier
- `final_predicted_class` = final decision after threshold

This is one of the strongest parts of the system.

---

## Step 8: Explain the Finance Rule Clearly

Say this clearly:

"Finance is not part of the machine learning training features because the OULAD training dataset does not contain finance data. So finance is handled as an external post-prediction modifier."

---

## Step 9: Show History and Latest Endpoints

In Swagger, show:

- `GET /score/latest/{student_id}`
- `GET /score/history/{student_id}`
- `GET /drivers/{student_id}`
- `GET /faculty/priority-queue`
- `GET /operations/context/{student_id}`
- `GET /interventions/history/{student_id}`
- `GET /interventions/analytics/effectiveness`
- `GET /institution/risk-overview`
- `GET /ai-assist/case-summary/{student_id}`
- `GET /ai-assist/communication-draft/{student_id}`
- `GET /ai-assist/recovery-plan/{student_id}`
- `GET /reports/operations-overview`
- `GET /student/me/overview`
- `GET /reports/exports/priority-queue`
- `GET /reports/exports/institution-overview`
- `GET /reports/exports/intervention-effectiveness`

Use one student like:

- `880003`

Say:

"The latest endpoint gives the most recent decision quickly. The history endpoint gives the audit trail of prediction records over time."

Also explain the new operational intelligence fields:

- `risk_trend`
- `stability`
- `risk_type`
- `recommended_actions`
- `trigger_alerts`

Say:

"These fields are not extra ML predictions. They are deterministic backend intelligence outputs built on top of prediction history and current academic, attendance, engagement, and finance signals. They help counsellors understand whether risk is worsening, what kind of risk it is, and what action should be taken next."

For `stability`, say:

"Stability tells us whether the prediction is strongly supported or borderline. It is calculated deterministically from threshold distance, model agreement, model spread, and recent volatility, so faculty can judge how confidently to act on the prediction."

For `trigger_alerts`, say:

"Trigger alerts are deterministic real-time rules that fire when the system detects sudden operational deterioration, such as a sharp attendance drop, repeated missed submissions, falling marks, unresolved fee due, or a fresh high-risk threshold crossing. They do not replace the model; they help counsellors react faster."

For `GET /operations/context/{student_id}`, say:

"This endpoint shows the live operational layer for one student: last meaningful activity, milestone flags like repeat-attempt or fee-pressure conditions, and SLA indicators such as whether faculty follow-up is overdue."

For `GET /interventions/history/{student_id}`, say:

"This endpoint shows the actual faculty intervention timeline and now also stores whether the alert was later judged valid or false, plus what outcome was observed after the intervention."

For `GET /interventions/analytics/effectiveness`, say:

"This endpoint turns intervention logging into operational analytics. It shows review coverage, false-alert rate, and which intervention types are actually producing improved outcomes over time."

For `GET /institution/risk-overview`, say:

"This endpoint is the backend foundation for future department and semester heatmaps. It aggregates the current live cohort into department-wise and semester-wise risk buckets, top risk types, and heatmap-friendly cells so admin users can see where intervention pressure is concentrating."

For `GET /ai-assist/case-summary/{student_id}`, say:

"This endpoint uses Gemini on demand to turn the student’s live operational state into a concise faculty-ready case summary. It does not change the prediction; it explains the case for faster human review."

For `GET /ai-assist/communication-draft/{student_id}`, say:

"This endpoint generates a ready-to-edit draft message for faculty, student, or parent communication based on the current live case context."

For `GET /ai-assist/recovery-plan/{student_id}`, say:

"This endpoint generates a short recovery plan grounded in the student’s current drivers, trend, triggers, and workflow state. It is useful for mentor follow-up and support planning."

For `GET /reports/operations-overview`, say:

"This endpoint consolidates the major backend reporting layers into one live response: faculty operational summary, institution-wide risk overview, and intervention-effectiveness analytics. It is useful for admin dashboards and exported reports."

For `GET /student/me/overview`, say:

"This endpoint is the backend foundation for the student module. It gives one safe self-service response containing the student’s own profile, latest risk state, warning history, and AI recovery plan."

For the CSV export endpoints, say:

"These export endpoints are useful for real institutional operations where admins still need downloadable CSV reports for manual review, meetings, and audit trails."

For `GET /drivers/{student_id}`, say:

"This endpoint now combines top risk drivers with risk trend, risk type, and recommended next actions for a specific student."

For `GET /faculty/priority-queue`, say:

"The faculty queue now includes not just risk score and urgency, but also a trend label, dominant risk type, and recommended next action."

---

## Step 10: Explain Why Student Login Alone Is Not Enough

If asked, say:

"A student login alone does not generate prediction. Prediction depends on synced LMS and ERP academic data. Finance is optional and used only as an external modifier. Login is only for viewing the latest stored result."

---

## Step 11: Closing Statement

"So this project is not just a trained model. It is a complete pipeline:

- ingest institutional data
- store it in PostgreSQL
- score students using the trained ML system
- adjust with finance policy
- store history for future review and intervention"

---

## Short Summary Version

"This demo uses simulated LMS, ERP, and finance data, but the system flow is real. Data is ingested through APIs, stored in PostgreSQL, converted into aligned features, scored by the trained ML model, adjusted with an external finance modifier, and stored in prediction history. This shows how the system would work in real deployment once institutional permissions are available."
"This demo uses simulated profile, LMS, ERP, and finance data, but the system flow is real. Data is registered and ingested through APIs, stored in PostgreSQL, converted into aligned features, scored by the trained ML model when meaningful data is ready, adjusted with an external finance modifier, and stored in prediction history. This shows how the system would work in real deployment once institutional permissions are available."

---

## Exact Order to Follow During Demo

1. Start backend
2. Start worker
3. Open `/docs`
4. Show `/health` and `/config`
5. Briefly show sample demo files
6. Run:

```powershell
python demo\reset_demo_data.py
python demo\run_demo.py
```

7. Explain low/medium/high-risk outputs
8. Show Supabase tables
9. Show `prediction_history`
10. Show `/score/latest/{student_id}`
11. Close with deployment explanation
