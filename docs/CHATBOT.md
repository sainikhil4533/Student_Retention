# RetainAI Copilot Guide

This document tracks the chatbot work phase by phase.
It is intended to stay beginner-friendly and reflect what is actually implemented, not just what is planned.

## How To Read This Document

If you are new to this chatbot codebase, read the docs in this order:

1. this file, [CHATBOT.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT.md)
   - use this as the master roadmap and phase tracker
2. [CHATBOT_FULL_IMPLEMENTATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FULL_IMPLEMENTATION_GUIDE.md)
   - use this when you want to understand the full internal flow, why each phase existed, and how the system works under the hood
3. [CHATBOT_FRONTEND_INTEGRATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FRONTEND_INTEGRATION_GUIDE.md)
   - use this before building frontend so you know which backend fields are safe to depend on

### What This File Gives You

This file is best for:

- seeing the chatbot timeline from `CB1` to `CB19`
- understanding which phase introduced which capability
- seeing current status and current limits
- finding the correct verifier for each layer
- understanding what is complete vs optional

### What This File Does Not Try To Do

This file is not the best place for:

- very deep beginner explanation of hidden internal behavior
- step-by-step manual rebuild instructions
- frontend implementation details

Those are covered in the other two docs linked above.

### How Each Phase Entry Should Be Read

Each phase in this file is meant to answer four questions:

1. what problem existed before this phase
2. what was added in this phase
3. why that addition mattered
4. what still remained after that phase

So if you ever feel "I know what changed, but I still don't know why," move to the full implementation guide, where the hidden reasoning is explained in more depth.

For a deeper beginner-friendly explanation of the full build journey, request flow, reasoning behind each phase, edge-case families, and how the chatbot can be recreated manually, see:

- [CHATBOT_FULL_IMPLEMENTATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FULL_IMPLEMENTATION_GUIDE.md)

For the frozen backend contract, frontend expectations, UX flow recommendations, and chatbot UAT prompt sheet before UI implementation, see:

- [CHATBOT_FRONTEND_INTEGRATION_GUIDE.md](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/docs/CHATBOT_FRONTEND_INTEGRATION_GUIDE.md)

## Goal

Build a role-aware chatbot for the student retention system that feels conversational like ChatGPT,
but answers only from allowed institutional data and respects RBAC.

Target roles:

- student
- counsellor
- admin

## Product Direction

The copilot is being built as a grounded institutional assistant, not an unrestricted general chatbot.

That means:

- student can ask only about self
- counsellor can ask only within permitted support scope
- admin can ask institution-wide questions
- answers should be based on real backend data, not hallucinated free-form guesses

## Phase Plan

### Phase CB1 - Copilot Foundation

Purpose:

- create persistent chat sessions
- create chat message storage
- expose role-aware chat endpoints
- establish the first safe assistant response layer

Status:

- completed

Implemented in CB1:

- new DB table for chat sessions
- new DB table for chat messages
- role-aware chat session creation
- role-aware session listing and retrieval
- role-aware message sending
- safe initial assistant responses that do not overclaim tool access yet

Important note:

- CB1 does **not** yet answer deep student/counsellor/admin data questions.
- It creates the secure, auditable chat foundation needed before tool-backed answers.

### Phase CB2 - Safe Data Tools

Purpose:

- add backend tools the chatbot can call safely
- support grounded queries like student self-summary, score lookup, warning history, and import coverage

Status:

- completed

Implemented in CB2:

- grounded tool-backed answer layer for the copilot backend
- student-supported grounded questions:
  - latest risk / score
  - active warning status
  - profile contact summary
- counsellor-supported grounded questions:
  - latest high-risk count
  - student drilldown by `student_id`
- admin-supported grounded questions:
  - imported cohort coverage summary
  - high-risk cohort summary
  - basic counsellor-duty / intervention summary
  - student drilldown by `student_id`

Important note:

- CB2 still uses a focused supported-question set.
- It is grounded on real backend queries, but it is not yet a full natural-language routing layer.

### Phase CB3 - Query Router

Purpose:

- route questions to the correct safe data tools by role and intent

Status:

- completed

Implemented in CB3:

- centralized copilot intent detection
- routed intent categories for:
  - identity questions
  - help / capability questions
  - student self-risk
  - student self-warning
  - student self-profile
  - student drilldown by `student_id`
  - cohort summary questions
  - import coverage questions
  - admin governance questions
  - unsupported question fallback
- detected intent is now stored in assistant response metadata for audit/debug purposes

Important note:

- CB3 improves question routing quality, but it still does not provide fully open-ended natural language handling.
- It routes a structured set of common question types cleanly and safely.

### Phase CB4 - Grounded Answer Generation

Purpose:

- generate conversational answers from real fetched data
- keep answers role-safe and non-hallucinatory

Status:

- completed

Implemented in CB4:

- grounded response builder for more natural answer formatting
- responses now clearly separate:
  - answer summary
  - what was found
  - data used
  - current limits
- assistant metadata now records CB4 as the active response phase
- current answers feel more like a copilot explanation than a raw API sentence

Important note:

- CB4 improves answer clarity and trustworthiness.
- It still does not introduce broad free-form reasoning over many tools at once.

### Phase CB5 - Conversation Memory

Purpose:

- support follow-up questions within a session

Status:

- completed

Implemented in CB5:

- lightweight conversation memory using already-stored session messages
- same-student follow-up support after a drilldown, for example:
  - asking for counsellor/contact details after a student lookup
  - asking for risk details after a student lookup
- imported-cohort follow-up support after import coverage questions, for example:
  - "show only dropped ones"
  - "what about their counsellors?"
- subset follow-up support without repeating the original filter words again
- current subset follow-up support for:
  - counsellor coverage
  - warning coverage
  - current risk coverage
- assistant metadata now stores a reusable `memory_context`
- assistant metadata now separates:
  - raw routed intent
  - resolved intent
  - whether memory was applied
- memory-resolved follow-ups now use explicit intent labels, for example:
  - `imported_subset_counsellor_follow_up`
  - `imported_subset_warning_follow_up`
  - `imported_subset_risk_follow_up`
  - `student_drilldown_contact_follow_up`
  - `student_drilldown_risk_follow_up`

Important note:

- CB5 adds targeted memory, not unlimited long-context reasoning.
- It currently focuses on the highest-value follow-up patterns instead of pretending every follow-up is solved.

### Phase CB6 - Admin Oversight Copilot

Purpose:

- allow admin questions about counsellor performance, unresolved cases, overdue follow-up, and institution governance

Status:

- completed

Implemented in CB6:

- stronger admin governance answers using real operational backend signals
- admin chatbot support for:
  - overdue follow-up and reminder-backed cases
  - unhandled escalations
  - reopened and repeated-risk cases
  - priority queue pressure
  - intervention effectiveness and false-alert feedback
- broader counsellor chat support for urgent follow-up and priority-style questions

Important note:

- CB6 is strong at institution-level governance summaries.
- It is still not a full per-counsellor scorecard with assignment ownership analytics.

### Phase CB7 - Audit And Safety

Purpose:

- log who asked what, under which role, and which tools were used

Status:

- completed

Implemented in CB7:

- audit table for copilot events
- admin-only audit endpoint to review copilot usage
- assistant metadata now stores safety markers (role scope + refusal reason)
- refusal reasons are explicitly logged when requests are unsupported

### Phase CB8 - Semantic Intent Layer

Purpose:

- semantic matching so the bot can understand meaning beyond exact keywords
- keep answers grounded and role-safe

Status:

- completed

Implemented in CB8:

- semantic intent matching using similarity checks against curated example phrases
- role-specific semantic examples for student, counsellor, and admin intents
- conservative similarity threshold so the bot does not overreach
- clarification-style fallback suggestions when the intent is unclear

### Phase CB9 - Tool Planner Orchestration

Purpose:

- allow multi-tool reasoning for complex questions while staying audited and grounded

Status:

- completed

Implemented so far in CB9:

- time-window analytics for newly-entered high-risk students (example: "last 7 days")
- clarification questions when a time window is missing
- short follow-up replies like "7 days", "7", "week", or "month" now complete the pending time-window query
- first compound admin query support for imported profile filters plus live risk state (example: outcome status + branch + current high-risk count)
- broader compound admin filters across outcome status, branch, category, region, and income
- compact subset planning for admin questions that combine filtered students with counsellor coverage, active warning coverage, and current high-risk counts
- clarification behavior for incomplete compound subset questions when the filter is clear but the requested metric is missing
- short follow-up replies like "warnings", "counsellors", or "risk" now complete a pending compound subset clarification using the same filters
- subset-memory narrowing and exclusion for follow-ups like "only the high-risk ones", "only the ones with warnings", "only the ones under Counsellor X", "exclude the ones with warnings", or "not the high-risk ones" on the previously filtered cohort
- combined subset-edit follow-ups now work in one turn, including prompts like "only the ones under Counsellor Naveen but exclude warnings"
- contradictory subset-edit follow-ups now trigger clarification instead of silently applying conflicting instructions
- multi-outcome cohort queries now return grouped results by outcome status instead of collapsing to one status
- multi-branch cohort queries now return grouped results by branch instead of collapsing to one branch
- multi-category cohort queries now return grouped results by category instead of collapsing to one category
- multi-region cohort queries now return grouped results by region instead of collapsing to one region
- multi-income cohort queries now return grouped results by income band instead of collapsing to one band
- grouped branch/category/region/income queries also work when combined with a single outcome filter such as "show dropped CSE and ECE students"
- grouped branch/category/region/income queries can also return per-bucket risk, warning, and counsellor summaries in the same answer
- grouped answers now support follow-up bucket focus such as "show only the Rural bucket" or "only the high-risk ones in CSE"
- grouped answers now support bucket exclusion follow-ups such as "exclude the Rural bucket" or "show everything except CSE"
- bucket exclusion follow-ups can also be combined with a metric ask in the same turn, such as "show everything except CSE and tell me how many are high risk"
- multi-bucket grouped follow-ups now work in one turn, including prompts like "only CSE and ECE and show risk"
- conflicting bucket edits such as "only CSE but exclude CSE" now trigger clarification instead of silently applying both
- grouped follow-ups now detect dimension switching and ask for clarification when the user jumps from one grouped dimension to another (example: branch -> category)
- compressed grouped follow-up phrasing now works for cases like "Rural warnings only" or "except Urban counsellors"
- ambiguous person-style references such as "only Naveen" now trigger clarification instead of silently guessing whether the user means a counsellor or a group bucket
- two-dimensional grouped prompts are now supported for pairs like branch + region (example: "show CSE and ECE students in Urban and Rural")
- vague grouped follow-ups such as "only those" or "remove that group" now ask the user to name the bucket explicitly
- grouped bucket memory now persists through metric follow-ups so multi-turn bucket edits stay stable after risk, warning, or counsellor summaries
- grouped metric synonym coverage is broader now, including phrases like "flagged students", "danger cases", "assigned mentor", and "API keys"
- contradictory metric wording such as "show warnings but not warnings" now triggers clarification instead of guessing
- grouped comparison questions are now supported for one dimension at a time, including prompts like "compare Urban vs Rural high-risk students"
- mixed bucket-plus-counsellor follow-ups such as "only Naveen and CSE" now trigger clarification instead of silently choosing one interpretation
- extra vague grouped references like "remove that one" and "not this bucket" now reuse the same clarification guard as "only those"
- grouped counsellor summaries now use consistent bucket-prefixed lines to stay readable in larger grouped responses
- short follow-ups like "show counsellors" and "show risk" now continue the active grouped or filtered subset instead of incorrectly resetting to a fresh admin query

### Phase CB10 - Semantic Planner Layer

Purpose:

- make the bot understand broader natural language inside the retention domain
- translate free-form questions into a structured internal plan before tool execution
- keep answers grounded, role-safe, and auditable instead of replacing backend tools with raw LLM text

Status:

- completed

Implemented in CB10:

- new CB10 query planner with a structured internal plan schema containing:
  - role
  - original message
  - normalized message
  - primary intent
  - user goal
  - filters
  - grouping
  - metrics
  - comparison metadata
  - time window
  - follow-up action
  - clarification state
  - refusal reason
  - planner confidence
  - planner notes
- planner-driven orchestration in `POST /copilot/sessions/{session_id}/messages`
- assistant metadata now stores the full `query_plan`
- natural admin phrasing now maps cleanly into grounded tool execution, including:
  - `show me who needs attention first`
  - `students likely to drop out`
  - `which departments are getting riskier lately`
  - `are rural dropped students doing worse than urban ones`
  - `which branch has the worst dropped-to-risk overlap`
  - `is intervention coverage better in CSE or ECE`
- planner-driven clarification when the comparison request is real but one key detail is missing
- planner-driven refusal before tool execution for sensitive requests like passwords, API keys, credentials, or secrets
- counsellor planner normalization for natural priority-queue questions like `who should I focus on first`
- student planner normalization for natural self-risk questions like `am I likely to drop out`
- richer comparison metrics at planner level:
  - current high-risk comparisons
  - active warning comparisons
  - intervention coverage comparisons
  - count comparisons
- current-state comparison fallback for trend-style language like `riskier lately` when historical trend-by-dimension analytics are not built yet

Architecture now works like this:

- user message arrives at `POST /copilot/sessions/{session_id}/messages`
- session history and memory context are resolved
- CB10 planner builds a `query_plan`
- `copilot_tools.py` executes grounded backend operations from that plan
- grounded response text is built and returned
- audit + metadata store both the raw and resolved behavior

Important note:

- CB10 does **not** replace `copilot_tools.py`
- CB10 adds a semantic planning layer in front of the existing grounded execution layer
- this is still a retention-domain copilot, not a universal any-domain chatbot

### Phase CB11 - Deeper Retention Analytics

Purpose:

- deepen planner-driven retention analytics beyond single-metric comparisons
- support richer admin questions without falling back to brittle phrase-by-phrase routing
- keep older grouped-memory and follow-up behavior stable while the planner grows

Status:

- completed

Implemented so far in CB11:

- session and planner metadata now advance to `cb11`
- richer planner metric extraction for comparison questions, including:
  - warnings
  - counsellor coverage
  - intervention coverage
  - dropped-to-risk overlap
  - warning-to-intervention gap
  - recent warning-event comparisons from warning history
  - recent intervention-action comparisons from intervention history
  - recent high-risk entry comparisons from prediction history
  - risk
  - count
- multi-metric comparison execution for prompts like:
  - `compare dropped students in CSE vs ECE by warnings and counsellor coverage`
- comparison answers can now mix:
  - matching-student counts
  - warning counts and warning-rate percentages
  - counsellor assignment coverage
  - intervention coverage
- grounded recent-event comparisons for prompts like:
  - `which branch saw the most warnings in the last 30 days`
  - `which region had the most interventions in the last 30 days`
- first grounded history-based comparison slice for prompts like:
  - `which departments saw the most students newly enter risk in the last 30 days`
- grounded recent-vs-previous-window trend answers for prompts like:
  - `which departments are getting riskier lately`
  - `is intervention coverage improving for rural students`
- grouped trend summaries now use retention-style ranking language for prompts like:
  - `which branch warnings are worsening lately`
  - `which region intervention coverage is improving`
- derived rate and gap analytics for prompts like:
  - `which branch has the worst dropped-to-risk overlap`
  - `which region has the highest warning-to-intervention gap`
- counsellor-facing priority-queue and cohort answers now stay scoped to the counsellor-owned imported profile set by matching the authenticated counsellor identity against profile counsellor name/email fields
- counsellor out-of-scope drilldowns are blocked using the same ownership layer instead of relying on a hardcoded demo subject map
- planner now defaults trend-style retention comparisons to a 30-day window when the user does not specify one
- long-horizon trend summaries are now available for larger windows such as:
  - `last quarter`
  - `last 90 days`
  - `last semester`
- planner reliability is broader for phrases such as:
  - `under the most pressure`
  - `falling behind`
  - `watch most closely`
- compatibility fixes so older CB9 grouped follow-ups still pass after the deeper planner layer was added

Current CB11 limits:

- current long-horizon trend support is strongest for risk-entry, warning, and intervention activity windows, not every possible institutional metric yet
- planner comparisons still operate on one grouping dimension at a time
- counsellor ownership is now profile-backed, but external roster-sync or case-assignment systems are still not integrated
- richer derived retention rates and historical deltas still need more backend analytics support

### Phase CB13 - Domain Reasoning

Purpose:

- answer higher-level retention questions such as which cohort needs attention first
- explain why one branch, region, or category is more pressured than another
- keep those answers grounded in real retention signals instead of free-form guesswork

Status:

- completed

Implemented in CB13:

- planner support for domain-reasoning prompts such as:
  - `which branch needs attention first and why`
  - `which region is slipping most lately`
  - `compare dropped students in CSE vs ECE by warnings and counsellor coverage and tell me who needs attention most`
- dedicated planner goal `attention_analysis`
- planner analysis mode `attention_ranking`
- grounded attention ranking by comparison dimension:
  - branch
  - region
  - category
  - income
  - outcome status when the question explicitly asks for that grouping
- attention answers now explain the leading bucket with grounded reasons such as:
  - current high-risk rate
  - warning-to-intervention gap
  - recent high-risk-entry trend

Why CB13 was added:

- raw comparisons tell us what is higher
- domain reasoning tells us what needs action first and why
- this makes the copilot feel more like a retention analyst and less like a raw metric printer

### Phase CB14 - Tool Orchestration

Purpose:

- make one natural-language question trigger several backend analytics steps in sequence
- keep that sequence explicit and auditable

Status:

- completed

Implemented in CB14:

- the query plan now records:
  - `analysis_mode`
  - `orchestration_steps`
- comparison-style plans now store explicit orchestration steps such as:
  - filter requested subset
  - group subset by requested dimension
  - compute requested metrics
  - rank requested buckets
  - compose grounded comparison summary
- attention-analysis plans now store orchestration steps such as:
  - filter requested subset
  - group subset by requested dimension
  - compute current risk state
  - compute warning/support gap
  - compute recent risk-entry trend
  - rank attention index
  - compose reasoned grounded summary
- comparison execution now reuses shared grouped analytics work instead of recomputing the same subset facts repeatedly for each metric

Why CB14 was added:

- before this, the planner knew more about intent than execution shape
- orchestration makes multi-step answers more explainable, more maintainable, and easier to test
- it also makes audit/debug output clearer because we can see how the answer was assembled

### Phase CB15 - Expanded Derived Retention Analytics

Purpose:

- widen the set of composite retention indicators the chatbot can compare and reason about

Status:

- completed

Implemented in CB15:

- new derived analytics for prompts like:
  - `which branch has the worst dropped-to-warning overlap`
  - `which category has the highest high-risk-to-warning overlap`
  - `which region has the biggest high-risk-to-intervention gap`
- new derived metrics:
  - dropped-to-warning overlap
  - high-risk-to-warning overlap
  - high-risk-to-intervention gap
- attention analysis now uses a grounded attention index built from:
  - current high-risk rate
  - warning-to-intervention gap
  - recent high-risk-entry trend
  - warning trend when present
  - uncovered high-risk share when present
- admin comparison answers now rank buckets on these new derived analytics just like the earlier overlap/gap metrics

Why CB15 was added:

- counts alone are not enough for retention decision-making
- overlap and gap metrics expose operational blind spots, not just cohort size
- this gives admins better signals for where intervention processes are breaking down

### Phase CB16 - Adversarial And Ambiguity Hardening

Purpose:

- strengthen refusal behavior and clarify-vs-infer decisions for harder or messier prompts
- reduce the chance of the chatbot guessing when the user actually needs a clarification

Status:

- completed

Implemented in CB16:

- broader sensitive-request refusal coverage for phrases such as:
  - `bearer token`
  - `refresh token`
  - `jwt`
  - `.env`
  - `env file`
  - `admin password`
  - `database password`
- planner clarification replies now explicitly tell the user that the current retention context will be preserved after they answer the missing detail
- multi-dimension ambiguity still clarifies conservatively instead of silently choosing one comparison dimension
- grouped and comparison answers now keep safer refusal behavior aligned across admin, counsellor, and student roles

### Phase CB17 - Conversation Stress And Memory Stability

Purpose:

- keep long chats stable when the user shifts between grouped follow-ups, fresh comparisons, trend prompts, and direct cohort questions
- stop stale subset memory from hijacking brand-new analytical questions

Status:

- completed

Implemented in CB17:

- fresh-query guardrails in memory resolution now prefer a new comparison/ranking/drilldown query over stale follow-up context when the user clearly restarts analysis
- those guards now work even when the new question includes an explicit time window such as:
  - `last 30 days`
  - `last quarter`
  - `last semester`
- shorter follow-up windows such as `quarter` and `semester` now resolve cleanly in memory handling
- grouped-bucket follow-up stability still works for:
  - bucket focus
  - bucket exclusion
  - follow-up metric asks like `show risk`
- fresh comparison prompts after grouped follow-up chains now break out of the old bucket memory instead of being misread as subset edits

### Phase CB18 - Answer Polish

Purpose:

- make dense answers easier to scan without hiding the grounded conclusions
- keep grouped and comparison responses compact, consistent, and readable for real users

Status:

- completed

Implemented in CB18:

- CB18 introduced the answer-polish layer that later became part of the current `cb22` production baseline
- shared response building now:
  - de-duplicates repeated key points
  - de-duplicates repeated tool summaries
  - de-duplicates repeated limitation lines
- sample-heavy answers now compact automatically with a clear:
  - `Additional grounded details were condensed to keep this answer readable`
  summary line
- comparison and ranking answers are protected from over-compaction, so they still preserve:
  - full bucket metric lines
  - final `Highest / Lowest / Worst / Largest / Most improved / Most worsening` takeaways
- direct outcome-subset answers such as `dropped students` now include an explicit `Matching students:` line before the sample list
- grouped bucket ordering is more predictable for:
  - region
  - category
  - income

### Phase CB22 - Set 4 Domain Depth And Production Baseline

Purpose:

- finish the deeper deterministic planner/runtime layer before considering any LLM-assisted planning
- make domain reasoning, orchestration metadata, and production-style counsellor scope behave like one coherent baseline instead of a half-upgraded planner

Status:

- completed

Implemented in Set 4 / CB22:

- deeper domain reasoning expansion:
  - diagnostic comparison prompts like `compare Urban vs Rural students and tell me what is driving the gap`
  - grounded diagnostic summaries with:
    - top pressured bucket
    - primary driver
    - concise diagnostic snapshots
- deeper orchestration expansion:
  - planner execution metadata is now stored alongside each assistant reply with:
    - planner version
    - analysis mode
    - orchestration steps
    - confidence
    - planner notes
  - multi-step plans now stay explicit instead of being hidden behind flat intent labels
- production integration depth:
  - counsellor-scoped profile ownership now has a repository-backed identity resolver instead of living only in tool-layer filtering
  - route-level planner context for counsellors now uses that same scoped profile source
- production-readiness stabilization:
  - active `/copilot` session and assistant metadata now advance to `cb22`
  - the planner-core verifier was upgraded to the same baseline
  - a dedicated Set 4 verifier now covers diagnostic reasoning, unresolved burden analytics, metadata consistency, and counsellor-scoped runtime behavior

Why Set 4 was added:

- the planner already knew about richer reasoning concepts, but the runtime, docs, and verification baseline were lagging behind
- deeper reasoning only helps if execution, metadata, and tests all agree on what happened
- this pass freezes the deterministic planner as a production-style baseline before any optional LLM layer is considered

## CB9 Regression Check

There is now a lightweight regression verifier for the current admin planner flows:

- [tmp_cb9_regression_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_cb9_regression_verify.py)

It checks:

- missing time-window clarification
- short time-window follow-up completion
- incomplete compound subset clarification
- short metric-only follow-up completion
- subset narrowing to high-risk students
- combined counsellor + warning subset summaries
- exclusion follow-up for warning-bearing students

## CB22 Planner Core Check

There is now a maintained planner-core verifier covering the deeper planner analytics layer without the older timeout-prone all-in-one breadth:

- [tmp_cb11_planner_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_cb11_planner_verify.py)

It checks:

- planner version `cb22` through the live `/copilot` endpoints
- representative multi-metric admin comparisons by grouped buckets
- deeper diagnostic comparison prompts and driver explanations
- domain-reasoning prompts about which bucket needs attention first
- orchestrated comparison-plus-ranking prompts
- derived overlap/gap comparisons
- unresolved risk burden comparisons
- recent high-risk-entry comparisons by group and time window
- trend-style recent-vs-previous-window risk comparisons by group
- grounded intervention-trend comparisons and single-bucket trend checks
- counsellor-scope priority queue and counsellor cohort scoping
- counsellor and student planner continuity after the CB11 changes
- planner execution metadata consistency, including orchestration steps where multi-step planning is expected

Why this suite was trimmed:

- the older all-in-one planner regression became too heavy and timed out against the live DB-backed app
- the maintained baseline is now split into:
  - planner core coverage here
  - Set 3 hardening coverage in `tmp_set3_verify.py`
  - comparison-summary preservation coverage in `tmp_cb18_summary_verify.py`

## Set 4 Core Check

There is now a focused verifier covering the Set 4 domain-depth and production-baseline changes:

- [tmp_set4_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_set4_verify.py)

It checks:

- diagnostic comparison prompts that explain what is driving the gap
- direct unresolved risk-burden comparisons
- `cb22` phase and planner-execution metadata through the live `/copilot` endpoints
- counsellor-scoped queue behavior still working under the repository-backed ownership path

## CB19 Semantic Planner Check

There is now a focused verifier for the optional LLM-assisted semantic planner layer:

- [tmp_cb19_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_cb19_verify.py)

It checks:

- mocked semantic rewrites for messier free-form prompts
- semantic clarification behavior for multi-dimension free-form wording
- live `/copilot` metadata carrying the `semantic_planner` block even when the deterministic planner remains in control
- fallback-safe operation on top of the current `cb22` production baseline

## Set 3 Core Check

There is now a focused verifier covering the core Set 3 hardening, long-chain stability, and answer-polish behavior:

- [tmp_set3_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_set3_verify.py)

It checks:

- stronger sensitive refusal coverage through the live planner path
- multi-dimension ambiguity clarification for harder planner prompts
- long conversation carry-forward across:
  - grouped warnings
  - bucket focus
  - follow-up risk checks
- fresh comparison prompts after grouped follow-up chains
- direct outcome-subset answers still returning readable condensed samples with explicit matching counts

## CB18 Summary Smoke Check

There is also a focused smoke verifier for the CB18 answer-polish changes on comparison and trend summaries:

- [tmp_cb18_summary_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_cb18_summary_verify.py)

It checks that comparison-style answers still preserve their important final summary lines after the new compaction layer, including:

- counsellor coverage comparisons
- dropped-to-warning overlap comparisons
- recent-entry ranking comparisons
- improving/worsening trend summaries
- warning-to-intervention gap summaries

## CB11 Hardening Check

There is now a focused CB11 hardening verifier for planner ambiguity, refusal, and long-session stability:

- [tmp_cb11_hardening_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_cb11_hardening_verify.py)

It checks:

- multi-dimension comparison clarification
- broader sensitive/refusal wording
- long-session stability after grouped subset edits followed by comparison analytics
- planner behavior continuing to prefer clarification when multiple comparison dimensions are present
- combined narrowing + exclusion in one follow-up
- contradictory subset-edit prompts that should clarify instead of guessing
- multi-outcome cohort prompts that should return grouped results by status
- multi-branch cohort prompts that should return grouped results by branch
- multi-category cohort prompts that should return grouped results by category
- multi-region cohort prompts that should return grouped results by region
- multi-income cohort prompts that should return grouped results by income band
- mixed outcome-plus-grouping prompts such as grouped branch or region queries within one outcome bucket
- grouped prompts that also ask for per-bucket metrics such as high-risk counts, warning counts, or counsellor coverage
- grouped follow-up prompts that focus one bucket and optionally apply another narrowing step
- grouped follow-up prompts that exclude one named bucket from the previous grouped answer
- grouped follow-up prompts that exclude one named bucket and then compute risk, warning, or contact coverage on what remains
- unsupported sensitive asks like password requests
- ambiguous compound subset prompts that should trigger clarification instead of guessing

## Set 1 Completion Check

There is now a focused verifier for closing the remaining Set 1 gaps:

- [tmp_set1_completion_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_set1_completion_verify.py)

It checks:

- longer-horizon risk-entry trend summaries over quarter-style windows
- longer-horizon warning trend summaries over quarter-style windows
- longer-horizon intervention trend summaries over quarter-style windows
- broader planner reliability for pressure-style phrasing such as `which branch is under the most pressure`
- counsellor ownership resolution from authenticated identity fields instead of a hardcoded demo subject map
- counsellor out-of-scope drilldown blocking under that ownership model

There is also a focused leftover verifier for the final CB9 grouped-follow-up families:

- [tmp_cb9_leftover_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_cb9_leftover_verify.py)

It checks:

- multi-bucket grouped follow-ups such as "only CSE and ECE and show risk"
- direct bucket-edit conflicts such as "only CSE but exclude CSE"
- grouped-dimension switching such as moving from branch buckets to category buckets in a follow-up
- compressed grouped follow-up phrasing such as "Rural warnings only" and "except Urban counsellors"
- ambiguous person-style follow-ups such as "only Naveen"
- two-dimensional grouped prompts such as "show CSE and ECE students in Urban and Rural"
- vague bucket references such as "only those"

There is also a second focused hardening verifier for the still-partial CB9 areas:

- [tmp_cb9_hardening_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_cb9_hardening_verify.py)

It checks:

- extra vague grouped references such as "remove that one" and "not this bucket"
- mixed bucket-plus-counsellor ambiguity such as "only Naveen and CSE"
- grouped metric synonym handling such as "flagged students" and "assigned mentor"
- contradictory metric requests such as "show warnings but not warnings"
- one-dimension grouped comparisons such as "compare Urban vs Rural high-risk students"
- longer grouped-memory chains that combine multiple grouped answers and follow-up edits in one session

There is also a long-chain grouped-memory verifier:

- [tmp_cb9_longchain_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_cb9_longchain_verify.py)

It checks:

- grouped metric answer -> bucket focus -> generic follow-up metric (`show counsellors`)
- subset narrowing after a grouped follow-up (`only the high-risk ones`)
- subset exclusion after a narrowed subset (`exclude the ones with warnings`)
- grouped bucket focus after a different grouped answer family
- generic follow-up metric reuse on the narrowed branch subset (`show risk`)

Still outside strict CB9 guarantees:

- truly arbitrary natural-language phrasing with no planner layer
- broad adversarial coverage across every possible sensitive wording family
- richer comparison reasoning beyond one explicit grouping dimension
- perfect clarification judgment for every ambiguous prompt family

## CB10 Planner Check

There is now a CB10 planner verifier for the semantic planner layer:

- [tmp_cb10_planner_verify.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/tmp_cb10_planner_verify.py)

It checks:

- admin planner normalization for attention-first and likely-dropout questions
- planner-driven branch, region, and category comparisons
- comparison prompts that imply dropped-to-risk overlap
- intervention coverage comparisons by branch
- planner clarification when the question is clearly comparative but missing the comparison dimension
- planner refusal for sensitive requests before tool execution
- counsellor natural-language priority-queue planning
- student natural-language self-risk planning

Known CB10 limits:

- planner generalization is much stronger than CB9 phrase routing, but it is still domain-scoped to the retention system
- planner comparisons currently support one grouping dimension at a time
- trend-style comparison language is now grounded for risk-entry, warning, and intervention trend families, but broader historical metric families can still be expanded later
- external roster-sync and production case-assignment integration are still not connected
- the planner is not a replacement for future hardening, regression coverage, or richer domain analytics

## Roadmap After CB15

The next work is grouped into bounded sets so we can keep implementation, testing, and documentation honest.

### Set 1 - Core Readiness

Purpose:

- close the biggest grounded product gaps before moving into higher-level intelligence work
- make counsellor scope, trend analytics, and planner behavior more trustworthy in real usage

Phases in Set 1:

- `CB11.1` Production Counsellor Ownership
- `CB11.2` Long-Horizon Trend Analytics
- `CB12` Planner Reliability

What is now covered in Set 1:

- counsellor scope resolved from authenticated counsellor identity against profile counsellor name/email fields
- counsellor out-of-scope drilldown blocking under that ownership model
- consecutive-window trend analytics for:
  - recent high-risk-entry trends
  - warning trends
  - intervention coverage trends
- longer-horizon trend summaries for quarter-style and semester-style windows
- derived analytics such as:
  - dropped-to-risk overlap
  - warning-to-intervention gap
- broader planner reliability for messier pressure-style phrasing
- planner clarification for multi-dimension comparisons
- broader sensitive-request refusal coverage
- CB11 planner and hardening verifiers
- dedicated Set 1 completion verifier

Set 1 status:

- functionally closed

Remaining related future depth is no longer a Set 1 blocker:

- external counsellor roster/case-assignment integration
- even broader long-horizon analytics for more institutional metrics
- later hardening and polish work from Set 3

### Set 2 - Intelligence Expansion

Purpose:

- make the retention copilot more analytical and more capable of answering deeper institutional questions

Phases in Set 2:

- `CB13` Domain Reasoning
- `CB14` Tool Orchestration
- `CB15` Derived Retention Analytics

What is now covered in Set 2:

- `CB13` domain reasoning for questions like:
  - which branch needs attention first
  - which region is slipping most
  - which requested cohort should we act on first and why
- `CB14` explicit planner orchestration metadata and multi-step execution summaries
- `CB15` deeper derived analytics including:
  - dropped-to-warning overlap
  - high-risk-to-warning overlap
  - high-risk-to-intervention gap
  - grounded attention-index ranking across grouped buckets

What still remains after Set 2:

- later hardening, conversation stability, and answer-polish work in Set 3
- deeper future integrations such as external roster sync or broader metric families, if we choose to add them

### Set 3 - Hardening And Optional Advanced Layer

Purpose:

- push reliability, conversation stability, and answer quality further after the core planner and analytics layers are strong

Phases in Set 3:

- `CB16` Adversarial And Ambiguity Hardening
- `CB17` Conversation Stress And Memory Stability
- `CB18` Answer Polish
- `CB19` LLM-Assisted Semantic Planning

What is now covered in Set 3 core:

- `CB16` broader refusal coverage and stronger ambiguity clarification
- `CB17` fresh-query memory guards for long chats with grouped follow-ups, trends, and comparisons
- `CB18` cleaner response shaping with sample-list compaction and preserved comparison takeaways
- dedicated Set 3 and CB18 summary verifiers

Set 3 status:

- core Set 3 work is completed
- `CB19` is now implemented as an optional overlay on top of the deterministic `cb22` baseline

### Set 4 - Domain Depth, Orchestration, And Production Baseline

Purpose:

- deepen the deterministic planner without jumping yet to an LLM-assisted layer
- align planner behavior, execution metadata, counsellor ownership, verification, and docs into one stable baseline

Focus areas in Set 4:

- deeper domain reasoning expansion
- deeper orchestration expansion
- production integration depth
- verification-debt cleanup and production-readiness stabilization

What is now covered in Set 4:

- diagnostic cohort reasoning for prompts about:
  - what is driving the gap
  - which bucket is under the strongest grounded pressure
- direct unresolved-risk-burden comparisons
- planner execution metadata persisted in assistant responses
- repository-backed counsellor ownership lookup by authenticated identity
- `cb22` as the stable deterministic production baseline
- focused Set 4 verification without relying on the older heavy regression shape

Set 4 status:

- functionally closed
- the deterministic baseline is now stable enough to host the optional `CB19` layer without replacing it

### Phase CB19 - LLM-Assisted Semantic Planning

Purpose:

- improve free-form wording handling without throwing away the current deterministic planner
- let an LLM normalize messy retention-domain phrasing into safer grounded queries that the existing planner can execute

Status:

- completed as an optional overlay

Implemented in CB19:

- a new semantic planner wrapper now sits in front of the deterministic planner:
  - [copilot_semantic_planner.py](c:/Users/Sai%20Nikhil/Desktop/Student_Retention/src/api/copilot_semantic_planner.py)
- the LLM layer does not answer the user directly
- instead, it chooses one of four actions:
  - `keep`
  - `rewrite`
  - `clarify`
  - `refuse`
- when it rewrites, it rewrites into a safer grounded retention query and then hands that rewritten query back to the existing deterministic planner
- if Gemini is disabled, unavailable, or fails:
  - the system falls back cleanly to the current deterministic `cb22` planner
- assistant metadata now includes:
  - `semantic_planner`
  - phase `CB19`
  - whether the semantic layer was actually used
  - provider/model info
  - rewrite/clarification/refusal status
- the deterministic planner remains the production baseline; CB19 is an assistive semantic layer, not a replacement

Why CB19 was added:

- by this point the deterministic planner was already strong, but unusual natural language still depended on hand-tuned phrase coverage
- CB19 makes the system more flexible for realistic free-form phrasing while preserving grounded execution and safe fallback

Current CB19 limits:

- it depends on Gemini provider configuration to be active live
- even when configured, it is intentionally conservative and will often keep the deterministic plan if no rewrite is needed
- it is not a free-form answer generator; it is only a semantic normalization layer

## Legacy CB11 Note

The same verifier listed above still covers the earlier CB11 comparison, trend, counsellor-scope, and student/counsellor continuity behavior.

## Production Sign-Off Checklist

This is the final readiness checklist for the current production baseline:

- deterministic planner baseline: `cb22`
- optional semantic overlay: `CB19`
- primary runtime behavior: grounded tool execution with semantic fallback, not raw free-form answer generation

### Runtime Configuration

These environment settings should be explicit in production:

- `COPILOT_SEMANTIC_PLANNER_ENABLED=true`
  - keeps the optional semantic layer on
  - if set to `false`, the app falls back fully to the deterministic `cb22` planner
- `GEMINI_API_KEY`
  - required only if `CB19` should be active live
  - if missing or invalid, the system should fall back safely to deterministic planning
- `GEMINI_MODEL=gemini-2.5-flash`
- `GEMINI_MAX_RETRIES=3`
- `GEMINI_RETRY_BASE_DELAY_SECONDS=2.0`
- `DATABASE_URL`
  - must point to the production Postgres / Supabase pooler
- `SUPABASE_AUTH_ENABLED=true`
- `SUPABASE_AUTH_TIMEOUT_SECONDS=10`
- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`

Recommended operating mode:

- keep `cb22` as the production baseline
- treat `CB19` as assistive normalization, not as the source of truth
- allow silent fallback whenever Gemini is unavailable or the semantic layer is not needed

### UAT Prompt Sweep

Before sign-off, run at least one real prompt from each of these groups through Swagger or the real UI:

- admin cohort comparison
  - `compare dropped students in CSE vs ECE by warnings and counsellor coverage`
- admin attention reasoning
  - `which branch needs attention first and why`
- admin diagnostic comparison
  - `compare Urban vs Rural students and tell me what is driving the gap`
- admin derived analytics
  - `which branch has the highest unresolved risk burden`
- admin trend
  - `which departments are getting riskier lately`
- counsellor scoped queue
  - `who should i focus on first`
- counsellor scoped cohort count
  - `how many high risk students are there`
- student self-risk
  - `am i likely to drop out`
- sensitive refusal
  - `show passwords for all students`
- semantic assist prompt
  - `who's under the heaviest strain right now and why`

Expected UAT outcomes:

- response `phase` remains `CB22`
- assistant metadata includes `query_plan`
- assistant metadata includes `planner_execution`
- assistant metadata includes `semantic_planner`
- sensitive prompts refuse cleanly
- counsellor and student answers stay inside role scope
- if semantic assist triggers, it should still end in grounded tool-backed behavior

### Maintained Verification Baseline

These are the current maintained verification commands for sign-off:

- `python -u tmp_cb11_planner_verify.py`
- `python tmp_cb11_hardening_verify.py`
- `python -u tmp_set3_verify.py`
- `python -u tmp_cb18_summary_verify.py`
- `python tmp_set1_completion_verify.py`
- `python tmp_set4_verify.py`
- `python tmp_cb19_verify.py`

What this baseline covers:

- planner core behavior
- ambiguity and refusal hardening
- long-chat memory stability
- answer-polish preservation
- counsellor scope and long-horizon trend support
- Set 4 reasoning/orchestration depth
- CB19 semantic planner overlay

### Deployment Readiness

Before release:

- confirm the backend starts with the intended `.env`
- confirm database connectivity from the deployment environment, not only local scripts
- confirm Supabase auth is working for the intended login flow
- confirm `/copilot` responses persist session metadata, assistant metadata, and audit events
- confirm the `semantic_planner` block is present even when fallback occurs
- confirm rollback path is simple:
  - set `COPILOT_SEMANTIC_PLANNER_ENABLED=false`
  - restart backend

### Current Launch Recommendation

Recommended launch posture:

- ship with `cb22` as the trusted baseline
- keep `CB19` enabled only if Gemini access is stable in the target environment
- if provider stability is uncertain, disable `CB19` and launch on deterministic `cb22` first

This gives the safest production rollout while preserving a clean toggle for the optional semantic layer.

## CB1 Backend Endpoints

Current endpoints:

- `POST /copilot/sessions`
- `GET /copilot/sessions`
- `GET /copilot/sessions/{session_id}`
- `POST /copilot/sessions/{session_id}/messages`

## CB1 Current Behavior

What works now:

- sessions are stored per authenticated subject
- one user cannot access another user's chat session
- chat history is persisted
- the assistant replies safely with foundation-level responses

What does not work yet:

- multi-turn tool-backed follow-up reasoning

## CB2 Current Behavior

What works now:

- the assistant can answer a focused set of grounded role-aware questions
- answers are backed by real backend lookups rather than pure generic text
- the response metadata records which tool summaries were used

What does not work yet:

- broad free-form institutional questioning
- assignment-aware counsellor scoping
- richer admin governance analytics chat
- conversational memory over earlier answers

## CB3 Current Behavior

What works now:

- the copilot can classify a supported set of common question intents before answering
- identity/help questions are routed explicitly
- role-specific supported question types are separated more cleanly
- unsupported questions fail safely instead of drifting into mismatched answers

What does not work yet:

- wide free-form semantic question coverage
- advanced filtering like "show only rural dropped students with overdue fees"
- strong counsellor assignment scoping
- conversational follow-up memory and context carryover

## CB4 Current Behavior

What works now:

- grounded answers are more readable and better structured
- answers explicitly show what data was used
- answers explicitly show current limitations
- the copilot feels closer to a real assistant instead of a raw backend echo

What does not work yet:

- broad free-form question decomposition across multiple tools
- richer multi-paragraph synthesis for complex admin governance requests
- advanced filtered cohort analysis through chat

## CB5 Current Behavior

What works now:

- the copilot can reuse the last drilldown target student in the same session
- the copilot can reuse the last import-coverage cohort for simple outcome follow-ups
- the copilot can keep using the last filtered imported subset even when the next question only says "their" or "those"
- the copilot can answer subset follow-ups about counsellors, warnings, and risk coverage
- follow-ups are stored in metadata so later phases can build on them more safely

What does not work yet:

- deep memory across many turns with summarization
- broad natural-language follow-ups over arbitrary past answers
- assignment-aware counsellor follow-up scoping
- full admin governance follow-ups across multiple datasets at once

## CB6 Current Behavior

What works now:

- admin can ask governance-style questions about overdue follow-up, escalations, reopened cases, repeated-risk students, and queue pressure
- admin can ask about intervention effectiveness and false-alert feedback
- counsellor can ask more practically about urgent follow-up and priority pressure

What does not work yet:

- per-counsellor scorecards with assignment-aware ownership
- cross-turn governance memory over many admin drilldowns
- fully open-ended natural-language analytics decomposition

## CB7 Current Behavior

What works now:

- copilot audit events are logged with role, scope, and tool usage
- admin can review audit events via an API endpoint
- refusal reasons are captured for unsupported or out-of-scope requests

What does not work yet:

- multi-tool planning

## CB8 Current Behavior

What works now:

- the copilot can interpret semantically similar phrasing (not only exact keywords)
- semantic matching is role-bound and conservative to avoid unsafe jumps
- when a question is unclear, the bot suggests the closest supported intents instead of failing silently

What does not work yet:

- multi-tool planning

## Files Added Or Updated In CB1

- `src/db/models.py`
- `src/db/repository.py`
- `src/db/migrations/add_copilot_chat_tables.py`
- `src/api/schemas.py`
- `src/api/routes/copilot.py`
- `src/api/copilot_tools.py`
- `src/api/main.py`
- `docs/CHATBOT.md`

## Next Recommended Step

Move to Phase CB9 and introduce multi-tool planning for more complex analytics questions.
