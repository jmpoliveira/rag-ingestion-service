"""What flows through the pipeline: source documents, parsed pages, chunks and vectors."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """A reference to one document in a source, before its content is read.

    ``document_id`` is stable for the life of the document in its source (for a folder, the
    path relative to the folder). It keys every chunk in the index, so re-ingesting the same
    document replaces its chunks instead of duplicating them. ``content_hash`` (SHA-256 of
    the bytes) tells whether the content changed since the last ingestion.
    """

    document_id: str
    media_type: str
    content_hash: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class Page:
    """Text of one page (1-based). Formats without pages have a single page 1."""

    number: int
    text: str


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    source: SourceDocument
    pages: tuple[Page, ...]

    @property
    def has_text(self) -> bool:
        return any(page.text.strip() for page in self.pages)


@dataclass(frozen=True, slots=True)
class TextSpan:
    """A piece of a page chosen by the chunker, before it gets an identity."""

    page: int
    start_index: int
    text: str


@dataclass(frozen=True, slots=True)
class Chunk:
    """One retrievable unit, with everything the index stores next to its vector.

    ``version`` identifies the content *and* the pipeline that produced the chunk. Two
    ingestions of the same bytes with the same chunking produce the same ids, which is what
    makes re-running (or re-delivering an event) harmless.
    """

    chunk_id: str
    document_id: str
    media_type: str
    content_hash: str
    version: str
    page: int
    chunk_index: int
    chunk_count: int
    start_index: int
    text: str


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    chunk: Chunk
    vector: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class IndexedDocument:
    """A document version that is completely written in the index.

    The index lists a version only when its marker chunk (index 0, written last) exists,
    so a write interrupted halfway is never mistaken for a complete document.
    """

    document_id: str
    version: str
    content_hash: str
    chunk_count: int


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A chunk returned by a similarity search. Used by the evals to measure the index."""

    chunk_id: str
    document_id: str
    page: int
    text: str
    distance: float


@dataclass(frozen=True, slots=True)
class StoredChunk:
    """A chunk as the index holds it, for inspection."""

    chunk_id: str
    document_id: str
    version: str
    page: int
    chunk_index: int
    chunk_count: int
    text: str
    dimensions: int


@dataclass(frozen=True, slots=True)
class CollectionInfo:
    """What a collection is, without opening it for writing."""

    name: str
    metadata: dict[str, object]
    chunks: int


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def document_version(content_hash: str, pipeline_fingerprint: str) -> str:
    """Identity of one ingestion result: same bytes + same pipeline = same version."""
    return _sha256(f"{content_hash}|{pipeline_fingerprint}")[:16]


def chunk_id(document_id: str, version: str, chunk_index: int) -> str:
    """Deterministic chunk id. The document id is hashed: paths can be long or contain
    characters that some vector stores do not accept in ids."""
    return f"{_sha256(document_id)[:16]}:{version}:{chunk_index}"
