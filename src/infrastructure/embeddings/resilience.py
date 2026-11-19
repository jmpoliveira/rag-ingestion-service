"""Retry for transient embedding failures, as a decorator around any ``Embedder``.

Only ``EmbeddingUnavailableError`` is retried (network, timeout, 429, 5xx). A missing model
or a malformed answer fails the same way every time, so retrying would only add delay.
Backoff is exponential with full jitter, so several workers restarting together do not
retry in lockstep.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from src.application.ports import Embedder
from src.domain.errors import EmbeddingUnavailableError

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("delays must satisfy 0 <= base_delay_seconds <= max_delay_seconds")

    def delay(self, attempt: int, jitter: float) -> float:
        """Delay before retry number ``attempt`` (1-based); ``jitter`` is in [0, 1)."""
        ceiling = min(self.max_delay_seconds, self.base_delay_seconds * 2 ** (attempt - 1))
        return ceiling * jitter


class RetryingEmbedder:
    def __init__(
        self,
        inner: Embedder,
        policy: RetryPolicy,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,  # not for security: spreads retries only
    ) -> None:
        self._inner = inner
        self._policy = policy
        self._sleep = sleep
        self._jitter = jitter

    @property
    def provider(self) -> str:
        return self._inner.provider

    @property
    def model(self) -> str:
        return self._inner.model

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return await self._retry(lambda: self._inner.embed_documents(texts))

    async def embed_query(self, text: str) -> Sequence[float]:
        return await self._retry(lambda: self._inner.embed_query(text))

    async def _retry(self, call: Callable[[], Awaitable[T]]) -> T:
        attempt = 1
        while True:
            try:
                return await call()
            except EmbeddingUnavailableError as err:
                if attempt >= self._policy.max_attempts:
                    raise
                delay = self._policy.delay(attempt, self._jitter())
                logger.warning(
                    "Embedding request failed, retrying",
                    extra={"attempt": attempt, "delay_seconds": round(delay, 2), "error": str(err)},
                )
                await self._sleep(delay)
                attempt += 1
