# Feature Contract

## How To Read This Document

This file defines the feature rules for the ML side of the project.

Use it when you want to answer questions like:

- which fields are allowed into the model
- which fields are forbidden
- how finance is treated
- how runtime feature alignment is enforced

Recommended supporting docs:

- [DOCS_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/DOCS_GUIDE.md)
- [DATA_DICTIONARY.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/DATA_DICTIONARY.md)
- [AI_RESPONSE_CONTRACT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/AI_RESPONSE_CONTRACT.md)

Why this matters:

This file protects the project from uncontrolled feature drift.
It is a rules doc, not a chatbot or live-workflow doc.

This document defines the exact contract between:

- ML training on the Kaggle/OULAD dataset
- runtime feature building from LMS, ERP, and finance sources
- backend prediction APIs

This file must be treated as the source of truth for model input rules.

## 1. Core Principle

The ML model is trained only on features that are available in the OULAD dataset and can also be computed from real-time institutional systems.

This means:

- training data source = OULAD / Kaggle dataset
- runtime data sources = LMS, ERP, finance, and other institutional systems
- model input = only approved aligned features
- non-aligned fields = never passed into the model

## 2. Approved Model Input Features

Only the following aligned features are allowed to go into the ML model.

### Demographics

1. `age_band`
2. `gender`
3. `highest_education`
4. `num_previous_attempts`
5. `disability_status`

### LMS Engagement

6. `lms_clicks_7d`
7. `lms_clicks_14d`
8. `lms_clicks_30d`
9. `lms_unique_resources_7d`
10. `days_since_last_lms_activity`

### Academic Performance

11. `assessment_submission_rate`
12. `weighted_assessment_score`
13. `late_submission_count`
14. `total_assessments_completed`

### Trends

15. `lms_7d_vs_14d_percent_change`
16. `assessment_score_trend`
17. `engagement_acceleration`

## 3. Forbidden Model Inputs

The following must not be used as direct model inputs unless the training pipeline and this contract are intentionally redesigned and approved.

### Forbidden because they are not part of the OULAD-aligned model

- attendance fields not explicitly mapped into the approved aligned schema
- finance fields
- hostel status
- scholarship status
- family income
- transport usage
- manual advisor notes
- department remarks
- raw ERP fields that do not map to approved aligned features

### Important rule

If a field is not in the approved aligned feature list, it must not be sent into the model.

## 4. ERP Usage Rule

ERP fields are allowed only if they are mapped to approved aligned features.

Rule:

- ERP field mapped to aligned feature -> allowed for model feature construction
- ERP field not mapped to aligned feature -> context only

Examples:

- `attendance_ratio` -> allowed only if it is intentionally mapped into an approved aligned feature or approved proxy
- `hostel_status` -> context only
- `section_name` -> context only
- `mentor_id` -> context only

## 5. Finance Usage Rule

Finance data may exist in real-time production data, but it is not part of ML training for the OULAD-aligned model.

So finance must be handled outside the ML model.

Allowed finance usage:

- store finance data in the database
- show finance signals on dashboard or case review screens
- use finance only as a small external post-prediction modifier

Forbidden finance usage:

- do not train the OULAD model on finance features
- do not pass finance columns into runtime model input
- do not let finance change the model feature schema

## 6. External Modifier Policy

If finance is used in scoring, it must be applied only after the model prediction as a simple external modifier.

Allowed pattern:

- `+0.05`
- `+0.10`
- hard cap on total modifier = `0.20`

Not allowed:

- complex formulas
- chained weighting logic
- hidden heuristic scoring systems
- replacing the original model output with rule-only logic

Example safe flow:

`aligned model features -> model prediction -> optional finance modifier -> final capped risk score`

## 7. Runtime Feature Alignment Rule

At runtime, the prediction system must build only the approved aligned features.

Before prediction:

1. load the saved `feature_order` from the model artifact
2. reorder runtime features to match that order
3. assert exact equality

Required enforcement:

```python
assert list(features.columns) == feature_order
```

If this assertion fails, prediction must stop immediately.

## 8. Feature Order Contract

The training pipeline must save the exact feature order used during model fitting.

The runtime inference pipeline must use that same order without exception.

This prevents:

- silent feature mismatch bugs
- reordered columns producing incorrect predictions
- hidden deployment failures

## 9. Output Contract

The prediction system should produce:

- base model risk score
- optional external modifier value
- final risk score
- explanation of major aligned signals
- context fields for advisor visibility

This keeps the model decision separate from business context.

## 10. Event Identity Contract For Real-Time Ingestion

For safe real-time ingestion, ERP and finance payloads should carry a stable source event identity in `context_fields`.

Recommended keys:

- `source_event_id`
- `event_id`
- `record_id`
- `ingestion_id`
- `observed_at`
- `event_time`
- `event_timestamp`
- `recorded_at`

Why this matters:

- same submission rate or same overdue amount may legitimately appear again later
- deduplication should happen only for the same source event, not for repeated values across time

Preferred production pattern:

`university source event id/timestamp -> store in context_fields -> deduplicate safely at ingest`

## 11. Working Rule For This Project

For this project, we will proceed with the following strict separation:

- model training = OULAD aligned features only
- runtime model input = approved aligned features only
- ERP extra fields = context unless mapped
- finance = external modifier only
- frontend will be built last

Any change to this contract must be explicitly approved before implementation.
