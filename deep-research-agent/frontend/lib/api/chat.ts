/**
 * HTTP client for the conversation (chat) API. Pure functions so the UI layer
 * can swap them under test (same pattern as lib/api/research.ts).
 */
import { parseApiError } from "@/lib/api/errors";
import type {
  ChatContextMode,
  ChatMessage,
  ConversationDetail,
  ConversationListResponse,
  ConversationSummary,
} from "@/lib/types/chat";

export const CHAT_API_URL =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8000/api";

/** Start a new chat session; ``title`` seeds the auto-title when omitted. */
export async function createConversation(
  title?: string,
  contextMode: ChatContextMode = "none",
): Promise<ConversationSummary> {
  const response = await fetch(`${CHAT_API_URL}/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...(title ? { title } : {}),
      context_mode: contextMode,
    }),
  });
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as ConversationSummary;
}

/** Recent conversations, most recently active first. */
export async function listConversations(
  limit = 25,
  offset = 0,
): Promise<ConversationListResponse> {
  const response = await fetch(
    `${CHAT_API_URL}/conversations?limit=${limit}&offset=${offset}`,
  );
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as ConversationListResponse;
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const response = await fetch(`${CHAT_API_URL}/conversations/${id}`);
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as ConversationDetail;
}

/** Toggle document grounding for a conversation (``none`` | ``documents``). */
export async function updateConversation(
  id: string,
  contextMode: ChatContextMode,
): Promise<ConversationSummary> {
  const response = await fetch(`${CHAT_API_URL}/conversations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ context_mode: contextMode }),
  });
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as ConversationSummary;
}

export async function deleteConversation(id: string): Promise<void> {
  const response = await fetch(`${CHAT_API_URL}/conversations/${id}`, {
    method: "DELETE",
  });
  if (!response.ok && response.status !== 404) {
    throw await parseApiError(response);
  }
}

/** Send one user turn; returns the persisted assistant reply (with citations). */
export async function sendMessage(
  id: string,
  content: string,
): Promise<ChatMessage> {
  const response = await fetch(`${CHAT_API_URL}/conversations/${id}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as ChatMessage;
}

export interface StreamChunk {
  event: "start" | "delta" | "done" | "error";
  data: any;
}

/**
 * Send one user turn and stream the reply as SSE. Returns an abortable
 * controller for client-side cancellation.
 */
export function streamMessage(
  id: string,
  content: string,
  onEvent: (chunk: StreamChunk) => void,
): { cancel: () => void } {
  const controller = new AbortController();

  void (async () => {
    try {
      const response = await fetch(
        `${CHAT_API_URL}/conversations/${id}/messages/stream`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
          signal: controller.signal,
        },
      );
      if (!response.ok) {
        onEvent({
          event: "error",
          data: { code: "http_error", message: `Request failed (${response.status})` },
        });
        return;
      }
      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // Frames are separated by a blank line (`\n\n`).
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const parsed = parseFrame(frame);
          if (parsed) onEvent(parsed);
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      onEvent({
        event: "error",
        data: {
          code: "network_error",
          message: (err as Error).message || "Stream failed",
        },
      });
    }
  })();

  return { cancel: () => controller.abort() };
}

/** Parse one SSE frame (``event: …\ndata: …``) into a StreamChunk. */
function parseFrame(frame: string): StreamChunk | null {
  const eventLine = frame.match(/^event:\s*(\w+)/m);
  const dataLine = frame.match(/^data:\s*(.+)$/m);
  if (!eventLine || !dataLine) return null;
  let data: any = {};
  try {
    data = JSON.parse(dataLine[1]);
  } catch {
    /* keep {} on malformed payloads */
  }
  return { event: eventLine[1] as StreamChunk["event"], data };
}