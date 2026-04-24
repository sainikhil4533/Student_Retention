import { CSSProperties, HTMLAttributes, PropsWithChildren, ReactNode } from "react";
import clsx from "clsx";
import { motion } from "framer-motion";

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
    <motion.button
      whileHover={{ y: -1 }}
      whileTap={{ scale: 0.98 }}
      className={clsx(
        "inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-medium transition-colors",
        variant === "primary" &&
        "bg-blue-600 text-white hover:bg-blue-700 shadow-sm",
        variant === "secondary" &&
        "border border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50 shadow-sm",
        variant === "ghost" && "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
        className,
      )}
      {...props}
    >
      {children}
    </motion.button>
  );
}

export function Card({
  children,
  className,
  style,
  ...props
}: PropsWithChildren<
  HTMLAttributes<HTMLDivElement> & {
    className?: string;
    style?: CSSProperties;
  }
>) {
  return (
    <div
      className={clsx("saas-card rounded-xl p-5", className)}
      style={style}
      {...props}
    >
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
    <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
      <div className="space-y-1.5">
        {eyebrow ? <p className="text-[11px] font-bold uppercase tracking-wider text-blue-600">{eyebrow}</p> : null}
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h2>
        {description ? <p className="max-w-2xl text-sm text-slate-500">{description}</p> : null}
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
  accent?: string;
}) {
  const isVeryLong = value.length > 14;
  const isLong = value.length > 8;
  return (
    <Card className="flex flex-col relative overflow-hidden group">
      <div className="flex items-center justify-between gap-3 shadow-none">
        <p className="text-sm font-medium text-slate-500">{label}</p>
        <span className={clsx("rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider", accent === "teal" ? "bg-teal-50 text-teal-600" : accent === "rose" ? "bg-rose-50 text-rose-600" : accent === "gold" ? "bg-amber-50 text-amber-600" : "bg-indigo-50 text-indigo-600")}>
          Live
        </span>
      </div>
      <p className={clsx("mt-3 font-semibold tracking-tight text-slate-900", isVeryLong ? "text-lg leading-tight lg:text-xl" : isLong ? "text-xl leading-snug lg:text-2xl" : "text-3xl")}>{value}</p>
      {note ? <p className="mt-2 text-[13px] text-slate-500 leading-snug">{note}</p> : null}
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
    <Card className="border-dashed flex flex-col items-center justify-center p-8 text-center bg-slate-50/50">
      <h3 className="text-base font-semibold text-slate-900">{title}</h3>
      <p className="mt-1 text-sm text-slate-500 max-w-sm">{description}</p>
    </Card>
  );
}

export function LoadingCard({ label = "Loading" }: { label?: string }) {
  return (
    <Card className="animate-pulse space-y-3">
      <div className="h-4 w-24 rounded bg-slate-200" />
      <div className="h-8 w-16 rounded bg-slate-200" />
      <div className="h-3 w-full rounded bg-slate-100" />
    </Card>
  );
}
