"""Use case: look inside a collection without changing it.

Answers the questions you ask while learning or debugging: does the collection exist, which
contract was it created with, which documents are complete in it, and what exactly was stored
for one document (chunk ids, versions, pages, vector size, text). It never creates a
collection: a missing one is reported, not made.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from src.application.ports import VectorIndexProvider
from src.application.telemetry import index_span
from src.domain.documents import CollectionInfo, IndexedDocument, StoredChunk
from src.domain.errors import IndexContractError
from src.domain.index import IndexSpec


@dataclass(frozen=True, slots=True)
class Inspection:
    collection: str
    info: CollectionInfo | None
    # Why the collection does not match the settings; None when it matches.
    contract_problem: str | None = None
    documents: Sequence[IndexedDocument] = field(default=())
    chunks: Sequence[StoredChunk] = field(default=())

    @property
    def exists(self) -> bool:
        return self.info is not None


class InspectIndex:
    def __init__(self, index_provider: VectorIndexProvider, spec: IndexSpec) -> None:
        self._index_provider = index_provider
        self._spec = spec

    async def execute(self, document_id: str | None = None) -> Inspection:
        name = self._spec.collection
        with index_span("describe", name):
            info = await self._index_provider.describe(name)
        if info is None:
            return Inspection(name, None)
        try:
            self._spec.check(info.metadata)
        except IndexContractError as err:
            # Still useful: shows what the collection *was* built with.
            return Inspection(name, info, contract_problem=str(err))
        # Exists and matches, so opening it neither creates nor changes anything.
        async with self._index_provider.open(self._spec) as index:
            with index_span("get", name):
                documents = await index.list_documents()
                chunks = await index.get_chunks(document_id) if document_id else ()
        return Inspection(name, info, documents=documents, chunks=chunks)
