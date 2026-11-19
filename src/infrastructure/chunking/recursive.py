"""Chunking with LangChain's ``RecursiveCharacterTextSplitter``, page by page.

Chunks never cross a page boundary, so every chunk has exactly one page to cite. The price:
a sentence split across two pages ends up in two chunks. For documents without pages
(Markdown, text) the whole document is one page.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.domain.documents import ParsedDocument, TextSpan


class RecursiveChunker:
    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be at least 1")
        if not 0 <= chunk_overlap < chunk_size:
            raise ValueError("chunk_overlap must be at least 0 and smaller than chunk_size")
        self._size = chunk_size
        self._overlap = chunk_overlap
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, add_start_index=True
        )

    @property
    def fingerprint(self) -> str:
        return f"recursive:{self._size}:{self._overlap}"

    def split(self, document: ParsedDocument) -> Sequence[TextSpan]:
        spans: list[TextSpan] = []
        for page in document.pages:
            if not page.text.strip():
                continue
            for piece in self._splitter.create_documents([page.text]):
                start = piece.metadata.get("start_index", -1)
                spans.append(
                    TextSpan(
                        page.number, start if isinstance(start, int) else -1, piece.page_content
                    )
                )
        return spans
