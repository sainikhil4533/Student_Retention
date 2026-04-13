import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { BarChartCard, PieChartCard } from "../components/charts";
import { EmptyState, LoadingCard, SectionTitle, StatCard, Card, Button } from "../components/ui";
import { apiRequest, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ActiveCasesResponse, FacultyPriorityQueue, FacultySummary, InterventionHistory, StudentCaseState, StudentOperationalContext } from "../types";

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
    queryKey: ["faculty-summary", auth?.accessToken],
    queryFn: () => apiRequest<FacultySummary>("/faculty/summary", { token: auth?.accessToken }),
  });
  const queueQuery = useQuery({
    queryKey: ["faculty-priority-queue", auth?.accessToken],
    queryFn: () => apiRequest<FacultyPriorityQueue>("/faculty/priority-queue", { token: auth?.accessToken }),
  });

  if (summaryQuery.isLoading || queueQuery.isLoading) {
    return <DashboardSkeleton />;
  }
  if (summaryQuery.isError || queueQuery.isError || !summaryQuery.data || !queueQuery.data) {
    return <EmptyState title="Counsellor workspace unavailable" description="The counsellor-facing summary or priority queue could not be loaded." />;
  }

  const summary = summaryQuery.data;
  const queue = queueQuery.data;

  return (
    <div className="space-y-6">
      <SectionTitle
        eyebrow="Counsellor dashboard"
        title="Operational clarity for case ownership"
        description="This dashboard avoids playful gamification. Instead, it uses momentum-style workflow cues that feel professional and useful for counsellor decision-making."
      />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Active high-risk students" value={String(summary.total_active_high_risk_students)} note="Current high-risk load inside the counsellor workspace." />
        <StatCard label="Active recovery windows" value={String(summary.total_active_recovery_windows)} note="Students still inside a live warning/recovery period." accent="teal" />
        <StatCard label="Expired windows" value={String(summary.total_expired_recovery_windows)} note="Cases that need urgent re-engagement." accent="rose" />
        <StatCard label="Critical unattended" value={String(summary.total_critical_unattended_cases)} note="Highest urgency cases requiring counsellor visibility." accent="gold" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
        <Card className="space-y-4">
          <SectionTitle eyebrow="Priority queue" title="Students who need attention first" description="This section is intentionally direct. Counsellor time is usually limited, so the queue stays action-oriented." />
          <div className="space-y-3">
            {queue.queue.slice(0, 6).map((item) => (
              <div key={item.student_id} className="rounded-3xl border border-slate-200 bg-white px-4 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-bold text-slate-950">Student {item.student_id}</p>
                    <p className="mt-1 text-sm leading-6 text-slate-600">{item.queue_reason}</p>
                  </div>
                  <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-semibold text-white">
                    {item.priority_label} · {item.priority_score}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <BarChartCard
          title="Counsellor case posture"
          description="A compact executive view that answers: where is the pressure concentrated right now?"
          data={[
            { label: "High risk", value: summary.total_active_high_risk_students },
            { label: "Active windows", value: summary.total_active_recovery_windows },
            { label: "Escalated", value: summary.total_escalated_cases },
            { label: "Repeated risk", value: summary.total_repeated_risk_students },
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
    queryKey: ["faculty-summary-report", auth?.accessToken],
    queryFn: () => apiRequest<FacultySummary>("/faculty/summary", { token: auth?.accessToken }),
  });

  if (summaryQuery.isLoading) {
    return <DashboardSkeleton />;
  }
  if (summaryQuery.isError || !summaryQuery.data) {
    return <EmptyState title="Counsellor reports unavailable" description="The faculty summary endpoint is required to build counsellor report visuals." />;
  }

  const summary = summaryQuery.data;

  return (
    <div className="space-y-6">
      <SectionTitle eyebrow="Counsellor reports" title="A deeper analytical view of current case pressure" description="The dashboard shows what to act on. This page shows the counsellor's operational mix in more analytical form." />
      <div className="grid gap-6 xl:grid-cols-2">
        <BarChartCard
          title="Intervention-related case mix"
          description="How the current counsellor workload is distributed across different case states."
          data={[
            { label: "Escalated", value: summary.total_escalated_cases },
            { label: "Follow-up", value: summary.total_followup_reminders_sent },
            { label: "Resolution", value: summary.total_resolution_candidates },
            { label: "Critical", value: summary.total_critical_unattended_cases },
          ]}
          xKey="label"
          dataKey="value"
        />
        <PieChartCard
          title="Case posture split"
          description="A clean proportional view for counsellor planning."
          data={[
            { label: "Active recovery", value: summary.total_active_recovery_windows },
            { label: "Resolution candidates", value: summary.total_resolution_candidates },
            { label: "Reopened", value: summary.total_reopened_cases },
            { label: "Unhandled", value: summary.total_unhandled_escalations },
          ]}
          nameKey="label"
          dataKey="value"
        />
      </div>
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
    queryFn: () => apiRequest<ActiveCasesResponse>("/cases/active", { token: auth?.accessToken }),
  });

  const selectedCase = useMemo<StudentCaseState | null>(() => {
    const cases = casesQuery.data?.cases || [];
    if (!cases.length) {
      return null;
    }
    if (!selectedStudentId) {
      return cases[0];
    }
    return cases.find((item) => item.student_id === selectedStudentId) || cases[0];
  }, [casesQuery.data?.cases, selectedStudentId]);

  const studentId = selectedCase?.student_id;

  const contextQuery = useQuery({
    queryKey: ["student-operational-context", studentId, auth?.accessToken],
    queryFn: () => apiRequest<StudentOperationalContext>(`/operations/context/${studentId}`, { token: auth?.accessToken }),
    enabled: Boolean(studentId),
  });

  const historyQuery = useQuery({
    queryKey: ["student-interventions", studentId, auth?.accessToken],
    queryFn: () => apiRequest<InterventionHistory>(`/interventions/history/${studentId}`, { token: auth?.accessToken }),
    enabled: Boolean(studentId),
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

  if (casesQuery.isLoading) {
    return <DashboardSkeleton />;
  }
  if (casesQuery.isError || !casesQuery.data) {
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
        <Card className="space-y-4">
          <SectionTitle
            eyebrow="Active cases"
            title={`Open workload (${casesQuery.data.total_students})`}
            description="Cases are ordered by urgency by the backend. Selecting a case opens the operational context and intervention history."
          />
          <div className="space-y-3">
            {casesQuery.data.cases.length ? (
              casesQuery.data.cases.map((item) => {
                const active = item.student_id === selectedCase?.student_id;
                return (
                  <button
                    key={item.student_id}
                    type="button"
                    onClick={() => setSelectedStudentId(item.student_id)}
                    className={`w-full rounded-3xl border px-4 py-4 text-left transition ${
                      active ? "border-indigo-200 bg-indigo-50" : "border-slate-200 bg-white hover:border-slate-300"
                    }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="font-bold text-slate-950">Student {item.student_id}</p>
                      <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-semibold text-white">
                        {item.risk_level || "Unknown"}
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-600">{item.summary}</p>
                  </button>
                );
              })
            ) : (
              <EmptyState title="No active cases" description="This workspace will populate as soon as the backend sees active cases that require counsellor/admin follow-up." />
            )}
          </div>
        </Card>

        <div className="space-y-6">
          {selectedCase ? (
            <>
              <Card className="space-y-4">
                <SectionTitle
                  eyebrow="Selected case"
                  title={`Student ${selectedCase.student_id}`}
                  description="The backend computes this state from prediction history, warning workflow, alerts, milestone flags, and intervention history."
                />
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  <StatCard label="Case state" value={selectedCase.current_case_state.replace(/_/g, " ")} note={selectedCase.summary} accent="teal" />
                  <StatCard label="Risk" value={selectedCase.risk_level || "Unknown"} note={`Probability ${selectedCase.final_risk_probability ?? "--"}`} />
                  <StatCard label="SLA status" value={selectedCase.sla_status} note={selectedCase.followup_overdue ? "Follow-up overdue" : "No overdue follow-up"} accent="gold" />
                  <StatCard label="Intervention" value={selectedCase.latest_intervention_status || "None"} note={selectedCase.candidate_for_resolution ? "Candidate for resolution" : "Still operational"} accent="rose" />
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
                      <InfoRow label="Last activity" value={contextQuery.data.activity_summary.last_meaningful_activity_at ? `${contextQuery.data.activity_summary.last_meaningful_activity_source || "Unknown"} · ${contextQuery.data.activity_summary.last_meaningful_activity_at}` : "Unavailable"} />
                      <InfoRow label="Milestone flags" value={contextQuery.data.milestone_flags.active_flags.length ? contextQuery.data.milestone_flags.active_flags.join(", ") : "No active milestone flags"} />
                      <InfoRow label="SLA summary" value={contextQuery.data.sla_summary.summary} />
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
