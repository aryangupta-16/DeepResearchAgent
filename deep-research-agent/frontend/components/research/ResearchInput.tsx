"use client";

import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api/errors";
import { listDocuments } from "@/lib/api/documents";
import type { ResearchDocument } from "@/lib/types/documents";

export interface ResearchInputProps {
  /** Receives the raw (untrimmed) query; resolves on success. */
  onSubmit: (query: string, documentIds: string[]) => Promise<void>;
  /**
   * When provided, ready documents are listed and selectable for hybrid
   * (web + document) research. Omitted => web-only form, as before.
   */
  loadDocuments?: () => Promise<ResearchDocument[]>;
  /** Optional seed value for controlled re-use (e.g. prefilled draft). */
  initialQuery?: string;
  /** Optional example prompts; clicking one fills the query field. */
  examples?: string[];
}

const MAX_LENGTH = 1000;

/** Self-contained research query form with client-side + submit-error feedback. */
export default function ResearchInput({
  onSubmit,
  loadDocuments,
  initialQuery = "",
  examples,
}: ResearchInputProps) {
  const [query, setQuery] = useState(initialQuery);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [documents, setDocuments] = useState<ResearchDocument[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Optional hybrid mode: offer ready documents for retrieval.
  useEffect(() => {
    if (!loadDocuments) return;
    let cancelled = false;
    void loadDocuments()
      .then((docs) => {
        if (!cancelled)
          setDocuments(docs.filter((doc) => doc.status === "ready"));
      })
      .catch(() => {
        /* documents are optional; never block the research form */
      });
    return () => {
      cancelled = true;
    };
  }, [loadDocuments]);

  function toggleDocument(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const trimmed = query.trim();
  const canSubmit = trimmed.length > 0 && !isSubmitting;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await onSubmit(trimmed, Array.from(selected));
    } catch (err) {
      const apiErr = err as ApiError;
      if (apiErr?.status === 422) {
        setError("Your query must be between 1 and 1,000 characters.");
      } else {
        setError(
          apiErr?.message ||
            "We could not reach the research backend. Is it running?",
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  const remaining = MAX_LENGTH - query.length;

  return (
    <form
      onSubmit={handleSubmit}
      className="card research-form"
      data-testid="research-form"
    >
      <label className="label" htmlFor="research-query">
        Research query
      </label>
      <textarea
        id="research-query"
        className="input textarea"
        rows={4}
        maxLength={MAX_LENGTH}
        placeholder="e.g. Compare the safety of electric vs hydrogen fuel cell trucks"
        value={query}
        onChange={(e) => setQuery(e.target.value.slice(0, MAX_LENGTH))}
        disabled={isSubmitting}
        aria-invalid={!!error}
        aria-describedby={error ? "query-error" : "query-hint"}
      />
      <p id="query-hint" className="form-hint">
        {trimmed.length === 0
          ? "Describe the question in as much detail as you can."
          : `${remaining} characters remaining`}
      </p>
      {error && (
        <p
          id="query-error"
          className="form-error"
          role="alert"
          data-testid="query-error"
        >
          {error}
        </p>
      )}

      {examples && examples.length > 0 && !isSubmitting && (
        <div className="example-row" data-testid="examples">
          <span className="form-hint">Try:</span>
          {examples.map((example) => (
            <button
              type="button"
              key={example}
              className="example-chip"
              onClick={() => setQuery(example)}
            >
              {example}
            </button>
          ))}
        </div>
      )}

      {loadDocuments && documents.length > 0 && (
        <fieldset
          className="fieldset-docs"
          data-testid="document-selection"
        >
                    <legend className="label fieldset-legend">
            Use uploaded documents
          </legend>
          {documents.map((doc) => (
            <label
              key={doc.id}
              className="doc-option"
              data-testid={`document-option-label-${doc.id}`}
            >
              <input
                type="checkbox"
                checked={selected.has(doc.id)}
                onChange={() => toggleDocument(doc.id)}
                disabled={isSubmitting}
                aria-label={`Use ${doc.filename}`}
                data-testid={`document-option-${doc.id}`}
              />
              <span className="doc-option-name">{doc.filename}</span>
            </label>
          ))}
        </fieldset>
      )}

      <button
        type="submit"
        className="btn btn-primary btn-lg"
        disabled={!canSubmit}
        aria-busy={isSubmitting}
        data-testid="submit-research"
      >
        {isSubmitting && <span className="spinner" />}
        {isSubmitting ? "Starting research…" : "Start research"}
      </button>
    </form>
  );
}
