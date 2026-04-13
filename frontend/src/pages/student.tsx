import { useQuery } from "@tanstack/react-query";
import { Flag, Flame, ShieldAlert, Trophy, UserCircle2 } from "lucide-react";

import { BarChartCard, PieChartCard } from "../components/charts";
import { Button, Card, EmptyState, LoadingCard, SectionTitle, StatCard } from "../components/ui";
import { apiRequest } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDate, formatPercent, titleCase } from "../lib/format";
import { StudentOverview, StudentTimeline } from "../types";

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

export function StudentDashboardPage() {
  const { auth } = useAuth();
  const overviewQuery = useQuery({
    queryKey: ["student-overview", auth?.accessToken],
    queryFn: () => apiRequest<StudentOverview>("/student/me/overview", { token: auth?.accessToken }),
  });
  const timelineQuery = useQuery({
    queryKey: ["student-timeline", auth?.studentId, auth?.accessToken],
    queryFn: () => apiRequest<StudentTimeline>(`/timeline/${auth?.studentId}`, { token: auth?.accessToken }),
    enabled: Boolean(auth?.studentId),
  });

  if (overviewQuery.isLoading) {
    return <DashboardSkeleton />;
  }
  if (overviewQuery.isError || !overviewQuery.data) {
    return <EmptyState title="Student overview unavailable" description="The signed-in student does not currently have a prediction-ready overview." />;
  }

  const overview = overviewQuery.data;
  const latestPrediction = overview.latest_prediction;
  const warningCount = overview.warning_history.warnings.length;
  const criticalTrigger = latestPrediction.trigger_alerts?.has_critical_trigger;

  return (
    <div className="space-y-6">
      <SectionTitle
        eyebrow="Student dashboard"
        title="Your next best actions, made visible"
        description="This dashboard is designed to feel motivating without becoming childish. The most important information stays in front of you, while the rest stays clean and readable."
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Current risk level"
          value={latestPrediction.final_predicted_class === 1 ? "High" : "Low"}
          note={latestPrediction.risk_type?.summary || "Current operational classification from the latest prediction."}
          accent={latestPrediction.final_predicted_class === 1 ? "rose" : "teal"}
        />
        <StatCard
          label="Risk probability"
          value={formatPercent(latestPrediction.final_risk_probability)}
          note={latestPrediction.risk_trend?.summary || "Latest probability after the backend scoring pipeline."}
        />
        <StatCard
          label="Warnings on record"
          value={String(warningCount)}
          note={warningCount ? "Warnings exist in your recovery history." : "No active warning history currently visible."}
          accent="gold"
        />
        <StatCard
          label="Critical triggers"
          value={criticalTrigger ? "Yes" : "No"}
          note={latestPrediction.trigger_alerts?.summary || "Critical trigger logic from the backend alerts layer."}
          accent="teal"
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <Card className="space-y-4 bg-gradient-to-br from-white to-indigo-50/60">
          <SectionTitle
            eyebrow="Motivational journey"
            title="Progress timeline"
            description="This is the formal, gamified version of the student timeline. It shows movement, checkpoints, and recovery momentum without feeling childish."
          />
          <div className="space-y-5">
            {timelineQuery.data?.timeline?.length ? (
              timelineQuery.data.timeline.slice(0, 6).map((event, index) => (
                <div key={`${event.event_type}-${index}`} className="timeline-track relative pl-12">
                  <div className="absolute left-0 top-1 flex h-9 w-9 items-center justify-center rounded-full border border-indigo-200 bg-white shadow-soft">
                    {event.status?.toLowerCase().includes("resolved") ? (
                      <Trophy className="h-4 w-4 text-teal-600" />
                    ) : event.event_type.includes("warning") ? (
                      <ShieldAlert className="h-4 w-4 text-amber-600" />
                    ) : (
                      <Flame className="h-4 w-4 text-indigo-600" />
                    )}
                  </div>
                  <div className="rounded-3xl border border-white/60 bg-white/85 p-4 shadow-soft">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <h3 className="text-sm font-bold text-slate-900">{event.title}</h3>
                      <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700">
                        {titleCase(event.status || event.event_type)}
                      </span>
                    </div>
                    <p className="mt-2 text-xs uppercase tracking-[0.18em] text-slate-400">{formatDate(event.event_time)}</p>
                    <p className="mt-3 text-sm leading-6 text-slate-600">
                      {typeof event.details?.recommended_next_action === "string"
                        ? String(event.details.recommended_next_action)
                        : typeof event.details?.reason === "string"
                          ? String(event.details.reason)
                          : `Risk level: ${event.risk_level || "unknown"} | Probability: ${event.final_risk_probability ?? "--"}`}
                    </p>
                  </div>
                </div>
              ))
            ) : (
              <EmptyState title="Timeline will appear here" description="As soon as the backend has timeline events for this student, the journey view will render them here." />
            )}
          </div>
        </Card>

        <Card className="space-y-4">
          <SectionTitle
            eyebrow="Next actions"
            title="What you should focus on now"
            description="These come from the latest grounded recommendation bundle."
          />
          <div className="space-y-3">
            {latestPrediction.recommended_actions?.length ? (
              latestPrediction.recommended_actions.slice(0, 4).map((action) => (
                <div key={action.title} className="rounded-3xl border border-slate-200 bg-white px-4 py-4">
                  <div className="flex items-start gap-3">
                    <div className="mt-1 rounded-full bg-indigo-50 p-2 text-indigo-600">
                      <Flag className="h-4 w-4" />
                    </div>
                    <div>
                      <p className="font-semibold text-slate-900">{action.title}</p>
                      <p className="mt-1 text-sm leading-6 text-slate-600">{action.rationale}</p>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <EmptyState title="No recommended actions found" description="The current prediction did not return a visible action bundle." />
            )}
          </div>
          <Card className="bg-slate-950 text-white">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-300">Recovery guidance</p>
            <p className="mt-3 text-lg font-bold">{overview.recovery_plan.summary}</p>
            <p className="mt-3 text-sm leading-7 text-slate-300">
              {latestPrediction.ai_insights?.student_guidance?.motivation || "Keep showing up consistently. Each logged action helps the system reflect your progress more accurately."}
            </p>
          </Card>
        </Card>
      </div>
    </div>
  );
}

export function StudentReportsPage() {
  const { auth } = useAuth();
  const overviewQuery = useQuery({
    queryKey: ["student-overview-report", auth?.accessToken],
    queryFn: () => apiRequest<StudentOverview>("/student/me/overview", { token: auth?.accessToken }),
  });

  if (overviewQuery.isLoading) {
    return <DashboardSkeleton />;
  }
  if (overviewQuery.isError || !overviewQuery.data) {
    return <EmptyState title="Student reports unavailable" description="Reports need a successful self-overview response to render." />;
  }

  const latestPrediction = overviewQuery.data.latest_prediction;

  return (
    <div className="space-y-6">
      <SectionTitle
        eyebrow="Student reports"
        title="A cleaner analytics view for the student side"
        description="The dashboard gives quick action. This page gives a slightly more analytical view without overwhelming the student."
      />
      <div className="grid gap-6 xl:grid-cols-2">
        <BarChartCard
          title="Current student risk indicators"
          description="A compact view of the latest backend-generated indicators that influence the student experience."
          data={[
            { label: "Probability", value: Math.round((latestPrediction.final_risk_probability || 0) * 100) },
            { label: "Triggers", value: latestPrediction.trigger_alerts?.trigger_count || 0 },
            { label: "Warnings", value: overviewQuery.data.warning_history.warnings.length },
          ]}
          xKey="label"
          dataKey="value"
        />
        <PieChartCard
          title="Warning cycle posture"
          description="Shows how much of the student’s current state is driven by direct warnings versus ongoing recommendation work."
          data={[
            { label: "Warnings", value: overviewQuery.data.warning_history.warnings.length },
            { label: "Recommended actions", value: overviewQuery.data.latest_prediction.recommended_actions?.length || 0 },
          ]}
          nameKey="label"
          dataKey="value"
        />
      </div>
    </div>
  );
}

export function StudentJourneyPage() {
  const { auth } = useAuth();
  const overviewQuery = useQuery({
    queryKey: ["student-overview-journey", auth?.accessToken],
    queryFn: () => apiRequest<StudentOverview>("/student/me/overview", { token: auth?.accessToken }),
  });
  const timelineQuery = useQuery({
    queryKey: ["student-full-timeline", auth?.studentId, auth?.accessToken],
    queryFn: () => apiRequest<StudentTimeline>(`/timeline/${auth?.studentId}`, { token: auth?.accessToken }),
    enabled: Boolean(auth?.studentId),
  });

  if (overviewQuery.isLoading || timelineQuery.isLoading) {
    return <DashboardSkeleton />;
  }
  if (overviewQuery.isError || !overviewQuery.data) {
    return <EmptyState title="Journey unavailable" description="The student journey page needs a successful self-overview response." />;
  }

  const overview = overviewQuery.data;
  const profileContext = overview.profile.profile_context || {};
  const registration = (profileContext.registration as Record<string, unknown> | undefined) || {};
  const timeline = timelineQuery.data?.timeline || [];

  return (
    <div className="space-y-6">
      <SectionTitle
        eyebrow="Student journey"
        title="A fuller progress story, not just a score"
        description="This page is where the student experience becomes more immersive. It keeps the professional tone, but gives the student a stronger sense of momentum and ownership."
      />
      <div className="grid gap-6 xl:grid-cols-[0.8fr_1.2fr]">
        <Card className="space-y-5">
          <div className="flex items-center gap-4">
            <div className="rounded-full bg-indigo-50 p-3 text-indigo-600">
              <UserCircle2 className="h-8 w-8" />
            </div>
            <div>
              <h3 className="text-xl font-bold text-slate-950">Student identity snapshot</h3>
              <p className="text-sm text-slate-500">A clear academic context card for the logged-in student.</p>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <JourneyInfo label="Register number" value={String(overview.profile.external_student_ref || overview.student_id)} />
            <JourneyInfo label="Faculty mentor" value={String(overview.profile.faculty_name || "Unassigned")} />
            <JourneyInfo label="Counsellor" value={String(overview.profile.counsellor_name || "Unassigned")} />
            <JourneyInfo label="Current outcome" value={String(registration.final_status || "Unknown")} />
            <JourneyInfo label="Branch" value={String((profileContext.branch as string) || "Unknown")} />
            <JourneyInfo label="Region" value={String((profileContext.region as string) || "Unknown")} />
          </div>
          <Card className="bg-slate-950 text-white">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-300">Motivation</p>
            <p className="mt-3 text-lg font-bold">
              {overview.latest_prediction.ai_insights?.student_guidance?.summary || "Your progress changes when your daily actions change. Small improvements matter."}
            </p>
          </Card>
        </Card>

        <Card className="space-y-4 bg-gradient-to-br from-white to-teal-50/50">
          <SectionTitle
            eyebrow="Full timeline"
            title="Every important step in one place"
            description="This version shows the full student timeline instead of only the short dashboard snippet."
          />
          <div className="space-y-5">
            {timeline.length ? (
              timeline.map((event, index) => (
                <div key={`${event.event_type}-${index}`} className="timeline-track relative pl-12">
                  <div className="absolute left-0 top-1 flex h-9 w-9 items-center justify-center rounded-full border border-teal-200 bg-white shadow-soft">
                    {event.status?.toLowerCase().includes("resolved") ? (
                      <Trophy className="h-4 w-4 text-teal-600" />
                    ) : event.event_type.includes("alert") ? (
                      <ShieldAlert className="h-4 w-4 text-amber-600" />
                    ) : (
                      <Flame className="h-4 w-4 text-indigo-600" />
                    )}
                  </div>
                  <div className="rounded-3xl border border-white/70 bg-white/90 p-4 shadow-soft">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <h3 className="font-bold text-slate-950">{event.title}</h3>
                      <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
                        {titleCase(event.status || event.event_type)}
                      </span>
                    </div>
                    <p className="mt-2 text-xs uppercase tracking-[0.18em] text-slate-400">{formatDate(event.event_time)}</p>
                    <p className="mt-3 text-sm leading-6 text-slate-600">
                      {typeof event.details?.reason === "string"
                        ? String(event.details.reason)
                        : typeof event.details?.recommended_next_action === "string"
                          ? String(event.details.recommended_next_action)
                          : `Risk level: ${event.risk_level || "unknown"} | Probability: ${event.final_risk_probability ?? "--"}`}
                    </p>
                  </div>
                </div>
              ))
            ) : (
              <EmptyState title="No timeline events available" description="The full timeline will appear here once the backend has event history for this student." />
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

function JourneyInfo({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{label}</p>
      <p className="mt-2 text-sm font-semibold text-slate-900">{value}</p>
    </div>
  );
}
