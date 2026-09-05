"""Minimal, dependency-free HTML → readable-text extraction.

Not a perfect crawler: we strip ``script``/``style``/``noscript`` elements and
collapse whitespace, keeping paragraphs readable. Usable research content is the
goal, not browser-level rendering.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_SKIP_TAGS = {"script", "style", "noscript", "head", "iframe", "svg", "template"}
_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "section",
    "article",
    "blockquote",
    "tr",
    "td",
    "ul",
    "ol",
    "header",
    "footer",
}

_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
_LINEBREAK_RE = re.compile(r"\n{3,}")


class _TextExtractor(HTMLParser):
    """Collects title + readable text, skipping non-content elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str = ""
        self._in_skip = 0
        self._in_title = False
        self._parts: list[str] = []
        self._last_was_block = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._in_skip += 1
        if tag == "title":
            self._in_title = True
        if tag in _BLOCK_TAGS and not self._in_skip:
            self._newline()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._in_skip:
            self._in_skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS and not self._in_skip:
            self._newline()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            # The title lives inside <head>, which is otherwise skipped — capture
            # it before the skip guard so page titles are never lost.
            self.title = (self.title + " " + data).strip()
            return
        if self._in_skip:
            return
        text = _WHITESPACE_RE.sub(" ", data).strip()
        if not text:
            return
        if self._last_was_block and self._parts:
            self._parts.append(" ")
        self._parts.append(text)
        self._last_was_block = False

    def _newline(self) -> None:
        if self._parts:
            self._parts.append("\n")
            self._last_was_block = True

    def text(self) -> str:
        raw = "".join(self._parts)
        # Join lines that are single words within a line and collapse blank runs.
        lines = [line.strip() for line in raw.splitlines()]
        return _LINEBREAK_RE.sub("\n\n", "\n".join(lines)).strip()


class HtmlExtractor:
    """Extracts readable text (and the ``<title>``) from an HTML document."""

    def extract(self, html: str) -> tuple[str, str]:
        """Return ``(title, text)`` for the given HTML string."""
        parser = _TextExtractor()
        try:
            parser.feed(html)
            parser.close()
        except Exception:  # pragma: no cover - malformed HTML must never crash tools
            return "", ""
        return parser.title, parser.text()


def extract_readable_text(html: str) -> str:
    """Convenience: readable text only."""
    return HtmlExtractor().extract(html)[1]