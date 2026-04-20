import {
  ArrowRight,
  Bot,
  Building2,
  ChartColumnBig,
  CheckCircle2,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
  Users2,
} from "lucide-react";
import { NavLink } from "react-router-dom";

import { CampusCopilotMark } from "../components/brand";
import { Button, Card, SectionTitle, StatCard } from "../components/ui";

const roleCards = [
  {
    title: "Students",
    description: "A focused academic workspace with journey guidance, risk clarity, and role-safe copilot support.",
    href: "/login/student",
  },
  {
    title: "Counsellors",
    description: "A case-driven workspace for follow-ups, intervention tracking, and scoped student support decisions.",
    href: "/login/counsellor",
  },
  {
    title: "Admins",
    description: "An institutional operations surface for imports, analytics, executive reporting, and platform oversight.",
    href: "/login/admin",
  },
];

export function HomePage() {
  return (
    <div className="pb-24">
      <section className="mx-auto grid max-w-7xl gap-10 px-4 pt-8 sm:px-6 lg:grid-cols-[1.05fr_0.95fr] lg:px-8 lg:pt-12">
        <div className="space-y-8 animate-rise">
          <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-[13px] font-semibold text-slate-600 shadow-sm">
            <Sparkles className="h-3.5 w-3.5 text-blue-600" />
            Institution-first retention intelligence
          </div>

          <div className="space-y-5">
            <h1 className="max-w-4xl text-5xl tracking-tight text-slate-900 sm:text-6xl font-bold leading-[1.1]">
              Institutional retention intelligence that feels modern, stays professional, and works like a real campus system.
            </h1>
            <p className="max-w-2xl text-lg leading-8 text-slate-600">
              RetentionOS brings student progress, counsellor action, institutional reporting, and grounded copilot support into one closed-campus workflow. It is built for institutional use, not public self-signup.
            </p>
          </div>

          <div className="flex flex-wrap gap-4 mt-8">
            <NavLink to="/login/admin">
              <Button className="px-6 py-2.5 text-sm">
                Start with admin access
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </NavLink>
            <NavLink
              to="/login/student"
              className="inline-flex items-center rounded-lg border border-slate-200 bg-white px-6 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition-colors hover:border-slate-300 hover:bg-slate-50"
            >
              View student experience
            </NavLink>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard label="Role-aware access" value="3" note="Student, counsellor, and admin sign-in paths." />
            <StatCard label="Grounded copilot" value="CB22" note="Deterministic baseline with safe semantic fallback." accent="teal" />
            <StatCard label="Import-safe workflow" value="Dry run" note="Admin validation before institutional persistence." accent="gold" />
          </div>
        </div>

        <Card className="bg-slate-50 border-slate-100 p-8 shadow-none flex flex-col justify-between">
          <div className="relative flex items-start justify-between">
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wider text-blue-600">Closed-campus operating model</p>
              <h2 className="mt-3 text-2xl font-semibold tracking-tight text-slate-900">One platform. Three roles.</h2>
              <p className="mt-3 max-w-xl text-sm leading-6 text-slate-500">
                The homepage stays concise and trustworthy. The real product begins only after authenticated sign-in, where experiences split cleanly.
              </p>
            </div>
            <CampusCopilotMark className="animate-floaty" />
          </div>

          <div className="relative mt-10 grid gap-4 sm:grid-cols-3">
            {[
              {
                title: "Student",
                detail: "Journey guidance, risk clarity, and formal motivation.",
              },
              {
                title: "Counsellor",
                detail: "Priority queue, case workbench, and intervention workflow.",
              },
              {
                title: "Admin",
                detail: "Institution analytics, imports, and operational visibility.",
              },
            ].map((item) => (
              <div key={item.title} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">{item.title}</p>
                <p className="mt-2 text-sm leading-6 text-slate-700">{item.detail}</p>
              </div>
            ))}
          </div>

          <div className="mt-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div className="grid gap-4 sm:grid-cols-3">
              {[
                ["Student clarity", "Motivating journey surfaces and formal timeline guidance."],
                ["Counsellor flow", "Priority queues and workbench actions without clutter."],
                ["Admin control", "Uploads, reports, and operations stay separate."],
              ].map(([title, text]) => (
                <div key={title}>
                  <p className="text-sm font-semibold text-slate-900">{title}</p>
                  <p className="mt-2 text-[13px] leading-5 text-slate-500">{text}</p>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </section>

      <section className="mx-auto mt-16 max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid gap-5 lg:grid-cols-4">
          {[
            {
              icon: LockKeyhole,
              title: "No public self-signup",
              description: "Institution-controlled access keeps identity, scope, and privacy aligned with real campus operation.",
            },
            {
              icon: Users2,
              title: "Role-specific dashboards",
              description: "Each role lands inside a workspace built around its actual decisions instead of one generic panel.",
            },
            {
              icon: ChartColumnBig,
              title: "Reports with structure",
              description: "Dashboards stay summary-first while deeper analysis belongs to reports and operations pages.",
            },
            {
              icon: Bot,
              title: "Grounded copilot",
              description: "The assistant feels natural, but answers stay tied to backend facts, route scope, and institutional rules.",
            },
          ].map(({ icon: Icon, title, description }) => (
            <Card key={title} className="h-full bg-white/92">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-slate-950 to-indigo-900 text-white shadow-soft">
                <Icon className="h-5 w-5" />
              </div>
              <h3 className="mt-5 text-lg font-extrabold text-slate-950">{title}</h3>
              <p className="mt-2 text-sm leading-7 text-slate-600">{description}</p>
            </Card>
          ))}
        </div>
      </section>

      <section className="mx-auto mt-20 max-w-7xl px-4 sm:px-6 lg:px-8">
        <SectionTitle
          eyebrow="Entry flows"
          title="Three role paths. One consistent institutional product."
          description="The public homepage explains the product, but the actual system behavior begins only after role-aware sign-in."
        />
        <div className="mt-8 grid gap-5 lg:grid-cols-3">
          {roleCards.map((card) => (
            <NavLink key={card.title} to={card.href}>
              <Card className="h-full border-slate-100 bg-white transition hover:-translate-y-1 hover:shadow-lift">
                <p className="text-sm font-semibold uppercase tracking-[0.22em] text-indigo-600">{card.title}</p>
                <h3 className="mt-3 text-2xl font-extrabold text-slate-950">{card.title} module</h3>
                <p className="mt-3 text-sm leading-7 text-slate-600">{card.description}</p>
                <div className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-slate-900">
                  Sign in
                  <ArrowRight className="h-4 w-4" />
                </div>
              </Card>
            </NavLink>
          ))}
        </div>
      </section>

      <section className="mx-auto mt-20 max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
          <Card className="home-section-slate border-white/70">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Operational design choice</p>
            <h3 className="mt-3 text-3xl font-extrabold tracking-tight text-slate-950">
              The homepage builds trust. The dashboards handle the real work.
            </h3>
            <p className="mt-4 max-w-2xl text-sm leading-7 text-slate-600">
              We intentionally stopped the public page from becoming a fake analytics dashboard. Public visitors should understand the platform model quickly, then sign in into the real role-specific experience.
            </p>
            <div className="mt-8 grid gap-4 sm:grid-cols-2">
              {[
                ["Shorter scroll", "The public page stays concise so the product feels confident instead of over-explained."],
                ["Better contrast", "Dark and light sections now alternate more clearly, so the page feels designed instead of washed out."],
                ["Role-first entry", "Each module gets its own path before any protected functionality appears."],
                ["Institution tone", "The page avoids startup-style AI noise and keeps a campus-trust posture."],
              ].map(([title, text]) => (
                <div key={title} className="rounded-3xl border border-white/80 bg-white/86 p-5 shadow-soft">
                  <p className="text-base font-bold text-slate-950">{title}</p>
                  <p className="mt-2 text-sm leading-7 text-slate-600">{text}</p>
                </div>
              ))}
            </div>
          </Card>

          <Card className="home-section-soft bg-white/95">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Why institutions use it</p>
            <h3 className="mt-3 text-3xl font-extrabold tracking-tight text-slate-950">
              It behaves like a structured campus platform, not like a generic public chatbot site.
            </h3>
            <div className="mt-8 space-y-4">
              {[
                "Dashboard-first landing screens keep the first experience calm and usable.",
                "Reports and operations live in deeper routes so analytics never overload the first screen.",
                "Chatbot access remains role-aware and grounded to backend data instead of open-ended guessing.",
                "Admin upload stays operationally separate from the public-facing and student-facing experience.",
              ].map((point) => (
                <div key={point} className="flex items-start gap-3 rounded-2xl border border-slate-200 bg-white/90 px-4 py-4">
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-teal-600" />
                  <p className="text-sm leading-7 text-slate-700">{point}</p>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </section>

      <section className="mx-auto mt-20 max-w-7xl px-4 pb-4 sm:px-6 lg:px-8">
        <Card className="home-section-dark overflow-hidden border-white/10 px-8 py-8 text-white shadow-lift">
          <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Ready to enter the platform</p>
              <h3 className="mt-3 text-3xl font-extrabold tracking-tight">
                Sign in and move directly into the role-specific workspace.
              </h3>
              <p className="mt-4 max-w-2xl text-sm leading-7 text-slate-300">
                Students receive a guided progress view, counsellors receive a case-oriented workspace, and admins receive institutional controls with reporting and import access.
              </p>
            </div>
            <div className="flex flex-wrap gap-3 lg:justify-end">
              <NavLink to="/login/admin">
                <Button className="bg-white text-slate-950 hover:bg-slate-100">Admin sign in</Button>
              </NavLink>
              <NavLink to="/login/student">
                <Button variant="secondary" className="border-white/20 bg-white/10 text-white hover:bg-white/15">
                  Student sign in
                </Button>
              </NavLink>
              <NavLink to="/login/counsellor">
                <Button variant="secondary" className="border-white/20 bg-white/10 text-white hover:bg-white/15">
                  Counsellor sign in
                </Button>
              </NavLink>
            </div>
          </div>
        </Card>
      </section>

      <section className="mx-auto mt-6 max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid gap-5 md:grid-cols-3">
          {[
            {
              icon: ShieldCheck,
              title: "Role-safe by design",
              description: "Each login path lands inside a dashboard built around that role’s actual responsibilities.",
            },
            {
              icon: Building2,
              title: "Institution-ready flow",
              description: "The homepage stays public and informative while the real operational system begins after sign-in.",
            },
            {
              icon: Bot,
              title: "Copilot that stays grounded",
              description: "The assistant feels familiar, but answer logic stays tied to backend data, scope, and institutional rules.",
            },
          ].map(({ icon: Icon, title, description }) => (
            <Card key={title} className="bg-white/92">
              <Icon className="h-8 w-8 text-indigo-600" />
              <h3 className="mt-5 text-xl font-bold text-slate-950">{title}</h3>
              <p className="mt-2 text-sm leading-7 text-slate-600">{description}</p>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
