# Backend Signoff - 2026-04-12

This document records the backend state after the Vignan import path and related reporting
hardening were completed and verified.

## Important Scope Note

This document is a **backend milestone snapshot**, not the full current system story.

It mainly captures the state of:

- Vignan import readiness
- reporting hardening
- backend operational readiness at that point in time

After this signoff, the chatbot/coplaner system continued to evolve substantially through:

- `CB1` to `CB19`
- deterministic planner baseline `cb22`
- optional semantic layer `CB19`
- frontend contract freeze

So if you want the **current chatbot state**, do not rely on this file alone.

Read these docs as well:

- [CHATBOT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT.md)
- [CHATBOT_FULL_IMPLEMENTATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FULL_IMPLEMENTATION_GUIDE.md)
- [CHATBOT_FRONTEND_INTEGRATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FRONTEND_INTEGRATION_GUIDE.md)

### Why This Note Was Added

Without this note, a beginner could incorrectly assume:

- this file reflects the final chatbot architecture
- frontend should start from this snapshot alone
- chatbot readiness stopped at backend import/reporting work

That would be misleading.

This file is still useful, but only for the backend milestone it originally signed off.

## Scope Confirmed

The backend currently supports:

- role-aware authentication and protected routes
- student, counsellor/faculty, and admin backend flows
- scoring with champion/challenger predictions
- AI insights, recovery guidance, and operational intelligence
- student warning and faculty escalation workflows
- guardian escalation through email / SMS / WhatsApp when configured
- background job execution through a separate worker
- production-style Vignan Excel/CSV import
- imported-cohort reporting and coverage diagnostics

## Vignan Import Path Confirmed

Verified import contract:

- required sheets:
  - `Admissions`
  - `Academics`
  - `Attendance`
  - `Finance`
  - `Registration`
  - `LMS`
- optional sheet:
  - `SupportMapping`

Verified backend behavior:

- raw upload files are not stored
- dry run validates and counts rows without persistence
- real import stores rows and can trigger scoring
- imported support/contact fields are normalized
- imported sensitive context fields are stored with a fairness-review boundary note

## Verified Test Snapshot

On the clean verified run:

- imported students: `99`
- scored students: `24`
- unscored students: `75`
- dominant unscored reason: `missing_lms_data`

This was accepted as expected because the LMS sheet did not cover the full cohort.

## Reporting Confirmed

Imported-only analytics are available through:

- `GET /reports/import-coverage`
- `GET /institution/risk-overview?imported_only=true`
- `GET /reports/exports/outcome-distribution?imported_only=true`

Verified analytics dimensions:

- branch / department
- semester
- category
- region
- income
- final outcome (`Dropped`, `Studying`, `Graduated`)

## Feature Handling Decision

The backend now handles imported Vignan fields in three safe groups:

1. actively used in live scoring or live intelligence
2. used in operational context, reporting, and support routing
3. stored for later institutional analysis or future retraining

Sensitive imported profile context such as:

- `category`
- `region`
- `income`
- `parent_education`
- `occupation`

is intentionally not treated as newly approved model input without a later fairness review.

## Known Acceptable Limits

- students without LMS rows are imported but remain unscored
- incomplete `SupportMapping` rows lead to missing contact ownership fields, not import failure
- Vignan-specific retraining is not part of the current signed-off backend scope

## Signoff Decision

Backend status for current project scope:

- functionally ready
- operationally verified
- stable enough to begin frontend work on top of the current API contract

## How To Interpret This Today

Today, this statement should be read like this:

- the import/reporting backend was already stable enough at that time
- later chatbot phases built on top of that stable backend foundation
- the current frontend work should now use the dedicated chatbot frontend contract guide, not only this older signoff snapshot
