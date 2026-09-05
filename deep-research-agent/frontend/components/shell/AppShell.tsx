"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { FileText, History, MessagesSquare, PenLine, Brain } from "lucide-react";
import { listResearch } from "@/lib/api/research";
import { listConversations } from "@/lib/api/chat";
import type { ResearchJobSummary } from "@/lib/types/research";
import type { ConversationSummary } from "@/lib/types/chat";

const NAV_ITEMS = [
  { href: "/", label: "New Research", icon: PenLine },
  { href: "/chat", label: "Chat", icon: MessagesSquare },
  { href: "/memory", label: "Memory", icon: Brain },
  { href: "/documents", label: "Documents", icon: FileText },
];

const HISTORY_POLL_MS = 8000;

function useActive(href: string): boolean {
  const pathname = usePathname();
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function SidebarNav() {
  return (
    <nav aria-label="Primary" className="sidebar-section">
      <span className="sidebar-label">Workspace</span>
      {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
        <SidebarLink key={href} href={href} label={label} Icon={Icon} />
      ))}
    </nav>
  );
}

function SidebarLink({
  href,
  label,
  Icon,
}: {
  href: string;
  label: string;
  Icon: typeof PenLine;
}) {
  const active = useActive(href);
  return (
    <Link
      href={href}
      className={`sidebar-link${active ? " sidebar-link-active" : ""}`}
      aria-current={active ? "page" : undefined}
    >
      <Icon aria-hidden="true" />
      {label}
    </Link>
  );
}

function TopbarNav() {
  return (
    <nav aria-label="Primary" className="nav topbar-nav">
      {NAV_ITEMS.map(({ href, label }) => (
        <TopbarLink key={href} href={href} label={label} />
      ))}
    </nav>
  );
}

function TopbarLink({ href, label }: { href: string; label: string }) {
  const active = useActive(href);
  return (
    <Link
      href={href}
      className={`nav-link${active ? " nav-link-active" : ""}`}
      aria-current={active ? "page" : undefined}
    >
      {label}
    </Link>
  );
}

/** Server-backed recent jobs, polled lightly; hidden entirely when empty. */
function SidebarHistory() {
  const [jobs, setJobs] = useState<ResearchJobSummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await listResearch(8);
        if (!cancelled) setJobs(data.items);
      } catch {
        // Sidebar history is best-effort; never block the shell on it.
      }
    }
    void load();
    const timer = setInterval(load, HISTORY_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (jobs.length === 0) return null;

  return (
    <nav aria-label="Recent research" className="sidebar-section sidebar-history">
      <span className="sidebar-label">
        <History size={12} aria-hidden /> Recent
      </span>
      {jobs.map((job) => (
        <Link
          key={job.id}
          href={`/research/${job.id}`}
          className="history-item"
          title={job.query}
        >
          <span
            className={`history-dot status-${job.status}`}
            aria-hidden
            data-testid="history-status-dot"
          />
          <span className="history-query">{truncateQuery(job.query)}</span>
        </Link>
      ))}
    </nav>
  );
}

/** Recent conversations, polled lightly; hidden entirely when empty. */
function SidebarConversations() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await listConversations(8);
        if (!cancelled) setConversations(data.conversations);
      } catch {
        // Sidebar conversations are best-effort; never block the shell on it.
      }
    }
    void load();
    const timer = setInterval(load, HISTORY_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (conversations.length === 0) return null;

  return (
    <nav
      aria-label="Recent conversations"
      className="sidebar-section sidebar-history"
    >
      <span className="sidebar-label">
        <MessagesSquare size={12} aria-hidden /> Conversations
      </span>
      {conversations.map((conversation) => (
        <Link
          key={conversation.id}
          href={`/chat/${conversation.id}`}
          className="history-item"
          title={conversation.title || "Untitled conversation"}
        >
          <span className={`history-dot${conversation.context_mode === "documents" ? " status-completed" : ""}`} aria-hidden />
          <span className="history-query">
            {truncateQuery(conversation.title || "Untitled conversation")}
          </span>
        </Link>
      ))}
    </nav>
  );
}

/** Sidebar labels stay short; the full query stays available via `title`. */
const QUERY_PREVIEW_MAX = 40;
function truncateQuery(query: string): string {
  const trimmed = query.trim().replace(/\s+/g, " ");
  return trimmed.length > QUERY_PREVIEW_MAX
    ? `${trimmed.slice(0, QUERY_PREVIEW_MAX).trimEnd()}…`
    : trimmed;
}

/** Application shell: fixed sidebar on desktop, top bar on mobile. */
export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>

      <aside className="sidebar">
        <Link href="/" className="sidebar-brand">
          <span className="brand-mark" aria-hidden="true">
            R
          </span>
          <span className="brand-text">Deep Research</span>
        </Link>
        <SidebarNav />
        <SidebarHistory />
        <SidebarConversations />
        <div className="sidebar-footer">Research that cites its sources.</div>
      </aside>

      <div className="shell-main">
        <header className="topbar">
          <Link href="/" className="brand">
            <span className="brand-mark" aria-hidden="true">
              R
            </span>
            <span className="brand-text">Deep Research</span>
          </Link>
          <TopbarNav />
        </header>

        <main id="main-content" className="sidebar-content">
          {children}
        </main>

        <footer className="footer shell-footer">
          Deep Research Agent — every claim cited, every source inspectable.
        </footer>
      </div>
    </div>
  );
}