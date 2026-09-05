"use client";

import { useEffect, useState } from "react";
import { formatElapsed } from "@/lib/utils/format";
import type { ResearchJob, ResearchStage, ResearchStatus } from "@/lib/types/research";
import { resolveSteps } from "./stages";

export interface ResearchProgressProps {
  job: ResearchJob;
}

const STATUS_LABEL: Record<ResearchStatus, string> = {
  pending: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

const STAGE_LABEL: Record<ResearchStage, string> = {
  planning: "Planning research",
  researching: "Searching & researching sources",
  synthesizing: "Writing report",
  validating: "Checking citations",
  completed: "Research complete",
  failed: "Research failed",
};

function statusClass(s: ResearchStatus): string {
  return `badge badge-${s}`;
}

/** Inline SVG check mark used inside "done" timeline dots. */
function DotCheck() {
  return (
    <svg className="dot-check" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2.5 6.5 L4.8 8.8 L9.5 3.2" />
    </svg>
  );
}

export default function ResearchProgress({ job }: ResearchProgressProps) {
  const [elapsed, setElapsed] = useState(() => formatElapsed(job.started_at));

  useEffect(() => {
    if (job.status !== "running") return;
    const id = setInterval(
      () => setElapsed(formatElapsed(job.started_at)),
      1000,
    );
    return () => clearInterval(id);
  }, [job.status, job.started_at]);

  const steps = resolveSteps(job.status, job.stage as ResearchStage | null);
  const currentStage = job.stage as ResearchStage | null;
  const stageLabel = currentStage
    ? STAGE_LABEL[currentStage]
    : STATUS_LABEL[job.status];

  const total = job.progress.total_tasks;
  const done = job.progress.completed_tasks;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
        <section
      className="card research-progress-section"
      data-testid="research-progress"
      aria-live="polite"
    >
      <div className="job-meta">
        <span className={statusClass(job.status)} data-testid="job-status">
          <span className="badge-dot" aria-hidden="true" />
          {STATUS_LABEL[job.status]}
        </span>
        <span className="muted small">Stage: {stageLabel}</span>
        <span className="spacer" />
        {job.status === "running" && (
          <span className="muted small" data-testid="elapsed">
            ⏱ Elapsed {elapsed}
          </span>
        )}
        {job.status === "completed" && job.completed_at && (
          <span className="muted small">
            ✓ Completed {new Date(job.completed_at).toLocaleString()}
          </span>
        )}
      </div>

      <p className="progress-caption muted small">
        {total > 0
          ? `${done} of ${total} tasks completed`
          : currentStage
            ? `${stageLabel}…`
            : "Queued — waiting to start."}
      </p>

      {total > 0 && (
        <div data-testid="progress-bar">
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <div className="muted small progress-pct">{pct}%</div>
        </div>
      )}

      <div className="timeline" role="list">
        {steps.map((step) => {
          const dotClass =
            step.state === "done"
              ? "timeline-dot done"
              : step.state === "active"
                ? "timeline-dot active"
                : "timeline-dot";
          return (
            <div className="timeline-item" key={step.key} role="listitem">
              <span
                className={dotClass}
                aria-hidden={step.state !== "active"}
                data-testid={`dot-${step.key}`}
              >
                {step.state === "done" ? <DotCheck /> : null}
                {step.state === "active" ? (
                  <span className="dot-pulse" />
                ) : null}
              </span>
              <div className="timeline-content">
                <div className="timeline-title">{step.label}</div>
                <div className="timeline-muted">{step.description}</div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
