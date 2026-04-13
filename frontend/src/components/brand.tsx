import clsx from "clsx";

export function CampusCopilotMark({ className }: { className?: string }) {
  return (
    <div
      className={clsx(
        "copilot-badge relative flex h-12 w-12 items-center justify-center rounded-[18px] border border-white/70 bg-gradient-to-br from-indigo-500 via-indigo-600 to-teal-500 text-white shadow-soft",
        className,
      )}
    >
      <span className="mt-4 text-[10px] font-black tracking-[0.24em]">AI</span>
    </div>
  );
}

export function BrandLockup({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <CampusCopilotMark className={compact ? "h-10 w-10 rounded-2xl" : ""} />
      <div>
        <p className="font-extrabold tracking-tight text-slate-950">{compact ? "RetentionOS" : "RetentionOS Copilot"}</p>
        <p className="text-xs tracking-[0.2em] text-slate-500 uppercase">
          {compact ? "Institution Suite" : "Institutional Student Success Platform"}
        </p>
      </div>
    </div>
  );
}
