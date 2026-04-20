# Local Startup And Readiness Guide

This guide explains how to run the full system locally in the simplest possible way.

It is written for a beginner who wants to know:

- which command starts what
- when the worker is needed
- when the frontend is needed
- what "ready" looks like
- what to test before calling the system usable

## 1. Fastest Way To Start Everything

From the project root, run:

```powershell
python run_all.py --with-frontend
```

What this does:

- starts the backend API
- starts the background worker
- starts the frontend Vite dev server

You can also use:

```powershell
start_system.bat
```

That batch file now does the same thing.

## 2. What Each Process Is For

### Backend API

This is the main FastAPI server.

It powers:

- login
- dashboards
- reports
- chatbot
- imports
- all API routes

Default local URL:

```text
http://127.0.0.1:8000
```

### Worker

This is the background job runner.

It is useful for:

- queued alerts
- summary snapshot tasks
- background processing behavior

If you are only doing a very quick API or UI check, you can run without it.

### Frontend

This is the Vite development server.

It powers:

- homepage
- login pages
- student/counsellor/admin workspaces
- chatbot UI

Default local URL is usually:

```text
http://127.0.0.1:5173
```

## 3. Alternative Startup Modes

### Backend only

```powershell
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

Use this if you only want:

- backend testing
- Swagger/API testing

### Backend + worker, no frontend

```powershell
python run_all.py
```

### Backend + frontend, no worker

```powershell
python run_all.py --with-frontend --no-worker
```

This is useful when you want UI flow testing without background-task noise.

## 4. Fast Preflight Check

Before starting everything, you can run:

```powershell
python check_local_readiness.py
```

What this does:

- checks that the main startup files exist
- checks that `.env` exists
- checks that the most important environment keys are present
- warns if the auth secret still looks like a demo/default value

Why this is useful:

- it catches obvious local setup mistakes before you waste time debugging startup errors
- it gives a beginner one simple "am I basically ready?" command

If `.env` is missing on a fresh machine, start from:

```powershell
copy .env.example .env
```

Then replace the placeholder values with your real environment settings.

## 5. What "Ready" Looks Like

The system is in a good local state if:

- backend starts without import errors
- frontend opens in the browser
- login works
- at least one student, counsellor, and admin route loads
- chatbot responds
- no obvious permission leaks appear

## 6. Practical Local Readiness Checklist

Run this checklist in order:

1. homepage opens
2. student login works
3. counsellor login works
4. admin login works
5. counsellor case workbench opens
6. admin reports open
7. chatbot answers a simple role-safe question
8. imports page opens for admin only

## 7. Recommended UAT Questions

### Student

- `What is my attendance right now?`
- `What should I focus on first this week?`

### Counsellor

- `Who should I focus on first?`
- `Which students have R-grade risk?`

### Admin

- `Which branch needs attention first and why?`
- `Which semester needs attention first?`

## 8. Important Honest Notes

### Gemini quota

If Gemini quota is exhausted, you may still see logs mentioning quota exhaustion.

That does not automatically mean the chatbot is broken.
The current system is designed to fall back safely to the deterministic grounded path.

### Remote database latency

If the configured database is remote, some local delays can still come from:

- database network latency
- first-load query cost
- cold startup effects

### Scope safety

Counsellor visibility must remain limited to assigned students only.
This is not optional.

If that ever fails in a browser test, treat it as a serious product issue.

## 9. Best Doc Pairing

While using this guide, keep these nearby:

- [FRONTEND_UAT_GUIDE.md](/c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_UAT_GUIDE.md)
- [GENERALIZED_INSTITUTION_IMPORT_GUIDE.md](/c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/GENERALIZED_INSTITUTION_IMPORT_GUIDE.md)
- [DEPLOYMENT_READINESS_CHECKLIST.md](/c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/DEPLOYMENT_READINESS_CHECKLIST.md)

Why:

- the UAT guide tells you what to verify
- the import guide explains what data foundation the system expects
- the deployment checklist explains what still has to be true before we call the system launch-ready
