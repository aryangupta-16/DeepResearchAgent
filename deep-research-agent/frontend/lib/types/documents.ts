/**
 * Types mirroring the backend document API schemas exactly
 * (see backend/src/app/documents/schemas.py). Do not guess fields.
 */

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export interface ResearchDocument {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  status: DocumentStatus;
  error: string | null;
  created_at: string;
  processed_at: string | null;
}

export interface DocumentListResponse {
  documents: ResearchDocument[];
  count: number;
}
