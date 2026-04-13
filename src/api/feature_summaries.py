from __future__ import annotations

from collections.abc import Sequence


def build_lms_summary_from_events(lms_events: Sequence) -> dict:
    if not lms_events:
        raise ValueError("No LMS events found for student.")

    latest_lms_day = max(event.event_date for event in lms_events)
    lms_clicks_7d = sum(
        event.sum_click for event in lms_events if event.event_date >= latest_lms_day - 6
    )
    lms_clicks_14d = sum(
        event.sum_click for event in lms_events if event.event_date >= latest_lms_day - 13
    )
    lms_clicks_30d = sum(
        event.sum_click for event in lms_events if event.event_date >= latest_lms_day - 29
    )
    lms_unique_resources_7d = len(
        {
            event.id_site
            for event in lms_events
            if event.event_date >= latest_lms_day - 6
        }
    )
    prior_7d_clicks = max(lms_clicks_14d - lms_clicks_7d, 0)
    low_engagement_count_7d = 0
    resource_type_counts_7d: dict[str, int] = {}
    for event in lms_events:
        if event.event_date < latest_lms_day - 6:
            continue
        context = getattr(event, "context_fields", None) or {}
        engagement_tag = str(context.get("engagement_tag") or "").strip().lower()
        if engagement_tag == "low":
            low_engagement_count_7d += 1
        resource_type = str(context.get("resource_type") or "").strip()
        if resource_type:
            resource_type_counts_7d[resource_type] = resource_type_counts_7d.get(resource_type, 0) + 1
    percent_change = (
        (lms_clicks_7d - prior_7d_clicks) / prior_7d_clicks
        if prior_7d_clicks > 0
        else (1.0 if lms_clicks_7d > 0 else 0.0)
    )

    return {
        "lms_clicks_7d": float(lms_clicks_7d),
        "lms_clicks_14d": float(lms_clicks_14d),
        "lms_clicks_30d": float(lms_clicks_30d),
        "lms_unique_resources_7d": float(lms_unique_resources_7d),
        "days_since_last_lms_activity": 0.0,
        "lms_7d_vs_14d_percent_change": float(percent_change),
        "engagement_acceleration": float(lms_clicks_7d - prior_7d_clicks),
        "low_engagement_events_7d": float(low_engagement_count_7d),
        "resource_type_counts_7d": resource_type_counts_7d,
    }


def build_erp_summary_from_event(erp_event) -> dict:
    if erp_event is None:
        raise ValueError("No ERP event found for student.")

    return {
        "assessment_submission_rate": float(erp_event.assessment_submission_rate or 0.0),
        "weighted_assessment_score": float(erp_event.weighted_assessment_score or 0.0),
        "late_submission_count": float(erp_event.late_submission_count or 0.0),
        "total_assessments_completed": float(erp_event.total_assessments_completed or 0.0),
        "assessment_score_trend": float(erp_event.assessment_score_trend or 0.0),
        "cgpa": float((getattr(erp_event, "context_fields", None) or {}).get("cgpa") or 0.0),
        "backlog_count": float((getattr(erp_event, "context_fields", None) or {}).get("backlog_count") or 0.0),
    }
