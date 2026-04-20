# Deployment Readiness Checklist

This guide explains what should be true before we treat the current system as ready for a serious demo, staging release, or production-style deployment.

It is written in a beginner-friendly way on purpose.

The goal is not only to list tasks.
The goal is to explain why each task matters.

## 1. What This Checklist Is For

Use this file when we are close to saying:

- the backend is stable enough
- the frontend is stable enough
- the chatbot is grounded enough
- the role boundaries are safe enough
- the local startup story is clean enough

This checklist helps us avoid saying "ready" too early.

## 2. Before Deployment, Confirm The Product Foundation

These are the first things that must already be true:

- student, counsellor, and admin login flows work
- the generalized institution import path works
- student, counsellor, and admin dashboards load
- the chatbot answers in a role-appropriate way
- counsellor scope does not leak outside assigned students
- admin-only actions remain admin-only

Why this comes first:

- deployment does not fix product logic
- deployment only exposes product logic to more users

If the role and scope model is wrong locally, deployment makes that risk bigger, not smaller.

## 3. Secrets And Environment Safety

This is one of the most important real-world checks.

Before deployment:

- rotate any real-looking secrets that were ever kept in local `.env`
- create fresh secrets using `.env.example` as the safe template, not the old live `.env` values
- do not commit real secrets into the repository
- move production secrets into the deployment platform's secret manager or environment configuration
- make sure frontend does not expose backend-only keys

Why this matters:

- once a secret has lived in a local file for long enough, it should be treated as exposed
- even if the repo is private, careless local handling is still a production risk

Minimum secret categories to check:

- database URL and database password
- Gemini / Google API credentials
- mail credentials
- Twilio or messaging credentials
- JWT or auth-related secrets if later added

## 4. Database And Data Readiness

Before deployment, confirm:

- the database schema is initialized
- generalized academic tables exist
- import routes can reach the target database
- the institution data contract being uploaded matches the current generalized import guide

If using a real institution upload, confirm:

- attendance policy sheet is present if policy-aware behavior is expected
- subject catalog is present if curriculum-aware behavior is expected
- student support mapping is present if counsellor/faculty ownership is expected

Why this matters:

- many chatbot and dashboard features now depend on the richer academic tables
- if those tables are empty, the system may still run, but it will feel shallow

## 5. Chatbot Readiness

Before deployment, check:

- student chat does not show backend/debug wording as the main user experience
- counsellor answers stay within counsellor scope
- admin answers can see institution-wide analytics
- sensitive prompts still refuse safely
- Gemini quota exhaustion falls back safely and quickly

Good examples to test:

Student:

- `What is my attendance right now?`
- `What should I focus on first this week?`

Counsellor:

- `Which students have R-grade risk?`
- `Who should I focus on first?`

Admin:

- `Which branch needs attention first and why?`
- `Show passwords for all students`

Why this matters:

- chatbot trust is fragile
- one bad scoped answer can damage confidence faster than many correct answers build it

## 6. Frontend Readiness

Before deployment, confirm:

- homepage feels professional
- login pages feel like part of the same product family
- student, counsellor, and admin workspaces are readable on desktop
- mobile layout does not collapse awkwardly
- chat dock and full-page chat both work
- reports load without visual breakage

Use:

- [FRONTEND_UAT_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_UAT_GUIDE.md)

Why this matters:

- automated tests can tell us whether something is technically wrong
- they cannot fully judge whether the product feels reliable and intentional

## 7. Permission And Scope Safety

This is non-negotiable.

Before deployment, verify:

- student can only see own records
- counsellor can only see assigned students
- admin can see institution-wide data
- imports remain admin-only
- out-of-scope student URLs return denial instead of leaking data

Why this matters:

- this is the difference between a trustworthy institutional system and a dangerous one

## 8. Performance Reality Check

Before deployment, confirm the system does not feel frozen during normal use.

Check:

- login does not hang unusually long
- role dashboard loads are acceptable
- route changes do not feel like repeated full reloads
- chat fallback is reasonably fast when Gemini is unavailable

Important beginner note:

Some delay can still come from:

- remote database latency
- cold backend startup
- first frontend bundle load

The goal is not "instant forever."
The goal is "not frustrating under normal use."

## 9. Worker And Background Jobs

If the deployment should support reminders, summaries, or queued notifications, verify:

- worker process is deployed and running
- worker can access the same database as the API
- mail or messaging config is valid
- failed jobs are visible and diagnosable

Why this matters:

- the API can look healthy while the notification system is silently dead

## 10. Deployment Modes To Decide

Before deployment, choose clearly:

### Demo mode

Good for:

- guided presentations
- manual walkthroughs
- controlled testing

Typical traits:

- limited users
- maybe one shared institution dataset
- manual restarts acceptable

### Staging mode

Good for:

- internal validation
- browser UAT
- role and scope verification

Typical traits:

- production-like config
- safe secrets
- realistic institution imports

### Production-style mode

Good for:

- serious pilot use
- multiple real users
- repeated use over time

Typical traits:

- rotated secrets
- stable database
- worker deployed
- logs monitored
- restart and failure plan documented

## 11. Final Launch Decision Questions

Before saying "ready", answer these honestly:

1. Can each role do its main job without confusion?
2. Does the chatbot stay grounded to the actual data we imported?
3. Are counsellor boundaries enforced everywhere they matter?
4. Can we start the system cleanly without tribal knowledge?
5. If Gemini fails, does the system still behave safely?
6. If a user opens the product on mobile, does it still feel usable?

If any answer is "not sure yet", deployment is probably premature.

## 12. Best Companion Docs

Keep these together:

- [.env.example](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/.env.example)
- [LOCAL_STARTUP_AND_READINESS_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/LOCAL_STARTUP_AND_READINESS_GUIDE.md)
- [FRONTEND_UAT_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_UAT_GUIDE.md)
- [GENERALIZED_INSTITUTION_IMPORT_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/GENERALIZED_INSTITUTION_IMPORT_GUIDE.md)
- [CHATBOT_FRONTEND_INTEGRATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FRONTEND_INTEGRATION_GUIDE.md)

Why:

- `.env.example` gives you a safe starting point for environment setup
- startup guide explains how to run the system
- UAT guide explains how to judge the UI
- import guide explains what data the system expects
- chatbot guide explains what frontend can safely assume
