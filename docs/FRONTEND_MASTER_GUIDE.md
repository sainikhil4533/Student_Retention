# Frontend Master Guide

## How To Use This Guide As A Beginner

This is the main beginner-friendly explanation of the new frontend.

Use it when you want to understand:

- what we built in the frontend
- why we built it this way
- how the public site and authenticated app are separated
- how the frontend connects to the backend
- how role-based dashboards work
- how the chatbot fits into the UI

If you are new to product/frontend work, this is the first frontend file you should read.

Then continue with:

- [FRONTEND_PHASE_PLAN.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_PHASE_PLAN.md)
- [FRONTEND_ROLE_FLOWS.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_ROLE_FLOWS.md)
- [FRONTEND_DESIGN_SYSTEM.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_DESIGN_SYSTEM.md)
- [FRONTEND_UAT_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_UAT_GUIDE.md)

## 1. What This Frontend Is Trying To Achieve

The frontend is not just trying to “show API data.”

It is trying to create a real product experience for three kinds of users:

- student
- counsellor
- admin

And it must do that while:

- keeping institutional seriousness
- staying attractive
- staying mobile-friendly
- preserving role boundaries
- keeping the chatbot useful and familiar

So the frontend has two jobs at once:

1. Make the system usable.
2. Make the system feel like a real institution product.

## 2. Public Experience Vs Authenticated Experience

One of the most important product decisions was to separate:

- the public homepage
- the real application

### Public Homepage

The public homepage is for:

- trust
- explanation
- first impression
- entry into sign-in

The final homepage direction is intentionally:

- shorter
- cleaner
- more institutional
- less like a long startup landing page

Why:

- this product is not selling a public AI chatbot
- it is introducing a controlled institutional system
- too much scrolling, too many decorative sections, or too much faux analytics on the public page makes the product feel less serious instead of more professional

It is not for:

- live student data
- live chatbot use
- public signup

Why:

This is not a public consumer chatbot.
It is an institution-specific system.

### Authenticated App

After login, the user enters the real application.

That application is:

- role-aware
- data-aware
- chatbot-enabled
- operational

This split is what makes the system feel like a real-world platform instead of a demo page with a chat box.

## 3. Frontend Architecture

The new frontend lives under:

- [frontend](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/frontend)

It is built with:

- React
- TypeScript
- Vite
- Tailwind CSS
- React Router
- React Query
- Recharts

### Why This Stack Was Chosen

React:
- good for structured product UIs

TypeScript:
- very important because the backend returns role-aware structured payloads

Vite:
- fast local development and clean build setup

Tailwind:
- fast styling with consistent spacing and responsive control

React Router:
- needed for separate public and authenticated routes

React Query:
- good for dashboard data, session lists, and chatbot session refreshes

Recharts:
- enough for informative production-style charts without overcomplicating the stack

## 4. File Ownership

This is one of the most important beginner concepts.

The frontend was not written as one giant file because that becomes impossible to maintain.

### Core files

- [frontend/src/App.tsx](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/frontend/src/App.tsx)
  - top-level routes
  - route guards
  - public vs authenticated split

- [frontend/src/lib/auth.tsx](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/frontend/src/lib/auth.tsx)
  - login state
  - token persistence
  - logout handling

- [frontend/src/lib/api.ts](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/frontend/src/lib/api.ts)
  - all fetch calls go through here
  - this keeps API handling consistent

- [frontend/src/components/layout.tsx](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/frontend/src/components/layout.tsx)
  - public header layout
  - authenticated app shell
  - role navigation

- [frontend/src/components/chatbot.tsx](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/frontend/src/components/chatbot.tsx)
  - chatbot launcher
  - session history
  - session loading
  - send-message flow

### Role pages

- [frontend/src/pages/student.tsx](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/frontend/src/pages/student.tsx)
- [frontend/src/pages/counsellor.tsx](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/frontend/src/pages/counsellor.tsx)
- [frontend/src/pages/admin.tsx](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/frontend/src/pages/admin.tsx)

These files are where role-specific dashboards and reports live.

## 5. How Login Works

At this stage, the frontend uses the existing backend auth route:

- `POST /auth/login`

The frontend sends:

- username
- password

The backend returns:

- access token
- role
- student id if relevant
- display name

The frontend stores that in local storage through [auth.tsx](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/frontend/src/lib/auth.tsx).

### Auth Upgrade Correction

The older wording in this document described login as a development-safe version.
That is no longer the full truth.

The current system now uses institution-style accounts stored in the database.
That means the frontend already works with:

- institution-created starter users
- username/password login tied to stored account records
- password-reset-required routing for temporary passwords
- a clean extension path toward OTP or SSO later

So when you read older notes in this guide that sound future-looking, treat them as historical context, not the current production direction.

### Important Beginner Note

This current login flow is still the development-safe version.

It is already shaped in a way that can later support:

- institution-created users
- first-login password reset
- future OTP or SSO

That means the UI is not painted into a corner.

## 6. How The Chatbot Fits Into The Frontend

The chatbot is available only after login.

That was an intentional product decision.

### Why it is inside the app

Because the chatbot is:

- role-scoped
- grounded to private institutional data
- session-aware

So exposing it on the public homepage would create the wrong expectation.

### How it works

The shared chatbot panel:

- loads existing sessions from `/copilot/sessions`
- creates a new session with `POST /copilot/sessions`
- loads a full session with `GET /copilot/sessions/{id}`
- sends a message with `POST /copilot/sessions/{id}/messages`

This gives the “ChatGPT-like history” feeling while still staying grounded to backend sessions.

## 7. Why The Student Timeline Needed One Backend Fix

While building the frontend, we noticed a product gap:

- the timeline route existed
- but it only allowed counsellor/admin access

## 7A. Student Frontend Is Now Starting To Use The Generalized Academic Foundation

This is one of the most important recent changes.

Earlier, the student UI was mostly driven by:

- latest prediction
- warning history
- profile context

That was useful, but it was not enough to make the product feel like a real academic system.

The student pages now also consume a richer backend block:

- `academic_progress`

That block includes:

- current year
- current semester
- semester mode
- overall attendance summary
- current subject-wise attendance
- weakest subject
- semester progression history
- I-grade and R-grade posture

### Why this change matters

Without this block, the student dashboard can only say:

- you are high risk
- you have warnings
- here are generic recommendations

With the new block, it can start saying:

- this is your current attendance posture
- this is your weakest subject
- this semester has shortage risk
- this semester mode is internship, project review, or regular coursework

That is much closer to a real institution product.

### Important beginner note

This was intentionally done as a student-first pass.

Why:

- the student experience was where the chatbot weakness was most visible
- student questions are highly dependent on attendance, subject status, and semester posture
- once this pattern is strong for students, we can extend the same generalized academic layer to counsellor and admin views

That meant the student could not see their own timeline in the new dashboard.

So we fixed the backend route to allow:

- counsellor/admin/system
- or the same student for their own record

This is a good example of real frontend work:

- frontend often exposes small backend access assumptions that were easy to miss before

## 8. Why Reports Got Their Own Routes

We intentionally did not put every chart on the first dashboard screen.

Instead:

- dashboard = quick orientation
- reports = deeper analysis

Why this matters:

- the first screen should help users understand what to do next
- the reports screen should help users analyze patterns

That separation is one of the main reasons the product feels more professional.

## 9. How The Three Roles Differ Visually

### Student

Student side uses:

- more motivational language
- a progress-oriented timeline
- more emotionally supportive layout

### Counsellor

Counsellor side uses:

- workload and urgency framing
- queue-first thinking
- more operational structure

### Admin

Admin side uses:

- executive summary cards
- institutional charts
- admin-only import control

This difference is important because a real-world product should not feel identical for every role.

## 10. What F5-F7 Added Beyond The First Shell

The first frontend block gave us:

- homepage
- login
- protected app shell
- dashboards
- chatbot dock

That was necessary, but it was still not enough to make the product feel complete for each role.

The deeper role pass was added because real products are not judged only by whether a route exists.
They are judged by whether each role feels like it has a serious workspace.

### Student journey page

The student should not only see:

- a risk card
- a warning count
- a few summary metrics

They should also see:

- who they are in the system
- how their journey has unfolded over time
- what steps the system thinks matter next

That is why the student module now includes:

- dashboard
- reports
- journey

The journey route is where the "professional but motivating" requirement becomes real.
It is still formal, but it gives the student a sense of movement instead of only a warning label.

### Counsellor workbench

If we only show counsellors:

- queue counts
- charts
- high-risk totals

then we still have an observer dashboard, not a working tool.

So the workbench route was added to let a counsellor:

- open active cases
- inspect one student at a time
- read operational context
- see intervention history
- log a new intervention action without leaving the page

This is one of the most important frontend improvements so far, because it turns the counsellor module into a true workflow surface.

### Admin operations page

The admin dashboard should stay executive-first.

That means it should not become overloaded with:

- import friction details
- intervention effectiveness diagnostics
- operational text blocks

So the admin operations page was added as a second layer.

This lets admin users keep:

- a clean dashboard for orientation

and also have:

- a deeper page for operational reading and process health

That separation is what keeps the product feeling mature instead of messy.

## 11. How Data Flows Through The Deeper Role Pages

The frontend does not invent business logic for these pages.
It asks the backend for role-safe, grounded data and then renders it clearly.

### Student journey flow

The page loads:

- `GET /student/me/overview`
- `GET /timeline/{student_id}`

The frontend combines those two responses to show:

- the student's identity snapshot
- the current prediction posture
- the formal timeline story

Why this split exists:

- `/student/me/overview` is the student summary source
- `/timeline/{student_id}` is the event history source

Keeping those responsibilities separate makes both backend and frontend easier to reason about.

### Counsellor workbench flow

The page loads:

- `GET /cases/active`
- `GET /operations/context/{student_id}`
- `GET /interventions/history/{student_id}`

And when the counsellor records a new action, it uses:

- `POST /interventions/action`

This is the operational chain:

1. load candidate cases
2. pick one student
3. load that student's deeper context
4. load that student's intervention trail
5. record new action
6. refresh the visible case and history state

That sequence is exactly how a real workbench should behave.

### Admin operations flow

The page loads:

- `GET /reports/operations-overview`
- `GET /reports/import-coverage`

The first endpoint answers:

- what is happening institution-wide operationally

The second endpoint answers:

- how healthy the imported cohort coverage is

Putting both on one page gives admin users a stronger operational picture without forcing them to mentally join unrelated dashboard widgets.

## 12. Edge Cases Already Considered In This Frontend Block

Even this early frontend block had some important edge cases:

- missing login credentials
- invalid login response
- protected route access without auth
- wrong role landing on a different role’s page
- empty chat history
- no imported students after cleanup
- import dry-run workflow
- no student overview available

F5-F7 added more edge-case thinking too:

- no timeline events yet for a student
- no active cases yet for a counsellor
- no operational context yet for a selected student
- no intervention history yet for a selected student
- zero imported students after a cleanup or reset
- admin operations page still needing to render usefully with sparse data

This matters because real products feel polished mostly through edge-case handling, not only through the happy path.

## 13. How To Rebuild This Manually

If you wanted to do this yourself manually, the right order is:

1. Create the frontend workspace.
2. Add routing.
3. Add auth state.
4. Create public layout.
5. Create app shell.
6. Add protected role routes.
7. Connect the first real endpoints.
8. Add the chatbot layer.
9. Add charts.
10. Add mobile polishing.

That order prevents most frontend chaos.

If you also want to rebuild the deeper role pages manually, the safest continuation order is:

1. add the student journey first because it is read-mostly and safe
2. add the counsellor workbench next because it introduces operational mutation
3. add admin operations after that because it is read-heavy but analytically denser
4. only then do broader polish and UAT passes

That order matters because it adds complexity in a controlled way.

## 14. What F8-F10 Completed

The final planned frontend block was about maturity, not about adding another random page.

It answered three questions:

### How should chat feel in a real product?

Answer:

- quick access through the dock
- deeper work through a full chat page
- role-based starter prompts
- clear in-stream states for clarification and refusal

This matters because users do not all use chat the same way.
Some ask one quick question.
Others need a longer analytical conversation.

### How should reports behave when data is sparse or when users need exports?

Answer:

- charts now have honest empty states
- chart legends now keep values readable
- admin reporting routes now expose practical export buttons

That is a production feature, not just visual polish.

### How should the app behave on smaller screens?

Answer:

- mobile navigation now has an intentional overlay behavior
- the chat history panel behaves like a proper mobile workspace panel
- the user can also use a full chat page instead of only a drawer

These are the kinds of details that separate a desktop-first demo from a more complete product.

## 15. What This Frontend Still Does Not Claim

The frontend is now functionally complete against the planned F1-F10 roadmap.

That still does not mean:

- every future animation decision is final
- every future chart is the best possible chart forever
- every future UX tweak has been exhausted

It means the planned production-grade foundation is now in place.

The product now has:

- real public/private separation
- role-specific application surfaces
- integrated chatbot UX
- deeper reporting surfaces
- mobile-aware interaction patterns

## 16. What Changed In The Auth Upgrade And Why

This auth upgrade matters because it changes the product from "demo login with nice UI" into "real institution-style access with a controlled lifecycle."

### What changed

Before this pass, the frontend login mostly behaved like a polished role entry into the app.

Now the real flow is:

1. the backend reads a stored account record
2. the backend returns role, username, display name, auth provider, and password-reset-required state
3. the frontend stores that auth state
4. route guards decide whether the user can go directly to the dashboard or must first complete password reset

### Why this was necessary

We had already agreed on the product principle:

- no public signup
- institution provisions the user
- the user receives an initial credential
- the user later changes that temporary password

Without implementing this, the frontend would have looked more real than the system actually was.

### Hidden working that a beginner usually cannot see

When login succeeds, the frontend is not only storing an access token.
It is also storing:

- `username`
- `role`
- `studentId`
- `displayName`
- `authProvider`
- `passwordResetRequired`

That hidden state is what makes the rest of the app behave correctly.

For example:

- if a user is authenticated but still has a temporary password, the app should not let that user move around dashboards, reports, or chat first
- it should send the user to `/app/reset-password`

That is why auth state is not a cosmetic feature. It controls route safety and product realism.

### What is still future work

This does not mean the auth story is finished forever.
It still leaves room for:

- OTP login
- SSO
- richer admin-managed account lifecycle tooling

But the important point is that the system is already on the real-world institution path now, not just pointing toward it.

## 17. What Changed In The Visual Polish Pass And Why

This polish pass was not about adding new routes.
It was about making the product feel closer to a real institution-grade system when a user actually looks at it.

### What was wrong before

Even though the frontend was already functionally strong, there were still some visual weaknesses:

- too many white surfaces in sequence
- not enough dark/light rhythm on the homepage
- the authenticated shell felt correct but not premium enough
- the chatbot worked well, but still looked more like a utility panel than a polished product surface

### What changed

We improved three main areas:

1. Homepage contrast and section rhythm
- stronger dark/light alternation
- better separation between trust sections and CTA sections
- more structured messaging about why the product is closed-campus and role-specific

2. Authenticated shell polish
- sidebar now feels more like a deliberate workspace surface
- signed-in state card is visually stronger
- active navigation states are clearer
- the app feels more premium without becoming flashy

3. Chat workspace polish
- dock launcher is stronger
- thread list selection is clearer
- message surfaces are easier to scan
- full-page chat feels more like a real productivity surface

### Why this matters

Frontend quality is not only about "can the route load?"
It is also about whether a user believes the product is serious, trustworthy, and production-grade.

This pass was specifically aimed at improving that feeling without making the UI noisy or childish.

## 18. Why We Still Keep A Separate UAT Guide

Even after the automated verifiers pass, visual quality still needs a browser-oriented checklist.

That is why [FRONTEND_UAT_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_UAT_GUIDE.md) exists.

The automated layer answers:

- did the route work?
- did the contract stay stable?
- did auth/chat/report flows still behave correctly?

The manual browser layer answers:

- does the homepage feel premium?
- does the sign-in flow feel clear?
- do the dashboards feel too crowded or too empty?
- does mobile behavior feel intentional?

That distinction is important for a beginner, because it explains why "all tests passed" and "the UI feels finished" are related, but not identical.

## 19. Counsellor And Admin Academic Pressure Upgrade

The frontend originally gave student pages the first academic-foundation upgrade.
This later pass extends the same idea to counsellor and admin.

### What changed

Counsellor screens now start showing:

- overall shortage counts
- I-grade risk counts
- R-grade risk counts
- subject hotspots inside counsellor scope

Admin screens now start showing:

- institution-wide I-grade risk counts
- institution-wide R-grade risk counts
- overall shortage pressure
- top subject hotspots

### Why this matters

If a counsellor asks the chatbot about R-grade risk but the dashboard only shows generic high-risk queue numbers, the product feels split-brained.

So this pass keeps three things aligned:

- what the backend knows
- what the chatbot says
- what the dashboard shows

That is a major production-quality rule:
the numbers visible in the product should support the language used by the assistant.

## 20. Counsellor Scope Safety Rule

There is another rule that matters just as much as good UI:

- a counsellor must only see assigned students

This is not only a backend concern.
It affects frontend trust too, because the frontend will render whatever the backend allows.

After the scope-hardening pass, the intended rule is:

- student sees only self
- counsellor sees only assigned students
- admin sees institution-wide data

So when a counsellor opens:

- case workbench
- student history
- timeline
- warnings
- alerts
- AI assist drilldowns

the backend should reject out-of-scope students instead of silently returning data.

## 21. Branch And Semester Pressure Visuals

This pass added a deeper analytical layer to the counsellor and admin reports pages.

Before this, the UI could already show:

- top subject pressure
- I-grade counts
- R-grade counts
- overall shortage counts

That was useful, but it still left an important real-world question unanswered:

- where is the pressure concentrated

In real institutional work, that usually means:

- which branch is under the most pressure
- which semester needs attention first

So the frontend now includes:

- branch pressure charts
- semester pressure charts

These are not decorative charts.
They are grounded summaries built from the generalized academic foundation.

What they help users understand:

- counsellors can see whether one branch inside their assigned cohort needs more attention
- admins can see whether one branch or semester slice needs broader institutional action

Why this matters:

- it makes the reports feel more like a real academic operations product
- it also keeps dashboard, reports, and chatbot aligned around the same branch/semester pressure model

## 22. Deeper Case Drilldown Context

This pass improves the counsellor case workbench and the admin operations reading experience.

Before this pass, the operational context panel mostly explained:

- recent activity
- milestone flags
- SLA posture

That was useful, but it still forced the user to mentally reconstruct the academic situation.

So the operational drilldown now also surfaces:

- branch
- current year and semester
- semester mode
- overall attendance posture
- subjects below threshold counts
- weakest subject
- current academic consequence summary

Why this matters:

- a counsellor can now open one student and understand both workflow state and academic state in one place
- the product feels more production-grade because the case screen behaves like a real case brief, not just a notification trace

## 23. Active Academic Burden Visibility

This pass adds a real-world academic rule that is easy to miss if the UI only shows current-semester numbers.

### The problem

A student may:

- be performing better in the current semester
- even look `LOW` risk in the prediction layer
- but still have an uncleared `I_GRADE` or `R_GRADE` from an earlier semester

If the frontend hides that, the product gives the wrong academic picture.

### What the frontend now shows

Student pages now surface:

- active burden count
- academic burden summary
- monitoring cadence
- unresolved `I_GRADE` and `R_GRADE` subject cards with effective status such as:
  - `Pending I-grade clearance`
  - `Pending R-grade clearance`

Counsellor pages now surface:

- total students with active academic burden
- carry-forward burden monitoring panel
- queue emphasis for burden-backed monitoring cases
- case drilldown visibility for unresolved burden subjects

### Why this matters

This keeps the UI honest:

- current semester improvement is still visible
- but uncleared I/R grade obligations are not silently forgotten

That is much closer to how a real institution would track academic follow-up.

### Timeline effect

The timeline now also includes uncleared-burden visibility.

That means a student can now see events that effectively say:

- this subject entered I-grade or R-grade status
- this subject still remains uncleared

This is important because otherwise the timeline would show only the trigger moment and not the continuing burden that follows.
