"""Unit tests for the document/RAG domain (Phase 8).

Covers: filename sanitization, storage keys, document status transitions,
deterministic chunking, and the normalized parser. PostgreSQL-backed behaviour
lives in the integration suite.
"""

from __future__ import annotations

import pytest

from app.common.exceptions import ValidationError
from app.documents.enums import (
    DocumentStatus,
    SourceType,
    validate_document_status_transition,
)
from app.documents.service import sanitize_filename, storage_key_for
from app.tools.documents.parser import ParsedPage

# ---- Filename / storage-key safety ----


def test_sanitize_filename_strips_paths_and_bad_chars() -> None:
    assert sanitize_filename("annual report.pdf") == "annual report.pdf"
    assert sanitize_filename("/abs/path/file.PDF") == "file.PDF"
    sanitized = sanitize_filename("../../etc/passwd")
    assert "/" not in sanitized
    assert sanitize_filename("") == "upload"


def test_storage_key_is_scoped_by_document_id() -> None:
    from uuid import uuid4

    key = storage_key_for(uuid4(), "../escape.pdf")
    bucketless = key.split("/", 1)[1]
    assert bucketless == "escape.pdf"
    assert not key.startswith("/")


# ---- Status lifecycle ----


def test_document_happy_path_transitions() -> None:
    validate_document_status_transition(
        DocumentStatus.PENDING, DocumentStatus.PROCESSING
    )
    validate_document_status_transition(DocumentStatus.PROCESSING, DocumentStatus.READY)


def test_terminal_statuses_are_enforced() -> None:
    for terminal in (DocumentStatus.READY, DocumentStatus.FAILED):
        with pytest.raises(ValidationError):
            validate_document_status_transition(terminal, DocumentStatus.PROCESSING)
    # FAILED may only be re-opened explicitly for reprocessing.
    validate_document_status_transition(DocumentStatus.FAILED, DocumentStatus.PENDING)
    with pytest.raises(ValidationError):
        validate_document_status_transition(DocumentStatus.PENDING, DocumentStatus.READY)


def test_source_type_enum() -> None:
    assert {SourceType.WEB.value, SourceType.DOCUMENT.value} == {"web", "document"}


# ---- Chunking ----


def _page(number: int, text: str) -> ParsedPage:
    return ParsedPage(page_number=number, text=text)


def test_chunking_is_deterministic_and_size_bounded() -> None:
    from app.rag.chunking import chunk_pages

    text = "\n\n".join(
        f"Paragraph {i} " + "word " * 30 for i in range(12)
    )
    pages = [_page(1, text)]
    first = chunk_pages(pages, chunk_size=600, overlap=100)
    second = chunk_pages(pages, chunk_size=600, overlap=100)

    assert [c.content for c in first] == [c.content for c in second]
    assert all(len(c.content) <= 600 + 200 for c in first)  # packing slack
    assert [c.chunk_index for c in first] == list(range(len(first)))


def test_chunking_preserves_page_numbers() -> None:
    from app.rag.chunking import chunk_pages

    pages = [
        _page(1, "Alpha paragraph.\n\nBeta paragraph."),
        _page(2, "Gamma paragraph."),
    ]
    drafts = chunk_pages(pages, chunk_size=400)
    assert drafts[0].page_number == 1
    page_two = [d for d in drafts if "Gamma" in d.content]
    assert page_two and page_two[0].page_number == 2


def test_chunking_rejects_bad_configuration() -> None:
    from app.rag.chunking import chunk_pages

    with pytest.raises(ValueError):
        chunk_pages([_page(1, "x")], chunk_size=0)
    with pytest.raises(ValueError):
        chunk_pages([_page(1, "x")], chunk_size=100, overlap=100)


# ---- Parser (PDF via a minimal hand-built document) ----


def _minimal_pdf(page_texts: list[str]) -> bytes:
    """Build a tiny but valid multi-page PDF with correct xref offsets.

    Layout: 1=Catalog, 2=Pages, then per page i (0-based):
    page obj 3+2i, content stream obj 4+2i. Last object = font.
    """
    n_pages = len(page_texts)
    font_id = 3 + 2 * n_pages

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{3 + 2 * i} 0 R' for i in range(n_pages))}] "
        f"/Count {n_pages} >>".encode(),
    ]
    for index, text in enumerate(page_texts):
        escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /Contents {4 + 2 * index} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF"
    ).encode()
    return bytes(out)


def test_parse_pdf_extracts_per_page_text() -> None:
    from app.tools.documents.parser import parse_document

    data = _minimal_pdf(["Revenue grew eighteen percent.", "Outlook for 2026."])
    parsed = parse_document(
        data, content_type="application/pdf", filename="report.pdf"
    )
    assert parsed.content_type == "application/pdf"
    assert [p.page_number for p in parsed.pages] == [1, 2]
    assert "eighteen percent" in parsed.pages[0].text
    assert "2026" in parsed.pages[1].text


def test_parse_text_documents() -> None:
    from app.tools.documents.parser import parse_document

    parsed = parse_document(
        b"Hello document.", content_type="text/plain", filename="notes.txt"
    )
    assert parsed.pages[0].page_number == 1
    assert parsed.text == "Hello document."


def test_unsupported_format_is_rejected_clearly() -> None:
    from app.tools.documents.parser import parse_document

    with pytest.raises(ValidationError, match="Supported formats"):
        parse_document(b"<html/>", content_type="text/html", filename="x.html")


# ---- Embedding factory ----


def test_embedding_factory_disabled_without_provider(monkeypatch) -> None:
    from app.config.settings import Settings
    from app.rag.embeddings import build_embedding_provider

    settings = Settings(_env_file=None, embedding_provider="")
    monkeypatch.setattr(
        "app.config.settings.get_settings", lambda: settings
    )
    assert build_embedding_provider() is None


def test_openai_embedding_provider_constructs_batched(monkeypatch) -> None:
    from app.config.settings import Settings
    from app.rag.embeddings import build_embedding_provider

    settings = Settings(
        _env_file=None,
        embedding_provider="openai",
        openai_api_key="test-key-not-real",
        embedding_model="text-embedding-3-small",
        document_embedding_batch_size=32,
    )
    monkeypatch.setattr(
        "app.config.settings.get_settings", lambda: settings
    )
    provider = build_embedding_provider()
    assert provider is not None
    assert provider.name == "openai"
    assert provider.model == "text-embedding-3-small"