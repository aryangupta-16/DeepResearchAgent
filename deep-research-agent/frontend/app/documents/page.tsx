"use client";

/**
 * Documents page (Phase 8): upload PDFs and watch async processing.
 * Honest progress only — statuses come from the backend, no fake percentages.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, FileText, Trash2, UploadCloud } from "lucide-react";
import {
  deleteDocument,
  documentDownloadUrl,
  getDocument,
  listDocuments,
  uploadDocument,
} from "@/lib/api/documents";
import type { ResearchDocument } from "@/lib/types/documents";

const POLL_MS = 2500;
const MAX_SIZE_MB = 25;
const TERMINAL = new Set(["ready", "failed"]);

function statusLabel(doc: ResearchDocument): string {
  switch (doc.status) {
    case "pending":
      return "Queued…";
    case "processing":
      return "Processing document…";
    case "ready":
      return "Ready";
    case "failed":
      return "Failed";
    default:
      return doc.status;
  }
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<ResearchDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await listDocuments();
      setDocuments(data.documents);
      setError(null);
    } catch {
      setError("Could not reach the API. Is the backend running?");
    }
  }, []);

  // Poll while any document is still processing; stop at terminal states.
  useEffect(() => {
    refresh(); // initial load
  }, [refresh]);

  useEffect(() => {
    if (!documents.some((d) => !TERMINAL.has(d.status))) return;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [documents, refresh]);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragActive(false);
      const file = e.dataTransfer.files?.[0];
      if (file) void handleUpload(file);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  async function handleUpload(file: File) {
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      setError(`File exceeds the ${MAX_SIZE_MB} MB upload limit.`);
      return;
    }
    setUploading(true);
    setError(null);
    try {
      await uploadDocument(file);
      await refresh();
    } catch (err) {
      setError(
        err instanceof Error && err.message
          ? `Upload failed: ${err.message}`
          : "Upload failed.",
      );
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  /** Two-step confirm, then hard delete. 409 (processing) surfaces a message. */
  async function handleDelete(doc: ResearchDocument) {
    if (confirmId !== doc.id) {
      setConfirmId(doc.id);
      // Auto-cancel the confirmation after a few seconds of inactivity.
      setTimeout(() => {
        setConfirmId((current) => (current === doc.id ? null : current));
      }, 4000);
      return;
    }
    setConfirmId(null);
    setDeletingId(doc.id);
    setError(null);
    try {
      await deleteDocument(doc.id);
      setDocuments((docs) => docs.filter((d) => d.id !== doc.id));
    } catch (err) {
      setError(
        err instanceof Error && err.message
          ? `Delete failed: ${err.message}`
          : "Delete failed.",
      );
      await refresh();
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="page-narrow">
      <header className="page-head-block">
        <h1 className="page-title">Documents</h1>
        <p className="page-sub">
          Upload PDFs to use as evidence alongside web research. Parsing,
          chunking, and embedding run asynchronously on the worker.
        </p>
      </header>

      <div
        className={`upload-zone${dragActive ? " upload-zone-active" : ""}`}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        data-testid="upload-zone"
        data-active={dragActive || undefined}
      >
        <input
          ref={inputRef}
          id="document-file"
          type="file"
          accept="application/pdf,.pdf"
          disabled={uploading}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleUpload(file);
          }}
          className="upload-input"
          data-testid="document-input"
          aria-label="Upload a PDF document"
        />
        <UploadCloud className="upload-icon" aria-hidden />
        <p className="upload-primary">
          {uploading ? "Uploading…" : "Drag & drop a PDF here"}
        </p>
        <p className="upload-secondary">
          or{" "}
          <label htmlFor="document-file" className="upload-browse">
            browse files
          </label>{" "}
          · PDF only, up to {MAX_SIZE_MB} MB
        </p>
        {error && (
          <p className="upload-error" role="alert" data-testid="documents-error">
            {error}
          </p>
        )}
      </div>

      <section className="doc-section" data-testid="document-list">
        <h2 className="doc-section-title">Your library</h2>
        {documents.length === 0 ? (
          <div className="empty-state">
            <FileText className="empty-icon" aria-hidden />
            <p>No documents yet. Upload a PDF to get started.</p>
          </div>
        ) : (
          <div className="doc-list">
            {documents.map((doc) => (
              <article
                key={doc.id}
                className="card doc-row"
                data-testid={`document-item-${doc.id}`}
              >
                <span className="doc-icon" aria-hidden>
                  <FileText size={18} />
                </span>
                <div className="doc-info">
                  <div className="doc-name">{doc.filename}</div>
                  <div className="doc-meta">
                    <span>{formatSize(doc.size)}</span>
                    <span>·</span>
                    <span>uploaded {formatDate(doc.created_at)}</span>
                  </div>
                  {doc.error && (
                    <div className="doc-error" role="alert">
                      {doc.error}
                    </div>
                  )}
                </div>
                <span
                  className={`badge badge-${doc.status}`}
                  data-status={doc.status}
                  data-testid={`document-status-${doc.id}`}
                >
                  <span className="badge-dot" aria-hidden />
                  {statusLabel(doc)}
                </span>
                {doc.status === "ready" && (
                  <a
                    href={documentDownloadUrl(doc.id)}
                    target="_blank"
                    rel="noreferrer"
                    className="btn btn-ghost btn-sm"
                    aria-label={`Open ${doc.filename}`}
                  >
                    <ExternalLink size={14} aria-hidden />
                    Open
                  </a>
                )}
                {doc.status !== "processing" && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm doc-delete"
                    disabled={deletingId === doc.id}
                    onClick={() => void handleDelete(doc)}
                    aria-label={`Delete ${doc.filename}`}
                    data-testid={`document-delete-${doc.id}`}
                  >
                    <Trash2 size={14} aria-hidden />
                    {confirmId === doc.id ? "Confirm?" : "Delete"}
                  </button>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
