# Guardian Notification Phase A To G Guide

## How To Read This Document

This file is the deep subsystem guide for guardian escalation.

Use it when you want to understand:

- why guardian notifications were added
- how the guardian phases progressed from A to G
- how email, SMS, WhatsApp, queueing, and policy logic fit together

Recommended supporting docs:

- [DOCS_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/DOCS_GUIDE.md)
- [LIVE_SYSTEM_WORKFLOW.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/LIVE_SYSTEM_WORKFLOW.md)
- [PHASE_1_TO_10_BACKEND_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/PHASE_1_TO_10_BACKEND_GUIDE.md)

Why this note matters:

This is a focused subsystem doc.
It explains guardian escalation deeply, but it is not the best first file for understanding the whole backend or chatbot.

This document explains the guardian-notification feature set that was added after the main backend Phase 1 to Phase 10 work.

It is written for a beginner.

The goal is to explain:

- what was implemented in each guardian phase
- why that step was needed
- what exact files and concepts were added
- why the system uses deterministic policy first and AI second
- how email, SMS, and WhatsApp were made to work
- how the system behaves in real-world university scenarios

---

## 1. Why Guardian Notifications Were Needed

The system already had:

- student warnings
- faculty escalation
- follow-up reminders
- interventions
- institution reporting

But your faculty added one more real-world requirement:

> in worst-case scenarios, the system should also notify parents or guardians

This requirement is important because in many real university situations:

- a student may ignore the warning
- faculty may still not get engagement from the student
- attendance and marks may keep falling
- there may also be a fee issue
- family support may be necessary in the final severe stage

Also, in the Indian context, not all parents use email regularly.

So the system had to support:

- `email`
- `sms`
- `whatsapp`

But it was not correct to jump straight into sending messages.

We first had to answer these questions:

- When exactly should the parent be contacted?
- Who stores the parent details?
- Which channel should be used?
- How do we avoid sending too early?
- How do we avoid duplicate sends?
- How do we audit what was sent?

That is why the guardian work was split into phases.

---

## 2. Big Design Principle

The most important design decision was:

**guardian escalation decision must be deterministic**

and

**message wording may use AI, but safely**

Why?

Because the question:

> should we contact the parent now?

is a serious institutional decision.

That should not depend on freeform LLM behavior.

So the system was designed like this:

- deterministic policy decides whether parent contact is allowed
- database stores the event
- worker sends in the background
- AI can improve the message wording
- fallback template still exists if AI is unavailable

This is a production-style design.

---

## 3. Correct Guardian Phase Names

The guardian work should be read with these names:

- `Phase A`: guardian contact fields + deterministic guardian escalation policy
- `Phase B`: guardian alert event persistence + evaluation/history/queue APIs
- `Phase C`: guardian background delivery integration with live email support
- `Phase D`: guardian SMS/WhatsApp provider integration with Twilio-compatible abstraction
- `Phase E`: guardian visibility and operational reporting
- `Phase F`: automatic guardian escalation orchestration
- `Phase G`: AI guardian message drafting

After Phase G, there were also two important refinements:

- guardian wording control fix
- SMS dispatch stability cleanup with optional Gemini use

These are explained at the end of this document.

---

## 4. Phase A

## Phase A: Guardian Contact Fields + Deterministic Guardian Escalation Policy

### 4.1 What Was Added

Guardian contact fields were added to student profiles:

- `parent_name`
- `parent_relationship`
- `parent_email`
- `parent_phone`
- `preferred_guardian_channel`
- `guardian_contact_enabled`

These were added in:

- [models.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/db/models.py)
- [add_guardian_contact_to_student_profiles.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/db/migrations/add_guardian_contact_to_student_profiles.py)
- [schemas.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/schemas.py)
- [profile.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/routes/profile.py)
- [sample_students.json](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/demo/sample_students.json)

### 4.2 Why These Fields Were Needed

Without these fields, the system does not know:

- who the guardian is
- whether guardian contact is allowed
- whether email or phone exists
- whether SMS or WhatsApp should be preferred

This means Phase A was the **data foundation**.

### 4.3 Why `guardian_contact_enabled` Is Important

This field acts as a safety switch.

If it is `false`, the system should not contact guardians even if:

- the student is high risk
- faculty escalation already happened
- the case looks severe

This is important because real institutions may have:

- privacy policies
- age-related constraints
- program-specific rules
- cases where guardian involvement is not allowed

### 4.4 Guardian Escalation Policy

A dedicated policy file was added:

- [guardian_alert_policy.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/guardian_alert_policy.py)

This file contains deterministic logic for:

- whether guardian escalation should happen
- why it should happen
- which channel should be used

### 4.5 Why A Policy File Was Needed

Parent escalation is not the same as:

- student warning
- faculty alert

It is more sensitive.

So the system should not say:

> student is high risk, send parent message immediately

That would be too aggressive and unrealistic.

Instead, Phase A required a proper worst-case policy.

### 4.6 What The Policy Checks

Guardian escalation is blocked unless all important safety conditions are satisfied.

In simple terms, the policy expects:

- guardian contact is enabled
- student is still high risk
- student warning flow already started
- faculty escalation already exists
- faculty has not already supported/resolved the case
- the case has crossed a worst-case threshold

Worst-case threshold means things like:

- repeated high-risk cycles
- relapse after earlier recovery
- critical unattended case
- follow-up reminder stage

### 4.7 Channel Selection Logic

Phase A also made the backend choose the most practical guardian channel safely.

Logic:

- use `preferred_guardian_channel` if it is usable
- if preferred channel is not usable, fallback sensibly
- phone supports `sms` and `whatsapp`
- email needs `parent_email`

This was necessary because in many Indian-family cases:

- parent email may be missing
- phone may be the most reliable channel
- WhatsApp may be better than email

### 4.8 Real-World Meaning Of Phase A

Phase A made the system capable of answering:

> If this case becomes severe, do we even have the guardian details and permission needed to contact them?

Before Phase A, the answer was no.

After Phase A, the answer became yes.

---

## 5. Phase B

## Phase B: Guardian Alert Event Persistence + Evaluation/History/Queue APIs

### 5.1 What Was Added

Phase B created a separate guardian event table and backend APIs.

Files:

- [models.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/db/models.py)
- [add_guardian_alert_events.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/db/migrations/add_guardian_alert_events.py)
- [repository.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/db/repository.py)
- [guardian_alert_service.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/guardian_alert_service.py)
- [guardian_alerts.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/routes/guardian_alerts.py)
- [schemas.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/schemas.py)

### 5.2 Why A Separate Table Was Needed

Guardian notifications are different from:

- student warnings
- faculty alert emails

So the backend needed a separate audit table:

- `guardian_alert_events`

This stores:

- student id
- prediction history id
- alert type
- guardian name
- guardian relationship
- recipient
- channel
- delivery status
- retry count
- error message
- context snapshot
- provider details

### 5.3 Why This Matters

If a parent is contacted, the institution must be able to answer:

- Was a guardian alert actually created?
- For which prediction cycle?
- Was it queued?
- Was it sent?
- Which channel was used?
- Did delivery fail?

Without persistence, none of this is reliable.

### 5.4 Evaluation API

Phase B added:

- `GET /guardian-alerts/evaluation/{student_id}`

This endpoint tells the system:

- whether guardian escalation is currently eligible
- what channel would be used
- why it is or is not eligible

This is useful because counsellors/admins can inspect the decision before delivery happens.

### 5.5 History API

Phase B added:

- `GET /guardian-alerts/history/{student_id}`

This gives the timeline/audit view of guardian escalation attempts.

### 5.6 Queue API

Phase B added:

- `POST /guardian-alerts/queue/{student_id}`

This is important because it separates:

- policy decision
- persistence
- actual sending

That is the correct architecture.

The queue API says:

> this guardian escalation is approved and should be sent later through the worker

### 5.7 Why Phase B Was Needed Before Sending

It would have been poor design to send parent messages directly from the API with no record.

Phase B made the system queue-ready and auditable first.

That is why it came before live SMS/WhatsApp/email sending.

---

## 6. Phase C

## Phase C: Guardian Background Delivery Integration With Live Email Support

### 6.1 What Was Added

Phase C connected guardian notifications to the existing background worker architecture.

Files:

- [email_service.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/email_service.py)
- [guardian_alert_dispatcher.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/guardian_alert_dispatcher.py)
- [job_queue.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/worker/job_queue.py)
- [guardian_alerts.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/routes/guardian_alerts.py)

### 6.2 Why Background Delivery Was Needed

The backend should not make the main API wait for:

- SMTP delivery
- Twilio delivery
- Gemini drafting

That would make the request slow and fragile.

So the architecture was:

1. create guardian event
2. queue job
3. worker sends in background

This is the same product-style design already used for other notifications.

### 6.3 Why Email Came First

Email was the easiest live channel to activate first because:

- SMTP was already configured
- the project already had email sending logic
- guardian email could reuse that path

So Phase C gave live guardian delivery through email first.

### 6.4 What Happened For SMS/WhatsApp In Phase C

At that time, SMS and WhatsApp were not yet fully connected to a provider.

So the system correctly did **not pretend** they were working.

Instead, it stored statuses like:

- `provider_pending`

This is a good design because fake success is dangerous.

### 6.5 Real-World Meaning Of Phase C

After Phase C, guardian delivery became a real background workflow instead of just a theoretical event.

---

## 7. Phase D

## Phase D: Guardian SMS/WhatsApp Provider Integration

### 7.1 What Was Added

Phase D integrated a Twilio-compatible provider for:

- `sms`
- `whatsapp`

Files:

- [guardian_messaging_service.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/guardian_messaging_service.py)
- [guardian_alert_dispatcher.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/guardian_alert_dispatcher.py)
- provider tracking fields in the guardian event model and migration

### 7.2 Why Twilio-Compatible Design Was Chosen

The system needed:

- one provider for SMS
- one provider for WhatsApp
- minimal redesign
- production-style abstraction

Twilio supports both.

So this was efficient and realistic.

### 7.3 What Phase D Handles

- channel-aware sender selection
- Twilio REST API call
- provider name tracking
- provider message id tracking
- failure capture
- Indian phone normalization

### 7.4 Why Phone Normalization Was Important

Guardian phone numbers in real data may appear like:

- `9123456780`
- `+919123456780`
- `09123456780`

The backend needed to normalize them safely before sending.

This is especially important in Indian-number workflows.

### 7.5 What Happens If Twilio Is Not Configured

The system does not crash.

It records:

- `provider_pending`
- provider name
- error message

This is correct because the backend still knows:

- a guardian escalation existed
- which channel it wanted to use
- why actual delivery did not happen

### 7.6 Real-World Meaning Of Phase D

After Phase D:

- guardian email could be sent through SMTP
- guardian SMS could be sent through Twilio
- guardian WhatsApp could be sent through Twilio

This is where multi-channel guardian communication became real.

---

## 8. Phase E

## Phase E: Guardian Visibility And Operational Reporting

### 8.1 What Was Added

Guardian escalation details were exposed in the operational views people already use.

Files:

- [cases.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/routes/cases.py)
- [timeline.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/routes/timeline.py)
- [institutional_analytics.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/institutional_analytics.py)
- [institution.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/routes/institution.py)
- [reports.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/routes/reports.py)

### 8.2 Why This Phase Was Needed

Sending a parent message is not enough.

Counsellors and admins must also be able to see:

- was a guardian escalation triggered?
- which channel was used?
- was it sent successfully?
- when did it happen?

So Phase E added that visibility.

### 8.3 What Became Visible

Case state now shows:

- guardian alert type
- guardian alert status
- guardian alert channel
- guardian alert time

Timeline now includes guardian alert events.

Institution overview now counts guardian escalation cases.

CSV/reporting also reflects guardian escalation counts.

### 8.4 Real-World Meaning Of Phase E

Phase E made guardian escalation part of real operations instead of a hidden background feature.

---

## 9. Phase F

## Phase F: Automatic Guardian Escalation Orchestration

### 9.1 What Was Added

Guardian escalation no longer depended only on someone manually calling an API.

The recovery monitor was upgraded to queue guardian escalation automatically when the worst-case policy is satisfied.

Files:

- [guardian_alert_service.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/guardian_alert_service.py)
- [guardian_alerts.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/routes/guardian_alerts.py)
- [recovery_monitor.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/recovery_monitor.py)

### 9.2 Why This Was Needed

In a real system, we should not depend on a staff member remembering:

> now call a separate parent queue API

Instead, once the case becomes severe enough, the backend should handle that automatically.

### 9.3 What The Recovery Monitor Now Does

The monitor checks:

- current high-risk state
- warning history
- escalation history
- intervention status
- repeated-risk condition
- reminder stage

If the guardian policy says yes:

- guardian event is created
- delivery job is queued

### 9.4 Important Fix Inside Phase F

There was a very important realism fix:

when a case moves deeper into escalation, the original student warning may no longer be active because it may already be marked:

- `escalated_to_faculty`

If the system only checked active warnings, it could wrongly conclude:

> no warning exists, so no guardian escalation allowed

So Phase F updated the logic to also use the latest warning history if there is no active warning.

That was a critical production fix.

### 9.5 Real-World Meaning Of Phase F

After Phase F, guardian escalation became part of the real automated intervention pipeline.

---

## 10. Phase G

## Phase G: AI Guardian Message Drafting

### 10.1 What Was Added

Guardian communication got an AI-assisted drafting layer.

Files:

- [ai_assistance_context.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/ai_assistance_context.py)
- [assistant_service.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/ai/assistant_service.py)
- [ai_assist.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/routes/ai_assist.py)
- [email_service.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/email_service.py)
- [guardian_messaging_service.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/guardian_messaging_service.py)
- [guardian_alert_dispatcher.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/guardian_alert_dispatcher.py)

### 10.2 New AI Endpoint

Phase G added:

- `GET /ai-assist/guardian-draft/{student_id}?channel=email|sms|whatsapp`

This allows previewing guardian-friendly wording before delivery.

### 10.3 Why AI Was Added Here

Guardian communication is sensitive.

It should not sound:

- robotic
- too technical
- too blunt

AI helps improve:

- warmth
- clarity
- channel-aware wording

For example:

- email can be fuller
- SMS must be short
- WhatsApp should be concise but human

### 10.4 Why AI Was Not Allowed To Control The Escalation Decision

This is very important.

AI only helps with:

- wording
- structure
- communication quality

AI does **not** decide:

- whether parents should be contacted
- whether the case is worst-case enough
- whether the channel is eligible

Those remain deterministic.

This is the correct production design.

---

## 11. Guardian Wording Fix After Phase G

### 11.1 What Went Wrong Initially

During live WhatsApp testing, a message was received like:

- it mentioned a faculty name awkwardly
- it mixed serious risk with phrases like “improved outlook”
- it sounded too polished and not parent-appropriate

That revealed a real problem:

Gemini had too much freedom in the final guardian message.

### 11.2 Why That Was Bad

Worst-case guardian escalation should not:

- mention faculty names awkwardly
- sound contradictory
- weaken the seriousness of the escalation
- include internal operational context in parent-facing language

### 11.3 What Was Changed

The backend was changed so guardian wording now goes through a **controlled guardian renderer** in:

- [assistant_service.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/ai/assistant_service.py)

Important helper functions:

- `_guardian_risk_concerns(...)`
- `_guardian_next_step(...)`
- `_join_human_list(...)`
- `_build_guardian_controlled_message(...)`

### 11.4 What This Fix Achieved

Now the final guardian wording is:

- simpler
- more serious
- parent-safe
- less contradictory
- free from awkward faculty-name mentions

### 11.5 Important Design Outcome

Gemini can still help, but the backend now guards the final guardian wording much more tightly.

This is exactly the kind of fix a real product team would make after user feedback.

---

## 12. SMS Stability Cleanup

### 12.1 Why SMS Needed Special Handling

SMS is different from email and WhatsApp.

It should be:

- short
- urgent
- fast
- reliable

The earlier SMS flow could be slower because it tried to build too much rich context during send-time.

### 12.2 What Was Changed

The backend SMS path was cleaned up so it became faster and safer.

Later, Gemini support for SMS was re-enabled in a controlled way using:

- `GUARDIAN_SMS_USE_LLM`

inside:

- [guardian_messaging_service.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/guardian_messaging_service.py)

### 12.3 Current SMS Behavior

If Gemini is enabled:

- the worker may try Gemini for SMS drafting

If Gemini is slow or quota-limited:

- fallback controlled SMS text is used automatically

Then:

- Twilio still sends the SMS

This means the system now has the best of both worlds:

- better wording when Gemini works
- reliable delivery when Gemini fails

---

## 13. Are Email, SMS, And WhatsApp Gemini-Enabled?

Yes, all three channels are Gemini-enabled.

But the more precise statement is:

- all three channels **can use Gemini**
- all three channels also have a **safe fallback path**

So:

- `email` -> Gemini-enabled with fallback
- `sms` -> Gemini-enabled with fallback
- `whatsapp` -> Gemini-enabled with fallback

This is important because:

- Gemini improves wording
- fallback guarantees delivery reliability

---

## 14. Are All Three Channels Background-Based?

Yes, the actual production flow is background-oriented for all guardian channels.

Design:

1. policy decides eligibility
2. event is created
3. job is queued
4. worker sends in background

So:

- email is background-based
- SMS is background-based
- WhatsApp is background-based

This means the API path does not need to wait for:

- Gemini
- SMTP
- Twilio

That is correct asynchronous system behavior.

---

## 15. Real Delivery Setup

### 15.1 Email

Guardian email uses SMTP through:

- [email_service.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/email_service.py)

Required `.env` values:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL`

### 15.2 SMS

Guardian SMS uses Twilio through:

- [guardian_messaging_service.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/alerts/guardian_messaging_service.py)

Required `.env` values:

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_SMS_FROM`
- `DEFAULT_PHONE_COUNTRY_CODE`

Optional behavior control:

- `GUARDIAN_SMS_USE_LLM`

### 15.3 WhatsApp

Guardian WhatsApp uses Twilio through the same service.

Required `.env` values:

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_WHATSAPP_FROM`
- `DEFAULT_PHONE_COUNTRY_CODE`

### 15.4 Gemini

Guardian draft generation depends on:

- `GEMINI_API_KEY`
- `GEMINI_MODEL`

But delivery still works when Gemini is unavailable because fallback exists.

---

## 16. Real Testing That Was Done

The guardian system was not only coded.

It was also tested in live conditions.

### 16.1 WhatsApp

Real WhatsApp sends were successfully verified through Twilio.

### 16.2 SMS

Real SMS sends were successfully verified through Twilio.

### 16.3 Email

Guardian email sending through SMTP was verified successfully.

### 16.4 Why This Matters

This means the guardian system is not just:

- queue-ready
- schema-ready
- policy-ready

It is also:

- channel-ready
- provider-ready
- actually tested

---

## 17. Full Guardian Flow In Plain English

This is the final simple end-to-end behavior:

1. student becomes high risk
2. student warning flow begins
3. if risk continues, faculty escalation happens
4. if the case becomes severe enough and still unresolved, guardian policy is evaluated
5. if eligible, guardian alert event is stored
6. a background job is queued
7. worker chooses channel:
   - email
   - SMS
   - WhatsApp
8. message wording may use Gemini
9. if Gemini fails, controlled fallback wording is used
10. provider sends message
11. delivery result is saved
12. case state, timeline, and reports show the guardian escalation

This is the complete guardian escalation architecture.

---

## 18. Why This Is A Good Product Design

This guardian system is strong because it combines:

- deterministic policy
- strong audit trail
- background delivery
- AI-assisted wording
- fallback reliability
- multi-channel support
- reporting visibility

In other words, it is not just:

> send one message to parent

It is a proper product-grade guardian escalation workflow.

---

## 19. Final Summary

Guardian notification support is now complete across:

- data model
- policy layer
- persistence
- APIs
- worker queue
- email delivery
- SMS delivery
- WhatsApp delivery
- AI drafting
- fallback templates
- case/timeline visibility
- institution reporting
- automatic orchestration

So if someone asks:

> Did the system really implement parent escalation properly?

The answer is:

**Yes.**

And if someone asks:

> Is it just a message sender?

The answer is:

**No. It is a full guardian escalation subsystem built on top of the early-warning platform.**
