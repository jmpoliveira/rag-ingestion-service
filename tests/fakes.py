"""In-memory implementations of the ports, for use-case and eval tests (no network)."""

from __future__ import annotations

import hashlib
import math
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from src.domain.documents import (
    CollectionInfo,
    EmbeddedChunk,
    IndexedDocument,
    Page,
    ParsedDocument,
    SearchHit,
    SourceDocument,
    StoredChunk,
    TextSpan,
)
from src.domain.errors import DocumentRejectedError
from src.domain.index import IndexSpec


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeSource:
    """Documents as ``{id: bytes}``; ``media_type`` is ``text/plain`` unless overridden."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files: dict[str, bytes] = dict(files or {})
        self.media_types: dict[str, str] = {}
        self.reads: list[str] = []

    async def list_documents(self) -> list[SourceDocument]:
        return [self.describe(doc_id) for doc_id in sorted(self.files)]

    def describe(self, doc_id: str) -> SourceDocument:
        data = self.files[doc_id]
        return SourceDocument(
            doc_id, self.media_types.get(doc_id, "text/plain"), sha(data), len(data)
        )

    async def read_bytes(self, document: SourceDocument) -> bytes:
        self.reads.append(document.document_id)
        if document.document_id not in self.files:
            raise DocumentRejectedError("Document no longer exists in the source")
        return self.files[document.document_id]


class FakeParser:
    """Text split into pages on form feeds; raises for documents containing ``CORRUPT``."""

    def __init__(self, media_types: frozenset[str] = frozenset({"text/plain"})) -> None:
        self._media_types = media_types

    @property
    def media_types(self) -> frozenset[str]:
        return self._media_types

    async def parse(self, document: SourceDocument, data: bytes) -> ParsedDocument:
        text = data.decode("utf-8")
        if "CORRUPT" in text:
            raise DocumentRejectedError("PDF could not be parsed")
        pages = tuple(Page(n, part) for n, part in enumerate(text.split("\f"), start=1))
        return ParsedDocument(document, pages)


class FakeChunker:
    """One chunk per line, so tests control the chunk count exactly."""

    def __init__(self, fingerprint: str = "lines:v1") -> None:
        self._fingerprint = fingerprint

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def split(self, document: ParsedDocument) -> Sequence[TextSpan]:
        return [
            TextSpan(page.number, 0, line)
            for page in document.pages
            for line in page.text.split("\n")
        ]


def bag_of_words(text: str, dimensions: int = 32) -> list[float]:
    """A deterministic toy embedding: similar words give similar vectors."""
    vector = [0.0] * dimensions
    for word in text.lower().split():
        vector[int(sha(word.encode())[:8], 16) % dimensions] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


@dataclass
class FakeEmbedder:
    provider: str = "fake"
    model: str = "bag-of-words"
    calls: list[list[str]] = field(default_factory=list[list[str]])
    queries: list[str] = field(default_factory=list[str])
    # Raised on the next call when set.
    error: Exception | None = None
    # Replace the answer of every documents call (to test validation).
    answer: list[list[float]] | None = None

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.calls.append(list(texts))
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return self.answer
        return [bag_of_words(text) for text in texts]

    async def embed_query(self, text: str) -> Sequence[float]:
        self.queries.append(text)
        if self.error is not None:
            raise self.error
        return bag_of_words(text)


@dataclass
class InMemoryIndex:
    """Behaves like the Chroma adapter: chunk 0 marks a complete version."""

    chunks: dict[str, EmbeddedChunk] = field(default_factory=dict[str, EmbeddedChunk])
    operations: list[str] = field(default_factory=list[str])
    # Raised by upsert when set (to simulate a write failing halfway).
    fail_upsert: Exception | None = None

    async def list_documents(self, document_id: str | None = None) -> list[IndexedDocument]:
        return sorted(
            (
                IndexedDocument(
                    c.chunk.document_id, c.chunk.version, c.chunk.content_hash, c.chunk.chunk_count
                )
                for c in self.chunks.values()
                if c.chunk.chunk_index == 0
                and (document_id is None or c.chunk.document_id == document_id)
            ),
            key=lambda d: (d.document_id, d.version),
        )

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        if self.fail_upsert is not None:
            raise self.fail_upsert
        self.operations.append(f"upsert {[c.chunk.chunk_index for c in chunks]}")
        for item in chunks:
            self.chunks[item.chunk.chunk_id] = item

    async def delete(self, document_id: str, *, keep_version: str | None = None) -> None:
        self.operations.append(f"delete {document_id} keep={keep_version}")
        self.chunks = {
            key: c
            for key, c in self.chunks.items()
            if c.chunk.document_id != document_id or c.chunk.version == keep_version
        }

    async def search(self, vector: Sequence[float], k: int) -> list[SearchHit]:
        def distance(item: EmbeddedChunk) -> float:
            return 1.0 - sum(a * b for a, b in zip(vector, item.vector, strict=False))

        ranked = sorted(self.chunks.values(), key=distance)[:k]
        return [
            SearchHit(
                c.chunk.chunk_id, c.chunk.document_id, c.chunk.page, c.chunk.text, distance(c)
            )
            for c in ranked
        ]

    async def get_chunks(self, document_id: str) -> list[StoredChunk]:
        found = [
            StoredChunk(
                c.chunk.chunk_id,
                c.chunk.document_id,
                c.chunk.version,
                c.chunk.page,
                c.chunk.chunk_index,
                c.chunk.chunk_count,
                c.chunk.text,
                len(c.vector),
            )
            for c in self.chunks.values()
            if c.chunk.document_id == document_id
        ]
        return sorted(found, key=lambda chunk: (chunk.version, chunk.chunk_index))

    def documents(self) -> dict[str, list[str]]:
        """``{document_id: [chunk texts in order]}`` for assertions."""
        found: dict[str, list[tuple[int, str]]] = {}
        for c in self.chunks.values():
            found.setdefault(c.chunk.document_id, []).append((c.chunk.chunk_index, c.chunk.text))
        return {doc: [text for _, text in sorted(items)] for doc, items in sorted(found.items())}


@dataclass
class InMemoryIndexProvider:
    """One collection. ``metadata`` is None until the collection is created by ``open``."""

    index: InMemoryIndex = field(default_factory=InMemoryIndex)
    metadata: dict[str, object] | None = None
    opened: list[IndexSpec] = field(default_factory=list[IndexSpec])
    dropped: list[str] = field(default_factory=list[str])

    @asynccontextmanager
    async def open(self, spec: IndexSpec) -> AsyncGenerator[InMemoryIndex]:
        self.opened.append(spec)
        if self.metadata is None:
            self.metadata = dict(spec.as_metadata())
        spec.check(self.metadata)
        yield self.index

    async def describe(self, collection: str) -> CollectionInfo | None:
        if self.metadata is None:
            return None
        return CollectionInfo(collection, dict(self.metadata), len(self.index.chunks))

    async def drop(self, collection: str) -> bool:
        self.dropped.append(collection)
        existed = self.metadata is not None or bool(self.index.chunks)
        self.index.chunks.clear()
        self.metadata = None
        return existed
