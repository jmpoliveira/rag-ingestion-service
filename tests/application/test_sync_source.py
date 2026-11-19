from __future__ import annotations

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.application.ingest_document import IngestConfig, IngestDocument
from src.application.reset_index import ResetIndex
from src.application.sync_source import SyncSource
from src.domain.errors import EmbeddingUnavailableError
from src.domain.index import IndexSpec
from src.domain.ingestion import Outcome
from tests.conftest import span_by_name
from tests.fakes import (
    FakeChunker,
    FakeEmbedder,
    FakeParser,
    FakeSource,
    InMemoryIndexProvider,
)

SPEC = IndexSpec(collection="kb", embedding_provider="fake", embedding_model="bag-of-words")


def _sync(
    source: FakeSource,
    provider: InMemoryIndexProvider,
    *,
    embedder: FakeEmbedder | None = None,
    delete_missing: bool = True,
) -> SyncSource:
    ingest = IngestDocument(
        source,
        [FakeParser()],
        FakeChunker(),
        embedder or FakeEmbedder(),
        IngestConfig(collection="kb", embedding_batch_size=8),
    )
    return SyncSource(source, ingest, provider, SPEC, delete_missing=delete_missing)


async def test_first_sync_indexes_every_document():
    # Arrange
    source = FakeSource({"a.txt": b"a1\na2", "b.txt": b"b1"})
    provider = InMemoryIndexProvider()

    # Act
    report = await _sync(source, provider).execute()

    # Assert
    assert report.counts[Outcome.INDEXED] == 2
    assert provider.index.documents() == {"a.txt": ["a1", "a2"], "b.txt": ["b1"]}
    assert provider.opened == [SPEC]


async def test_second_sync_without_changes_does_nothing():
    # Arrange
    source = FakeSource({"a.txt": b"a1", "b.txt": b"b1"})
    provider = InMemoryIndexProvider()
    await _sync(source, provider).execute()
    provider.index.operations.clear()

    # Act
    report = await _sync(source, provider).execute()

    # Assert
    assert report.counts[Outcome.UNCHANGED] == 2
    assert provider.index.operations == []


async def test_a_document_removed_from_the_source_is_removed_from_the_index():
    # Arrange
    source = FakeSource({"a.txt": b"a1", "b.txt": b"b1"})
    provider = InMemoryIndexProvider()
    await _sync(source, provider).execute()
    del source.files["b.txt"]

    # Act
    report = await _sync(source, provider).execute()

    # Assert
    assert [r.document_id for r in report.results if r.outcome is Outcome.REMOVED] == ["b.txt"]
    assert provider.index.documents() == {"a.txt": ["a1"]}


async def test_an_empty_source_never_wipes_the_index():
    # Arrange: a wrong path or an unmounted volume looks like an empty folder
    source = FakeSource({"a.txt": b"a1"})
    provider = InMemoryIndexProvider()
    await _sync(source, provider).execute()
    source.files.clear()

    # Act
    report = await _sync(source, provider).execute()

    # Assert
    assert provider.index.documents() == {"a.txt": ["a1"]}
    assert "source is empty" in report.warnings[0]


async def test_deletion_can_be_disabled():
    # Arrange
    source = FakeSource({"a.txt": b"a1", "b.txt": b"b1"})
    provider = InMemoryIndexProvider()
    await _sync(source, provider).execute()
    del source.files["b.txt"]

    # Act
    report = await _sync(source, provider, delete_missing=False).execute()

    # Assert
    assert "b.txt" in provider.index.documents()
    assert "no longer in the source" in report.warnings[0]


async def test_one_failed_document_does_not_stop_the_others():
    # Arrange
    source = FakeSource({"a.txt": b"CORRUPT", "b.txt": b"b1"})
    provider = InMemoryIndexProvider()

    # Act
    report = await _sync(source, provider).execute()

    # Assert
    assert report.failed
    assert report.counts[Outcome.INDEXED] == 1


async def test_a_fatal_error_stops_the_sync():
    # Arrange
    source = FakeSource({"a.txt": b"a1", "b.txt": b"b1"})
    embedder = FakeEmbedder(error=EmbeddingUnavailableError("down"))

    # Act / Assert
    with pytest.raises(EmbeddingUnavailableError):
        await _sync(source, InMemoryIndexProvider(), embedder=embedder).execute()
    assert len(embedder.calls) == 1  # stopped at the first document


async def test_the_report_carries_the_trace_id_of_the_sync_span(spans: InMemorySpanExporter):
    # Arrange
    source = FakeSource({"a.txt": b"a1"})

    # Act
    report = await _sync(source, InMemoryIndexProvider()).execute()

    # Assert
    root = span_by_name(spans, "ingest sync")
    assert report.trace_id == f"{root.context.trace_id:032x}"  # type: ignore[union-attr]
    assert root.attributes is not None
    assert root.attributes["ingest.source.documents"] == 1


async def test_reset_drops_the_collection():
    # Arrange
    source = FakeSource({"a.txt": b"a1"})
    provider = InMemoryIndexProvider()
    await _sync(source, provider).execute()

    # Act
    dropped = await ResetIndex(provider, "kb").execute()

    # Assert
    assert dropped
    assert provider.dropped == ["kb"]
    assert provider.index.documents() == {}
