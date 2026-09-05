"use client";

import SourceCard from "./SourceCard";
import type {
  ResearchReport,
  SourceWithEvidence,
} from "@/lib/types/research";

export interface ResearchReportProps {
  report: ResearchReport;
  sources: SourceWithEvidence[];
  /** Open the evidence drawer for a given source id. */
  onInspectSource: (sourceId: string) => void;
}

/**
 * Render a structured report. Citations are surfaced as numbered chips per section
 * (the LLM provides `citation_source_ids`, not inline [1] markers), so we number
 * them globally in first-seen order for stable references.
 */
export default function ResearchReport({
  report,
  sources,
  onInspectSource,
}: ResearchReportProps) {
  const sourceById = new Map(sources.map((s) => [s.id, s]));

  // Build a stable global numbering for cited sources across all sections.
  const citationOrder: string[] = [];
  const seen = new Set<string>();
  for (const section of report.sections ?? []) {
    for (const id of section.citation_source_ids ?? []) {
      if (!seen.has(id)) {
        seen.add(id);
        citationOrder.push(id);
      }
    }
  }
  const citationNumber = (id: string) => citationOrder.indexOf(id) + 1;

  // Phase 8: web citations read [W1]; document citations read [D2] and
  // surface the page number from their evidence locators (e.g. "Page 12").
  const citationLabel = (
    id: string,
  ): { prefix: "W" | "D"; n: number; source?: SourceWithEvidence; pageHint?: string } => {
    const source = sourceById.get(id);
    const isDocument = source?.source_type === "document";
    let pageHint: string | undefined;
    if (isDocument) {
      const locator = source?.evidence.find((e) => e.locator)?.locator;
      if (locator) pageHint = locator.replace(/^page\s*/i, "Page ");
    }
    return { prefix: isDocument ? "D" : "W", n: citationNumber(id), source, pageHint };
  };

  const citedCount = citationOrder.length;
  const evidenceCount = sources.reduce((acc, s) => acc + s.evidence.length, 0);

  return (
    <article className="report-wrap" data-testid="research-report">
      <header className="report-header">
        <h1 className="report-title">{report.title}</h1>
        <div className="report-meta">
          <span className="badge badge-completed">
            <span className="badge-dot" aria-hidden="true" />
            Complete
          </span>
          <span className="badge">
            {sources.length} source{sources.length === 1 ? "" : "s"}
          </span>
          <span className="badge">{citedCount} cited</span>
          <span className="badge">{evidenceCount} evidence item{evidenceCount === 1 ? "" : "s"}</span>
        </div>
        {report.summary && <p className="report-summary">{report.summary}</p>}
      </header>

      {(report.sections ?? []).map((section, i) => (
        <section className="report-section" key={`${section.heading}-${i}`}>
          <h2 className="section-heading">
            {section.heading}
            <span className="section-badge">{i + 1}</span>
          </h2>
          <p className="section-content">{section.content}</p>
          {section.citation_source_ids &&
            section.citation_source_ids.length > 0 && (
            <div className="citation-row" data-testid="citation-chips">
              {section.citation_source_ids.map((id, j) => {
                const { prefix, n, source, pageHint } = citationLabel(id);
                const isDocument = prefix === "D";
                const titleParts = [
                  source?.title || source?.url || id,
                  ...(isDocument && pageHint ? [pageHint] : []),
                ];
                return (
                  <button
                    type="button"
                    key={`${i}-${j}-${id}`}
                    className="citation-chip"
                    onClick={() => onInspectSource(id)}
                    aria-label={`Cited ${isDocument ? "document" : "web"} source ${n}: ${titleParts.join(" — ")}`}
                    data-testid={`citation-chip-${i}-${n}`}
                    data-citation-type={prefix}
                    disabled={!source}
                    title={titleParts.join(" — ")}
                  >
                    [{prefix}{n}]
                  </button>
                );
              })}
            </div>
          )}
        </section>
      ))}

      {report.conclusion ? (
        <section className="report-section" data-testid="report-conclusion">
          <h2 className="section-heading">
            Conclusion
            <span className="section-badge">✓</span>
          </h2>
          <p className="section-content">{report.conclusion}</p>
        </section>
      ) : null}

      <section className="report-section" data-testid="report-sources">
        <h2 className="section-heading">Sources</h2>
        {sources.length === 0 ? (
          <p className="muted small">
            No sources were captured for this report.
          </p>
        ) : (
          <div className="source-grid">
            {sources.map((source) => (
              <SourceCard key={source.id} source={source} />
            ))}
          </div>
        )}
      </section>
    </article>
  );
}
