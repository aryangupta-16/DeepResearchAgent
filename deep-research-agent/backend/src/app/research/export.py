"""Report export (Phase C polish): render a completed research report as a
downloadable Markdown document.

The export is deliberately *detailed* — everything the interactive report
shows on screen is included: title, summary, every section with its cited
sources, the conclusion, and the full source list with each evidence item
(claim, excerpt, locator). Markdown is the V1 format: zero dependencies,
diff-able, and trivially convertible to PDF/DOCX later (deferred by design).

Builders take plain data (parsed report dict + source dicts) so they are
trivially unit-testable without a database.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def parse_report_json(raw: str | None) -> dict[str, Any] | None:
    """Decode the report JSON stored on a completed job; ``None`` if absent/bad."""
    if not raw:
        return None
    try:
        report = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Stored report JSON is malformed; export unavailable.")
        return None
    return report if isinstance(report, dict) else None


def _source_line(number: int, source: dict[str, Any]) -> str:
    title = source.get("title") or "Untitled source"
    if source.get("source_type") == "document" or not source.get("url"):
        document_note = "uploaded document"
        if source.get("document_name"):
            document_note += f": {source['document_name']}"
        return f"{number}. **{title}** ({document_note})"
    domain = source.get("domain")
    suffix = f" — {domain}" if domain else ""
    return f"{number}. **{title}**{suffix}  \n   <{source['url']}>"


def _evidence_lines(source: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in source.get("evidence") or []:
        claim = (item.get("claim") or "").strip()
        if not claim:
            continue
        line = f"   - {claim}"
        excerpt = (item.get("excerpt") or "").strip()
        if excerpt and excerpt != claim:
            line += f" \u2014 \u201c{excerpt}\u201d"
        locator = item.get("locator")
        if locator:
            line += f" ({locator})"
        lines.append(line)
    return lines


def build_markdown(
    query: str,
    report: dict[str, Any],
    sources: list[dict[str, Any]],
) -> str:
    """Render the full report (with cited sources + evidence) as Markdown."""
    # Global source numbering in first-cited order (matches the UI's chips).
    citation_order: list[str] = []
    seen: set[str] = set()
    for section in report.get("sections") or []:
        for source_id in section.get("citation_source_ids") or []:
            if source_id and source_id not in seen:
                seen.add(source_id)
                citation_order.append(source_id)
    source_ids = {str(source.get("id")) for source in sources}
    number_of = {
        source_id: i + 1
        for i, source_id in enumerate(citation_order)
        if source_id in source_ids
    }

    lines: list[str] = [f"# {report.get('title') or 'Research report'}", ""]
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines += [f"_Generated {generated}_", ""]
    if query:
        lines += [f"**Query:** {query}", ""]
    if report.get("summary"):
        lines += [report["summary"].strip(), ""]

    for section in report.get("sections") or []:
        heading = (section.get("heading") or "").strip() or "Section"
        lines += [f"## {heading}", ""]
        content = (section.get("content") or "").strip()
        if content:
            lines += [content, ""]
        cited = [
            f"[{number_of[sid]}]" for sid in section.get("citation_source_ids") or []
            if sid in number_of
        ]
        if cited:
            lines += [f"Sources: {' '.join(cited)}", ""]

    if report.get("conclusion"):
        lines += ["## Conclusion", "", report["conclusion"].strip(), ""]

    lines += ["## Sources", ""]
    if not sources:
        lines += ["_No sources were captured for this report._", ""]
    else:
        for index, source in enumerate(sources, start=1):
            lines += [_source_line(index, source)]
            evidence_lines = _evidence_lines(source)
            if evidence_lines:
                lines += ["", "   **Evidence:**"]
                lines += evidence_lines
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def export_filename(research_id: str, extension: str) -> str:
    """Attachment filename for an exported report."""
    short = research_id.replace("-", "")[:8]
    return f"research-report-{short}.{extension}"