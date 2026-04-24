import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  Bot,
  ChevronLeft,
  Copy,
  Check,
  MessageSquare,
  Plus,
  Send,
  Sparkles,
  X,
  User,
} from "lucide-react";
import clsx from "clsx";

import { apiRequest } from "../lib/api";
import { useAuth } from "../lib/auth";
import { CopilotMessage, CopilotSession } from "../types";
import { CampusCopilotMark } from "./brand";

/* ─────────────────── Types ─────────────────── */
type SessionResponse = { session: CopilotSession; messages: CopilotMessage[] };
type SessionListResponse = { sessions: CopilotSession[] };
type ChatSurfaceMode = "dock" | "page";

/* ─────────────────── Starter prompts per role ─────────────────── */
const STARTER_PROMPTS: Record<string, { icon: string; text: string }[]> = {
  student: [
    { icon: "📊", text: "What is my current risk level?" },
    { icon: "⚠️", text: "Do I have any warnings?" },
    { icon: "🎯", text: "What should I focus on this week?" },
  ],
  counsellor: [
    { icon: "🔥", text: "Who needs attention first?" },
    { icon: "📋", text: "Show active cases needing follow-up" },
    { icon: "📈", text: "Which students are under pressure?" },
  ],
  admin: [
    { icon: "🏫", text: "Branch wise risk overview" },
    { icon: "📊", text: "How many students are high risk?" },
    { icon: "🔍", text: "Which department needs attention first?" },
  ],
  system: [
    { icon: "🏫", text: "Branch wise risk overview" },
    { icon: "📊", text: "How many students are high risk?" },
    { icon: "🔍", text: "Which department needs attention first?" },
  ],
};

/* ─────────────────── Relative time helper ─────────────────── */
function relativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = Math.max(0, now - then);
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

/* ─────────────────── Simple Markdown Renderer ─────────────────── */
function renderMarkdown(text: string) {
  if (!text) return null;
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];
  let listItems: string[] = [];
  let numberedItems: string[] = [];

  const flushList = () => {
    if (listItems.length > 0) {
      elements.push(
        <ul key={`ul-${elements.length}`} className="my-2 ml-4 list-disc space-y-1 text-sm leading-6 text-slate-700">
          {listItems.map((item, i) => <li key={i}>{inlineFormat(item)}</li>)}
        </ul>
      );
      listItems = [];
    }
    if (numberedItems.length > 0) {
      elements.push(
        <ol key={`ol-${elements.length}`} className="my-2 ml-4 list-decimal space-y-1 text-sm leading-6 text-slate-700">
          {numberedItems.map((item, i) => <li key={i}>{inlineFormat(item)}</li>)}
        </ol>
      );
      numberedItems = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Bullet list
    if (/^[\s]*[-•*]\s+/.test(line)) {
      listItems.push(line.replace(/^[\s]*[-•*]\s+/, ""));
      continue;
    }

    // Numbered list
    if (/^[\s]*\d+[.)]\s+/.test(line)) {
      numberedItems.push(line.replace(/^[\s]*\d+[.)]\s+/, ""));
      continue;
    }

    flushList();

    // Headers
    if (/^###\s+/.test(line)) {
      elements.push(<h4 key={i} className="mt-3 mb-1 text-sm font-bold text-slate-900">{inlineFormat(line.replace(/^###\s+/, ""))}</h4>);
    } else if (/^##\s+/.test(line)) {
      elements.push(<h3 key={i} className="mt-3 mb-1 text-[15px] font-bold text-slate-900">{inlineFormat(line.replace(/^##\s+/, ""))}</h3>);
    } else if (/^#\s+/.test(line)) {
      elements.push(<h2 key={i} className="mt-3 mb-1 text-base font-bold text-slate-900">{inlineFormat(line.replace(/^#\s+/, ""))}</h2>);
    }
    // Empty line
    else if (line.trim() === "") {
      elements.push(<div key={i} className="h-2" />);
    }
    // Regular paragraph
    else {
      elements.push(<p key={i} className="text-sm leading-7 text-slate-800">{inlineFormat(line)}</p>);
    }
  }
  flushList();
  return <>{elements}</>;
}

/** Bold, italic, code inline formatting */
function inlineFormat(text: string): React.ReactNode {
  // Split by **bold**, *italic*, `code`
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (/^\*\*(.+)\*\*$/.test(part)) {
      return <strong key={i} className="font-semibold text-slate-900">{part.slice(2, -2)}</strong>;
    }
    if (/^\*(.+)\*$/.test(part)) {
      return <em key={i} className="italic">{part.slice(1, -1)}</em>;
    }
    if (/^`(.+)`$/.test(part)) {
      return <code key={i} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-mono text-indigo-700">{part.slice(1, -1)}</code>;
    }
    return part;
  });
}

/* ─────────────────── Dock Launcher (FAB) ─────────────────── */
export function ChatbotDock() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <motion.button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-5 right-5 z-40 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-600 via-indigo-600 to-cyan-500 text-white shadow-xl shadow-indigo-500/30"
        whileHover={{ scale: 1.08 }}
        whileTap={{ scale: 0.95 }}
      >
        <Sparkles className="h-6 w-6" />
      </motion.button>

      <AnimatePresence>
        {open && (
          <motion.div
            className="fixed inset-0 z-50"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={() => setOpen(false)} />
            <motion.div
              className="absolute inset-y-0 right-0 flex w-full max-w-[900px]"
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ type: "spring", damping: 28, stiffness: 300 }}
            >
              <CopilotWorkspace mode="dock" onClose={() => setOpen(false)} />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

export function ChatbotPage() {
  return <CopilotWorkspace mode="page" />;
}

/* ─────────────────── Main Workspace ─────────────────── */
function CopilotWorkspace({ mode, onClose }: { mode: ChatSurfaceMode; onClose?: () => void }) {
  const { auth } = useAuth();
  const queryClient = useQueryClient();
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(mode === "page");
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const sessionsQuery = useQuery({
    queryKey: ["copilot-sessions", auth?.accessToken],
    queryFn: () => apiRequest<SessionListResponse>("/copilot/sessions", { token: auth?.accessToken }),
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
      setSidebarOpen(false);
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
      apiRequest<SessionResponse>(`/copilot/sessions/${selectedSessionId}`, { token: auth?.accessToken }),
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
        timeoutMs: 60000,
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
  const hasMessages = messages.length > 1; // First message is system greeting

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, sendMessage.isPending]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 160) + "px";
    }
  }, [draft]);

  const handleSend = (override?: string) => {
    const trimmed = (override ?? draft).trim();
    if (!trimmed || !selectedSessionId) return;
    sendMessage.mutate(trimmed);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const handleCopy = (id: number, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  /* ─── Sidebar ─── */
  const sidebar = (
    <aside
      className={clsx(
        "flex flex-col border-r border-slate-200/80 bg-white",
        mode === "dock"
          ? clsx(
              "absolute inset-y-0 left-0 z-30 w-72 transition-transform duration-300",
              sidebarOpen ? "translate-x-0" : "-translate-x-full",
              "lg:static lg:translate-x-0",
            )
          : "hidden w-80 rounded-l-3xl lg:flex",
      )}
    >
      <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-4">
        <h3 className="text-sm font-bold text-slate-900">Conversations</h3>
        <button
          onClick={() => createSession.mutate()}
          className="flex h-8 w-8 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600 transition hover:bg-indigo-100"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {sessionsQuery.data?.sessions?.length ? (
          <div className="space-y-1">
            {sessionsQuery.data.sessions.map((session) => (
              <button
                key={session.id}
                type="button"
                onClick={() => { setSelectedSessionId(session.id); setSidebarOpen(false); }}
                className={clsx(
                  "w-full rounded-xl px-3 py-2.5 text-left transition-all",
                  selectedSessionId === session.id
                    ? "bg-indigo-50 text-indigo-900"
                    : "text-slate-600 hover:bg-slate-50",
                )}
              >
                <div className="flex items-center gap-2">
                  <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-50" />
                  <p className="line-clamp-1 text-[13px] font-medium">{session.title}</p>
                </div>
                <p className="mt-1 pl-5.5 text-[11px] text-slate-400">{relativeTime(session.created_at)}</p>
              </button>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <MessageSquare className="h-8 w-8 text-slate-300" />
            <p className="mt-3 text-sm font-medium text-slate-400">No conversations yet</p>
            <p className="mt-1 text-xs text-slate-400">Start a new one above</p>
          </div>
        )}
      </div>
    </aside>
  );

  /* ─── Chat Area ─── */
  const chatArea = (
    <section className="relative flex min-w-0 flex-1 flex-col bg-gradient-to-b from-slate-50/80 to-white">
      {/* Header */}
      <header className="flex items-center gap-3 border-b border-slate-200/70 bg-white/90 px-4 py-3 backdrop-blur-sm">
        {mode === "dock" && (
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="flex h-8 w-8 items-center justify-center rounded-xl text-slate-400 transition hover:bg-slate-100 lg:hidden"
          >
            <ChevronLeft className={clsx("h-4 w-4 transition-transform", sidebarOpen && "rotate-180")} />
          </button>
        )}
        <CampusCopilotMark className="h-9 w-9 rounded-xl" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-bold text-slate-900">RetentionOS Copilot</p>
          <p className="text-[11px] text-slate-400">AI-powered institutional insights</p>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => createSession.mutate()}
            className="flex h-8 items-center gap-1.5 rounded-xl bg-slate-100 px-3 text-xs font-medium text-slate-600 transition hover:bg-slate-200"
          >
            <Plus className="h-3.5 w-3.5" /> New
          </button>
          {mode === "dock" && onClose && (
            <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-xl text-slate-400 transition hover:bg-slate-100">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-4 py-6">
          {!hasMessages ? (
            /* ─── Welcome Screen ─── */
            <div className="flex flex-col items-center justify-center py-12">
              <motion.div initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ duration: 0.4 }}>
                <CampusCopilotMark className="h-16 w-16 rounded-2xl" />
              </motion.div>
              <motion.h2
                className="mt-6 text-xl font-bold text-slate-900"
                initial={{ y: 10, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: 0.15 }}
              >
                How can I help you today?
              </motion.h2>
              <motion.p
                className="mt-2 max-w-md text-center text-sm text-slate-500"
                initial={{ y: 10, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: 0.25 }}
              >
                Ask me about student risk, performance analytics, branch comparisons, or any institutional insight.
              </motion.p>

              <motion.div
                className="mt-8 grid w-full max-w-lg gap-3 sm:grid-cols-3"
                initial={{ y: 15, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: 0.35 }}
              >
                {starterPrompts.map((prompt) => (
                  <button
                    key={prompt.text}
                    type="button"
                    onClick={() => handleSend(prompt.text)}
                    disabled={!selectedSessionId || sendMessage.isPending}
                    className="group flex flex-col items-center gap-2 rounded-2xl border border-slate-200 bg-white p-4 text-center transition-all hover:border-indigo-200 hover:bg-indigo-50/50 hover:shadow-md disabled:opacity-50"
                  >
                    <span className="text-2xl">{prompt.icon}</span>
                    <span className="text-xs font-medium text-slate-600 group-hover:text-indigo-700">{prompt.text}</span>
                  </button>
                ))}
              </motion.div>
            </div>
          ) : (
            /* ─── Message Thread ─── */
            <div className="space-y-1">
              {messages.map((message, idx) => (
                <MessageBubble
                  key={message.id}
                  message={message}
                  index={idx}
                  copiedId={copiedId}
                  onCopy={handleCopy}
                />
              ))}
            </div>
          )}

          {/* Typing Indicator */}
          <AnimatePresence>
            {sendMessage.isPending && (
              <motion.div
                className="mt-4 flex items-start gap-3"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-indigo-600">
                  <Bot className="h-4 w-4 text-white" />
                </div>
                <div className="rounded-2xl rounded-tl-md bg-white px-4 py-3 shadow-sm border border-slate-100">
                  <div className="flex items-center gap-1.5">
                    <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400" style={{ animationDelay: "0ms" }} />
                    <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400" style={{ animationDelay: "150ms" }} />
                    <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400" style={{ animationDelay: "300ms" }} />
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Error */}
          {sendMessage.isError && (
            <motion.div
              className="mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              {sendMessage.error instanceof Error ? sendMessage.error.message : "Something went wrong. Please try again."}
            </motion.div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input Footer */}
      <footer className="border-t border-slate-200/70 bg-white/95 px-4 py-3 backdrop-blur-sm">
        <div className="mx-auto max-w-3xl">
          {/* Show starter chips only when conversation has messages */}
          {hasMessages && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {starterPrompts.slice(0, 2).map((prompt) => (
                <button
                  key={prompt.text}
                  type="button"
                  onClick={() => handleSend(prompt.text)}
                  disabled={!selectedSessionId || sendMessage.isPending}
                  className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-[11px] font-medium text-slate-500 transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-50"
                >
                  {prompt.text}
                </button>
              ))}
            </div>
          )}
          <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 shadow-sm transition-all focus-within:border-indigo-300 focus-within:shadow-md focus-within:shadow-indigo-100/50">
            <textarea
              ref={textareaRef}
              rows={1}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask anything about student retention..."
              className="min-h-[36px] max-h-[160px] flex-1 resize-none border-0 bg-transparent text-sm text-slate-800 outline-none placeholder:text-slate-400"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
              }}
            />
            <motion.button
              onClick={() => handleSend()}
              disabled={!draft.trim() || !selectedSessionId || sendMessage.isPending}
              className={clsx(
                "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-all",
                draft.trim()
                  ? "bg-gradient-to-br from-violet-600 to-indigo-600 text-white shadow-md shadow-indigo-500/25"
                  : "bg-slate-100 text-slate-400",
              )}
              whileHover={draft.trim() ? { scale: 1.05 } : {}}
              whileTap={draft.trim() ? { scale: 0.95 } : {}}
            >
              <Send className="h-4 w-4" />
            </motion.button>
          </div>
          <p className="mt-2 text-center text-[10px] text-slate-400">
            Responses are grounded in your institution's data. Always verify critical decisions.
          </p>
        </div>
      </footer>
    </section>
  );

  /* ─── Layout ─── */
  const workspace = (
    <div className={clsx(
      "flex overflow-hidden bg-white",
      mode === "dock" ? "h-full w-full rounded-l-3xl shadow-2xl" : "min-h-[75vh] rounded-3xl border border-slate-200 shadow-xl",
    )}>
      {sidebar}
      {/* Sidebar overlay for mobile dock */}
      {mode === "dock" && sidebarOpen && (
        <div className="absolute inset-0 z-20 bg-black/20 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}
      {chatArea}
    </div>
  );

  if (mode === "dock") {
    return workspace;
  }
  return workspace;
}

/* ─────────────────── Message Bubble ─────────────────── */
function MessageBubble({
  message,
  index,
  copiedId,
  onCopy,
}: {
  message: CopilotMessage;
  index: number;
  copiedId: number | null;
  onCopy: (id: number, text: string) => void;
}) {
  const isUser = message.role === "user";

  return (
    <motion.div
      className={clsx("flex gap-3 py-3", isUser ? "justify-end" : "justify-start")}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.05, 0.3), duration: 0.3 }}
    >
      {/* Avatar */}
      {!isUser && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-indigo-600 shadow-sm">
          <Bot className="h-4 w-4 text-white" />
        </div>
      )}

      {/* Bubble */}
      <div className={clsx("group relative max-w-[80%] min-w-0")}>
        <div
          className={clsx(
            "rounded-2xl px-4 py-3",
            isUser
              ? "rounded-tr-md bg-gradient-to-br from-indigo-600 to-violet-600 text-white shadow-md shadow-indigo-500/20"
              : "rounded-tl-md border border-slate-100 bg-white text-slate-800 shadow-sm",
          )}
        >
          {isUser ? (
            <p className="text-sm leading-7 whitespace-pre-wrap">{message.content}</p>
          ) : (
            renderMarkdown(message.content)
          )}
        </div>

        {/* Meta row */}
        <div className={clsx("mt-1.5 flex items-center gap-2 px-1", isUser ? "justify-end" : "justify-start")}>
          <span className="text-[10px] text-slate-400">
            {message.created_at ? relativeTime(message.created_at) : ""}
          </span>
          {!isUser && (
            <button
              onClick={() => onCopy(message.id, message.content)}
              className="flex h-5 w-5 items-center justify-center rounded-md text-slate-300 opacity-0 transition group-hover:opacity-100 hover:bg-slate-100 hover:text-slate-500"
              title="Copy response"
            >
              {copiedId === message.id ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
            </button>
          )}
        </div>
      </div>

      {/* User avatar */}
      {isUser && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-slate-200 shadow-sm">
          <User className="h-4 w-4 text-slate-600" />
        </div>
      )}
    </motion.div>
  );
}
