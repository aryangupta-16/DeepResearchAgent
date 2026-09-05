"use client";

import { useState } from "react";
import { documentDownloadUrl } from "@/lib/api/documents";
import type { ChatCitation, ChatMessage } from "@/lib/types/chat";

/** Split ``[C#]`` markers out of an assistant reply so they can become chips. */
export function renderContentWithCitations(
  content: string,
  citations: ChatCitation[],
): Array<{ kind: "text" | "cite"; text: string; citation?: ChatCitation }> {
  const byKey = new Map(citations.map((c) => [c.citation_key, c]));
  const parts: Array<{
    kind: "text" | "cite";
    text: string;
    citation?: ChatCitation;
  }> = [];
  let last = 0;
  // Created per call (not per iteration): a /g regex keeps state in
  // `lastIndex`, so reusing one instance across exec() calls is required for
  // the loop to advance — but it must be fresh per invocation.
  const marker = /\[C(\d+)\]/g;
  let match: RegExpExecArray | null;
  while ((match = marker.exec(content))) {
    if (match.index > last) {
      parts.push({ kind: "text", text: content.slice(last, match.index) });
    }
    const key = `C${match[1]}`;
    parts.push({
      kind: "cite",
      text: `[${key}]`,
      citation: byKey.get(key),
    });
    last = match.index + match[0].length;
  }
  if (last < content.length) {
    parts.push({ kind: "text", text: content.slice(last) });
  }
  return parts;
}

function CitationDetail({ citation }: { citation: ChatCitation }) {
  const page = citation.page_number ? ` · Page ${citation.page_number}` : "";
  return (
    <div className="chat-citation-detail" data-testid="citation-detail">
      <div className="chat-citation-title">
        {citation.document_name}
        {page && <span className="chat-citation-page">{page}</span>}
      </div>
      <p className="chat-citation-excerpt">{citation.excerpt}</p>
      <a
        className="chat-citation-link"
        href={documentDownloadUrl(citation.document_id)}
        target="_blank"
        rel="noreferrer"
      >
        Open document ↗
      </a>
    </div>
  );
}

function AssistantContent({
  message,
  onToggleCitation,
}: {
  message: ChatMessage;
  onToggleCitation: (key: string) => void;
}) {
  const parts = renderContentWithCitations(message.content, message.citations);
  return (
    <div
      className="chat-message-content"
      data-testid="chat-message-assistant"
    >
      {parts.map((part, i) =>
        part.kind === "text" ? (
          <span key={i}>{part.text}</span>
        ) : (
          <button
            type="button"
            key={i}
            className="chat-cite-chip"
            data-testid={`cite-chip-${part.text.slice(1, -1)}`}
            disabled={!part.citation}
            title={part.citation?.document_name ?? "Unresolved citation"}
            onClick={() => part.citation && onToggleCitation(part.citation.citation_key)}
          >
            {part.text}
          </button>
        ),
      )}
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  return (
    <div
      className={`chat-bubble chat-bubble-${message.role === "assistant" ? "assistant" : "user"}`}
      data-testid={message.role === "assistant" ? "chat-message-assistant" : "chat-message-user"}
    >
      {message.content}
    </div>
  );
}

/** Short local time, e.g. ``2:41 PM`` (non-streaming only — keep renders cheap). */
export function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/**
 * A full message thread with clickable, evidence-linked citation chips.
 * ``streamingText`` renders a live "Assistant · typing…" bubble during SSE.
 */
export default function ChatThread({
  messages,
  streamingText,
}: {
  messages: ChatMessage[];
  streamingText?: string | null;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);

  function toggle(key: string) {
    setExpanded((prev) => (prev === key ? null : key));
  }

  if (messages.length === 0 && !streamingText) {
    return (
      <div className="chat-empty" data-testid="chat-empty">
        <p className="muted">Ask anything — quick answers, grounded in your documents when you want.</p>
      </div>
    );
  }

  return (
    <div className="chat-thread" data-testid="chat-thread">
      {messages.map((message, i) => {
        const isAssistant = message.role === "assistant";
        return (
          <div className="chat-message" key={`${message.id}-${i}`}>
            <div
              className={`chat-message-row chat-row-${message.role}`}
              data-testid={`row-${message.role}`}
            >
              {isAssistant ? (
                <AssistantContent message={message} onToggleCitation={toggle} />
              ) : (
                <Bubble message={message} />
              )}
              <span className="chat-message-meta">
                {isAssistant ? "Assistant" : "You"} ·{" "}
                {formatTime(message.created_at)}
              </span>
            </div>
            {isAssistant &&
              message.citations.length > 0 &&
              expanded && (() => {
                const citation = message.citations.find(
                  (c) => c.citation_key === expanded,
                );
                return citation ? <CitationDetail citation={citation} /> : null;
              })()}
            {isAssistant && message.citations.length > 0 && (
              <span className="chat-citation-count" data-testid="citation-count">
                {message.citations.length} source
                {message.citations.length === 1 ? "" : "s"} cited
              </span>
            )}
          </div>
        );
      })}
      {streamingText !== undefined && streamingText !== null && (
        <div className="chat-message">
          <div className="chat-message-row">
            <div
              className="chat-message-content"
              data-testid="chat-streaming-message"
            >
              {streamingText || "…"}
            </div>
            <span className="chat-message-meta">Assistant · typing</span>
          </div>
        </div>
      )}
    </div>
  );
}