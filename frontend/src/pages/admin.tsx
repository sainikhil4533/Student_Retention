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
      <SectionTitle
        eyebrow="Admin dashboard"
        title="Institution-wide visibility with clean operational depth"
        description="The admin landing experience stays executive-first. Uploads and full reports remain available, but the first screen is designed for quick institutional understanding."
        action={
          <NavLink to="/app/admin/imports">
            <Button>
              <UploadCloud className="mr-2 h-4 w-4" />
              Upload new cohort
            </Button>
          </NavLink>
        }
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total students" value={String(overview.total_students)} note="Current institution-wide live student count in the risk overview." />
        <StatCard label="High risk" value={String(overview.total_high_risk_students)} note="Students currently classified as high risk." accent="rose" />
        <StatCard label="Imported students" value={String(coverage.total_imported_students)} note="Current imported cohort size visible through import coverage." accent="teal" />
        <StatCard label="Scored imported students" value={String(coverage.scored_students)} note="Imported students that already have a prediction generated." accent="gold" />
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
          title="Outcome distribution"
          description="A quick institution-wide outcome posture view."
          data={overview.outcome_distribution.map((item) => ({
            label: item.outcome_status,
            value: item.student_count,
          }))}
          nameKey="label"
          dataKey="value"
        />
      </div>

      <Card className="bg-slate-950 text-white">
        <p className="text-xs uppercase tracking-[0.22em] text-slate-300">Executive summary</p>
        <p className="mt-3 text-lg font-bold">{overview.summary}</p>
      </Card>
    </div>
  );
}

export function AdminReportsPage() {
  const { auth } = useAuth();
  const institutionQuery = useQuery({
    queryKey: ["institution-report", auth?.accessToken],
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
          title="Category-wise high-risk load"
          description="Administrative comparison view across imported profile categories."
          data={overview.category_buckets.map((item) => ({
            label: item.bucket_label,
            value: item.high_risk_students,
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
        `/admin/imports/vignan?trigger_scoring=${triggerScoring}&dry_run=${dryRun}`,
        {
          method: "POST",
          token: auth?.accessToken,
          body: form,
          isFormData: true,
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
              Accepts the production-style Vignan import formats supported by the backend: `.xlsx` or `.zip` with named CSV sheets.
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
          <Card className="bg-slate-950 text-white">
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
    queryKey: ["import-coverage-detailed", auth?.accessToken],
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
