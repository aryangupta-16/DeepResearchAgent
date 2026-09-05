"use client";

import type { SourceWithEvidence } from "@/lib/types/research";
import { documentDownloadUrl } from "@/lib/api/documents";

export interface SourceCardProps {
  source: SourceWithEvidence;
  /** Number of evidence items, for the subtitle. */
  evidenceCount?: number;
}

/**
 * A compact source card shown in the report's "Sources" section.
 * Web sources link to the original URL; document sources link to the
 * stored file download and are labelled as such (no fake URLs).
 */
export default function SourceCard({ source, evidenceCount }: SourceCardProps) {
  const shown = evidenceCount ?? source.evidence.length;
  const isDocument = source.source_type === "document" || !source.url;
  const subtitle = isDocument
    ? "Uploaded document"
    : (source.domain ||
        (() => {
          try {
            return new URL(source.url ?? "").hostname || source.url;
          } catch {
            return source.url ?? "";
          }
        })());
  const avatarLetter = (source.title || source.url || "?").trim().charAt(0);

  return (
    <a
      className="source-card"
      href={isDocument && source.document_id
        ? documentDownloadUrl(source.document_id)
        : (source.url ?? "#")}
      target="_blank"
      rel="noreferrer"
      data-testid="source-card"
      data-source-type={isDocument ? "document" : "web"}
    >
      <div className="source-head">
        <span className="source-avatar" aria-hidden="true">
          {avatarLetter}
        </span>
        <span className="source-type-badge">
          {isDocument ? "Document" : "Web"}
        </span>
      </div>
      <div className="source-title">{source.title}</div>
      {!isDocument && source.url && (
        <div className="source-url">{source.url}</div>
      )}
      <div className="source-domain">{subtitle}</div>
      <div className="source-footer">
        <span aria-hidden="true">◎</span>
        {shown} evidence item{shown === 1 ? "" : "s"} · inspect by citing it
      </div>
    </a>
  );
}
