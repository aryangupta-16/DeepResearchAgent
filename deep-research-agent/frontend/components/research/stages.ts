import type { ResearchStage, ResearchStatus } from "@/lib/types/research";

/** Ordered steps of a deep-research run, in execution order. */
export interface StageStep {
  key: ResearchStage;
  label: string;
  /** Short description shown alongside the step. */
  description: string;
}

export const STAGE_STEPS: StageStep[] = [
  { key: "planning", label: "Planning", description: "Decomposing the query into research tasks." },
  { key: "researching", label: "Researching", description: "Searching the web and collecting sources." },
  { key: "synthesizing", label: "Writing report", description: "Combining findings into a citation-aware report." },
  { key: "validating", label: "Checking citations", description: "Verifying sources before finalizing." },
];

export function stageOrder(stage: ResearchStage | string | null | undefined): number {
  if (!stage) return -1;
  return STAGE_STEPS.findIndex((s) => s.key === stage);
}

export type StepState = "done" | "active" | "pending";

export interface ResolvedStep extends StageStep {
  state: StepState;
}

/**
 * Resolve the step state for each stage.
 * - completed → all done; failed/cancelled → steps up to current are done, rest pending.
 * - running → steps before `stage` are done; `stage` is active; later steps pending.
 */
export function resolveSteps(
  status: ResearchStatus,
  stage: ResearchStage | string | null,
): ResolvedStep[] {
  const idx = stageOrder(stage);
  return STAGE_STEPS.map((step, i) => {
    let state: StepState;
    if (status === "completed") state = "done";
    else if (status === "failed" || status === "cancelled") {
      state = i <= idx && idx >= 0 ? "done" : "pending";
    } else if (i < idx) {
      state = "done";
    } else if (i === idx) {
      state = "active";
    } else {
      state = "pending";
    }
    return { ...step, state };
  });
}

