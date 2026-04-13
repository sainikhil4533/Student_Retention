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
