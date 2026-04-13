# Report Index

This file explains what each report in the project means and whether it is:

- a temporal evaluation report
- a dataset diagnostic report
- a production artifact diagnostic report

## 1. Temporal Evaluation Reports

These reports are based on the temporal split strategy used for model selection and threshold selection.

Temporal split definition:

- train on past presentations: `2013B`, `2013J`
- validate/test on future presentations: `2014B`, `2014J`

### `models/reports/model_comparison_results.json`

Type:

- temporal evaluation report

Purpose:

- compares all candidate models under temporal split
- used to decide which model generalizes best to future data

Current role:

- supports champion model selection

### `models/reports/temporal_split_evaluation.json`

Type:

- temporal evaluation report

Purpose:

- provides explicit temporal split performance for all candidate models
- confirms deployment realism

Current role:

- core validation report for model quality under future-data simulation

### `models/reports/threshold_analysis.json`

Type:

- temporal evaluation report

Purpose:

- tests multiple classification thresholds using the temporal validation setup
- supports final threshold selection for the champion model

Current role:

- supports threshold decision in `models/metadata/model_config.json`

## 2. Dataset Diagnostic Reports

These reports analyze the processed dataset itself.

They do not depend on train/test split style.

### `models/reports/feature_relationships_report.txt`

Type:

- dataset diagnostic report

Purpose:

- shows correlation relationships between engineered numerical features
- helps identify redundancy and feature interactions

### `models/reports/outlier_analysis_report.txt`

Type:

- dataset diagnostic report

Purpose:

- analyzes numerical feature ranges and skew/outlier behavior
- helps decide whether special preprocessing is needed

## 3. Production Artifact Diagnostic Reports

These reports are based on the saved final model artifacts or final model registry.

They are not temporal split reports, but they are still valid and important.

### `models/reports/feature_importance_report.txt`

Type:

- production artifact diagnostic report

Purpose:

- explains which features matter most in the saved champion artifact

Important note:

- this report is generated from the final champion model trained on the full dataset after temporal validation
- so it is aligned with the final production model, not with a validation split

### `models/reports/inference_test_results.json`

Type:

- production artifact diagnostic report

Purpose:

- verifies that all saved model artifacts can load and run inference correctly
- checks champion/challenger prediction flow

Important note:

- this is a smoke test for production readiness
- it is not a temporal evaluation report

## 4. Source Of Truth Files

These are not reports, but they define the official production ML decisions.

### `models/metadata/model_config.json`

Defines:

- champion model
- production threshold
- evaluation type

### `models/metadata/model_registry.json`

Defines:

- artifact paths
- metadata paths
- champion/challenger status
- training scope

## 5. Current Final ML Decision

Current production-aligned decision:

- champion model: `gradient_boosting`
- threshold: `0.55`
- evaluation type: `temporal_split`

This means:

- temporal reports are used for model and threshold selection
- final saved artifacts are trained on the full dataset after temporal validation

## 6. Current System Workflow Document

### `docs/LIVE_SYSTEM_WORKFLOW.md`

Type:

- operational system workflow document

Purpose:

- explains how the current backend behaves end to end
- documents automated scoring, deduplication-aware ingestion, Gemini/fallback reasoning, student-first warning, recovery window handling, faculty escalation, per-student faculty routing, intervention tracking, asynchronous email sending with retry tracking, attendance-aware recovery interpretation, follow-up reminders, faculty queue/summary behavior, and time-based monitoring

Current role:

- primary explanation document for the live production-style workflow

## 7. Data Import Guide

### `docs/VIGNAN_IMPORT_GUIDE.md`

Type:

- operational data import guide

Purpose:

- documents the production-style CSV/Excel ingestion flow for Vignan datasets
- lists required sheets/columns and admin import endpoint usage

## 8. Backend Signoff

### `docs/BACKEND_SIGNOFF_2026-04-12.md`

Type:

- backend milestone signoff document

Purpose:

- records the verified backend state after Vignan import hardening
- summarizes what was tested, what is ready, and what remains intentionally deferred

## 9. Chatbot Build Guide

### `docs/CHATBOT.md`

Type:

- feature build guide

Purpose:

- tracks the RetainAI Copilot implementation phase by phase
- explains what is already implemented versus what is planned next

Important note:

- this is the best file for phase/status tracking
- it is not the deepest beginner explanation of hidden internal chatbot behavior

## 10. Full Chatbot Implementation Guide

### `docs/CHATBOT_FULL_IMPLEMENTATION_GUIDE.md`

Type:

- deep implementation walkthrough

Purpose:

- explains the full chatbot journey from `CB1` to `CB19`
- explains the request lifecycle from API call to grounded answer
- explains why each phase existed
- explains major edge-case families and why they were fixed in specific layers
- helps a beginner understand how the chatbot could be rebuilt manually

When to use it:

- when you want to understand the chatbot deeply, not just see status labels
- when you want to understand hidden internal flow that is not obvious from UI behavior
- when you want a beginner-friendly explanation of planner, memory, tools, and semantic assist

## 11. Chatbot Frontend Integration Guide

### `docs/CHATBOT_FRONTEND_INTEGRATION_GUIDE.md`

Type:

- frontend integration contract

Purpose:

- freezes the chatbot backend contract before frontend work
- documents:
  - endpoints
  - response shapes
  - frontend-safe metadata fields
  - clarification/refusal handling
  - UAT prompt sheet
  - launch assumptions for frontend

When to use it:

- before designing or building the chatbot UI
- when deciding which backend fields are safe to depend on in frontend
- when validating frontend behavior during UAT
