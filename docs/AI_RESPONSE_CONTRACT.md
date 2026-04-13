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
