from __future__ import annotations

import pytest

from src.domain.documents import Page, ParsedDocument, SourceDocument
from src.infrastructure.chunking.recursive import RecursiveChunker

SOURCE = SourceDocument("a.pdf", "application/pdf", "h", 1)


def test_chunks_respect_the_size_and_never_cross_pages():
    # Arrange
    long_page = " ".join(f"word{i}" for i in range(200))
    document = ParsedDocument(SOURCE, (Page(1, long_page), Page(2, ""), Page(3, "short page")))

    # Act
    spans = RecursiveChunker(chunk_size=100, chunk_overlap=20).split(document)

    # Assert
    assert all(len(span.text) <= 100 for span in spans)
    assert {span.page for span in spans} == {1, 3}
    assert spans[-1].text == "short page"
    assert spans[0].start_index == 0
    assert long_page[spans[1].start_index :].startswith(spans[1].text)


def test_empty_document_gives_no_chunks():
    document = ParsedDocument(SOURCE, (Page(1, "   "),))
    assert RecursiveChunker(chunk_size=100, chunk_overlap=0).split(document) == []


def test_fingerprint_names_the_settings():
    assert RecursiveChunker(chunk_size=500, chunk_overlap=50).fingerprint == "recursive:500:50"


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (100, 100), (100, -1)])
def test_invalid_settings_are_rejected(size: int, overlap: int):
    with pytest.raises(ValueError, match="chunk_"):
        RecursiveChunker(chunk_size=size, chunk_overlap=overlap)
