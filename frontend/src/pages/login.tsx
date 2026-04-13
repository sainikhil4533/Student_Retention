import { FormEvent, useMemo, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { LockKeyhole, UserRound } from "lucide-react";

import { BrandLockup } from "../components/brand";
import { Button, Card } from "../components/ui";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

const roleCopy = {
  student: {
    title: "Student sign-in",
    description: "Use the credentials issued by the institution to access your dashboard, timeline, reports, and chatbot.",
    sample: "student_880001 / student_880001",
  },
  counsellor: {
    title: "Counsellor sign-in",
    description: "Enter your counsellor credentials to open the scoped priority queue, interventions workspace, and copilot.",
    sample: "counsellor_demo / counsellor_demo",
  },
  admin: {
    title: "Admin sign-in",
    description: "Enter the admin workspace to access institution analytics, imports, reports, and chatbot controls.",
    sample: "admin_demo / admin_demo",
  },
} as const;

export function RoleLoginPage() {
  const navigate = useNavigate();
  const { role = "student" } = useParams();
  const { auth, isAuthenticated, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const copy = useMemo(() => roleCopy[role as keyof typeof roleCopy] ?? roleCopy.student, [role]);

  if (isAuthenticated && auth) {
    return <Navigate to={resolveDashboardRoute(auth.role)} replace />;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await login({ username, password });
      navigate(resolveDashboardRoute(session.role), { replace: true });
    } catch (unknownError) {
      const detail =
        unknownError instanceof ApiError
          ? unknownError.detail
          : unknownError instanceof Error
            ? unknownError.message
            : "Unable to sign in.";
      setError(detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto grid min-h-[calc(100vh-110px)] max-w-7xl items-center gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[0.9fr_1.1fr] lg:px-8">
      <div className="space-y-6">
        <BrandLockup />
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-600">Secure access</p>
          <h1 className="mt-3 text-4xl font-black tracking-tight text-slate-950">{copy.title}</h1>
          <p className="mt-4 max-w-xl text-base leading-8 text-slate-600">{copy.description}</p>
        </div>
        <Card className="bg-slate-950 text-white">
          <p className="text-xs uppercase tracking-[0.24em] text-slate-300">Current development credentials</p>
          <p className="mt-3 text-lg font-bold">{copy.sample}</p>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            This frontend is already structured for institution-issued credentials and future forced-reset or OTP flows.
          </p>
        </Card>
      </div>

      <Card className="mx-auto w-full max-w-xl bg-white p-7 sm:p-8">
        <form className="space-y-5" onSubmit={handleSubmit}>
          <div>
            <label className="mb-2 block text-sm font-semibold text-slate-700">Username</label>
            <div className="flex items-center gap-3 rounded-2xl border border-slate-200 px-4 py-3">
              <UserRound className="h-4 w-4 text-slate-400" />
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="Enter institution-issued username"
                className="w-full border-0 bg-transparent outline-none"
              />
            </div>
          </div>
          <div>
            <label className="mb-2 block text-sm font-semibold text-slate-700">Password</label>
            <div className="flex items-center gap-3 rounded-2xl border border-slate-200 px-4 py-3">
              <LockKeyhole className="h-4 w-4 text-slate-400" />
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Enter password"
                className="w-full border-0 bg-transparent outline-none"
              />
            </div>
          </div>

          {error ? (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
          ) : null}

          <Button className="w-full justify-center" disabled={busy}>
            {busy ? "Signing in..." : "Continue"}
          </Button>
        </form>
      </Card>
    </div>
  );
}

function resolveDashboardRoute(role: string) {
  if (role === "student") {
    return "/app/student/dashboard";
  }
  if (role === "counsellor") {
    return "/app/counsellor/dashboard";
  }
  return "/app/admin/dashboard";
}
