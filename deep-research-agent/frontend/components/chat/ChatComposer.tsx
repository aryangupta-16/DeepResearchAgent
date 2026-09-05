"use client";

import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api/errors";
import { listDocuments } from "@/lib/api/documents";

export interface ChatComposerProps {
  /**
   * Called with the trimmed message; resolves when the turn is persisted.
   * The parent owns the loading/optimistic states across the whole thread.
   */
  onSend: (content: string) => Promise<void>;
  /** Whether this conversation answers from uploaded documents (Phase C2). */
  useDocuments: boolean;
  /** Toggle document grounding for this conversation. */
  onToggleDocuments: (enabled: boolean) => Promise<void>;
  /** Disabled while a turn is in flight or the conversation is loading. */
  disabled?: boolean;
}

const MAX_LENGTH = 8000;

/**
 * Chat composer with a "Use uploaded documents" toggle (enabled only when at
 * least one ready document exists in the library).
 */
export default function ChatComposer({
  onSend,
  useDocuments,
  onToggleDocuments,
  disabled = false,
}: ChatComposerProps) {
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [documentsAvailable, setDocumentsAvailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void listDocuments()
      .then((res) => {
        if (!cancelled)
          setDocumentsAvailable(
            res.documents.some((doc) => doc.status === "ready"),
          );
      })
      .catch(() => {
        /* documents are optional; never block the composer */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const trimmed = content.trim();
  const canSend = trimmed.length > 0 && !sending && !disabled;
  const remaining = MAX_LENGTH - content.length;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSend) return;
    setSending(true);
    setError(null);
    try {
      await onSend(trimmed);
      setContent("");
    } catch (err) {
      const apiErr = err as ApiError;
      setError(
        apiErr?.message ||
          "We could not reach the chat backend. Is it running?",
      );
    } finally {
      setSending(false);
    }
  }

  async function handleToggle(enabled: boolean) {
    setError(null);
    try {
      await onToggleDocuments(enabled);
    } catch (err) {
      const apiErr = err as ApiError;
      setError(apiErr?.message || "Could not update the conversation context.");
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="card chat-composer"
      data-testid="chat-composer"
    >
      <div className="composer-context-row">
        <label className="chat-context-toggle" data-testid="documents-toggle">
          <input
            type="checkbox"
            checked={useDocuments}
            disabled={disabled || !documentsAvailable}
            onChange={(e) => void handleToggle(e.target.checked)}
            aria-label="Answer from uploaded documents"
          />
          <span>Answer from uploaded documents</span>
        </label>
        {!documentsAvailable && !disabled && (
          <span className="form-hint" data-testid="documents-unavailable">
            No ready documents — upload one first.
          </span>
        )}
      </div>

      <textarea
        className="input textarea chat-composer-input"
        rows={3}
        maxLength={MAX_LENGTH}
        placeholder="Ask a quick question…"
        value={content}
        onChange={(e) => setContent(e.target.value.slice(0, MAX_LENGTH))}
        disabled={sending || disabled}
        aria-invalid={!!error}
        aria-describedby={error ? "composer-error" : undefined}
      />
      {error && (
        <p
          id="composer-error"
          className="form-error"
          role="alert"
          data-testid="composer-error"
        >
          {error}
        </p>
      )}
      <div className="composer-actions">
        {/* Counter only appears near the limit — noise otherwise. */}
        {remaining <= 300 && (
          <span
            className={`form-hint${remaining < 100 ? " char-limit-warn" : ""}`}
            data-testid="char-counter"
          >
            {remaining} characters left
          </span>
        )}
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!canSend}
          aria-busy={sending}
          data-testid="send-message"
        >
          {sending && <span className="spinner" />}
          {sending ? "Thinking…" : "Send"}
        </button>
      </div>
    </form>
  );
}