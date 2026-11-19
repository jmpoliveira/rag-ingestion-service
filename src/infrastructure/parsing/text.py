"""Plain text and Markdown: decoded as UTF-8, one page."""

from __future__ import annotations

from src.domain.documents import Page, ParsedDocument, SourceDocument
from src.domain.errors import DocumentRejectedError


class TextParser:
    @property
    def media_types(self) -> frozenset[str]:
        return frozenset({"text/plain", "text/markdown"})

    async def parse(self, document: SourceDocument, data: bytes) -> ParsedDocument:
        try:
            # utf-8-sig also accepts (and drops) the byte-order mark some editors write.
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as err:
            raise DocumentRejectedError("Text document is not valid UTF-8") from err
        return ParsedDocument(document, (Page(1, text),))
