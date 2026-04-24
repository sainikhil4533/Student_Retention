import { BarChart3, Bot, Compass, LayoutDashboard, ListTodo, LogOut, Menu, Upload, Users } from "lucide-react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useMemo, useState } from "react";

import { BrandLockup } from "./brand";
import { ChatbotDock } from "./chatbot";
import { Button } from "./ui";
import { useAuth } from "../lib/auth";

type NavItem = {
  label: string;
  to: string;
  icon: typeof Compass;
};

function roleNav(role: string): NavItem[] {
  if (role === "student") {
    return [
      { label: "Dashboard", to: "/app/student/dashboard", icon: LayoutDashboard },
      { label: "Journey", to: "/app/student/journey", icon: Compass },
      { label: "Reports", to: "/app/student/reports", icon: BarChart3 },
      { label: "Copilot", to: "/app/student/chat", icon: Bot },
    ];
  }
  if (role === "counsellor") {
    return [
      { label: "Dashboard", to: "/app/counsellor/dashboard", icon: LayoutDashboard },
      { label: "Cases", to: "/app/counsellor/cases", icon: ListTodo },
      { label: "Reports", to: "/app/counsellor/reports", icon: BarChart3 },
      { label: "Copilot", to: "/app/counsellor/chat", icon: Bot },
    ];
  }
  return [
    { label: "Dashboard", to: "/app/admin/dashboard", icon: LayoutDashboard },
    { label: "Students", to: "/app/admin/students", icon: Users },
    { label: "Reports", to: "/app/admin/reports", icon: BarChart3 },
    { label: "Operations", to: "/app/admin/operations", icon: Compass },
    { label: "Imports", to: "/app/admin/imports", icon: Upload },
    { label: "Copilot", to: "/app/admin/chat", icon: Bot },
  ];
}

export function PublicLayout() {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative min-h-screen overflow-hidden">
      <div className="hero-grid hero-noise absolute inset-0 opacity-70" />
      <div className="absolute inset-x-0 top-0 h-56 bg-[radial-gradient(circle_at_top,rgba(99,102,241,0.12),transparent_62%)]" />
      <header className="relative z-40 mx-auto flex max-w-7xl items-center justify-between px-4 py-6 sm:px-6 lg:px-8">
        <BrandLockup />
        <div className="relative">
          <Button className="rounded-full px-5 py-3" onClick={() => setOpen((value) => !value)}>Sign in</Button>
          {open ? (
            <div className="absolute right-0 z-50 mt-3 w-64 rounded-[28px] border border-white/80 bg-white/95 p-2 shadow-lift backdrop-blur">
              {[
                ["Student", "/login/student"],
                ["Counsellor", "/login/counsellor"],
                ["Admin", "/login/admin"],
              ].map(([label, href]) => (
                <NavLink
                  key={label}
                  to={href}
                  onClick={() => setOpen(false)}
                  className="block rounded-2xl px-4 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
                >
                  {label}
                </NavLink>
              ))}
            </div>
          ) : null}
        </div>
      </header>
      <main className="relative z-10">
        <Outlet />
      </main>
    </div>
  );
}

export function AppShell() {
  const { auth, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);

  const navItems = useMemo(() => roleNav(auth?.role ?? "student"), [auth?.role]);
  const isResetRoute = location.pathname === "/app/reset-password";
  const workspaceTitle = isResetRoute
    ? "Password Reset"
    : location.pathname.includes("students")
      ? "Student Directory"
    : location.pathname.includes("reports")
      ? "Reports"
      : location.pathname.includes("chat")
        ? "Copilot"
      : location.pathname.includes("imports")
        ? "Data Imports"
      : location.pathname.includes("operations")
        ? "Operations"
      : location.pathname.includes("journey")
        ? "Journey"
      : location.pathname.includes("cases")
        ? "Cases"
      : "Dashboard";

  return (
    <div className="workspace-shell min-h-screen">
      {mobileOpen && !isResetRoute ? <button type="button" className="fixed inset-0 z-20 bg-slate-950/25 lg:hidden" onClick={() => setMobileOpen(false)} aria-label="Close navigation" /> : null}
      <div className="mx-auto flex min-h-screen max-w-[1800px]">
        {!isResetRoute ? (
          <aside
            className={`sidebar-panel fixed inset-y-0 left-0 z-30 flex w-72 flex-col border-r border-white/70 p-5 shadow-soft transition lg:static lg:translate-x-0 ${
              mobileOpen ? "translate-x-0" : "-translate-x-full"
            }`}
          >
            <BrandLockup compact />
            <div className="mt-10 rounded-[28px] bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 p-5 text-white shadow-lift">
              <p className="text-xs uppercase tracking-[0.22em] text-slate-300">Signed in</p>
              <p className="mt-2 text-lg font-bold">{auth?.displayName ?? "User"}</p>
              <div className="mt-3 inline-flex rounded-full border border-white/10 bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-slate-200">
                {auth?.role ?? "role"}
              </div>
            </div>

            <nav className="mt-8 space-y-2">
              {navItems.map(({ label, to, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  onClick={() => setMobileOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-semibold transition ${
                      isActive
                        ? "bg-gradient-to-r from-indigo-50 to-white text-indigo-700 shadow-[0_8px_24px_rgba(79,70,229,0.08)]"
                        : "text-slate-600 hover:bg-white hover:text-slate-900"
                    }`
                  }
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </NavLink>
              ))}
            </nav>

            <div className="mt-auto pt-10">
              <Button
                variant="secondary"
                className="w-full justify-center"
                onClick={() => {
                  logout();
                  navigate("/");
                }}
              >
                <LogOut className="mr-2 h-4 w-4" />
                Sign out
              </Button>
            </div>
          </aside>
        ) : null}

        <div className="flex min-h-screen min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 border-b border-white/60 bg-slate-50/88 backdrop-blur">
            <div className="flex items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
              <div className="flex items-center gap-3">
                {!isResetRoute ? (
                  <Button variant="secondary" className="lg:hidden" onClick={() => setMobileOpen((value) => !value)}>
                    <Menu className="h-4 w-4" />
                  </Button>
                ) : null}
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Workspace</p>
                  <h1 className="text-xl font-extrabold text-slate-950">{workspaceTitle}</h1>
                </div>
              </div>
              <div className="hidden items-center gap-3 rounded-full border border-slate-200 bg-white/90 px-4 py-2 text-sm text-slate-500 shadow-soft md:flex">
                <Bot className="h-4 w-4 text-indigo-600" />
                {isResetRoute ? "Security step before workspace access." : "Copilot stays available across the full app."}
              </div>
            </div>
          </header>

          <main className="workspace-surface flex-1 px-4 py-6 sm:px-6 lg:px-8">
            <Outlet />
          </main>
        </div>
      </div>
      {!isResetRoute && !location.pathname.includes("/chat") ? <ChatbotDock /> : null}
    </div>
  );
}
