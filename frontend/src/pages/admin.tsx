import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronLeft, ChevronRight, Download, ShieldAlert, ShieldCheck, UploadCloud, Users } from "lucide-react";
import { NavLink, useNavigate, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";

import { BarChartCard, PieChartCard } from "../components/charts";
import { Button, Card, EmptyState, LoadingCard, SectionTitle, StatCard } from "../components/ui";
import { API_BASE_URL, apiRequest } from "../lib/api";
import { useAuth } from "../lib/auth";
import { CounsellorAccountabilityResponse, ImportCoverage, InstitutionOverview, OperationalOverview, StudentDirectoryResponse } from "../types";

/* ─────────────────────── helpers ─────────────────────── */

const TIER_CONFIG: Record<string, { label: string; color: string; bg: string; border: string; icon: typeof AlertTriangle; textColor: string }> = {
  HIGH:   { label: "High Risk",   color: "text-rose-600",   bg: "bg-rose-50",   border: "border-rose-200", icon: AlertTriangle, textColor: "text-rose-700" },
  MEDIUM: { label: "Medium Risk", color: "text-amber-600",  bg: "bg-amber-50",  border: "border-amber-200", icon: ShieldAlert,  textColor: "text-amber-700" },
  LOW:    { label: "Low Risk",    color: "text-blue-600",   bg: "bg-blue-50",   border: "border-blue-200", icon: ShieldCheck,  textColor: "text-blue-700" },
  SAFE:   { label: "Safe",        color: "text-emerald-600",bg: "bg-emerald-50",border: "border-emerald-200", icon: CheckCircle2, textColor: "text-emerald-700" },
};

function tierCount(overview: InstitutionOverview, tier: string): number {
  if (tier === "HIGH") return overview.total_high_risk_students;
  if (tier === "MEDIUM") return overview.total_medium_risk_students;
  if (tier === "LOW") return overview.total_low_risk_students;
  if (tier === "SAFE") return overview.total_safe_students;
  return 0;
}

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

/* ═══════════════════════════════════════════════════════════
   ADMIN DASHBOARD — 4-tier risk overview + clickable cards
   ═══════════════════════════════════════════════════════════ */

export function AdminDashboardPage() {
  const { auth } = useAuth();
  const navigate = useNavigate();

  const institutionQuery = useQuery({
    queryKey: ["institution-overview", auth?.accessToken],
    queryFn: () => apiRequest<InstitutionOverview>("/institution/risk-overview", { token: auth?.accessToken }),
  });
  const importQuery = useQuery({
    queryKey: ["import-coverage", auth?.accessToken],
    queryFn: () => apiRequest<ImportCoverage>("/reports/import-coverage", { token: auth?.accessToken }),
  });

  if (institutionQuery.isLoading || importQuery.isLoading) {
    return <DashboardSkeleton />;
  }
  if (institutionQuery.isError || importQuery.isError || !institutionQuery.data || !importQuery.data) {
    return <EmptyState title="Admin dashboard unavailable" description="The institution overview or import coverage endpoints are not currently returning data." />;
  }

  const overview = institutionQuery.data;
  const coverage = importQuery.data;

  return (
    <div className="space-y-6">
      {/* ── Hero banner ── */}
      <Card className="bg-slate-900 border-none text-white shadow-none p-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="animate-rise">
            <p className="text-[11px] font-bold uppercase tracking-wider text-blue-400">Admin dashboard</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight">Institution Risk Overview</h2>
            <p className="mt-3 max-w-3xl text-[13px] leading-6 text-slate-400">
              {overview.total_students} students tracked · {coverage.scored_students} scored · Click any risk tier below to see individual students, their reasons, and counsellor assignments.
            </p>
          </div>
          <NavLink to="/app/admin/imports" className="animate-rise">
            <Button className="bg-white text-slate-950 hover:bg-slate-100">
              <UploadCloud className="mr-2 h-4 w-4" />
              Upload new cohort
            </Button>
          </NavLink>
        </div>
      </Card>

      {/* ── 4 clickable tier cards ── */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {(["HIGH", "MEDIUM", "LOW", "SAFE"] as const).map((tier, i) => {
          const cfg = TIER_CONFIG[tier];
          const Icon = cfg.icon;
          const count = tierCount(overview, tier);
          const pct = overview.total_students > 0 ? ((count / overview.total_students) * 100).toFixed(1) : "0";
          return (
            <motion.div
              key={tier}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.08, duration: 0.35 }}
            >
              <button
                onClick={() => navigate(`/app/admin/students?tier=${tier}`)}
                className={`w-full rounded-xl border-2 ${cfg.border} ${cfg.bg} p-5 text-left transition-all hover:shadow-lg hover:scale-[1.02] active:scale-[0.98] cursor-pointer`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Icon className={`h-5 w-5 ${cfg.color}`} />
                    <span className={`text-xs font-bold uppercase tracking-wider ${cfg.color}`}>{cfg.label}</span>
                  </div>
                  <ArrowRight className={`h-4 w-4 ${cfg.color} opacity-60`} />
                </div>
                <p className={`mt-3 text-4xl font-extrabold tracking-tight ${cfg.textColor}`}>{count}</p>
                <p className="mt-1 text-sm text-slate-500">{pct}% of all students</p>
              </button>
            </motion.div>
          );
        })}
      </div>

      {/* ── Quick stats row ── */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total students" value={String(overview.total_students)} note="Current institution-wide live student count." />
        <StatCard label="I-grade risk" value={String(overview.total_students_with_i_grade_risk)} note="Students below safe subject-wise attendance." accent="teal" />
        <StatCard label="R-grade risk" value={String(overview.total_students_with_r_grade_risk)} note="Students in repeat-grade attendance territory." accent="gold" />
        <StatCard label="Overdue follow-ups" value={String(overview.total_followup_overdue_students)} note="Students with pending counsellor action." accent="rose" />
      </div>

      {/* ── Risk tier pie chart + department bar ── */}
      <div className="grid gap-6 xl:grid-cols-2">
        <PieChartCard
          title="Risk tier distribution"
          description="Institution-wide breakdown across all 4 risk tiers."
          data={[
            { label: "High", value: overview.total_high_risk_students },
            { label: "Medium", value: overview.total_medium_risk_students },
            { label: "Low", value: overview.total_low_risk_students },
            { label: "Safe", value: overview.total_safe_students },
          ]}
          nameKey="label"
          dataKey="value"
        />
        <BarChartCard
          title="Department risk distribution"
          description="Which departments carry the most high-risk students."
          data={overview.department_buckets.map((item) => ({
            label: item.bucket_label,
            value: item.high_risk_students,
          }))}
          xKey="label"
          dataKey="value"
        />
      </div>

      {/* ── Subject pressure bar ── */}
      <BarChartCard
        title="Subject pressure hotspots"
        description="Subjects currently pulling the most students below the institutional attendance policy."
        data={overview.top_subject_pressure.map((item) => ({
          label: item.subject_name,
          value: item.students_below_threshold,
        }))}
        xKey="label"
        dataKey="value"
      />

      {/* ── Executive summary ── */}
      <Card className="bg-slate-950 text-white">
        <p className="text-xs uppercase tracking-[0.22em] text-slate-300">Executive summary</p>
        <p className="mt-3 text-lg font-bold">{overview.summary}</p>
      </Card>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════
   ADMIN STUDENTS — Tier drill-down directory with table
   ═══════════════════════════════════════════════════════════ */

export function AdminStudentsPage() {
  const { auth } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedTier, setSelectedTier] = useState(searchParams.get("tier") || "ALL");
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 25;

  const studentsQuery = useQuery({
    queryKey: ["admin-students", auth?.accessToken, selectedTier, currentPage],
    queryFn: () =>
      apiRequest<StudentDirectoryResponse>(
        `/institution/students?risk_level=${selectedTier}&page=${currentPage}&page_size=${pageSize}`,
        { token: auth?.accessToken }
      ),
  });

  function handleTierChange(tier: string) {
    setSelectedTier(tier);
    setCurrentPage(1);
    setSearchParams(tier === "ALL" ? {} : { tier });
  }

  return (
    <div className="space-y-6">
      <SectionTitle
        eyebrow="Student directory"
        title="Drill down by risk tier"
        description="See exactly who is in each risk category, why they were flagged, and which counsellor is assigned."
      />

      {/* ── Tier filter pills ── */}
      <div className="flex flex-wrap gap-2">
        {["ALL", "HIGH", "MEDIUM", "LOW", "SAFE"].map((tier) => {
          const isActive = selectedTier === tier;
          const cfg = tier === "ALL" ? null : TIER_CONFIG[tier];
          return (
            <button
              key={tier}
              onClick={() => handleTierChange(tier)}
              className={`rounded-lg px-4 py-2 text-sm font-semibold transition-all ${
                isActive
                  ? cfg
                    ? `${cfg.bg} ${cfg.color} ${cfg.border} border-2`
                    : "bg-slate-900 text-white border-2 border-slate-900"
                  : "bg-white text-slate-600 border border-slate-200 hover:border-slate-300 hover:bg-slate-50"
              }`}
            >
              {tier === "ALL" ? "All Students" : TIER_CONFIG[tier].label}
            </button>
          );
        })}
      </div>

      {/* ── Student table ── */}
      {studentsQuery.isLoading ? (
        <DashboardSkeleton />
      ) : studentsQuery.isError || !studentsQuery.data ? (
        <EmptyState title="Could not load students" description="The student directory API did not return data. Check that the backend is running." />
      ) : studentsQuery.data.students.length === 0 ? (
        <EmptyState
          title={`No ${selectedTier === "ALL" ? "" : selectedTier.toLowerCase() + " risk "}students found`}
          description="There are no students matching the current filter criteria."
        />
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/80">
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">Student ID</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">Risk Level</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">Probability</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">Branch</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">Attendance</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">Top Risk Reasons</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">Counsellor</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">Case State</th>
                </tr>
              </thead>
              <tbody>
                {studentsQuery.data.students.map((student, idx) => {
                  const cfg = TIER_CONFIG[student.risk_level] || TIER_CONFIG.SAFE;
                  return (
                    <motion.tr
                      key={student.student_id}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: idx * 0.02 }}
                      className="border-b border-slate-100 hover:bg-slate-50/60 transition"
                    >
                      <td className="px-4 py-3 font-medium text-slate-900">{student.student_id}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold ${cfg.bg} ${cfg.color} ${cfg.border} border`}>
                          {student.risk_level}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-slate-700">
                        {(student.risk_probability * 100).toFixed(1)}%
                      </td>
                      <td className="px-4 py-3 text-slate-600">{student.branch || "—"}</td>
                      <td className="px-4 py-3">
                        {student.overall_attendance_percent != null ? (
                          <span className={student.overall_attendance_percent < 75 ? "text-rose-600 font-semibold" : "text-slate-700"}>
                            {student.overall_attendance_percent.toFixed(1)}%
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 max-w-xs">
                        {student.top_risk_reasons.length > 0 ? (
                          <ul className="space-y-0.5">
                            {student.top_risk_reasons.map((reason, i) => (
                              <li key={i} className="text-xs text-slate-600 leading-snug">• {reason}</li>
                            ))}
                          </ul>
                        ) : (
                          <span className="text-xs text-slate-400">No specific reasons flagged</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-600 text-xs">
                        {student.counsellor_name || <span className="text-slate-400">Unassigned</span>}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${
                          student.case_state === "high_risk_active" || student.case_state === "critical_unattended_case"
                            ? "bg-rose-50 text-rose-700 border border-rose-200"
                            : student.case_state === "resolved" || student.case_state === "low_risk_stable"
                              ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                              : "bg-slate-100 text-slate-600 border border-slate-200"
                        }`}>
                          {(student.case_state || "unknown").replace(/_/g, " ")}
                        </span>
                        {student.has_overdue_followup && (
                          <span className="ml-1.5 inline-flex items-center rounded-md bg-rose-100 text-rose-700 px-1.5 py-0.5 text-[10px] font-bold">
                            OVERDUE
                          </span>
                        )}
                      </td>
                    </motion.tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* ── Pagination ── */}
          {studentsQuery.data.total_pages > 1 && (
            <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3 bg-slate-50/50">
              <p className="text-sm text-slate-500">
                Showing page {studentsQuery.data.page} of {studentsQuery.data.total_pages} · {studentsQuery.data.total_students} total students
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="text-sm font-medium text-slate-700">{currentPage}</span>
                <Button
                  variant="secondary"
                  disabled={currentPage >= studentsQuery.data.total_pages}
                  onClick={() => setCurrentPage((p) => p + 1)}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════
   ADMIN REPORTS — Fixed charts (no more undefined labels)
   ═══════════════════════════════════════════════════════════ */

export function AdminReportsPage() {
  const { auth } = useAuth();
  const institutionQuery = useQuery({
    queryKey: ["institution-overview", auth?.accessToken],
    queryFn: () => apiRequest<InstitutionOverview>("/institution/risk-overview", { token: auth?.accessToken }),
  });

  if (institutionQuery.isLoading) {
    return <DashboardSkeleton />;
  }
  if (institutionQuery.isError || !institutionQuery.data) {
    return <EmptyState title="Admin reports unavailable" description="The institution risk overview endpoint is required for this report workspace." />;
  }

  const overview = institutionQuery.data;

  return (
    <div className="space-y-6">
      <SectionTitle
        eyebrow="Admin reports"
        title="Institutional analytics workspace"
        description="Deeper analytics views — risk distribution, attendance pressure, and subject hotspots."
        action={
          <div className="flex flex-wrap gap-2">
            <ExportButton token={auth?.accessToken} path="/reports/exports/institution-overview" label="Export overview" />
            <ExportButton token={auth?.accessToken} path="/reports/exports/outcome-distribution" label="Export outcomes" />
          </div>
        }
      />

      {/* ── Tier distribution + attendance posture ── */}
      <div className="grid gap-6 xl:grid-cols-2">
        <PieChartCard
          title="Risk tier distribution"
          description="4-tier classification of all students: HIGH ≥65%, MEDIUM ≥40%, LOW ≥20%, SAFE <20%."
          data={[
            { label: "High", value: overview.total_high_risk_students },
            { label: "Medium", value: overview.total_medium_risk_students },
            { label: "Low", value: overview.total_low_risk_students },
            { label: "Safe", value: overview.total_safe_students },
          ]}
          nameKey="label"
          dataKey="value"
        />
        <BarChartCard
          title="Attendance policy posture"
          description="Institution-wide split of overall shortage, I-grade, and R-grade pressure."
          data={[
            { label: "Overall shortage", value: overview.total_students_with_overall_shortage },
            { label: "I-grade", value: overview.total_students_with_i_grade_risk },
            { label: "R-grade", value: overview.total_students_with_r_grade_risk },
          ]}
          xKey="label"
          dataKey="value"
        />
      </div>

      {/* ── Subject + branch pressure ── */}
      <div className="grid gap-6 xl:grid-cols-2">
        <BarChartCard
          title="Top subject hotspots"
          description="Subjects with the highest number of students below attendance policy."
          data={overview.top_subject_pressure.map((item) => ({
            label: item.subject_name,
            value: item.students_below_threshold,
          }))}
          xKey="label"
          dataKey="value"
        />
        <BarChartCard
          title="Branch attendance pressure"
          description="Which branches carry the strongest overall-shortage and repeat-grade pressure."
          data={overview.branch_pressure.map((item) => ({
            label: item.bucket_label,
            value: item.students_with_r_grade_risk + item.students_with_overall_shortage,
          }))}
          xKey="label"
          dataKey="value"
        />
      </div>

      {/* ── Semester pressure ── */}
      <div className="grid gap-6 xl:grid-cols-2">
        <BarChartCard
          title="Semester attendance pressure"
          description="Which semester slices currently need the most institution-wide recovery attention."
          data={overview.semester_pressure.map((item) => ({
            label: item.bucket_label,
            value: item.students_with_r_grade_risk + item.students_with_overall_shortage,
          }))}
          xKey="label"
          dataKey="value"
        />
        <BarChartCard
          title="Outcome distribution"
          description="How students are distributed across final outcomes."
          data={overview.outcome_distribution.map((item) => ({
            label: item.outcome_status,
            value: item.student_count,
          }))}
          xKey="label"
          dataKey="value"
        />
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════
   ADMIN IMPORTS — unchanged from original
   ═══════════════════════════════════════════════════════════ */

export function AdminImportsPage() {
  const { auth } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [triggerScoring, setTriggerScoring] = useState(true);
  const [dryRun, setDryRun] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleUpload() {
    if (!file) {
      setError("Choose a .xlsx or .zip file before uploading.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await apiRequest<Record<string, unknown>>(
        `/admin/imports/institution?trigger_scoring=${triggerScoring}&dry_run=${dryRun}`,
        {
          method: "POST",
          token: auth?.accessToken,
          body: form,
          isFormData: true,
          timeoutMs: 600000,
        },
      );
      setResult(response);
    } catch (unknownError) {
      setError(unknownError instanceof Error ? unknownError.message : "Upload failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <SectionTitle
        eyebrow="Admin imports"
        title="Controlled institutional upload workspace"
        description="Only admins can access this screen. It is intentionally separated from the first dashboard view because uploads are operational tasks, not something that should dominate executive analytics."
      />

      <Card className="space-y-5">
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-3xl border border-dashed border-slate-300 bg-slate-50 p-5">
            <p className="text-sm font-semibold text-slate-900">Upload file</p>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Accepts the generalized institution import formats supported by the backend: `.xlsx` or `.zip` with named CSV sheets.
            </p>
            <input
              type="file"
              accept=".xlsx,.zip"
              className="mt-4 block w-full text-sm"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </div>

          <div className="space-y-4 rounded-3xl border border-slate-200 bg-white p-5">
            <label className="flex items-center gap-3 text-sm font-medium text-slate-700">
              <input type="checkbox" checked={triggerScoring} onChange={(event) => setTriggerScoring(event.target.checked)} />
              Trigger scoring after import
            </label>
            <label className="flex items-center gap-3 text-sm font-medium text-slate-700">
              <input type="checkbox" checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} />
              Dry run only
            </label>
            <p className="text-sm leading-6 text-slate-600">
              Dry run is the safest pre-import validation mode because it checks sheets and columns without persisting student records.
            </p>
            <Button onClick={handleUpload} disabled={submitting}>
              {submitting ? "Uploading..." : "Start import"}
            </Button>
          </div>
        </div>

        {error ? <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : null}

        {result ? (
          <Card className="border-slate-900/80 text-white" style={{ background: "#020617" }}>
            <p className="text-xs uppercase tracking-[0.22em] text-slate-300">Latest import response</p>
            <pre className="mt-4 overflow-auto whitespace-pre-wrap text-sm leading-6 text-slate-100">
              {JSON.stringify(result, null, 2)}
            </pre>
          </Card>
        ) : null}
      </Card>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════
   ADMIN OPERATIONS — with 4-tier awareness
   ═══════════════════════════════════════════════════════════ */

export function AdminOperationsPage() {
  const { auth } = useAuth();
  const operationsQuery = useQuery({
    queryKey: ["operations-overview", auth?.accessToken],
    queryFn: () => apiRequest<OperationalOverview>("/reports/operations-overview", { token: auth?.accessToken }),
  });
  const importCoverageQuery = useQuery({
    queryKey: ["import-coverage", auth?.accessToken],
    queryFn: () => apiRequest<ImportCoverage>("/reports/import-coverage", { token: auth?.accessToken }),
  });

  const counsellorQuery = useQuery({
    queryKey: ["counsellor-accountability", auth?.accessToken],
    queryFn: () => apiRequest<CounsellorAccountabilityResponse>("/institution/counsellor-accountability", { token: auth?.accessToken }),
  });

  if (operationsQuery.isLoading || importCoverageQuery.isLoading) {
    return <DashboardSkeleton />;
  }
  if (operationsQuery.isError || importCoverageQuery.isError || !operationsQuery.data || !importCoverageQuery.data) {
    return <EmptyState title="Admin operations unavailable" description="The deeper operational reporting endpoints are needed to build this admin page." />;
  }

  const operations = operationsQuery.data;
  const coverage = importCoverageQuery.data;
  const topBranch = operations.institution_overview.branch_pressure[0];
  const topSemester = operations.institution_overview.semester_pressure[0];
  const topSubject = operations.institution_overview.top_subject_pressure[0];
  const counsellors = counsellorQuery.data?.counsellors ?? [];

  return (
    <div className="space-y-6">
      <SectionTitle
        eyebrow="Admin operations"
        title="Operational depth beyond the dashboard"
        description="Import health, intervention effectiveness, counsellor workload, and system-wide workflow posture."
        action={<ExportButton token={auth?.accessToken} path="/reports/exports/intervention-effectiveness" label="Export intervention effectiveness" />}
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total intervention actions" value={String(operations.intervention_effectiveness.total_actions)} note="All logged intervention actions across the system." />
        <StatCard label="Reviewed actions" value={String(operations.intervention_effectiveness.total_reviewed_actions)} note={`${operations.intervention_effectiveness.review_coverage_percent}% review coverage`} accent="teal" />
        <StatCard label="Improved cases" value={String(operations.intervention_effectiveness.total_improved_cases)} note={`${operations.intervention_effectiveness.improvement_rate_percent}% improvement rate`} accent="gold" />
        <StatCard label="Imported unscored" value={String(coverage.unscored_students)} note="Imported students who still do not have prediction output." accent="rose" />
      </div>

      {/* ── Counsellor Accountability ── */}
      <Card className="overflow-hidden p-0">
        <div className="px-5 pt-5 pb-3">
          <SectionTitle
            eyebrow="Counsellor accountability"
            title="Who is doing their duty?"
            description="Workload distribution, pending tasks, and overdue follow-ups per counsellor."
          />
        </div>
        {counsellorQuery.isLoading ? (
          <div className="p-5"><LoadingCard /></div>
        ) : counsellors.length === 0 ? (
          <div className="p-5"><EmptyState title="No counsellor data" description="No counsellors found in the system." /></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-t border-slate-200 bg-slate-50/80">
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">Counsellor</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-600">Email</th>
                  <th className="px-4 py-3 text-center font-semibold text-slate-600">Assigned</th>
                  <th className="px-4 py-3 text-center font-semibold text-slate-600">High Risk</th>
                  <th className="px-4 py-3 text-center font-semibold text-slate-600">Medium Risk</th>
                  <th className="px-4 py-3 text-center font-semibold text-slate-600">Pending</th>
                  <th className="px-4 py-3 text-center font-semibold text-slate-600">Overdue</th>
                  <th className="px-4 py-3 text-center font-semibold text-slate-600">Status</th>
                </tr>
              </thead>
              <tbody>
                {counsellors.map((c) => (
                  <tr key={c.counsellor_name} className="border-b border-slate-100 hover:bg-slate-50/60 transition">
                    <td className="px-4 py-3 font-medium text-slate-900">{c.counsellor_name}</td>
                    <td className="px-4 py-3 text-slate-500 text-xs">{c.counsellor_email || "—"}</td>
                    <td className="px-4 py-3 text-center text-slate-700">{c.total_assigned}</td>
                    <td className="px-4 py-3 text-center">
                      <span className={c.high_risk_count > 0 ? "text-rose-600 font-bold" : "text-slate-400"}>{c.high_risk_count}</span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={c.medium_risk_count > 0 ? "text-amber-600 font-semibold" : "text-slate-400"}>{c.medium_risk_count}</span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={c.pending_interventions > 0 ? "text-amber-600 font-semibold" : "text-slate-400"}>{c.pending_interventions}</span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={c.overdue_followups > 0 ? "text-rose-600 font-bold" : "text-slate-400"}>{c.overdue_followups}</span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold ${
                        c.performance_label === "overdue"
                          ? "bg-rose-50 text-rose-700 border border-rose-200"
                          : c.performance_label === "needs_attention"
                            ? "bg-amber-50 text-amber-700 border border-amber-200"
                            : "bg-emerald-50 text-emerald-700 border border-emerald-200"
                      }`}>
                        {c.performance_label === "overdue" ? "⚠ Overdue" : c.performance_label === "needs_attention" ? "Needs Attention" : "✓ On Track"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <BarChartCard
          title="Intervention effectiveness by action status"
          description="Shows which intervention states actually lead to outcomes and improvement."
          data={operations.intervention_effectiveness.action_effectiveness.map((item) => ({
            label: item.action_status,
            value: item.effectiveness_score,
          }))}
          xKey="label"
          dataKey="value"
        />
        <BarChartCard
          title="Import coverage friction"
          description="Highlights where imported cohorts still lose completeness or scoring readiness."
          data={[
            { label: "Missing LMS", value: coverage.students_missing_lms },
            { label: "Missing ERP", value: coverage.students_missing_erp },
            { label: "Missing finance", value: coverage.students_missing_finance },
            { label: "Missing counsellor email", value: coverage.students_missing_counsellor_email },
          ]}
          xKey="label"
          dataKey="value"
        />
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <StatCard
          label="Most pressured branch"
          value={topBranch?.bucket_label || "Unavailable"}
          note={
            topBranch
              ? `${topBranch.students_with_r_grade_risk} R-grade and ${topBranch.students_with_overall_shortage} overall-shortage students`
              : "No branch-pressure detail available yet."
          }
        />
        <StatCard
          label="Most pressured semester"
          value={topSemester?.bucket_label || "Unavailable"}
          note={
            topSemester
              ? `${topSemester.students_with_r_grade_risk} R-grade and ${topSemester.students_with_overall_shortage} overall-shortage students`
              : "No semester-pressure detail available yet."
          }
          accent="teal"
        />
        <StatCard
          label="Top subject hotspot"
          value={topSubject?.subject_name || "Unavailable"}
          note={
            topSubject
              ? `${topSubject.students_below_threshold} students below threshold`
              : "No subject hotspot detail available yet."
          }
          accent="gold"
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <BarChartCard
          title="Branch pressure from operations view"
          description="This helps admins move from abstract risk posture to the first branch-level action area."
          data={operations.institution_overview.branch_pressure.map((item) => ({
            label: item.bucket_label,
            value: item.students_with_r_grade_risk + item.students_with_overall_shortage,
          }))}
          xKey="label"
          dataKey="value"
        />
        <BarChartCard
          title="Semester pressure from operations view"
          description="This shows which semester slice currently concentrates the most attendance-policy stress."
          data={operations.institution_overview.semester_pressure.map((item) => ({
            label: item.bucket_label,
            value: item.students_with_r_grade_risk + item.students_with_overall_shortage,
          }))}
          xKey="label"
          dataKey="value"
        />
      </div>

      <Card className="space-y-4">
        <SectionTitle
          eyebrow="Operational reading"
          title="How the backend currently summarizes the institution"
          description="Turns chart-heavy data back into a plain-language interpretation."
        />
        <div className="grid gap-4 xl:grid-cols-2">
          <Card className="bg-slate-950 text-white">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-300">Institution overview</p>
            <p className="mt-3 text-base leading-7">{operations.institution_overview.summary}</p>
          </Card>
          <Card className="bg-white">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Intervention effectiveness</p>
            <p className="mt-3 text-base leading-7 text-slate-700">{operations.intervention_effectiveness.summary}</p>
          </Card>
        </div>
      </Card>
    </div>
  );
}


/* ─────────────────────── shared ─────────────────────── */

function ExportButton({
  token,
  path,
  label,
}: {
  token?: string | null;
  path: string;
  label: string;
}) {
  async function handleExport() {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
      throw new Error(`Export failed with status ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = path.split("/").pop() || "report.csv";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <Button variant="secondary" onClick={handleExport}>
      <Download className="mr-2 h-4 w-4" />
      {label}
    </Button>
  );
}
