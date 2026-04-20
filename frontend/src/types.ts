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
  academic_progress: {
    institution_name?: string | null;
    branch?: string | null;
    batch?: string | null;
    current_year?: number | null;
    current_semester?: number | null;
    current_academic_status?: string | null;
    semester_mode?: string | null;
    expected_graduation_year?: number | null;
    standing_label?: string | null;
    total_backlogs?: number | null;
    current_overall_attendance_percent?: number | null;
    current_overall_status?: string | null;
    current_subjects_below_75_count: number;
    current_subjects_below_65_count: number;
    has_i_grade_risk: boolean;
    has_r_grade_risk: boolean;
    academic_risk_band?: string | null;
    active_burden_count: number;
    has_active_i_grade_burden: boolean;
    has_active_r_grade_burden: boolean;
    monitoring_cadence?: string | null;
    academic_burden_summary?: string | null;
    weakest_subject_name?: string | null;
    weakest_subject_percent?: number | null;
    attendance_summary: string;
    active_i_grade_subjects: Array<{
      subject_code?: string | null;
      subject_name?: string | null;
      year?: number | null;
      semester?: number | null;
      raw_result_status?: string | null;
      raw_grade?: string | null;
      attendance_linked_status?: string | null;
      effective_result_status?: string | null;
      effective_grade?: string | null;
      subject_attendance_percent?: number | null;
    }>;
    active_r_grade_subjects: Array<{
      subject_code?: string | null;
      subject_name?: string | null;
      year?: number | null;
      semester?: number | null;
      raw_result_status?: string | null;
      raw_grade?: string | null;
      attendance_linked_status?: string | null;
      effective_result_status?: string | null;
      effective_grade?: string | null;
      subject_attendance_percent?: number | null;
    }>;
    subject_attendance: Array<{
      year?: number | null;
      semester?: number | null;
      subject_code?: string | null;
      subject_name: string;
      subject_type?: string | null;
      overall_attendance_percent?: number | null;
      subject_attendance_percent?: number | null;
      required_percent?: number | null;
      overall_status?: string | null;
      subject_status?: string | null;
      grade_consequence?: string | null;
      condonation_required: boolean;
      summer_repeat_required: boolean;
      internals_repeat_required: boolean;
      end_sem_eligible: boolean;
      classes_conducted?: number | null;
      classes_attended?: number | null;
      consecutive_absences?: number | null;
      missed_days?: number | null;
      trend?: string | null;
    }>;
    semester_progress: Array<{
      year?: number | null;
      semester?: number | null;
      overall_attendance_percent?: number | null;
      overall_status?: string | null;
      subjects_below_75_count?: number | null;
      subjects_below_65_count?: number | null;
      has_i_grade_risk: boolean;
      has_r_grade_risk: boolean;
      current_eligibility?: string | null;
      semester_mode?: string | null;
    }>;
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
  priority_score?: number | null;
  priority_label?: string | null;
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
  academic_context?: {
    institution_name?: string | null;
    branch?: string | null;
    current_year?: number | null;
    current_semester?: number | null;
    semester_mode?: string | null;
    current_academic_status?: string | null;
    standing_label?: string | null;
    overall_attendance_percent?: number | null;
    overall_status?: string | null;
    subjects_below_75_count?: number | null;
    subjects_below_65_count?: number | null;
    has_i_grade_risk?: boolean;
    has_r_grade_risk?: boolean;
    current_eligibility?: string | null;
    academic_risk_band?: string | null;
    active_burden_count?: number | null;
    has_active_i_grade_burden?: boolean;
    has_active_r_grade_burden?: boolean;
    monitoring_cadence?: string | null;
    academic_burden_summary?: string | null;
    active_i_grade_subjects?: Array<{
      subject_code?: string | null;
      subject_name?: string | null;
      year?: number | null;
      semester?: number | null;
      raw_result_status?: string | null;
      raw_grade?: string | null;
      attendance_linked_status?: string | null;
      effective_result_status?: string | null;
      effective_grade?: string | null;
      subject_attendance_percent?: number | null;
    }>;
    active_r_grade_subjects?: Array<{
      subject_code?: string | null;
      subject_name?: string | null;
      year?: number | null;
      semester?: number | null;
      raw_result_status?: string | null;
      raw_grade?: string | null;
      attendance_linked_status?: string | null;
      effective_result_status?: string | null;
      effective_grade?: string | null;
      subject_attendance_percent?: number | null;
    }>;
    weakest_subject_name?: string | null;
    weakest_subject_percent?: number | null;
    weakest_subject_status?: string | null;
    cgpa?: number | null;
    backlogs?: number | null;
    subject_risk_summary?: Array<{
      subject_name: string;
      subject_attendance_percent?: number | null;
      subject_status?: string | null;
      grade_consequence?: string | null;
    }>;
  } | null;
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
  total_students_with_overall_shortage: number;
  total_students_with_i_grade_risk: number;
  total_students_with_r_grade_risk: number;
  total_students_with_active_academic_burden: number;
  total_students_with_active_i_grade_burden: number;
  total_students_with_active_r_grade_burden: number;
  top_subject_pressure: Array<{
    subject_name: string;
    total_students: number;
    students_below_threshold: number;
    i_grade_students: number;
    r_grade_students: number;
    average_attendance_percent?: number | null;
    summary: string;
  }>;
  branch_pressure: Array<{
    bucket_label: string;
    total_students: number;
    students_with_overall_shortage: number;
    students_with_i_grade_risk: number;
    students_with_r_grade_risk: number;
    average_overall_attendance_percent?: number | null;
    summary: string;
  }>;
  semester_pressure: Array<{
    bucket_label: string;
    total_students: number;
    students_with_overall_shortage: number;
    students_with_i_grade_risk: number;
    students_with_r_grade_risk: number;
    average_overall_attendance_percent?: number | null;
    summary: string;
  }>;
  academic_burden_monitoring_students: Array<{
    student_id: number;
    risk_level?: string | null;
    final_risk_probability?: number | null;
    status: string;
    event_time?: string | null;
    note?: string | null;
  }>;
};

export type FacultyDashboardSummary = {
  total_active_high_risk_students: number;
  total_critical_unattended_cases: number;
  total_students_with_overall_shortage: number;
  total_students_with_i_grade_risk: number;
  total_students_with_r_grade_risk: number;
  total_students_with_active_academic_burden: number;
  total_students_with_active_i_grade_burden: number;
  total_students_with_active_r_grade_burden: number;
  top_subject_pressure: Array<{
    subject_name: string;
    total_students: number;
    students_below_threshold: number;
    i_grade_students: number;
    r_grade_students: number;
    average_attendance_percent?: number | null;
    summary: string;
  }>;
  branch_pressure: Array<{
    bucket_label: string;
    total_students: number;
    students_with_overall_shortage: number;
    students_with_i_grade_risk: number;
    students_with_r_grade_risk: number;
    average_overall_attendance_percent?: number | null;
    summary: string;
  }>;
  semester_pressure: Array<{
    bucket_label: string;
    total_students: number;
    students_with_overall_shortage: number;
    students_with_i_grade_risk: number;
    students_with_r_grade_risk: number;
    average_overall_attendance_percent?: number | null;
    summary: string;
  }>;
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
    has_active_academic_burden: boolean;
    academic_risk_band?: string | null;
    monitoring_cadence?: string | null;
    active_burden_count: number;
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
  total_students_with_overall_shortage: number;
  total_students_with_i_grade_risk: number;
  total_students_with_r_grade_risk: number;
  department_buckets: Array<{ bucket_label: string; total_students: number; high_risk_students: number }>;
  category_buckets: Array<{ bucket_label: string; total_students: number; high_risk_students: number }>;
  region_buckets: Array<{ bucket_label: string; total_students: number; high_risk_students: number }>;
  top_subject_pressure: Array<{
    subject_name: string;
    total_students: number;
    students_below_threshold: number;
    i_grade_students: number;
    r_grade_students: number;
    average_attendance_percent?: number | null;
    summary: string;
  }>;
  branch_pressure: Array<{
    bucket_label: string;
    total_students: number;
    students_with_overall_shortage: number;
    students_with_i_grade_risk: number;
    students_with_r_grade_risk: number;
    average_overall_attendance_percent?: number | null;
    summary: string;
  }>;
  semester_pressure: Array<{
    bucket_label: string;
    total_students: number;
    students_with_overall_shortage: number;
    students_with_i_grade_risk: number;
    students_with_r_grade_risk: number;
    average_overall_attendance_percent?: number | null;
    summary: string;
  }>;
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
