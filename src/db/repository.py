from datetime import UTC, datetime
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import (
    AlertEvent,
    BackgroundJob,
    CopilotChatMessage,
    CopilotChatSession,
    CopilotAuditEvent,
    ERPEvent,
    FacultySummarySnapshot,
    FinanceEvent,
    GuardianAlertEvent,
    InterventionAction,
    LMSEvent,
    PredictionHistory,
    StudentProfile,
    StudentWarningEvent,
)


class EventRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _normalized_context_fields(value: dict | None) -> dict:
        return value or {}

    @classmethod
    def _dedupe_identity_from_context(cls, event: dict) -> tuple[str, str] | None:
        context = cls._normalized_context_fields(event.get("context_fields"))
        for key in ("source_event_id", "event_id", "record_id", "ingestion_id"):
            value = context.get(key)
            if value not in (None, ""):
                return (key, str(value))
        for key in ("observed_at", "event_time", "event_timestamp", "recorded_at"):
            value = context.get(key)
            if value not in (None, ""):
                return (key, str(value))
        return None

    def find_matching_lms_event(self, event: dict) -> LMSEvent | None:
        return (
            self.db.query(LMSEvent)
            .filter(
                LMSEvent.student_id == event["student_id"],
                LMSEvent.code_module == event["code_module"],
                LMSEvent.code_presentation == event["code_presentation"],
                LMSEvent.id_site == event["id_site"],
                LMSEvent.event_date == event["event_date"],
                LMSEvent.sum_click == event["sum_click"],
            )
            .order_by(LMSEvent.id.desc())
            .first()
        )

    def add_lms_event(self, event: dict) -> LMSEvent:
        existing = self.find_matching_lms_event(event)
        if existing is not None:
            return existing
        db_event = LMSEvent(**event)
        self.db.add(db_event)
        self.db.commit()
        self.db.refresh(db_event)
        return db_event

    def find_matching_erp_event(self, event: dict) -> ERPEvent | None:
        dedupe_identity = self._dedupe_identity_from_context(event)
        if dedupe_identity is None:
            return None

        candidates = (
            self.db.query(ERPEvent)
            .filter(ERPEvent.student_id == event["student_id"])
            .order_by(ERPEvent.id.desc())
            .all()
        )
        target_key, target_value = dedupe_identity
        for candidate in candidates:
            candidate_context = self._normalized_context_fields(candidate.context_fields)
            if str(candidate_context.get(target_key, "")) == target_value:
                return candidate
        return None

    def add_erp_event(self, event: dict) -> ERPEvent:
        existing = self.find_matching_erp_event(event)
        if existing is not None:
            return existing
        db_event = ERPEvent(**event)
        self.db.add(db_event)
        self.db.commit()
        self.db.refresh(db_event)
        return db_event

    def find_matching_finance_event(self, event: dict) -> FinanceEvent | None:
        dedupe_identity = self._dedupe_identity_from_context(event)
        if dedupe_identity is None:
            return None

        candidates = (
            self.db.query(FinanceEvent)
            .filter(FinanceEvent.student_id == event["student_id"])
            .order_by(FinanceEvent.id.desc())
            .all()
        )
        target_key, target_value = dedupe_identity
        for candidate in candidates:
            candidate_context = self._normalized_context_fields(candidate.context_fields)
            if str(candidate_context.get(target_key, "")) == target_value:
                return candidate
        return None

    def add_finance_event(self, event: dict) -> FinanceEvent:
        existing = self.find_matching_finance_event(event)
        if existing is not None:
            return existing
        db_event = FinanceEvent(**event)
        self.db.add(db_event)
        self.db.commit()
        self.db.refresh(db_event)
        return db_event

    def upsert_student_profile(self, profile: dict) -> StudentProfile:
        db_profile = self.db.get(StudentProfile, profile["student_id"])

        if db_profile is None:
            db_profile = StudentProfile(**profile)
            self.db.add(db_profile)
        else:
            for field, value in profile.items():
                setattr(db_profile, field, value)

        self.db.commit()
        self.db.refresh(db_profile)
        return db_profile

    def get_lms_events_for_student(self, student_id: int) -> list[LMSEvent]:
        return (
            self.db.query(LMSEvent)
            .filter(LMSEvent.student_id == student_id)
            .order_by(LMSEvent.event_date.asc())
            .all()
        )

    def get_latest_erp_event(self, student_id: int) -> ERPEvent | None:
        return (
            self.db.query(ERPEvent)
            .filter(ERPEvent.student_id == student_id)
            .order_by(ERPEvent.id.desc())
            .first()
        )

    def get_erp_event_history_for_student(self, student_id: int) -> list[ERPEvent]:
        return (
            self.db.query(ERPEvent)
            .filter(ERPEvent.student_id == student_id)
            .order_by(ERPEvent.id.desc())
            .all()
        )

    def get_latest_finance_event(self, student_id: int) -> FinanceEvent | None:
        return (
            self.db.query(FinanceEvent)
            .filter(FinanceEvent.student_id == student_id)
            .order_by(FinanceEvent.id.desc())
            .first()
        )

    def get_finance_event_history_for_student(self, student_id: int) -> list[FinanceEvent]:
        return (
            self.db.query(FinanceEvent)
            .filter(FinanceEvent.student_id == student_id)
            .order_by(FinanceEvent.id.desc())
            .all()
        )

    def get_student_profile(self, student_id: int) -> StudentProfile | None:
        return self.db.get(StudentProfile, student_id)

    def get_all_student_profiles(self) -> list[StudentProfile]:
        return (
            self.db.query(StudentProfile)
            .order_by(StudentProfile.student_id.asc())
            .all()
        )

    def get_imported_student_profiles(self) -> list[StudentProfile]:
        return (
            self.db.query(StudentProfile)
            .filter(StudentProfile.external_student_ref.is_not(None))
            .order_by(StudentProfile.student_id.asc())
            .all()
        )

    @staticmethod
    def _normalized_identity_tokens(*values: str) -> list[str]:
        tokens: list[str] = []
        for raw in values:
            value = str(raw or "").strip()
            if not value:
                continue
            lowered = value.lower()
            candidates = {
                lowered,
                lowered.replace("_", " "),
                lowered.replace(".", " "),
                lowered.replace("-", " "),
            }
            if "@" in lowered:
                local = lowered.split("@", 1)[0]
                candidates.add(local)
                candidates.add(local.replace(".", " "))
                candidates.add(local.replace("_", " "))
            if lowered.startswith("counsellor "):
                stripped = lowered.split(" ", 1)[1].strip()
                if stripped:
                    candidates.add(stripped)
            for candidate in candidates:
                cleaned = " ".join(part for part in re.split(r"[\s._-]+", candidate) if part)
                if cleaned:
                    tokens.append(cleaned)
        normalized: list[str] = []
        for token in tokens:
            if token not in normalized:
                normalized.append(token)
        return normalized

    def get_imported_student_profiles_for_counsellor_identity(
        self,
        *,
        subject: str,
        display_name: str | None = None,
    ) -> list[StudentProfile]:
        values = [str(subject or "").strip(), str(display_name or "").strip()]
        if subject.endswith("_demo") and "counsellor" in subject.lower() and not display_name:
            values.append(subject.replace("_demo", "").replace("_", " "))
        scope_identifiers = self._normalized_identity_tokens(*values)
        if not scope_identifiers:
            return []
        filtered: list[StudentProfile] = []
        for profile in self.get_imported_student_profiles():
            profile_identifiers = self._normalized_identity_tokens(
                str(getattr(profile, "counsellor_name", "") or ""),
                str(getattr(profile, "counsellor_email", "") or ""),
            )
            if any(scope in profile_identifiers for scope in scope_identifiers):
                filtered.append(profile)
        return filtered

    def get_student_profile_by_external_ref(self, external_ref: str) -> StudentProfile | None:
        return (
            self.db.query(StudentProfile)
            .filter(StudentProfile.external_student_ref == external_ref)
            .first()
        )

    def create_copilot_chat_session(self, record: dict) -> CopilotChatSession:
        db_record = CopilotChatSession(**record)
        self.db.add(db_record)
        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def get_copilot_chat_session(self, session_id: int) -> CopilotChatSession | None:
        return self.db.get(CopilotChatSession, session_id)

    def update_copilot_chat_session(self, session_id: int, updates: dict) -> CopilotChatSession | None:
        db_record = self.db.get(CopilotChatSession, session_id)
        if db_record is None:
            return None
        for field, value in updates.items():
            setattr(db_record, field, value)
        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def list_copilot_chat_sessions_for_subject(self, owner_subject: str) -> list[CopilotChatSession]:
        return (
            self.db.query(CopilotChatSession)
            .filter(CopilotChatSession.owner_subject == owner_subject)
            .order_by(CopilotChatSession.last_message_at.desc(), CopilotChatSession.id.desc())
            .all()
        )

    def add_copilot_chat_message(self, record: dict) -> CopilotChatMessage:
        db_record = CopilotChatMessage(**record)
        self.db.add(db_record)
        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def list_copilot_chat_messages(self, session_id: int) -> list[CopilotChatMessage]:
        return (
            self.db.query(CopilotChatMessage)
            .filter(CopilotChatMessage.session_id == session_id)
            .order_by(CopilotChatMessage.created_at.asc(), CopilotChatMessage.id.asc())
            .all()
        )

    def add_copilot_audit_event(self, record: dict) -> CopilotAuditEvent:
        db_record = CopilotAuditEvent(**record)
        self.db.add(db_record)
        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def list_copilot_audit_events(
        self,
        *,
        session_id: int | None = None,
        limit: int = 100,
    ) -> list[CopilotAuditEvent]:
        query = self.db.query(CopilotAuditEvent)
        if session_id is not None:
            query = query.filter(CopilotAuditEvent.session_id == session_id)
        return query.order_by(
            CopilotAuditEvent.created_at.desc(),
            CopilotAuditEvent.id.desc(),
        ).limit(limit).all()

    def get_max_student_id(self) -> int:
        value = self.db.query(func.max(StudentProfile.student_id)).scalar()
        if value in (None, ""):
            return 0
        return int(value)

    def add_prediction_history(self, record: dict) -> PredictionHistory:
        db_record = PredictionHistory(**record)
        self.db.add(db_record)
        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def update_prediction_history(
        self,
        prediction_history_id: int,
        updates: dict,
    ) -> PredictionHistory | None:
        db_record = self.db.get(PredictionHistory, prediction_history_id)
        if db_record is None:
            return None

        for field, value in updates.items():
            setattr(db_record, field, value)

        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def add_alert_event(self, record: dict) -> AlertEvent:
        db_record = AlertEvent(**record)
        self.db.add(db_record)
        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def add_guardian_alert_event(self, record: dict) -> GuardianAlertEvent:
        db_record = GuardianAlertEvent(**record)
        self.db.add(db_record)
        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def get_guardian_alert_event(self, guardian_alert_event_id: int) -> GuardianAlertEvent | None:
        return self.db.get(GuardianAlertEvent, guardian_alert_event_id)

    def update_guardian_alert_event(
        self,
        guardian_alert_event_id: int,
        updates: dict,
    ) -> GuardianAlertEvent | None:
        db_record = self.db.get(GuardianAlertEvent, guardian_alert_event_id)
        if db_record is None:
            return None

        for field, value in updates.items():
            setattr(db_record, field, value)

        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def get_latest_guardian_alert_for_student(self, student_id: int) -> GuardianAlertEvent | None:
        return (
            self.db.query(GuardianAlertEvent)
            .filter(GuardianAlertEvent.student_id == student_id)
            .order_by(GuardianAlertEvent.sent_at.desc(), GuardianAlertEvent.id.desc())
            .first()
        )

    def get_guardian_alert_history_for_student(self, student_id: int) -> list[GuardianAlertEvent]:
        return (
            self.db.query(GuardianAlertEvent)
            .filter(GuardianAlertEvent.student_id == student_id)
            .order_by(GuardianAlertEvent.sent_at.desc(), GuardianAlertEvent.id.desc())
            .all()
        )

    def get_all_guardian_alert_events(self) -> list[GuardianAlertEvent]:
        return (
            self.db.query(GuardianAlertEvent)
            .order_by(GuardianAlertEvent.sent_at.desc(), GuardianAlertEvent.id.desc())
            .all()
        )

    def find_existing_guardian_alert_for_prediction(
        self,
        *,
        student_id: int,
        prediction_history_id: int,
        alert_type: str,
    ) -> GuardianAlertEvent | None:
        return (
            self.db.query(GuardianAlertEvent)
            .filter(
                GuardianAlertEvent.student_id == student_id,
                GuardianAlertEvent.prediction_history_id == prediction_history_id,
                GuardianAlertEvent.alert_type == alert_type,
                GuardianAlertEvent.delivery_status.in_(
                    ("queued", "processing", "sent", "delivered")
                ),
            )
            .order_by(GuardianAlertEvent.sent_at.desc(), GuardianAlertEvent.id.desc())
            .first()
        )

    def get_alert_event(self, alert_event_id: int) -> AlertEvent | None:
        return self.db.get(AlertEvent, alert_event_id)

    def update_alert_event(self, alert_event_id: int, updates: dict) -> AlertEvent | None:
        db_record = self.db.get(AlertEvent, alert_event_id)
        if db_record is None:
            return None

        for field, value in updates.items():
            setattr(db_record, field, value)

        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def get_latest_alert_for_student(self, student_id: int) -> AlertEvent | None:
        return (
            self.db.query(AlertEvent)
            .filter(
                AlertEvent.student_id == student_id,
                AlertEvent.email_status == "sent",
            )
            .order_by(AlertEvent.sent_at.desc(), AlertEvent.id.desc())
            .first()
        )

    def get_alert_history_for_student(self, student_id: int) -> list[AlertEvent]:
        return (
            self.db.query(AlertEvent)
            .filter(AlertEvent.student_id == student_id)
            .order_by(AlertEvent.sent_at.desc(), AlertEvent.id.desc())
            .all()
        )

    def get_all_alert_events(self) -> list[AlertEvent]:
        return (
            self.db.query(AlertEvent)
            .order_by(AlertEvent.sent_at.desc(), AlertEvent.id.desc())
            .all()
        )

    def add_intervention_action(self, record: dict) -> InterventionAction:
        db_record = InterventionAction(**record)
        self.db.add(db_record)
        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def get_intervention_action(self, intervention_action_id: int) -> InterventionAction | None:
        return self.db.get(InterventionAction, intervention_action_id)

    def update_intervention_action(
        self,
        intervention_action_id: int,
        updates: dict,
    ) -> InterventionAction | None:
        db_record = self.db.get(InterventionAction, intervention_action_id)
        if db_record is None:
            return None

        for field, value in updates.items():
            setattr(db_record, field, value)

        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def get_intervention_history_for_student(self, student_id: int) -> list[InterventionAction]:
        return (
            self.db.query(InterventionAction)
            .filter(InterventionAction.student_id == student_id)
            .order_by(InterventionAction.created_at.desc(), InterventionAction.id.desc())
            .all()
        )

    def get_latest_intervention_for_student(self, student_id: int) -> InterventionAction | None:
        return (
            self.db.query(InterventionAction)
            .filter(InterventionAction.student_id == student_id)
            .order_by(InterventionAction.created_at.desc(), InterventionAction.id.desc())
            .first()
        )

    def get_all_intervention_actions(self) -> list[InterventionAction]:
        return (
            self.db.query(InterventionAction)
            .order_by(InterventionAction.created_at.desc(), InterventionAction.id.desc())
            .all()
        )

    def add_faculty_summary_snapshot(self, record: dict) -> FacultySummarySnapshot:
        db_record = FacultySummarySnapshot(**record)
        self.db.add(db_record)
        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def find_active_background_job(self, dedupe_key: str) -> BackgroundJob | None:
        return (
            self.db.query(BackgroundJob)
            .filter(
                BackgroundJob.dedupe_key == dedupe_key,
                BackgroundJob.status.in_(("queued", "processing")),
            )
            .order_by(BackgroundJob.id.desc())
            .first()
        )

    def add_background_job(self, record: dict) -> BackgroundJob:
        db_record = BackgroundJob(**record)
        self.db.add(db_record)
        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def enqueue_background_job(
        self,
        *,
        job_type: str,
        payload: dict,
        dedupe_key: str | None = None,
    ) -> BackgroundJob:
        if dedupe_key:
            existing = self.find_active_background_job(dedupe_key)
            if existing is not None:
                return existing
        return self.add_background_job(
            {
                "job_type": job_type,
                "dedupe_key": dedupe_key,
                "payload": payload,
                "status": "queued",
                "attempt_count": 0,
            }
        )

    def claim_next_background_job(
        self,
        reference_time: datetime | None = None,
    ) -> BackgroundJob | None:
        effective_time = reference_time or datetime.now(UTC)
        job = (
            self.db.query(BackgroundJob)
            .filter(
                BackgroundJob.status == "queued",
                BackgroundJob.available_at <= effective_time,
            )
            .order_by(BackgroundJob.available_at.asc(), BackgroundJob.id.asc())
            .first()
        )
        if job is None:
            return None

        job.status = "processing"
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.claimed_at = effective_time
        job.updated_at = effective_time
        self.db.commit()
        self.db.refresh(job)
        return job

    def update_background_job(self, job_id: int, updates: dict) -> BackgroundJob | None:
        db_record = self.db.get(BackgroundJob, job_id)
        if db_record is None:
            return None

        for field, value in updates.items():
            setattr(db_record, field, value)

        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def get_faculty_summary_snapshot(self, snapshot_id: int) -> FacultySummarySnapshot | None:
        return self.db.get(FacultySummarySnapshot, snapshot_id)

    def update_faculty_summary_snapshot(
        self,
        snapshot_id: int,
        updates: dict,
    ) -> FacultySummarySnapshot | None:
        db_record = self.db.get(FacultySummarySnapshot, snapshot_id)
        if db_record is None:
            return None

        for field, value in updates.items():
            setattr(db_record, field, value)

        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def get_latest_faculty_summary_snapshot(
        self,
        snapshot_type: str | None = None,
    ) -> FacultySummarySnapshot | None:
        query = self.db.query(FacultySummarySnapshot)
        if snapshot_type is not None:
            query = query.filter(FacultySummarySnapshot.snapshot_type == snapshot_type)
        return query.order_by(
            FacultySummarySnapshot.generated_at.desc(),
            FacultySummarySnapshot.id.desc(),
        ).first()

    def get_faculty_summary_snapshot_history(
        self,
        snapshot_type: str | None = None,
        limit: int = 20,
    ) -> list[FacultySummarySnapshot]:
        query = self.db.query(FacultySummarySnapshot)
        if snapshot_type is not None:
            query = query.filter(FacultySummarySnapshot.snapshot_type == snapshot_type)
        return query.order_by(
            FacultySummarySnapshot.generated_at.desc(),
            FacultySummarySnapshot.id.desc(),
        ).limit(limit).all()

    def add_student_warning_event(self, record: dict) -> StudentWarningEvent:
        db_record = StudentWarningEvent(**record)
        self.db.add(db_record)
        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def get_student_warning_event(self, warning_event_id: int) -> StudentWarningEvent | None:
        return self.db.get(StudentWarningEvent, warning_event_id)

    def update_student_warning_event(
        self,
        warning_event_id: int,
        updates: dict,
    ) -> StudentWarningEvent | None:
        db_record = self.db.get(StudentWarningEvent, warning_event_id)
        if db_record is None:
            return None

        for field, value in updates.items():
            setattr(db_record, field, value)

        self.db.commit()
        self.db.refresh(db_record)
        return db_record

    def get_active_student_warning_for_student(self, student_id: int) -> StudentWarningEvent | None:
        return (
            self.db.query(StudentWarningEvent)
            .filter(
                StudentWarningEvent.student_id == student_id,
                StudentWarningEvent.resolution_status.is_(None),
            )
            .order_by(StudentWarningEvent.sent_at.desc(), StudentWarningEvent.id.desc())
            .first()
        )

    def get_expired_active_student_warnings(
        self,
        reference_time: datetime | None = None,
    ) -> list[StudentWarningEvent]:
        effective_time = reference_time or datetime.now(UTC)
        return (
            self.db.query(StudentWarningEvent)
            .filter(
                StudentWarningEvent.resolution_status.is_(None),
                StudentWarningEvent.recovery_deadline <= effective_time,
            )
            .order_by(StudentWarningEvent.recovery_deadline.asc(), StudentWarningEvent.id.asc())
            .all()
        )

    def get_student_warning_history_for_student(self, student_id: int) -> list[StudentWarningEvent]:
        return (
            self.db.query(StudentWarningEvent)
            .filter(StudentWarningEvent.student_id == student_id)
            .order_by(StudentWarningEvent.sent_at.desc(), StudentWarningEvent.id.desc())
            .all()
        )

    def get_all_student_warning_events(self) -> list[StudentWarningEvent]:
        return (
            self.db.query(StudentWarningEvent)
            .order_by(StudentWarningEvent.sent_at.desc(), StudentWarningEvent.id.desc())
            .all()
        )

    def get_prediction_history_for_student(self, student_id: int) -> list[PredictionHistory]:
        return (
            self.db.query(PredictionHistory)
            .filter(PredictionHistory.student_id == student_id)
            .order_by(PredictionHistory.created_at.desc(), PredictionHistory.id.desc())
            .all()
        )

    def get_all_prediction_history(self) -> list[PredictionHistory]:
        return (
            self.db.query(PredictionHistory)
            .order_by(PredictionHistory.created_at.desc(), PredictionHistory.id.desc())
            .all()
        )

    def get_latest_predictions_for_all_students(self) -> list[PredictionHistory]:
        latest_by_student: dict[int, PredictionHistory] = {}
        for row in self.get_all_prediction_history():
            latest_by_student.setdefault(int(row.student_id), row)
        return list(latest_by_student.values())

    def get_latest_prediction_for_student(self, student_id: int) -> PredictionHistory | None:
        return (
            self.db.query(PredictionHistory)
            .filter(PredictionHistory.student_id == student_id)
            .order_by(PredictionHistory.created_at.desc(), PredictionHistory.id.desc())
            .first()
        )

    def get_prediction_history_by_id(self, prediction_history_id: int) -> PredictionHistory | None:
        return self.db.get(PredictionHistory, prediction_history_id)
