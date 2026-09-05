import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import EvidencePanel from "@/components/research/EvidencePanel";
import type { SourceWithEvidence } from "@/lib/types/research";

const source: SourceWithEvidence = {
  id: "s1",
  url: "https://example.com/page",
  title: "Page Title",
  domain: "example.com",
  source_type: "web" as const,
  document_id: null,
  retrieved_at: "2024-01-01T12:00:00Z",
  evidence: [
    { id: "e1", claim: "Robots are advancing.", excerpt: "quick brown fox", locator: "paragraph 3" },
    { id: "e2", claim: "Costs are falling.", excerpt: null, locator: null },
  ],
};

describe("EvidencePanel", () => {
  it("renders the source header, link and evidence items", () => {
    render(<EvidencePanel source={source} onClose={vi.fn()} />);
    expect(screen.getByTestId("evidence-panel")).toBeInTheDocument();
    expect(screen.getByTestId("source-link")).toHaveAttribute("href", source.url);
    expect(screen.getAllByTestId("evidence-item")).toHaveLength(2);
    // excerpt rendered in quotes
    expect(screen.getByText('"quick brown fox"')).toBeInTheDocument();
    // locator rendered
    expect(screen.getByText("Location: paragraph 3")).toBeInTheDocument();
  });

  it("omits the excerpt line and locator when absent", () => {
    render(<EvidencePanel source={source} onClose={vi.fn()} />);
    const items = screen.getAllByTestId("evidence-item");
    const last = items[1];
    expect(last.querySelector(".evidence-excerpt")).toBeNull();
    expect(last.querySelector(".evidence-locator")).toBeNull();
  });

  it("closes on Escape and the close button", () => {
    const onClose = vi.fn();
    render(<EvidencePanel source={source} onClose={onClose} />);
    fireEvent.click(screen.getByTestId("drawer-close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders a fallback message when a source has no evidence items", () => {
    const empty: SourceWithEvidence = { ...source, evidence: [] };
    render(<EvidencePanel source={empty} onClose={vi.fn()} />);
    expect(screen.getByText(/No discrete evidence items/)).toBeInTheDocument();
  });

  it("renders the link to open the source in a new tab", () => {
    render(<EvidencePanel source={source} onClose={vi.fn()} />);
    const open = screen.getByTestId("open-source");
    expect(open).toHaveAttribute("href", source.url);
  });
});
