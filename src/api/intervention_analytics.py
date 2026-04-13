from collections import defaultdict


def build_intervention_effectiveness_summary(rows: list) -> dict:
    total_actions = len(rows)
    reviewed_rows = [row for row in rows if row.reviewed_at is not None or row.alert_validity]
    false_alert_rows = [
        row for row in rows if str(getattr(row, "alert_validity", "")).strip().lower() == "false_alert"
    ]
    valid_alert_rows = [
        row for row in rows if str(getattr(row, "alert_validity", "")).strip().lower() == "valid_alert"
    ]
    outcome_rows = [row for row in rows if getattr(row, "outcome_recorded_at", None) is not None or row.outcome_status]
    improved_rows = [
        row for row in rows if str(getattr(row, "outcome_status", "")).strip().lower() == "improved"
    ]
    unresolved_rows = [
        row for row in rows if str(getattr(row, "outcome_status", "")).strip().lower() == "unresolved"
    ]

    action_groups: dict[str, list] = defaultdict(list)
    for row in rows:
        action_groups[str(row.action_status).strip().lower()].append(row)

    action_effectiveness: list[dict] = []
    for action_status, action_rows in sorted(action_groups.items()):
        action_total = len(action_rows)
        action_reviewed = sum(1 for row in action_rows if row.reviewed_at is not None or row.alert_validity)
        action_false_alerts = sum(
            1
            for row in action_rows
            if str(getattr(row, "alert_validity", "")).strip().lower() == "false_alert"
        )
        action_outcomes = [row for row in action_rows if row.outcome_recorded_at is not None or row.outcome_status]
        action_improved = sum(
            1
            for row in action_rows
            if str(getattr(row, "outcome_status", "")).strip().lower() == "improved"
        )
        action_unresolved = sum(
            1
            for row in action_rows
            if str(getattr(row, "outcome_status", "")).strip().lower() == "unresolved"
        )

        review_rate = round((action_reviewed / action_total) * 100, 1) if action_total else 0.0
        effectiveness_score = round((action_improved / action_total) * 100, 1) if action_total else 0.0
        false_alert_rate = round((action_false_alerts / action_total) * 100, 1) if action_total else 0.0

        if action_improved and action_false_alerts == 0:
            summary = "This intervention type is showing positive recorded outcomes without false-alert feedback."
        elif action_false_alerts:
            summary = "This intervention type has false-alert feedback and should be reviewed before scaling."
        elif action_unresolved:
            summary = "This intervention type is still producing unresolved outcomes and needs follow-up tracking."
        else:
            summary = "More review and outcome logging is needed before judging this intervention type."

        action_effectiveness.append(
            {
                "action_status": action_status,
                "total_actions": action_total,
                "reviewed_actions": action_reviewed,
                "review_rate": review_rate,
                "false_alert_count": action_false_alerts,
                "false_alert_rate": false_alert_rate,
                "outcomes_recorded": len(action_outcomes),
                "improved_count": action_improved,
                "unresolved_count": action_unresolved,
                "effectiveness_score": effectiveness_score,
                "summary": summary,
            }
        )

    if improved_rows and not false_alert_rows:
        summary = "Recorded interventions are showing positive outcomes with no false-alert reviews so far."
    elif false_alert_rows:
        summary = "Some interventions were reviewed as false alerts, so counsellor feedback is now available for operational tuning."
    elif outcome_rows:
        summary = "Outcome tracking is active, but the improvement rate is still mixed across intervention types."
    else:
        summary = "Intervention logging exists, but review and outcome coverage is still too limited for strong effectiveness conclusions."

    return {
        "total_actions": total_actions,
        "total_reviewed_actions": len(reviewed_rows),
        "total_false_alerts": len(false_alert_rows),
        "total_valid_alerts": len(valid_alert_rows),
        "total_outcomes_recorded": len(outcome_rows),
        "total_improved_cases": len(improved_rows),
        "total_unresolved_cases": len(unresolved_rows),
        "review_coverage_percent": round((len(reviewed_rows) / total_actions) * 100, 1)
        if total_actions
        else 0.0,
        "improvement_rate_percent": round((len(improved_rows) / total_actions) * 100, 1)
        if total_actions
        else 0.0,
        "false_alert_rate_percent": round((len(false_alert_rows) / total_actions) * 100, 1)
        if total_actions
        else 0.0,
        "summary": summary,
        "action_effectiveness": action_effectiveness,
    }
