export type RoleName = "student" | "counsellor" | "admin" | "system";

export type QueryPlan = {
  user_goal?: string;
  clarification_needed?: boolean;
  analysis_mode?: string;
  [key: string]: unknown;
};

export type CopilotMessage = {
  id: number;
  session_id: number;
  role: "assistant" | "user";
  message_type: string;
  content: string;
  metadata_json?: {
    phase?: string;
    response_mode?: string;
    limitations?: string[];
    query_plan?: QueryPlan;
    safety_marker?: {
      refusal_reason?: string | null;
      [key: string]: unknown;
    };
    [key: string]: unknown;
  };
  created_at?: string | null;
};

export type CopilotSession = {
  id: number;
  title: string;
  status: string;
  owner_role: RoleName;
  owner_student_id?: number | null;
  display_name?: string | null;
  system_prompt_version: string;
  created_at?: string | null;
};

export type StudentOverview = {
  student_id: number;
  profile: {
    faculty_name?: string | null;
    counsellor_name?: string | null;
    external_student_ref?: string | null;
    profile_context?: Record<string, unknown> | null;
  };
  latest_prediction: {
    final_risk_probability: number;
    final_predicted_class: number;
    risk_type?: { primary_type?: string; summary?: string } | null;
    risk_trend?: { trend_label?: string; summary?: string } | null;
    recommended_actions?: Array<{ title: string; rationale: string }>;
    trigger_alerts?: { trigger_count?: number; has_critical_trigger?: boolean; summary?: string } | null;
    ai_insights?: { student_guidance?: { summary?: string; motivation?: string } } | null;
    created_at?: string | null;
  };
  warning_history: {
    warnings: Array<{
      warning_type: string;
      resolution_status?: string | null;
      recovery_deadline?: string | null;
    }>;
  };
  recovery_plan: {
    summary: string;
    key_points: string[];
    recommended_followup: string[];
  };
};

export type TimelineEvent = {
  event_time?: string | null;
  event_type: string;
  title: string;
  status?: string | null;
  risk_level?: string | null;
  final_risk_probability?: number | null;
  details?: Record<string, unknown> | null;
};

export type StudentTimeline = {
  student_id: number;
  timeline: TimelineEvent[];
};

export type StudentCaseState = {
  student_id: number;
  current_case_state: string;
  risk_level?: string | null;
  final_risk_probability?: number | null;
  latest_prediction_created_at?: string | null;
  warning_status?: string | null;
  warning_resolution_status?: string | null;
  faculty_alert_type?: string | null;
  faculty_alert_status?: string | null;
  guardian_alert_type?: string | null;
  guardian_alert_status?: string | null;
  guardian_alert_channel?: string | null;
  guardian_alert_sent_at?: string | null;
  latest_intervention_status?: string | null;
  candidate_for_resolution: boolean;
  is_reopened_case: boolean;
  is_critical_unattended_case: boolean;
  last_meaningful_activity_at?: string | null;
  last_meaningful_activity_source?: string | null;
  active_milestone_flags: string[];
  sla_status: string;
  followup_overdue: boolean;
  summary: string;
};

export type ActiveCasesResponse = {
  total_students: number;
  cases: StudentCaseState[];
};

export type StudentOperationalContext = {
  student_id: number;
  risk_level?: string | null;
  final_risk_probability?: number | null;
  activity_summary: {
    last_meaningful_activity_at?: string | null;
    last_meaningful_activity_source?: string | null;
    days_since_last_meaningful_activity?: number | null;
    latest_lms_event_day?: number | null;
    summary: string;
  };
  milestone_flags: {
    active_flags: string[];
    summary: string;
  };
  sla_summary: {
    sla_status: string;
    followup_overdue: boolean;
    summary: string;
  };
};

export type InterventionHistory = {
  student_id: number;
  interventions: Array<{
    id?: number | null;
    student_id: number;
    alert_event_id?: number | null;
    action_status: string;
    actor_name?: string | null;
    notes?: string | null;
    alert_validity?: string | null;
    false_alert_reason?: string | null;
    reviewed_by?: string | null;
    reviewed_at?: string | null;
    outcome_status?: string | null;
    outcome_notes?: string | null;
    outcome_recorded_by?: string | null;
    outcome_recorded_at?: string | null;
    created_at?: string | null;
  }>;
};

export type FacultySummary = {
  total_active_high_risk_students: number;
  total_active_recovery_windows: number;
  total_expired_recovery_windows: number;
  total_escalated_cases: number;
  total_followup_reminders_sent: number;
  total_resolution_candidates: number;
  total_reopened_cases: number;
  total_critical_unattended_cases: number;
  total_repeated_risk_students: number;
  total_unhandled_escalations: number;
};

export type FacultyPriorityQueue = {
  total_students: number;
  queue: Array<{
    student_id: number;
    priority_score: number;
    priority_label: string;
    queue_reason: string;
    current_risk_level: string;
    final_risk_probability?: number | null;
    recommended_next_action?: string | null;
    risk_type?: string | null;
  }>;
};

export type InstitutionOverview = {
  total_students: number;
  total_high_risk_students: number;
  total_dropped_students: number;
  total_studying_students: number;
  total_graduated_students: number;
  total_followup_overdue_students: number;
  total_guardian_escalation_students: number;
  department_buckets: Array<{ bucket_label: string; total_students: number; high_risk_students: number }>;
  category_buckets: Array<{ bucket_label: string; total_students: number; high_risk_students: number }>;
  region_buckets: Array<{ bucket_label: string; total_students: number; high_risk_students: number }>;
  outcome_distribution: Array<{ outcome_status: string; student_count: number }>;
  summary: string;
};

export type ImportCoverage = {
  total_imported_students: number;
  scored_students: number;
  unscored_students: number;
  students_missing_lms: number;
  students_missing_erp: number;
  students_missing_finance: number;
  students_missing_student_email: number;
  students_missing_faculty_email: number;
  students_missing_counsellor_email: number;
};

export type OperationalOverview = {
  generated_at?: string | null;
  summary: FacultySummary;
  institution_overview: InstitutionOverview;
  intervention_effectiveness: {
    total_actions: number;
    total_reviewed_actions: number;
    total_false_alerts: number;
    total_valid_alerts: number;
    total_outcomes_recorded: number;
    total_improved_cases: number;
    total_unresolved_cases: number;
    review_coverage_percent: number;
    improvement_rate_percent: number;
    false_alert_rate_percent: number;
    summary: string;
    action_effectiveness: Array<{
      action_status: string;
      total_actions: number;
      outcomes_recorded: number;
      improved_count: number;
      unresolved_count: number;
      effectiveness_score: number;
      summary: string;
    }>;
  };
};
