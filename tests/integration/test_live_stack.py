"""Smoke test against the real stack: Ollama and Chroma from your .env (docker-env).

Skipped unless pytest runs with ``--live`` (``make test-live``): CI has neither service.
It proves what the unit tests cannot: that the configured embedding model answers, that
Chroma accepts our writes and filters, and that a second sync is a no-op. It writes only
to a temporary collection, which is dropped at the end, even when an assertion fails.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

import main
from config.settings import Settings, get_settings
from src.domain.index import KEY_MODEL
from src.domain.ingestion import Outcome

pytestmark = pytest.mark.live

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "knowledge-base"
SAMPLE_DOCUMENTS = 6


@pytest.fixture
async def live_settings() -> AsyncIterator[Settings]:
    """Your .env, pointed at the samples and at a throwaway collection."""
    get_settings.cache_clear()
    settings = get_settings().model_copy(
        update={
            "source_dir": SAMPLES,
            "chroma_collection": f"live-test-{uuid.uuid4().hex[:8]}",
        }
    )
    try:
        yield settings
    finally:
        await main.build_reset(settings).execute()
        get_settings.cache_clear()


async def test_sync_writes_every_sample_and_a_second_sync_does_nothing(
    live_settings: Settings,
):
    # Act
    first = await main.build_sync(live_settings).execute()
    second = await main.build_sync(live_settings).execute()

    # Assert
    assert first.counts[Outcome.INDEXED] == SAMPLE_DOCUMENTS, first.results
    assert not first.failed
    assert second.counts[Outcome.UNCHANGED] == SAMPLE_DOCUMENTS, second.results


async def test_the_collection_records_the_contract_and_real_vectors(live_settings: Settings):
    # Arrange
    await main.build_sync(live_settings).execute()

    # Act
    inspection = await main.build_inspect(live_settings).execute("refund-policy.md")

    # Assert
    assert inspection.info is not None
    assert inspection.contract_problem is None
    assert inspection.info.metadata[KEY_MODEL] == live_settings.embedding_model
    assert len(inspection.documents) == SAMPLE_DOCUMENTS
    assert inspection.chunks, "refund-policy.md has no chunks"
    dimensions = {chunk.dimensions for chunk in inspection.chunks}
    assert len(dimensions) == 1
    assert dimensions.pop() > 0


async def test_a_question_finds_its_document_through_the_real_embeddings(
    live_settings: Settings,
):
    # Arrange: a sanity check of the whole path, not a quality metric (that is `make eval`)
    await main.build_sync(live_settings).execute()
    embedder = main.build_embedder(live_settings)
    spec = main.build_index_spec(live_settings, embedder)

    # Act
    vector = await embedder.embed_query("Do you give refunds for monthly subscriptions?")
    async with main.build_index_provider(live_settings).open(spec) as index:
        hits = await index.search(vector, 3)

    # Assert
    assert "refund-policy.md" in [hit.document_id for hit in hits], hits
