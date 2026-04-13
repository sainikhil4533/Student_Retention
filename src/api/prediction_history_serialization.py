from __future__ import annotations

from src.api.schemas import (
    PredictionHistoryItem,
    RecommendedActionItem,
    RiskTrendSummary,
    RiskTypeSummary,
    StabilitySummary,
    TriggerAlertItem,
    TriggerAlertSummary,
)
from src.api.time_utils import to_ist


def resolve_prediction_intelligence_snapshot(row, computed: dict | None = None) -> dict:
    persisted = {
        "risk_trend": getattr(row, "risk_trend", None),
        "stability": getattr(row, "stability", None),
        "risk_type": getattr(row, "risk_type", None),
        "recommended_actions": getattr(row, "recommended_actions", None),
        "trigger_alerts": getattr(row, "trigger_alerts", None),
    }

    return {
        "risk_trend": persisted["risk_trend"] or (computed or {}).get("risk_trend"),
        "stability": persisted["stability"] or (computed or {}).get("stability"),
        "risk_type": persisted["risk_type"] or (computed or {}).get("risk_type"),
        "recommended_actions": persisted["recommended_actions"]
        or (computed or {}).get("recommended_actions")
        or [],
        "trigger_alerts": persisted["trigger_alerts"] or (computed or {}).get("trigger_alerts"),
    }


def build_prediction_history_item_from_row(
    row,
    computed: dict | None = None,
) -> PredictionHistoryItem:
    intelligence = resolve_prediction_intelligence_snapshot(row, computed)
    trigger_alerts = intelligence["trigger_alerts"]

    return PredictionHistoryItem(
        student_id=row.student_id,
        champion_model=row.champion_model,
        threshold=float(row.threshold),
        base_predicted_class=int(row.base_predicted_class),
        base_risk_probability=float(row.base_risk_probability),
        finance_modifier=float(row.finance_modifier),
        final_risk_probability=float(row.final_risk_probability),
        final_predicted_class=int(row.final_predicted_class),
        challenger_predictions=row.challenger_predictions,
        ai_insights=row.ai_insights,
        risk_trend=(
            RiskTrendSummary(**intelligence["risk_trend"])
            if intelligence["risk_trend"] is not None
            else None
        ),
        stability=(
            StabilitySummary(**intelligence["stability"])
            if intelligence["stability"] is not None
            else None
        ),
        risk_type=(
            RiskTypeSummary(**intelligence["risk_type"])
            if intelligence["risk_type"] is not None
            else None
        ),
        recommended_actions=[
            RecommendedActionItem(**item)
            for item in intelligence["recommended_actions"]
        ],
        trigger_alerts=(
            TriggerAlertSummary(
                triggers=[
                    TriggerAlertItem(**item)
                    for item in trigger_alerts["triggers"]
                ],
                has_critical_trigger=bool(trigger_alerts["has_critical_trigger"]),
                trigger_count=int(trigger_alerts["trigger_count"]),
                summary=str(trigger_alerts["summary"]),
            )
            if trigger_alerts is not None
            else None
        ),
        created_at=to_ist(row.created_at),
    )
