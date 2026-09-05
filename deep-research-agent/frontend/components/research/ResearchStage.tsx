"use client";

import type { ResearchJob, ResearchStage } from "@/lib/types/research";
import { STAGE_STEPS, resolveSteps } from "./stages";

export interface ResearchStageProps {
  job: ResearchJob;
}

const LABEL: Record<ResearchStage, string> = {
  planning: "Planning research",
  researching: "Searching & researching sources",
  synthesizing: "Writing report",
  validating: "Checking citations",
  completed: "Research complete",
  failed: "Research failed",
};

const DESCRIPTION: Record<ResearchStage, string> = {
  planning: "Decomposing your query into focused research tasks.",
  researching: "Searching the web (and your documents) and collecting grounded sources.",
  synthesizing: "Combining findings into a citation-aware report.",
  validating: "Verifying sources before finalizing.",
  completed: "Research complete.",
  failed: "Research failed.",
};

/** Inline stage banner + spinner shown while a job is running. */
export default function ResearchStage({ job }: ResearchStageProps) {
  const stage = (job.stage as ResearchStage | null) ?? "planning";
  const label = LABEL[stage] ?? "Working…";
  const description = DESCRIPTION[stage] ?? "";
  const isTerminal =
    job.status === "completed" ||
    job.status === "failed" ||
    job.status === "cancelled";

  const stepStates = resolveSteps(job.status, stage);

  return (
    <section
      className="card stage-banner"
      data-testid="research-stage"
      aria-live="polite"
    >
      <div className="stage-live">
        {!isTerminal ? (
          <span className="live-dot" aria-hidden="true" />
        ) : (
          <span className="live-dot" aria-hidden="true" style={{ background: "var(--color-success)" }} />
        )}
        <span className="stage-title">{label}</span>
      </div>
      <p className="stage-desc">{description}</p>
      <div className="stage-chips">
        {STAGE_STEPS.map((step, i) => {
          const state = stepStates[i]?.state ?? "pending";
          const chipClass =
            state === "done"
              ? "stage-chip done"
              : state === "active"
                ? "stage-chip active"
                : "stage-chip";
          return (
            <span
              className={chipClass}
              key={step.key}
              data-testid={`stage-badge-${step.key}`}
            >
              {state === "done" ? "✓ " : state === "active" ? "● " : "○ "}
              {step.label}
            </span>
          );
        })}
      </div>
    </section>
  );
}
