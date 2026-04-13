from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db.database import Base


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    student_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    faculty_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    faculty_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    counsellor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    counsellor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_relationship: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parent_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    preferred_guardian_channel: Mapped[str | None] = mapped_column(String(30), nullable=True)
    guardian_contact_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    external_student_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    profile_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    gender: Mapped[str] = mapped_column(String(20))
    highest_education: Mapped[str] = mapped_column(String(100))
    age_band: Mapped[str] = mapped_column(String(20))
    disability_status: Mapped[str] = mapped_column(String(10))
    num_previous_attempts: Mapped[float] = mapped_column(Float)


class LMSEvent(Base):
    __tablename__ = "lms_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    code_module: Mapped[str] = mapped_column(String(20))
    code_presentation: Mapped[str] = mapped_column(String(20))
    id_site: Mapped[int] = mapped_column(Integer)
    event_date: Mapped[int] = mapped_column(Integer, index=True)
    sum_click: Mapped[int] = mapped_column(Integer)
    context_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ERPEvent(Base):
    __tablename__ = "erp_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    code_module: Mapped[str] = mapped_column(String(20))
    code_presentation: Mapped[str] = mapped_column(String(20))
    assessment_submission_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    weighted_assessment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    late_submission_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_assessments_completed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assessment_score_trend: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class FinanceEvent(Base):
    __tablename__ = "finance_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    fee_overdue_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    fee_delay_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    modifier_candidate: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PredictionHistory(Base):
    __tablename__ = "prediction_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    champion_model: Mapped[str] = mapped_column(String(100))
    threshold: Mapped[float] = mapped_column(Float)
    base_predicted_class: Mapped[int] = mapped_column(Integer)
    base_risk_probability: Mapped[float] = mapped_column(Float)
    finance_modifier: Mapped[float] = mapped_column(Float)
    final_risk_probability: Mapped[float] = mapped_column(Float)
    final_predicted_class: Mapped[int] = mapped_column(Integer)
    challenger_predictions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_insights: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_trend: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    stability: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_type: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    recommended_actions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    trigger_alerts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    prediction_history_id: Mapped[int] = mapped_column(
        ForeignKey("prediction_history.id"),
        index=True,
    )
    alert_type: Mapped[str] = mapped_column(String(50), index=True)
    risk_level: Mapped[str] = mapped_column(String(20))
    final_risk_probability: Mapped[float] = mapped_column(Float)
    recipient: Mapped[str] = mapped_column(String(255))
    email_status: Mapped[str] = mapped_column(String(20), index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class GuardianAlertEvent(Base):
    __tablename__ = "guardian_alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    prediction_history_id: Mapped[int] = mapped_column(
        ForeignKey("prediction_history.id"),
        index=True,
    )
    alert_type: Mapped[str] = mapped_column(String(50), index=True)
    risk_level: Mapped[str] = mapped_column(String(20))
    final_risk_probability: Mapped[float] = mapped_column(Float)
    guardian_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guardian_relationship: Mapped[str | None] = mapped_column(String(50), nullable=True)
    recipient: Mapped[str] = mapped_column(String(255))
    channel: Mapped[str] = mapped_column(String(30), index=True)
    delivery_status: Mapped[str] = mapped_column(String(30), index=True)
    provider_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class StudentWarningEvent(Base):
    __tablename__ = "student_warning_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    prediction_history_id: Mapped[int] = mapped_column(
        ForeignKey("prediction_history.id"),
        index=True,
    )
    warning_type: Mapped[str] = mapped_column(String(50), index=True)
    risk_level: Mapped[str] = mapped_column(String(20))
    final_risk_probability: Mapped[float] = mapped_column(Float)
    recipient: Mapped[str] = mapped_column(String(255))
    delivery_status: Mapped[str] = mapped_column(String(20), index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    recovery_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_status: Mapped[str | None] = mapped_column(String(30), nullable=True)


class InterventionAction(Base):
    __tablename__ = "intervention_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(Integer, index=True)
    alert_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("alert_events.id"),
        nullable=True,
        index=True,
    )
    action_status: Mapped[str] = mapped_column(String(30), index=True)
    actor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    alert_validity: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    false_alert_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome_status: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    outcome_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_recorded_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class FacultySummarySnapshot(Base):
    __tablename__ = "faculty_summary_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_type: Mapped[str] = mapped_column(String(30), index=True)
    summary_payload: Mapped[dict] = mapped_column(JSON)
    email_delivery_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_type: Mapped[str] = mapped_column(String(50), index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CopilotChatSession(Base):
    __tablename__ = "copilot_chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_subject: Mapped[str] = mapped_column(String(255), index=True)
    owner_role: Mapped[str] = mapped_column(String(30), index=True)
    owner_student_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New chat")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    system_prompt_version: Mapped[str] = mapped_column(String(30), nullable=False, default="cb1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class CopilotChatMessage(Base):
    __tablename__ = "copilot_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("copilot_chat_sessions.id"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    message_type: Mapped[str] = mapped_column(String(30), nullable=False, default="text")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class CopilotAuditEvent(Base):
    __tablename__ = "copilot_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("copilot_chat_sessions.id"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("copilot_chat_messages.id"),
        nullable=True,
        index=True,
    )
    owner_subject: Mapped[str] = mapped_column(String(255), index=True)
    owner_role: Mapped[str] = mapped_column(String(30), index=True)
    owner_student_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    detected_intent: Mapped[str | None] = mapped_column(String(60), nullable=True)
    resolved_intent: Mapped[str | None] = mapped_column(String(60), nullable=True)
    memory_applied: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    tool_summaries: Mapped[list | None] = mapped_column(JSON, nullable=True)
    refusal_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
