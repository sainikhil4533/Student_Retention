import { BarChart3, Bot, Compass, LayoutDashboard, ListTodo, LogOut, Menu, Upload } from "lucide-react";
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
      <div className="hero-grid absolute inset-0 bg-hero-grid opacity-60" />
      <header className="relative z-40 mx-auto flex max-w-7xl items-center justify-between px-4 py-6 sm:px-6 lg:px-8">
        <BrandLockup />
        <div className="relative">
          <Button onClick={() => setOpen((value) => !value)}>Sign in</Button>
          {open ? (
            <div className="absolute right-0 z-50 mt-3 w-56 rounded-3xl border border-slate-200 bg-white p-2 shadow-lift">
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

  return (
    <div className="min-h-screen">
      {mobileOpen ? <button type="button" className="fixed inset-0 z-20 bg-slate-950/25 lg:hidden" onClick={() => setMobileOpen(false)} aria-label="Close navigation" /> : null}
      <div className="mx-auto flex min-h-screen max-w-[1800px]">
        <aside
          className={`fixed inset-y-0 left-0 z-30 flex w-72 flex-col border-r border-slate-200 bg-white/85 p-5 shadow-soft transition lg:static lg:translate-x-0 ${
            mobileOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <BrandLockup compact />
          <div className="mt-10 rounded-[28px] bg-slate-950 p-5 text-white">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-300">Signed in</p>
            <p className="mt-2 text-lg font-bold">{auth?.displayName ?? "User"}</p>
            <p className="text-sm capitalize text-slate-300">{auth?.role ?? "role"}</p>
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
                      ? "bg-indigo-50 text-indigo-700"
                      : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
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

        <div className="flex min-h-screen min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 border-b border-white/60 bg-slate-50/85 backdrop-blur">
            <div className="flex items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
              <div className="flex items-center gap-3">
                <Button variant="secondary" className="lg:hidden" onClick={() => setMobileOpen((value) => !value)}>
                  <Menu className="h-4 w-4" />
                </Button>
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Workspace</p>
                  <h1 className="text-xl font-extrabold text-slate-950">
                  {location.pathname.includes("reports")
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
                        : "Dashboard"}
                  </h1>
                </div>
              </div>
              <div className="hidden items-center gap-3 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm text-slate-500 md:flex">
                <Bot className="h-4 w-4 text-indigo-600" />
                Copilot stays available across the full app.
              </div>
            </div>
          </header>

          <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
            <Outlet />
          </main>
        </div>
      </div>
      {!location.pathname.includes("/chat") ? <ChatbotDock /> : null}
    </div>
  );
}
