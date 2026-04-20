# Generalized Institution Import Guide

## Why This Document Exists

This guide explains the new generalized import foundation that replaces the earlier idea of a single university-shaped import path.

It is written for a beginner who wants to understand:

- what changed in the backend
- why the old import shape was not enough
- what happens when an admin uploads an institution dataset
- which tables are now filled behind the scenes
- how the system stays generalized while still working well for a university like Vignan

This is not only an endpoint note.
It is a system-behavior explanation.

## The Real Problem We Fixed

Earlier, the system had a strong operational workflow, but the import layer was still too narrow.

The old approach mostly compressed imported data into:

- one `student profile`
- LMS events
- one ERP-style summary event
- one finance event

That was enough for a first predictive pipeline, but not enough for a real academic assistant.

Why not:

- curriculum was not first-class
- attendance policy was not first-class
- semester progress was not first-class
- subject-wise academic consequence was not first-class

So even if the chatbot tried to sound intelligent, the backend was still standing on a shallow academic model.

## What We Added In This Foundation Pass

We added a generalized academic foundation layer in the backend.

New first-class database tables:

- `institution_attendance_policies`
- `subject_catalog_entries`
- `student_academic_progress_records`
- `student_semester_progress_records`
- `student_subject_attendance_records`
- `student_academic_records`

These tables sit alongside the older operational tables such as:

- `student_profiles`
- `lms_events`
- `erp_events`
- `finance_events`

That means the system now has two layers:

1. operational event layer
2. richer academic structure layer

This is the correct direction for a real institution system.

## New Import Endpoint

The new generalized route is:

- `POST /admin/imports/institution`

This route accepts:

- `.xlsx`
- or `.zip` containing CSV sheets

The route is designed for a generalized institution contract, not for one university name.

## Required Sheets In The New Contract

The generalized route currently requires:

- `Admissions`
- `Registration`
- `Attendance`
- `AttendancePolicy`
- `SubjectCatalog`

Optional sheets:

- `SupportMapping`
- `StudentAcademicProgress`
- `SemesterProgress`
- `Academics`
- `Finance`
- `LMS`

Why this is important:

- core academic structure must exist
- richer operational data can be layered on top

That is more realistic than forcing every institution to start with the exact same single workbook shape.

## What Happens During Import

When an admin uploads a file to `POST /admin/imports/institution`, the backend now does the following:

### Step 1. Read the workbook or zip

The route reads:

- Excel sheet names
- or CSV filenames inside a zip

Then it converts them into in-memory row dictionaries.

### Step 2. Validate the generalized contract

The backend checks:

- required sheets exist
- required columns exist
- attendance policy is present
- subject catalog is present

This prevents a shallow or ambiguous import from being treated as valid.

### Step 3. Detect the institution name

The system looks for `InstitutionName` in:

- `AttendancePolicy`
- `SubjectCatalog`
- `Admissions`

If the file does not provide a clean value, the backend falls back to:

- `Imported Institution`

This is important because the engine is no longer supposed to assume one fixed institution name.

### Step 4. Persist institution-wide policy

The backend writes rows into:

- `institution_attendance_policies`

This is the rule engine input.

Example of what gets stored:

- overall minimum percent
- subject minimum percent
- R-grade threshold
- I-grade band
- condonation rules
- end-sem eligibility rules

This is how we avoid hardcoding university rules deep inside chatbot logic.

### Step 5. Persist curriculum

The backend writes subject catalog rows into:

- `subject_catalog_entries`

This gives the system:

- branch-aware subjects
- semester-aware subjects
- subject code and name mapping
- elective flags
- subject type

Now the system can understand that semester 3 and semester 7 are academically different, which is essential for realistic dashboards and chatbot answers.

### Step 6. Upsert student profile

For each student registration number, the backend still upserts:

- `student_profiles`

This keeps older parts of the system working.

But now the profile payload also carries richer context such as:

- institution name
- branch
- batch
- regulation
- semester
- current year
- semester mode
- support contact phones inside `profile_context`

This matters because not every detail belongs as a top-level column.

### Step 7. Persist academic progress

The backend now writes a one-row academic current-state record into:

- `student_academic_progress_records`

This answers the question:

- where is this student now in the program?

It stores things like:

- current year
- current semester
- current academic status
- semester mode
- expected graduation year
- backlog summary

### Step 8. Persist subject-wise attendance

This is one of the biggest changes.

The backend now writes subject-level attendance rows into:

- `student_subject_attendance_records`

Each row can contain:

- subject code
- subject name
- semester
- year
- overall attendance percent
- subject attendance percent
- required percent
- subject status
- consequence

This is the real foundation for answers such as:

- what is my weakest subject
- do I have I-grade risk
- do I have R-grade risk

### Step 9. Apply attendance policy

The backend now evaluates attendance against the uploaded institution policy.

Current rule engine behavior:

- overall attendance compared against `overall_min_percent`
- subject attendance compared against `subject_min_percent`
- subject below `r_grade_below_percent` becomes `R_GRADE`
- subject within the I-grade band becomes `I_GRADE`

From that, the backend derives:

- `overall_status`
- `subject_status`
- `grade_consequence`
- `condonation_required`
- `summer_repeat_required`
- `internals_repeat_required`
- `end_sem_eligible`

This is the most important “realism” upgrade in this pass.

### Step 10. Build semester progress

If the file contains `SemesterProgress`, the backend uses it.

If not, the backend derives semester progress from the imported attendance rows.

That data is stored in:

- `student_semester_progress_records`

This is important because many user-facing questions are semester-level, not just subject-level.

Examples:

- how many subjects are below threshold in semester 4
- does this student have semester-wide eligibility risk
- is this student in project review mode

### Step 11. Persist academic marks

If `Academics` is present, the backend writes:

- `student_academic_records`

This allows attendance consequence and academic marks to live side by side instead of pretending they are unrelated.

### Step 12. Preserve operational compatibility

The backend still creates:

- LMS events
- finance events
- ERP-style summary event

Why we kept this:

- existing risk scoring and operational flows still depend on those tables
- this foundation pass should improve the system without breaking the already-built pipeline

So this pass is intentionally additive, not destructive.

## Why We Kept The Old `/admin/imports/vignan` Route

We kept the old route for compatibility.

Why:

- existing UI and older docs were built around it
- older test scripts may still call it
- removing it immediately would create breakage before the generalized transition is complete

So the system currently has:

- old legacy route for compatibility
- new generalized route for the future-proof path

This is a deliberate bridge strategy.

## Why This Makes The Chatbot Better Later

The chatbot still needs a deeper role-aware pass after this.

But this foundation solves the biggest underlying problem:

- the backend now has richer academic truth to reason over

That means the later chatbot pass can answer from:

- actual subject-wise attendance state
- actual policy consequences
- actual semester-level progress
- actual curriculum mapping

instead of trying to sound smart on top of a shallow import model.

## What This Pass Does Not Claim Yet

This pass does not mean:

- every chatbot question is solved already
- dashboards are fully rebuilt around the new tables already
- every old doc is fully generalized already

This pass specifically delivers:

- generalized import foundation
- policy engine foundation
- curriculum foundation
- richer persistence model

That is the correct first serious step.

## Beginner Summary

If you want the shortest possible understanding:

- old system imported students into a narrow event model
- new system imports students into a richer academic structure
- attendance policy and curriculum are now first-class backend concepts
- the system is becoming institution-agnostic instead of staying one-university-shaped
- this gives the next chatbot and dashboard passes a much stronger base
