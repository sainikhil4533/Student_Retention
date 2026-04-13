# Frontend Phase Plan

## How To Use This Document

This file is the execution map for the new frontend that we started from scratch.

Use it when you want to understand:

- what each frontend phase is supposed to achieve
- why we separated the work into phases instead of building everything in one shot
- which early phases are already implemented
- what still belongs to later frontend work

This file is not the full implementation guide.
For the deeper beginner explanation, also read:

- [FRONTEND_MASTER_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_MASTER_GUIDE.md)
- [FRONTEND_DESIGN_SYSTEM.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_DESIGN_SYSTEM.md)
- [FRONTEND_ROLE_FLOWS.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_ROLE_FLOWS.md)
- [CHATBOT_FRONTEND_INTEGRATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FRONTEND_INTEGRATION_GUIDE.md)

## Why We Split Frontend Work Into Phases

Frontend work becomes messy very quickly if we try to do everything at once.

For this system, the risk was even higher because:

- there are three roles
- there is a chatbot
- there are dashboards and reports
- there is admin-only import control
- the app must work on desktop and mobile
- the app must feel professional, not like a demo

So we split the work into phases to answer one question at a time:

1. What should exist?
2. What should it look like?
3. What should the public experience be?
4. What should happen after login?
5. What should each role see?
6. How should the chatbot fit into the UI?

## Phase List

### F1. Product Spec Freeze

Goal:
- freeze the screen map
- freeze the route map
- freeze the role responsibilities
- freeze where chatbot, reports, and imports belong

Why it exists:
- if we skip this, the UI keeps changing while implementation is happening
- that causes rework and confusion

### F2. Design System Foundation

Goal:
- define typography
- define colors
- define spacing
- define card/button/input styles
- define motion rules

Why it exists:
- if every page invents its own style, the app stops feeling professional
- a design system is how we keep the whole product looking like one real company product

### F3. Public Experience

Goal:
- build the homepage
- keep sign-in at the top right
- keep public users out of the internal app
- explain the platform clearly before login

Why it exists:
- this is an institution-specific product, not a public chatbot
- the public homepage should create trust, not expose internal tooling

### F4. Auth And App Shell

Goal:
- build login pages
- protect routes
- create role-aware app layout
- make the chatbot available inside the authenticated product

Why it exists:
- once a user logs in, the product needs a stable shell:
  - navigation
  - protected pages
  - app header
  - sidebar
  - chatbot dock

### F5. Student Module

Goal:
- full student workspace
- deeper student timeline
- more complete student reports

Why it exists:
- the student dashboard alone is not enough if we want repeat engagement
- students need one place that feels like a guided journey, not only a risk score
- this is where the formal, motivational version of the timeline belongs

### F6. Counsellor Module

Goal:
- full counsellor workflow pages
- student case views
- intervention-first work surface

Why it exists:
- counsellors do not just need charts; they need a working surface for real case handling
- a professional counsellor module should move from "who needs attention?" to "what do I do next?"
- this phase is what turns the counsellor side from a dashboard into an operational workspace

### F7. Admin Module Expansion

Goal:
- deeper institutional reports
- richer imports UX
- admin operations polish

Why it exists:
- admin users need more than a landing snapshot
- they need a second layer for operational health, import friction, and intervention performance
- import actions should stay available without taking over the first screen

### F8. Chat UX Expansion

Goal:
- deeper chat polish
- expanded chat page
- richer session behavior

Why it exists:
- a floating launcher alone is useful, but not enough for longer role-based analysis
- users need a full conversation surface for deeper work, history review, and follow-up analysis
- the chat experience should feel familiar without forcing the user to leave the product context

### F9. Reports Polish

Goal:
- better charts
- better empty states
- export-friendly presentation

Why it exists:
- raw charts are not enough if they become hard to read on smaller screens or sparse datasets
- reports should help the user act, not just prove that charts can render
- export actions matter most on the admin side, where institutional reporting is an actual workflow

### F10. Responsive And UAT Pass

Goal:
- finish mobile details
- run true end-to-end UI testing

Why it exists:
- a dashboard that only works nicely on laptop is not production-ready
- chat, navigation, and reports all need their own mobile behavior
- final UAT is where the frontend stops being merely implemented and starts being trustworthy

## What Is Implemented Right Now

The current unattended implementation block completed:

- `F1` Product Spec Freeze
- `F2` Design System Foundation
- `F3` Public Experience
- `F4` Auth And App Shell
- `F5` Student Module
- `F6` Counsellor Module
- `F7` Admin Module Expansion
- `F8` Chat UX Expansion
- `F9` Reports Polish
- `F10` Responsive And UAT Pass

That means the frontend now already has:

- a new scratch-built frontend workspace under [frontend](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/frontend)
- a professional homepage
- role-based sign-in entry pages
- protected application routing
- student, counsellor, and admin dashboard shells backed by real endpoints
- reports routes for each role
- admin import page
- a shared chatbot launcher and history panel
- a dedicated student journey route
- a dedicated counsellor workbench route
- a dedicated admin operations route
- a dedicated copilot page for each role in addition to the floating dock
- richer chat session behavior with starter prompts and clearer clarification/refusal states
- better chart empty states and legend blocks
- admin export actions in the reporting layer
- stronger mobile navigation and chat behavior

## What F5-F7 Added In Practical Product Terms

F1-F4 gave us a strong product shell.
F5-F7 are what made the shell start behaving like a serious role-based system.

These phases added:

- a student journey page that turns a summary dashboard into a fuller progress story
- a counsellor workbench that turns a queue into an actual intervention workspace
- an admin operations page that separates executive summary from deeper operational reading

This separation matters because each role now has:

- a first screen for orientation
- a deeper screen for role-specific work

That is one of the clearest differences between a prototype UI and a production-grade UI.

## F5 Student Module Status

What is now implemented:

- student dashboard with action-first summary cards
- student reports route for cleaner analytics
- student journey route for the fuller timeline story
- student-safe access to their own timeline endpoint

Important edge cases:

- if the backend cannot produce a student overview yet, the UI shows an honest empty state instead of pretending data exists
- if the timeline has no events yet, the page still explains what will appear later
- the design stays professional even while using motivational language

## F6 Counsellor Module Status

What is now implemented:

- counsellor dashboard with queue-first summary
- counsellor reports route for workload analysis
- counsellor cases workbench with:
  - active case list
  - selected case summary
  - operational context panel
  - intervention history panel
  - intervention logging form

Important edge cases:

- if there are no active cases, the counsellor sees a clean empty state instead of a broken page
- if a selected student has no operational context yet, the page surfaces that honestly
- intervention logging stays in-page so the user does not lose context by navigating away

## F7 Admin Module Status

What is now implemented:

- admin dashboard with executive summary cards
- admin reports route for institutional comparisons
- admin imports route for controlled cohort upload
- admin operations route for:
  - intervention effectiveness
  - import coverage friction
  - plain-language operational summaries

Important edge cases:

- import coverage can be zero after a cleanup or before the next real upload, and that is now treated as a valid state
- upload is separated from the dashboard so analytics and operational tasks do not clash
- admin-only routes remain protected by role guards

## F8 Chat UX Status

What is now implemented:

- shared dock-based chatbot for quick access
- dedicated role chat routes for longer sessions
- starter prompts by role
- clearer in-message treatment for:
  - grounded answers
  - clarifications
  - safe refusals
- better mobile thread navigation inside chat

Important edge cases:

- if semantic assist falls back, chat still behaves normally
- if there is no existing session, the user can create one from either dock or full page
- clarification remains in the stream and is not treated like a broken request

## F9 Reports Polish Status

What is now implemented:

- honest chart empty states
- chart legend blocks so values stay readable even without perfect hover interaction
- admin export buttons for key CSV-backed reporting endpoints

Important edge cases:

- sparse imported data is treated as valid, not as a rendering failure
- charts remain readable even when only a few data points exist

## F10 Responsive And UAT Status

What is now implemented:

- mobile overlay handling for sidebar navigation
- full-page chat view so mobile users are not forced into only a drawer workflow
- focused verifier coverage for the F8-F10 layer

Important edge cases:

- dock and full chat page do not fight each other
- mobile history panel can be opened and closed without blocking the rest of the workspace

## Important Boundary

All planned frontend phases through F10 are now implemented.

That does not mean "perfect forever."
It means:

- the planned role surfaces exist
- the chatbot has both quick and expanded entry points
- reporting is readable and export-aware
- mobile behavior has been deliberately handled
- focused verification exists for each major frontend block

This is important because otherwise it becomes hard to tell:

- what is already "real"
- what is still "initial"
- what is still future expansion

## Why Reports Are Not Dumped On The First Screen

One major product decision was this:

- login should land on a dashboard
- dashboard should show summary and urgency
- full reports should live on a separate route

Why:

- dashboards are for fast orientation
- reports are for analysis
- if we put every chart directly on the first screen, the product feels heavy and noisy

So the design intentionally uses:

- first screen = executive snapshot
- reports route = deeper analysis

## Why Chatbot Is Inside The App, Not On The Public Homepage

We intentionally kept the real chatbot behind login.

Why:

- the chatbot is role-aware
- the chatbot depends on authenticated scope
- the chatbot is grounded to private institutional data

So the correct product choice was:

- public homepage explains the product
- authenticated experience exposes the real chatbot

## Manual Rebuild Mindset For A Beginner

If you wanted to rebuild this frontend manually, the right mental order would be:

1. Decide the roles.
2. Decide what each role is allowed to see.
3. Decide the public-to-private transition.
4. Build the app shell.
5. Plug in real endpoints.
6. Add charts and polish.
7. Add the chatbot in the authenticated workspace.

That is exactly why the phase order looks the way it does.
