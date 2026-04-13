# Project Documentation Guide

This file explains **all major docs in the project**, what each one is for, and in what order a beginner should read them.

The goal is simple:

- someone new to the project should not have to guess where to start
- someone working on frontend should not read the wrong backend roadmap first
- someone learning the concepts should understand the system before diving into low-level workflow details

## 1. Best Reading Order For A Beginner

If you are completely new, read in this order:

1. [DOCS_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/DOCS_GUIDE.md)
   - what each doc is for
   - the reading order

2. [PHASE_1_TO_10_BACKEND_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/PHASE_1_TO_10_BACKEND_GUIDE.md)
   - how the backend matured phase by phase
   - very good starting point for understanding the product/backend journey

3. [LIVE_SYSTEM_WORKFLOW.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/LIVE_SYSTEM_WORKFLOW.md)
   - how the live backend behaves end to end right now

4. [CHATBOT_FULL_IMPLEMENTATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FULL_IMPLEMENTATION_GUIDE.md)
   - how the chatbot was built from `CB1` to `CB19`
   - why each chatbot layer exists

5. [CHATBOT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT.md)
   - the structured chatbot phase/status tracker

6. [CHATBOT_FRONTEND_INTEGRATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FRONTEND_INTEGRATION_GUIDE.md)
   - what frontend can safely depend on

7. [FRONTEND_MASTER_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_MASTER_GUIDE.md)
   - how the scratch-built frontend is structured and why

8. [FRONTEND_PHASE_PLAN.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_PHASE_PLAN.md)
   - what the frontend phases are and which ones are already implemented

9. [FRONTEND_DESIGN_SYSTEM.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_DESIGN_SYSTEM.md)
   - the visual/design reasoning behind the UI

10. [FRONTEND_ROLE_FLOWS.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_ROLE_FLOWS.md)
   - how student, counsellor, and admin flows differ in practice

After that, go into specialized docs depending on your task.

## 2. Docs By Purpose

### A. System Understanding Docs

These are the best docs for understanding the product and architecture.

- [PHASE_1_TO_10_BACKEND_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/PHASE_1_TO_10_BACKEND_GUIDE.md)
  - beginner-friendly backend evolution story

- [LIVE_SYSTEM_WORKFLOW.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/LIVE_SYSTEM_WORKFLOW.md)
  - current live backend behavior

- [FULL_AI_SYSTEM_ROADMAP.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FULL_AI_SYSTEM_ROADMAP.md)
  - larger AI-system roadmap and reasoning

### B. Chatbot Docs

- [CHATBOT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT.md)
  - chatbot phase tracker

- [CHATBOT_FULL_IMPLEMENTATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FULL_IMPLEMENTATION_GUIDE.md)
  - deep chatbot architecture and implementation explanation

- [CHATBOT_FRONTEND_INTEGRATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FRONTEND_INTEGRATION_GUIDE.md)
  - frontend contract and UAT for chatbot

### C. Contracts And Rules Docs

- [AI_RESPONSE_CONTRACT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/AI_RESPONSE_CONTRACT.md)
  - response ownership and output-shape contract for the AI scoring side

- [FEATURE_CONTRACT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FEATURE_CONTRACT.md)
  - which features are allowed, forbidden, and how alignment is enforced

- [DATA_DICTIONARY.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/DATA_DICTIONARY.md)
  - beginner-friendly data understanding for OULAD and feature mapping

### D. Frontend Docs

- [FRONTEND_MASTER_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_MASTER_GUIDE.md)
  - main beginner-friendly explanation of the scratch-built frontend

- [FRONTEND_PHASE_PLAN.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_PHASE_PLAN.md)
  - frontend roadmap and phase state

- [FRONTEND_DESIGN_SYSTEM.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_DESIGN_SYSTEM.md)
  - visual system, motion rules, and gamification boundaries

- [FRONTEND_ROLE_FLOWS.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_ROLE_FLOWS.md)
  - role-by-role UX reasoning and operational flow explanation

### E. Operational / Milestone Docs

- [BACKEND_SIGNOFF_2026-04-12.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/BACKEND_SIGNOFF_2026-04-12.md)
  - milestone backend signoff snapshot

- [REPORT_INDEX.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/REPORT_INDEX.md)
  - where model reports and project docs fit

### F. Import / Institution Docs

- [VIGNAN_IMPORT_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/VIGNAN_IMPORT_GUIDE.md)
  - production-style import guide for Vignan data

### G. Guardian Notification Docs

- [GUARDIAN_NOTIFICATION_PHASE_A_TO_G_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/GUARDIAN_NOTIFICATION_PHASE_A_TO_G_GUIDE.md)
  - the guardian escalation subsystem from concept to implementation

## 3. Which Doc To Read For Which Task

### If you want to understand the backend conceptually

Read:

- [PHASE_1_TO_10_BACKEND_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/PHASE_1_TO_10_BACKEND_GUIDE.md)
- [LIVE_SYSTEM_WORKFLOW.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/LIVE_SYSTEM_WORKFLOW.md)

### If you want to understand the chatbot deeply

Read:

- [CHATBOT_FULL_IMPLEMENTATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FULL_IMPLEMENTATION_GUIDE.md)
- [CHATBOT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT.md)

### If you want to build frontend

Read:

- [FRONTEND_MASTER_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_MASTER_GUIDE.md)
- [FRONTEND_PHASE_PLAN.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_PHASE_PLAN.md)
- [FRONTEND_DESIGN_SYSTEM.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_DESIGN_SYSTEM.md)
- [FRONTEND_ROLE_FLOWS.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_ROLE_FLOWS.md)
- [CHATBOT_FRONTEND_INTEGRATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FRONTEND_INTEGRATION_GUIDE.md)
- [CHATBOT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT.md)

### If you want to understand data/features

Read:

- [DATA_DICTIONARY.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/DATA_DICTIONARY.md)
- [FEATURE_CONTRACT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FEATURE_CONTRACT.md)

### If you want to understand AI output ownership

Read:

- [AI_RESPONSE_CONTRACT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/AI_RESPONSE_CONTRACT.md)

### If you want to understand guardian escalation

Read:

- [GUARDIAN_NOTIFICATION_PHASE_A_TO_G_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/GUARDIAN_NOTIFICATION_PHASE_A_TO_G_GUIDE.md)
- [LIVE_SYSTEM_WORKFLOW.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/LIVE_SYSTEM_WORKFLOW.md)

### If you want to understand Vignan import

Read:

- [VIGNAN_IMPORT_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/VIGNAN_IMPORT_GUIDE.md)
- [BACKEND_SIGNOFF_2026-04-12.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/BACKEND_SIGNOFF_2026-04-12.md)

## 4. One Important Warning

Do not read one doc in isolation and assume it explains the whole project.

Why:

- some docs are milestone snapshots
- some docs are conceptual contracts
- some docs are live behavior docs
- some docs are chatbot-only docs
- some docs were written for a specific phase

That is normal in a growing project.

This guide exists so those different docs still feel like one coherent documentation system.

## 5. Final Beginner Recommendation

If you ever feel confused again, come back to this file first.

The safest sequence is:

- concept docs first
- workflow docs next
- specialized subsystem docs after that

That way you understand the system before you start reading implementation details.
