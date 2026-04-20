# Generalized Academic Data Template Guide

## How To Use This Guide

This guide explains the generalized academic CSV contract that we used to create a temporary sample pack during design.

Important note:

- the temporary in-repo sample pack was removed after handoff so the repository does not stay tied to one institution's example data
- this guide remains the source of truth for the schema, purpose, and reasoning behind that pack

It is written for a beginner who wants to understand:

- why the old Vignan workbook was not rich enough for a real production-grade chatbot
- what each CSV in the new pack is for
- which files are generic for any institution
- which values are only example rows that you can replace later
- how these files connect to dashboards, reports, timeline logic, and chatbot behavior

This guide is not only about import structure.
It is also about system behavior.

The deeper reason we created this pack is:

- the chatbot can only answer well when the underlying academic data is realistic enough

If the data only contains one subject row and one semester row per student, then even a strong chatbot will keep sounding weak, because the underlying academic story is weak.

Implementation note:

- this file explains the generalized data contract itself
- the backend implementation that now consumes that contract is explained in [GENERALIZED_INSTITUTION_IMPORT_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/GENERALIZED_INSTITUTION_IMPORT_GUIDE.md)
- that separation is intentional:
  - this guide teaches what the data should look like
  - the other guide teaches what the backend now does with that data

## What Was Wrong With The Older Shape

The original workbook already had useful sheets:

- `Admissions`
- `Registration`
- `Attendance`
- `Academics`
- `Finance`
- `LMS`
- `SupportMapping`

But the real gap was structural:

- one student did not have a rich semester history
- one student did not have all subjects for a semester
- attendance did not directly express the academic consequence of shortage
- the system did not know the difference between:
  - safe attendance
  - condonation (`I_GRADE`)
  - repeat-subject summer risk (`R_GRADE`)
- final-year internship/project-review scenarios were not represented explicitly

That is why the chatbot could answer only shallow versions of questions like:

- `what is my attendance right now`
- `which subject is causing the problem`
- `what should I focus on this week`

## Design Goal Of The New Pack

The pack is designed to be:

- generalized for any institution
- but still excellent when used with Vignan-style data

That means we do **not** hardcode one university into the system logic.
Instead, we store the institution-specific structure in the uploaded data.

So the system becomes:

- one generalized academic engine
- plus institution-specific uploaded curriculum and policy data

## Files In The Contract

The generalized contract uses these CSV files:

- `Admissions.csv`
- `Registration.csv`
- `StudentAcademicProgress.csv`
- `AttendancePolicy.csv`
- `SubjectCatalog.csv`
- `SemesterProgress.csv`
- `Attendance.csv`
- `Academics.csv`
- `Finance.csv`
- `LMS.csv`
- `SupportMapping.csv`

## Why Each File Exists

### 1. Admissions.csv

Purpose:

- stores stable background and demographic profile context
- drives student profile cards, branch grouping, region/category reporting, and certain risk explanations

Important idea:

- this file should stay mostly institution-agnostic
- another university can still use the same structure with different branch names and admission patterns

### 2. Registration.csv

Purpose:

- identifies where the student is currently in the program
- records current semester, current year, and semester mode

Why `SemesterMode` matters:

- your university has a real final-year scenario where semester 8 may be:
  - internship
  - project review
  - or normal coursework

If the system does not know this, it may speak incorrectly about classroom attendance for students who are actually in internship mode.

### 3. StudentAcademicProgress.csv

Purpose:

- stores a cleaner one-row summary of the student's current academic state
- useful for dashboards and chat grounding

Think of this as:

- the "where is this student now?" table

It is helpful because some user-facing flows should not recompute that from many raw sheets every time.

### 4. AttendancePolicy.csv

Purpose:

- stores institution policy instead of hardcoding attendance rules into code

This is one of the most important new files.

Why:

- your university requires both overall 75 percent and subject-wise 75 percent
- subject below 65 means `R_GRADE`
- subject 65 to below 75 means `I_GRADE`

That is a real policy layer.
If we encode it only in backend code, the system becomes harder to generalize.

If we store it as uploaded data:

- Vignan works correctly
- another institution can later upload different thresholds

### 5. SubjectCatalog.csv

Purpose:

- defines which subjects belong to which branch, year, and semester

This file is what makes the system feel real.

Without it:

- semester 3 and semester 5 can look artificially similar
- the chatbot cannot answer subject-aware attendance questions well
- the system cannot know which subjects changed from one semester to another

In this pack, the example rows use the CSE curriculum you provided.
That does **not** mean the system is being hardcoded to CSE forever.
It means we are using one real curriculum as the first uploaded catalog example.

### 6. SemesterProgress.csv

Purpose:

- stores semester-level derived summary per student

This file is useful because many queries care about semester-level state:

- overall attendance shortage
- count of subjects below 75
- count of subjects below 65
- whether `I_GRADE` or `R_GRADE` risk exists

This can be:

- uploaded directly
- or derived later by backend logic from `Attendance.csv`

For a first generalized system, having the sheet is useful because it makes the intent very clear.

### 7. Attendance.csv

Purpose:

- this is now the most important operational file
- one row represents one student, one subject, one semester

This is a major redesign from the older shape.

Why:

- real attendance risk is subject-specific
- semester-wide overall attendance is not enough
- the university rule itself is subject-sensitive

This file now carries not only attendance percentages, but also academic consequence:

- `SAFE`
- `I_GRADE`
- `R_GRADE`

This is what allows the chatbot to answer:

- `which subject is hurting me most`
- `do I have I grade risk`
- `do I need to repeat a subject`

### 8. Academics.csv

Purpose:

- keeps marks, grades, and academic outcomes aligned with attendance consequence

This is important because a subject with `R_GRADE` should not look like a normal passed subject in another part of the system.

### 9. Finance.csv

Purpose:

- keeps fee and payment pressure visible
- used for operational and risk context

This file is less central than attendance for your new policy-driven model, but still useful.

### 10. LMS.csv

Purpose:

- stores learning-platform engagement mapped to subjects and semesters

This becomes much more valuable once it includes `SubjectCode` and `SubjectName`.

Then the system can answer combined questions like:

- `your attendance and LMS engagement are both weak in Compiler Design`

### 11. SupportMapping.csv

Purpose:

- stores support ownership and contact information
- required for realistic counsellor/faculty/admin workflows

This file helps the system behave like a closed institution platform rather than a public app.

What is stored here now:

- student contact data:
  - `student_email`
  - `student_phone`
- faculty contact data:
  - `faculty_name`
  - `faculty_email`
  - `faculty_phone`
- counsellor contact data:
  - `counsellor_name`
  - `counsellor_email`
  - `counsellor_phone`
- guardian data:
  - `parent_name`
  - `parent_relationship`
  - `parent_email`
  - `parent_phone`
  - `preferred_guardian_channel`
  - `guardian_contact_enabled`

Why we did not collapse all of this into one generic contact block:

- in a real institution, student, faculty, counsellor, and guardian are different roles
- they do not always share the same responsibilities
- the chatbot and workflows may later need to answer different questions such as:
  - `who is my counsellor`
  - `who is my faculty mentor`
  - `which guardian contact channel is enabled`
  - `which students are assigned to counsellor X`

Why faculty and counsellor are separate:

- faculty is usually closer to classroom, subject, and academic performance
- counsellor is usually closer to follow-up, risk handling, and retention support

Some universities may combine those roles in practice, but the generalized system should not assume that by default.
It is safer to keep both roles separate in the data model and let a specific institution map them to the same person later if needed.

## What Is Still Example Data vs Real Data

Important beginner clarification:

The rows in this pack are **example rows**.

They are realistic enough to model the system properly, but they are not meant to be the only future institutional data.

So you can:

- copy them
- expand them
- replace them with real institutional rows

What matters most is the **shape**, not only the sample values.

## How These Files Connect Together

The intended relationship is:

1. `Admissions.csv`
   - who the student is

2. `Registration.csv` and `StudentAcademicProgress.csv`
   - where the student currently is academically

3. `SubjectCatalog.csv`
   - what subjects should exist for that branch and semester

4. `AttendancePolicy.csv`
   - what thresholds and consequences apply

5. `Attendance.csv`
   - what the student's subject-wise and overall attendance actually is

6. `SemesterProgress.csv`
   - a summary view of semester-level attendance risk

7. `Academics.csv`
   - the marks/grade side of the same academic story

8. `LMS.csv`
   - learning engagement context

9. `Finance.csv`
   - payment pressure context

10. `SupportMapping.csv`
   - ownership and communication context

## Why We Included Vignan-Style CSE Subjects Here

You explicitly provided the CSE semester curriculum, and that was useful.

We used it here because:

- it gives us a real subject catalog example
- it makes semester progression believable
- it improves the eventual chatbot realism a lot

But we are not making the platform "CSE-only" or "Vignan-only."

The correct interpretation is:

- the **system remains generalized**
- the **uploaded subject catalog makes it institution-specific at runtime**

That is the architecture we want.

## How This Helps The Chatbot Later

Once the generalized backend is upgraded against this data model, the chatbot can answer much better questions such as:

Student:

- `which data do you have of me`
- `what is my overall attendance`
- `which subjects are below 75`
- `do I have I grade risk`
- `do I have R grade risk`
- `what should I focus on this week`

Counsellor:

- `which assigned students have R grade risk`
- `which students are below overall threshold`
- `which subject is creating the most trouble in my cohort`

Admin:

- `branch-wise I grade count`
- `branch-wise R grade count`
- `subject shortage hotspots`
- `semester-wise attendance compliance`

## What You Should Do Next With This Pack

You said:

- once you copy these, the temporary template files can be deleted
- then implementation of the generalized system can continue

That is a good workflow.

So the intended next order is:

1. copy these CSV files
2. edit/expand them as needed
3. confirm they are the target institutional input format
4. then we can delete the temporary template folder
5. then start implementing the generalized academic/attendance engine

## Important Practical Note

This pack is still a transition pack.

It does not automatically mean the current import pipeline fully understands all of these files yet.

That is the next implementation step.

So think of this pack as:

- the agreed target data contract

not:

- the final import implementation

## Summary

This pack was created because the current Vignan workbook was not rich enough for:

- real subject-wise attendance reasoning
- realistic semester progression
- proper `SAFE / I_GRADE / R_GRADE` academic consequence handling
- believable student/counsellor/admin chatbot answers

The new pack fixes that by separating:

- generalized academic engine concepts
- institution-specific uploaded curriculum and policy data

That is the right foundation for making the system work well for Vignan now, while still staying extensible for any institution later.
