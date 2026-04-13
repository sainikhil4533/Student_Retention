# Frontend Role Flows

## How To Use This Document

Read this file when you want to understand the frontend from the point of view of a real user instead of from the point of view of routes or React files.

This document explains:

- what each role sees first
- why each role got different sections
- how the deeper pages work internally
- what edge cases the UI is prepared for
- how a beginner can think about these flows without getting lost in code

This is not a replacement for the full frontend guide.
It is the role-behavior companion to it.

Also read:

- [FRONTEND_MASTER_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_MASTER_GUIDE.md)
- [FRONTEND_PHASE_PLAN.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_PHASE_PLAN.md)
- [CHATBOT_FRONTEND_INTEGRATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FRONTEND_INTEGRATION_GUIDE.md)

## Why Role Flows Matter

In a real product, role-based UI is not just about hiding and showing menu items.

It is about answering different questions for different users:

- student: "What is my current situation and what should I do next?"
- counsellor: "Which student needs me now and what exactly should I do?"
- admin: "What is happening across the institution and where is the system weak?"

If we give the same workflow to everyone, the product becomes shallow.

So this document explains how we translated those three questions into three different UI flows.

## Student Flow

### Main purpose

The student flow should feel:

- supportive
- clear
- motivating
- still formal

It should not feel like:

- a punishment portal
- a raw analytics screen
- a childish game

### Entry flow

Student logs in through the student role login page.

After login, the student lands on:

- `/app/student/dashboard`

That first page is intentionally summary-first.
It answers:

- what is my current risk posture?
- do I have warnings?
- do I have critical triggers?
- what should I focus on now?

### Why the student also has a journey page

The dashboard alone is not enough for long-term engagement.

Students need a second page that tells a story:

- where they are
- what changed
- what happened in sequence
- what progress still matters

That is why the student module includes:

- dashboard
- reports
- journey

The journey page uses:

- `/student/me/overview`
- `/timeline/{student_id}`

This is one of the most important role decisions in the frontend.
It is where the "professional but attractive" requirement becomes real.

### Student edge cases

- no overview yet:
  the page shows an honest empty state
- no timeline yet:
  the page explains that events will appear when the backend has them
- low data after cohort cleanup:
  the UI does not fake a rich state if the backend has little to show

## Counsellor Flow

### Main purpose

The counsellor flow should feel:

- operational
- urgent where needed
- organized
- focused on case handling

It should not feel like:

- an admin analytics portal
- a game
- a student self-service view

### Entry flow

Counsellor logs in through the counsellor role login page.

After login, the counsellor lands on:

- `/app/counsellor/dashboard`

That page answers:

- how much active pressure exists?
- how many recovery windows are active?
- how many cases are critical or overdue?

It is a workload summary page.

### Why the counsellor needed a workbench page

A counsellor does not only need:

- counts
- bar charts
- queue totals

They need a place to work on an actual student case.

That is why the workbench page exists:

- `/app/counsellor/cases`

It uses:

- `/cases/active`
- `/operations/context/{student_id}`
- `/interventions/history/{student_id}`
- `POST /interventions/action`

This gives the counsellor a real operational sequence:

1. choose an active case
2. understand the case state
3. inspect the student's current context
4. inspect intervention history
5. record a new action

Without this page, the counsellor module would still be mostly observational.

### Counsellor edge cases

- no active cases:
  the page shows a clean no-workload state
- context unavailable for one selected student:
  the UI says so honestly instead of crashing
- no intervention history:
  the page still remains useful and explains what will appear later

## Admin Flow

### Main purpose

The admin flow should feel:

- executive
- strategic
- institutional
- operationally aware

It should not feel like:

- a student support page
- a counsellor case panel
- a playful gamified dashboard

### Entry flow

Admin logs in through the admin role login page.

After login, the admin lands on:

- `/app/admin/dashboard`

That page answers:

- how many students are in the system?
- how many are high risk?
- how large is the imported cohort?
- how much has already been scored?

This page is intentionally compact.

### Why admin got separate reports, imports, and operations pages

Admin has the broadest responsibility.
That means one page is not enough.

So we separated the admin experience into:

- dashboard
- reports
- imports
- operations

#### Reports

Used for denser institutional comparisons.

#### Imports

Used for cohort upload and dry-run validation.
This is separated on purpose because upload is an operational task, not a dashboard widget.

#### Operations

Used for:

- intervention effectiveness
- import coverage friction
- broader system workflow reading

This keeps the dashboard from becoming overloaded while still giving admin users the depth they need.

### Admin edge cases

- zero imported students after a cleanup:
  still valid, should not crash the page
- no scoring yet:
  import coverage still needs to render honestly
- sparse intervention history:
  the operations page should still render summary structure cleanly

## Chatbot Across Roles

The chatbot is shared across roles, but its meaning changes by role.

### Student

The chatbot is a guided helper.
It should feel supportive and scoped to the student's own context.

### Counsellor

The chatbot is a case-analysis helper.
It should help the counsellor reason about workload and student risk inside their scope.

### Admin

The chatbot is an institutional analysis helper.
It should help with trends, comparisons, import coverage, and high-level analysis.

That is why the chatbot is attached to the authenticated app shell instead of the public homepage.

## Manual Thinking Model For A Beginner

If you are trying to design role flows manually, use this order:

1. Ask what the user needs to decide first after login.
2. Put only that on the dashboard.
3. Move deeper analysis to a second page.
4. Move operational work to a dedicated workspace page.
5. Keep the chatbot available everywhere, but scoped by role.

This simple model is the reason the frontend now feels more like a real system and less like a collection of random pages.
