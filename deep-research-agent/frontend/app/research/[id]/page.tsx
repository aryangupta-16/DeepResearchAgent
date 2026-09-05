"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import ResearchProgress from "@/components/research/ResearchProgress";
import ResearchStage from "@/components/research/ResearchStage";
import ResearchReport from "@/components/research/ResearchReport";
import EvidencePanel from "@/components/research/EvidencePanel";
import ReportSkeleton from "@/components/research/ReportSkeleton";
import {
  getResearch,
  getResearchSources,
  parseReport,
  reportMarkdownUrl,
} from "@/lib/api/research";
import { ApiError } from "@/lib/api/errors";
import type { ResearchJob, SourceWithEvidence } from "@/lib/types/research";

const POLL_INTERVAL_MS = 2500;
const TERMINAL: ReadonlySet<ResearchJob["status"]> = new Set([
  "completed",
  "failed",
  "cancelled",
] as ResearchJob["status"][]);

export default function ResearchPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params?.id;

  const [job, setJob] = useState<ResearchJob | null>(null);
  const [sources, setSources] = useState<SourceWithEvidence[] | null>(null);
  const [transientError, setTransientError] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [panelSource, setPanelSource] = useState<SourceWithEvidence | null>(
    null,
  );

  const pollRef = useRef<number | null>(null);
  const stoppedRef = useRef(false);

    useEffect(() => {
    if (!id) return;
    stoppedRef.current = false;

    const fetchOnce = async () => {
      setTransientError(false);
      try {
        const updated = await getResearch(id);
        if (stoppedRef.current) return;
        setJob(updated);

        if (TERMINAL.has(updated.status)) {
          // Stop polling once we reach a terminal status.
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
          if (sources === null) {
            if (updated.status === "completed") {
              try {
                const src = await getResearchSources(id);
                if (!stoppedRef.current) setSources(src.sources);
              } catch {
                if (!stoppedRef.current) setSources([]);
              }
            } else {
              setSources([]);
            }
          }
        }
      } catch (err) {
        if (stoppedRef.current) return;
        const apiErr = err as ApiError;
        if (apiErr?.status === 404) {
          setNotFound(true);
        } else {
          setTransientError(true);
        }
      }
    };

    void fetchOnce();
    pollRef.current = window.setInterval(fetchOnce, POLL_INTERVAL_MS);

    return () => {
      stoppedRef.current = true;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-fetch sources once when the job transitions to completed.
  useEffect(() => {
    if (!id || !job || job.status !== "completed" || sources !== null) return;
    void (async () => {
      try {
        const src = await getResearchSources(id);
        setSources(src.sources);
      } catch {
        setSources([]);
      }
    })();
  }, [id, job, sources]);

  if (!id) return null;

    if (notFound) {
    return (
      <section className="card not-found-card" data-testid="not-found">
        <p className="muted">Research job not found.</p>
        <button
          className="btn btn-outline"
          onClick={() => router.push("/")}
          data-testid="back-home"
        >
          Back to home
        </button>
      </section>
    );
  }

  if (!job) {
    return <ReportSkeleton message="Starting research…" />;
  }

  const isTerminal = TERMINAL.has(job.status);
  // Decode the structured report (a JSON string in `job.report`) only for
  // completed jobs; cheap & safe to recompute each render.
  const report = job.status === "completed" ? parseReport(job) : null;

  return (
    <div data-testid="research-page">
      <header className="query-card job-header">
        <h2 className="query-label">Query</h2>
        <p className="query-text">{job.query}</p>
      </header>

      {!isTerminal && (
        <>
          <ResearchStage job={job} />
          <ResearchProgress job={job} />
        </>
      )}

      {transientError && !isTerminal && (
        <div
          className="callout callout-error transient-error"
          data-testid="transient-error"
        >
          Couldn&apos;t reach the backend for a moment — retrying…
        </div>
      )}

      {job.status === "failed" && (
        <div
          className="callout callout-error job-failed"
          data-testid="job-failed"
        >
          <strong>Research failed</strong>
          <p className="muted small job-failed-message">
            {job.error || "No details were reported."}
          </p>
          <div className="job-failed-actions">
            <button
              className="btn btn-outline"
              onClick={() => router.push("/")}
              data-testid="retry-link"
            >
              Start a new research
            </button>
          </div>
        </div>
      )}

      {job.status === "completed" && (
        <>
          <div className="report-actions">
            <a
              className="btn btn-outline btn-sm"
              href={reportMarkdownUrl(id)}
              download
              data-testid="download-markdown"
            >
              Download report (.md)
            </a>
          </div>
          <ResearchProgress job={job} />
          {sources === null ? (
            <ReportSkeleton message="Fetching the report…" />
          ) : report ? (
            <ResearchReport
              report={report}
              sources={sources}
              onInspectSource={(sourceId) => {
                const src = sources.find((s) => s.id === sourceId);
                if (src) setPanelSource(src);
              }}
            />
          ) : (
            <div className="callout no-report" data-testid="no-report">
              The report was not available. Refresh the page.
            </div>
          )}
        </>
      )}

      {panelSource && (
        <EvidencePanel source={panelSource} onClose={() => setPanelSource(null)} />
      )}
    </div>
  );
}