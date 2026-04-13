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
        <div className="space-y-8">
          <div className="inline-flex items-center gap-2 rounded-full border border-indigo-100 bg-white/90 px-4 py-2 text-sm font-semibold text-indigo-700 shadow-soft">
            <Sparkles className="h-4 w-4" />
            Institution-first retention intelligence with grounded AI
          </div>

          <div className="space-y-6">
            <h1 className="max-w-4xl text-5xl font-black leading-[0.98] tracking-tight text-slate-950 sm:text-6xl xl:text-[4.6rem]">
              Institutional retention intelligence that feels modern, stays professional, and works like a real campus system.
            </h1>
            <p className="max-w-2xl text-lg leading-8 text-slate-600">
              RetentionOS brings student progress, counsellor action, institutional reporting, and grounded copilot support into one closed-campus workflow. It is built for institutional use, not public self-signup.
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <NavLink to="/login/admin">
              <Button>
                Start with admin access
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </NavLink>
            <NavLink
              to="/login/student"
              className="inline-flex items-center rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-soft transition hover:border-slate-300 hover:bg-slate-50"
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

        <Card className="home-section-dark relative overflow-hidden border-white/10 p-8 text-white shadow-lift">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(99,102,241,0.35),transparent_28%),radial-gradient(circle_at_bottom_left,rgba(20,184,166,0.22),transparent_26%)]" />
          <div className="relative flex items-start justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-slate-300">Closed-campus operating model</p>
              <h2 className="mt-3 text-3xl font-extrabold leading-tight">One platform. Three roles. One institutional source of truth.</h2>
              <p className="mt-4 max-w-xl text-sm leading-7 text-slate-300">
                The homepage stays concise and trustworthy. The real product begins only after authenticated sign-in, where student, counsellor, and admin experiences split cleanly.
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
              <div key={item.title} className="rounded-3xl border border-white/10 bg-white/10 p-4 backdrop-blur-sm">
                <p className="text-xs uppercase tracking-[0.18em] text-indigo-200">{item.title}</p>
                <p className="mt-3 text-sm leading-6 text-slate-100">{item.detail}</p>
              </div>
            ))}
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
        <div className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
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

          <Card className="home-section-dark border-white/10 text-white">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Homepage design decision</p>
            <h3 className="mt-3 text-3xl font-extrabold tracking-tight text-white">
              Attractive, but still serious enough for an academic institution.
            </h3>
            <div className="mt-8 grid gap-4 sm:grid-cols-2">
              {[
                {
                  title: "Formal visual tone",
                  text: "We keep the surface premium and calm instead of using loud startup-style hero noise.",
                },
                {
                  title: "Shorter scrolling path",
                  text: "The homepage should explain the system, not become a long analytics page before login.",
                },
                {
                  title: "Role clarity",
                  text: "Students, counsellors, and admins should understand their route immediately without generic copy blocks.",
                },
                {
                  title: "Professional CTA flow",
                  text: "Sign-in stays the primary action because this is an institution-owned workflow, not a public consumer app.",
                },
              ].map((item) => (
                <div key={item.title} className="rounded-3xl border border-white/10 bg-white/10 p-5 backdrop-blur-sm">
                  <p className="text-base font-bold text-white">{item.title}</p>
                  <p className="mt-2 text-sm leading-7 text-slate-200">{item.text}</p>
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
