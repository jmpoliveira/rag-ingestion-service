"""Use case: delete the whole collection, on purpose.

The old service dropped the collection on every run. Now it is an explicit, separate
command: the only way to change the embedding model of an existing collection, and never
a side effect of an ordinary sync.
"""

from __future__ import annotations

import logging

from src.application.ports import VectorIndexProvider
from src.application.telemetry import index_span

logger = logging.getLogger(__name__)


class ResetIndex:
    def __init__(self, index_provider: VectorIndexProvider, collection: str) -> None:
        self._index_provider = index_provider
        self._collection = collection

    async def execute(self) -> bool:
        """Returns False when the collection did not exist."""
        with index_span("drop", self._collection):
            dropped = await self._index_provider.drop(self._collection)
        logger.warning(
            "Collection dropped" if dropped else "Collection did not exist",
            extra={"collection": self._collection},
        )
        return dropped
