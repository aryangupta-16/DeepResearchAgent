/**
 * HTTP client for the long-term memory API. Mirrors the chat/documents
 * client pattern: pure functions so the UI layer can swap them under test.
 */
import { parseApiError } from "@/lib/api/errors";
import type {
  Memory,
  MemoryCreate,
  MemoryListResponse,
  MemoryUpdate,
} from "@/lib/types/memory";

const API_URL =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8000/api";

/** Remove trailing slash to prevent double-slash in constructed URLs. */
const API_BASE = API_URL.replace(/\/+$/, "");

export async function listMemories(): Promise<MemoryListResponse> {
  const response = await fetch(`${API_BASE}/memory?limit=100`);
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as MemoryListResponse;
}

export async function createMemory(payload: MemoryCreate): Promise<Memory> {
  const response = await fetch(`${API_BASE}/memory`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as Memory;
}

export async function updateMemory(
  id: string,
  payload: MemoryUpdate
): Promise<Memory> {
  const response = await fetch(`${API_BASE}/memory/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as Memory;
}

export async function deleteMemory(id: string): Promise<void> {
  const response = await fetch(`${API_BASE}/memory/${id}`, {
    method: "DELETE",
  });
  if (!response.ok && response.status !== 404) {
    throw await parseApiError(response);
  }
}
