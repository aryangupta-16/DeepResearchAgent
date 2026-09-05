"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ResearchDocument } from "@/lib/types/documents";
import {
  documentDownloadUrl,
  listDocuments,
} from "@/lib/api/documents";

const POLL_INTERVAL_MS = 2500;

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function StatusBadge({ status }: { status: ResearchDocument["status"] }) {
  const map: Record<string, { label: string; className: string }> = {
    pending: { label: "Queued…", className: "badge badge-pending" },
    processing: {
      label: "Processing document...",
      className: "badge badge-processing",
    },
    ready: { label: "✓ Ready", className: "badge badge-ready" },
    failed: { label: "✕ Failed", className: "badge badge-failed" },
  };
  const view = map[status] ?? map.pending;
  return (
    <span
      className={view.className}
      data-testid="document-status"
      data-status={status}
    >
      {view.label}
    </span>
  );
}

/**
 * Documents panel on the home page.
 *
 * V1 responsibilities:
 * - list uploaded documents with persisted status (pending/processing/ready/failed)
 * - upload a PDF (multipart) -> 202 -> poll status every ~2.5s until terminal
 * - stop polling at ready/failed; never fake progress or percentages
 */
export default function DocumentPanel() {
  const [documents, setDocuments] = useState<ResearchDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Interval survives re-renders; cleared on unmount and when nothing is active.
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(() => {
      void (async () => {
        try {
          const response = await listDocuments();
          setDocuments(response.documents);
          const hasActive = response.documents.some(
            (doc) => doc.status === "pending" || doc.status === "processing",
          );
          if (!hasActive) stopPolling();
        } catch {
          // transient errors keep polling; a later tick may recover
        }
      })();
    }, POLL_INTERVAL_MS);
  }, [stopPolling]);

  const refresh = useCallback(async () => {
    try {
      const response = await listDocuments();
      setDocuments(response.documents);
      const hasActive = response.documents.some(
        (doc) => doc.status === "pending" || doc.status === "processing",
      );
      if (hasActive) startPolling();
      else stopPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load documents");
    }
  }, [startPolling, stopPolling]);

  useEffect(() => {
    void refresh();
    return () => stopPolling();
  }, [refresh, stopPolling]);

  async function handleUpload(file: File) {
    setError(null);
    setUploading(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const apiUrl =
        process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
      const response = await fetch(`${apiUrl}/documents`, {
        method: "POST",
        body,
      });
      if (!response.ok) {
        const detail = await response.text().catch(() => "");
        throw new Error(
          detail
            ? `Upload failed (${response.status}): ${detail}`
            : `Upload failed (${response.status})`,
        );
      }
      await refresh(); // shows up as pending/processing immediately
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  return (
    <section className="card" data-testid="documents-panel">
      <h2>Documents</h2>
      <p className="muted small">
        Upload PDFs to ground research in your own material.
      </p>

            <div className="doc-upload-actions">
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf,.pdf"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void handleUpload(file);
          }}
          disabled={uploading}
          data-testid="document-input"
        />
        {uploading && (
          <span className="muted small" data-testid="uploading-indicator">
            Uploading…
          </span>
        )}
      </div>

      {error && (
        <p className="error" role="alert" data-testid="documents-error">
          {error}
        </p>
      )}

      {documents.length > 0 && (
        <ul className="document-list" data-testid="document-list">
          {documents.map((doc) => (
            <li key={doc.id} className="document-row" data-testid="document-row">
              <div className="document-info">
                <a
                  href={documentDownloadUrl(doc.id)}
                  target="_blank"
                  rel="noreferrer"
                  className="document-name"
                >
                  {doc.filename}
                </a>
                <span className="muted small"> · {formatSize(doc.size)}</span>
              </div>
              <StatusBadge status={doc.status} />
              {doc.status === "failed" && doc.error && (
                <span className="muted small" title={doc.error}>
                  — {doc.error}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}