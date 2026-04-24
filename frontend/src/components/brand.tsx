import clsx from "clsx";

/** Sparkle-gradient AI logo mark — used in dock FAB and chat header */
export function CampusCopilotMark({ className }: { className?: string }) {
  return (
    <div
      className={clsx(
        "copilot-mark relative flex items-center justify-center rounded-2xl bg-gradient-to-br from-violet-600 via-indigo-600 to-cyan-500 text-white shadow-lg shadow-indigo-500/25",
        className ?? "h-12 w-12",
      )}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        className="h-6 w-6"
        stroke="currentColor"
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {/* Brain / AI sparkle icon */}
        <path d="M12 2L14.09 8.26L20 9.27L15.55 13.97L16.91 20L12 16.9L7.09 20L8.45 13.97L4 9.27L9.91 8.26L12 2Z" />
      </svg>
    </div>
  );
}

export function BrandLockup({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <CampusCopilotMark className={compact ? "h-9 w-9 rounded-xl" : "h-11 w-11"} />
      <div>
        <p className="font-bold tracking-tight text-slate-950">{compact ? "RetentionOS" : "RetentionOS Copilot"}</p>
        <p className="text-[11px] tracking-wide text-slate-500">
          {compact ? "Institution Suite" : "AI-Powered Student Success"}
        </p>
      </div>
    </div>
  );
}
