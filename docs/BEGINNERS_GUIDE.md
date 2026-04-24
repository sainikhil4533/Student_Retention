# Student Retention Platform — Beginner's Guide

> **What is this?** A system that predicts which students are likely to drop out, 
> classifies them into risk tiers, and helps administrators and counsellors 
> take action before it's too late.

---

## 🧠 How It Works (Simple Version)

```
Student Data (attendance, grades, fees)
        ↓
   ML Model predicts dropout probability (0.0 to 1.0)
        ↓
   Risk Classification (4 tiers)
        ↓
   Dashboard shows who needs help
        ↓
   Counsellors intervene
```

---

## 🎯 The 4-Tier Risk System

Every student gets a **dropout probability** from the ML model — a number 
between 0 (no risk) and 1 (certain dropout). We classify students into 
4 tiers based on what that number *means*:

| Tier | Threshold | What It Means | Action Required |
|------|-----------|---------------|-----------------|
| 🔴 **HIGH** | ≥ 0.50 (50%) | Student is **more likely to drop out than not**. This is the mathematical decision boundary. | Immediate intervention |
| 🟡 **MEDIUM** | ≥ 0.30 (30%) | **1 in 3 chance** of dropping out. Meaningful risk signals present. | Proactive support & monitoring |
| 🔵 **LOW** | ≥ 0.15 (15%) | **1 in 7 chance**. Minor indicators visible. | Periodic check-ins |
| 🟢 **SAFE** | < 0.15 (15%) | Negligible risk. Student appears stable. | No action needed |

### Why these exact numbers?

- **0.50** is the most defensible threshold in probability — it's the point where 
  dropout becomes *more likely than not*. Every statistician agrees on this boundary.
- **0.30** (~1 in 3) is universally accepted as "moderate risk" across medical, 
  financial, and educational risk models.
- **0.15** (~1 in 7) is the standard "low but non-negligible" threshold.
- These thresholds are **fixed and universal** — they don't change based on the 
  current dataset. If a cohort has no high-risk students, that's genuinely good 
  news, not a classification error.

### Where is this code?

📄 **`src/api/risk_classification.py`** — the single source of truth.
Every part of the system imports `classify_risk_level()` from this one file.

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                  FRONTEND                        │
│              (React + Vite)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │Dashboard │ │Students  │ │  Chatbot (Copilot)│ │
│  │(4 tiers) │ │Directory │ │                   │ │
│  └────┬─────┘ └────┬─────┘ └────────┬──────────┘ │
│       │            │                │            │
└───────┼────────────┼────────────────┼────────────┘
        │            │                │
        ▼            ▼                ▼
┌─────────────────────────────────────────────────┐
│                  BACKEND                         │
│              (FastAPI + Python)                   │
│                                                  │
│  /institution/risk-overview    → Dashboard data  │
│  /institution/students         → Student table   │
│  /institution/counsellor-accountability → Staff  │
│  /copilot/chat                 → Chatbot AI      │
│                                                  │
│  risk_classification.py  ← ALL tiers come from   │
│                             this ONE file        │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│               DATABASE                           │
│           (Supabase / PostgreSQL)                 │
│                                                  │
│  student_profiles, predictions, interventions,   │
│  alerts, attendance records, finance events      │
└─────────────────────────────────────────────────┘
```

---

## 📁 Key Files (What Does What)

### Backend (Python — `src/` folder)

| File | What It Does |
|------|--------------|
| `src/api/risk_classification.py` | **THE risk engine.** Defines thresholds (0.50/0.30/0.15) and `classify_risk_level()`. Every other file imports from here. |
| `src/api/routes/institution.py` | API endpoints for the admin dashboard: risk overview, student directory, counsellor accountability |
| `src/api/scoring_service.py` | Runs the ML model on a student's data and saves the prediction |
| `src/api/copilot_tools.py` | The chatbot brain — handles queries like "show medium risk students" |
| `src/api/institutional_analytics.py` | Aggregates data for charts (department breakdown, attendance pressure, etc.) |
| `src/api/schemas.py` | Defines the shape of API responses (what fields are returned) |
| `src/db/repository.py` | All database queries (get predictions, get profiles, etc.) |
| `src/db/database.py` | Database connection setup |

### Frontend (TypeScript/React — `frontend/src/` folder)

| File | What It Does |
|------|--------------|
| `frontend/src/pages/admin.tsx` | The admin dashboard: 4 tier cards, student table, reports, operations, imports |
| `frontend/src/components/layout.tsx` | Sidebar navigation and page shell |
| `frontend/src/components/chatbot.tsx` | The floating chatbot widget |
| `frontend/src/components/charts.tsx` | Bar charts and pie charts |
| `frontend/src/components/ui.tsx` | Reusable UI components (buttons, cards, stat cards) |
| `frontend/src/types.ts` | TypeScript type definitions matching the backend API |
| `frontend/src/App.tsx` | Route definitions (which URL shows which page) |
| `frontend/src/lib/api.ts` | API client (how frontend talks to backend) |
| `frontend/src/lib/auth.ts` | Authentication logic |

---

## 🖥️ Admin Dashboard — What You See

### 1. Risk Tier Cards (top of dashboard)
Four large, color-coded, clickable cards:
- 🔴 **High Risk** — click to see all HIGH students in a table
- 🟡 **Medium Risk** — click to filter MEDIUM students
- 🔵 **Low Risk** — click for LOW students
- 🟢 **Safe** — click for SAFE students

### 2. Student Directory (`/app/admin/students`)
A full table showing every student with:
- Student ID
- Risk level badge (color-coded)
- Dropout probability (%)
- Branch / Department
- Attendance %
- Top risk reasons (why the model flagged them)
- Assigned counsellor
- Case state (active/resolved/etc.)
- Overdue badge if counsellor hasn't followed up

### 3. Counsellor Accountability (Operations page)
A table showing each counsellor's workload:
- How many students assigned to them
- How many are HIGH / MEDIUM risk
- Pending interventions
- Overdue follow-ups
- Performance status (✓ On Track / Needs Attention / ⚠ Overdue)

### 4. Chatbot
Ask questions in natural language:
- "show medium risk students" → lists MEDIUM tier students
- "who are high risk" → lists HIGH tier students  
- "how many safe students" → counts SAFE tier

---

## 🚀 How to Run

### Prerequisites
- Python 3.10+
- Node.js 18+
- A `.env` file with database credentials (copy from `.env.example`)

### Start everything
```bash
# Terminal 1 — Backend
python run_all.py

# Terminal 2 — Frontend
cd frontend
npm run dev
```

### Access
- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

### Login credentials
- **Admin**: `admin.retention` / `Admin@123`
- Check the login page for other role credentials

---

## 🔄 Data Flow: What Happens When a Student Gets Scored

```
1. Admin uploads student data (Excel/ZIP)
       ↓
2. Backend parses and stores profiles, attendance, grades, fees
       ↓
3. Scoring service runs ML model on each student
       ↓
4. Model outputs: final_risk_probability (e.g., 0.47)
       ↓
5. risk_classification.py converts:  0.47 → "MEDIUM"
       ↓
6. Dashboard shows the student in the MEDIUM tier card
       ↓
7. Counsellor gets assigned and takes action
```

---

## ❓ FAQ

**Q: Why are there 0 HIGH risk students in my sample data?**
A: Your sample data has maximum probability of ~0.60. With the HIGH threshold 
at 0.50, students above 0.50 ARE classified as HIGH. If you see 0, it means 
no student in the current dataset has probability ≥ 0.50. That's actually a 
good thing — it means the model doesn't think anyone is more likely to drop 
out than not.

**Q: Can I change the thresholds?**
A: Yes — edit `src/api/risk_classification.py`. Change `HIGH_THRESHOLD`, 
`MEDIUM_THRESHOLD`, and `LOW_THRESHOLD`. The entire system will automatically 
use the new values. But be careful: the current thresholds are semantically 
grounded (0.50 = decision boundary) and shouldn't be changed without good reason.

**Q: What if all students are in MEDIUM and none in LOW/SAFE?**
A: That's because your current dataset's probabilities are all above 0.30. 
When real production data arrives with students who have lower risk scores, 
the LOW and SAFE tiers will populate naturally.

**Q: How does the chatbot know which tier a student is in?**
A: It imports the same `classify_risk_level()` function from 
`risk_classification.py`. There is ONE source of truth for classification.
