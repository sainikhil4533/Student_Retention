from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


GuardianChannel = Literal["email", "sms", "whatsapp"]


@dataclass(frozen=True)
class GuardianEscalationDecision:
    should_send: bool
    alert_type: str | None
    reason: str
    channel: GuardianChannel | None
    severity: str


def _preferred_guardian_channel(profile) -> GuardianChannel | None:
    channel = str(getattr(profile, "preferred_guardian_channel", "") or "").strip().lower()
    if channel in {"email", "sms", "whatsapp"}:
        return channel  # type: ignore[return-value]

    if getattr(profile, "parent_phone", None):
        return "whatsapp"
    if getattr(profile, "parent_email", None):
        return "email"
    return None


def _guardian_channel_available(profile, channel: GuardianChannel | None) -> bool:
    if channel == "email":
        return bool(str(getattr(profile, "parent_email", "") or "").strip())
    if channel in {"sms", "whatsapp"}:
        return bool(str(getattr(profile, "parent_phone", "") or "").strip())
    return False


def evaluate_guardian_escalation_decision(
    *,
    profile,
    current_prediction,
    latest_warning=None,
    latest_alert=None,
    latest_intervention=None,
    repeat_high_risk_count: int = 0,
    high_risk_cycle_count: int = 0,
    has_relapsed_after_resolution: bool = False,
    is_critical_unattended_case: bool = False,
) -> GuardianEscalationDecision:
    if not bool(getattr(profile, "guardian_contact_enabled", False)):
        return GuardianEscalationDecision(
            should_send=False,
            alert_type=None,
            reason="Guardian contact is not enabled for this student profile.",
            channel=None,
            severity="none",
        )

    if float(current_prediction.final_risk_probability) < 0.50:
        return GuardianEscalationDecision(
            should_send=False,
            alert_type=None,
            reason="Student is not currently high risk.",
            channel=None,
            severity="none",
        )

    if latest_warning is None:
        return GuardianEscalationDecision(
            should_send=False,
            alert_type=None,
            reason="Guardian escalation is blocked until the student warning flow has started.",
            channel=None,
            severity="none",
        )

    if latest_alert is None:
        return GuardianEscalationDecision(
            should_send=False,
            alert_type=None,
            reason="Guardian escalation is blocked until faculty escalation exists.",
            channel=None,
            severity="none",
        )

    latest_intervention_status = (
        str(getattr(latest_intervention, "action_status", "") or "").strip().lower()
        if latest_intervention is not None
        else None
    )
    if latest_intervention_status in {"support_provided", "resolved"}:
        return GuardianEscalationDecision(
            should_send=False,
            alert_type=None,
            reason="Guardian escalation is blocked because faculty has already provided support or resolved the case.",
            channel=None,
            severity="none",
        )

    worst_case_trigger = (
        is_critical_unattended_case
        or has_relapsed_after_resolution
        or high_risk_cycle_count >= 2
        or repeat_high_risk_count >= 3
        or str(getattr(latest_alert, "alert_type", "") or "").strip().lower()
        == "faculty_followup_reminder"
    )
    if not worst_case_trigger:
        return GuardianEscalationDecision(
            should_send=False,
            alert_type=None,
            reason="Worst-case guardian escalation conditions are not met yet.",
            channel=None,
            severity="none",
        )

    channel = _preferred_guardian_channel(profile)
    if not _guardian_channel_available(profile, channel):
        return GuardianEscalationDecision(
            should_send=False,
            alert_type=None,
            reason="Guardian escalation is eligible, but no usable guardian contact channel is configured.",
            channel=channel,
            severity="critical",
        )

    return GuardianEscalationDecision(
        should_send=True,
        alert_type="guardian_worst_case_escalation",
        reason=(
            "Student remains high risk after student warning and faculty escalation, "
            "and the case now meets worst-case guardian-escalation conditions."
        ),
        channel=channel,
        severity="critical",
    )
