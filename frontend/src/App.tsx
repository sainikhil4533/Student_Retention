import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { lazy, Suspense } from "react";

import { AppShell, PublicLayout } from "./components/layout";
import { useAuth } from "./lib/auth";

// Lazy load all page components to reduce initial bundle size
const AdminDashboardPage = lazy(() => import("./pages/admin").then(m => ({ default: m.AdminDashboardPage })));
const AdminImportsPage = lazy(() => import("./pages/admin").then(m => ({ default: m.AdminImportsPage })));
const AdminOperationsPage = lazy(() => import("./pages/admin").then(m => ({ default: m.AdminOperationsPage })));
const AdminReportsPage = lazy(() => import("./pages/admin").then(m => ({ default: m.AdminReportsPage })));
const AdminStudentsPage = lazy(() => import("./pages/admin").then(m => ({ default: m.AdminStudentsPage })));
const RoleChatPage = lazy(() => import("./pages/chat").then(m => ({ default: m.RoleChatPage })));
const CounsellorCasesPage = lazy(() => import("./pages/counsellor").then(m => ({ default: m.CounsellorCasesPage })));
const CounsellorDashboardPage = lazy(() => import("./pages/counsellor").then(m => ({ default: m.CounsellorDashboardPage })));
const CounsellorReportsPage = lazy(() => import("./pages/counsellor").then(m => ({ default: m.CounsellorReportsPage })));
const HomePage = lazy(() => import("./pages/home").then(m => ({ default: m.HomePage })));
const ResetPasswordPage = lazy(() => import("./pages/login").then(m => ({ default: m.ResetPasswordPage })));
const RoleLoginPage = lazy(() => import("./pages/login").then(m => ({ default: m.RoleLoginPage })));
const StudentDashboardPage = lazy(() => import("./pages/student").then(m => ({ default: m.StudentDashboardPage })));
const StudentJourneyPage = lazy(() => import("./pages/student").then(m => ({ default: m.StudentJourneyPage })));
const StudentReportsPage = lazy(() => import("./pages/student").then(m => ({ default: m.StudentReportsPage })));

// Loading fallback component
function PageLoader() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-white">
      <div className="text-center">
        <div className="inline-flex h-12 w-12 animate-spin rounded-full border-4 border-slate-300 border-t-blue-600"></div>
        <p className="mt-4 text-sm text-slate-600">Loading page...</p>
      </div>
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route path="/" element={<Suspense fallback={<PageLoader />}><HomePage /></Suspense>} />
        <Route path="/login/:role" element={<Suspense fallback={<PageLoader />}><RoleLoginPage /></Suspense>} />
      </Route>

      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route path="reset-password" element={<Suspense fallback={<PageLoader />}><ResetPasswordPage /></Suspense>} />
        <Route path="student/dashboard" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["student"]}><StudentDashboardPage /></RoleGuard></Suspense>} />
        <Route path="student/chat" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["student"]}><RoleChatPage /></RoleGuard></Suspense>} />
        <Route path="student/journey" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["student"]}><StudentJourneyPage /></RoleGuard></Suspense>} />
        <Route path="student/reports" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["student"]}><StudentReportsPage /></RoleGuard></Suspense>} />
        <Route path="counsellor/dashboard" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["counsellor"]}><CounsellorDashboardPage /></RoleGuard></Suspense>} />
        <Route path="counsellor/cases" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["counsellor"]}><CounsellorCasesPage /></RoleGuard></Suspense>} />
        <Route path="counsellor/chat" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["counsellor"]}><RoleChatPage /></RoleGuard></Suspense>} />
        <Route path="counsellor/reports" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["counsellor"]}><CounsellorReportsPage /></RoleGuard></Suspense>} />
        <Route path="admin/dashboard" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["admin", "system"]}><AdminDashboardPage /></RoleGuard></Suspense>} />
        <Route path="admin/chat" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["admin", "system"]}><RoleChatPage /></RoleGuard></Suspense>} />
        <Route path="admin/reports" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["admin", "system"]}><AdminReportsPage /></RoleGuard></Suspense>} />
        <Route path="admin/operations" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["admin", "system"]}><AdminOperationsPage /></RoleGuard></Suspense>} />
        <Route path="admin/imports" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["admin", "system"]}><AdminImportsPage /></RoleGuard></Suspense>} />
        <Route path="admin/students" element={<Suspense fallback={<PageLoader />}><RoleGuard allowed={["admin", "system"]}><AdminStudentsPage /></RoleGuard></Suspense>} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function ProtectedRoute({ children }: { children: JSX.Element }) {
  const { isAuthenticated, auth } = useAuth();
  const location = useLocation();
  if (!isAuthenticated || !auth) {
    return <Navigate to="/login/student" replace />;
  }
  if (auth.passwordResetRequired && location.pathname !== "/app/reset-password") {
    return <Navigate to="/app/reset-password" replace />;
  }
  return children;
}

function RoleGuard({
  allowed,
  children,
}: {
  allowed: string[];
  children: JSX.Element;
}) {
  const { auth } = useAuth();
  if (!auth) {
    return <Navigate to="/login/student" replace />;
  }
  if (auth.passwordResetRequired) {
    return <Navigate to="/app/reset-password" replace />;
  }
  if (!allowed.includes(auth.role)) {
    return <Navigate to={defaultRoute(auth.role)} replace />;
  }
  return children;
}

function defaultRoute(role: string) {
  if (role === "student") {
    return "/app/student/dashboard";
  }
  if (role === "counsellor") {
    return "/app/counsellor/dashboard";
  }
  return "/app/admin/dashboard";
}
