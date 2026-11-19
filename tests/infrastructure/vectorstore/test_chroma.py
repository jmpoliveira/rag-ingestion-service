"""The Chroma adapter against a scripted client (the real server is not started in tests).

The fake records the arguments the adapter sends; the filter syntax (``$and``, ``$ne``) and
the result shapes follow chromadb-client 1.5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import httpx
import pytest
from chromadb.api import AsyncClientAPI
from chromadb.errors import InvalidArgumentError, NotFoundError, UniqueConstraintError

from src.domain.documents import Chunk, EmbeddedChunk
from src.domain.errors import IndexContractError, VectorIndexError, VectorIndexUnavailableError
from src.domain.index import IndexSpec
from src.infrastructure.vectorstore.chroma import ChromaIndexProvider, ChromaVectorIndex

SPEC = IndexSpec(collection="kb", embedding_provider="ollama", embedding_model="nomic")


@dataclass
class FakeCollection:
    metadata: dict[str, Any] | None = None
    pages: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    calls: list[tuple[str, dict[str, Any]]] = field(
        default_factory=list[tuple[str, dict[str, Any]]]
    )
    query_result: dict[str, Any] = field(default_factory=dict[str, Any])
    error: Exception | None = None

    def _record(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((name, kwargs))
        if self.error is not None:
            raise self.error

    async def get(self, **kwargs: Any) -> dict[str, Any]:
        self._record("get", kwargs)
        return self.pages.pop(0) if self.pages else {"ids": [], "metadatas": []}

    async def upsert(self, **kwargs: Any) -> None:
        self._record("upsert", kwargs)

    async def delete(self, **kwargs: Any) -> None:
        self._record("delete", kwargs)

    async def count(self) -> int:
        return 7

    async def query(self, **kwargs: Any) -> dict[str, Any]:
        self._record("query", kwargs)
        return self.query_result


@dataclass
class FakeClient:
    collection: FakeCollection | None = None
    created: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    create_error: Exception | None = None
    deleted: list[str] = field(default_factory=list[str])

    async def get_collection(self, name: str, embedding_function: Any = None) -> FakeCollection:
        if self.collection is None:
            raise NotFoundError(f"Collection [{name}] does not exist")
        return self.collection

    async def create_collection(self, **kwargs: Any) -> FakeCollection:
        if self.create_error is not None:
            error, self.create_error = self.create_error, None
            self.collection = FakeCollection(metadata=SPEC.as_metadata())
            raise error
        self.created.append(kwargs)
        self.collection = FakeCollection(metadata=kwargs["metadata"])
        return self.collection

    async def delete_collection(self, name: str) -> None:
        if self.collection is None:
            raise NotFoundError(f"Collection [{name}] does not exist")
        self.deleted.append(name)
        self.collection = None


def _provider(client: FakeClient, batch_size: int = 2) -> ChromaIndexProvider:
    async def factory() -> AsyncClientAPI:
        return cast(AsyncClientAPI, client)

    return ChromaIndexProvider(
        host="chroma.test", port=8000, ssl=False, batch_size=batch_size, client_factory=factory
    )


def _index(collection: FakeCollection, batch_size: int = 2) -> ChromaVectorIndex:
    return ChromaVectorIndex(collection, batch_size=batch_size)  # type: ignore[arg-type]


def _embedded(index: int, *, version: str = "v1") -> EmbeddedChunk:
    chunk = Chunk(
        chunk_id=f"id-{index}",
        document_id="docs/a.pdf",
        media_type="application/pdf",
        content_hash="hash",
        version=version,
        page=1,
        chunk_index=index,
        chunk_count=3,
        start_index=0,
        text=f"text {index}",
    )
    return EmbeddedChunk(chunk, (0.1, 0.2))


async def test_a_missing_collection_is_created_with_the_contract_and_no_embedding_function():
    # Arrange
    client = FakeClient()

    # Act
    async with _provider(client).open(SPEC):
        pass

    # Assert
    [created] = client.created
    assert created["metadata"] == SPEC.as_metadata()
    assert created["embedding_function"] is None
    assert created["configuration"] == {"hnsw": {"space": "cosine"}}


async def test_an_existing_collection_is_checked_not_changed():
    # Arrange: built by the old service, without a contract
    client = FakeClient(collection=FakeCollection(metadata=None))

    # Act / Assert
    with pytest.raises(IndexContractError):
        async with _provider(client).open(SPEC):
            pass
    assert client.created == []


async def test_a_collection_created_concurrently_is_read_instead():
    # Arrange
    client = FakeClient(create_error=UniqueConstraintError("exists"))

    # Act
    async with _provider(client).open(SPEC) as index:
        # Assert
        assert isinstance(index, ChromaVectorIndex)


async def test_an_unreachable_server_is_unavailable():
    # Arrange
    async def factory() -> AsyncClientAPI:
        raise httpx.ConnectError("refused")

    provider = ChromaIndexProvider(
        host="h", port=1, ssl=False, batch_size=1, client_factory=factory
    )

    # Act / Assert
    with pytest.raises(VectorIndexUnavailableError):
        async with provider.open(SPEC):
            pass


async def test_upsert_sends_batches_with_ids_vectors_metadata_and_text():
    # Arrange
    collection = FakeCollection()

    # Act
    await _index(collection, batch_size=2).upsert([_embedded(1), _embedded(2), _embedded(0)])

    # Assert
    batches = [kwargs for name, kwargs in collection.calls if name == "upsert"]
    assert [b["ids"] for b in batches] == [["id-1", "id-2"], ["id-0"]]
    assert batches[1]["embeddings"] == [[0.1, 0.2]]
    assert batches[1]["documents"] == ["text 0"]
    assert batches[1]["metadatas"] == [
        {
            "document_id": "docs/a.pdf",
            "media_type": "application/pdf",
            "content_hash": "hash",
            "version": "v1",
            "page": 1,
            "chunk_index": 0,
            "chunk_count": 3,
            "start_index": 0,
        }
    ]


async def test_delete_keeps_the_current_version_when_asked():
    # Arrange
    collection = FakeCollection()
    index = _index(collection)

    # Act
    await index.delete("a.pdf")
    await index.delete("a.pdf", keep_version="v2")

    # Assert
    assert collection.calls[0] == ("delete", {"where": {"document_id": "a.pdf"}})
    assert collection.calls[1] == (
        "delete",
        {"where": {"$and": [{"document_id": "a.pdf"}, {"version": {"$ne": "v2"}}]}},
    )


async def test_list_documents_reads_marker_chunks_page_by_page(monkeypatch: pytest.MonkeyPatch):
    # Arrange
    monkeypatch.setattr("src.infrastructure.vectorstore.chroma._PAGE_SIZE", 2)
    marker = {"document_id": "a", "version": "v1", "content_hash": "h", "chunk_count": 4}
    collection = FakeCollection(
        pages=[
            {"ids": ["1", "2"], "metadatas": [marker, {**marker, "document_id": "b"}]},
            {"ids": ["3"], "metadatas": [{"version": "broken"}]},
        ]
    )

    # Act
    found = await _index(collection).list_documents()

    # Assert
    assert [(d.document_id, d.chunk_count) for d in found] == [("a", 4), ("b", 4)]
    assert collection.calls[0][1]["where"] == {"chunk_index": 0}
    assert collection.calls[1][1]["offset"] == 2


async def test_list_documents_for_one_document_filters_by_id():
    # Arrange
    collection = FakeCollection()

    # Act
    await _index(collection).list_documents("a.pdf")

    # Assert
    assert collection.calls[0][1]["where"] == {
        "$and": [{"chunk_index": 0}, {"document_id": "a.pdf"}]
    }


async def test_search_returns_hits_in_rank_order():
    # Arrange
    collection = FakeCollection(
        query_result={
            "ids": [["c1", "c2"]],
            "documents": [["first", None]],
            "metadatas": [[{"document_id": "a", "page": 2}, {"document_id": "b"}]],
            "distances": [[0.1, 0.4]],
        }
    )

    # Act
    hits = await _index(collection).search([0.1, 0.2], 2)

    # Assert
    assert [(h.chunk_id, h.document_id, h.page, h.text, h.distance) for h in hits] == [
        ("c1", "a", 2, "first", 0.1),
        ("c2", "b", 0, "", 0.4),
    ]
    assert collection.calls[0][1]["n_results"] == 2


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (InvalidArgumentError("bad metadata"), VectorIndexError),
        (httpx.ReadTimeout("slow"), VectorIndexUnavailableError),
        (Exception("500 Internal Server Error"), VectorIndexError),
    ],
)
async def test_client_errors_are_translated(error: Exception, expected: type[Exception]):
    # Arrange
    collection = FakeCollection(error=error)

    # Act / Assert
    with pytest.raises(expected):
        await _index(collection).upsert([_embedded(0)])


async def test_drop_reports_whether_the_collection_existed():
    # Arrange
    client = FakeClient(collection=FakeCollection(metadata=SPEC.as_metadata()))
    provider = _provider(client)

    # Act / Assert
    assert await provider.drop("kb") is True
    assert await provider.drop("kb") is False


def test_batch_size_must_be_positive():
    with pytest.raises(ValueError, match="batch_size"):
        ChromaIndexProvider(host="h", port=1, ssl=False, batch_size=0)


async def test_describe_reads_metadata_and_size_without_creating():
    # Arrange
    client = FakeClient(collection=FakeCollection(metadata={"rag.distance": "cosine"}))
    empty = FakeClient()

    # Act
    info = await _provider(client).describe("kb")
    missing = await _provider(empty).describe("kb")

    # Assert
    assert info is not None
    assert (info.name, info.metadata, info.chunks) == ("kb", {"rag.distance": "cosine"}, 7)
    assert missing is None
    assert empty.created == []


async def test_get_chunks_returns_every_version_in_order_with_vector_size():
    # Arrange
    def meta(version: str, index: int) -> dict[str, Any]:
        return {"version": version, "chunk_index": index, "chunk_count": 2, "page": 1}

    collection = FakeCollection(
        pages=[
            {
                "ids": ["b1", "a1", "a0"],
                "metadatas": [meta("v2", 1), meta("v1", 1), meta("v1", 0)],
                "documents": ["B1", "A1", None],
                "embeddings": [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3], None],
            }
        ]
    )

    # Act
    chunks = await _index(collection).get_chunks("a.md")

    # Assert
    assert [(c.chunk_id, c.version, c.chunk_index, c.dimensions) for c in chunks] == [
        ("a0", "v1", 0, 0),
        ("a1", "v1", 1, 3),
        ("b1", "v2", 1, 3),
    ]
    assert chunks[0].text == ""
    assert collection.calls[0][1]["where"] == {"document_id": "a.md"}
