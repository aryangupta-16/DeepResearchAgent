"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, Zap } from "lucide-react";
import { createResearch } from "@/lib/api/research";
import { createConversation, sendMessage } from "@/lib/api/chat";
import { listDocuments } from "@/lib/api/documents";
import ResearchInput from "@/components/research/ResearchInput";
import type { ApiError } from "@/lib/api/errors";

type ComposerMode = "research" | "quick";

export default function HomePage() {
  const router = useRouter();
  const [mode, setMode] = useState<ComposerMode>("research");
  const [quickQuery, setQuickQuery] = useState("");
  const [quickError, setQuickError] = useState<string | null>(null);
  const [quickSending, setQuickSending] = useState(false);

  async function handleSubmit(query: string, documentIds: string[]) {
    const job = await createResearch(query, "deep_research", documentIds);
    router.push(`/research/${job.id}`);
  }

  const loadReadyDocuments = useCallback(
    async () => (await listDocuments()).documents,
    [],
  );

  /** Quick answer: plain, synchronous chat — no deep-research job is created. */
  async function handleQuickSubmit(e: React.FormEvent) {
    e.preventDefault();
    const query = quickQuery.trim();
    if (!query || quickSending) return;
    setQuickSending(true);
    setQuickError(null);
    try {
      const conversation = await createConversation(query);
      await sendMessage(conversation.id, query);
      router.push(`/chat/${conversation.id}`);
    } catch (err) {
      const apiErr = err as ApiError;
      setQuickError(
        apiErr?.message ||
          "We could not reach the chat backend. Is it running?",
      );
    } finally {
      setQuickSending(false);
    }
  }

  return (
    <section className="home-hero" data-testid="home-page">
      <p className="eyebrow">Deep research, grounded in evidence</p>
      <h1 className="hero-title">
        Ask a question. <span className="grad-text">Get a cited report.</span>
      </h1>
      <p className="hero-sub">
        Quick answers in seconds — or send a deep question through the agent
        for a fully cited report.
      </p>

      <div className="composer-mode-toggle" role="tablist" aria-label="Composer mode">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "research"}
          className={`mode-tab${mode === "research" ? " mode-tab-active" : ""}`}
          onClick={() => setMode("research")}
          data-testid="mode-research"
        >
          <FileText aria-hidden /> Research deeply
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "quick"}
          className={`mode-tab${mode === "quick" ? " mode-tab-active" : ""}`}
          onClick={() => setMode("quick")}
          data-testid="mode-quick"
        >
          <Zap aria-hidden /> Quick answer
        </button>
      </div>

      {mode === "research" ? (
        <div className="hero-composer">
          <ResearchInput
            onSubmit={handleSubmit}
            loadDocuments={loadReadyDocuments}
          />
        </div>
      ) : (
        <form
          className="card quick-composer"
          onSubmit={handleQuickSubmit}
          data-testid="quick-composer"
        >
          <input
            className="input quick-input"
            maxLength={1000}
            placeholder="Ask anything…"
            value={quickQuery}
            onChange={(e) => setQuickQuery(e.target.value)}
            disabled={quickSending}
            aria-invalid={!!quickError}
            data-testid="quick-query-input"
          />
          {quickError && (
            <p className="form-error" role="alert" data-testid="quick-error">
              {quickError}
            </p>
          )}
          <div className="quick-composer-actions">
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!quickQuery.trim() || quickSending}
              aria-busy={quickSending}
              data-testid="quick-send"
            >
              {quickSending && <span className="spinner" />}
              {quickSending ? "Thinking…" : "Ask"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}