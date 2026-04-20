import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { UploadCloud } from "lucide-react";
import { NavLink } from "react-router-dom";

import { BarChartCard, PieChartCard } from "../components/charts";
import { Button, Card, EmptyState, LoadingCard, SectionTitle, StatCard } from "../components/ui";
import { API_BASE_URL, apiRequest } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ImportCoverage, InstitutionOverview, OperationalOverview } from "../types";

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

export function AdminDashboardPage() {
  const { auth } = useAuth();
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
      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <Card className="bg-slate-900 border-none text-white shadow-none p-8">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="animate-rise">
              <p className="text-[11px] font-bold uppercase tracking-wider text-blue-400">Admin dashboard</p>
              <h2 className="mt-2 text-2xl font-semibold tracking-tight">Institution-wide visibility with clean operational depth.</h2>
              <p className="mt-3 max-w-3xl text-[13px] leading-6 text-slate-400">
                The admin landing experience stays executive-first. Uploads and full reports remain available, but the first screen is designed for quick institutional understanding before deeper operational work.
              </p>
            </div>
            <NavLink to="/app/admin/imports" className="animate-rise">
              <Button className="bg-white text-slate-950 hover:bg-slate-100">
                <UploadCloud className="mr-2 h-4 w-4" />
                Upload new cohort
              </Button>
            </NavLink>
          </div>
          <div className="mt-6 grid gap-4 sm:grid-cols-3 animate-rise" style={{ animationDelay: '100ms' }}>
            <div className="rounded border border-white/10 bg-white/5 p-4">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Imported students</p>
              <p className="mt-1 text-sm font-medium text-white">{coverage.total_imported_students} currently visible in the imported cohort</p>
            </div>
            <div className="rounded border border-white/10 bg-white/5 p-4">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Scoring readiness</p>
              <p className="mt-1 text-sm font-medium text-white">{coverage.scored_students} students already have prediction output</p>
            </div>
            <div className="rounded border border-white/10 bg-white/5 p-4">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Outcome posture</p>
              <p className="mt-1 text-sm font-medium text-white">{overview.total_high_risk_students} students are currently high risk</p>
            </div>
          </div>
        </Card>

        <Card className="space-y-4 bg-white/92">
          <SectionTitle
            eyebrow="Executive reading"
            title="What admins should see first"
            description="The first screen stays summary-first so institution leaders can orient quickly before moving into reports, imports, or operations."
          />
          <div className="space-y-3">
            <AdminInfoRow label="Why uploads are separate" value="Imports are operational tasks, so they should not dominate the executive landing screen." />
            <AdminInfoRow label="Why reports are a dedicated route" value="Heavy charts belong in their own analytics workspace instead of overloading the first admin view." />
            <AdminInfoRow label="Copilot role" value="Use the admin copilot for institution-scoped questions, comparisons, and reporting follow-ups grounded to backend data." />
          </div>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total students" value={String(overview.total_students)} note="Current institution-wide live student count in the risk overview." />
        <StatCard label="High risk" value={String(overview.total_high_risk_students)} note="Students currently classified as high risk." accent="rose" />
        <StatCard label="I-grade risk" value={String(overview.total_students_with_i_grade_risk)} note="Students currently below the safe subject-wise attendance band." accent="teal" />
        <StatCard label="R-grade risk" value={String(overview.total_students_with_r_grade_risk)} note="Students currently in repeat-grade attendance territory." accent="gold" />
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <BarChartCard
          title="Department risk distribution"
          description="Shows which departments carry the most high-risk load."
          data={overview.department_buckets.map((item) => ({
            label: item.bucket_label,
            value: item.high_risk_students,
          }))}
          xKey="label"
          dataKey="value"
        />
        <PieChartCard
          title="Attendance policy posture"
          description="A quick institution-wide view of overall shortage, I-grade pressure, and R-grade pressure."
          data={[
            { label: "Overall shortage", value: overview.total_students_with_overall_shortage },
            { label: "I-grade", value: overview.total_students_with_i_grade_risk },
            { label: "R-grade", value: overview.total_students_with_r_grade_risk },
            { label: "High risk", value: overview.total_high_risk_students },
          ]}
          nameKey="label"
          dataKey="value"
        />
      </div>

      <BarChartCard
        title="Subject pressure hotspots"
        description="Shows which subjects are currently pulling the most students below the institutional attendance policy."
        data={overview.top_subject_pressure.map((item) => ({
          label: item.subject_name,
          value: item.students_below_threshold,
        }))}
        xKey="label"
        dataKey="value"
      />

      <Card className="bg-slate-950 text-white">
        <p className="text-xs uppercase tracking-[0.22em] text-slate-300">Executive summary</p>
        <p className="mt-3 text-lg font-bold">{overview.summary}</p>
      </Card>
    </div>
  );
}

function AdminInfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{label}</p>
      <p className="mt-2 text-sm leading-7 text-slate-700">{value}</p>
    </div>
  );
}

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
        title="A dedicated institutional analytics workspace"
        description="The login dashboard stays compact. This route holds the denser institutional views that would otherwise make the first screen too heavy."
        action={
          <div className="flex flex-wrap gap-2">
            <ExportButton token={auth?.accessToken} path="/reports/exports/institution-overview" label="Export overview" />
            <ExportButton token={auth?.accessToken} path="/reports/exports/outcome-distribution" label="Export outcomes" />
          </div>
        }
      />
      <div className="grid gap-6 xl:grid-cols-2">
        <BarChartCard
          title="Region-wise high-risk load"
          description="Administrative comparison view across imported profile regions."
          data={overview.region_buckets.map((item) => ({
            label: item.bucket_label,
            value: item.high_risk_students,
          }))}
          xKey="label"
          dataKey="value"
        />
        <BarChartCard
          title="Attendance policy posture"
          description="Institution-wide split of overall shortage, I-grade, and R-grade pressure."
          data={[
            { label: "Overall shortage", value: overview.total_students_with_overall_shortage },
            { label: "I-grade", value: overview.total_students_with_i_grade_risk },
            { label: "R-grade", value: overview.total_students_with_r_grade_risk },
            { label: "High risk", value: overview.total_high_risk_students },
          ]}
          xKey="label"
          dataKey="value"
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <BarChartCard
          title="Category-wise high-risk load"
          description="Administrative comparison view across imported profile categories."
          data={overview.category_buckets.map((item) => ({
            label: item.bucket_label,
            value: item.high_risk_students,
          }))}
          xKey="label"
          dataKey="value"
        />
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
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <BarChartCard
          title="Branch attendance pressure"
          description="Shows which branches carry the strongest combined overall-shortage and repeat-grade pressure."
          data={overview.branch_pressure.map((item) => ({
            label: item.bucket_label,
            value: item.students_with_r_grade_risk + item.students_with_overall_shortage,
          }))}
          xKey="label"
          dataKey="value"
        />
        <BarChartCard
          title="Semester attendance pressure"
          description="Shows which semester slices currently need the most institution-wide recovery attention."
          data={overview.semester_pressure.map((item) => ({
            label: item.bucket_label,
            value: item.students_with_r_grade_risk + item.students_with_overall_shortage,
          }))}
          xKey="label"
          dataKey="value"
        />
      </div>
    </div>
  );
}

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

  return (
    <div className="space-y-6">
      <SectionTitle
        eyebrow="Admin operations"
        title="Operational depth beyond the dashboard snapshot"
        description="This page is for the more serious administrative view: import health, intervention effectiveness, and the system-wide workflow posture."
        action={<ExportButton token={auth?.accessToken} path="/reports/exports/intervention-effectiveness" label="Export intervention effectiveness" />}
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total intervention actions" value={String(operations.intervention_effectiveness.total_actions)} note="All logged intervention actions across the system." />
        <StatCard label="Reviewed actions" value={String(operations.intervention_effectiveness.total_reviewed_actions)} note={`${operations.intervention_effectiveness.review_coverage_percent}% review coverage`} accent="teal" />
        <StatCard label="Improved cases" value={String(operations.intervention_effectiveness.total_improved_cases)} note={`${operations.intervention_effectiveness.improvement_rate_percent}% improvement rate`} accent="gold" />
        <StatCard label="Imported unscored" value={String(coverage.unscored_students)} note="Imported students who still do not have prediction output." accent="rose" />
      </div>

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
          description="This is useful for admins because it turns a chart-heavy page back into a plain-language interpretation."
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
      <UploadCloud className="mr-2 h-4 w-4" />
      {label}
    </Button>
  );
}
