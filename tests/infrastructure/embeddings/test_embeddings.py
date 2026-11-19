from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_ollama import OllamaEmbeddings
from ollama import ResponseError

from src.domain.errors import (
    EmbeddingConfigError,
    EmbeddingError,
    EmbeddingUnavailableError,
)
from src.infrastructure.embeddings.ollama import OllamaEmbedder, create_ollama_embedder
from src.infrastructure.embeddings.resilience import RetryingEmbedder, RetryPolicy
from tests.fakes import FakeEmbedder


def _ollama(answer: Any = None, error: Exception | None = None) -> tuple[OllamaEmbedder, AsyncMock]:
    embeddings = OllamaEmbeddings(model="nomic-embed-text", base_url="http://ollama.test")
    mock = AsyncMock(return_value=answer, side_effect=error)
    object.__setattr__(embeddings, "aembed_documents", mock)
    embedder = OllamaEmbedder(
        embeddings, document_prefix="search_document: ", query_prefix="search_query: "
    )
    return embedder, mock


async def test_documents_and_queries_get_their_task_prefixes():
    # Arrange
    embedder, mock = _ollama(answer=[[0.1, 0.2]])

    # Act
    await embedder.embed_documents(["chunk"])
    await embedder.embed_query("question")

    # Assert
    assert mock.await_args_list[0].args == (["search_document: chunk"],)
    assert mock.await_args_list[1].args == (["search_query: question"],)
    assert embedder.provider == "ollama"
    assert embedder.model == "nomic-embed-text"


async def test_a_query_without_a_vector_is_an_error():
    embedder, _ = _ollama(answer=[])
    with pytest.raises(EmbeddingError, match="no vector"):
        await embedder.embed_query("q")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ResponseError("model not found", 404), EmbeddingConfigError),
        (ResponseError("unauthorized", 401), EmbeddingConfigError),
        (ResponseError("busy", 503), EmbeddingUnavailableError),
        (ResponseError("slow down", 429), EmbeddingUnavailableError),
        (ResponseError("bad input", 400), EmbeddingError),
        (ConnectionError("refused"), EmbeddingUnavailableError),
        (httpx.ReadTimeout("timeout"), EmbeddingUnavailableError),
    ],
)
async def test_provider_errors_are_translated(error: Exception, expected: type[Exception]):
    # Arrange
    embedder, _ = _ollama(error=error)

    # Act / Assert
    with pytest.raises(expected) as caught:
        await embedder.embed_documents(["x"])
    assert type(caught.value) is expected


def test_the_factory_does_not_call_the_network():
    # Act
    embedder = create_ollama_embedder(
        base_url="http://ollama.test:11434", model="m", timeout_seconds=5
    )

    # Assert
    assert embedder.model == "m"


def _policy(attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(max_attempts=attempts, base_delay_seconds=1, max_delay_seconds=3)


async def test_retry_recovers_from_a_transient_failure():
    # Arrange
    inner = FakeEmbedder(error=EmbeddingUnavailableError("down"))
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)
        inner.error = None  # the provider comes back

    embedder = RetryingEmbedder(inner, _policy(), sleep=sleep, jitter=lambda: 1.0)

    # Act
    vectors = await embedder.embed_documents(["a"])

    # Assert
    assert len(vectors) == 1
    assert sleeps == [1.0]
    assert (embedder.provider, embedder.model) == ("fake", "bag-of-words")


async def test_retry_gives_up_after_the_last_attempt_with_capped_backoff():
    # Arrange
    inner = FakeEmbedder(error=EmbeddingUnavailableError("down"))
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    embedder = RetryingEmbedder(inner, _policy(attempts=4), sleep=sleep, jitter=lambda: 1.0)

    # Act / Assert
    with pytest.raises(EmbeddingUnavailableError):
        await embedder.embed_query("q")
    assert sleeps == [1.0, 2.0, 3.0]  # 1, 2, then capped at 3 instead of 4


async def test_errors_that_retrying_cannot_fix_are_not_retried():
    # Arrange
    inner = FakeEmbedder(error=EmbeddingConfigError("no model"))
    embedder = RetryingEmbedder(inner, _policy(), sleep=AsyncMock())

    # Act / Assert
    with pytest.raises(EmbeddingConfigError):
        await embedder.embed_documents(["a"])
    assert len(inner.calls) == 1


@pytest.mark.parametrize(("attempts", "base", "maximum"), [(0, 1, 1), (1, -1, 1), (1, 2, 1)])
def test_invalid_retry_policy(attempts: int, base: float, maximum: float):
    with pytest.raises(ValueError, match="must"):
        RetryPolicy(max_attempts=attempts, base_delay_seconds=base, max_delay_seconds=maximum)
