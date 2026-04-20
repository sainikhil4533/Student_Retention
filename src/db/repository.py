from datetime import UTC, datetime
import re

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.db.models import (
    AlertEvent,
    AuthAccount,
    BackgroundJob,
    CopilotChatMessage,
    CopilotChatSession,
    CopilotAuditEvent,
    ERPEvent,
    FacultySummarySnapshot,
    FinanceEvent,
    GuardianAlertEvent,
    InstitutionAttendancePolicy,
    InterventionAction,
    LMSEvent,
    PredictionHistory,
    StudentAcademicProgressRecord,
    StudentAcademicRecord,
    StudentProfile,
    StudentSemesterProgressRecord,
    StudentSubjectAttendanceRecord,
    StudentWarningEvent,
    SubjectCatalogEntry,
)


class EventRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _normalize_student_scope(student_ids: set[int] | None) -> set[int] | None:
        if student_ids is None:
            return None
        normalized = {
            int(student_id)
            for student_id in student_ids
            if student_id not in (None, "")
        }
        return normalized

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

    def add_lms_event(self, event: dict, *, commit: bool = True) -> LMSEvent:
        existing = self.find_matching_lms_event(event)
        if existing is not None:
            return existing
        db_event = LMSEvent(**event)
        self.db.add(db_event)
        if commit:
            self.db.commit()
            self.db.refresh(db_event)
        return db_event

    def get_auth_account_by_username(self, username: str) -> AuthAccount | None:
        return (
            self.db.query(AuthAccount)
            .filter(func.lower(AuthAccount.username) == str(username or "").strip().lower())
            .first()
        )

    def create_auth_account(self, record: dict, *, commit: bool = True) -> AuthAccount:
        db_record = AuthAccount(**record)
        self.db.add(db_record)
        if commit:
            self.db.commit()
            self.db.refresh(db_record)
        return db_record

    def update_auth_account(self, account_id: int, updates: dict) -> AuthAccount | None:
        db_record = self.db.get(AuthAccount, account_id)
        if db_record is None:
            return None
        for field, value in updates.items():
            setattr(db_record, field, value)
        self.db.commit()
        self.db.refresh(db_record)
        return db_record

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

    def add_erp_event(self, event: dict, *, commit: bool = True) -> ERPEvent:
        existing = self.find_matching_erp_event(event)
        if existing is not None:
            return existing
        db_event = ERPEvent(**event)
        self.db.add(db_event)
        if commit:
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

    def add_finance_event(self, event: dict, *, commit: bool = True) -> FinanceEvent:
        existing = self.find_matching_finance_event(event)
        if existing is not None:
            return existing
        db_event = FinanceEvent(**event)
        self.db.add(db_event)
        if commit:
            self.db.commit()
            self.db.refresh(db_event)
        return db_event

    def replace_institution_attendance_policies(
        self,
        *,
        institution_name: str,
        records: list[dict],
        commit: bool = True,
    ) -> list[InstitutionAttendancePolicy]:
        self.db.query(InstitutionAttendancePolicy).filter(
            InstitutionAttendancePolicy.institution_name == institution_name
        ).delete(synchronize_session=False)
        db_records = [InstitutionAttendancePolicy(**record) for record in records]
        self.db.add_all(db_records)
        if commit:
            self.db.commit()
            for item in db_records:
                self.db.refresh(item)
        return db_records

    def replace_subject_catalog_entries(
        self,
        *,
        institution_name: str,
        records: list[dict],
        commit: bool = True,
    ) -> list[SubjectCatalogEntry]:
        self.db.query(SubjectCatalogEntry).filter(
            SubjectCatalogEntry.institution_name == institution_name
        ).delete(synchronize_session=False)
        db_records = [SubjectCatalogEntry(**record) for record in records]
        self.db.add_all(db_records)
        if commit:
            self.db.commit()
            for item in db_records:
                self.db.refresh(item)
        return db_records

    def replace_student_academic_progress(
        self,
        *,
        student_id: int,
        record: dict,
        commit: bool = True,
    ) -> StudentAcademicProgressRecord:
        self.db.query(StudentAcademicProgressRecord).filter(
            StudentAcademicProgressRecord.student_id == student_id
        ).delete(synchronize_session=False)
        db_record = StudentAcademicProgressRecord(**record)
        self.db.add(db_record)
        if commit:
            self.db.commit()
            self.db.refresh(db_record)
        return db_record

    def replace_student_semester_progress(
        self,
        *,
        student_id: int,
        records: list[dict],
        commit: bool = True,
    ) -> list[StudentSemesterProgressRecord]:
        self.db.query(StudentSemesterProgressRecord).filter(
            StudentSemesterProgressRecord.student_id == student_id
        ).delete(synchronize_session=False)
        db_records = [StudentSemesterProgressRecord(**record) for record in records]
        self.db.add_all(db_records)
        if commit:
            self.db.commit()
            for item in db_records:
                self.db.refresh(item)
        return db_records

    def replace_student_subject_attendance(
        self,
        *,
        student_id: int,
        records: list[dict],
        commit: bool = True,
    ) -> list[StudentSubjectAttendanceRecord]:
        self.db.query(StudentSubjectAttendanceRecord).filter(
            StudentSubjectAttendanceRecord.student_id == student_id
        ).delete(synchronize_session=False)
        db_records = [StudentSubjectAttendanceRecord(**record) for record in records]
        self.db.add_all(db_records)
        if commit:
            self.db.commit()
            for item in db_records:
                self.db.refresh(item)
        return db_records

    def replace_student_academic_records(
        self,
        *,
        student_id: int,
        records: list[dict],
        commit: bool = True,
    ) -> list[StudentAcademicRecord]:
        self.db.query(StudentAcademicRecord).filter(
            StudentAcademicRecord.student_id == student_id
        ).delete(synchronize_session=False)
        db_records = [StudentAcademicRecord(**record) for record in records]
        self.db.add_all(db_records)
        if commit:
            self.db.commit()
            for item in db_records:
                self.db.refresh(item)
        return db_records

    def get_subject_catalog_entries(
        self,
        *,
        institution_name: str | None = None,
        branch: str | None = None,
        semester: int | None = None,
    ) -> list[SubjectCatalogEntry]:
        query = self.db.query(SubjectCatalogEntry)
        if institution_name:
            query = query.filter(SubjectCatalogEntry.institution_name == institution_name)
        if branch:
            query = query.filter(SubjectCatalogEntry.branch == branch)
        if semester is not None:
            query = query.filter(SubjectCatalogEntry.semester == semester)
        return query.order_by(
            SubjectCatalogEntry.branch.asc(),
            SubjectCatalogEntry.semester.asc(),
            SubjectCatalogEntry.subject_code.asc(),
        ).all()

    def get_latest_attendance_policy(
        self,
        *,
        institution_name: str,
    ) -> InstitutionAttendancePolicy | None:
        return (
            self.db.query(InstitutionAttendancePolicy)
            .filter(InstitutionAttendancePolicy.institution_name == institution_name)
            .order_by(
                InstitutionAttendancePolicy.updated_at.desc(),
                InstitutionAttendancePolicy.id.desc(),
            )
            .first()
        )

    def get_student_academic_progress_record(
        self,
        student_id: int,
    ) -> StudentAcademicProgressRecord | None:
        return (
            self.db.query(StudentAcademicProgressRecord)
            .filter(StudentAcademicProgressRecord.student_id == student_id)
            .order_by(StudentAcademicProgressRecord.updated_at.desc(), StudentAcademicProgressRecord.id.desc())
            .first()
        )

    def get_student_semester_progress_records(
        self,
        student_id: int,
    ) -> list[StudentSemesterProgressRecord]:
        return (
            self.db.query(StudentSemesterProgressRecord)
            .filter(StudentSemesterProgressRecord.student_id == student_id)
            .order_by(
                StudentSemesterProgressRecord.semester.asc(),
                StudentSemesterProgressRecord.id.asc(),
            )
            .all()
        )

    def get_latest_student_semester_progress_record(
        self,
        student_id: int,
    ) -> StudentSemesterProgressRecord | None:
        return (
            self.db.query(StudentSemesterProgressRecord)
            .filter(StudentSemesterProgressRecord.student_id == student_id)
            .order_by(
                StudentSemesterProgressRecord.semester.desc(),
                StudentSemesterProgressRecord.id.desc(),
            )
            .first()
        )

    def get_student_subject_attendance_records(
        self,
        student_id: int,
    ) -> list[StudentSubjectAttendanceRecord]:
        return (
            self.db.query(StudentSubjectAttendanceRecord)
            .filter(StudentSubjectAttendanceRecord.student_id == student_id)
            .order_by(
                StudentSubjectAttendanceRecord.semester.asc(),
                StudentSubjectAttendanceRecord.subject_name.asc(),
                StudentSubjectAttendanceRecord.id.asc(),
            )
            .all()
        )

    def get_current_student_subject_attendance_records(
        self,
        student_id: int,
    ) -> list[StudentSubjectAttendanceRecord]:
        progress = self.get_student_academic_progress_record(student_id)
        query = self.db.query(StudentSubjectAttendanceRecord).filter(
            StudentSubjectAttendanceRecord.student_id == student_id
        )
        if progress is not None and progress.current_semester is not None:
            query = query.filter(
                StudentSubjectAttendanceRecord.semester == progress.current_semester
            )
        return query.order_by(
            StudentSubjectAttendanceRecord.subject_attendance_percent.asc(),
            StudentSubjectAttendanceRecord.subject_name.asc(),
            StudentSubjectAttendanceRecord.id.asc(),
        ).all()

    def get_student_academic_progress_records_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> list[StudentAcademicProgressRecord]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return []
        query = self.db.query(StudentAcademicProgressRecord)
        if student_scope is not None:
            query = query.filter(StudentAcademicProgressRecord.student_id.in_(student_scope))
        return query.order_by(
            StudentAcademicProgressRecord.student_id.asc(),
            StudentAcademicProgressRecord.updated_at.desc(),
            StudentAcademicProgressRecord.id.desc(),
        ).all()

    def get_latest_student_semester_progress_records_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> list[StudentSemesterProgressRecord]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return []
        query = self.db.query(StudentSemesterProgressRecord)
        if student_scope is not None:
            query = query.filter(StudentSemesterProgressRecord.student_id.in_(student_scope))
        rows = query.order_by(
            StudentSemesterProgressRecord.student_id.asc(),
            StudentSemesterProgressRecord.semester.desc(),
            StudentSemesterProgressRecord.id.desc(),
        ).all()
        latest_by_student: dict[int, StudentSemesterProgressRecord] = {}
        for row in rows:
            latest_by_student.setdefault(int(row.student_id), row)
        return list(latest_by_student.values())

    def get_current_student_subject_attendance_records_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> list[StudentSubjectAttendanceRecord]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return []
        query = self.db.query(StudentSubjectAttendanceRecord)
        if student_scope is not None:
            query = query.filter(StudentSubjectAttendanceRecord.student_id.in_(student_scope))
        rows = query.order_by(
            StudentSubjectAttendanceRecord.student_id.asc(),
            StudentSubjectAttendanceRecord.semester.desc(),
            StudentSubjectAttendanceRecord.subject_attendance_percent.asc(),
            StudentSubjectAttendanceRecord.id.asc(),
        ).all()
        progress_rows = self.get_student_academic_progress_records_for_students(student_scope)
        current_semester_by_student = {
            int(row.student_id): row.current_semester
            for row in progress_rows
            if row.current_semester is not None
        }
        filtered: list[StudentSubjectAttendanceRecord] = []
        for row in rows:
            current_semester = current_semester_by_student.get(int(row.student_id))
            if current_semester is None or row.semester == current_semester:
                filtered.append(row)
        return filtered

    def get_student_academic_records(
        self,
        student_id: int,
    ) -> list[StudentAcademicRecord]:
        return (
            self.db.query(StudentAcademicRecord)
            .filter(StudentAcademicRecord.student_id == student_id)
            .order_by(
                StudentAcademicRecord.semester.asc(),
                StudentAcademicRecord.subject_name.asc(),
                StudentAcademicRecord.id.asc(),
            )
            .all()
        )

    def get_student_academic_records_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> list[StudentAcademicRecord]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return []
        query = self.db.query(StudentAcademicRecord)
        if student_scope is not None:
            query = query.filter(StudentAcademicRecord.student_id.in_(student_scope))
        return query.order_by(
            StudentAcademicRecord.student_id.asc(),
            StudentAcademicRecord.semester.asc(),
            StudentAcademicRecord.subject_name.asc(),
            StudentAcademicRecord.id.asc(),
        ).all()

    def get_current_student_academic_records(
        self,
        student_id: int,
    ) -> list[StudentAcademicRecord]:
        progress = self.get_student_academic_progress_record(student_id)
        query = self.db.query(StudentAcademicRecord).filter(
            StudentAcademicRecord.student_id == student_id
        )
        if progress is not None and progress.current_semester is not None:
            query = query.filter(StudentAcademicRecord.semester == progress.current_semester)
        return query.order_by(
            StudentAcademicRecord.subject_name.asc(),
            StudentAcademicRecord.id.asc(),
        ).all()

    def upsert_student_profile(self, profile: dict, *, commit: bool = True) -> StudentProfile:
        db_profile = self.db.get(StudentProfile, profile["student_id"])

        if db_profile is None:
            db_profile = StudentProfile(**profile)
            self.db.add(db_profile)
        else:
            for field, value in profile.items():
                setattr(db_profile, field, value)

        if commit:
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

    def get_latest_lms_event_days_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> dict[int, int]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return {}
        query = (
            self.db.query(
                LMSEvent.student_id,
                func.max(LMSEvent.event_date).label("latest_event_date"),
            )
            .group_by(LMSEvent.student_id)
        )
        if student_scope is not None:
            query = query.filter(LMSEvent.student_id.in_(student_scope))
        return {
            int(row.student_id): int(row.latest_event_date)
            for row in query.all()
            if row.latest_event_date is not None
        }

    def get_latest_erp_event(self, student_id: int) -> ERPEvent | None:
        return (
            self.db.query(ERPEvent)
            .filter(ERPEvent.student_id == student_id)
            .order_by(ERPEvent.id.desc())
            .first()
        )

    def get_latest_erp_events_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> dict[int, ERPEvent]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return {}
        query = self.db.query(ERPEvent)
        if student_scope is not None:
            query = query.filter(ERPEvent.student_id.in_(student_scope))
        latest_by_student: dict[int, ERPEvent] = {}
        for row in query.order_by(ERPEvent.student_id.asc(), ERPEvent.id.desc()).all():
            latest_by_student.setdefault(int(row.student_id), row)
        return latest_by_student

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

    def get_latest_finance_events_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> dict[int, FinanceEvent]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return {}
        query = self.db.query(FinanceEvent)
        if student_scope is not None:
            query = query.filter(FinanceEvent.student_id.in_(student_scope))
        latest_by_student: dict[int, FinanceEvent] = {}
        for row in query.order_by(FinanceEvent.student_id.asc(), FinanceEvent.id.desc()).all():
            latest_by_student.setdefault(int(row.student_id), row)
        return latest_by_student

    def get_finance_event_history_for_student(self, student_id: int) -> list[FinanceEvent]:
        return (
            self.db.query(FinanceEvent)
            .filter(FinanceEvent.student_id == student_id)
            .order_by(FinanceEvent.id.desc())
            .all()
        )

    def get_student_profile(self, student_id: int) -> StudentProfile | None:
        return self.db.get(StudentProfile, student_id)

    def get_student_profiles_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> dict[int, StudentProfile]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return {}
        query = self.db.query(StudentProfile)
        if student_scope is not None:
            query = query.filter(StudentProfile.student_id.in_(student_scope))
        return {
            int(row.student_id): row
            for row in query.all()
        }

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
        lowered_values = {
            str(value or "").strip().lower()
            for value in values
            if str(value or "").strip()
        }
        email_candidates = {value for value in lowered_values if "@" in value}
        local_candidates = {
            value.split("@", 1)[0]
            for value in email_candidates
            if value.split("@", 1)[0]
        }
        local_candidates.update(
            value
            for value in lowered_values
            if value and "@" not in value
        )

        normalized_name_expr = func.trim(
            func.regexp_replace(
                func.lower(func.coalesce(StudentProfile.counsellor_name, "")),
                r"[\s._-]+",
                " ",
                "g",
            )
        )
        normalized_email_local_expr = func.trim(
            func.regexp_replace(
                func.lower(func.split_part(func.coalesce(StudentProfile.counsellor_email, ""), "@", 1)),
                r"[\s._-]+",
                " ",
                "g",
            )
        )
        exact_email_expr = func.lower(func.coalesce(StudentProfile.counsellor_email, ""))
        exact_name_expr = func.lower(func.coalesce(StudentProfile.counsellor_name, ""))
        email_local_expr = func.lower(func.split_part(func.coalesce(StudentProfile.counsellor_email, ""), "@", 1))

        conditions = []
        if email_candidates:
            conditions.append(exact_email_expr.in_(sorted(email_candidates)))
        if lowered_values:
            conditions.append(exact_name_expr.in_(sorted(lowered_values)))
        if local_candidates:
            normalized_locals = self._normalized_identity_tokens(*sorted(local_candidates))
            conditions.append(email_local_expr.in_(sorted(local_candidates)))
            if normalized_locals:
                conditions.append(normalized_name_expr.in_(normalized_locals))
                conditions.append(normalized_email_local_expr.in_(normalized_locals))

        base_query = (
            self.db.query(StudentProfile)
            .filter(StudentProfile.external_student_ref.is_not(None))
        )
        if conditions:
            matched_profiles = (
                base_query
                .filter(or_(*conditions))
                .order_by(StudentProfile.student_id.asc())
                .all()
            )
            if matched_profiles:
                return matched_profiles

        filtered: list[StudentProfile] = []
        for profile in base_query.order_by(StudentProfile.student_id.asc()).all():
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

    def create_copilot_chat_session(self, record: dict, *, commit: bool = True) -> CopilotChatSession:
        db_record = CopilotChatSession(**record)
        self.db.add(db_record)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(db_record)
        return db_record

    def get_copilot_chat_session(self, session_id: int) -> CopilotChatSession | None:
        return self.db.get(CopilotChatSession, session_id)

    def update_copilot_chat_session(
        self,
        session_id: int,
        updates: dict,
        *,
        commit: bool = True,
        refresh: bool = True,
    ) -> CopilotChatSession | None:
        db_record = self.db.get(CopilotChatSession, session_id)
        if db_record is None:
            return None
        for field, value in updates.items():
            setattr(db_record, field, value)
        self.db.flush()
        if commit:
            self.db.commit()
        if refresh:
            self.db.refresh(db_record)
        return db_record

    def list_copilot_chat_sessions_for_subject(self, owner_subject: str) -> list[CopilotChatSession]:
        return (
            self.db.query(CopilotChatSession)
            .filter(CopilotChatSession.owner_subject == owner_subject)
            .order_by(CopilotChatSession.last_message_at.desc(), CopilotChatSession.id.desc())
            .all()
        )

    def add_copilot_chat_message(self, record: dict, *, commit: bool = True) -> CopilotChatMessage:
        db_record = CopilotChatMessage(**record)
        self.db.add(db_record)
        self.db.flush()
        if commit:
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

    def add_copilot_audit_event(self, record: dict, *, commit: bool = True) -> CopilotAuditEvent:
        db_record = CopilotAuditEvent(**record)
        self.db.add(db_record)
        self.db.flush()
        if commit:
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

    def get_guardian_alert_events_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> list[GuardianAlertEvent]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return []
        query = self.db.query(GuardianAlertEvent)
        if student_scope is not None:
            query = query.filter(GuardianAlertEvent.student_id.in_(student_scope))
        return query.order_by(GuardianAlertEvent.sent_at.desc(), GuardianAlertEvent.id.desc()).all()

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

    def get_latest_alert_events_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> list[AlertEvent]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return []
        query = self.db.query(AlertEvent)
        if student_scope is not None:
            query = query.filter(AlertEvent.student_id.in_(student_scope))
        latest_ids = query.with_entities(
            AlertEvent.student_id.label("student_id"),
            func.max(AlertEvent.id).label("latest_id"),
        ).group_by(AlertEvent.student_id).subquery()
        return (
            self.db.query(AlertEvent)
            .join(latest_ids, AlertEvent.id == latest_ids.c.latest_id)
            .order_by(AlertEvent.sent_at.desc(), AlertEvent.id.desc())
            .all()
        )

    def get_all_alert_events(self) -> list[AlertEvent]:
        return (
            self.db.query(AlertEvent)
            .order_by(AlertEvent.sent_at.desc(), AlertEvent.id.desc())
            .all()
        )

    def get_alert_events_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> list[AlertEvent]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return []
        query = self.db.query(AlertEvent)
        if student_scope is not None:
            query = query.filter(AlertEvent.student_id.in_(student_scope))
        return query.order_by(AlertEvent.sent_at.desc(), AlertEvent.id.desc()).all()

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

    def get_intervention_actions_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> list[InterventionAction]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return []
        query = self.db.query(InterventionAction)
        if student_scope is not None:
            query = query.filter(InterventionAction.student_id.in_(student_scope))
        return query.order_by(
            InterventionAction.created_at.desc(),
            InterventionAction.id.desc(),
        ).all()

    def get_latest_intervention_actions_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> list[InterventionAction]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return []
        query = self.db.query(InterventionAction)
        if student_scope is not None:
            query = query.filter(InterventionAction.student_id.in_(student_scope))
        latest_ids = query.with_entities(
            InterventionAction.student_id.label("student_id"),
            func.max(InterventionAction.id).label("latest_id"),
        ).group_by(InterventionAction.student_id).subquery()
        return (
            self.db.query(InterventionAction)
            .join(latest_ids, InterventionAction.id == latest_ids.c.latest_id)
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

    def get_student_warning_events_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> list[StudentWarningEvent]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return []
        query = self.db.query(StudentWarningEvent)
        if student_scope is not None:
            query = query.filter(StudentWarningEvent.student_id.in_(student_scope))
        return query.order_by(
            StudentWarningEvent.sent_at.desc(),
            StudentWarningEvent.id.desc(),
        ).all()

    def get_latest_student_warning_events_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> list[StudentWarningEvent]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return []
        query = self.db.query(StudentWarningEvent)
        if student_scope is not None:
            query = query.filter(StudentWarningEvent.student_id.in_(student_scope))
        latest_ids = query.with_entities(
            StudentWarningEvent.student_id.label("student_id"),
            func.max(StudentWarningEvent.id).label("latest_id"),
        ).group_by(StudentWarningEvent.student_id).subquery()
        return (
            self.db.query(StudentWarningEvent)
            .join(latest_ids, StudentWarningEvent.id == latest_ids.c.latest_id)
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

    def get_prediction_history_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> list[PredictionHistory]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return []
        query = self.db.query(PredictionHistory)
        if student_scope is not None:
            query = query.filter(PredictionHistory.student_id.in_(student_scope))
        return query.order_by(
            PredictionHistory.created_at.desc(),
            PredictionHistory.id.desc(),
        ).all()

    def get_latest_predictions_for_all_students(self) -> list[PredictionHistory]:
        return self.get_latest_predictions_for_students()

    def get_latest_predictions_for_students(
        self,
        student_ids: set[int] | None = None,
    ) -> list[PredictionHistory]:
        student_scope = self._normalize_student_scope(student_ids)
        if student_scope == set():
            return []
        query = self.db.query(PredictionHistory)
        if student_scope is not None:
            query = query.filter(PredictionHistory.student_id.in_(student_scope))
        latest_ids = query.with_entities(
            PredictionHistory.student_id.label("student_id"),
            func.max(PredictionHistory.id).label("latest_id"),
        ).group_by(PredictionHistory.student_id).subquery()
        return (
            self.db.query(PredictionHistory)
            .join(latest_ids, PredictionHistory.id == latest_ids.c.latest_id)
            .order_by(PredictionHistory.created_at.desc(), PredictionHistory.id.desc())
            .all()
        )

    def get_latest_prediction_for_student(self, student_id: int) -> PredictionHistory | None:
        return (
            self.db.query(PredictionHistory)
            .filter(PredictionHistory.student_id == student_id)
            .order_by(PredictionHistory.created_at.desc(), PredictionHistory.id.desc())
            .first()
        )

    def get_prediction_history_by_id(self, prediction_history_id: int) -> PredictionHistory | None:
        return self.db.get(PredictionHistory, prediction_history_id)
