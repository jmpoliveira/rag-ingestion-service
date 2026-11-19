from __future__ import annotations

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.application.ingest_document import IngestConfig, IngestDocument
from src.domain.errors import (
    EmbeddingConfigError,
    EmbeddingError,
    EmbeddingUnavailableError,
    VectorIndexError,
)
from src.domain.ingestion import Outcome
from tests.conftest import span_by_name, span_names
from tests.fakes import FakeChunker, FakeEmbedder, FakeParser, FakeSource, InMemoryIndex


def _ingest(
    source: FakeSource,
    embedder: FakeEmbedder | None = None,
    *,
    chunker: FakeChunker | None = None,
    batch_size: int = 2,
) -> IngestDocument:
    return IngestDocument(
        source,
        [FakeParser()],
        chunker or FakeChunker(),
        embedder or FakeEmbedder(),
        IngestConfig(collection="kb", embedding_batch_size=batch_size),
    )


async def test_new_document_is_chunked_embedded_and_written_with_its_metadata():
    # Arrange
    source = FakeSource({"a.txt": b"alpha\nbeta\fgamma"})
    index = InMemoryIndex()

    # Act
    result = await _ingest(source).execute(source.describe("a.txt"), index)

    # Assert
    assert result.outcome is Outcome.INDEXED
    assert result.chunks == 3
    assert index.documents() == {"a.txt": ["alpha", "beta", "gamma"]}
    pages = sorted((c.chunk.chunk_index, c.chunk.page) for c in index.chunks.values())
    assert pages == [(0, 1), (1, 1), (2, 2)]
    assert {c.chunk.chunk_count for c in index.chunks.values()} == {3}


async def test_the_marker_chunk_is_written_last_and_old_versions_removed_after():
    # Arrange
    source = FakeSource({"a.txt": b"one\ntwo\nthree"})
    index = InMemoryIndex()
    document = source.describe("a.txt")

    # Act
    await _ingest(source).execute(document, index)

    # Assert
    assert index.operations[0] == "upsert [1, 2]"
    assert index.operations[1] == "upsert [0]"
    assert index.operations[2].startswith("delete a.txt keep=")


async def test_an_unchanged_document_is_not_read_again():
    # Arrange
    source = FakeSource({"a.txt": b"one\ntwo"})
    index = InMemoryIndex()
    ingest = _ingest(source)
    await ingest.execute(source.describe("a.txt"), index)
    source.reads.clear()

    # Act
    result = await ingest.execute(source.describe("a.txt"), index)

    # Assert
    assert result.outcome is Outcome.UNCHANGED
    assert source.reads == []


async def test_a_changed_document_replaces_its_previous_chunks():
    # Arrange
    source = FakeSource({"a.txt": b"one\ntwo\nthree"})
    index = InMemoryIndex()
    ingest = _ingest(source)
    await ingest.execute(source.describe("a.txt"), index)
    source.files["a.txt"] = b"only one line now"

    # Act
    result = await ingest.execute(source.describe("a.txt"), index)

    # Assert
    assert result.outcome is Outcome.INDEXED
    assert index.documents() == {"a.txt": ["only one line now"]}


async def test_a_new_chunking_reingests_the_same_bytes():
    # Arrange
    source = FakeSource({"a.txt": b"one\ntwo"})
    index = InMemoryIndex()
    await _ingest(source, chunker=FakeChunker("lines:v1")).execute(source.describe("a.txt"), index)

    # Act
    result = await _ingest(source, chunker=FakeChunker("lines:v2")).execute(
        source.describe("a.txt"), index
    )

    # Assert
    assert result.outcome is Outcome.INDEXED
    assert len(await index.list_documents("a.txt")) == 1


async def test_a_write_interrupted_before_the_marker_is_redone():
    # Arrange: the body is written, then the process "dies" before the marker
    source = FakeSource({"a.txt": b"one\ntwo\nthree"})
    index = InMemoryIndex()
    ingest = _ingest(source)
    await ingest.execute(source.describe("a.txt"), index)
    marker = next(key for key, c in index.chunks.items() if c.chunk.chunk_index == 0)
    del index.chunks[marker]

    # Act
    result = await ingest.execute(source.describe("a.txt"), index)

    # Assert
    assert result.outcome is Outcome.INDEXED
    assert index.documents() == {"a.txt": ["one", "two", "three"]}


async def test_text_is_cleaned_before_chunking():
    # Arrange: a zero-width space hides text from a reviewer
    source = FakeSource({"a.txt": "pay\u200bload   here".encode()})
    index = InMemoryIndex()

    # Act
    await _ingest(source).execute(source.describe("a.txt"), index)

    # Assert
    assert index.documents() == {"a.txt": ["payload here"]}


async def test_document_without_text_is_empty_and_its_old_chunks_are_removed():
    # Arrange
    source = FakeSource({"a.txt": b"text"})
    index = InMemoryIndex()
    ingest = _ingest(source)
    await ingest.execute(source.describe("a.txt"), index)
    source.files["a.txt"] = b"  \f  "

    # Act
    result = await ingest.execute(source.describe("a.txt"), index)

    # Assert
    assert result.outcome is Outcome.EMPTY
    assert index.documents() == {}


async def test_a_rejected_document_fails_without_touching_its_indexed_version():
    # Arrange
    source = FakeSource({"a.txt": b"good"})
    index = InMemoryIndex()
    ingest = _ingest(source)
    await ingest.execute(source.describe("a.txt"), index)
    source.files["a.txt"] = b"CORRUPT"

    # Act
    result = await ingest.execute(source.describe("a.txt"), index)

    # Assert
    assert result.outcome is Outcome.FAILED
    assert result.detail == "PDF could not be parsed"
    assert index.documents() == {"a.txt": ["good"]}


async def test_unsupported_media_type_fails():
    # Arrange
    source = FakeSource({"a.bin": b"x"})
    source.media_types["a.bin"] = "application/octet-stream"

    # Act
    result = await _ingest(source).execute(source.describe("a.bin"), InMemoryIndex())

    # Assert
    assert result.outcome is Outcome.FAILED


async def test_embeddings_are_requested_in_batches():
    # Arrange
    source = FakeSource({"a.txt": b"1\n2\n3\n4\n5"})
    embedder = FakeEmbedder()

    # Act
    await _ingest(source, embedder, batch_size=2).execute(source.describe("a.txt"), InMemoryIndex())

    # Assert
    assert [len(call) for call in embedder.calls] == [2, 2, 1]


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ([[0.1]], "returned 1 vectors for 2 texts"),
        ([[0.1], []], "empty vector"),
        ([[0.1], [float("nan")]], "non-finite"),
    ],
)
async def test_malformed_embeddings_fail_the_document(answer: list[list[float]], message: str):
    # Arrange
    source = FakeSource({"a.txt": b"one\ntwo"})
    embedder = FakeEmbedder(answer=answer)
    index = InMemoryIndex()

    # Act
    result = await _ingest(source, embedder).execute(source.describe("a.txt"), index)

    # Assert
    assert result.outcome is Outcome.FAILED
    assert message in result.detail
    assert index.chunks == {}


async def test_vectors_of_different_sizes_across_batches_fail_the_document():
    # Arrange: the first batch gets 2-d vectors, the second 3-d
    source = FakeSource({"a.txt": b"1\n2\n3"})

    class Shifting(FakeEmbedder):
        async def embed_documents(self, texts: object) -> list[list[float]]:  # type: ignore[override]
            size = 2 if not self.calls else 3
            self.calls.append([])
            return [[0.5] * size for _ in texts]  # type: ignore[attr-defined]

    # Act
    result = await _ingest(source, Shifting(), batch_size=2).execute(
        source.describe("a.txt"), InMemoryIndex()
    )

    # Assert
    assert result.outcome is Outcome.FAILED
    assert "different sizes" in result.detail


@pytest.mark.parametrize(
    "error",
    [EmbeddingUnavailableError("down"), EmbeddingConfigError("no model")],
)
async def test_fatal_embedding_errors_stop_the_run(error: EmbeddingError):
    # Arrange
    source = FakeSource({"a.txt": b"one"})

    # Act / Assert
    with pytest.raises(type(error)):
        await _ingest(source, FakeEmbedder(error=error)).execute(
            source.describe("a.txt"), InMemoryIndex()
        )


async def test_an_index_write_rejection_fails_only_this_document():
    # Arrange
    source = FakeSource({"a.txt": b"one"})
    index = InMemoryIndex(fail_upsert=VectorIndexError("rejected"))

    # Act
    result = await _ingest(source).execute(source.describe("a.txt"), index)

    # Assert
    assert result.outcome is Outcome.FAILED


async def test_spans_cover_every_stage_without_document_text(spans: InMemorySpanExporter):
    # Arrange
    source = FakeSource({"a.txt": b"secret words\nmore"})

    # Act
    await _ingest(source).execute(source.describe("a.txt"), InMemoryIndex())

    # Assert
    names = span_names(spans)
    assert {"read", "parse", "chunk", "embeddings bag-of-words", "upsert kb", "delete kb"} <= set(
        names
    )
    document = span_by_name(spans, "ingest document")
    assert document.attributes is not None
    assert document.attributes["ingest.document.outcome"] == "indexed"
    embedding = span_by_name(spans, "embeddings bag-of-words")
    assert embedding.attributes is not None
    assert embedding.attributes["gen_ai.operation.name"] == "embeddings"
    assert embedding.attributes["gen_ai.embeddings.dimension.count"] == 32
    all_values = [str(v) for s in spans.get_finished_spans() for v in (s.attributes or {}).values()]
    assert not any("secret" in value for value in all_values)


async def test_a_failed_document_marks_its_span_as_error(spans: InMemorySpanExporter):
    # Arrange
    source = FakeSource({"a.txt": b"CORRUPT"})

    # Act
    await _ingest(source).execute(source.describe("a.txt"), InMemoryIndex())

    # Assert
    document = span_by_name(spans, "ingest document")
    assert not document.status.is_ok


def test_batch_size_must_be_positive():
    with pytest.raises(ValueError, match="embedding_batch_size"):
        _ingest(FakeSource(), batch_size=0)


def test_supported_media_types_come_from_the_parsers():
    assert _ingest(FakeSource()).media_types == frozenset({"text/plain"})
