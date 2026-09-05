/**
 * Types mirroring the backend API schemas exactly
 * (see backend/src/app/research/schemas.py). Do not guess fields.
 */

export type ResearchStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type ResearchStage =
  | "planning"
  | "researching"
  | "synthesizing"
  | "validating"
  | "completed"
  | "failed";

export interface JobProgress {
  completed_tasks: number;
  total_tasks: number;
}

export interface ResearchJob {
  id: string;
  query: string;
  workflow_type: string;
  status: ResearchStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  stage: ResearchStage | null;
  attempts: number;
  progress: JobProgress;
  /** Full structured report; only populated once the job is completed. */
  report: string | null;
}

export interface ResearchTask {
  id: string;
  research_job_id: string;
  description: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  result: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface EvidenceItem {
  id: string;
  claim: string;
  excerpt: string | null;
  locator: string | null;
}

export interface SourceWithEvidence {
  id: string;
  /** Web sources only; document sources carry document_id instead. */
  url: string | null;
  title: string;
  domain: string | null;
  source_type: "web" | "document";
  document_id: string | null;
  retrieved_at: string;
  evidence: EvidenceItem[];
}

export interface ResearchSourcesResponse {
  research_id: string;
  sources: SourceWithEvidence[];
}

export interface ResearchTasksResponse {
  research_id: string;
  tasks: ResearchTask[];
}

/** Parsed shape of the structured report JSON stored on a completed job. */
export interface ReportSection {
  heading: string;
  content: string;
  citation_source_ids: string[];
}

export interface ResearchListResponse {
  items: ResearchJobSummary[];
  count: number;
  limit: number;
  offset: number;
}

/** Lightweight job row for the history list (no report payload). */
export interface ResearchJobSummary {
  id: string;
  query: string;
  workflow_type: string;
  status: ResearchStatus;
  created_at: string;
  completed_at: string | null;
}

export interface ResearchReport {
  title: string;
  summary: string;
  sections: ReportSection[];
  conclusion: string;
}
