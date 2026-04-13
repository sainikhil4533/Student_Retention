from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class PredictionRequest(BaseModel):
    gender: str
    highest_education: str
    age_band: str
    disability_status: str
    num_previous_attempts: float
    lms_clicks_7d: float
    lms_clicks_14d: float
    lms_clicks_30d: float
    lms_unique_resources_7d: float
    days_since_last_lms_activity: float
    lms_7d_vs_14d_percent_change: float
    engagement_acceleration: float
    assessment_submission_rate: float
    weighted_assessment_score: float
    late_submission_count: float
    total_assessments_completed: float
    assessment_score_trend: float


class ModelPrediction(BaseModel):
    model_name: str
    is_champion: bool
    predicted_class: int
    predicted_risk_probability: float


class ChampionPredictionResponse(BaseModel):
    champion_model: str
    threshold: float
    predicted_class: int
    predicted_risk_probability: float


class PredictionResponse(BaseModel):
    champion_prediction: ModelPrediction
    challenger_predictions: list[ModelPrediction]


class ModelConfigResponse(BaseModel):
    champion_model: str
    threshold: float
    evaluation_type: str


class LMSIngestionRequest(BaseModel):
    student_id: int
    code_module: str
    code_presentation: str
    id_site: int
    event_date: int
    sum_click: int
    context_fields: dict | None = None


class LMSIngestionResponse(BaseModel):
    status: str
    source: str
    ingested_count: int
    duplicate_ignored: bool = False
    auto_score_triggered: bool = False


class ERPIngestionRequest(BaseModel):
    student_id: int
    code_module: str
    code_presentation: str
    assessment_submission_rate: float | None = None
    weighted_assessment_score: float | None = None
    late_submission_count: int | None = None
    total_assessments_completed: int | None = None
    assessment_score_trend: float | None = None
    context_fields: dict | None = None


class ERPIngestionResponse(BaseModel):
    status: str
    source: str
    ingested_count: int
    duplicate_ignored: bool = False
    auto_score_triggered: bool = False
    student_warning_triggered: bool = False
    student_warning_type: str | None = None
    student_warning_status: str | None = None
    recovery_deadline: datetime | None = None
    alert_triggered: bool = False
    alert_type: str | None = None
    alert_status: str | None = None


class FinanceIngestionRequest(BaseModel):
    student_id: int
    fee_overdue_amount: float | None = None
    fee_delay_days: int | None = None
    payment_status: str | None = None
    modifier_candidate: float | None = None
    context_fields: dict | None = None


class FinanceIngestionResponse(BaseModel):
    status: str
    source: str
    ingested_count: int
    duplicate_ignored: bool = False
    auto_score_triggered: bool = False


class StudentContext(BaseModel):
    student_id: int
    student_email: str | None = None
    faculty_name: str | None = None
    faculty_email: str | None = None
    counsellor_name: str | None = None
    counsellor_email: str | None = None
    parent_name: str | None = None
    parent_relationship: str | None = None
    parent_email: str | None = None
    parent_phone: str | None = None
    preferred_guardian_channel: str | None = None
    guardian_contact_enabled: bool = False
    external_student_ref: str | None = None
    profile_context: dict | None = None
    gender: str
    highest_education: str
    age_band: str
    disability_status: str
    num_previous_attempts: float


class ScoreStudentRequest(BaseModel):
    demographics: StudentContext


class StudentProfileUpsertRequest(StudentContext):
    pass


class StudentProfileResponse(StudentContext):
    pass


class AuthLoginRequest(BaseModel):
    username: str
    password: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str
    role: str
    student_id: int | None = None
    display_name: str | None = None


class AuthMeResponse(BaseModel):
    role: str
    subject: str
    student_id: int | None = None
    display_name: str | None = None
    auth_provider: str | None = None


class StudentGuidance(BaseModel):
    summary: str
    suggestions: list[str]
    motivation: str


class AIInsights(BaseModel):
    source: str | None = None
    confidence: str
    reasoning: str
    actions: list[str]
    urgency: str
    timeline: str
    student_guidance: StudentGuidance


class RiskTrendSummary(BaseModel):
    trend_score: int
    trend_label: str
    trend_direction: str
    current_probability: float | None = None
    previous_probability: float | None = None
    probability_change: float | None = None
    high_risk_count_7d: int = 0
    high_risk_count_14d: int = 0
    high_risk_count_30d: int = 0
    summary: str


class RiskTypeSummary(BaseModel):
    primary_type: str
    secondary_type: str | None = None
    summary: str
    category_scores: dict[str, int]


class StabilitySummary(BaseModel):
    stability_score: int
    stability_label: str
    threshold_distance: float
    model_agreement_ratio: float
    probability_spread: float
    recent_volatility: float
    summary: str


class TriggerAlertItem(BaseModel):
    trigger_code: str
    title: str
    severity: str
    rationale: str
    recommended_action: str


class TriggerAlertSummary(BaseModel):
    triggers: list[TriggerAlertItem]
    has_critical_trigger: bool = False
    trigger_count: int = 0
    summary: str


class ActivitySummary(BaseModel):
    last_meaningful_activity_at: datetime | None = None
    last_meaningful_activity_source: str | None = None
    days_since_last_meaningful_activity: float | None = None
    latest_lms_event_day: int | None = None
    summary: str


class MilestoneFlagsSummary(BaseModel):
    repeat_attempt_flag: bool = False
    first_year_flag: bool = False
    backlog_heavy_flag: bool = False
    pre_exam_phase_flag: bool = False
    fee_pressure_flag: bool = False
    active_flags: list[str] = []
    summary: str


class SLASummary(BaseModel):
    sla_status: str
    hours_since_latest_prediction: float | None = None
    hours_since_warning_created: float | None = None
    hours_to_first_faculty_action: float | None = None
    hours_open_without_faculty_action: float | None = None
    followup_overdue: bool = False
    summary: str


class RecommendedActionItem(BaseModel):
    action_code: str
    title: str
    priority: str
    rationale: str


class ScoreStudentResponse(BaseModel):
    champion_prediction: ModelPrediction
    challenger_predictions: list[ModelPrediction]
    finance_modifier: float
    final_risk_probability: float
    final_predicted_class: int
    ai_insights: AIInsights
    risk_trend: RiskTrendSummary
    stability: StabilitySummary
    risk_type: RiskTypeSummary
    recommended_actions: list[RecommendedActionItem]
    trigger_alerts: TriggerAlertSummary
    student_warning_triggered: bool = False
    student_warning_status: str | None = None
    student_warning_type: str | None = None
    recovery_deadline: datetime | None = None
    alert_triggered: bool = False
    alert_type: str | None = None
    alert_status: str | None = None


class PredictionHistoryItem(BaseModel):
    student_id: int
    champion_model: str
    threshold: float
    base_predicted_class: int
    base_risk_probability: float
    finance_modifier: float
    final_risk_probability: float
    final_predicted_class: int
    challenger_predictions: list[dict] | None = None
    ai_insights: AIInsights | None = None
    risk_trend: RiskTrendSummary | None = None
    stability: StabilitySummary | None = None
    risk_type: RiskTypeSummary | None = None
    recommended_actions: list[RecommendedActionItem] = []
    trigger_alerts: TriggerAlertSummary | None = None
    created_at: datetime | None = None


class PredictionHistoryResponse(BaseModel):
    student_id: int
    history: list[PredictionHistoryItem]


class AlertEventItem(BaseModel):
    student_id: int
    prediction_history_id: int
    alert_type: str
    risk_level: str
    final_risk_probability: float
    recipient: str
    email_status: str
    retry_count: int = 0
    error_message: str | None = None
    sent_at: datetime | None = None


class AlertHistoryResponse(BaseModel):
    student_id: int
    alerts: list[AlertEventItem]


class GuardianEscalationEvaluationResponse(BaseModel):
    student_id: int
    should_send: bool
    alert_type: str | None = None
    reason: str
    channel: str | None = None
    severity: str
    recipient: str | None = None
    guardian_name: str | None = None
    guardian_relationship: str | None = None
    guardian_contact_enabled: bool = False
    repeat_high_risk_count: int = 0
    high_risk_cycle_count: int = 0
    has_relapsed_after_recovery: bool = False
    has_relapsed_after_resolution: bool = False
    is_critical_unattended_case: bool = False
    latest_prediction_id: int | None = None


class GuardianAlertEventItem(BaseModel):
    id: int | None = None
    student_id: int
    prediction_history_id: int
    alert_type: str
    risk_level: str
    final_risk_probability: float
    guardian_name: str | None = None
    guardian_relationship: str | None = None
    recipient: str
    channel: str
    delivery_status: str
    provider_name: str | None = None
    provider_message_id: str | None = None
    retry_count: int = 0
    error_message: str | None = None
    context_snapshot: dict | None = None
    sent_at: datetime | None = None


class GuardianAlertHistoryResponse(BaseModel):
    student_id: int
    alerts: list[GuardianAlertEventItem]


class GuardianAlertQueueResponse(BaseModel):
    queued: bool
    deduplicated: bool = False
    message: str
    evaluation: GuardianEscalationEvaluationResponse
    alert: GuardianAlertEventItem | None = None


class StudentWarningEventItem(BaseModel):
    student_id: int
    prediction_history_id: int
    warning_type: str
    risk_level: str
    final_risk_probability: float
    recipient: str
    delivery_status: str
    retry_count: int = 0
    error_message: str | None = None
    sent_at: datetime | None = None
    recovery_deadline: datetime | None = None
    resolved_at: datetime | None = None
    resolution_status: str | None = None


class StudentWarningHistoryResponse(BaseModel):
    student_id: int
    warnings: list[StudentWarningEventItem]


class TimelineEventItem(BaseModel):
    event_time: datetime | None = None
    event_type: str
    title: str
    status: str | None = None
    student_id: int
    prediction_history_id: int | None = None
    warning_event_id: int | None = None
    alert_event_id: int | None = None
    risk_level: str | None = None
    final_risk_probability: float | None = None
    details: dict | None = None


class StudentTimelineResponse(BaseModel):
    student_id: int
    timeline: list[TimelineEventItem]


class RecoveryScorecardResponse(BaseModel):
    student_id: int
    warning_event_id: int | None = None
    warning_type: str | None = None
    warning_sent_at: datetime | None = None
    recovery_deadline: datetime | None = None
    recovery_window_status: str
    resolution_status: str | None = None
    student_warning_status: str | None = None
    faculty_alert_status: str | None = None
    faculty_alert_type: str | None = None
    latest_intervention_status: str | None = None
    latest_intervention_actor: str | None = None
    latest_intervention_notes: str | None = None
    latest_intervention_created_at: datetime | None = None
    baseline_risk_level: str | None = None
    current_risk_level: str | None = None
    baseline_final_risk_probability: float | None = None
    current_final_risk_probability: float | None = None
    risk_probability_change: float | None = None
    improvement_status: str
    attendance_recovery_status: str = "unavailable"
    current_attendance_ratio: float | None = None
    current_attendance_trend: float | None = None
    consecutive_absences: float | None = None
    low_attendance_subjects: list[str] = []
    candidate_for_resolution: bool = False
    resolution_candidate_reason: str | None = None
    latest_prediction_created_at: datetime | None = None
    summary: str


class RiskDriverItem(BaseModel):
    driver_name: str
    severity: str
    evidence: str


class RiskDriverResponse(BaseModel):
    student_id: int
    risk_level: str
    final_risk_probability: float
    risk_trend: RiskTrendSummary
    stability: StabilitySummary
    risk_type: RiskTypeSummary
    recommended_actions: list[RecommendedActionItem]
    trigger_alerts: TriggerAlertSummary
    drivers: list[RiskDriverItem]


class FacultyPriorityQueueItem(BaseModel):
    student_id: int
    priority_score: int
    priority_label: str
    queue_reason: str
    current_risk_level: str
    final_risk_probability: float
    risk_trend_score: int
    risk_trend_label: str
    stability_score: int
    stability_label: str
    risk_type: str
    recommended_next_action: str | None = None
    active_trigger_codes: list[str] = []
    has_critical_trigger: bool = False
    last_meaningful_activity_at: datetime | None = None
    last_meaningful_activity_source: str | None = None
    active_milestone_flags: list[str] = []
    sla_status: str = "not_applicable"
    followup_overdue: bool = False
    recovery_window_status: str
    warning_status: str | None = None
    faculty_alert_status: str | None = None
    faculty_alert_type: str | None = None
    latest_intervention_status: str | None = None
    repeat_high_risk_count: int
    high_risk_cycle_count: int
    has_relapsed_after_recovery: bool
    has_relapsed_after_resolution: bool
    is_repeated_risk_case: bool
    is_reopened_case: bool
    is_critical_unattended_case: bool
    latest_prediction_created_at: datetime | None = None


class FacultyPriorityQueueResponse(BaseModel):
    total_students: int
    queue: list[FacultyPriorityQueueItem]


class FacultySummaryStudentItem(BaseModel):
    student_id: int
    risk_level: str | None = None
    final_risk_probability: float | None = None
    status: str
    event_time: datetime | None = None
    note: str | None = None


class FacultySummaryResponse(BaseModel):
    generated_at: datetime | None = None
    total_active_high_risk_students: int
    total_active_recovery_windows: int
    total_expired_recovery_windows: int
    total_escalated_cases: int
    total_followup_reminders_sent: int
    total_resolution_candidates: int
    total_reopened_cases: int
    total_critical_unattended_cases: int
    total_repeated_risk_students: int
    total_unhandled_escalations: int
    active_recovery_students: list[FacultySummaryStudentItem]
    expired_recovery_students: list[FacultySummaryStudentItem]
    escalated_students: list[FacultySummaryStudentItem]
    followup_reminder_students: list[FacultySummaryStudentItem]
    resolution_candidate_students: list[FacultySummaryStudentItem]
    reopened_case_students: list[FacultySummaryStudentItem]
    critical_unattended_case_students: list[FacultySummaryStudentItem]
    repeated_risk_students: list[FacultySummaryStudentItem]
    unhandled_escalation_students: list[FacultySummaryStudentItem]


class RepeatedRiskResponse(BaseModel):
    student_id: int
    total_predictions: int
    high_risk_prediction_count: int
    high_risk_cycle_count: int
    currently_high_risk: bool
    is_repeated_risk_case: bool
    has_relapsed_after_recovery: bool
    has_relapsed_after_resolution: bool
    is_reopened_case: bool
    latest_prediction_created_at: datetime | None = None
    summary: str


class RepeatedRiskReportResponse(BaseModel):
    total_students: int
    students: list[RepeatedRiskResponse]


class InterventionActionCreateRequest(BaseModel):
    student_id: int
    alert_event_id: int | None = None
    action_status: str
    actor_name: str | None = None
    notes: str | None = None


class InterventionReviewRequest(BaseModel):
    intervention_id: int
    alert_validity: Literal["valid_alert", "false_alert"]
    false_alert_reason: str | None = None
    reviewed_by: str | None = None


class InterventionOutcomeRequest(BaseModel):
    intervention_id: int
    outcome_status: Literal["improved", "no_change", "worsened", "unresolved"]
    outcome_notes: str | None = None
    outcome_recorded_by: str | None = None


class InterventionActionItem(BaseModel):
    id: int | None = None
    student_id: int
    alert_event_id: int | None = None
    action_status: str
    actor_name: str | None = None
    notes: str | None = None
    alert_validity: str | None = None
    false_alert_reason: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    outcome_status: str | None = None
    outcome_notes: str | None = None
    outcome_recorded_by: str | None = None
    outcome_recorded_at: datetime | None = None
    created_at: datetime | None = None


class InterventionHistoryResponse(BaseModel):
    student_id: int
    interventions: list[InterventionActionItem]


class InterventionEffectivenessItem(BaseModel):
    action_status: str
    total_actions: int
    reviewed_actions: int
    review_rate: float
    false_alert_count: int
    false_alert_rate: float
    outcomes_recorded: int
    improved_count: int
    unresolved_count: int
    effectiveness_score: float
    summary: str


class InterventionEffectivenessResponse(BaseModel):
    total_actions: int
    total_reviewed_actions: int
    total_false_alerts: int
    total_valid_alerts: int
    total_outcomes_recorded: int
    total_improved_cases: int
    total_unresolved_cases: int
    review_coverage_percent: float
    improvement_rate_percent: float
    false_alert_rate_percent: float
    summary: str
    action_effectiveness: list[InterventionEffectivenessItem]


class InstitutionBucketSummary(BaseModel):
    label: str
    total_students: int
    high_risk_students: int
    critical_trigger_students: int
    followup_overdue_students: int
    guardian_escalation_students: int
    reopened_cases: int
    repeated_risk_students: int
    average_risk_probability: float
    risk_type_distribution: dict[str, int]
    summary: str


class InstitutionHeatmapCell(BaseModel):
    department_label: str
    semester_label: str
    total_students: int
    high_risk_students: int
    critical_trigger_students: int
    guardian_escalation_students: int
    average_risk_probability: float


class RiskTypeDistributionItem(BaseModel):
    risk_type: str
    student_count: int


class OutcomeDistributionItem(BaseModel):
    outcome_status: str
    student_count: int


class InstitutionRiskOverviewResponse(BaseModel):
    generated_at: datetime | None = None
    total_students: int
    total_high_risk_students: int
    total_critical_trigger_students: int
    total_followup_overdue_students: int
    total_guardian_escalation_students: int
    total_reopened_cases: int
    total_repeated_risk_students: int
    total_dropped_students: int
    total_studying_students: int
    total_graduated_students: int
    department_buckets: list[InstitutionBucketSummary]
    semester_buckets: list[InstitutionBucketSummary]
    category_buckets: list[InstitutionBucketSummary] = []
    region_buckets: list[InstitutionBucketSummary] = []
    income_buckets: list[InstitutionBucketSummary] = []
    heatmap_cells: list[InstitutionHeatmapCell]
    top_risk_types: list[RiskTypeDistributionItem]
    outcome_distribution: list[OutcomeDistributionItem]
    summary: str


class AICaseSummaryResponse(BaseModel):
    source: str
    headline: str
    summary: str
    key_points: list[str]
    recommended_followup: list[str]


class AICommunicationDraftResponse(BaseModel):
    source: str
    audience: str
    subject: str
    opening: str
    body: str
    closing: str


class AIGuardianCommunicationDraftResponse(BaseModel):
    source: str
    channel: str
    guardian_name: str
    subject: str
    opening: str
    body: str
    closing: str
    compact_text: str


class AIRecoveryPlanResponse(BaseModel):
    source: str
    plan_summary: str
    weekly_priorities: list[str]
    support_actions: list[str]
    success_signals: list[str]


class StudentCaseStateResponse(BaseModel):
    student_id: int
    current_case_state: str
    risk_level: str | None = None
    final_risk_probability: float | None = None
    latest_prediction_created_at: datetime | None = None
    warning_status: str | None = None
    warning_resolution_status: str | None = None
    faculty_alert_type: str | None = None
    faculty_alert_status: str | None = None
    guardian_alert_type: str | None = None
    guardian_alert_status: str | None = None
    guardian_alert_channel: str | None = None
    guardian_alert_sent_at: datetime | None = None
    latest_intervention_status: str | None = None
    candidate_for_resolution: bool = False
    is_reopened_case: bool = False
    is_critical_unattended_case: bool = False
    last_meaningful_activity_at: datetime | None = None
    last_meaningful_activity_source: str | None = None
    active_milestone_flags: list[str] = []
    sla_status: str = "not_applicable"
    followup_overdue: bool = False
    summary: str


class ActiveCasesResponse(BaseModel):
    total_students: int
    cases: list[StudentCaseStateResponse]


class FacultySummarySnapshotItem(BaseModel):
    id: int
    snapshot_type: str
    email_delivery_status: str | None = None
    email_error_message: str | None = None
    emailed_at: datetime | None = None
    generated_at: datetime | None = None
    summary: FacultySummaryResponse
    institution_overview: InstitutionRiskOverviewResponse | None = None
    intervention_effectiveness: InterventionEffectivenessResponse | None = None


class FacultySummarySnapshotHistoryResponse(BaseModel):
    total_snapshots: int
    snapshots: list[FacultySummarySnapshotItem]


class OperationalReportOverviewResponse(BaseModel):
    generated_at: datetime | None = None
    summary: FacultySummaryResponse
    institution_overview: InstitutionRiskOverviewResponse
    intervention_effectiveness: InterventionEffectivenessResponse


class StudentOperationalContextResponse(BaseModel):
    student_id: int
    risk_level: str | None = None
    final_risk_probability: float | None = None
    activity_summary: ActivitySummary
    milestone_flags: MilestoneFlagsSummary
    sla_summary: SLASummary


class StudentSelfOverviewResponse(BaseModel):
    student_id: int
    profile: StudentProfileResponse
    latest_prediction: PredictionHistoryItem
    warning_history: StudentWarningHistoryResponse
    recovery_plan: AIRecoveryPlanResponse


class VignanImportResponse(BaseModel):
    status: str
    total_students: int
    profiles_upserted: int
    support_mappings_applied: int = 0
    lms_events_ingested: int
    erp_events_ingested: int
    finance_events_ingested: int
    scoring_triggered: int
    errors: list[str] = []


class ImportCoverageStudentItem(BaseModel):
    student_id: int
    external_student_ref: str | None = None
    student_email: str | None = None
    faculty_email: str | None = None
    counsellor_email: str | None = None
    has_lms_data: bool
    has_erp_data: bool
    has_finance_data: bool
    has_prediction: bool
    outcome_status: str | None = None
    missing_reasons: list[str] = []


class ImportCoverageResponse(BaseModel):
    total_imported_students: int
    scored_students: int
    unscored_students: int
    students_missing_lms: int
    students_missing_erp: int
    students_missing_finance: int
    students_missing_student_email: int
    students_missing_faculty_email: int
    students_missing_counsellor_email: int
    students: list[ImportCoverageStudentItem]


class CopilotChatMessageRequest(BaseModel):
    content: str


class CopilotChatSessionCreateRequest(BaseModel):
    title: str | None = None
    opening_message: str | None = None


class CopilotChatMessageItem(BaseModel):
    id: int
    session_id: int
    role: str
    message_type: str
    content: str
    metadata_json: dict | None = None
    created_at: datetime | None = None


class CopilotChatSessionItem(BaseModel):
    id: int
    title: str
    status: str
    owner_role: str
    owner_student_id: int | None = None
    display_name: str | None = None
    system_prompt_version: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_message_at: datetime | None = None


class CopilotChatSessionResponse(BaseModel):
    session: CopilotChatSessionItem
    messages: list[CopilotChatMessageItem]


class CopilotChatSessionListResponse(BaseModel):
    total_sessions: int
    sessions: list[CopilotChatSessionItem]


class CopilotChatReplyResponse(BaseModel):
    session: CopilotChatSessionItem
    user_message: CopilotChatMessageItem
    assistant_message: CopilotChatMessageItem


class CopilotAuditEventItem(BaseModel):
    id: int
    session_id: int
    message_id: int | None = None
    owner_subject: str
    owner_role: str
    owner_student_id: int | None = None
    detected_intent: str | None = None
    resolved_intent: str | None = None
    memory_applied: bool = False
    tool_summaries: list | None = None
    refusal_reason: str | None = None
    created_at: datetime | None = None


class CopilotAuditListResponse(BaseModel):
    total_events: int
    events: list[CopilotAuditEventItem]


class CopilotToolUseItem(BaseModel):
    tool_name: str
    summary: str


class CopilotGroundedAnswerResponse(BaseModel):
    answer: str
    tools_used: list[CopilotToolUseItem] = []
    limitations: list[str] = []
