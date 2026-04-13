import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell, PublicLayout } from "./components/layout";
import { useAuth } from "./lib/auth";
import { AdminDashboardPage, AdminImportsPage, AdminOperationsPage, AdminReportsPage } from "./pages/admin";
import { RoleChatPage } from "./pages/chat";
import { CounsellorCasesPage, CounsellorDashboardPage, CounsellorReportsPage } from "./pages/counsellor";
import { HomePage } from "./pages/home";
import { RoleLoginPage } from "./pages/login";
import { StudentDashboardPage, StudentJourneyPage, StudentReportsPage } from "./pages/student";

export function App() {
  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/login/:role" element={<RoleLoginPage />} />
      </Route>

      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route path="student/dashboard" element={<RoleGuard allowed={["student"]}><StudentDashboardPage /></RoleGuard>} />
        <Route path="student/chat" element={<RoleGuard allowed={["student"]}><RoleChatPage /></RoleGuard>} />
        <Route path="student/journey" element={<RoleGuard allowed={["student"]}><StudentJourneyPage /></RoleGuard>} />
        <Route path="student/reports" element={<RoleGuard allowed={["student"]}><StudentReportsPage /></RoleGuard>} />
        <Route path="counsellor/dashboard" element={<RoleGuard allowed={["counsellor"]}><CounsellorDashboardPage /></RoleGuard>} />
        <Route path="counsellor/cases" element={<RoleGuard allowed={["counsellor"]}><CounsellorCasesPage /></RoleGuard>} />
        <Route path="counsellor/chat" element={<RoleGuard allowed={["counsellor"]}><RoleChatPage /></RoleGuard>} />
        <Route path="counsellor/reports" element={<RoleGuard allowed={["counsellor"]}><CounsellorReportsPage /></RoleGuard>} />
        <Route path="admin/dashboard" element={<RoleGuard allowed={["admin", "system"]}><AdminDashboardPage /></RoleGuard>} />
        <Route path="admin/chat" element={<RoleGuard allowed={["admin", "system"]}><RoleChatPage /></RoleGuard>} />
        <Route path="admin/reports" element={<RoleGuard allowed={["admin", "system"]}><AdminReportsPage /></RoleGuard>} />
        <Route path="admin/operations" element={<RoleGuard allowed={["admin", "system"]}><AdminOperationsPage /></RoleGuard>} />
        <Route path="admin/imports" element={<RoleGuard allowed={["admin", "system"]}><AdminImportsPage /></RoleGuard>} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function ProtectedRoute({ children }: { children: JSX.Element }) {
  const { isAuthenticated, auth } = useAuth();
  if (!isAuthenticated || !auth) {
    return <Navigate to="/login/student" replace />;
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
