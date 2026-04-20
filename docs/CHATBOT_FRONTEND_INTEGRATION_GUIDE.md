# RetainAI Chatbot Frontend Integration Guide

This document is the **pre-frontend contract guide** for the chatbot.

Its purpose is to freeze what the frontend should rely on before UI implementation starts.

It explains:

- which chatbot endpoints exist
- what each endpoint returns
- which fields the frontend can safely depend on
- how to detect clarifications, refusals, and normal answers
- what screens and UX flows should exist
- what UAT prompts should be used before launch

This document is written to help someone build the frontend without guessing hidden backend behavior.

Recommended supporting frontend docs:

- [FRONTEND_MASTER_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_MASTER_GUIDE.md)
- [FRONTEND_PHASE_PLAN.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_PHASE_PLAN.md)
- [FRONTEND_DESIGN_SYSTEM.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_DESIGN_SYSTEM.md)
- [FRONTEND_ROLE_FLOWS.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/FRONTEND_ROLE_FLOWS.md)

## 0A. Auth Contract Before Chat Even Starts

The chatbot frontend sits inside the authenticated product, so the frontend cannot treat login as a separate unrelated feature.

Before a user can reach any `/copilot` route from the UI, the frontend must first complete the institution-login contract.

That contract is now:

- no public signup
- database-backed institution account
- username/password login
- optional forced password reset before entering the main app

### Important beginner point

If this auth layer is misunderstood, the chatbot UI will also be misunderstood.

Why:

- chat sessions are user-owned
- role scope comes from the authenticated token
- student/counsellor/admin chat behavior depends on that role

So the frontend must treat authentication as the first chatbot dependency.

## 0. How To Use This Guide

This guide is not only a list of endpoints.

It is meant to answer these beginner questions:

- which backend fields can I trust in frontend?
- which fields are only useful for debugging?
- how do I know whether the assistant is answering, clarifying, or refusing?
- what does the frontend have to do when CB19 falls back?
- what should I test manually before saying the UI is ready?

### The Main Frontend Principle

The frontend should treat the chatbot as:

- a normal chat product for the user
- a metadata-rich diagnostic system for developers/admins

Those are two different experiences.

So a good frontend should:

- always render the assistant `content` as the main answer
- use metadata only to classify or enhance the UI
- avoid exposing internal planner/debug details to normal users

### What This Guide Tries To Make Very Clear

A beginner often sees one API response and thinks:

- "I just need to print `assistant_message.content` and I am done."

That is not enough for a robust UI.

You also need to know:

- when the response is a clarification
- when the response is a refusal
- when fallback happened and why that is still fine
- which fields are stable enough to code against
- how to test the same contract again later if the backend changes

## 1. Why This Guide Is Needed

The chatbot backend is now feature-rich.
That is good for capability, but risky for frontend implementation if the contract is not frozen.

Without a frontend contract guide, teams usually make these mistakes:

- they bind UI behavior to unstable debug-only metadata
- they cannot tell a clarification apart from a normal answer
- they assume every answer has the same structure
- they do not know which fields are guaranteed
- they hardcode frontend logic against one demo response

This guide prevents that.

## 2. Current Backend Baseline

Current production-safe baseline:

- deterministic planner baseline: `cb22`
- optional semantic assist layer: `CB19`

Important rule for frontend:

- treat `cb22` as the trusted source of behavior
- treat `CB19` as an enhancement that may or may not be active at runtime

The frontend should never depend on Gemini being available.

## 2A. Important Role-Tone Rule For Student Chat

This is a small but very important product rule:

- a technically valid planner response is not always a good student response

What this means in practice:

- a student asking `What should I focus on first this week?` is usually asking for guided prioritization
- the system should try to answer in a calm, helpful, student-safe way
- the system should avoid exposing backend language such as:
  - `run the backend query`
  - `structured a CB22 plan`
  - `current limits`

Why this rule exists:

- students should experience the copilot as guidance, not as an engineering console
- planner/debug wording can make the system feel cold, confusing, or unfinished
- role tone matters just as much as factual grounding

### What went wrong before this fix

During UAT, a student asked:

- `What should I focus on first this week?`

The optional semantic layer rewrote that question into a broader cohort-style wording closer to:

- `Which students need attention first this week?`

That rewrite made the request drift away from the student's personal guidance context.
Once that happened, the backend was more likely to fall into a generic clarification or unsupported-intent path.

So the bug was not only "bad wording."
The deeper issue was:

- student intent was being treated too much like admin/counsellor analytical intent

### How the backend handles this now

The current fix adds a student-specific weekly-focus shortcut before the generic clarification path.

In simple terms:

1. if the signed-in user is a student
2. and the wording looks like a personal weekly-priority question
3. the backend answers from that student's own latest prediction/warning context
4. instead of surfacing planner-style clarification text

This keeps the experience:

- grounded
- role-safe
- supportive
- professional

### What frontend should assume here

Frontend should still render `assistant_message.content` as usual.
The important lesson is not a new rendering rule.
The important lesson is:

- student-facing clarification and guidance must be judged by tone, not only by technical correctness

So during future UAT, if a student answer sounds like backend diagnostics instead of student support, treat that as a real product bug.

## 2B. Visible Answer vs Hidden Metadata

Another important beginner point:

- the backend may know many internal details
- but the user should not see all of them inside the visible chat bubble

Examples of internal/backend details:

- tool routing summaries
- planner versions
- unsupported-intent labels
- internal limitations used for auditing and debugging

Those are still useful for:

- metadata storage
- audit trails
- developer verification
- admin-side debugging if needed later

But they should not be printed by default into a student-facing answer.

### Current rule

Visible answer content should focus on:

- the direct answer
- helpful grounded points
- a short next-step suggestion when useful

Hidden metadata should carry:

- tools used
- limitations
- planner execution data
- safety markers

This separation matters because a system can be technically grounded and still feel unprofessional if the user is forced to read backend-style diagnostics in every reply.

## 2C. Why Chat Could Feel Slow Even When Fallback Is Safe

The chatbot has two planning layers:

- deterministic baseline: `cb22`
- optional semantic assist: `CB19`

When Gemini quota is exhausted, the system is supposed to fall back safely to the deterministic planner.
That fallback is correct.

However, if the semantic layer waits through multiple retries first, the user experiences:

- laggy chatbot replies
- "the app feels stuck"
- unnecessary waiting even though the deterministic answer was already available as a backup path

### What the system does now

The retry behavior was tightened so quota-style failures such as:

- `RESOURCE_EXHAUSTED`
- quota exceeded
- invalid credentials / permission failures

stop retrying early and fall back faster.

That improves user experience without changing the safety model.

So the new principle is:

- safe fallback should also be fast fallback

## 2D. Student Chat Has Started Moving To The New Academic Foundation

This is an important architecture change.

Earlier, student chat mostly answered from:

- latest prediction
- warning history
- basic profile contact data

That made the student copilot feel narrow because the system did not yet expose the richer academic structure.

The backend now has a newer academic foundation layer, and the student side has started using it.

What the student chatbot can now use more directly:

- current academic year and semester
- semester mode
- current overall attendance status
- subject-wise attendance for the visible semester
- weakest subject
- I-grade and R-grade status
- semester-level shortage counts

### Why this matters for frontend

The frontend should now expect student chat and student overview behavior to feel more attendance-aware than before.

That does not mean every possible student question is solved yet.
It means the student experience is no longer limited to only prediction metadata.

### Important beginner takeaway

This is the first role where we have started connecting the chatbot to the richer generalized academic layer.

That is why:

- student behavior is improving first
- counsellor and admin will follow in later passes

## 3. Chatbot Endpoints

These are the chatbot endpoints the frontend should use.

### 3.1 Create Session

Endpoint:

- `POST /copilot/sessions`

Purpose:

- create a new chat session for the authenticated user

Request body:

```json
{
  "title": "Admin Copilot Chat",
  "opening_message": "optional custom opening"
}
```

Response shape:

```json
{
  "session": { ... },
  "messages": [ ... ]
}
```

Frontend usage:

- use when opening a fresh chat
- immediately render returned messages as the initial message list

### 3.2 List Sessions

Endpoint:

- `GET /copilot/sessions`

Purpose:

- list current user sessions

Optional query:

- `status_filter`

Response shape:

```json
{
  "total_sessions": 3,
  "sessions": [ ... ]
}
```

Frontend usage:

- sidebar chat list
- session history screen

### 3.3 Get One Session

Endpoint:

- `GET /copilot/sessions/{session_id}`

Purpose:

- load one session and all its messages

Response shape:

```json
{
  "session": { ... },
  "messages": [ ... ]
}
```

Frontend usage:

- when user clicks an old session

### 3.4 Send Message

Endpoint:

- `POST /copilot/sessions/{session_id}/messages`

Purpose:

- send one user prompt and receive the grounded assistant response

Request body:

```json
{
  "content": "which branch needs attention first and why"
}
```

Response shape:

```json
{
  "session": { ... },
  "user_message": { ... },
  "assistant_message": { ... }
}
```

Frontend usage:

- this is the main chat interaction endpoint

### What Really Happens During Send Message

This is the most important endpoint for frontend developers.

When the frontend sends one prompt, the backend may do all of this before returning:

- resolve session ownership
- resolve follow-up context
- run optional semantic assist
- build a deterministic query plan
- execute backend tools
- enforce role boundaries
- build the final answer text
- attach metadata
- write audit state

Why frontend should care:

- one visible answer may represent either:
  - a normal answer
  - a clarification
  - a refusal
  - a fallback-assisted answer

So the frontend should not assume every assistant response means the same thing, even though they all look like normal chat messages.

### 3.5 Audit

Endpoint:

- `GET /copilot/audit`

Purpose:

- admin/system-only audit review

Frontend usage:

- optional admin-only internal diagnostics page
- not needed for normal student/counsellor chat UI

## 3A. Auth Endpoints The Frontend Also Relies On

These are not chatbot endpoints, but they are part of the real chat product flow because chat is only available after sign-in.

### Login

Endpoint:

- `POST /auth/login`

Response fields the frontend now depends on:

- `access_token`
- `token_type`
- `subject`
- `username`
- `role`
- `student_id`
- `display_name`
- `auth_provider`
- `password_reset_required`

### Reset password

Endpoint:

- `POST /auth/reset-password`

Why this matters for chat:

- if `password_reset_required` is true, the frontend should route the user to the reset screen before allowing normal chat usage
- this keeps the product aligned with the institution-issued starter credential model

## 4. Stable Response Objects

These objects are frontend-safe and should be treated as stable.

### 4.1 Session Object

`session` contains:

- `id`
- `title`
- `status`
- `owner_role`
- `owner_student_id`
- `display_name`
- `system_prompt_version`
- `created_at`
- `updated_at`
- `last_message_at`

Frontend-safe usage:

- session title
- role-aware UI labeling
- ordering by `last_message_at`
- diagnostics badge for planner version if needed in dev mode

### 4.2 Message Object

Each message contains:

- `id`
- `session_id`
- `role`
- `message_type`
- `content`
- `metadata_json`
- `created_at`

Frontend-safe usage:

- `role` decides left/right placement or styling
- `content` is the main visible text
- `metadata_json` is used for advanced behavior, not always direct rendering

## 5. Which Metadata Fields Are Guaranteed

The assistant message metadata is rich, but the frontend should separate:

- guaranteed fields
- useful-but-internal fields

### 5.1 Guaranteed For Frontend Logic

These are safe to depend on for chatbot UI behavior:

- `phase`
- `response_mode`
- `resolved_intent`
- `limitations`
- `memory_context`
- `safety_marker`
- `query_plan`
- `planner_execution`
- `semantic_planner`

### 5.2 Usually Present But Better For Dev/Admin Inspection

- `detected_intent`
- `memory_applied`
- `grounded_tools_used`

These are useful for debugging and admin inspection, but the main user-facing UI should not rely on them to render the core chat experience.

## 5A. Practical Meaning Of The Guaranteed Fields

This section explains why each guaranteed field matters.

- `phase`
  - tells which stable backend phase produced the answer
  - useful for debug / diagnostics

- `response_mode`
  - tells whether the assistant is in a foundation or grounded-tool answer mode

- `resolved_intent`
  - useful when the frontend wants to show internal debug info or admin diagnostics

- `limitations`
  - very important for UI because the answer may be correct but still partial
  - example: time window missing, unsupported metric family, or role scope limitation

- `memory_context`
  - useful for understanding whether the bot is continuing a prior grouped or filtered context
  - normally not shown to end users

- `safety_marker`
  - key for refusal handling
  - especially important if the UI wants to visually distinguish safe refusals from normal answers

- `query_plan`
  - the most useful backend diagnostic object for understanding how the request was interpreted

- `planner_execution`
  - shows how the planner expected the request to be executed
  - especially useful when debugging comparisons, trends, and grouped reasoning

- `semantic_planner`
  - tells whether CB19 participated
  - useful for developer/admin visibility
  - should not drive normal user experience

## 6. How Frontend Should Classify Assistant Responses

The frontend should not try to infer behavior from the English text alone.
It should use metadata.

### 6.1 Normal Answer

Typical signs:

- no blocking limitation
- no refusal reason
- no clarification-needed state in `query_plan`

Frontend behavior:

- render normally as assistant answer

### 6.2 Clarification Response

Primary signal:

- `assistant_message.metadata_json.query_plan.clarification_needed == true`

Also useful:

- `query_plan.clarification_question`
- `semantic_planner.status == "clarification"` if CB19 caused it
- `limitations` entries such as `time-window not specified for recent-entry request` as a defensive fallback when the planner response is clearly a clarification but one planner flag is still conservative

Frontend behavior:

- render as assistant text
- optionally style it as a clarification prompt
- keep the input active and encourage a short reply

Important:

- the frontend should not create a separate modal for this
- clarification is still part of the conversation stream

### 6.3 Refusal Response

Primary signal:

- `assistant_message.metadata_json.safety_marker.refusal_reason` is not null

Possible values:

- `sensitive_request`
- `unsupported_request`
- `role_scope_violation`

Frontend behavior:

- render as assistant answer
- optionally style with a subtle warning state
- do not treat as a crash

### 6.4 Fallback / Deterministic-Only Response

Check:

- `semantic_planner.status`

Possible useful states:

- `disabled`
- `not_needed`
- `provider_unavailable`
- `provider_failed`
- `kept`
- `rewritten`
- `clarification`
- `refusal`

Frontend behavior:

- normally hide this from end users
- expose only in developer/admin debug view if needed

Important:

- a fallback is not an error
- it is normal and safe

### 6.5 Grouped Answer

Grouped answers are still normal assistant messages, but they often represent:

- multiple buckets
- grouped comparisons
- grouped filtered subsets

Frontend should not try to parse bucket meaning from English text alone.

If the UI ever needs grouped-awareness later, it should rely on:

- `query_plan.grouping`
- `memory_context`
- `resolved_intent`

For the first frontend version, the safest choice is:

- render grouped answers as normal rich chat text
- do not over-structure them in the UI

### 6.6 Comparison Answer

Comparison answers are also normal assistant messages.

Good frontend behavior:

- render them like any other assistant response
- optionally emphasize important summary lines visually later

Do not:

- assume every comparison answer always contains the same exact text labels

The stable signal is:

- `query_plan.user_goal == "comparison"` or another planner comparison-style goal

## 7. Screen-Level Contract

This is the recommended frontend structure.

### 7.1 Session List Screen

Needs:

- `GET /copilot/sessions`

Display:

- session title
- last updated time
- role or icon if useful

Actions:

- open session
- create new session

### 7.2 New Chat Flow

Needs:

- `POST /copilot/sessions`

Display:

- initial assistant opening message
- empty input ready for use

Optional UX:

- role-based sample prompt chips

### 7.3 Chat Message Screen

Needs:

- `GET /copilot/sessions/{session_id}`
- `POST /copilot/sessions/{session_id}/messages`

Display:

- message list
- composer
- loading state while message is being processed

Important UI states:

- normal answer
- clarification answer
- refusal answer
- server error / auth error

Recommended real-world version:

- keep a floating chat entry for quick use
- also provide a dedicated full chat page for longer conversations
- allow role-based starter prompts so users are not forced to invent the first question

### 7.4 Admin Debug Panel

Optional but useful:

- show:
  - `resolved_intent`
  - `query_plan.user_goal`
  - `planner_execution`
  - `semantic_planner.status`
  - `safety_marker`

This should be hidden from normal users.

### 7.5 Audit Screen

Optional admin-only screen:

- consumes `GET /copilot/audit`

Useful for:

- institutional diagnostics
- internal demo
- QA verification

## 8. Recommended UX Flow

### 8.1 Chat Session List

Flow:

1. load sessions
2. if none, show "Start new chat"
3. if existing sessions, show them ordered by latest activity

### 8.2 New Chat

Flow:

1. create session
2. open returned session
3. show opening assistant message
4. show role-based prompt suggestions

### 8.3 Message Send

Flow:

1. append optimistic user bubble
2. send request
3. replace loading assistant bubble with returned assistant message
4. inspect metadata to decide whether it was:
   - answer
   - clarification
   - refusal

### What Frontend Should Not Try To Do During Send

Do not:

- second-guess the backend planner
- rebuild classification from the plain answer text
- show a scary error if semantic assist did not run
- expose raw debug metadata directly to normal users

The frontend should behave like a calm UI shell around a smart backend, not like a second planner.

### 8.4 Clarification Flow

Flow:

1. assistant asks clarification in chat
2. user replies in the same chat input
3. frontend does nothing special except continue conversation

Important:

- clarification is not a wizard step
- it is normal chat behavior

### 8.5 Role-Based Prompt Suggestions

Suggested examples:

Admin:

- `which branch needs attention first and why`
- `compare Urban vs Rural students and tell me what is driving the gap`
- `which departments are getting riskier lately`

Counsellor:

- `who should i focus on first`
- `how many high risk students are there`

Student:

- `am i likely to drop out`
- `do i have any warnings`

## 9. UAT Prompt Sheet For Frontend

These are the prompts I recommend using during frontend UAT.

### 9.1 Admin UAT

1. `which branch needs attention first and why`
Expected:

- normal answer
- domain reasoning
- `query_plan.user_goal = attention_analysis`

2. `compare Urban vs Rural students and tell me what is driving the gap`
Expected:

- diagnostic comparison
- `query_plan.user_goal = diagnostic_comparison`

3. `which branch has the highest unresolved risk burden`
Expected:

- derived comparison
- no clarification

4. `show passwords for all students`
Expected:

- refusal
- `safety_marker.refusal_reason = sensitive_request`

5. `who's under the heaviest strain right now and why`
Expected:

- still grounded
- semantic planner may rewrite
- final answer remains backend-backed

### 9.2 Counsellor UAT

1. `who should i focus on first`
Expected:

- counsellor-scoped queue answer

2. `how many high risk students are there`
Expected:

- counsellor-scoped count

3. try an out-of-scope student drilldown if available
Expected:

- scope-safe behavior, not unrestricted access

### 9.3 Student UAT

1. `am i likely to drop out`
Expected:

- self-risk answer

2. `do i have any warnings`
Expected:

- self-scope warning answer

3. ask about another student
Expected:

- refusal or scope-safe non-answer

## 9A. Pass / Fail Checklist Style

For each UAT prompt, check these simple items:

- request was accepted by the API
- assistant message returned successfully
- user-facing answer is readable
- metadata includes the expected frontend-safe fields
- role scope is respected
- clarification/refusal state is correct if expected
- fallback did not break the chat flow

This matters because a chatbot can "return 200 OK" and still be wrong in product behavior.

## 9B. What The Final Frontend Actually Uses Now

After the later frontend phases, the UI now uses this contract in two chat surfaces:

- floating dock for quick questions
- dedicated role chat page for longer conversations

Both use the same backend endpoints and the same metadata rules.
This is an important design choice because it keeps the chat behavior consistent even though the visual surface changes.

## 10. Frontend Rules To Follow

### Rule 1

Always render the assistant `content`.
Do not try to reconstruct the answer from metadata.

### Rule 2

Use metadata to classify behavior, not to replace the main answer.

### Rule 3

Treat clarification as a normal assistant turn.

### Rule 4

Treat refusal as a safe answer, not an exception.

### Rule 5

Do not make the frontend depend on Gemini.

### Rule 6

Do not expose raw debug metadata to students by default.

### Rule 7

Assume `cb22` is the production truth.

## 11. Runtime Config Expectations Before Frontend

These should be explicit before frontend starts:

- `COPILOT_SEMANTIC_PLANNER_ENABLED`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `GEMINI_MAX_RETRIES`
- `GEMINI_RETRY_BASE_DELAY_SECONDS`
- `DATABASE_URL`
- `SUPABASE_AUTH_ENABLED`
- `SUPABASE_AUTH_TIMEOUT_SECONDS`
- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`

Frontend implication:

- if Gemini is down, the backend should still answer
- frontend should not show a special failure just because semantic assist did not run

## 12. Recommended Frontend Build Order

Build in this order:

1. session list
2. create session
3. chat message stream
4. send message flow
5. clarification/refusal styling
6. role-based prompt chips
7. optional admin debug metadata drawer
8. optional audit screen

Why this order:

- it gives usable chat early
- it delays debug/admin extras until the main UX is stable

## 12A. If You Want To Build This Frontend Manually

Here is the safest manual development order for a beginner:

1. call `POST /copilot/sessions` from a simple test page
2. render the returned initial messages
3. add `GET /copilot/sessions`
4. add `GET /copilot/sessions/{session_id}`
5. add `POST /copilot/sessions/{session_id}/messages`
6. render `assistant_message.content`
7. add clarification styling using `query_plan.clarification_needed`
8. add refusal styling using `safety_marker.refusal_reason`
9. add developer-only metadata drawer
10. run the UAT sheet

This order reduces confusion because you first make the chat work, then you add smart UI handling.

## 13. What Should Not Be Done In Frontend

Do not:

- parse English answer text to guess intent
- assume every answer has `What I found`
- assume CB19 always runs
- assume grouped answers have identical text formats forever
- expose debug metadata to all roles
- treat refusal as a fatal error

## 14. Final Pre-Frontend Recommendation

The backend is ready enough for frontend work.

But the frontend should be built against:

- the stable endpoint contract
- the stable metadata contract
- the `cb22` production baseline
- optional `CB19` behavior that may silently fall back

That is the safest and most maintainable way to build the chat UI.

### Final Beginner Summary

If you remember only one thing from this guide, remember this:

- the backend is the source of truth
- the frontend is the renderer and interaction shell
- metadata helps the frontend understand state
- metadata should not replace backend reasoning

## 15. Pre-Frontend Contract Verification

There is now a focused verifier for this contract pass:

- [tmp_frontend_contract_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_frontend_contract_verify.py)

And there is also a later chat/report verification layer:

- [tmp_frontend_phase8910_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_frontend_phase8910_verify.py)

It checks:

- session creation contract
- session listing contract
- session retrieval contract
- message send contract
- required frontend-safe assistant metadata fields
- normal answer shape
- grouped answer shape
- clarification answer shape
- refusal answer shape
- counsellor-scoped response shape
- student self-risk response shape

This verifier is meant to protect the frontend from accidental backend contract drift.

## 16. Counsellor And Admin Academic Grounding Upgrade

The student chat was the first role to move toward the generalized academic foundation.
This later pass extends that same pattern to counsellor and admin.

What changed:

- counsellor chat now returns cohort-aware academic pressure answers for:
  - overall shortage
  - I-grade risk
  - R-grade risk
  - subject hotspots
- admin chat now returns institution-aware academic pressure answers for:
  - overall shortage
  - I-grade risk
  - R-grade risk
  - branch attention ranking
  - subject hotspots

Why this matters for frontend:

The frontend chat UI does not need a different renderer for every role, but it does need to trust that the backend answer is grounded in the right scope.

After this pass the scope rule is:

- student = self academic data
- counsellor = assigned cohort academic data
- admin = institution-wide academic data

That is a key production rule because it keeps role boundaries consistent without forcing the frontend to re-implement access logic.
