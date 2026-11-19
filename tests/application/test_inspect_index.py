from __future__ import annotations

from src.application.inspect_index import InspectIndex
from src.domain.index import KEY_MODEL, IndexSpec
from tests.evals.helpers import filled_index
from tests.fakes import InMemoryIndexProvider

SPEC = IndexSpec(collection="kb", embedding_provider="fake", embedding_model="bag-of-words")


async def test_a_missing_collection_is_reported_and_not_created():
    # Arrange
    provider = InMemoryIndexProvider()

    # Act
    inspection = await InspectIndex(provider, SPEC).execute()

    # Assert
    assert not inspection.exists
    assert provider.opened == []
    assert provider.metadata is None


async def test_a_collection_under_another_contract_is_described_but_not_opened():
    # Arrange
    provider = InMemoryIndexProvider(metadata={**SPEC.as_metadata(), KEY_MODEL: "other"})

    # Act
    inspection = await InspectIndex(provider, SPEC).execute("a.txt")

    # Assert
    assert inspection.info is not None
    assert inspection.info.metadata[KEY_MODEL] == "other"
    assert inspection.contract_problem is not None
    assert "other" in inspection.contract_problem
    assert provider.opened == []


async def test_lists_complete_documents_and_the_chunks_of_one():
    # Arrange
    index = await filled_index({"a.txt": "one\ntwo", "b.txt": "three"})
    provider = InMemoryIndexProvider(index, metadata=dict(SPEC.as_metadata()))

    # Act
    inspection = await InspectIndex(provider, SPEC).execute("a.txt")

    # Assert
    assert inspection.info is not None
    assert inspection.info.chunks == 3
    assert sorted(d.document_id for d in inspection.documents) == ["a.txt", "b.txt"]
    assert [(c.chunk_index, c.text, c.dimensions) for c in inspection.chunks] == [
        (0, "one", 32),
        (1, "two", 32),
    ]


async def test_without_a_document_no_chunks_are_read():
    # Arrange
    index = await filled_index({"a.txt": "one"})
    provider = InMemoryIndexProvider(index, metadata=dict(SPEC.as_metadata()))

    # Act
    inspection = await InspectIndex(provider, SPEC).execute()

    # Assert
    assert inspection.chunks == ()
    assert len(inspection.documents) == 1
