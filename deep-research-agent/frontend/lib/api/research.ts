/**
 * Low-level HTTP client for the deep-research API. Pure functions so the UI
 * layer can swap them under test (see *.test.ts files).
 */
import type {
  ResearchJob,
  ResearchListResponse,
  ResearchReport,
  ResearchSourcesResponse,
  ResearchTasksResponse,
} from "@/lib/types/research";
import { parseApiError } from "@/lib/api/errors";
import type { ApiError } from "@/lib/api/errors";
export { ApiError };

export const API_URL =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8000/api";

/** Remove trailing slash to prevent double-slash in constructed URLs. */
export const API_BASE = API_URL.replace(/\/+$/, "");

export async function createResearch(
  query: string,
  workflowType = "deep_research",
  documentIds: string[] = [],
): Promise<ResearchJob> {
  const response = await fetch(`${API_BASE}/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      workflow_type: workflowType,
      ...(documentIds.length > 0 ? { document_ids: documentIds } : {}),
    }),
  });
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as ResearchJob;
}

export async function getResearch(id: string): Promise<ResearchJob> {
  const response = await fetch(`${API_BASE}/research/${id}`);
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as ResearchJob;
}

export async function getResearchTasks(id: string): Promise<ResearchTasksResponse> {
  const response = await fetch(`${API_BASE}/research/${id}/tasks`);
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as ResearchTasksResponse;
}

export async function getResearchSources(
  id: string,
): Promise<ResearchSourcesResponse> {
  const response = await fetch(`${API_BASE}/research/${id}/sources`);
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as ResearchSourcesResponse;
}

/** Recent research jobs, newest first (history sidebar). */
export async function listResearch(
  limit = 25,
  offset = 0,
): Promise<ResearchListResponse> {
  const response = await fetch(
    `${API_BASE}/research?limit=${limit}&offset=${offset}`,
  );
  if (!response.ok) throw await parseApiError(response);
  return (await response.json()) as ResearchListResponse;
}

/** Decode the JSON string stored in `job.report`; returns null when absent/invalid. */
export function parseReport(job: ResearchJob | null): ResearchReport | null {
  if (!job?.report) return null;
  try {
    return JSON.parse(job.report) as ResearchReport;
  } catch {
    return null;
  }
}

/** URL to download a completed report as a Markdown document. */
export function reportMarkdownUrl(id: string): string {
  return `${API_BASE}/research/${id}/report.md`;
}
