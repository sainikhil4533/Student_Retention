import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  MessageSquareMore,
  Plus,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import clsx from "clsx";

import { apiRequest } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDate } from "../lib/format";
import { CopilotMessage, CopilotSession } from "../types";
import { CampusCopilotMark } from "./brand";
import { Button, Card, EmptyState } from "./ui";

type SessionResponse = {
  session: CopilotSession;
  messages: CopilotMessage[];
};

type SessionListResponse = {
  sessions: CopilotSession[];
};

type ChatSurfaceMode = "dock" | "page";

const STARTER_PROMPTS: Record<string, string[]> = {
  student: [
    "Am I likely to drop out?",
    "Do I have any warnings right now?",
    "What should I focus on first this week?",
  ],
  counsellor: [
    "Who should I focus on first?",
    "Which students are under the most pressure?",
    "Show me active cases that need follow-up.",
  ],
  admin: [
    "Which branch needs attention first and why?",
    "How many imported students are there?",
    "Compare Urban vs Rural students and tell me what is driving the gap.",
  ],
  system: [
    "Which branch needs attention first and why?",
    "How many imported students are there?",
    "Compare Urban vs Rural students and tell me what is driving the gap.",
  ],
};

export function ChatbotDock() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-4 right-4 z-40 flex items-center gap-3 rounded-full border border-white/70 bg-slate-950 px-4 py-3 text-white shadow-lift transition hover:-translate-y-1 md:bottom-6 md:right-6"
      >
        <CampusCopilotMark className="h-11 w-11 rounded-[16px] shadow-none" />
        <div className="hidden text-left sm:block">
          <p className="text-sm font-semibold">Campus Copilot</p>
          <p className="text-xs text-slate-300">Ask naturally, stay grounded.</p>
        </div>
      </button>

      {open ? (
        <CopilotWorkspace
          mode="dock"
          onClose={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}

export function ChatbotPage() {
  return <CopilotWorkspace mode="page" />;
}

function CopilotWorkspace({
  mode,
  onClose,
}: {
  mode: ChatSurfaceMode;
  onClose?: () => void;
}) {
  const { auth } = useAuth();
  const queryClient = useQueryClient();
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [mobileHistoryOpen, setMobileHistoryOpen] = useState(mode === "page");

  const sessionsQuery = useQuery({
    queryKey: ["copilot-sessions", auth?.accessToken],
    queryFn: () =>
      apiRequest<SessionListResponse>("/copilot/sessions", {
        token: auth?.accessToken,
      }),
    enabled: Boolean(auth?.accessToken),
  });

  const createSession = useMutation({
    mutationFn: () =>
      apiRequest<SessionResponse>("/copilot/sessions", {
        method: "POST",
        token: auth?.accessToken,
        body: { title: "New conversation" },
      }),
    onSuccess: (payload) => {
      queryClient.invalidateQueries({ queryKey: ["copilot-sessions", auth?.accessToken] });
      queryClient.setQueryData(["copilot-session", payload.session.id, auth?.accessToken], payload);
      setSelectedSessionId(payload.session.id);
      setMobileHistoryOpen(false);
    },
  });

  useEffect(() => {
    if (!selectedSessionId && sessionsQuery.data?.sessions?.length) {
      setSelectedSessionId(sessionsQuery.data.sessions[0].id);
    }
  }, [selectedSessionId, sessionsQuery.data?.sessions]);

  const sessionQuery = useQuery({
    queryKey: ["copilot-session", selectedSessionId, auth?.accessToken],
    queryFn: () =>
      apiRequest<SessionResponse>(`/copilot/sessions/${selectedSessionId}`, {
        token: auth?.accessToken,
      }),
    enabled: Boolean(auth?.accessToken && selectedSessionId),
  });

  const sendMessage = useMutation({
    mutationFn: (content: string) =>
      apiRequest<{
        session: CopilotSession;
        user_message: CopilotMessage;
        assistant_message: CopilotMessage;
      }>(`/copilot/sessions/${selectedSessionId}/messages`, {
        method: "POST",
        token: auth?.accessToken,
        body: { content },
      }),
    onSuccess: () => {
      if (selectedSessionId) {
        queryClient.invalidateQueries({ queryKey: ["copilot-session", selectedSessionId, auth?.accessToken] });
      }
      queryClient.invalidateQueries({ queryKey: ["copilot-sessions", auth?.accessToken] });
      setDraft("");
    },
  });

  const messages = useMemo(() => sessionQuery.data?.messages ?? [], [sessionQuery.data?.messages]);
  const starterPrompts = STARTER_PROMPTS[auth?.role ?? "student"] ?? STARTER_PROMPTS.student;

  const handleSend = (override?: string) => {
    const trimmed = (override ?? draft).trim();
    if (!trimmed || !selectedSessionId) {
      return;
    }
    sendMessage.mutate(trimmed);
  };

  const surfaceClassName =
    mode === "dock"
      ? "absolute inset-y-0 right-0 flex h-full w-full max-w-5xl animate-rise overflow-hidden rounded-l-[32px] border-l border-white/50 bg-slate-50 shadow-2xl"
      : "grid min-h-[72vh] gap-6 lg:grid-cols-[320px_minmax(0,1fr)]";

  const shell = (
    <div className={surfaceClassName}>
      <aside
        className={clsx(
          "border-slate-200 bg-white/90",
          mode === "dock"
            ? clsx(
                "absolute inset-y-0 left-0 z-10 w-[86%] max-w-[320px] border-r p-5 shadow-xl transition lg:static lg:flex lg:w-80 lg:translate-x-0 lg:flex-col lg:shadow-none",
                mobileHistoryOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
              )
            : "hidden rounded-[28px] border p-5 shadow-soft lg:flex lg:flex-col",
        )}
      >
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-indigo-600">Chat history</p>
            <h3 className="mt-1 text-xl font-extrabold text-slate-950">Copilot threads</h3>
          </div>
          <Button variant="secondary" onClick={() => createSession.mutate()}>
            <Plus className="mr-2 h-4 w-4" />
            New
          </Button>
        </div>

        <div className="mt-5 space-y-3 overflow-y-auto pr-1">
          {sessionsQuery.data?.sessions?.length ? (
            sessionsQuery.data.sessions.map((session) => (
              <button
                key={session.id}
                type="button"
                onClick={() => {
                  setSelectedSessionId(session.id);
                  setMobileHistoryOpen(false);
                }}
                className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                  selectedSessionId === session.id
                    ? "border-indigo-200 bg-indigo-50"
                    : "border-slate-200 bg-white hover:border-slate-300"
                }`}
              >
                <p className="line-clamp-1 text-sm font-semibold text-slate-900">{session.title}</p>
                <div className="mt-2 flex items-center justify-between gap-3">
                  <p className="text-xs text-slate-500">{formatDate(session.created_at)}</p>
                  <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                    {session.system_prompt_version}
                  </span>
                </div>
              </button>
            ))
          ) : (
            <EmptyState
              title="No conversations yet"
              description="Create the first thread to get a role-aware assistant workspace."
            />
          )}
        </div>
      </aside>

      {mode === "dock" && mobileHistoryOpen ? (
        <button
          type="button"
          className="absolute inset-0 z-0 bg-slate-950/20 lg:hidden"
          onClick={() => setMobileHistoryOpen(false)}
          aria-label="Close chat history"
        />
      ) : null}

      <section
        className={clsx(
          "relative z-20 flex min-w-0 flex-col",
          mode === "dock" ? "ml-0 flex-1 bg-slate-50 lg:ml-0" : "rounded-[32px] border border-white/70 bg-white/70 shadow-soft",
        )}
      >
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white/80 px-4 py-4 sm:px-5">
          <div className="flex items-center gap-3">
            <CampusCopilotMark className="h-11 w-11 rounded-[16px]" />
            <div>
              <p className="text-sm font-semibold text-slate-950">Campus Copilot</p>
              <p className="text-xs text-slate-500">Grounded assistant with role-safe memory and fallback-safe semantic assist</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button variant="secondary" className="lg:hidden" onClick={() => setMobileHistoryOpen((value) => !value)}>
              {mobileHistoryOpen ? <ChevronLeft className="mr-2 h-4 w-4" /> : <ChevronRight className="mr-2 h-4 w-4" />}
              Threads
            </Button>
            <Button variant="secondary" onClick={() => createSession.mutate()}>
              <Plus className="mr-2 h-4 w-4" />
              New
            </Button>
            {mode === "dock" && onClose ? (
              <Button variant="ghost" onClick={onClose}>
                <X className="h-5 w-5" />
              </Button>
            ) : null}
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
          <div className="mx-auto flex max-w-4xl flex-col gap-4">
            {messages.length ? (
              messages.map((message) => <MessageBubble key={message.id} message={message} />)
            ) : (
              <Card className="mx-auto max-w-2xl text-center">
                <Sparkles className="mx-auto h-9 w-9 text-indigo-600" />
                <h3 className="mt-4 text-xl font-bold text-slate-950">Start a grounded conversation</h3>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  The assistant stays inside your role boundary, remembers the session, and answers from backend facts instead of guessing.
                </p>
              </Card>
            )}

            {sendMessage.isPending ? (
              <div className="max-w-[92%] rounded-[28px] border border-indigo-100 bg-indigo-50/70 px-4 py-3 shadow-soft">
                <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
                  <span className="inline-flex h-2.5 w-2.5 animate-pulse rounded-full bg-indigo-500" />
                  Copilot is grounding your request...
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <footer className="border-t border-slate-200 bg-white/85 px-4 py-4 sm:px-6">
          <div className="mx-auto max-w-4xl space-y-3">
            <div className="flex flex-wrap gap-2">
              {starterPrompts.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => handleSend(prompt)}
                  disabled={!selectedSessionId || sendMessage.isPending}
                  className="rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {prompt}
                </button>
              ))}
            </div>

            <div className="flex items-end gap-3 rounded-[28px] border border-slate-200 bg-white px-4 py-3 shadow-soft">
              <MessageSquareMore className="mb-2 h-5 w-5 shrink-0 text-slate-400" />
              <textarea
                rows={1}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Ask about risk, warnings, timelines, priority queues, comparisons, or reports..."
                className="min-h-[40px] flex-1 resize-none border-0 bg-transparent text-sm outline-none"
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    handleSend();
                  }
                }}
              />
              <Button onClick={() => handleSend()} disabled={!selectedSessionId || sendMessage.isPending}>
                <Send className="mr-2 h-4 w-4" />
                Send
              </Button>
            </div>
          </div>
        </footer>
      </section>
    </div>
  );

  if (mode === "dock") {
    return (
      <div className="fixed inset-0 z-50 bg-slate-950/35 backdrop-blur-sm">
        {shell}
      </div>
    );
  }

  return shell;
}

function MessageBubble({ message }: { message: CopilotMessage }) {
  const responseMode = message.metadata_json?.response_mode;
  const refusalReason = message.metadata_json?.safety_marker?.refusal_reason;
  const limitations = message.metadata_json?.limitations ?? [];
  const clarificationNeeded =
    Boolean(message.metadata_json?.query_plan?.clarification_needed) ||
    limitations.some((item) => item.toLowerCase().includes("time-window not specified"));

  return (
    <div
      className={`max-w-[92%] rounded-[28px] px-4 py-3 shadow-soft ${
        message.role === "user"
          ? "ml-auto bg-slate-950 text-white"
          : refusalReason
            ? "border border-rose-200 bg-rose-50 text-rose-900"
            : clarificationNeeded
              ? "border border-amber-200 bg-amber-50 text-slate-900"
              : responseMode === "grounded_tool_answer"
                ? "bg-white text-slate-900"
                : "border border-indigo-100 bg-indigo-50/70 text-slate-900"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        {message.role === "assistant" && clarificationNeeded ? (
          <StatusPill tone="clarification" label="Clarification needed" />
        ) : null}
        {message.role === "assistant" && refusalReason ? (
          <StatusPill tone="refusal" label="Safe refusal" />
        ) : null}
        {message.role === "assistant" && !clarificationNeeded && !refusalReason ? (
          <StatusPill tone="grounded" label="Grounded answer" />
        ) : null}
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-7">{message.content}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.18em] opacity-70">
        <span>{message.role}</span>
        {message.metadata_json?.phase ? <span>{message.metadata_json.phase}</span> : null}
        {message.created_at ? <span>{formatDate(message.created_at)}</span> : null}
      </div>
    </div>
  );
}

function StatusPill({
  tone,
  label,
}: {
  tone: "grounded" | "clarification" | "refusal";
  label: string;
}) {
  const icon =
    tone === "grounded" ? (
      <CheckCircle2 className="h-3.5 w-3.5" />
    ) : tone === "clarification" ? (
      <Sparkles className="h-3.5 w-3.5" />
    ) : (
      <AlertTriangle className="h-3.5 w-3.5" />
    );

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
        tone === "grounded" && "bg-teal-50 text-teal-700",
        tone === "clarification" && "bg-amber-50 text-amber-700",
        tone === "refusal" && "bg-rose-50 text-rose-700",
      )}
    >
      {icon}
      {label}
    </span>
  );
}
