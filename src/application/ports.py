"""Ports: the interfaces the use cases need. Infrastructure implements them.

The split between ``DocumentSource`` (where documents come from) and the use cases (what is
done with one document) is what lets an event consumer replace the folder scan later
without touching the pipeline (ADR 0002).
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from src.domain.documents import (
    CollectionInfo,
    EmbeddedChunk,
    IndexedDocument,
    ParsedDocument,
    SearchHit,
    SourceDocument,
    StoredChunk,
    TextSpan,
)
from src.domain.index import IndexSpec


class DocumentSource(Protocol):
    """Where documents live. A folder today; blob storage behind events tomorrow."""

    async def list_documents(self) -> Sequence[SourceDocument]:
        """Every document currently in the source, with its content hash.

        Raises:
            SourceUnavailableError: the source itself cannot be read.
        """
        ...

    async def read_bytes(self, document: SourceDocument) -> bytes:
        """The content of one document.

        Raises:
            DocumentRejectedError: this document cannot be read (gone, too large...).
            SourceUnavailableError: the source itself cannot be read.
        """
        ...


class DocumentParser(Protocol):
    """Extracts text from one media type. Must be safe on hostile input."""

    @property
    def media_types(self) -> frozenset[str]: ...

    async def parse(self, document: SourceDocument, data: bytes) -> ParsedDocument:
        """Raises:
        DocumentRejectedError: encrypted, corrupted, over a limit or not decodable.
        """
        ...


class Chunker(Protocol):
    @property
    def fingerprint(self) -> str:
        """Identifies the chunking settings; part of every document version."""
        ...

    def split(self, document: ParsedDocument) -> Sequence[TextSpan]: ...


class Embedder(Protocol):
    """One embedding model on one provider. Applies the model's task prefixes itself."""

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """One vector per text, in order.

        Raises:
            EmbeddingError: malformed answer (a per-document failure).
            EmbeddingUnavailableError, EmbeddingConfigError: stop the run.
        """
        ...

    async def embed_query(self, text: str) -> Sequence[float]: ...


class VectorIndex(Protocol):
    """An open collection that satisfies the index contract."""

    async def list_documents(self, document_id: str | None = None) -> Sequence[IndexedDocument]:
        """Complete document versions (marker chunk present), optionally for one document."""
        ...

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None: ...

    async def delete(self, document_id: str, *, keep_version: str | None = None) -> None:
        """Delete a document's chunks, except those of ``keep_version`` when given."""
        ...

    async def search(self, vector: Sequence[float], k: int) -> Sequence[SearchHit]: ...

    async def get_chunks(self, document_id: str) -> Sequence[StoredChunk]:
        """Every chunk stored for one document, all versions, ordered by version and index."""
        ...


class VectorIndexProvider(Protocol):
    def open(self, spec: IndexSpec) -> AbstractAsyncContextManager[VectorIndex]:
        """Open (or create) the collection and check its contract.

        Raises:
            IndexContractError: the collection was built under another contract.
            VectorIndexUnavailableError: the vector store cannot be reached.
        """
        ...

    async def describe(self, collection: str) -> CollectionInfo | None:
        """Read a collection's metadata and size without creating or checking it.

        Returns None when it does not exist.
        """
        ...

    async def drop(self, collection: str) -> bool:
        """Delete a whole collection. Returns False when it did not exist."""
        ...
