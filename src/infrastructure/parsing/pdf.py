"""PDF text extraction with pypdf.

PDF parsing runs on hostile input: pypdf can raise many exception types on malformed
files, and a crafted file can try to exhaust memory. The parser runs in a worker thread
(it is CPU-bound and would block the event loop), refuses encrypted files it cannot open
with an empty password, caps the number of pages, and turns every parsing failure into a
``DocumentRejectedError`` so one bad file never stops a sync.
"""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO

from pypdf import PasswordType, PdfReader
from pypdf.errors import PyPdfError

from src.domain.documents import Page, ParsedDocument, SourceDocument
from src.domain.errors import DocumentRejectedError

logger = logging.getLogger(__name__)

# pypdf's own errors, plus what it is known to raise on malformed structures.
_PARSE_ERRORS = (
    PyPdfError,
    ValueError,
    KeyError,
    TypeError,
    IndexError,
    AttributeError,
    RecursionError,
)


class PdfParser:
    def __init__(self, *, max_pages: int) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        self._max_pages = max_pages

    @property
    def media_types(self) -> frozenset[str]:
        return frozenset({"application/pdf"})

    async def parse(self, document: SourceDocument, data: bytes) -> ParsedDocument:
        return await asyncio.to_thread(self._parse, document, data)

    def _parse(self, document: SourceDocument, data: bytes) -> ParsedDocument:
        try:
            reader = PdfReader(BytesIO(data))
            # Many PDFs are "encrypted" only to set permissions, with an empty password.
            if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
                raise DocumentRejectedError("PDF is password protected")
            count = len(reader.pages)
            if count > self._max_pages:
                raise DocumentRejectedError(
                    f"PDF has {count} pages, over the limit of {self._max_pages}"
                )
            pages = tuple(
                Page(number, page.extract_text() or "")
                for number, page in enumerate(reader.pages, start=1)
            )
        except DocumentRejectedError:
            raise
        except _PARSE_ERRORS as err:
            logger.warning(
                "PDF parsing failed",
                extra={"document_id": document.document_id, "error": type(err).__name__},
            )
            raise DocumentRejectedError("PDF could not be parsed") from err
        return ParsedDocument(document, pages)
