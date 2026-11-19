from __future__ import annotations

import pytest

from src.domain.documents import (
    Page,
    ParsedDocument,
    SourceDocument,
    chunk_id,
    document_version,
)
from src.domain.errors import EmbeddingUnavailableError, FatalError, IndexContractError
from src.domain.index import KEY_MODEL, IndexSpec
from src.domain.ingestion import DocumentResult, IngestionReport, Outcome

SPEC = IndexSpec(collection="kb", embedding_provider="ollama", embedding_model="nomic")


def test_document_version_changes_with_the_content_or_the_pipeline():
    # Act
    base = document_version("hash-a", "chunker:1")

    # Assert
    assert base == document_version("hash-a", "chunker:1")
    assert base != document_version("hash-b", "chunker:1")
    assert base != document_version("hash-a", "chunker:2")


def test_chunk_ids_are_deterministic_and_do_not_contain_the_path():
    # Act
    first = chunk_id("folder/My File.pdf", "v1", 3)

    # Assert
    assert first == chunk_id("folder/My File.pdf", "v1", 3)
    assert first != chunk_id("folder/My File.pdf", "v1", 4)
    assert "My File" not in first


def test_parsed_document_without_visible_text_has_no_text():
    # Arrange
    source = SourceDocument("a.pdf", "application/pdf", "h", 1)

    # Act / Assert
    assert not ParsedDocument(source, (Page(1, "  \n"), Page(2, ""))).has_text
    assert ParsedDocument(source, (Page(1, ""), Page(2, "x"))).has_text


def test_contract_accepts_a_collection_created_with_the_same_spec():
    SPEC.check(SPEC.as_metadata())  # must not raise


def test_contract_refuses_a_collection_without_a_contract():
    with pytest.raises(IndexContractError, match="no index contract"):
        SPEC.check({"hnsw:space": "l2"})
    with pytest.raises(IndexContractError):
        SPEC.check(None)


def test_contract_names_every_difference():
    # Arrange
    existing = {**SPEC.as_metadata(), KEY_MODEL: "other-model"}

    # Act
    with pytest.raises(IndexContractError) as caught:
        SPEC.check(existing)

    # Assert
    assert "other-model" in str(caught.value)
    assert "nomic" in str(caught.value)


def test_unavailable_embedder_is_both_an_embedding_error_and_fatal():
    assert issubclass(EmbeddingUnavailableError, FatalError)


def test_report_counts_every_outcome_and_flags_failures():
    # Arrange
    report = IngestionReport(
        (
            DocumentResult("a", Outcome.INDEXED, 3),
            DocumentResult("b", Outcome.FAILED, detail="x"),
            DocumentResult("c", Outcome.INDEXED, 1),
        )
    )

    # Act
    counts = report.counts

    # Assert
    assert counts[Outcome.INDEXED] == 2
    assert counts[Outcome.REMOVED] == 0
    assert report.failed
    assert not IngestionReport(()).failed
