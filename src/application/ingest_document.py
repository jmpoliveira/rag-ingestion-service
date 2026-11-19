"""Use case: ingest one document into an open index.

It is the unit of work for every trigger. The folder sync calls it for each file today; an
event consumer will call it for each message tomorrow (ADR 0002). That is why it must be
**idempotent** (ADR 0003): the same document version is written under the same ids, a
version already in the index is skipped, and a write interrupted halfway is detected and
redone on the next attempt.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

from src.application.ports import Chunker, DocumentParser, DocumentSource, Embedder, VectorIndex
from src.application.sanitization import CLEANING_VERSION, clean_text
from src.application.telemetry import (
    ATTR_CHUNKS,
    ATTR_DIMENSIONS,
    ATTR_OUTCOME,
    ATTR_PAGES,
    document_span,
    embeddings_span,
    index_span,
    mark_error,
    stage_span,
)
from src.domain.documents import (
    Chunk,
    EmbeddedChunk,
    Page,
    ParsedDocument,
    SourceDocument,
    chunk_id,
    document_version,
)
from src.domain.errors import (
    DocumentRejectedError,
    EmbeddingError,
    FatalError,
    VectorIndexError,
)
from src.domain.ingestion import DocumentResult, Outcome

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestConfig:
    collection: str
    embedding_batch_size: int


class IngestDocument:
    def __init__(
        self,
        source: DocumentSource,
        parsers: Sequence[DocumentParser],
        chunker: Chunker,
        embedder: Embedder,
        config: IngestConfig,
    ) -> None:
        if config.embedding_batch_size < 1:
            raise ValueError("embedding_batch_size must be at least 1")
        self._source = source
        self._parsers = {media: parser for parser in parsers for media in parser.media_types}
        self._chunker = chunker
        self._embedder = embedder
        self._config = config

    @property
    def media_types(self) -> frozenset[str]:
        return frozenset(self._parsers)

    @property
    def pipeline_fingerprint(self) -> str:
        """Everything besides the bytes that changes the chunks. Changing it re-ingests every
        document on the next sync. (The embedding model is not here: it is fixed per
        collection by the index contract, ADR 0004.)"""
        return f"{self._chunker.fingerprint};clean=v{CLEANING_VERSION}"

    async def execute(self, document: SourceDocument, index: VectorIndex) -> DocumentResult:
        with document_span(document.document_id, document.media_type, document.size_bytes) as span:
            result = await self._ingest(document, index)
            span.set_attribute(ATTR_OUTCOME, result.outcome.value)
            span.set_attribute(ATTR_CHUNKS, result.chunks)
            if result.outcome is Outcome.FAILED:
                mark_error(span, "document_failed")
            log = logger.warning if result.outcome is Outcome.FAILED else logger.info
            log(
                "Document %s",
                result.outcome.value,
                extra={
                    "document_id": document.document_id,
                    "chunks": result.chunks,
                    **({"detail": result.detail} if result.detail else {}),
                },
            )
            return result

    async def _ingest(self, document: SourceDocument, index: VectorIndex) -> DocumentResult:
        doc_id = document.document_id
        version = document_version(document.content_hash, self.pipeline_fingerprint)
        existing = await index.list_documents(doc_id)
        if [item.version for item in existing] == [version]:
            return DocumentResult(doc_id, Outcome.UNCHANGED)

        parser = self._parsers.get(document.media_type)
        if parser is None:
            return DocumentResult(doc_id, Outcome.FAILED, detail="Unsupported media type")
        try:
            parsed = await self._parse(document, parser)
            if not parsed.has_text:
                if existing:
                    # The new content has no text: the old chunks describe something gone.
                    await self._delete(doc_id, index)
                return DocumentResult(doc_id, Outcome.EMPTY, detail="No extractable text")
            chunks = self._chunk(parsed, version)
            vectors = await self._embed([chunk.text for chunk in chunks])
            embedded = [
                EmbeddedChunk(chunk, tuple(vector))
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            await self._write(doc_id, version, embedded, index)
        except FatalError:
            raise
        except (DocumentRejectedError, EmbeddingError, VectorIndexError) as err:
            # Per-document failure. Any previous version stays searchable: stale is better
            # than missing, and the next sync retries.
            return DocumentResult(doc_id, Outcome.FAILED, detail=str(err))
        return DocumentResult(doc_id, Outcome.INDEXED, chunks=len(embedded))

    async def _parse(self, document: SourceDocument, parser: DocumentParser) -> ParsedDocument:
        with stage_span("read"):
            data = await self._source.read_bytes(document)
        with stage_span("parse") as span:
            parsed = await parser.parse(document, data)
            span.set_attribute(ATTR_PAGES, len(parsed.pages))
        pages = tuple(Page(page.number, clean_text(page.text)) for page in parsed.pages)
        return ParsedDocument(document, pages)

    def _chunk(self, parsed: ParsedDocument, version: str) -> list[Chunk]:
        with stage_span("chunk") as span:
            spans = [piece for piece in self._chunker.split(parsed) if piece.text.strip()]
            span.set_attribute(ATTR_CHUNKS, len(spans))
        source = parsed.source
        return [
            Chunk(
                chunk_id=chunk_id(source.document_id, version, position),
                document_id=source.document_id,
                media_type=source.media_type,
                content_hash=source.content_hash,
                version=version,
                page=piece.page,
                chunk_index=position,
                chunk_count=len(spans),
                start_index=piece.start_index,
                text=piece.text,
            )
            for position, piece in enumerate(spans)
        ]

    async def _embed(self, texts: Sequence[str]) -> list[Sequence[float]]:
        """Embed in batches: bounded request size and memory, whatever the document size."""
        size = self._config.embedding_batch_size
        vectors: list[Sequence[float]] = []
        for start in range(0, len(texts), size):
            batch = texts[start : start + size]
            with embeddings_span(self._embedder.provider, self._embedder.model, len(batch)) as span:
                answer = await self._embedder.embed_documents(batch)
                _check_vectors(answer, expected=len(batch))
                span.set_attribute(ATTR_DIMENSIONS, len(answer[0]))
            vectors.extend(answer)
        if len({len(vector) for vector in vectors}) > 1:
            raise EmbeddingError("Embedding provider returned vectors of different sizes")
        return vectors

    async def _write(
        self, document_id: str, version: str, chunks: Sequence[EmbeddedChunk], index: VectorIndex
    ) -> None:
        """Write the new version, then remove the others (ADR 0003).

        Chunk 0 is the completion marker and goes last: if the process dies before it, the
        version is not listed as complete and the next attempt writes it again. Old versions
        are deleted only after the new one is complete, so the document is never missing
        from search results; at worst both versions are briefly visible.
        """
        collection = self._config.collection
        body, marker = chunks[1:], chunks[:1]
        if body:
            with index_span("upsert", collection, len(body)):
                await index.upsert(body)
        with index_span("upsert", collection, len(marker)):
            await index.upsert(marker)
        with index_span("delete", collection):
            await index.delete(document_id, keep_version=version)

    async def _delete(self, document_id: str, index: VectorIndex) -> None:
        with index_span("delete", self._config.collection):
            await index.delete(document_id)


def _check_vectors(vectors: Sequence[Sequence[float]], *, expected: int) -> None:
    """Never trust a provider's answer blindly: a wrong count would shift every vector onto
    the wrong chunk, and a NaN poisons similarity search silently."""
    if len(vectors) != expected:
        raise EmbeddingError(
            f"Embedding provider returned {len(vectors)} vectors for {expected} texts"
        )
    if any(not vector for vector in vectors):
        raise EmbeddingError("Embedding provider returned an empty vector")
    if any(not math.isfinite(value) for vector in vectors for value in vector):
        raise EmbeddingError("Embedding provider returned a non-finite value")
