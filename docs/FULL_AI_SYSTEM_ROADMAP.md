# Full AI System Roadmap

## Important Context Before Reading

This file captures the broader AI-system upgrade roadmap for prediction, explanation, action, and guidance.

It is still useful for understanding the larger backend evolution, but it is **not** the best single source for the current chatbot state.

Why this note matters:

- the chatbot/copilot track continued far beyond the earlier roadmap shape
- the current chatbot architecture now includes:
  - deterministic planner baseline `cb22`
  - optional semantic assist `CB19`
  - grouped memory and follow-up orchestration
  - deeper retention analytics
  - frontend contract freeze docs

So if you are specifically trying to understand the chatbot today, read these first:

- [CHATBOT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT.md)
- [CHATBOT_FULL_IMPLEMENTATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FULL_IMPLEMENTATION_GUIDE.md)
- [CHATBOT_FRONTEND_INTEGRATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FRONTEND_INTEGRATION_GUIDE.md)

### What This File Is Best For

Use this roadmap when you want to understand:

- the larger AI/backend evolution of the project
- prediction/explanation/alerting architecture
- how the non-chatbot AI layers were originally planned

Do not use this file alone to understand:

- the final chatbot phase-by-phase story
- the current frontend contract for the chatbot
- the exact current copilot runtime behavior

## Objective

Upgrade the current system from:

`Predict`

to:

`Predict -> Explain -> Decide -> Act -> Guide`

without breaking the existing ML pipeline, feature alignment, or backend behavior.

---

## Non-Negotiable Rules

1. ML model is the only source of prediction.
2. Finance data must not be used in ML features.
3. Finance may only act as an external modifier after prediction.
4. Strict feature alignment must always be enforced:

```python
assert list(features.columns) == feature_order
```

5. LLM must never override the ML prediction.
6. Existing ML training pipeline must remain unchanged.
7. Existing feature engineering must remain unchanged.

---

## Current System Status

Already completed:

- ML pipeline trained on OULAD
- champion model selected with temporal validation
- final model trained on full dataset
- feature order enforced
- FastAPI backend
- PostgreSQL persistence
- prediction history
- demo data and faculty demo flow
- Gemini reasoning with fallback safety
- student-first warning workflow
- recovery-window-based faculty escalation
- asynchronous student and faculty email dispatch
- bounded retry tracking for student and faculty email dispatch
- time-based background recovery escalation monitoring
- DB-backed background job queue with dedicated worker process
- faculty intervention action tracking
- faculty priority queue and operational summary APIs
- repeated-risk reporting
- automated follow-up reminders for untouched escalations
- deduplication-aware LMS/ERP/finance ingestion handling
- per-student faculty routing with fallback to global faculty email
- attendance reasoning layer for explanation and risk drivers
- attendance-aware recovery and closure interpretation
- deterministic risk trend summaries on live APIs
- deterministic stability scoring on live APIs
- deterministic risk type classification on live APIs
- deterministic recommended-action generation on live APIs
- deterministic trigger-based operational alert rules on live APIs
- operational activity-recency, milestone-flag, and SLA context APIs
- false-alert review and intervention outcome tracking on intervention records
- intervention effectiveness analytics APIs
- institution-level department and semester risk overview APIs
- on-demand AI assistance APIs for case summary, communication draft, and recovery planning
- consolidated operational reporting APIs and richer reporting snapshots
- bearer-token auth, RBAC, student self-service aggregation, and CSV export endpoints
- persisted operational-intelligence snapshots in `prediction_history` for auditability
- Phase A: guardian contact profile fields and deterministic worst-case guardian-escalation policy foundation
- Phase B: guardian alert event persistence plus guardian escalation evaluation and queue APIs
- Phase C: guardian background delivery integration with live email support and explicit SMS/WhatsApp provider-pending states
- Phase D: Twilio-compatible guardian SMS/WhatsApp provider abstraction with provider tracking fields
- Phase E: guardian escalation visibility in case state, timeline, institution overview, and CSV exports
- Phase F: automatic guardian escalation orchestration through the recovery monitor with deduplication
- Phase G: channel-aware AI guardian communication drafts for preview and reuse in real guardian delivery

So the next work is an enhancement layer, not a rebuild.

For the detailed current live behavior, see:

- `docs/LIVE_SYSTEM_WORKFLOW.md`

---

## Correct Implementation Order

Frontend should **not** come first.

Most of the AI-system work belongs to the backend and service layer, because frontend should consume a stable response contract only after the reasoning, alerting, and guidance logic are finalized.

So the correct order is:

1. Define enhanced response contract
2. Build fallback reasoning layer
3. Build LLM reasoning layer
4. Enhance prediction service
5. Add alert service
6. Add logging / DB storage for AI outputs
7. Update API endpoints
8. Test end to end
9. Build frontend last

---

## Phase 1: Response Contract First

### Goal
Freeze the enhanced output shape before implementation.

### Why first
This response will affect:

- `predict_service.py`
- score endpoints
- DB logging
- alert system
- frontend UI

### Target output

```json
{
  "risk_score": 0.82,
  "risk_level": "HIGH",
  "confidence": "High confidence based on strong academic and engagement signals",
  "reasoning": "The student shows low assessment performance and weak LMS engagement.",
  "actions": [
    "Schedule mentor meeting",
    "Review missed assessments",
    "Monitor LMS activity over next 7 days"
  ],
  "urgency": "HIGH",
  "timeline": "Immediate",
  "student_guidance": {
    "summary": "Your recent activity suggests you may need extra academic support.",
    "suggestions": [
      "Meet your faculty mentor",
      "Complete pending work this week",
      "Log into the LMS daily"
    ],
    "motivation": "You can recover with small, consistent effort and timely support."
  },
  "alert_sent": true
}
```

### Output ownership

- `risk_score` -> ML only
- `risk_level` -> threshold logic only
- `confidence` -> deterministic or fallback rule
- `reasoning` -> fallback or LLM
- `actions` -> fallback or LLM
- `urgency` -> fallback or LLM
- `timeline` -> fallback or LLM
- `student_guidance` -> fallback or LLM
- `alert_sent` -> alert system result

---

## Phase 2: Rule-Based Fallback First

### Goal
Guarantee that the API never breaks even if OpenAI fails.

### Why before LLM
This gives:

- production safety
- consistent API contract
- deterministic baseline behavior

### Create

- `src/ai/fallback_reasoning.py`

### It should generate

- concise reasoning
- faculty actions
- urgency
- timeline
- student guidance

based on:

- risk score
- risk level
- important summary fields such as:
  - LMS engagement
  - assessment score
  - submission rate
  - late submissions
  - optional finance modifier

### Example logic

- if risk is high and score is low -> urgent faculty action
- if LMS inactivity is high -> suggest immediate engagement support
- if finance modifier increased risk -> mention fee issue as external context, not model cause

---

## Phase 3: LLM Service

### Goal
Generate better reasoning and student guidance without affecting prediction itself.

### Create

- `src/ai/llm_service.py`

### Function

`generate_ai_insights(student_data, risk_score, risk_level)`

### Model choice

Use a lightweight model such as:

- `gpt-4.1-mini`

### Prompt rules

- concise prompt
- structured output only
- explain why student is at risk
- suggest faculty actions
- assign urgency
- suggest intervention timeline
- provide supportive student guidance

### Important rule

LLM must not compute or modify:

- prediction
- threshold
- risk level

LLM is for explanation and guidance only.

---

## Phase 4: Enhance Predict Service

### Goal
Keep ML path unchanged and add reasoning layer after it.

### File

- `src/api/predict_service.py`

### Correct internal flow

`features -> ML model -> risk_score -> risk_level -> fallback/LLM insights -> optional finance modifier already existing -> final response`

### Important separation

- ML decides risk score
- threshold logic decides risk level
- LLM/fallback explains
- finance remains external

### Do not break

- `predict_champion(...)`
- `predict_all_models(...)`
- feature validation

Instead, add a new enriched method or extend score-layer integration carefully.

---

## Phase 5: Email Alert System

### Goal
Notify faculty when a student is high risk.

### Create

- `src/alerts/email_service.py`

### Function

`send_alert_email(student_data, prediction_output)`

### Trigger

- only when `risk_level == "HIGH"`

### Email content

- student id
- risk score
- risk level
- reasoning
- actions
- urgency
- timeline

### Safety rules

- duplicate alerts must be prevented
- email failure must not break API
- alert result should be logged as `alert_sent = true/false`

---

## Phase 6: Logging and Persistence

### Goal
Store the AI-system outputs, not just prediction scores.

### Recommended DB update
Extend or complement `prediction_history` to store:

- risk score
- risk level
- reasoning
- actions
- urgency
- timeline
- student guidance
- alert_sent

### Why before frontend
Frontend will need to display these fields.

### Important design choice
Either:

1. extend current `prediction_history`
or
2. create a new table like `ai_prediction_details`

Recommended:

- extend `prediction_history` if change scope stays manageable

---

## Phase 7: API Updates

### Goal
Return the enhanced AI output through score endpoints.

### Main endpoints affected

- `/score/student`
- `/score/latest/{student_id}`
- `/score/history/{student_id}`

### What should happen

- ML result returned as before
- enriched reasoning and guidance added
- alert status included
- history/latest endpoints expose the stored enhanced fields

### Important rule
Do not remove current useful fields.
Enhance them carefully.

---

## Phase 8: Testing Before Frontend

### Must test

1. ML prediction still works unchanged
2. feature alignment still enforced
3. finance still stays external only
4. fallback works when OpenAI fails
5. email failure does not break scoring
6. high-risk cases trigger alert flow
7. latest/history endpoints return enriched outputs

### Test cases

- low-risk student
- medium-risk student
- high-risk student
- OpenAI unavailable
- email unavailable

---

## Phase 9: Frontend Last

### Why last
Frontend should consume the final stable backend response, not shape it.

### Faculty dashboard should show

- student id
- risk score
- risk level
- reasoning
- actions
- urgency
- timeline
- alert sent
- history

### Student dashboard should show

- summary
- suggestions
- supportive guidance
- motivation

### Important UI separation

- faculty sees intervention details
- student sees supportive mentor-style guidance

---

## Recommended File Plan

### New files

- `src/ai/fallback_reasoning.py`
- `src/ai/llm_service.py`
- `src/alerts/email_service.py`

### Files to enhance

- `src/api/predict_service.py`
- `src/api/routes/score.py`
- `src/api/schemas.py`
- `src/db/models.py`
- `src/db/repository.py`

---

## Best Execution Order

1. Freeze enriched response schema
2. Implement fallback reasoning
3. Implement LLM service
4. Integrate enriched output into prediction service
5. Extend DB storage
6. Implement email alert service
7. Update score/history/latest endpoints
8. Test end to end
9. Build frontend

---

## What Must Happen Before Frontend

These should be completed first:

- fallback reasoning
- LLM service
- predict service enhancement
- DB logging for AI output
- alert integration
- updated history/latest APIs

So yes:

**most of the requested AI-system work should be done before frontend**

---

## Final Recommendation

The first implementation step should be:

**define the enriched schema and fallback reasoning layer**

Why:

- it is safe
- it does not depend on OpenAI setup yet
- it gives a stable contract for the rest of the system

Only after that should we connect LLM and alerts.
