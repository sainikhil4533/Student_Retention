import { FormEvent, useMemo, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import {
  Building2,
  KeyRound,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
  UserRound,
} from "lucide-react";

import { BrandLockup, CampusCopilotMark } from "../components/brand";
import { Button, Card } from "../components/ui";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

const roleCopy = {
  student: {
    title: "Student sign-in",
    subtitle: "Institution-issued student access",
    description:
      "Students enter with institution-issued credentials, view their own dashboard, and can update temporary passwords after first access.",
    usernameHint: "stu001",
    passwordHint: "Welcome@123 (temporary)",
    helper:
      "Use the imported institution account given to you. Newly provisioned student accounts usually start with a temporary password and must reset it after first login. Public self-sign-up is intentionally disabled.",
    surface:
      "Journey view, self-risk dashboard, reports, and role-safe copilot guidance become available after login.",
  },
  counsellor: {
    title: "Counsellor sign-in",
    subtitle: "Scoped operational access",
    description:
      "Counsellor accounts open a case-driven workspace with student scope, intervention trails, and priority handling.",
    usernameHint: "asha.counsellor",
    passwordHint: "Welcome@123 (temporary)",
    helper:
      "Counsellor access is institution-controlled, tied to imported cohort ownership where available, and newly provisioned counsellor accounts also start with a temporary password.",
    surface:
      "Priority queue, case workbench, interventions workspace, reports, and scoped copilot support.",
  },
  admin: {
    title: "Admin sign-in",
    subtitle: "Institution command surface",
    description:
      "Admin accounts manage uploads, reports, operations, and institution-wide retention visibility from one controlled workspace.",
    usernameHint: "admin.retention",
    passwordHint: "Admin@123",
    helper: "Admins are the only role with upload and operational controls. This route is intentionally stricter.",
    surface:
      "Institution analytics, import flow, exports, operational summaries, and admin-scoped copilot support.",
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
    if (auth.passwordResetRequired) {
      return <Navigate to="/app/reset-password" replace />;
    }
    return <Navigate to={resolveDashboardRoute(auth.role)} replace />;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await login({ username, password });
      navigate(session.passwordResetRequired ? "/app/reset-password" : resolveDashboardRoute(session.role), {
        replace: true,
      });
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
    <div className="mx-auto grid min-h-[calc(100vh-110px)] max-w-7xl items-center gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[1.02fr_0.98fr] lg:px-8 lg:py-12">
      <div className="space-y-6">
        <div className="inline-flex items-center gap-2 rounded-full border border-white/70 bg-white/80 px-4 py-2 text-sm font-semibold text-indigo-700 shadow-soft">
          <Sparkles className="h-4 w-4" />
          {copy.subtitle}
        </div>
        <div className="space-y-4">
          <h1 className="max-w-2xl text-4xl font-black tracking-tight text-slate-950 sm:text-5xl">{copy.title}</h1>
          <p className="max-w-xl text-base leading-8 text-slate-600">{copy.description}</p>
        </div>

        <Card className="home-section-dark overflow-hidden border-white/10 p-6 text-white shadow-lift">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-slate-300">What opens after sign-in</p>
              <p className="mt-3 text-lg font-bold leading-8">{copy.surface}</p>
            </div>
            <CampusCopilotMark className="shrink-0" />
          </div>
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            <div className="rounded-3xl border border-white/10 bg-white/10 p-4 backdrop-blur-sm">
              <p className="text-xs uppercase tracking-[0.18em] text-indigo-200">Starter username</p>
              <p className="mt-3 text-sm font-semibold text-white">{copy.usernameHint}</p>
            </div>
            <div className="rounded-3xl border border-white/10 bg-white/10 p-4 backdrop-blur-sm">
              <p className="text-xs uppercase tracking-[0.18em] text-indigo-200">Starter password</p>
              <p className="mt-3 text-sm font-semibold text-white">{copy.passwordHint}</p>
            </div>
          </div>
          <div className="mt-5 flex items-start gap-3 rounded-3xl border border-white/10 bg-white/10 px-4 py-4 backdrop-blur-sm">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-teal-300" />
            <p className="text-sm leading-7 text-slate-100">{copy.helper}</p>
          </div>
        </Card>
      </div>

      <Card className="mx-auto w-full max-w-lg p-8 shadow-sm">
        <div className="mb-8">
          <h2 className="text-2xl font-semibold tracking-tight text-slate-900">Sign in to RetentionOS</h2>
          <p className="mt-2 text-sm text-slate-500">
            Use your institution-issued credentials.
          </p>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <label className="mb-1.5 block text-[13px] font-medium text-slate-700">Username</label>
            <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 outline-none transition-all focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-500/20">
              <UserRound className="h-4 w-4 text-slate-400" />
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="Enter institution-issued username"
                className="w-full border-0 bg-transparent text-slate-900 outline-none placeholder:text-slate-400"
              />
            </div>
            <p className="mt-2 text-xs leading-6 text-slate-500">Examples: registration number style login, staff login ID, or institution-managed account name.</p>
          </div>

          <div>
            <label className="mb-1.5 block text-[13px] font-medium text-slate-700">Password</label>
            <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 outline-none transition-all focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-500/20">
              <LockKeyhole className="h-4 w-4 text-slate-400" />
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Enter password"
                className="w-full border-0 bg-transparent text-slate-900 outline-none placeholder:text-slate-400"
              />
            </div>
            <div className="mt-2 flex items-start gap-2 text-xs leading-6 text-slate-500">
              <Building2 className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
              Sign-in is limited to institution-provisioned accounts only. There is no public registration flow on this product.
            </div>
          </div>

          {error ? (
            <div className="rounded-3xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-6 text-rose-700">
              {error}
            </div>
          ) : null}

          <Button className="w-full justify-center rounded-[24px] py-3.5" disabled={busy}>
            {busy ? "Signing in..." : "Continue to workspace"}
          </Button>
        </form>
      </Card>
    </div>
  );
}

export function ResetPasswordPage() {
  const navigate = useNavigate();
  const { auth, resetPassword, logout } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  if (!auth) {
    return <Navigate to="/login/student" replace />;
  }
  if (!auth.passwordResetRequired) {
    return <Navigate to={resolveDashboardRoute(auth.role)} replace />;
  }
  const authenticatedRole = auth.role;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    if (newPassword.length < 8) {
      setError("Choose a password with at least 8 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("New password and confirmation do not match.");
      return;
    }
    setBusy(true);
    try {
      await resetPassword({ currentPassword, newPassword });
      setSuccess("Password updated. Redirecting to your workspace...");
      navigate(resolveDashboardRoute(authenticatedRole), { replace: true });
    } catch (unknownError) {
      const detail =
        unknownError instanceof ApiError
          ? unknownError.detail
          : unknownError instanceof Error
            ? unknownError.message
            : "Unable to reset password.";
      setError(detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto grid min-h-[calc(100vh-110px)] max-w-6xl items-center gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[0.95fr_1.05fr] lg:px-8 lg:py-12">
      <Card className="home-section-dark border-white/10 p-7 text-white shadow-lift">
        <p className="text-xs uppercase tracking-[0.22em] text-slate-300">First-login security step</p>
        <h1 className="mt-3 text-4xl font-black tracking-tight">Update the temporary password before entering the full workspace.</h1>
        <p className="mt-4 text-sm leading-7 text-slate-300">
          This is how the system supports institution-issued starter credentials without keeping users on weak, shared, or temporary passwords for long.
        </p>
        <div className="mt-8 space-y-3">
          {[
            "The current password proves that the institution handed the account to the right person.",
            "The new password becomes your private credential for future login.",
            "Later, this same pattern can be extended to OTP, SSO, or admin-triggered reset flows.",
          ].map((point) => (
            <div key={point} className="rounded-3xl border border-white/10 bg-white/10 px-4 py-4 text-sm leading-7 text-slate-100 backdrop-blur-sm">
              {point}
            </div>
          ))}
        </div>
        <Button
          variant="secondary"
          className="mt-6 border-white/20 bg-white/10 text-white hover:bg-white/15"
          onClick={() => {
            logout();
            navigate("/");
          }}
        >
          Sign out instead
        </Button>
      </Card>

      <Card className="mx-auto w-full max-w-lg p-8 shadow-sm">
        <div className="mb-8">
          <div className="inline-flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wider text-blue-700">
            <KeyRound className="h-3.5 w-3.5" />
            Update Required
          </div>
          <h2 className="mt-4 text-2xl font-semibold tracking-tight text-slate-900">Set new password</h2>
          <p className="mt-2 text-sm text-slate-500">
            Signed in as <span className="font-semibold text-slate-900">{auth.username}</span>.
          </p>
        </div>
        <form className="space-y-5" onSubmit={handleSubmit}>
          <PasswordField
            label="Current temporary password"
            value={currentPassword}
            onChange={setCurrentPassword}
            placeholder="Enter current password"
          />
          <PasswordField
            label="New password"
            value={newPassword}
            onChange={setNewPassword}
            placeholder="Choose a new password"
          />
          <PasswordField
            label="Confirm new password"
            value={confirmPassword}
            onChange={setConfirmPassword}
            placeholder="Re-enter new password"
          />

          {error ? (
            <div className="rounded-3xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-6 text-rose-700">
              {error}
            </div>
          ) : null}
          {success ? (
            <div className="rounded-3xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm leading-6 text-emerald-700">
              {success}
            </div>
          ) : null}

          <Button className="w-full justify-center rounded-[24px] py-3.5" disabled={busy}>
            {busy ? "Updating..." : "Update password"}
          </Button>
        </form>
      </Card>
    </div>
  );
}

function PasswordField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-[13px] font-medium text-slate-700">{label}</label>
      <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 outline-none transition-all focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-500/20">
        <LockKeyhole className="h-4 w-4 text-slate-400" />
        <input
          type="password"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          className="w-full border-0 bg-transparent text-slate-900 outline-none placeholder:text-slate-400"
        />
      </div>
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
