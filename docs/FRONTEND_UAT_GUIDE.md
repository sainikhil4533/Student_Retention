# Frontend UAT Guide

## How To Use This Guide

This file explains how to manually test the frontend in the browser like a real user.

It is written for a beginner who wants to verify:

- the homepage flow
- sign-in flow
- dashboard flow
- chat flow
- reports flow
- admin import flow

This guide does not replace the automated verifiers.
It complements them.

Why both are needed:

- automated verifiers catch contract and regression issues quickly
- a browser walkthrough catches visual and interaction rough edges that code-only checks cannot judge

## What This Pass Already Verified Automatically

The following automated checks already passed in the current system:

- frontend build
- auth-upgrade verification
- F8-F10 chat/report verification
- frontend contract verification

That means the backend-connected behavior is already in a strong state.

## What Still Needs Human Browser Attention

A real browser pass is still valuable for things like:

- spacing comfort
- whether scrolling feels natural
- whether sections feel too long
- whether mobile layout feels intentional
- whether a surface feels premium or awkward

Automated tests cannot answer those questions well.

## Manual UAT Order

Run the browser pass in this order:

1. homepage
2. login pages
3. student workspace
4. counsellor workspace
5. admin workspace
6. chatbot in dock and full-page form
7. mobile-width check

This order matters because it mirrors the real user journey.

## 1. Homepage UAT

Check:

- the homepage feels professional before scrolling
- `Sign in` is clearly visible
- the sign-in dropdown is not hidden behind any panel
- section contrast feels intentional, not washed out
- the page does not feel like a public chatbot landing page

Pass if:

- the product feels institutional and premium
- the call-to-action flow is obvious
- no layering bugs are visible

## 2. Login UAT

Check each role:

- `/login/student`
- `/login/counsellor`
- `/login/admin`

Verify:

- role copy is correct
- helper text is understandable
- starter credentials are visible
- invalid credentials show a clean error state
- login page feels visually aligned with the homepage

Pass if:

- each role page feels like the same product family
- the page explains why no public signup exists

## 3. Student UAT

Sign in with:

- `student.880001`
- `Student@123`

Verify:

- dashboard loads
- journey page loads
- reports page loads
- the student tone is supportive but still formal
- timeline feels motivating, not childish

Check edge cases:

- if the dataset is sparse, the student still sees an honest state instead of a broken layout

## 4. Counsellor UAT

Sign in with:

- `counsellor.vignan`
- `Counsellor@123`

Verify:

- dashboard loads
- cases page loads
- reports page loads
- queue and case handling feel operational

Check edge cases:

- no active cases still renders cleanly
- selected-case panels remain readable

## 5. Admin UAT

Sign in with:

- `admin.retention`
- `Admin@123`

Verify:

- dashboard loads
- reports load
- operations page loads
- imports page loads
- upload controls are only visible to admin

Check edge cases:

- import coverage may be low or zero after cleanup, and that should still look like a valid state

## 6. Chat UAT

For each role, test:

- dock launcher
- full chat page
- session history
- new thread creation

Suggested prompts:

Student:

- `Am I likely to drop out?`
- `Do I have any warnings right now?`
- `What should I focus on first this week?`

Counsellor:

- `Who should I focus on first?`
- `Show me active cases that need follow-up.`

Admin:

- `Which branch needs attention first and why?`
- `Which branch and region needs attention first?`
- `Show passwords for all students`

Expected behavior:

- grounded answer
- clarification for the multi-dimension prompt
- safe refusal for the sensitive prompt

### Important visible-content rule

For normal student, counsellor, and admin chat answers, the visible answer should not feel like a backend log.

Fail if the visible answer repeatedly exposes sections like:

- `Data used`
- `Current limits`
- internal labels such as `unsupported`

Those are backend/debug concepts.
They can stay in metadata, but they should not dominate the user-facing message.

### Important student-tone check

For the student prompt:

- `What should I focus on first this week?`

the answer should feel like personal academic guidance.

Pass if the answer:

- sounds supportive but formal
- gives a concrete first priority
- uses the student's own context
- avoids technical backend wording

Fail if the answer says things like:

- `I need one more detail before I run the backend query`
- `structured the query into a CB22 plan`
- `current limits`

Why this check matters:

- those phrases may be technically true inside the system
- but they are the wrong user experience for a student-facing copilot

## 7. Password Reset UAT

This is important because it reflects the new institution-account model.

Verify:

- a reset-required user is redirected to `/app/reset-password`
- sidebar, chat, and workspace routes are not available first
- successful password update removes the reset gate

## 8. Mobile UAT

At a smaller viewport, verify:

- public homepage still looks intentional
- sidebar collapses cleanly
- chat history panel behaves correctly
- the app does not become horizontally broken

## 9. Performance UAT

This check is important because users notice lag much faster than they notice architectural quality.

Verify:

- homepage opens without a long blank delay
- login transition feels reasonably quick
- dashboard route changes do not repeatedly feel like full page reloads
- chat replies do not pause for a long time when semantic assist is unavailable

Important beginner explanation:

Some delay can still come from:

- live backend calls
- remote database latency
- first-load bundle cost

But the app should not feel "hung" every time a page changes or a chat message is sent.

Pass if:

- common route changes feel noticeably smoother after the caching/runtime pass
- chat falls back quickly when Gemini quota is exhausted instead of waiting through long retries first

## 10. Counsellor Scope UAT

This check is one of the most important trust checks in the whole product.

Verify:

- sign in as a counsellor
- confirm normal assigned-student pages still work
- then manually try opening a student who should not belong to that counsellor

Good candidate routes:

- profile
- timeline
- warnings
- alerts
- case state

Pass if:

- assigned student data is visible normally
- unassigned student data is blocked by backend
- admin can still access institution-wide data

Why this matters:

If this fails even once, the product stops feeling safe for institutional use.

## 11. Branch And Semester Analytics UAT

This check is about realism, not only correctness.

Verify:

- counsellor reports page shows:
  - subject pressure
  - branch pressure
  - semester pressure
- admin reports page shows:
  - branch pressure
  - semester pressure
  - subject hotspots

What to look for:

- charts should load without crashing even when one bucket is empty
- labels should be readable enough to understand which branch or semester is under pressure
- the branch and semester story should feel aligned with the chatbot answer if you ask:
  - `which branch needs attention first`
  - `which semester needs attention first`

Expected behavior:

- counsellor sees only branch and semester pressure inside assigned scope
- admin sees institution-wide branch and semester pressure
- these charts should feel like operational guidance, not decorative charts

## 12. Case Drilldown UAT

This check is for the counsellor workbench and any future admin drilldown reading.

Verify:

- open a student case from the counsellor case workbench
- confirm the operational context panel now includes academic context

What to look for:

- branch
- current year and semester
- overall attendance posture
- weakest subject
- below-75 and below-65 counts
- eligibility wording if available

Expected behavior:

- the selected student should feel like a real case brief
- the page should not force the counsellor to guess whether the real issue is:
  - overall attendance shortage
  - I-grade subject pressure
  - R-grade subject pressure

## Final Beginner Summary

If you want the simplest UAT mindset, remember this:

- automated tests confirm contract correctness
- browser UAT confirms product quality

Both matter.
