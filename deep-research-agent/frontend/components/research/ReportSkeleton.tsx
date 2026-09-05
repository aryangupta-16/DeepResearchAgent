"use client";

/** A card skeleton with shimmer blocks + spinner, for report loading states. */
export default function ReportSkeleton({
  message = "Loading report…",
}: { message?: string }) {
  return (
    <section className="card skeleton" data-testid="skeleton" aria-busy="true">
      <div className="skeleton-header">
        <span className="spinner spinner-md" />
        <p className="muted skeleton-message">{message}</p>
      </div>
      <div className="shimmer shimmer-title" />
      <div className="shimmer" />
      <div className="shimmer shimmer-wide" />
      <div className="shimmer shimmer-wider" />
      <div className="shimmer shimmer-short" />
      <div className="shimmer shimmer-content" />
    </section>
  );
}
