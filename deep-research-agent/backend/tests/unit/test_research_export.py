"""Unit tests for the Markdown report export (Phase C polish)."""

from __future__ import annotations

from app.research.export import build_markdown, export_filename, parse_report_json

REPORT = {
    "title": "Electric vs Hydrogen Trucks",
    "summary": "A comparative summary.",
    "sections": [
        {
            "heading": "Safety",
            "content": "Electric trucks score higher on crash tests.",
            "citation_source_ids": ["s1", "s2"],
        },
        {
            "heading": "Cost",
            "content": "Hydrogen fuel is pricier per km.",
            "citation_source_ids": ["s2", "missing"],
        },
    ],
    "conclusion": "Electric wins today.",
}

SOURCES = [
    {
        "id": "s1",
        "title": "Crash Test Digest",
        "url": "https://crash.test/digest",
        "domain": "crash.test",
        "source_type": "web",
        "document_id": None,
        "document_name": None,
        "evidence": [
            {"claim": "EVs score 5-star.", "excerpt": "five stars", "locator": "p1"}
        ],
    },
    {
        "id": "s2",
        "title": "Fleet Cost Model",
        "url": None,
        "domain": None,
        "source_type": "document",
        "document_id": "doc-9",
        "document_name": "fleet_costs.pdf",
        "evidence": [
            {"claim": "H2 costs 2x per km.", "excerpt": "", "locator": "page 4"}
        ],
    },
]


def test_parse_report_json_roundtrip_and_garbage() -> None:
    assert parse_report_json('{"title": "T"}') == {"title": "T"}
    assert parse_report_json("{not json") is None
    assert parse_report_json(None) is None
    assert parse_report_json('["list"]') is None


def test_build_markdown_includes_full_detail() -> None:
    markdown = build_markdown("Compare trucks", REPORT, SOURCES)

    assert markdown.startswith("# Electric vs Hydrogen Trucks")
    assert "**Query:** Compare trucks" in markdown
    assert "## Safety" in markdown
    assert "Electric trucks score higher on crash tests." in markdown
    assert "Sources: [1] [2]" in markdown
    assert "## Conclusion" in markdown
    assert "Electric wins today." in markdown


def test_build_markdown_sources_section_is_detailed() -> None:
    markdown = build_markdown("q", REPORT, SOURCES)

    # Web source: title, domain, URL.
    assert "1. **Crash Test Digest** — crash.test" in markdown
    assert "<https://crash.test/digest>" in markdown
    # Document source: labelled as uploaded document with its filename.
    assert "2. **Fleet Cost Model** (uploaded document: fleet_costs.pdf)" in markdown
    # Evidence: claim + excerpt + locator.
    assert "- EVs score 5-star. — \u201cfive stars\u201d (p1)" in markdown
    assert "- H2 costs 2x per km. (page 4)" in markdown


def test_build_markdown_ignores_citations_without_sources() -> None:
    markdown = build_markdown("q", REPORT, SOURCES)
    # "missing" has no matching source; must not appear as a numbered citation.
    assert "[3]" not in markdown


def test_build_markdown_handles_empty_sources() -> None:
    markdown = build_markdown("q", REPORT, [])
    assert "No sources were captured" in markdown
    assert "Sources: [1]" not in markdown


def test_export_filename_is_short_and_extensioned() -> None:
    name = export_filename("0c2f4e6a-8b1d-4c3e-9f2a-1234567890ab", "md")
    assert name == "research-report-0c2f4e6a.md"
