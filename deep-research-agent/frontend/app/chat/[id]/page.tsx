"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import ChatThread from "@/components/chat/ChatThread";
import ChatComposer from "@/components/chat/ChatComposer";
import { ApiError } from "@/lib/api/errors";
import {
  createConversation,
  deleteConversation,
  getConversation,
  streamMessage,
  updateConversation,
} from "@/lib/api/chat";
import type {
  ChatContextMode,
  ChatMessage,
  ConversationDetail,
} from "@/lib/types/chat";

export default function ChatConversationPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params?.id;

  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [transientError, setTransientError] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [sending, setSending] = useState(false);
  const [streamingText, setStreamingText] = useState<string | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const streamRef = useRef<{ cancel: () => void } | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);

  const refresh = useCallback(async () => {
    if (!id) return;
    setTransientError(false);
    try {
      const updated = await getConversation(id);
      setDetail(updated);
    } catch (err) {
      const apiErr = err as ApiError;
      if (apiErr?.status === 404) setNotFound(true);
      else setTransientError(true);
    }
  }, [id]);

  useEffect(() => {
    setNotFound(false);
    setDetail(null);
    void refresh();
  }, [refresh]);

  // Auto-scroll to the newest message on updates and during streaming.
  useEffect(() => {
    const node = threadRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [detail?.messages, streamingText]);

  // Cancel an in-flight stream on unmount.
  useEffect(() => {
    return () => streamRef.current?.cancel();
  }, []);

  async function handleSend(content: string) {
    if (!id) return;
    setSending(true);
    setStreamError(null);
    setStreamingText("");
    let parts: string[] = [];

    const streamed: ChatMessage | null = await new Promise((resolve) => {
      let assistant: ChatMessage | null = null;
      let userMessageId: number | null = null;

      streamRef.current = streamMessage(id, content, (chunk) => {
        if (chunk.event === "start") {
          userMessageId = chunk.data.user_message_id;
          // Optimistically append the user turn to the thread.
          setDetail((prev) => {
            if (!prev) return prev;
            const userMessage: ChatMessage = {
              id: userMessageId ?? 0,
              conversation_id: id,
              role: "user",
              content,
              model: null,
              provider: null,
              prompt_tokens: null,
              completion_tokens: null,
              citations: [],
              created_at: new Date().toISOString(),
            };
            return { ...prev, messages: [...prev.messages, userMessage] };
          });
        } else if (chunk.event === "delta") {
          parts.push(chunk.data.text as string);
          setStreamingText(parts.join(""));
        } else if (chunk.event === "done") {
          assistant = chunk.data as ChatMessage;
          resolve(assistant);
        } else if (chunk.event === "error") {
          setStreamError(
            chunk.data?.message || "The assistant hit an error. Try again.",
          );
          setStreamingText(null);
          resolve(null);
        }
      });
    });

    if (streamed) {
      // Replace the optimistic user turn with the authoritative thread.
      await refresh();
      setStreamingText(null);
    }
    setSending(false);
  }

  async function handleToggleDocuments(enabled: boolean) {
    if (!id) return;
    const mode: ChatContextMode = enabled ? "documents" : "none";
    const updated = await updateConversation(id, mode);
    setDetail((prev) =>
      prev ? { ...prev, context_mode: updated.context_mode } : prev,
    );
  }

  async function handleNewConversation() {
    const conversation = await createConversation();
    router.push(`/chat/${conversation.id}`);
  }

  async function handleDelete() {
    if (!id) return;
    if (
      !window.confirm(
        "Delete this conversation and its messages? This cannot be undone.",
      )
    ) {
      return;
    }
    await deleteConversation(id);
    router.replace("/chat");
  }

  if (notFound) {
    return (
      <section className="card not-found-card" data-testid="chat-not-found">
        <p className="muted">Conversation not found.</p>
        <button
          className="btn btn-outline"
          onClick={handleNewConversation}
          data-testid="new-conversation-from-404"
        >
          Start a new conversation
        </button>
      </section>
    );
  }

  if (!detail) {
    return (
      <div className="chat-loading" data-testid="chat-loading">
        Loading conversation…
      </div>
    );
  }

  return (
    <div className="chat-page" data-testid="chat-conversation-page">
      <header className="chat-header">
        <h1 className="chat-title">{detail.title || "Untitled conversation"}</h1>
        <div className="chat-header-actions">
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={handleNewConversation}
            data-testid="new-conversation"
          >
            New
          </button>
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={handleDelete}
            data-testid="delete-conversation"
          >
            Delete
          </button>
        </div>
      </header>

      {transientError && (
        <div
          className="callout callout-error transient-error"
          data-testid="chat-transient-error"
        >
          Couldn&apos;t reach the backend for a moment — refresh to retry.
        </div>
      )}
      {streamError && (
        <div className="callout callout-error" data-testid="chat-stream-error">
          {streamError}
        </div>
      )}

      <div
        className="chat-thread-scroll"
        ref={threadRef}
        data-testid="chat-thread-scroll"
      >
        <ChatThread
          messages={detail.messages}
          streamingText={streamingText}
        />
      </div>

      <ChatComposer
        onSend={handleSend}
        disabled={sending}
        useDocuments={detail.context_mode === "documents"}
        onToggleDocuments={handleToggleDocuments}
      />
    </div>
  );
}