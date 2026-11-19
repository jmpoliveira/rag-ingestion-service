"""ChromaDB over HTTP (the ``chromadb-client`` package: the client only, no server or local
embedding models in the image).

- Opening a collection never changes it: an existing collection is read and its contract
  checked; only a missing one is created with ours (ADR 0004). ``get_or_create`` is not
  used because it is not explicit about what happens to the metadata of an existing one.
- Vectors are always computed by our ``Embedder``: the collection gets no embedding
  function, so Chroma never downloads or runs a model of its own.
- Chroma's anonymous product telemetry is switched off.

Chunk metadata (the per-chunk part of the index contract, schema version 1): ``document_id``,
``media_type``, ``content_hash``, ``version``, ``page``, ``chunk_index``, ``chunk_count``,
``start_index``. The chunk text is stored as the Chroma document.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any, cast

import chromadb
import httpx
from chromadb.api import AsyncClientAPI
from chromadb.api.models.AsyncCollection import (  # pyright: ignore[reportMissingTypeStubs]
    AsyncCollection,
)
from chromadb.config import Settings as ChromaSettings
from chromadb.errors import ChromaError, NotFoundError, UniqueConstraintError

from src.domain.documents import (
    CollectionInfo,
    EmbeddedChunk,
    IndexedDocument,
    SearchHit,
    StoredChunk,
)
from src.domain.errors import VectorIndexError, VectorIndexUnavailableError
from src.domain.index import IndexSpec

logger = logging.getLogger(__name__)

ClientFactory = Callable[[], Awaitable[AsyncClientAPI]]

_PAGE_SIZE = 500


class ChromaVectorIndex:
    def __init__(self, collection: AsyncCollection, *, batch_size: int) -> None:
        self._collection = collection
        self._batch_size = batch_size

    async def list_documents(self, document_id: str | None = None) -> list[IndexedDocument]:
        # Only marker chunks (index 0, written last): one row per complete version.
        where: dict[str, Any] = {"chunk_index": 0}
        if document_id is not None:
            where = {"$and": [{"chunk_index": 0}, {"document_id": document_id}]}
        found: list[IndexedDocument] = []
        offset = 0
        while True:
            page = await _call(
                self._collection.get(
                    where=where, include=["metadatas"], limit=_PAGE_SIZE, offset=offset
                )
            )
            metadatas = page["metadatas"] or []
            found.extend(item for item in map(_indexed_document, metadatas) if item is not None)
            if len(page["ids"]) < _PAGE_SIZE:
                return found
            offset += _PAGE_SIZE

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        for start in range(0, len(chunks), self._batch_size):
            batch = chunks[start : start + self._batch_size]
            await _call(
                self._collection.upsert(
                    ids=[item.chunk.chunk_id for item in batch],
                    embeddings=[list(item.vector) for item in batch],
                    metadatas=[_metadata(item) for item in batch],
                    documents=[item.chunk.text for item in batch],
                )
            )

    async def delete(self, document_id: str, *, keep_version: str | None = None) -> None:
        where: dict[str, Any] = {"document_id": document_id}
        if keep_version is not None:
            where = {"$and": [where, {"version": {"$ne": keep_version}}]}
        await _call(self._collection.delete(where=where))

    async def search(self, vector: Sequence[float], k: int) -> list[SearchHit]:
        result = await _call(
            self._collection.query(
                query_embeddings=[list(vector)],
                n_results=k,
                include=["documents", "metadatas", "distances"],
            )
        )
        ids = result["ids"][0] if result["ids"] else []
        documents = (result["documents"] or [[]])[0]
        metadatas = (result["metadatas"] or [[]])[0]
        distances = (result["distances"] or [[]])[0]
        return [
            SearchHit(
                chunk_id=chunk_id,
                document_id=str(meta.get("document_id", "")),
                page=_int(meta.get("page")),
                text=text or "",
                distance=float(distance),
            )
            for chunk_id, text, meta, distance in zip(
                ids, documents, metadatas, distances, strict=True
            )
        ]

    async def get_chunks(self, document_id: str) -> list[StoredChunk]:
        result = await _call(
            self._collection.get(
                where={"document_id": document_id},
                include=["metadatas", "documents", "embeddings"],
            )
        )
        metadatas = result["metadatas"] or []
        documents = result["documents"] or []
        embeddings = result["embeddings"]
        vectors: list[Any] = [] if embeddings is None else list(embeddings)
        chunks = [
            StoredChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                version=str(meta.get("version", "")),
                page=_int(meta.get("page")),
                chunk_index=_int(meta.get("chunk_index")),
                chunk_count=_int(meta.get("chunk_count")),
                text=text or "",
                dimensions=len(vector) if vector is not None else 0,
            )
            for chunk_id, meta, text, vector in zip(
                result["ids"], metadatas, documents, vectors, strict=True
            )
        ]
        return sorted(chunks, key=lambda chunk: (chunk.version, chunk.chunk_index))


class ChromaIndexProvider:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        ssl: bool,
        batch_size: int,
        client_factory: ClientFactory | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._batch_size = batch_size
        self._client_factory = client_factory or (
            lambda: chromadb.AsyncHttpClient(
                host=host,
                port=port,
                ssl=ssl,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        )

    @asynccontextmanager
    async def open(self, spec: IndexSpec) -> AsyncGenerator[ChromaVectorIndex]:
        client = await _call(self._client_factory())
        collection = await _call(self._get_or_create(client, spec))
        spec.check(collection.metadata)
        logger.debug("Collection opened", extra={"collection": spec.collection})
        yield ChromaVectorIndex(collection, batch_size=self._batch_size)

    async def describe(self, collection: str) -> CollectionInfo | None:
        client = await _call(self._client_factory())
        try:
            found = await _call(client.get_collection(name=collection, embedding_function=None))
        except _NotFound:
            return None
        count = await _call(found.count())
        return CollectionInfo(collection, dict(found.metadata or {}), count)

    async def drop(self, collection: str) -> bool:
        client = await _call(self._client_factory())
        try:
            await _call(client.delete_collection(name=collection))
        except _NotFound:
            return False
        return True

    @staticmethod
    async def _get_or_create(client: AsyncClientAPI, spec: IndexSpec) -> AsyncCollection:
        try:
            return await client.get_collection(name=spec.collection, embedding_function=None)
        except NotFoundError:
            pass
        try:
            logger.info("Creating collection", extra={"collection": spec.collection})
            return await client.create_collection(
                name=spec.collection,
                metadata=spec.as_metadata(),
                embedding_function=None,
                configuration={"hnsw": {"space": spec.distance}},
            )
        except UniqueConstraintError:
            # Another worker created it in the meantime: read it (and check its contract).
            return await client.get_collection(name=spec.collection, embedding_function=None)


class _NotFound(VectorIndexError):
    """Internal: the collection does not exist (only meaningful to ``drop``)."""


async def _call[T](operation: Awaitable[T]) -> T:
    """Translate every client failure into a domain error.

    The Chroma HTTP client raises ``ChromaError`` subclasses for errors it recognises, but a
    plain ``Exception`` carrying the response body for any other HTTP error status, so the
    last clause has to be broad. It logs the type and re-raises as a domain error.
    """
    try:
        return await operation
    except NotFoundError as err:
        raise _NotFound(str(err)) from err
    except ChromaError as err:
        raise VectorIndexError(f"Vector store rejected the operation: {err.name()}") from err
    except httpx.TransportError as err:
        raise VectorIndexUnavailableError("Vector store is unreachable") from err
    except Exception as err:
        logger.error("Unexpected vector store error", extra={"error": type(err).__name__})
        raise VectorIndexError("Vector store failed") from err


def _metadata(item: EmbeddedChunk) -> dict[str, str | int]:
    chunk = item.chunk
    return {
        "document_id": chunk.document_id,
        "media_type": chunk.media_type,
        "content_hash": chunk.content_hash,
        "version": chunk.version,
        "page": chunk.page,
        "chunk_index": chunk.chunk_index,
        "chunk_count": chunk.chunk_count,
        "start_index": chunk.start_index,
    }


def _indexed_document(meta: Mapping[str, object] | None) -> IndexedDocument | None:
    if meta is None:
        return None
    values = cast(Mapping[str, Any], meta)
    document_id, version = values.get("document_id"), values.get("version")
    if not isinstance(document_id, str) or not isinstance(version, str):
        logger.warning("Ignoring a marker chunk without document_id or version")
        return None
    return IndexedDocument(
        document_id=document_id,
        version=version,
        content_hash=str(values.get("content_hash", "")),
        chunk_count=_int(values.get("chunk_count")),
    )


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
