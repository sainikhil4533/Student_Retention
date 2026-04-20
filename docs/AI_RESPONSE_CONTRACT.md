# AI Response Contract

## How To Read This Document

This file is a **contract doc**, not a live behavior walkthrough.

That means it answers:

- what the AI response shape should be
- which layer owns which field
- which rules must not be violated

It does **not** try to explain the full current backend or chatbot flow by itself.

Recommended supporting docs:

- [DOCS_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/DOCS_GUIDE.md)
- [FULL_AI_SYSTEM_ROADMAP.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FULL_AI_SYSTEM_ROADMAP.md)
- [LIVE_SYSTEM_WORKFLOW.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/LIVE_SYSTEM_WORKFLOW.md)
- [STRICT_CHATBOT_SYSTEM_PROMPT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/STRICT_CHATBOT_SYSTEM_PROMPT.md)

### Why This Note Matters

A beginner can easily confuse:

- contract docs
- live workflow docs
- implementation status docs

This file belongs to the **contract** category.

## Purpose

This document defines the exact response structure for the upgraded AI system.

We are doing this **before writing LLM or alert code** so that:

- backend services know what to return
- database logging knows what to store
- alert logic knows what to read
- frontend later knows what to display

This is the stable contract for the next phase of the project.

---

## Why This Step Comes First

Right now, the system already returns:

- champion prediction
- challenger predictions
- finance modifier
- final risk probability
- final predicted class

But the upgraded AI system must also return:

- reasoning
- faculty actions
- urgency
- intervention timeline
- student guidance
- alert status

If we start coding without freezing this structure first, we may have to rewrite:

- `predict_service.py`
- `schemas.py`
- `score.py`
- database models
- frontend later

So this file acts as the blueprint for the AI upgrade.

---

## Core Rules

These rules must not be broken:

1. ML model is the only source of prediction.
2. Finance is not part of ML features.
3. Finance may only act as an external modifier.
4. Feature alignment must remain strict:

```python
assert list(features.columns) == feature_order
```

5. LLM must never override the ML prediction.
6. Existing ML training and feature engineering must not be changed.

---

## Chatbot Grounding Contract

These rules apply to the role-based chatbot layer that explains or summarizes the system.

The chatbot is allowed to:

- explain grounded model results
- explain attendance-policy status
- explain carry-forward academic burden
- compare grouped institutional buckets when the backend supports the grouping
- synthesize multiple grounded signal families together when the question needs it

The chatbot is not allowed to:

- invent unsupported cohort numbers
- silently merge prediction risk and attendance-policy risk into one count when the question is ambiguous
- answer outside the user’s role scope
- pretend a subject is cleared if unresolved `I_GRADE` or `R_GRADE` burden still exists

### Required multi-signal reasoning behavior

When the backend has the data, the chatbot should not behave like a single-table lookup bot.

It should be able to reason across:

- prediction history
- LMS engagement
- ERP academic performance
- finance context
- attendance-policy status
- active academic burden

Example:

- if current attendance looks `SAFE`
- but prediction risk is still `HIGH`

the chatbot should not stop at the attendance status alone.
It should explain what other grounded signals are still driving concern, such as:

- weak assessment performance
- declining submissions
- weak LMS engagement
- finance stress
- unresolved older I/R-grade burden

### Student reasoning-first requirement

For student self-service questions, the chatbot should not rely only on one routed intent bucket when the question clearly asks for a more specific grounded answer.

The student layer should first separate whether the turn is asking for:

- a direct fact
  - for example current semester position
- a grounded count with an availability caveat
  - for example assignment counts when exact assigned-total data is not exposed
- a cross-signal explanation
  - for example finance affecting performance
- a seriousness or consequence explanation
  - for example `should I panic`
- a staged plan
  - for example day-by-day vs week-by-week recovery

That means the student layer should prefer:

- interpret the exact ask
- fetch the relevant grounded slices
- compose the right response type

instead of:

- forcing every question into one generic attendance/risk/plan template.

This rule applies to:

- student self-risk answers
- student safety-check questions
- counsellor student drilldowns
- admin student drilldowns

### Counsellor reasoning-first requirement

For counsellor questions, the chatbot should not treat every natural-language cohort query as one generic risky-student summary.

The counsellor layer should first separate whether the turn is asking for:

- a student-priority view
  - for example who needs attention first
- a scoped subset filter
  - for example only CSE students or only final year
- a cohort explanation
  - for example which factor is affecting most students
- a seriousness or consequence explanation
  - for example should I worry about my group
- a cross-feature comparison
  - for example attendance versus assignments across risky students

That means the counsellor layer should prefer:

- interpret the operational question first
- narrow the scoped student set when needed
- return the right response type for the actual ask

instead of:

- reusing stale cohort memory too early
- or defaulting every fresh counsellor question into one generic cohort count.

### Admin reasoning-first requirement

For admin questions, the chatbot should not treat every fresh institution-level question as a continuation of the previous grouped view or strategy thread.

The admin layer should first separate whether the turn is asking for:

- an institution-health explanation
  - for example `should we be worried`
- a fresh grouped or comparison view
  - for example `branch wise risk` or `compare attendance and risk across branches`
- a strategy or governance move
  - for example `where should we focus` or `give strategic plan`

That means the admin layer should prefer:

- interpret whether the turn is fresh or truly a follow-up
- preserve fresh grouped scope when the user starts a new institutional slice
- return explanation versus strategy in the right stage

instead of:

- reusing stale admin subset memory too early
- or collapsing fresh grouped analysis into the previous action thread.

### Required distinctions

When users ask about `high risk`, the chatbot must be careful because this can mean more than one thing.

It must distinguish:

- `prediction risk`
  - model-based retention risk
- `attendance-policy risk`
  - overall shortage
  - `I_GRADE`
  - `R_GRADE`
- `active academic burden`
  - unresolved earlier `I_GRADE` / `R_GRADE` outcomes still requiring monitoring

If a prompt is naturally ambiguous, the chatbot should separate the layers instead of pretending they are identical.

### Required scope behavior

- `student`
  - only own record
- `counsellor`
  - only assigned students
- `admin`
  - institution-wide view

This scope rule applies to:

- direct answers
- grouped answers
- comparisons
- follow-up questions

### Required grouped-answer behavior

If the chatbot supports a grouped dimension such as:

- branch
- year
- semester
- gender
- category
- region

then grouped follow-up continuity must stay honest.

Example:

1. user asks:
   - `show high risk semester wise, year wise`
2. user follows with:
   - `branch wise also`

The chatbot should continue the same grouped analytical thread, not reset to a generic total count.

### Required promised-follow-up behavior

If the chatbot itself offers a specific next step, then a short natural follow-up should continue that exact thread instead of falling back to an unsupported-intent answer.

Example:

1. student asks:
   - `what is my current attendance`
2. chatbot answers:
   - `If you want, I can next tell you whether this puts you in safe, I-grade, or R-grade territory.`
3. student follows with:
   - `ok tell`

The chatbot should continue with the attendance-territory answer.
It should not reset and ask the student to restate the full intent again.

This should hold even for very short natural continuations such as:

- `ok`
- `continue`
- `then?`
- `proceed`

When possible, the system should resolve these using the last assistant memory context locally before relying on any external semantic provider.

This also applies to action-oriented student follow-ups such as:

- `proceed with overall recovery priorities`
- `how can i recover from high alert`
- `how can i remove the HIGH label risk`

Those should continue the same grounded advisory thread.
They should not collapse back into a generic risk restatement or a clarification request when the current student data is already sufficient.

This continuity rule also applies across mixed analytical chains such as:

1. grouped answer
2. grouped extension
3. ambiguity explanation

Example:

1. admin asks:
   - `show high risk semester wise, year wise`
2. follows with:
   - `branch wise also`
3. then asks:
   - `what do you mean by that?`

The chatbot should continue the same analytical thread.
It should not reset to a generic risk answer or lose the distinction between:

- prediction risk
- attendance-policy risk
- active academic burden

### Required uncleared-burden behavior

If unresolved `I_GRADE` or `R_GRADE` burden exists:

- the chatbot must not talk as if the subject is fully passed
- counsellor answers must keep those students visible for monitoring
- student answers must explain that the burden remains active until actual clearance

This rule applies even if current-semester performance looks better.

---

## Final Response Shape

The upgraded score response should conceptually become:

```json
{
  "risk_score": 0.82,
  "risk_level": "HIGH",
  "confidence": "High confidence based on strong academic and engagement signals",
  "reasoning": "The student shows low assessment performance and weak LMS engagement.",
  "actions": [
    "Schedule mentor meeting",
    "Review missed assessments",
    "Monitor LMS activity over the next 7 days"
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

This does **not** replace the current useful fields immediately.
Instead, it defines the enriched contract we will layer onto the existing system carefully.

---

## Field Ownership

This is the most important part.

Each field must have a clear owner.

### 1. ML-Owned Fields

These are determined only by the ML system and threshold logic:

- `risk_score`
- `risk_level`

#### `risk_score`

- source: champion ML model probability
- this is the base model output
- not created by the LLM

#### `risk_level`

- source: threshold logic
- must not be decided by the LLM

Example:

- score below threshold -> `LOW` or `MEDIUM` depending on design
- score above threshold -> `HIGH`

Note:
we may later keep `LOW / MEDIUM / HIGH` as a banded version of existing threshold logic, but the decision logic will still remain deterministic.

---

### 2. Finance Modifier Fields

These are determined by the existing external finance logic:

- `finance_modifier`
- `final_risk_probability`
- `final_predicted_class`

#### Important rule

Finance does not change:

- ML feature set
- ML prediction process

Finance only affects the final post-prediction adjusted result.

So the internal order stays:

`ML prediction -> external finance modifier -> final adjusted result`

---

### 3. Explanation / Reasoning Fields

These come from fallback rules or the LLM:

- `confidence`
- `reasoning`
- `actions`
- `urgency`
- `timeline`

These fields are **explanatory and advisory**, not predictive.

#### `confidence`

This should be deterministic or fallback-based at first.

Reason:
- confidence should not become vague or unstable because of LLM wording

It may later depend on:

- margin from threshold
- strength of signals
- consistency of model outputs

#### `reasoning`

This explains:

- why the student is at risk or safe
- what main signals are contributing

Examples:

- weak LMS engagement
- low assessment score
- low submission rate
- repeated late submissions

#### `actions`

These are faculty-facing intervention suggestions.

Examples:

- schedule mentor meeting
- review missed assessments
- monitor next 7 days
- contact academic advisor

#### `urgency`

Allowed values:

- `LOW`
- `MEDIUM`
- `HIGH`

#### `timeline`

Examples:

- `Immediate`
- `Within 3 days`
- `Monitor weekly`

---

### 4. Student Guidance Fields

These are student-facing and must be supportive.

Structure:

```json
"student_guidance": {
  "summary": "...",
  "suggestions": [...],
  "motivation": "..."
}
```

#### `summary`

Simple explanation in non-threatening language.

#### `suggestions`

Concrete steps the student can take.

Examples:

- log into LMS daily
- finish pending assignments
- meet faculty mentor

#### `motivation`

Encouraging line.

Tone must always be:

- supportive
- calm
- non-judgmental

---

### 5. Operational Field

- `alert_sent`

This tells us whether the faculty alert flow actually triggered successfully.

Important:

- email failure must not break the API
- `alert_sent` can be `false` even if the student is high risk, if sending failed

---

## Proposed Internal Flow

This is the correct future execution order:

1. Build aligned features
2. Enforce feature order
3. Run champion ML model
4. Compute base `risk_score`
5. Compute `risk_level`
6. Apply external finance modifier
7. Compute `final_risk_probability`
8. Compute `final_predicted_class`
9. Generate fallback or LLM insights
10. Trigger alert if needed
11. Save enriched response to database
12. Return enriched API response

Important:

- LLM comes **after** prediction
- alert comes **after** prediction
- student guidance comes **after** prediction

So the architecture remains:

`Predict -> Explain -> Decide -> Act -> Guide`

---

## Fallback Requirement

The API must never fail just because OpenAI is unavailable.

So every explanatory field must have a fallback path.

If LLM fails:

- use rule-based reasoning
- use default actions
- use default urgency
- use default timeline
- use default student guidance

This means the API response shape must remain the same whether OpenAI works or not.

---

## Database Planning

These fields will eventually need to be stored in DB:

- `risk_score`
- `risk_level`
- `finance_modifier`
- `final_risk_probability`
- `final_predicted_class`
- `confidence`
- `reasoning`
- `actions`
- `urgency`
- `timeline`
- `student_guidance`
- `alert_sent`

This matters because:

- frontend will need them later
- history endpoint will need them later
- faculty audit trail depends on them

---

## Frontend Impact

This contract is also the foundation for frontend later.

### Faculty dashboard needs

- risk score
- risk level
- reasoning
- actions
- urgency
- timeline
- alert status

### Student dashboard needs

- summary
- suggestions
- motivation

So this file helps us avoid changing frontend API shape repeatedly later.

---

## What Happens Next

After this contract is accepted, the correct next implementation step is:

### Phase 2

Create:

- `src/ai/fallback_reasoning.py`

Why first:

- safer than OpenAI integration
- gives stable response even if LLM is unavailable
- lets us test the enriched system before external API dependency

Only after that should we add:

- `src/ai/llm_service.py`
- alert email service
- DB enrichment updates

---

## Final Summary

This document defines:

- what the AI system must return
- who owns each field
- why LLM must remain explanation-only
- how finance remains external
- why fallback must exist

This is the blueprint for all next implementation steps.

---

## Cross-Role Operational Continuation

The contract now also expects operational follow-up behavior for:

- `student`
- `counsellor`
- `admin`

This means the assistant should not stop at:

- counts
- grouped breakdowns
- pressure ranking

If the assistant itself has already explained:

- which bucket is worse
- which branch needs attention first
- which students need weekly monitoring
- which students are in the priority queue

then short follow-ups like:

- `ok`
- `continue`
- `proceed`
- `what should we do first`
- `what should i do first`
- `how do we reduce this`

should continue into a grounded action layer instead of falling back to generic clarification.

The response must stay:

- role-scoped
- data-grounded
- multi-signal aware

For `counsellor`, that action layer should connect:

- priority queue
- unresolved I/R-grade burden
- scoped subject hotspots
- scoped pressure buckets

For `admin`, that action layer should connect:

- institution priority queue
- subject hotspots
- branch / semester pressure
- carry-forward burden governance

So the chatbot behaves more like:

- a data-aware operational assistant

and less like:

- a static reporting bot that only repeats counts.
## Shared Core Defaults

The chatbot now follows a stricter shared-core policy before role-specific logic runs:

- simple student `assignment rate` questions default to `assignment submission rate`
- simple student `attendance` questions default to `overall attendance`
- simple student `risk` questions default to `current risk level`
- simple student `lms details` / `lms activity` questions default to `current LMS activity summary`
- simple student `erp details` questions default to `current ERP academic-performance summary`
- simple student `finance details` / `fee status` questions default to `current finance summary`
- simple counsellor `risk` questions default to `which students are high risk`
- simple admin `risk` questions default to `how many students are high risk`

Short replies like `yes`, `ok`, `continue`, and `proceed` are treated as continuation signals when the prior assistant turn left usable memory context.

Clarification should only happen when the ambiguity is genuinely dangerous. If a clarification has already been asked for a topic and the user replies vaguely, the chatbot should continue with the remembered best safe assumption instead of asking the same clarification again.

For student self-service flows, explanation answers should also leave a usable next-step memory context whenever a reasonable action continuation exists. This lets short replies like `ok` naturally continue from explanation into action instead of reopening clarification.

For the student role, the runtime should now also preserve a lightweight conversation-control layer in memory so short replies can continue safely without guessing from scratch every turn. In practice, the student flow now carries:

- `last_intent`
- `last_topic`
- `response_type`
- `pending_student_follow_up`

This supports the student rule set more explicitly:

- `data_request`
  - return the requested grounded metrics first
- `explanation_request`
  - explain why the current student state looks the way it does
- `action_request`
  - move into recovery / next-step guidance instead of re-dumping all the same metrics again
- `followup_request`
  - short replies like `yes`, `ok`, `continue`, and `proceed` should continue the last student thread when a safe next step is already known

The student default-assumption layer should stay broad but safe:

- `attendance` -> overall current attendance
- `assignment rate` -> current assignment submission rate
- `risk` -> current risk level

The student follow-up layer should also tolerate topic switching:

- `risk` -> `what is my lms activity`
- `risk` -> `what is my erp data`
- `risk` -> `fee status`

Those should be treated as fresh grounded student data requests, not as stale risk-thread repetition.

Topic switching should also stay honest. If a student asks a fresh first-class data question after a prior answer, the chatbot should switch topics instead of repeating the previous one. This applies to:

- `what is my LMS details`
- `give me my lms activity`
- `what is my erp details`
- `what is my finance details`

Those should resolve to grounded LMS / ERP / finance summaries first, then short follow-ups like `ok` should continue into the matching impact thread instead of resetting or repeating the older risk answer.

For counsellor flows, the same contract now applies in scoped multi-student form:

- simple `students?` should default to the current assigned-student view
- simple `risk` should default to the current high-risk student view
- counsellor runtime memory should also preserve:
  - `last_intent`
  - `last_topic`
  - `response_type`
  - `pending_role_follow_up`
- student-specific explanations should continue into student-specific actions when the counsellor replies with a short follow-up like `ok`
- counsellor short follow-ups such as `yes`, `yeah`, `yep`, `ok`, `continue`, and `proceed` should continue the current safe counsellor thread instead of reopening clarification
- grouped subset follow-ups such as `show only CSE` and `what about top 5` should continue the same scoped cohort instead of reopening clarification
- fresh topic switches such as `show my assigned students` -> `which students have i grade risk` -> `what should i do for high risk students` should move into the new scoped topic instead of staying trapped in the older subset context
- counsellor response mode should stay explicit:
  - `data_request` -> scoped student/cohort metrics first
  - `explanation_request` -> explain why a student or scoped cohort looks risky
  - `action_request` -> move into grounded counsellor actions instead of repeating the same data dump

For admin flows, the same contract now applies institution-wide:

- simple `stats` should default to the current institution high-risk snapshot
- simple `trend` should default to the recent high-risk-entry view for the last 30 days
- admin runtime memory should also preserve:
  - `last_intent`
  - `last_topic`
  - `response_type`
  - `pending_role_follow_up`
- strategy prompts such as `what strategy should we take` or `how to reduce dropout risk` should resolve to an institution-level action list
- grouped admin follow-ups such as `branch-wise risk` -> `only CSE` -> `continue` should move from grouped view to focused subset to grounded admin actions
- grouped admin answers must keep prediction high risk separate from attendance-policy risk layers
- institution-level signal questions such as `compare lms vs erp impact`, `how finance is affecting risk`, `which factor impacts performance most`, and `hidden risk across departments` should resolve to grounded institution-health explanations instead of clarification or generic count fallback
- grouped institutional prompts such as `year wise performance`, `risk by department`, `performance by branch`, and `compare 1st year vs final year` should resolve to grouped institutional breakdowns instead of stale subset follow-up reuse
- fresh topic switches such as `risk` -> `trend` -> `subject hotspot` -> `what strategy should we take` should answer the new institutional topic directly instead of repeating the previous admin answer
- explanation-to-action continuity must also hold for admin institution-health threads, so short continuations like `ok`, `continue`, and `give full solution plan` should move into grounded operational strategy rather than resetting to unsupported
- grouped admin follow-ups should stay analytical across deeper chains, so prompts like `only CSE` -> `compare with ECE` -> `why is CSE worse` -> `what should we fix first` should stay inside the same grouped decision thread instead of falling into clarification or generic subset fallback
- admin response mode should stay explicit:
  - `data_request` -> institution metrics or grouped counts first
  - `explanation_request` -> explain grouped differences, drivers, or risk-layer differences
  - `action_request` -> move into institutional strategy or operational action instead of re-dumping the same counts
