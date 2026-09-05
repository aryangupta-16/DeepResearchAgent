"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { documentDownloadUrl } from "@/lib/api/documents";
import type { SourceWithEvidence } from "@/lib/types/research";

export interface EvidencePanelProps {
  source: SourceWithEvidence;
  /** Called when the user dismisses the panel. */
  onClose: () => void;
}


/**
 * Right-hand drawer showing the evidence supporting a cited source.
 * Renders via portal so it sits above the page scroll.
 */
export default function EvidencePanel({ source, onClose }: EvidencePanelProps) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    // Prevent background scroll while open + focus the dialog for a11y.
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  const isDocument = source.source_type === "document";

  return createPortal(
    <>
      <div
        className="drawer-backdrop"
        onClick={onClose}
        aria-hidden="true"
        data-testid="drawer-backdrop"
      />
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label={`Evidence for ${source.title || source.url}`}
        data-testid="evidence-panel"
      >
        <div className="drawer-header">
          <div className="drawer-title-row">
            <h3 className="drawer-title">Evidence</h3>
            <span className={"type-badge"} data-testid="drawer-type">
              {isDocument ? "Document" : "Web source"}
            </span>
          </div>
          <button
            ref={closeRef}
            type="button"
            className="drawer-close"
            aria-label="Close evidence panel"
            onClick={onClose}
            data-testid="drawer-close"
          >
            ✕
          </button>
        </div>
        <div className="drawer-body">
          <div className="source-card">
            <div className="source-head">
              <span className="source-avatar" aria-hidden="true">
                {(source.title || "?").trim().charAt(0)}
              </span>
              <span className="source-type-badge">
                {isDocument ? "Document" : "Web"}
              </span>
            </div>
            <div className="source-title">{source.title || source.url}</div>
            {isDocument ? (
              <>
                <div
                  className="source-domain"
                  data-testid="document-source-label"
                >
                  Uploaded document
                </div>
                {source.document_id && (
                  <a
                    href={documentDownloadUrl(source.document_id)}
                    target="_blank"
                    rel="noreferrer"
                    className="source-url"
                    data-testid="document-link"
                  >
                    Open document ↗
                  </a>
                )}
              </>
            ) : (
              <a
                href={source.url ?? "#"}
                target="_blank"
                rel="noreferrer"
                className="source-url"
                data-testid="source-link"
              >
                {source.url}
              </a>
            )}
            {source.domain && (
              <div className="source-domain">{source.domain}</div>
            )}
                        <div className="muted small source-retrieved">
              Retrieved {new Date(source.retrieved_at).toLocaleString()}
            </div>
          </div>

          <div className="source-evidence">
            {source.evidence.length === 0 ? (
              <p className="muted small">
                No discrete evidence items were recorded for this source; it was
                still included in the citation index used during synthesis.
              </p>
            ) : (
              source.evidence.map((item) => (
                <div
                  className="evidence-item"
                  key={item.id}
                  data-testid="evidence-item"
                >
                  <div className="evidence-claim">{item.claim}</div>
                  {item.excerpt && (
                    <div className="evidence-excerpt">&quot;{item.excerpt}&quot;</div>
                  )}
                  {item.locator && (
                    <div className="evidence-locator">
                      Location: {item.locator}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          <div>
            {source.url && (
              <a
                href={source.url}
                target="_blank"
                rel="noreferrer"
                className="btn btn-outline"
                data-testid="open-source"
              >
                Open source in new tab
              </a>
            )}
          </div>
        </div>
      </aside>
    </>,
    document.body,
  );
}

