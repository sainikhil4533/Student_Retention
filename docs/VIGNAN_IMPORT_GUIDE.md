# Vignan Data Import Guide

## How To Read This Document

This file is the operational import guide for Vignan data.

Use it when you want to understand:

- what sheets and columns are required
- how import normalization works
- what the import endpoint expects
- which reporting endpoints are import-aware

Recommended supporting docs:

- [DOCS_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/DOCS_GUIDE.md)
- [BACKEND_SIGNOFF_2026-04-12.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/BACKEND_SIGNOFF_2026-04-12.md)
- [LIVE_SYSTEM_WORKFLOW.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/LIVE_SYSTEM_WORKFLOW.md)

Important note:

This guide focuses on import behavior.
It is not the full chatbot guide and not the full live workflow guide.

This guide describes the production-style import flow for the Vignan Excel/CSV datasets.
The system does not store the raw file. It validates, parses, and ingests rows into the
database, then triggers scoring and downstream alerts if enabled.

## Supported Formats

- `.xlsx` with the six sheets listed below 
- `.zip` containing CSV files named after each sheet (e.g., `Admissions.csv`)

## Required Sheets

- Admissions
- Academics
- Attendance
- Finance
- Registration
- LMS

## Optional Sheets

- SupportMapping

## Required Columns

Admissions:
- `registerno`, `Branch`, `Batch`, `Category`, `Region`, `ParentEdu`, `Occupation`, `Income`, `Gender`, `AgeBand`, `Attempts`

Academics:
- `registerno`, `Semester`, `CGPA`, `Backlogs`, `shortname`, `Marks`

Attendance:
- `registerno`, `Semester`, `Overall%`, `shortname`, `Subject%`, `ConsecutiveAbs`, `MissedvDays`, `Trend`

Finance:
- `registerno`, `Status`, `Due`, `DelayDays`, `Scholarship`, `Modifier`

Registration:
- `registerno`, `Semester`, `Registered`, `FinalStatus`

LMS:
- `registerno`, `event_date`, `id_site`, `sum_click`, `engagement_tag`, `resource_type`

SupportMapping:
- `registerno`, `student_email`, `disability_status`, `faculty_name`, `faculty_email`, `parent_name`, `parent_relationship`, `parent_email`, `parent_phone`, `preferred_guardian_channel`, `guardian_contact_enabled`, `counsellor_name`, `counsellor_email`

## API Endpoint

`POST /admin/imports/vignan`

Query parameters:
- `trigger_scoring=true` (default): run scoring after import to create AI insights, alerts, and notifications
- `dry_run=true`: validate and count rows without storing any data

## Import Behavior

- Admissions populate student profile fields and `profile_context`.
- Registration is stored in `profile_context.registration`.
- If `SupportMapping` is present, communication and ownership fields are populated from it.
- Academics + Attendance create a single ERP event per student.
- Finance creates a finance event per student.
- LMS creates one event per LMS row with extra fields stored in `context_fields`.
- Imported profile context also stores a fairness boundary note so institution-specific sensitive
  context fields are available for analytics/support, but are not treated as newly approved model
  inputs by default.

## Normalization Rules

The import path now normalizes common messy values automatically:

- `disability_status`
  - values like `Y`, `YES`, `TRUE` become `Y`
  - values like `0N`, `N`, blank, or anything else default safely to `N`
- `guardian_contact_enabled`
  - accepts `true/false`, `yes/no`, `1/0`
- `preferred_guardian_channel`
  - only keeps `email`, `sms`, or `whatsapp`
- `parent_relationship`
  - common values normalize to `Father`, `Mother`, `Parent`, or `Guardian`
- `Attendance.Trend`
  - categorical values are mapped as:
    - `Poor -> -1`
    - `Average -> 0`
    - `Good -> 1`

## Operational Usage Of Imported Features

The Vignan import does not treat every field the same way.

Used directly in live scoring or live intelligence:

- LMS clicks and activity windows
- attendance ratio and attendance trend
- weighted marks
- finance overdue amount, delay days, and modifier
- CGPA and backlog count in operational context
- LMS `engagement_tag` and `resource_type` in LMS summaries

Used for reporting, support context, or case ownership:

- `FinalStatus`
- `Branch`
- `Category`
- `Region`
- `Income`
- `Scholarship`
- faculty/counsellor/guardian mapping fields

Intentionally not added as new model inputs without review:

- `Category`
- `Region`
- `Income`
- `ParentEdu`
- `Occupation`

These remain stored for analytics, explanations, support routing, and future retraining work.

## Reporting Endpoints For Imported Cohorts

After a successful real import, the most useful verification endpoints are:

- `GET /reports/import-coverage`
  - shows how many imported students were scored and why some were skipped
- `GET /institution/risk-overview?imported_only=true`
  - shows imported-only institutional analytics
- `GET /reports/exports/outcome-distribution?imported_only=true`
  - exports imported-only outcome counts as CSV

The institution overview now includes:

- `department_buckets`
- `semester_buckets`
- `category_buckets`
- `region_buckets`
- `income_buckets`
- `outcome_distribution`

## Verified Test Outcome

On the verified clean import run used during backend signoff:

- imported students: `99`
- scored students: `24`
- unscored students: `75`
- main reason for unscored students: `missing_lms_data`

This is expected because the LMS sheet currently contains rows for only part of the imported cohort.

## Production Notes

- Raw upload files are not stored.
- If `dry_run=true`, no data is persisted.
- If `trigger_scoring=true`, the system will generate predictions and queue email/SMS/WhatsApp
  notifications as configured.

## Local Run Modes

Production-style deployment should keep the API and worker as separate processes.
For local demo/testing convenience, this project also includes:

- `python run_all.py`
- `start_system.bat`

These start both the FastAPI backend and the background worker together while preserving
the same logical separation used in production.

## Current Known Limits

- Not every imported student will be scored unless they have the required LMS + ERP inputs.
- If `SupportMapping` is incomplete for a row, the student can still be imported, but contact and
  ownership fields may remain null.
- A Vignan-specific retraining pipeline is not part of the current backend scope yet.
