/**
 * HTTP client for the document API. Pure functions so the UI layer can swap
 * them under test (same pattern as lib/api/research.ts).
 */
import type {
  DocumentListResponse,
  ResearchDocument,
} from "@/lib/types/documents";
import { parseApiError } from "@/lib/api/errors";

const API_URL =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8000/api";

/** Upload a PDF; the backend persists + enqueues async processing (202). */
export async function uploadDocument(file: File): Promise<ResearchDocument> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(`${API_URL}/documents`, { method: "POST", body });
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as ResearchDocument;
}

export async function getDocument(id: string): Promise<ResearchDocument> {
  const response = await fetch(`${API_URL}/documents/${id}`);
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as ResearchDocument;
}

export async function listDocuments(): Promise<DocumentListResponse> {
  const response = await fetch(`${API_URL}/documents`);
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as DocumentListResponse;
}

/** URL that streams the stored binary (used by "Open document" links). */
export function documentDownloadUrl(id: string): string {
  return `${API_URL}/documents/${id}/download`;
}

/**
 * Hard-delete a document (204). The backend refuses with 409 while the
 * document is still processing; historical research evidence is never touched.
 */
export async function deleteDocument(id: string): Promise<void> {
  const response = await fetch(`${API_URL}/documents/${id}`, { method: "DELETE" });
  if (!response.ok && response.status !== 404) {
    throw await parseApiError(response);
  }
}
