# OULAD Data Dictionary

## How To Read This Document

This file is the data-understanding guide.

Use it when you want to understand:

- what each dataset file means
- how files join together
- which raw fields feed the project
- how approved model features relate to source data

Recommended supporting docs:

- [DOCS_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/DOCS_GUIDE.md)
- [FEATURE_CONTRACT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FEATURE_CONTRACT.md)

If you want live backend behavior rather than raw data understanding, read:

- [LIVE_SYSTEM_WORKFLOW.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/LIVE_SYSTEM_WORKFLOW.md)

This file explains the raw OULAD dataset tables in beginner-friendly language.

The purpose is to help us understand:

- what each CSV file contains
- how the files are connected
- which approved aligned features come from which source

## 1. Big Picture

The OULAD dataset is split across multiple CSV files.

Each file contains one part of the student journey:

- student profile and final outcome
- course metadata
- LMS activity
- assessments and scores
- registration timeline

We combine these files to create a single training dataset for the ML model.

## 2. Main Join Keys

These columns are used to connect files together.

- `id_student` = unique student identifier
- `code_module` = course/module code
- `code_presentation` = presentation/session code
- `id_assessment` = unique assessment identifier
- `id_site` = unique LMS content/resource identifier

In many places, a student record is uniquely identified by:

- `id_student`
- `code_module`
- `code_presentation`

## 3. File Explanations

### `studentInfo.csv`

What it contains:

- one row per student-course-presentation combination
- demographic information
- historical student information
- final academic outcome

Important columns:

- `id_student`
- `code_module`
- `code_presentation`
- `gender`
- `highest_education`
- `age_band`
- `num_of_prev_attempts`
- `disability`
- `final_result`

Why it matters:

- this is the main base table for training
- it contains the target outcome we want to predict
- it provides the demographic aligned features

Aligned features supported:

- `age_band`
- `gender`
- `highest_education`
- `num_previous_attempts`
- `disability_status`

Likely target source:

- `final_result`

### `studentVle.csv`

What it contains:

- student interactions with LMS learning resources
- date of interaction
- number of clicks

Important columns:

- `id_student`
- `code_module`
- `code_presentation`
- `id_site`
- `date`
- `sum_click`

Why it matters:

- this is the main LMS behavior log
- it helps us measure engagement over recent time windows

Aligned features supported:

- `lms_clicks_7d`
- `lms_clicks_14d`
- `lms_clicks_30d`
- `days_since_last_lms_activity`

Works together with:

- `vle.csv`

### `vle.csv`

What it contains:

- metadata about LMS sites/resources
- type of activity or content

Important columns:

- `id_site`
- `code_module`
- `code_presentation`
- `activity_type`

Why it matters:

- this helps us understand what kind of resource a student interacted with
- it helps measure resource diversity

Aligned features supported:

- `lms_unique_resources_7d`

Works together with:

- `studentVle.csv`

### `studentAssessment.csv`

What it contains:

- student submissions and scores for assessments

Important columns:

- `id_assessment`
- `id_student`
- `date_submitted`
- `score`
- `is_banked`

Why it matters:

- this gives us observed student performance
- it tells us whether students are submitting and how well they score

Aligned features supported:

- `weighted_assessment_score`
- `late_submission_count`
- `total_assessments_completed`

Works together with:

- `assessments.csv`

### `assessments.csv`

What it contains:

- metadata for each assessment
- type, due date, and weight

Important columns:

- `id_assessment`
- `assessment_type`
- `date`
- `weight`

Why it matters:

- it gives the official due date of each assessment
- it gives the assessment weight needed for weighted score calculation

Aligned features supported:

- `assessment_submission_rate`
- `weighted_assessment_score`
- `late_submission_count`
- `assessment_score_trend`

Works together with:

- `studentAssessment.csv`

### `studentRegistration.csv`

What it contains:

- student registration and unregistration timing

Important columns:

- `id_student`
- `code_module`
- `code_presentation`
- `date_registration`
- `date_unregistration`

Why it matters:

- helps us understand whether a student withdrew early
- may help create valid time windows for training

Possible usage:

- filtering invalid or partial records
- understanding timing of dropout events

### `courses.csv`

What it contains:

- course/module presentation metadata

Important columns:

- `code_module`
- `code_presentation`
- `module_presentation_length`

Why it matters:

- gives the overall length of the course presentation
- helps when defining relative timeline windows

Possible usage:

- normalizing time-based features
- validating date ranges

## 4. How The Files Connect

Typical joins:

1. Start from `studentInfo.csv`
2. Join LMS activity from `studentVle.csv`
3. Join LMS metadata from `vle.csv`
4. Join student assessment records from `studentAssessment.csv`
5. Join assessment metadata from `assessments.csv`
6. Optionally join registration timing from `studentRegistration.csv`
7. Optionally join course metadata from `courses.csv`

## 5. Approved Feature Mapping

This section maps approved aligned features to likely raw sources.

### Demographics

- `age_band` -> `studentInfo.csv`
- `gender` -> `studentInfo.csv`
- `highest_education` -> `studentInfo.csv`
- `num_previous_attempts` -> `studentInfo.csv` using `num_of_prev_attempts`
- `disability_status` -> `studentInfo.csv` using `disability`

### LMS Engagement

- `lms_clicks_7d` -> `studentVle.csv`
- `lms_clicks_14d` -> `studentVle.csv`
- `lms_clicks_30d` -> `studentVle.csv`
- `lms_unique_resources_7d` -> `studentVle.csv` + `vle.csv`
- `days_since_last_lms_activity` -> `studentVle.csv`

### Academic Performance

- `assessment_submission_rate` -> `studentAssessment.csv` + `assessments.csv`
- `weighted_assessment_score` -> `studentAssessment.csv` + `assessments.csv`
- `late_submission_count` -> `studentAssessment.csv` + `assessments.csv`
- `total_assessments_completed` -> `studentAssessment.csv`

### Trends

- `lms_7d_vs_14d_percent_change` -> derived from LMS rolling windows
- `assessment_score_trend` -> derived from assessment history over time
- `engagement_acceleration` -> derived from change in LMS activity trend

## 6. Important Beginner Note

The raw CSV files do not directly contain the final 17 approved aligned features.

Instead:

- some features come directly from one column
- some features require joining two files
- some features are engineered by aggregating events over time

That is why the next coding step will be feature engineering, not model training immediately.

## 7. Project Rule Reminder

Even if live ERP or finance systems later provide extra fields, those fields must not be added into the ML model unless they are part of the approved aligned contract.

So:

- OULAD-aligned fields -> model input
- unmapped ERP fields -> context only
- finance fields -> external modifier only
