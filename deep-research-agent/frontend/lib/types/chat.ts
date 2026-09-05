/**
 * Types mirroring the backend chat API schemas exactly
 * (see backend/src/app/chat/schemas.py). Do not guess fields.
 */

export type ChatRole = "user" | "assistant";
export type ChatContextMode = "none" | "documents";

/** One document citation backing an assistant reply (Phase C2). */
export interface ChatCitation {
  citation_key: string;
  document_id: string;
  document_name: string;
  page_number: number | null;
  excerpt: string;
  score: number;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  context_mode: ChatContextMode;
  created_at: string;
  updated_at: string;
}

export interface ConversationListResponse {
  conversations: ConversationSummary[];
}

export interface ChatMessage {
  /** Autoincrement int (ordering-critical); conversations remain UUID-keyed. */
  id: number;
  conversation_id: string;
  role: ChatRole;
  content: string;
  model: string | null;
  provider: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  citations: ChatCitation[];
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessage[];
}