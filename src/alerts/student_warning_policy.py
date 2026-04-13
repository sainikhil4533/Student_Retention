from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv


load_dotenv()


DEFAULT_RECOVERY_WINDOW_DAYS = int(os.getenv("RECOVERY_WINDOW_DAYS", "7"))


@dataclass(frozen=True)
class StudentWarningDecision:
    should_send: bool
    warning_type: str | None
    reason: str
    recovery_deadline: datetime | None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def build_recovery_deadline(reference_time: datetime | None = None) -> datetime:
    baseline = _as_utc(reference_time) or datetime.now(UTC)
    return baseline + timedelta(days=DEFAULT_RECOVERY_WINDOW_DAYS)


def evaluate_student_warning_decision(
    current_prediction,
    active_warning_event=None,
) -> StudentWarningDecision:
    created_at = _as_utc(getattr(current_prediction, "created_at", None)) or datetime.now(UTC)

    if int(current_prediction.final_predicted_class) != 1:
        return StudentWarningDecision(
            should_send=False,
            warning_type=None,
            reason="Student is not currently high risk.",
            recovery_deadline=None,
        )

    if active_warning_event is None:
        return StudentWarningDecision(
            should_send=True,
            warning_type="initial_student_warning",
            reason="Student newly entered high-risk state and should be warned first.",
            recovery_deadline=build_recovery_deadline(created_at),
        )

    return StudentWarningDecision(
        should_send=False,
        warning_type=None,
        reason="Active student recovery window already exists.",
        recovery_deadline=_as_utc(getattr(active_warning_event, "recovery_deadline", None)),
    )


def should_escalate_to_faculty(
    current_prediction,
    active_warning_event=None,
) -> tuple[bool, str]:
    if int(current_prediction.final_predicted_class) != 1:
        return False, "Student is not currently high risk."

    if active_warning_event is None:
        return False, "Student must be warned before faculty escalation."

    recovery_deadline = _as_utc(getattr(active_warning_event, "recovery_deadline", None))
    created_at = _as_utc(getattr(current_prediction, "created_at", None)) or datetime.now(UTC)
    if recovery_deadline is None:
        return False, "Recovery deadline is missing on active warning."

    if created_at < recovery_deadline:
        return False, "Student is still within the recovery window."

    return True, "Recovery window expired and student remains high risk."
