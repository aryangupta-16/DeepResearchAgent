"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { MessagesSquare } from "lucide-react";
import { createConversation, listConversations } from "@/lib/api/chat";
import type { ConversationSummary } from "@/lib/types/chat";

/** Landing page for /chat: recent conversations + starting a new one. */
export default function ChatIndexPage() {
  const router = useRouter();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await listConversations(25);
      setConversations(data.conversations);
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleNew() {
    const conversation = await createConversation();
    router.push(`/chat/${conversation.id}`);
  }

  return (
    <section className="chat-index" data-testid="chat-index">
      <header className="chat-header">
        <div>
          <h1 className="chat-title">Chat</h1>
          <p className="form-hint">
            Quick answers in seconds — ground them in your documents when you
            need citations.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={handleNew}
          data-testid="start-conversation"
        >
          Start a conversation
        </button>
      </header>

      {error && (
        <div className="callout callout-error" data-testid="chat-list-error">
          Couldn&apos;t load conversations. Is the backend running?
        </div>
      )}

      {loaded && conversations.length === 0 && !error && (
        <div className="chat-empty" data-testid="chat-index-empty">
          <MessagesSquare aria-hidden />
          <p className="muted">No conversations yet — start one above.</p>
        </div>
      )}

      {conversations.length > 0 && (
        <ul className="chat-list" data-testid="chat-list">
          {conversations.map((conversation) => (
            <li key={conversation.id}>
              <Link
                href={`/chat/${conversation.id}`}
                className="chat-list-item"
                data-testid={`chat-list-item-${conversation.id}`}
              >
                <span className="chat-list-title">
                  {conversation.title || "Untitled conversation"}
                </span>
                <span className="form-hint">
                  {conversation.context_mode === "documents"
                    ? "Documents context"
                    : "Plain chat"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}