# Live System Workflow

## How To Read This Document

This file explains how the **live backend behaves end to end**.

It is best read after you already understand the larger project context.

Recommended reading before this file:

- [DOCS_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/DOCS_GUIDE.md)
- [PHASE_1_TO_10_BACKEND_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/PHASE_1_TO_10_BACKEND_GUIDE.md)

If you want the chatbot-specific story, read:

- [CHATBOT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT.md)
- [CHATBOT_FULL_IMPLEMENTATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FULL_IMPLEMENTATION_GUIDE.md)

### What This Document Is Best For

Use this file when you want to understand:

- the real backend execution order
- how scoring, warnings, recovery, escalation, jobs, reporting, and auth fit together
- what the system does in production-style operation

### What This Document Is Not Best For

This is not the best first file for:

- feature ownership rules
- data dictionary understanding
- chatbot phase-by-phase learning
- frontend integration

This document explains how the current Student Retention system works end to end in its present backend implementation.

It is intended to help any reader understand:

- what data enters the system
- when scoring happens
- when Gemini is used
- when fallback reasoning is used
- when the student gets a warning
- when faculty gets an escalation
- how asynchronous email sending works
- how the recovery window is enforced
- how time-based escalation now works in real time
- how faculty intervention tracking now works
- how false-alert review and intervention outcome tracking now work
- how automated follow-up reminders now work
- how faculty summary and queue APIs interpret active cases
- how the new deterministic operational intelligence layer works
- how institution-level aggregate risk summaries now work
- how on-demand Gemini assistance now works for case summaries, communication drafts, and recovery plans
- how consolidated operational reporting now combines faculty, intervention, and institution views
- how authentication, RBAC, student self-service, and CSV exports now work
- how guardian worst-case escalation now has a policy-evaluation and queue-ready persistence layer

---

## 1. Current System Purpose

The current system is not just a prediction API.

It now behaves as a real-time student-retention intervention pipeline:

`Ingest -> Score -> Explain -> Warn Student -> Wait Recovery Window -> Escalate To Faculty If Needed`

The system is designed so that:

- ML remains the only source of prediction
- Gemini improves explanation and guidance
- students are warned first when they become high risk
- faculty is contacted only after the recovery window if the student still remains high risk

The backend now also behaves more like a real product backend:

- bearer-token authentication exists
- role-based access control exists
- student, counsellor, admin, and system-facing routes are separated

---

## 2. Main Data Sources

The system currently works with four major data groups:

### Student profile

Stored in:

- `student_profiles`

Contains:

- `student_id`
- `student_email`
- `faculty_name`
- `faculty_email`
- `parent_name`
- `parent_relationship`
- `parent_email`
- `parent_phone`
- `preferred_guardian_channel`
- `guardian_contact_enabled`
- `gender`
- `highest_education`
- `age_band`
- `disability_status`
- `num_previous_attempts`

This is required because the prediction model needs demographic features.

The faculty mapping fields are used for escalation routing:

- student warnings go to `student_email`
- faculty escalations and follow-up reminders go to `faculty_email`
- if `faculty_email` is missing, the system falls back to the global `FACULTY_ALERT_EMAIL` configuration when available

The guardian mapping fields are now stored as Phase A foundation for worst-case escalation:

- `parent_email` supports guardian email later
- `parent_phone` supports SMS or WhatsApp later
- `preferred_guardian_channel` guides channel choice
- `guardian_contact_enabled` acts as the first safety gate so guardian escalation is never assumed by default

The guardian escalation backend now also has a Phase B queue-ready persistence layer:

- guardian escalation can be evaluated deterministically before any message is sent
- eligible cases can be written into `guardian_alert_events`
- this preserves an audit trail before email, SMS, or WhatsApp delivery is plugged in

Guardian delivery now also supports the Phase C and Phase D live dispatch path:

- guardian email can be sent through the existing SMTP pipeline
- guardian events are pushed into the same background-job worker used by other notifications
- guardian SMS and guardian WhatsApp now use a Twilio-compatible provider abstraction
- if Twilio credentials are not configured, SMS and WhatsApp safely remain `provider_pending`
- guardian alert history now stores provider name and provider message id when the provider returns one

Phase E now adds operational visibility for guardian escalation:

- case-state responses now expose the latest guardian escalation type, status, channel, and time
- student timelines now include guardian escalation events
- institution overview and CSV export now include guardian escalation counts

Phase F now automates guardian escalation inside the existing background workflow:

- the recovery monitor now checks whether a case has crossed the worst-case guardian threshold
- if the policy says yes, the monitor queues guardian escalation automatically
- the same deduplication logic is reused, so repeated monitor passes do not create duplicate guardian events for the same prediction cycle

Phase G now adds AI-assisted guardian messaging on top of the guardian workflow:

- counsellors and admins can preview a guardian-ready draft through `GET /ai-assist/guardian-draft/{student_id}?channel=email|sms|whatsapp`
- the guardian draft is channel-aware, so email gets a fuller subject/body/closing while SMS and WhatsApp get a compact guardian-safe message
- the real guardian delivery pipeline now reuses the same draft logic, which keeps previewed wording and delivered wording aligned
- the drafting layer stays separate from the guardian escalation policy, so the system still decides worst-case escalation deterministically and uses AI only for wording

### LMS data

Stored in:

- `lms_events`

Purpose:

- captures engagement behavior
- used to derive recent learning activity features

### ERP data

Stored in:

- `erp_events`

Purpose:

- captures academic performance data
- acts as the trigger source for automated scoring
- can also carry attendance context used for backend reasoning and recovery monitoring

### Finance data

Stored in:

- `finance_events`

Purpose:

- does not go into ML features
- acts only as an external post-prediction modifier

---

## 3. Current Automated Scoring Rule

Automated scoring is already implemented.

### What happens on LMS ingest

Endpoint:

- `POST /ingest/lms`

Behavior:

- stores LMS event
- does not score

### What happens on finance ingest

Endpoint:

- `POST /ingest/finance`

Behavior:

- stores finance data
- does not score

### Event deduplication behavior

To make repeated source retries safer:

- LMS events are deduplicated using their natural event identity:
  - `student_id`
  - `code_module`
  - `code_presentation`
  - `id_site`
  - `event_date`
  - `sum_click`
- ERP events are deduplicated only when `context_fields` includes a stable source identity such as:
  - `source_event_id`
  - `event_id`
  - `record_id`
  - `ingestion_id`
  - `observed_at`
  - `event_time`
  - `event_timestamp`
  - `recorded_at`
- finance events follow the same rule as ERP events

Important:

- identical academic or finance values can legitimately occur at different times
- so ERP and finance are **not** deduplicated just because the numeric values match
- for real university integrations, the strongest pattern is to pass a source event id or event timestamp inside `context_fields`

### What happens on ERP ingest

Endpoint:

- `POST /ingest/erp`

Behavior:

- stores ERP data
- checks whether:
  - student profile exists
  - LMS data exists
- if both exist, scoring runs automatically

So the current automated scoring condition is:

`profile exists + LMS exists + ERP arrives`

Finance is optional.

---

## 4. How Prediction Works

The prediction flow is:

1. load profile
2. load LMS history
3. load latest ERP event
4. load latest finance event
5. assemble model-aligned features
6. run all ML models
7. use the champion model result
8. apply finance modifier externally
9. decide final predicted class using threshold

Important rules:

- ML model is the only source of prediction
- Gemini never changes the risk class
- finance never enters model features
- finance only modifies final probability afterward
- attendance context may strengthen explanation, driver analysis, and recovery interpretation, but it does not directly alter the OULAD-aligned ML feature schema

### Attendance reasoning layer

The backend now interprets attendance context from ERP `context_fields` in a structured way.

Supported attendance context examples:

- `attendance_ratio`
- `attendance_trend`
- `consecutive_absences`
- `missed_sessions_7d`
- `subject_attendance`

Current use of this attendance layer:

- strengthens fallback and Gemini explanation context
- adds attendance-aware risk drivers
- improves recovery scorecard summaries
- influences closure-readiness and recovery resolution suggestions

Important:

- this attendance layer is currently a backend reasoning and intervention aid
- it is not a direct ML input unless the training contract is intentionally redesigned later

### Deterministic operational intelligence layer

After prediction is stored, the backend now also computes three live operational signals from current LMS or ERP context plus prediction history:

- `risk_trend`
- `stability`
- `risk_type`
- `recommended_actions`
- `trigger_alerts`

The backend also now exposes a separate operational context layer for live student handling:

- activity recency
- milestone flags
- SLA tracking

These are not new ML outputs.

They are deterministic backend intelligence fields designed for real-time operational use.

The backend now also exposes a separate on-demand AI assistance layer.

This layer is intentionally different from the deterministic operational layer:

- deterministic logic remains the source of truth
- Gemini is used only for human-facing narrative support
- fallback text is used if Gemini is unavailable

Current on-demand AI assistance uses the latest live case context to generate:

- case summaries for faculty review
- communication drafts for faculty, student, or parent audiences
- recovery-plan suggestions for follow-up support

These outputs do not change:

- prediction
- thresholding
- trend
- stability
- trigger rules
- faculty priority ranking

#### `risk_trend`

This summarizes how the student's risk is moving over time using prediction history.

Current fields include:

- `trend_score`
- `trend_label`
- `trend_direction`
- `current_probability`
- `previous_probability`
- `probability_change`
- `high_risk_count_7d`
- `high_risk_count_14d`
- `high_risk_count_30d`
- `summary`

Examples of current labels include:

- `initial_low_risk`
- `initial_high_risk`
- `newly_high_risk`
- `persistent_high_risk`
- `recovering`
- `worsening`
- `sharp_worsening`
- `improving`
- `strong_improvement`
- `stable`

#### `risk_type`

This classifies the dominant operational risk pattern for the student based on current drivers.

Current output includes:

- `primary_type`
- `secondary_type`
- `summary`
- category score breakdown for:
  - `academic`
  - `attendance`
  - `engagement`
  - `finance`

Current primary types include:

- `academic_decline`
- `attendance_driven`
- `engagement_drop`
- `finance_driven`
- `multi_factor_risk`
- `stable_profile`

#### `recommended_actions`

This is a deterministic action layer based on dominant driver patterns.

Each recommended action currently includes:

- `action_code`
- `title`
- `priority`
- `rationale`

Examples include:

- academic recovery planning
- attendance counselling
- remedial referral
- finance verification
- LMS re-engagement support

Why this layer exists:

- it keeps counsellor-facing operational guidance consistent
- it does not depend on LLM success
- it can be used in real time even when Gemini is unavailable

#### `trigger_alerts`

The backend now also computes deterministic real-time trigger alerts on each scoring pass.

These triggers are operational alert rules, not new ML predictions.

They are designed to catch sharp deterioration patterns that counsellors care about immediately.

Each trigger currently includes:

- `trigger_code`
- `title`
- `severity`
- `rationale`
- `recommended_action`

Current trigger patterns include:

- sharp attendance drop compared with the previous ERP snapshot
- downward attendance pattern
- repeated consecutive absences
- sudden submission-rate deterioration
- repeated missed or late submissions
- sharp marks drop compared with the previous ERP snapshot
- declining assessment trend
- unresolved fee-due pattern
- threshold crossing into high-risk state

Trigger summary output also includes:

- `has_critical_trigger`
- `trigger_count`
- `summary`

Why this matters:

- real universities often want fast trigger-based review even before a long case history is built
- these rules catch operational deterioration patterns in real time
- they can strengthen urgency, queue interpretation, and follow-up planning without changing the ML prediction itself

#### Activity recency

The backend now computes a last meaningful activity summary for live operational review.

Current fields include:

- `last_meaningful_activity_at`
- `last_meaningful_activity_source`
- `days_since_last_meaningful_activity`
- `latest_lms_event_day`
- `summary`

Important:

- this field prefers real source timestamps such as ERP or finance `event_timestamp`
- if only LMS relative day information exists, the backend exposes that as supporting context
- so the timestamp becomes most reliable after real institutional integrations provide absolute source timestamps

#### Milestone flags

The backend now computes milestone flags that indicate whether the student is in a known vulnerable phase.

Current flags include:

- `repeat_attempt_flag`
- `first_year_flag`
- `backlog_heavy_flag`
- `pre_exam_phase_flag`
- `fee_pressure_flag`
- `active_flags`

Current data sources:

- `num_previous_attempts`
- finance overdue state
- optional ERP `context_fields` such as:
  - `semester_number`
  - `year_of_study`
  - `backlog_count`
  - `academic_phase`

This means the system already supports milestone-aware logic, and it becomes richer as real university ERP fields are mapped.

#### SLA tracking

The backend now computes live workflow SLA summaries for counsellor operations.

Current fields include:

- `sla_status`
- `hours_since_latest_prediction`
- `hours_since_warning_created`
- `hours_to_first_faculty_action`
- `hours_open_without_faculty_action`
- `followup_overdue`
- `summary`

Current SLA interpretation supports statuses like:

- `within_sla`
- `attention_needed`
- `overdue`
- `within_monitoring`
- `not_applicable`

Why this matters:

- it shows whether the system or faculty workflow is acting fast enough
- it makes early-warning performance measurable instead of only descriptive

#### `stability`

The backend now also computes a deterministic prediction stability signal.

This is different from the human-readable `ai_insights.confidence` wording.

Current stability output includes:

- `stability_score`
- `stability_label`
- `threshold_distance`
- `model_agreement_ratio`
- `probability_spread`
- `recent_volatility`
- `summary`

How it is currently derived:

- distance from threshold
- agreement between champion and challenger model outputs
- spread between model probabilities
- short-term movement compared with recent prediction history

Current labels include:

- `very_stable`
- `stable`
- `watchlist`
- `volatile`

Why this matters:

- it helps counsellors know whether the case is strongly supported or borderline
- it improves real-time decision quality without relying on LLM wording alone
- it gives the LLM a stronger operational context for explanation, while keeping the actual decision deterministic

---

## 5. Gemini And Fallback Reasoning

After the final risk result is computed, the system generates `ai_insights`.

### Primary reasoning layer

- `Gemini`

### Backup reasoning layer

- rule-based fallback

The system always tries Gemini first for every student:

- low risk
- medium risk
- high risk

If Gemini succeeds:

- `ai_insights.source = "gemini"`

If Gemini fails because of quota, provider load, or temporary error:

- fallback reasoning is used
- `ai_insights.source = "fallback"`

This guarantees the API keeps working even when the external LLM is temporarily unavailable.

### Gemini retry behavior

Before fallback is used, the system now retries Gemini with exponential backoff.

Default retry behavior:

- `GEMINI_MAX_RETRIES = 3`
- `GEMINI_RETRY_BASE_DELAY_SECONDS = 2.0`

So the system is more resilient than a single-shot LLM call.

---

## 6. Prediction History

Every completed score is stored in:

- `prediction_history`

Stored fields include:

- champion model
- threshold
- base predicted class
- base probability
- finance modifier
- final probability
- final predicted class
- challenger predictions
- `ai_insights`
- `created_at`

This allows:

- latest prediction lookup
- history view
- alert linking
- warning linking

Important:

- `risk_trend`
- `stability`
- `risk_type`
- `recommended_actions`
- `trigger_alerts`

are now persisted on new `prediction_history` rows at scoring time.

This means:

- new scores keep an auditable snapshot of the operational intelligence that was shown when the score was created
- older historical rows that predate this persistence change still remain readable through live fallback computation in the APIs

---

## 7. Student-First Warning Workflow

This was added to make the system more realistic and institution-friendly.

Instead of immediately emailing faculty on first high-risk detection, the system now warns the student first.

### Warning table

Student warnings are stored in:

- `student_warning_events`

Fields include:

- `student_id`
- `prediction_history_id`
- `warning_type`
- `risk_level`
- `final_risk_probability`
- `recipient`
- `delivery_status`
- `error_message`
- `sent_at`
- `recovery_deadline`
- `resolved_at`
- `resolution_status`

### When student warning is sent

A student warning is created when:

- the student is currently `HIGH` risk
- there is no active unresolved warning already open

Current warning type:

- `initial_student_warning`

### What the warning means

It means:

- the student has entered a high-risk state
- the student gets a support-oriented warning first
- a recovery window is opened
- faculty is not alerted yet

---

## 8. Recovery Window

When a student warning is created, the system also stores:

- `recovery_deadline`

This is currently configurable through:

- `RECOVERY_WINDOW_DAYS`

Current default:

- `7` days

That means:

- student receives warning now
- system waits for the defined recovery period
- faculty should only be contacted later if the student still remains high risk

---

## 9. What Happens During The Recovery Window

During the recovery window:

- faculty does not receive escalation mail
- the student warning remains active
- future scoring can still happen normally
- if the student recovers and is no longer high risk, the warning is resolved as:
  - `resolution_status = recovered`

So the recovery window protects the student from immediate faculty escalation.

---

## 10. Faculty Escalation Workflow

Faculty escalations are stored separately in:

- `alert_events`

This separation is intentional.

### Why alerts are stored separately

Because:

- student warning and faculty escalation are different events
- the warning should remain as history even after escalation

### What alert type is used after recovery window

When escalation happens after the recovery window, the faculty alert is stored with:

- `alert_type = post_warning_escalation`

Important:

- `warning_type` in `student_warning_events` remains:
  - `initial_student_warning`
- that row is not deleted
- instead it is updated with:
  - `resolution_status = escalated_to_faculty`
  - `resolved_at = ...`

So the warning history stays intact.

---

## 11. How Faculty Escalation Now Works In Real Time

Initially, faculty escalation happened only when the student was scored again after the recovery window.

That was improved.

The system now includes a background recovery monitor.

### What the monitor does

It periodically checks:

- unresolved student warnings
- whose `recovery_deadline` has already passed

If the latest prediction for that student is still `HIGH`, the system:

1. creates a faculty alert event
2. sends faculty mail
3. resolves the student warning as escalated

### Why this matters

This means faculty escalation no longer depends only on a future ERP/LMS event.

It can now happen automatically based on time.

### Monitor interval

Config:

- `RECOVERY_ESCALATION_CHECK_SECONDS`

Current default:

- `60` seconds

So the backend checks approximately once per minute for expired recovery windows.

### Important practical condition

The backend server must be running for this automated monitor to work.

If the server is down during the exact deadline, the next startup/check cycle will catch the expired warning and escalate then.

---

## 12. Queue And Worker Architecture

The system now separates API request handling from background operational work.

### API responsibility

The FastAPI server now focuses on:

- ingesting data
- scoring students
- storing predictions and event rows
- enqueueing background jobs

### Worker responsibility

A separate worker process now handles:

- queued student warning emails
- queued faculty escalation emails
- queued faculty follow-up reminder emails
- recovery monitor loop
- daily summary monitor loop

### Why this was changed

Earlier, inline SMTP sending and monitor loops lived inside the API process. That made the API carry operational load that is better handled separately.

Now the system does this:

1. score is completed
2. DB event row is created with `pending`
3. a background job row is queued
4. API response returns
5. worker process picks up the queued job
6. worker sends email
7. DB event row is updated to:
  - `sent`
  - `failed`
  - or `skipped`

### Result

This makes the system much more production-minded:

- faster response path
- less blocking
- mail failures do not break scoring

### Email retry behavior

Both student-warning and faculty-alert dispatch now support bounded retry attempts for transient SMTP failures.

Current retry config:

- `EMAIL_MAX_RETRIES`
- `EMAIL_RETRY_DELAY_SECONDS`

Retry metadata is stored on the event rows themselves:

- `student_warning_events.retry_count`
- `alert_events.retry_count`

This means warning/alert history now shows not only final mail status, but also how many attempts were made before success or final failure.

### Running the system now

To get the full live workflow, both processes should run:

- API:
  - `python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000`
- worker:
  - `python -m src.worker.runner`

---

## 13. Faculty Intervention Tracking

The system now tracks human faculty follow-up actions separately from system-generated alerts.

### Intervention table

Faculty actions are stored in:

- `intervention_actions`

Fields include:

- `student_id`
- `alert_event_id`
- `action_status`
- `actor_name`
- `notes`
- `alert_validity`
- `false_alert_reason`
- `reviewed_by`
- `reviewed_at`
- `outcome_status`
- `outcome_notes`
- `outcome_recorded_by`
- `outcome_recorded_at`
- `created_at`

### Why this table exists

The system can automatically detect and send warnings or escalations, but it should not guess whether faculty actually:

- saw the case
- contacted the student
- provided support
- resolved the case

So those are logged manually as real human actions.

### Current faculty action types

Examples include:

- `seen`
- `acknowledged`
- `contacted`
- `support_provided`
- `resolved`

### How intervention status affects the workflow now

The system does not just store these actions anymore. It also uses them operationally:

- if faculty marks a case as `resolved` for the current high-risk prediction, that case is removed from the active faculty queue
- the recovery scorecard now shows latest intervention details
- the time-based recovery monitor will not escalate again if faculty has already resolved the current case

So intervention actions are now part of workflow behavior, not just historical notes.

### False-alert review and outcome tracking

The same intervention record now also supports operational review and outcome evidence.

This means faculty can later update an intervention with:

- whether the alert was actually valid
- whether it was a false alert
- who reviewed it
- what the observed outcome was
- who recorded that outcome

This is intentionally stored on the intervention row so the system keeps one auditable faculty-action timeline instead of splitting action and review into disconnected tables.

Current review endpoint:

- `POST /interventions/review`

Current outcome endpoint:

- `POST /interventions/outcome`

Current accepted operational values are intentionally simple and human-entered, for example:

- alert validity:
  - `valid_alert`
  - `false_alert`
- outcome status:
  - `improved`
  - `no_change`
  - `worsened`
  - `unresolved`

Why this matters:

- counsellor feedback is now captured explicitly
- false alerts can now be measured instead of only guessed
- intervention quality can now be analyzed over time

---

## 14. Automated Follow-Up Reminder Workflow

The escalation flow has been extended one step further.

### New reminder type

If a faculty escalation is already sent but no faculty action is logged for some time, the system can now send:

- `faculty_followup_reminder`

### When reminder is sent

Reminder is sent only if all of these are true:

- `post_warning_escalation` already exists
- the escalation email was actually sent successfully
- the student is still currently `HIGH` risk
- no faculty intervention was logged after that escalation
- no reminder was already sent for that same escalation cycle
- the reminder delay has passed

### Reminder delay

Current config:

- `FOLLOWUP_REMINDER_DELAY_HOURS`

Current default:

- `48` hours

### Why this matters

This makes the system more realistic:

- first the system escalates to faculty
- then it waits for faculty follow-up
- if the case still remains untouched, it reminds automatically

This avoids both extremes:

- no reminder at all
- repeated reminder spam

The current implementation sends only one reminder per unresolved escalation cycle.

---

## 15. Status Fields Meaning

### Student warning status

In `student_warning_events.delivery_status`:

- `pending`
  - warning was created, background dispatch not finished yet
- `sent`
  - warning email was delivered successfully
- `failed`
  - SMTP attempt failed
- `skipped`
  - no student email or SMTP config was available

### Faculty alert status

In `alert_events.email_status`:

- `pending`
- `sent`
- `failed`
- `skipped`

These have the same operational meaning as above.

---

## 16. Timezone Behavior

The database stores timestamps safely in UTC.

For API readability, important timestamps are converted to IST in responses, including:

- `created_at`
- `recovery_deadline`
- warning history timestamps
- alert history timestamps

This makes the system easier to understand for local institutional use.

---

## 17. Faculty Operational APIs

The backend now exposes operational APIs that combine the stored workflow data for faculty use.

### `GET /faculty/priority-queue`

Purpose:

- returns currently active high-risk students who still need attention

Key behavior:

- excludes cases already resolved by faculty for the current risk state
- ranks students using:
  - active/expired recovery state
  - escalation state
  - probability severity
  - repeated-risk behavior
  - relapse behavior
  - latest faculty action status

It now also exposes:

- `risk_trend_score`
- `risk_trend_label`
- `stability_score`
- `stability_label`
- `risk_type`
- `recommended_next_action`
- `active_trigger_codes`
- `has_critical_trigger`
- `last_meaningful_activity_at`
- `last_meaningful_activity_source`
- `active_milestone_flags`
- `sla_status`
- `followup_overdue`

### `GET /faculty/summary`

Purpose:

- gives a one-shot faculty operational overview

Current summary includes:

- total active high-risk students
- total active recovery windows
- total expired recovery windows
- total escalated cases
- total follow-up reminders sent
- total repeated-risk students
- total unhandled escalations

It also returns student lists for:

- active recovery students
- expired recovery students
- escalated students
- follow-up reminder students
- repeated-risk students
- unhandled escalation students

### `GET /timeline/{student_id}`

Purpose:

- combines prediction, warning, and alert history into one timeline for a student

Prediction-created timeline entries now also include:

- `risk_trend_label`
- `stability_label`
- `risk_type`
- `recommended_next_action`
- `trigger_codes`

### `GET /recovery/scorecard/{student_id}`

Purpose:

- shows warning baseline vs current state
- shows whether the student recovered, worsened, or was escalated
- shows attendance-aware recovery interpretation
- now also shows latest faculty intervention details

### Attendance-aware closure behavior

Recovery and closure review are no longer based only on the latest low-risk prediction.

If academic risk improves but attendance is still weak, the backend can keep the case in a follow-up-needed state instead of marking it ready for closure.

Examples of attendance conditions that can block closure readiness:

- low `attendance_ratio`
- negative `attendance_trend`
- repeated `consecutive_absences`
- subject-wise attendance weakness

### `GET /risk-patterns/repeated`

Purpose:

- automatically lists students who repeatedly fall into high risk

### `GET /drivers/{student_id}`

Purpose:

- returns current top risk drivers for a student
- now also includes:
  - `risk_trend`
  - `stability`
  - `risk_type`
  - `recommended_actions`
  - `trigger_alerts`

### `GET /score/latest/{student_id}`

Purpose:

- returns the latest prediction with explanation fields
- now also includes:
  - `risk_trend`
  - `stability`
  - `risk_type`
  - `recommended_actions`
  - `trigger_alerts`

### `GET /score/history/{student_id}`

Purpose:

- returns prediction history for the student
- each history item now also includes:
  - `risk_trend`
  - `stability`
  - `risk_type`
  - `recommended_actions`
  - `trigger_alerts`

### `GET /operations/context/{student_id}`

Purpose:

- returns the current operational context for one student

Current output includes:

- activity summary
- milestone flags
- SLA summary
- latest risk level and probability

This endpoint is especially useful for live counsellor drill-down and future frontend panels.

### `GET /institution/risk-overview`

Purpose:

- returns institution-level aggregate risk analytics for admin, HOD, and future heatmap views

Current output includes:

- total students in the live scored cohort
- total high-risk students
- total students with critical trigger patterns
- total follow-up-overdue students
- total reopened cases
- total repeated-risk students
- department-wise risk buckets
- semester-wise risk buckets
- heatmap-friendly department-semester cells
- top risk-type distribution

Current grouping behavior:

- department label is resolved from ERP `context_fields` when available, using values like:
  - `programme`
  - `branch`
  - `department`
- if those are unavailable, the system falls back to module-based or profile-based placeholders
- semester label is resolved from ERP `context_fields` such as:
  - `semester_number`
  - `year_of_study`
  - `academic_phase`
- if those are unavailable, the system falls back to presentation-based or unknown placeholders

Why this matters:

- it gives the backend a real institution-monitoring layer before frontend exists
- it allows future branch-wise and semester-wise heatmaps to consume stable API data
- it helps admin users identify where risk is concentrating, instead of only reviewing one student at a time

### `GET /ai-assist/case-summary/{student_id}`

Purpose:

- returns an AI-generated faculty-facing summary of the student’s latest live case state

Current output includes:

- `headline`
- `summary`
- `key_points`
- `recommended_followup`
- `source`

### `GET /ai-assist/communication-draft/{student_id}`

Purpose:

- returns an AI-generated ready-to-edit communication draft grounded in the latest live case context

Current supported audiences:

- `faculty`
- `student`
- `parent`

Current output includes:

- `subject`
- `opening`
- `body`
- `closing`
- `audience`
- `source`

### `GET /ai-assist/recovery-plan/{student_id}`

Purpose:

- returns an AI-generated one-week recovery plan grounded in the current live case state

Current output includes:

- `plan_summary`
- `weekly_priorities`
- `support_actions`
- `success_signals`
- `source`

Why this matters:

- the system can now produce practical AI-assisted faculty material on demand
- the outputs stay grounded in the live operational state instead of generic prompting
- frontend can later consume these endpoints directly without adding new reasoning logic in the UI

### `GET /reports/operations-overview`

Purpose:

- returns one consolidated live backend report for admin and reporting use

Current output combines:

- `summary`
  - the faculty operational summary
- `institution_overview`
  - department and semester level risk aggregation
- `intervention_effectiveness`
  - false-alert review and outcome analytics

Why this matters:

- reporting consumers can now fetch one combined operational object instead of stitching three separate APIs
- it prepares the backend for dashboards, admin pages, and report exports
- it keeps live reporting and snapshot reporting aligned around the same data model

### Faculty summary snapshots now include richer reporting payloads

The stored faculty summary snapshot now persists not only:

- faculty operational summary

but also:

- institution overview
- intervention effectiveness analytics

This means emailed and stored snapshots now reflect the broader operational state of the system, not only the queue-level faculty counts.

### `GET /interventions/history/{student_id}`

Purpose:

- returns the full intervention timeline for a student
- now includes review and outcome metadata on each faculty action row

### `GET /interventions/analytics/effectiveness`

Purpose:

- returns aggregated intervention-quality analytics for operational review

Current output includes:

- total intervention actions
- review coverage
- false-alert count and rate
- outcomes recorded
- improved and unresolved counts
- per-action effectiveness summaries

This endpoint is designed for backend reporting first and future admin dashboards later.

So the system now supports both:

- individual student drill-down
- faculty-wide operational overview

---

## 18. Authentication And RBAC

The backend now includes a bearer-token authentication layer and route-level RBAC.

Current supported roles:

- `student`
- `counsellor`
- `admin`
- `system`

### Current auth endpoints

- `POST /auth/login`
- `GET /auth/me`

### Why this matters

Before this phase, the backend behaved like an open prototype API.

Now the route surface is separated by intended product usage:

- student-facing access
- counsellor-facing operational access
- admin-facing reporting access
- internal or system-only ingestion and scoring paths

### Current access model

Public:

- `GET /health`
- `POST /auth/login`

Student-safe:

- own profile
- own latest score/history
- own warning history
- own AI recovery plan
- own self overview

Counsellor/admin:

- faculty queue
- case states
- drivers
- interventions
- warnings review
- AI case summaries
- operational context

Admin/system:

- institution overview
- consolidated reports
- snapshot generation and sending
- ingestion
- internal scoring trigger routes
- export endpoints

### Student self-service endpoint

The backend now includes:

- `GET /student/me/overview`

This endpoint gives the student module a single safe aggregated response containing:

- profile
- latest prediction
- warning history
- AI recovery plan

This is intended to reduce frontend stitching work for the student module.

### Current export endpoints

Admin/system users can now export CSV from:

- `GET /reports/exports/priority-queue`
- `GET /reports/exports/institution-overview`
- `GET /reports/exports/intervention-effectiveness`

These exports are designed for real institutional reporting and manual review workflows.

---

## 19. Demo Flow

The demo script currently performs this order:

1. profile upsert
2. LMS ingest
3. finance ingest
4. ERP ingest

### Low-risk and medium-risk demo students

Behavior:

- auto-score runs
- Gemini/fallback insights are generated
- no student warning
- no faculty alert

### High-risk demo student

Behavior:

- auto-score runs
- Gemini/fallback insights are generated
- `initial_student_warning` is created
- student mail is sent asynchronously
- no faculty alert yet
- `recovery_deadline` is stored

Faculty escalation happens only later if:

- recovery window expires
- and the student still remains high risk

---

## 20. What Is Fully Automated Now

The following are automated:

- profile persistence
- LMS ingest
- finance ingest
- deduplication-aware ingest handling for LMS and source-identified ERP/finance events
- ERP-triggered scoring
- prediction storage
- Gemini reasoning attempt
- fallback reasoning if Gemini fails
- deterministic risk trend computation
- deterministic stability scoring
- deterministic risk type classification
- deterministic action recommendation generation
- deterministic trigger-based alert rule evaluation
- last meaningful activity summarization
- milestone-flag evaluation from profile, ERP context, and finance state
- live SLA summary computation for active workflows
- faculty review capture for valid-alert vs false-alert feedback
- intervention outcome logging for improved/no-change/worsened/unresolved tracking
- intervention effectiveness analytics
- institution-level department and semester aggregate risk analytics
- on-demand AI case summaries, communication drafts, and recovery-plan generation
- consolidated operational reporting and richer faculty summary snapshots
- bearer-token authentication and role-based route protection
- student self-service overview aggregation
- CSV export endpoints for admin reporting
- student warning creation for first high-risk event
- student warning email dispatch
- bounded retry attempts for student warning email dispatch
- recovery deadline tracking
- time-based monitoring of expired recovery windows
- faculty escalation creation
- faculty escalation email dispatch
- bounded retry attempts for faculty escalation and follow-up reminder email dispatch
- time-based follow-up reminder creation for untouched escalations
- warning and alert history persistence

---

## 21. What Is Manual By Design

The following are intentionally manual:

- faculty marking a case as `seen`
- faculty marking a case as `contacted`
- faculty marking a case as `support_provided`
- faculty marking a case as `resolved`
- faculty writing notes about the intervention
- faculty marking whether an alert was valid or a false alert
- faculty recording the observed outcome of an intervention

These should remain human-entered because the system should not falsely pretend it knows what action a faculty member actually performed.

---

## 22. What Is Still A Future Improvement

The system is now strong, but a few production-scale improvements still remain for later:

- richer faculty dashboard / student dashboard
- richer period-aware attendance policies and institution-specific attendance rules
- richer mentor/faculty ownership models beyond a single per-student faculty email
- full guardian escalation delivery over email, SMS, and WhatsApp on top of the new Phase A guardian profile and policy foundation
- replacement of the current local bearer-token auth with university SSO or identity-provider integration
- stronger password and user lifecycle management beyond the current demo login bootstrap

These are enhancements, not blockers for the current workflow.

---

## 23. Current Final Operational Flow

The current live flow can be summarized as:

`Profile + LMS + ERP -> Auto-score -> Gemini/Fallback -> If low/medium: store only`

`Profile + LMS + ERP -> Auto-score -> Gemini/Fallback -> If high: warn student first -> open recovery window -> monitor deadline -> if still high after deadline: escalate to faculty`

`After faculty escalation -> wait for faculty intervention -> if no faculty action is logged after the configured delay and student is still high risk: send one faculty follow-up reminder`

This is the current implemented system behavior.
