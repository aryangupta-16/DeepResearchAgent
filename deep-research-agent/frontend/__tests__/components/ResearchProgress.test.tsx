import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ResearchProgress from "@/components/research/ResearchProgress";
import type { ResearchJob } from "@/lib/types/research";

function baseJob(overrides: Partial<ResearchJob> = {}): ResearchJob {
  return {
    id: "1",
    query: "Q",
    workflow_type: "deep_research",
    status: "running",
    created_at: "2024-01-01T00:00:00Z",
    started_at: "2024-01-01T00:00:00Z",
    completed_at: null,
    error: null,
    stage: "researching",
    attempts: 1,
    progress: { completed_tasks: 2, total_tasks: 4 },
    report: null,
    ...overrides,
  };
}

describe("ResearchProgress", () => {
  it("renders the running badge, stage label and progress percentage", () => {
    render(<ResearchProgress job={baseJob({ status: "running", stage: "researching" })} />);
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByText(/Searching & researching sources/)).toBeInTheDocument();
    expect(screen.getByText("2 of 4 tasks completed")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("renders elapsed time while running and clears it on completion", () => {
    const { rerender } = render(<ResearchProgress job={baseJob({ started_at: new Date().toISOString() })} />);
    expect(screen.getByText(/Elapsed/)).toBeInTheDocument();
    rerender(<ResearchProgress job={baseJob({ status: "completed", stage: "completed", started_at: new Date().toISOString() })} />);
    expect(screen.queryByText(/Elapsed/)).not.toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("marks the current running stage active and earlier stages done", () => {
    const { container } = render(<ResearchProgress job={baseJob({ status: "running", stage: "synthesizing" })} />);
    const planningDot = container.querySelector('[data-testid="dot-planning"]');
    const researchingDot = container.querySelector('[data-testid="dot-researching"]');
    const synthesizingDot = container.querySelector('[data-testid="dot-synthesizing"]');
    expect(planningDot?.className).toContain("done");
    expect(researchingDot?.className).toContain("done");
    expect(synthesizingDot?.className).toContain("active");
  });

  it("disables the progress percentage when no tasks are set yet", () => {
    render(<ResearchProgress job={baseJob({ status: "running", stage: "planning", progress: { completed_tasks: 0, total_tasks: 0 } })} />);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("renders a 404-friendly label for a missing job gracefully (no crash)", () => {
    render(<ResearchProgress job={baseJob({ status: "failed", stage: "failed", error: "boom" })} />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });
});
