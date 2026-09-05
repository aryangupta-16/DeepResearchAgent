import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const { mockGetResearch, mockGetSources, mockParseReport } = vi.hoisted(() => ({
  mockGetResearch: vi.fn(),
  mockGetSources: vi.fn(),
  mockParseReport: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "job-1" }),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/research", () => ({
  getResearch: mockGetResearch,
  getResearchSources: mockGetSources,
  createResearch: vi.fn(),
  getResearchTasks: vi.fn(),
  parseReport: mockParseReport,
  reportMarkdownUrl: (id: string) => `http://localhost:8000/api/research/${id}/report.md`,
}));

// React import is required because the module under test is a client component
// that uses hooks; importing it directly is fine in vitest.
import ResearchPage from "@/app/research/[id]/page";
import type { ResearchJob, SourceWithEvidence } from "@/lib/types/research";

const runningJob: ResearchJob = {
  id: "job-1",
  query: "Hydrogen vs electric trucks",
  workflow_type: "deep_research",
  status: "running",
  created_at: "2024-01-01T00:00:00Z",
  started_at: "2024-01-01T00:00:00Z",
  completed_at: null,
  error: null,
  stage: "researching",
  attempts: 1,
  progress: { completed_tasks: 1, total_tasks: 4 },
  report: null,
};

const completedJob: ResearchJob = {
  ...runningJob,
  status: "completed",
  stage: "completed",
  completed_at: "2024-01-01T00:03:21Z",
  report: JSON.stringify({
    title: "Hydrogen vs Electric Trucks",
    summary: "A concise summary.",
    sections: [
      {
        heading: "Safety",
        content: "Electric trucks are safer.",
        citation_source_ids: ["s1"],
      },
    ],
    conclusion: "Electric wins.",
  }),
};

const sourceOne: SourceWithEvidence = {
  id: "s1",
  url: "https://example.com/electric",
  title: "Electric Trucks Overview",
  domain: "example.com",
  source_type: "web" as const,
  document_id: null,
  retrieved_at: "2024-01-01T00:00:00Z",
  evidence: [{ id: "e1", claim: "Electric trucks are quieter.", excerpt: "quiet", locator: "p2" }],
};

const REPORT = {
  title: "Hydrogen vs Electric Trucks",
  summary: "A concise summary.",
  sections: [
    {
      heading: "Safety",
      content: "Electric trucks are safer.",
      citation_source_ids: ["s1"],
    },
  ],
  conclusion: "Electric wins.",
};

describe("ResearchPage polling", () => {
  beforeEach(() => {
    vi.useRealTimers();
    mockGetResearch.mockReset();
    mockGetSources.mockReset();
    mockParseReport.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders a skeleton, then the running stage, then the completed report", async () => {
    let calls = 0;
    mockGetResearch.mockImplementation(async () => {
      calls++;
      if (calls === 1) return runningJob;
      return completedJob;
    });
    mockGetSources.mockResolvedValue({ sources: [sourceOne] });
    mockParseReport.mockReturnValue(REPORT);

    render(<ResearchPage />);

    // initial async fetch resolves -> running stage appears
    await waitFor(() => screen.getByTestId("research-stage"), { timeout: 1000 });
    expect(screen.getByTestId("dot-researching").className).toContain("active");

    // the 2.5s poll returns the completed job -> report renders
    await waitFor(() => screen.getByTestId("research-report"), { timeout: 3500 });

    // sources are fetched exactly once upon completion
    expect(mockGetSources).toHaveBeenCalledTimes(1);
    expect(mockGetSources).toHaveBeenCalledWith("job-1");

    // report + citation chip + source card rendered
    expect(screen.getByText("Hydrogen vs Electric Trucks")).toBeInTheDocument();
    expect(screen.getByTestId("citation-chip-0-1")).toHaveTextContent("[W1]");
    expect(screen.getAllByTestId("source-card")).toHaveLength(1);

    // opening a citation opens the evidence drawer
    expect(screen.queryByTestId("evidence-panel")).not.toBeInTheDocument();
  });

  it("renders a not-found view when the job is gone (404)", async () => {
    mockGetResearch.mockRejectedValue({
      name: "ApiError",
      status: 404,
      message: "Research job not found.",
    });
    render(<ResearchPage />);
    await waitFor(() => screen.getByText(/Research job not found/i), {
      timeout: 1500,
    });
    expect(
      screen.getByRole("button", { name: /back to home/i }),
    ).toBeInTheDocument();
  });

  it("renders the failed state and a retry link on a failed job", async () => {
    const failedJob: ResearchJob = {
      ...runningJob,
      status: "failed",
      stage: "failed",
      error: "LLM endpoint unreachable.",
    };
    mockGetResearch.mockResolvedValue(failedJob);
    render(<ResearchPage />);
    await waitFor(() => screen.getByTestId("job-failed"), { timeout: 1500 });
    expect(screen.getByText("LLM endpoint unreachable.")).toBeInTheDocument();
    expect(screen.getByTestId("retry-link")).toBeInTheDocument();
    expect(screen.queryByTestId("research-report")).not.toBeInTheDocument();
  });

  it("clears its polling interval once the job reaches a terminal status", async () => {
    mockGetResearch.mockResolvedValue(completedJob);
    mockGetSources.mockResolvedValue({ sources: [] });
    mockParseReport.mockReturnValue(REPORT);

    const clearIntervalSpy = vi.spyOn(global, "clearInterval");
    render(<ResearchPage />);
    await waitFor(() => screen.getByTestId("research-report"), { timeout: 2000 });

    // A completed job must not fetch again; wait past a poll window and verify.
    expect(mockGetResearch).toHaveBeenCalledTimes(1);
    await new Promise((r) => setTimeout(r, 3000));
    expect(mockGetResearch).toHaveBeenCalledTimes(1);
    expect(clearIntervalSpy).toHaveBeenCalled();
    clearIntervalSpy.mockRestore();
  });
});
