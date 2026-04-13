import { PropsWithChildren, ReactNode } from "react";
import clsx from "clsx";

export function Button({
  children,
  className,
  variant = "primary",
  ...props
}: PropsWithChildren<
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: "primary" | "secondary" | "ghost";
  }
>) {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center rounded-2xl px-4 py-2.5 text-sm font-semibold transition duration-200",
        variant === "primary" &&
          "bg-ink text-white shadow-soft hover:-translate-y-0.5 hover:bg-slate-800",
        variant === "secondary" &&
          "border border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50",
        variant === "ghost" && "text-slate-600 hover:bg-slate-100",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function Card({
  children,
  className,
}: PropsWithChildren<{
  className?: string;
}>) {
  return (
    <div className={clsx("glass rounded-[28px] border border-white/70 p-5 shadow-soft", className)}>
      {children}
    </div>
  );
}

export function SectionTitle({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="space-y-1">
        {eyebrow ? <p className="text-xs font-semibold uppercase tracking-[0.22em] text-teal-700">{eyebrow}</p> : null}
        <h2 className="text-2xl font-extrabold tracking-tight text-slate-900">{title}</h2>
        {description ? <p className="max-w-3xl text-sm leading-6 text-slate-600">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function StatCard({
  label,
  value,
  note,
  accent = "indigo",
}: {
  label: string;
  value: string;
  note?: string;
  accent?: "indigo" | "teal" | "gold" | "rose";
}) {
  const accentClass = {
    indigo: "from-indigo-500/15 to-indigo-100/20 text-indigo-700",
    teal: "from-teal-500/15 to-teal-100/20 text-teal-700",
    gold: "from-amber-400/15 to-amber-100/20 text-amber-700",
    rose: "from-rose-400/15 to-rose-100/20 text-rose-700",
  }[accent];

  return (
    <Card className={clsx("bg-gradient-to-br", accentClass)}>
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className="mt-3 text-3xl font-extrabold tracking-tight text-slate-900">{value}</p>
      {note ? <p className="mt-2 text-sm leading-6 text-slate-600">{note}</p> : null}
    </Card>
  );
}

export function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <Card className="border-dashed border-slate-200 bg-white/70 text-center">
      <h3 className="text-lg font-bold text-slate-900">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
    </Card>
  );
}

export function LoadingCard({ label = "Loading" }: { label?: string }) {
  return (
    <Card className="animate-pulse space-y-3">
      <div className="h-4 w-28 rounded-full bg-slate-200" />
      <div className="h-8 w-20 rounded-full bg-slate-200" />
      <div className="h-3 w-full rounded-full bg-slate-200" />
    </Card>
  );
}
