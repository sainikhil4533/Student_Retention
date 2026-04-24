import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { BarChartCard, PieChartCard } from "../components/charts";
import { EmptyState, LoadingCard, SectionTitle, StatCard, Card, Button } from "../components/ui";
import { apiRequest, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ActiveCasesResponse, FacultyDashboardSummary, FacultyPriorityQueue, FacultySummary, InterventionHistory, StudentCaseState, StudentOperationalContext } from "../types";

function DashboardSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <LoadingCard />
      <LoadingCard />
      <LoadingCard />
      <LoadingCard />
    </div>
  );
}

export function CounsellorDashboardPage() {
  const { auth } = useAuth();
  const summaryQuery = useQuery({
    queryKey: ["faculty-dashboard-summary", auth?.accessToken],
    queryFn: () => apiRequest<FacultyDashboardSummary>("/faculty/dashboard-summary", { token: auth?.accessToken, timeoutMs: 45000 }),
    retry: 0,
  });
  const summaryFallbackQuery = useQuery({
    queryKey: ["faculty-dashboard-summary-fallback", auth?.accessToken],
    queryFn: () => apiRequest<FacultySummary>("/faculty/summary", { token: auth?.accessToken, timeoutMs: 45000 }),
    enabled: Boolean(auth?.accessToken && summaryQuery.isError),
    retry: 0,
  });
  const queueQuery = useQuery({
    queryKey: ["faculty-priority-queue", auth?.accessToken],
    queryFn: () => apiRequest<FacultyPriorityQueue>("/faculty/priority-queue", { token: auth?.accessToken, timeoutMs: 45000 }),
    enabled: Boolean(auth?.accessToken && (summaryQuery.data || summaryFallbackQuery.data)),
    retry: 0,
  });

  if (summaryQuery.isLoading || (summaryQuery.isError && summaryFallbackQuery.isLoading)) {
    return <DashboardSkeleton />;
  }
  const summary = summaryQuery.data || (summaryFallbackQuery.data ? buildDashboardSummaryFallback(summaryFallbackQuery.data) : null);
  if (!summary) {
    return <EmptyState title="Counsellor workspace unavailable" description="The counsellor-facing summary or priority queue could not be loaded." />;
  }
  const queue = queueQuery.data;

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
        <Card className="bg-slate-900 border-none text-white shadow-none p-8">
          <p className="text-[11px] font-bold uppercase tracking-wider text-blue-400">Counsellor dashboard</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-white">Operational clarity for case ownership.</h2>
          <p className="mt-3 max-w-3xl text-[13px] leading-6 text-slate-400">
            This dashboard avoids playful gamification. Instead, it uses momentum-style workflow cues that feel professional, urgent, and useful for counsellor decision-making.
          </p>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            <div className="rounded border border-white/10 bg-white/5 p-4">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Signed in as</p>
              <p className="mt-1 text-sm font-medium text-white">{auth?.displayName || "Counsellor"}</p>
            </div>
            <div className="rounded border border-white/10 bg-white/5 p-4">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Critical unattended</p>
              <p className="mt-1 text-sm font-medium text-white">{summary.total_critical_unattended_cases} students currently need urgent visibility</p>
            </div>
            <div className="rounded border border-white/10 bg-white/5 p-4">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Scoped queue</p>
              <p className="mt-1 text-sm font-medium text-white">
                {queue ? `${queue.total_students} students visible` : "Loading preview"}
              </p>
            </div>
          </div>
        </Card>

        <Card className="space-y-4 bg-white/92">
          <SectionTitle
            eyebrow="Role posture"
            title="How this workspace is meant to be used"
            description="The first screen stays direct: what is urgent, what is active, and what deserves immediate follow-up."
          />
          <div className="space-y-3">
            <InfoRow label="Handling tone" value="Professional urgency with low-noise summaries, not playful gamification." />
            <InfoRow label="Best next step" value="Review the summary, then open the case workbench when a student needs deeper intervention handling." />
            <InfoRow label="Copilot role" value="Use the counsellor copilot for scoped cohort questions and follow-up decisions, not for open public Q&A." />
          </div>
        </Card>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Active high-risk students" value={String(summary.total_active_high_risk_students)} note="Current high-risk load inside the counsellor workspace." />
        <StatCard label="I-grade risk" value={String(summary.total_students_with_i_grade_risk)} note="Students currently below the safe subject attendance band." accent="teal" />
        <StatCard label="R-grade risk" value={String(summary.total_students_with_r_grade_risk)} note="Students whose subject attendance has dropped into repeat-grade territory." accent="rose" />
        <StatCard label="Overall shortage" value={String(summary.total_students_with_overall_shortage)} note="Students whose current visible semester is below the overall attendance requirement." accent="gold" />
        <StatCard
          label="Active burden monitoring"
          value={String(summary.total_students_with_active_academic_burden)}
          note={`${summary.total_students_with_active_i_grade_burden} I-grade carry-forward and ${summary.total_students_with_active_r_grade_burden} R-grade carry-forward students still need follow-up even if the current semester improves.`}
          accent={summary.total_students_with_active_r_grade_burden ? "rose" : "gold"}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
        <Card className="space-y-4">
          <SectionTitle eyebrow="Priority queue" title="Students who need attention first" description="This section is intentionally direct. Counsellor time is usually limited, so the queue stays action-oriented." />
          {queueQuery.isLoading ? (
            <div className="space-y-3">
              <LoadingCard />
              <LoadingCard />
            </div>
          ) : queueQuery.isError || !queue ? (
            <EmptyState
              title="Priority queue is taking too long"
              description="The counsellor summary loaded, but the heavier queue preview did not finish in time. You can still use Copilot or open Cases while we keep this endpoint lighter."
            />
          ) : (
            <div className="space-y-3">
              {queue.queue.slice(0, 6).map((item) => (
                <div key={item.student_id} className="rounded-3xl border border-slate-200 bg-white px-4 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-bold text-slate-950">Student {item.student_id}</p>
                      <p className="mt-1 text-sm leading-6 text-slate-600">{item.queue_reason}</p>
                      {item.has_active_academic_burden ? (
                        <p className="mt-2 text-xs font-semibold uppercase tracking-[0.16em] text-rose-600">
                          Active burden: {item.active_burden_count} subject(s) | {item.academic_risk_band?.replace(/_/g, " ")} | {item.monitoring_cadence?.replace(/_/g, " ")} monitoring
                        </p>
                      ) : null}
                    </div>
                    <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-semibold text-white">
                      {item.priority_label} | {item.priority_score}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <BarChartCard
          title="Counsellor academic pressure"
          description="A compact view of the attendance policy pressure inside the counsellor scope."
          data={[
            { label: "Overall shortage", value: summary.total_students_with_overall_shortage },
            { label: "I-grade", value: summary.total_students_with_i_grade_risk },
            { label: "R-grade", value: summary.total_students_with_r_grade_risk },
            { label: "Critical unattended", value: summary.total_critical_unattended_cases },
            { label: "Active burden", value: summary.total_students_with_active_academic_burden },
          ]}
          xKey="label"
          dataKey="value"
        />
      </div>
    </div>
  );
}

export function CounsellorReportsPage() {
  const { auth } = useAuth();
  const summaryQuery = useQuery({
    queryKey: ["faculty-reports-summary", auth?.accessToken],
    queryFn: () => apiRequest<FacultySummary>("/faculty/summary", { token: auth?.accessToken, timeoutMs: 45000 }),
    retry: 0,
  });
  const dashboardFallbackQuery = useQuery({
    queryKey: ["faculty-reports-summary-fallback", auth?.accessToken],
    queryFn: () => apiRequest<FacultyDashboardSummary>("/faculty/dashboard-summary", { token: auth?.accessToken, timeoutMs: 45000 }),
    enabled: Boolean(auth?.accessToken && summaryQuery.isError),
    retry: 0,
  });

  if (summaryQuery.isLoading || (summaryQuery.isError && dashboardFallbackQuery.isLoading)) {
    return <DashboardSkeleton />;
  }
  const summary = summaryQuery.data || (dashboardFallbackQuery.data ? buildFacultySummaryFallback(dashboardFallbackQuery.data) : null);
  if (!summary) {
    return <EmptyState title="Counsellor reports unavailable" description="The faculty summary endpoint is required to build counsellor report visuals." />;
  }

  return (
    <div className="space-y-6">
      <SectionTitle eyebrow="Counsellor reports" title="A deeper analytical view of current case pressure" description="The dashboard shows what to act on. This page shows the counsellor's operational mix in more analytical form." />
      <div className="grid gap-6 xl:grid-cols-2">
        <BarChartCard
          title="Subject pressure inside counsellor scope"
          description="Which subjects are pulling the most students below attendance policy in the currently visible counsellor cohort."
          data={summary.top_subject_pressure.map((item) => ({
            label: item.subject_name,
            value: item.students_below_threshold,
          }))}
          xKey="label"
          dataKey="value"
        />
        <PieChartCard
          title="Attendance policy split"
          description="A cleaner planning view of safe vs policy-risk pressure in the counsellor cohort."
          data={[
            { label: "Overall shortage", value: summary.total_students_with_overall_shortage },
            { label: "I-grade", value: summary.total_students_with_i_grade_risk },
            { label: "R-grade", value: summary.total_students_with_r_grade_risk },
            { label: "Active recovery", value: summary.total_active_recovery_windows },
          ]}
          nameKey="label"
          dataKey="value"
        />
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <BarChartCard
          title="Branch pressure inside counsellor scope"
          description="Shows which visible branches carry the heaviest attendance-policy pressure for this counsellor's assigned students."
          data={summary.branch_pressure.map((item) => ({
            label: item.bucket_label,
            value: item.students_with_r_grade_risk + item.students_with_overall_shortage,
          }))}
          xKey="label"
          dataKey="value"
        />
        <BarChartCard
          title="Semester pressure inside counsellor scope"
          description="Shows which semester slices inside the assigned cohort currently need the most recovery attention."
          data={summary.semester_pressure.map((item) => ({
            label: item.bucket_label,
            value: item.students_with_r_grade_risk + item.students_with_overall_shortage,
          }))}
          xKey="label"
          dataKey="value"
        />
      </div>
      <Card className="space-y-4">
        <SectionTitle
          eyebrow="Carry-forward monitoring"
          title="Students who still need cadence-based follow-up"
          description="These students remain on the counsellor radar because an I-grade or R-grade burden is still uncleared, even if their current semester performance has improved."
        />
        <div className="space-y-3">
          {summary.academic_burden_monitoring_students.length ? (
            summary.academic_burden_monitoring_students.slice(0, 8).map((item) => (
              <div key={`burden-${item.student_id}`} className="rounded border border-slate-200 bg-white px-4 py-4 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-sm font-semibold text-slate-900">Student {item.student_id}</p>
                  <span className="rounded bg-amber-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-700">
                    {item.status.replace(/_/g, " ")}
                  </span>
                </div>
                <p className="mt-2 text-[13px] leading-5 text-slate-600">{item.note || "Active academic burden monitoring is still recommended."}</p>
              </div>
            ))
          ) : (
            <EmptyState title="No active burden monitoring" description="No assigned students currently have unresolved I-grade or R-grade burden on record." />
          )}
        </div>
      </Card>
    </div>
  );
}

const INTERVENTION_STATUSES = [
  "seen",
  "acknowledged",
  "contacted",
  "support_provided",
  "resolved",
] as const;

export function CounsellorCasesPage() {
  const { auth } = useAuth();
  const [selectedStudentId, setSelectedStudentId] = useState<number | null>(null);
  const [actionStatus, setActionStatus] = useState<(typeof INTERVENTION_STATUSES)[number]>("seen");
  const [actorName, setActorName] = useState(auth?.displayName || "Counsellor");
  const [notes, setNotes] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitState, setSubmitState] = useState<"idle" | "saving" | "done">("idle");

  const casesQuery = useQuery({
    queryKey: ["active-cases", auth?.accessToken],
    queryFn: () => apiRequest<ActiveCasesResponse>("/cases/active", { token: auth?.accessToken, timeoutMs: 45000 }),
    retry: 0,
  });
  const queueFallbackQuery = useQuery({
    queryKey: ["active-cases-fallback-queue", auth?.accessToken],
    queryFn: () => apiRequest<FacultyPriorityQueue>("/faculty/priority-queue", { token: auth?.accessToken, timeoutMs: 45000 }),
    enabled: Boolean(auth?.accessToken && casesQuery.isError),
    retry: 0,
  });
  const activeCases = casesQuery.data || (queueFallbackQuery.data ? buildActiveCasesFallback(queueFallbackQuery.data) : null);

  const selectedCase = useMemo<StudentCaseState | null>(() => {
    const cases = activeCases?.cases || [];
    if (!cases.length) {
      return null;
    }
    if (!selectedStudentId) {
      return cases[0];
    }
    return cases.find((item) => item.student_id === selectedStudentId) || cases[0];
  }, [activeCases?.cases, selectedStudentId]);

  const studentId = selectedCase?.student_id;

  const contextQuery = useQuery({
    queryKey: ["student-operational-context", studentId, auth?.accessToken],
    queryFn: () => apiRequest<StudentOperationalContext>(`/operations/context/${studentId}`, { token: auth?.accessToken, timeoutMs: 45000 }),
    enabled: Boolean(studentId),
    retry: 0,
  });

  const historyQuery = useQuery({
    queryKey: ["student-interventions", studentId, auth?.accessToken],
    queryFn: () => apiRequest<InterventionHistory>(`/interventions/history/${studentId}`, { token: auth?.accessToken, timeoutMs: 45000 }),
    enabled: Boolean(studentId),
    retry: 0,
  });

  async function handleCreateAction() {
    if (!studentId) {
      return;
    }
    setSubmitState("saving");
    setSubmitError(null);
    try {
      await apiRequest("/interventions/action", {
        method: "POST",
        token: auth?.accessToken,
        body: {
          student_id: studentId,
          action_status: actionStatus,
          actor_name: actorName,
          notes,
        },
      });
      await historyQuery.refetch();
      await casesQuery.refetch();
      setNotes("");
      setSubmitState("done");
    } catch (error) {
      setSubmitState("idle");
      setSubmitError(error instanceof ApiError ? error.detail : error instanceof Error ? error.message : "Unable to save intervention action.");
    }
  }

  if (casesQuery.isLoading || (casesQuery.isError && queueFallbackQuery.isLoading)) {
    return <DashboardSkeleton />;
  }
  if (!activeCases) {
    return <EmptyState title="Case workspace unavailable" description="The active cases endpoint is required for the counsellor workbench." />;
  }

  return (
    <div className="space-y-6">
      <SectionTitle
        eyebrow="Counsellor workbench"
        title="Case-by-case intervention workspace"
        description="This is the deeper counsellor page beyond the dashboard. It turns summary information into an actual working surface for reviewing case state, operational context, and intervention history."
      />
      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Card className="flex flex-col" style={{ maxHeight: "calc(100vh - 120px)" }}>
          <div className="shrink-0 p-4 border-b border-slate-100">
            <SectionTitle
              eyebrow="Active cases"
              title={`Open workload (${activeCases.total_students})`}
              description="Cases are ordered by urgency using the same scoped counsellor queue. Selecting a case opens the operational context and intervention history."
            />
          </div>
          <div className="overflow-y-auto flex-1 p-4">
            <div className="space-y-3">
              {activeCases.cases.length ? (
                activeCases.cases.map((item) => {
                  const active = item.student_id === selectedCase?.student_id;
                  return (
                    <button
                      key={item.student_id}
                      type="button"
                      onClick={() => setSelectedStudentId(item.student_id)}
                      className={`w-full rounded-3xl border px-4 py-4 text-left transition ${active ? "border-indigo-200 bg-indigo-50" : "border-slate-200 bg-white hover:border-slate-300"
                        }`}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <p className="font-bold text-slate-950">Student {item.student_id}</p>
                        <div className="flex flex-wrap items-center gap-2">
                          {item.priority_label ? (
                            <span className="rounded-full bg-indigo-100 px-3 py-1 text-xs font-semibold text-indigo-700">
                              {item.priority_label.replace(/_/g, " ")}
                              {item.priority_score != null ? ` | ${item.priority_score}` : ""}
                            </span>
                          ) : null}
                          <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-semibold text-white">
                            {item.risk_level || "Unknown"}
                          </span>
                        </div>
                      </div>
                      <p className="mt-2 text-sm leading-6 text-slate-600">{item.summary}</p>
                    </button>
                  );
                })
              ) : (
                <EmptyState title="No active cases" description="This workspace will populate as soon as the backend sees active cases that require counsellor/admin follow-up." />
              )}
            </div>
          </div>
        </Card>

        <div className="overflow-y-auto space-y-6" style={{ maxHeight: "calc(100vh - 120px)" }}>
          {selectedCase ? (
            <>
              <Card className="space-y-4">
                <SectionTitle
                  eyebrow="Selected case"
                  title={`Student ${selectedCase.student_id}`}
                  description="The backend computes this state from prediction history, warning workflow, alerts, milestone flags, and intervention history."
                />
                <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
                  <div className="flex flex-col gap-1.5 p-4 rounded-2xl bg-slate-50 border border-slate-100">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Case State</span>
                    <span className="text-base font-semibold text-slate-900 capitalize leading-tight">
                      {selectedCase.current_case_state.replace(/_/g, " ")}
                    </span>
                    <span className="text-xs text-slate-500 leading-snug line-clamp-2" title={selectedCase.summary}>{selectedCase.summary}</span>
                  </div>
                  
                  <div className="flex flex-col gap-1.5 p-4 rounded-2xl bg-indigo-50/50 border border-indigo-100">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-500">Queue Priority</span>
                    <span className="text-base font-semibold text-indigo-900 capitalize leading-tight">
                      {selectedCase.priority_label?.replace(/_/g, " ") || "Unranked"}
                    </span>
                    <span className="text-xs text-indigo-600 leading-snug">
                      {selectedCase.priority_score != null ? `Score ${selectedCase.priority_score}` : "Active workflow"}
                    </span>
                  </div>

                  <div className="flex flex-col gap-1.5 p-4 rounded-2xl bg-slate-50 border border-slate-100">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Risk Level</span>
                    <span className="text-base font-semibold text-slate-900 capitalize leading-tight">
                      {selectedCase.risk_level || "Unknown"}
                    </span>
                    <span className="text-xs text-slate-500 leading-snug">
                      Probability {selectedCase.final_risk_probability != null ? selectedCase.final_risk_probability.toFixed(4) : "--"}
                    </span>
                  </div>

                  <div className="flex flex-col gap-1.5 p-4 rounded-2xl bg-amber-50/50 border border-amber-100">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-amber-600">SLA Status</span>
                    <span className="text-base font-semibold text-amber-900 capitalize leading-tight break-all">
                      {selectedCase.sla_status.replace(/_/g, " ")}
                    </span>
                    <span className="text-xs text-amber-700 leading-snug">
                      {selectedCase.followup_overdue ? "Follow-up overdue" : "No overdue follow-up"}
                    </span>
                  </div>

                  <div className="flex flex-col gap-1.5 p-4 rounded-2xl bg-rose-50/50 border border-rose-100">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-rose-500">Intervention</span>
                    <span className="text-base font-semibold text-rose-900 capitalize leading-tight">
                      {selectedCase.latest_intervention_status?.replace(/_/g, " ") || "None"}
                    </span>
                    <span className="text-xs text-rose-600 leading-snug">
                      {selectedCase.candidate_for_resolution ? "Resolution candidate" : "Still operational"}
                    </span>
                  </div>
                </div>
              </Card>

              <div className="grid gap-6 xl:grid-cols-2">
                <Card className="space-y-4">
                  <SectionTitle
                    eyebrow="Operational context"
                    title="What the backend sees around this student"
                    description="This combines recent activity, milestone flags, and SLA context into one readable panel."
                  />
                  {contextQuery.isLoading ? (
                    <LoadingCard />
                  ) : contextQuery.data ? (
                    <div className="space-y-4">
                      <InfoRow label="Activity summary" value={contextQuery.data.activity_summary.summary} />
                      <InfoRow label="Last activity" value={contextQuery.data.activity_summary.last_meaningful_activity_at ? `${contextQuery.data.activity_summary.last_meaningful_activity_source || "Unknown"} | ${contextQuery.data.activity_summary.last_meaningful_activity_at}` : "Unavailable"} />
                      <InfoRow label="Milestone flags" value={contextQuery.data.milestone_flags.active_flags.length ? contextQuery.data.milestone_flags.active_flags.join(", ") : "No active milestone flags"} />
                      <InfoRow label="SLA summary" value={contextQuery.data.sla_summary.summary} />
                      {contextQuery.data.academic_context ? (
                        <>
                          <InfoRow
                            label="Academic position"
                            value={`Year ${contextQuery.data.academic_context.current_year ?? "--"}, Semester ${contextQuery.data.academic_context.current_semester ?? "--"}, ${contextQuery.data.academic_context.branch || "Unknown branch"}${contextQuery.data.academic_context.semester_mode ? `, ${contextQuery.data.academic_context.semester_mode.replace(/_/g, " ")}` : ""}`}
                          />
                          <InfoRow
                            label="Attendance posture"
                            value={
                              contextQuery.data.academic_context.overall_attendance_percent != null
                                ? `${contextQuery.data.academic_context.overall_attendance_percent.toFixed(2)}% overall (${contextQuery.data.academic_context.overall_status || "unknown"})`
                                : "Overall attendance is not available."
                            }
                          />
                          <InfoRow
                            label="Academic consequences"
                            value={`Below 75% subjects: ${contextQuery.data.academic_context.subjects_below_75_count ?? 0}; below 65% subjects: ${contextQuery.data.academic_context.subjects_below_65_count ?? 0}; eligibility: ${contextQuery.data.academic_context.current_eligibility || "not available"}`}
                          />
                          <InfoRow
                            label="Carry-forward burden"
                            value={
                              contextQuery.data.academic_context.active_burden_count
                                ? `${contextQuery.data.academic_context.academic_burden_summary || "Uncleared academic burden is still active."} Monitoring cadence: ${String(contextQuery.data.academic_context.monitoring_cadence || "none").replace(/_/g, " ")}.`
                                : "No unresolved I-grade or R-grade subject burden is currently active."
                            }
                          />
                          <InfoRow
                            label="Weakest subject"
                            value={
                              contextQuery.data.academic_context.weakest_subject_name
                                ? `${contextQuery.data.academic_context.weakest_subject_name} at ${contextQuery.data.academic_context.weakest_subject_percent?.toFixed(2) ?? "--"}% (${contextQuery.data.academic_context.weakest_subject_status || "unknown"})`
                                : "Weakest subject detail is not available."
                            }
                          />
                        </>
                      ) : null}
                    </div>
                  ) : (
                    <EmptyState title="Context unavailable" description="No operational context could be loaded for the selected student." />
                  )}
                </Card>

                <Card className="space-y-4">
                  <SectionTitle
                    eyebrow="Log new action"
                    title="Record counsellor handling"
                    description="This is where the page becomes truly operational instead of just analytical."
                  />
                  <div className="space-y-4">
                    <label className="block">
                      <span className="mb-2 block text-sm font-semibold text-slate-700">Action status</span>
                      <select
                        value={actionStatus}
                        onChange={(event) => setActionStatus(event.target.value as (typeof INTERVENTION_STATUSES)[number])}
                        className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3"
                      >
                        {INTERVENTION_STATUSES.map((status) => (
                          <option key={status} value={status}>
                            {status}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block">
                      <span className="mb-2 block text-sm font-semibold text-slate-700">Actor name</span>
                      <input
                        value={actorName}
                        onChange={(event) => setActorName(event.target.value)}
                        className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-2 block text-sm font-semibold text-slate-700">Notes</span>
                      <textarea
                        value={notes}
                        onChange={(event) => setNotes(event.target.value)}
                        rows={4}
                        className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3"
                        placeholder="Add what was done, what was discussed, or what should happen next."
                      />
                    </label>
                    {submitError ? <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{submitError}</div> : null}
                    {submitState === "done" ? <div className="rounded-2xl border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-700">Intervention action recorded successfully.</div> : null}
                    <Button onClick={handleCreateAction} disabled={submitState === "saving"}>
                      {submitState === "saving" ? "Saving..." : "Save intervention action"}
                    </Button>
                  </div>
                </Card>
              </div>

              {contextQuery.data?.academic_context?.subject_risk_summary?.length ? (
                <Card className="space-y-4">
                  <SectionTitle
                    eyebrow="Academic drilldown"
                    title="Current subject pressure for this student"
                    description="This panel is where the generalized academic model becomes useful in the real counsellor workflow."
                  />
                  <div className="space-y-3">
                    {contextQuery.data.academic_context.subject_risk_summary.map((item) => (
                      <div key={`${item.subject_name}-${item.subject_status}`} className="rounded-3xl border border-slate-200 bg-white px-4 py-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <p className="font-semibold text-slate-950">{item.subject_name}</p>
                          <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-semibold text-white">
                            {item.subject_status || "Unknown"}
                          </span>
                        </div>
                        <p className="mt-2 text-sm leading-6 text-slate-600">
                          Attendance: {item.subject_attendance_percent != null ? `${item.subject_attendance_percent.toFixed(2)}%` : "Unavailable"}
                          {item.grade_consequence ? ` | Consequence: ${item.grade_consequence}` : ""}
                        </p>
                      </div>
                    ))}
                  </div>
                </Card>
              ) : null}

              {(contextQuery.data?.academic_context?.active_i_grade_subjects?.length || contextQuery.data?.academic_context?.active_r_grade_subjects?.length) ? (
                <Card className="space-y-4">
                  <SectionTitle
                    eyebrow="Uncleared burden"
                    title="Subjects that must stay under monitoring"
                    description="These subjects should remain uncleared in the case view until the student actually clears the I-grade or R-grade."
                  />
                  <div className="space-y-3">
                    {contextQuery.data.academic_context.active_r_grade_subjects?.map((item) => (
                      <div key={`r-burden-${item.subject_code || item.subject_name}`} className="rounded-3xl border border-rose-200 bg-white px-4 py-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <p className="font-semibold text-slate-950">{item.subject_name || item.subject_code || "Unknown subject"}</p>
                          <span className="rounded-full bg-rose-600 px-3 py-1 text-xs font-semibold text-white">R Grade Active</span>
                        </div>
                        <p className="mt-2 text-sm leading-6 text-slate-600">
                          Effective status: {item.effective_result_status || "Pending clearance"}.
                        </p>
                      </div>
                    ))}
                    {contextQuery.data.academic_context.active_i_grade_subjects?.map((item) => (
                      <div key={`i-burden-${item.subject_code || item.subject_name}`} className="rounded-3xl border border-amber-200 bg-white px-4 py-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <p className="font-semibold text-slate-950">{item.subject_name || item.subject_code || "Unknown subject"}</p>
                          <span className="rounded-full bg-amber-500 px-3 py-1 text-xs font-semibold text-white">I Grade Active</span>
                        </div>
                        <p className="mt-2 text-sm leading-6 text-slate-600">
                          Effective status: {item.effective_result_status || "Pending clearance"}.
                        </p>
                      </div>
                    ))}
                  </div>
                </Card>
              ) : null}

              <Card className="space-y-4">
                <SectionTitle
                  eyebrow="Intervention history"
                  title="Existing action trail"
                  description="This makes the counsellor page feel like a real case workspace, because previous handling stays visible instead of disappearing into logs."
                />
                {historyQuery.isLoading ? (
                  <LoadingCard />
                ) : historyQuery.data?.interventions?.length ? (
                  <div className="space-y-3">
                    {historyQuery.data.interventions.map((item) => (
                      <div key={`${item.id}-${item.created_at}`} className="rounded-3xl border border-slate-200 bg-white px-4 py-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <p className="font-semibold text-slate-950">{item.action_status}</p>
                          <p className="text-xs uppercase tracking-[0.18em] text-slate-400">{item.created_at || "No timestamp"}</p>
                        </div>
                        <p className="mt-2 text-sm leading-6 text-slate-600">{item.notes || "No notes recorded."}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="No intervention history yet" description="Once a counsellor/admin records actions, they will appear here." />
                )}
              </Card>
            </>
          ) : (
            <EmptyState title="Select a case" description="Choose a case from the left to open the counsellor workbench." />
          )}
        </div>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{label}</p>
      <p className="mt-2 text-sm leading-6 text-slate-700">{value}</p>
    </div>
  );
}

function buildFacultySummaryFallback(summary: FacultyDashboardSummary): FacultySummary {
  return {
    total_active_high_risk_students: summary.total_active_high_risk_students,
    total_active_recovery_windows: 0,
    total_expired_recovery_windows: 0,
    total_escalated_cases: 0,
    total_followup_reminders_sent: summary.total_critical_unattended_cases,
    total_resolution_candidates: 0,
    total_reopened_cases: 0,
    total_critical_unattended_cases: summary.total_critical_unattended_cases,
    total_repeated_risk_students: 0,
    total_unhandled_escalations: 0,
    total_students_with_overall_shortage: summary.total_students_with_overall_shortage,
    total_students_with_i_grade_risk: summary.total_students_with_i_grade_risk,
    total_students_with_r_grade_risk: summary.total_students_with_r_grade_risk,
    total_students_with_active_academic_burden: summary.total_students_with_active_academic_burden,
    total_students_with_active_i_grade_burden: summary.total_students_with_active_i_grade_burden,
    total_students_with_active_r_grade_burden: summary.total_students_with_active_r_grade_burden,
    top_subject_pressure: summary.top_subject_pressure,
    branch_pressure: summary.branch_pressure,
    semester_pressure: summary.semester_pressure,
    academic_burden_monitoring_students: [],
  };
}

function buildDashboardSummaryFallback(summary: FacultySummary): FacultyDashboardSummary {
  return {
    total_active_high_risk_students: summary.total_active_high_risk_students,
    total_critical_unattended_cases: summary.total_critical_unattended_cases,
    total_students_with_overall_shortage: summary.total_students_with_overall_shortage,
    total_students_with_i_grade_risk: summary.total_students_with_i_grade_risk,
    total_students_with_r_grade_risk: summary.total_students_with_r_grade_risk,
    total_students_with_active_academic_burden: summary.total_students_with_active_academic_burden,
    total_students_with_active_i_grade_burden: summary.total_students_with_active_i_grade_burden,
    total_students_with_active_r_grade_burden: summary.total_students_with_active_r_grade_burden,
    top_subject_pressure: summary.top_subject_pressure,
    branch_pressure: summary.branch_pressure,
    semester_pressure: summary.semester_pressure,
  };
}

function buildActiveCasesFallback(queue: FacultyPriorityQueue): ActiveCasesResponse {
  return {
    total_students: queue.total_students,
    cases: queue.queue.map((item) => ({
      student_id: item.student_id,
      current_case_state: item.current_risk_level === "HIGH" ? "high_risk_active" : "academic_burden_monitoring",
      priority_score: item.priority_score,
      priority_label: item.priority_label,
      risk_level: item.current_risk_level,
      final_risk_probability: item.final_risk_probability ?? null,
      latest_prediction_created_at: null,
      warning_status: null,
      warning_resolution_status: null,
      faculty_alert_type: null,
      faculty_alert_status: null,
      guardian_alert_type: null,
      guardian_alert_status: null,
      guardian_alert_channel: null,
      guardian_alert_sent_at: null,
      latest_intervention_status: null,
      candidate_for_resolution: false,
      is_reopened_case: false,
      is_critical_unattended_case: false,
      last_meaningful_activity_at: null,
      last_meaningful_activity_source: null,
      active_milestone_flags: [],
      sla_status: "not_applicable",
      followup_overdue: false,
      summary: item.queue_reason,
    })),
  };
}
