import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ResearchReport from "@/components/research/ResearchReport";
import type { ResearchReport as Report, SourceWithEvidence } from "@/lib/types/research";

const report: Report = {
  title: "Hydrogen vs Electric Trucks",
  summary: "A concise summary of the findings.",
  sections: [
    {
      heading: "Safety considerations",
      content: "Electric trucks have fewer moving parts.",
      citation_source_ids: ["s2", "s1"],
    },
    {
      heading: "Environmental impact",
      content: "Hydrogen production is energy-intensive.",
      citation_source_ids: ["s1"],
    },
  ],
  conclusion: "Electric trucks appear safer overall.",
};

const sources: SourceWithEvidence[] = [
  {
    id: "s1",
    url: "https://example.com/electric",
    title: "Electric Trucks Overview",
    domain: "example.com",
    source_type: "web",
    document_id: null,
    retrieved_at: "2024-01-01T00:00:00Z",
    evidence: [
      { id: "e1", claim: "Electric trucks are quieter.", excerpt: "…quieter…", locator: "para 2" },
    ],
  },
  {
    id: "s2",
    url: "https://example.com/hydrogen",
    title: "Hydrogen Trucks Overview",
    domain: "example.com",
    source_type: "web",
    document_id: null,
    retrieved_at: "2024-01-01T00:00:00Z",
    evidence: [],
  },
];

describe("ResearchReport", () => {
  it("renders the title, summary, sections and conclusion", () => {
    render(<ResearchReport report={report} sources={sources} onInspectSource={vi.fn()} />);
    expect(screen.getByText(report.title)).toBeInTheDocument();
    expect(screen.getByText(report.summary)).toBeInTheDocument();
    expect(screen.getByText("Safety considerations")).toBeInTheDocument();
    expect(screen.getByText("Environmental impact")).toBeInTheDocument();
    expect(screen.getByText(report.conclusion)).toBeInTheDocument();
  });

    it("numbers citations globally in first-seen order", () => {
    render(<ResearchReport report={report} sources={sources} onInspectSource={vi.fn()} />);
    // s2 is cited first -> [W1], then s1 -> [W2]; both appear in section 0
    expect(screen.getByTestId("citation-chip-0-1")).toHaveTextContent("[W1]");
    expect(screen.getByTestId("citation-chip-0-2")).toHaveTextContent("[W2]");
    // section 1 re-uses the global number for s1 -> [W2]
    expect(screen.getByTestId("citation-chip-1-2")).toHaveTextContent("[W2]");
  });

  it("calls onInspectSource with the source id when a chip is clicked", () => {
    const onInspectSource = vi.fn();
    render(<ResearchReport report={report} sources={sources} onInspectSource={onInspectSource} />);
    // chip [2] corresponds to s1 (cited second, globally)
    fireEvent.click(screen.getByTestId("citation-chip-0-2"));
    expect(onInspectSource).toHaveBeenCalledWith("s1");
  });

  it("renders the sources section and SourceCards", () => {
    render(<ResearchReport report={report} sources={sources} onInspectSource={vi.fn()} />);
    expect(screen.getAllByTestId("source-card")).toHaveLength(2);
  });

  it("renders a fallback when no sources are available", () => {
    render(<ResearchReport report={report} sources={[]} onInspectSource={vi.fn()} />);
    expect(screen.getByText(/No sources were captured/)).toBeInTheDocument();
  });
});
