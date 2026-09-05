"""Document parsing: normalize uploaded files into pages of plain text.

This is the only module that knows about PDF libraries. Everything downstream
(chunking, embedding, retrieval, evidence) works with the normalized
:class:`ParsedPage` representation, so a future parser swap cannot leak
PDF-specific objects through the application.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from app.common.exceptions import ValidationError


@dataclass(frozen=True)
class ParsedPage:
    """One normalized page of parsed content (1-based page numbers)."""

    page_number: int
    text: str


@dataclass(frozen=True)
class ParsedDocument:
    """Normalized parse result for one uploaded document."""

    pages: list[ParsedPage] = field(default_factory=list)
    content_type: str = ""

    @property
    def text(self) -> str:
        """Full concatenated text (used for hashing/preview, not for chunking)."""
        return "\n\n".join(page.text for page in self.pages)


#: Content types V1 can parse. Anything else is rejected with a clear error.
SUPPORTED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "text/plain": "text",
    "text/markdown": "text",
}

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}


def detect_kind(*, content_type: str, filename: str) -> str:
    """Map declared content type / filename to an internal parser kind."""
    kind = SUPPORTED_CONTENT_TYPES.get((content_type or "").split(";")[0].strip())
    if kind:
        return kind
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith((".txt", ".md")):
        return "text"
    raise ValidationError(
        f"Unsupported document type {content_type!r} for {filename!r}. "
        "Supported formats: PDF, TXT, Markdown."
    )


def parse_document(data: bytes, *, content_type: str, filename: str) -> ParsedDocument:
    """Parse raw upload bytes into normalized pages.

    Raises:
        ValidationError: when the format is unsupported or the payload is not a
            valid document of that type.
    """
    if not data:
        raise ValidationError("Uploaded document is empty.")

    kind = detect_kind(content_type=content_type, filename=filename)
    if kind == "pdf":
        return _parse_pdf(data)
    return _parse_text(data)


def _parse_pdf(data: bytes) -> ParsedDocument:
    try:
        from pypdf import PdfReader  # local import: only needed for PDFs
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ValidationError("PDF support is not installed.") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
        pages: list[ParsedPage] = []
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(ParsedPage(page_number=index, text=text))
    except Exception as exc:
        raise ValidationError(f"Could not parse PDF: {exc}") from exc

    if not pages:
        raise ValidationError(
            "The PDF contains no extractable text (scanned/image-only PDFs are "
            "not supported yet)."
        )
    return ParsedDocument(pages=pages, content_type="application/pdf")


def _parse_text(data: bytes) -> ParsedDocument:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("Text documents must be UTF-8 encoded.") from exc
    text = text.strip()
    if not text:
        raise ValidationError("Uploaded document is empty.")
    # A text file has no native pagination; treat it as one logical page so
    # citations still carry a stable locator.
    return ParsedDocument(pages=[ParsedPage(page_number=1, text=text)], content_type="text/plain")