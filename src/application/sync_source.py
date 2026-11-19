"""Use case: make the index match the source (the folder trigger, ADR 0002).

A sync is a reconciliation, not a reload: unchanged documents are skipped, changed ones are
re-ingested, and documents that disappeared from the source are removed from the index.
Running it twice in a row does nothing the second time.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from src.application.ingest_document import IngestDocument
from src.application.ports import DocumentSource, VectorIndex, VectorIndexProvider
from src.application.telemetry import (
    ATTR_SOURCE_DOCUMENTS,
    current_trace_id,
    index_span,
    sync_span,
)
from src.domain.documents import SourceDocument
from src.domain.index import IndexSpec
from src.domain.ingestion import DocumentResult, IngestionReport, Outcome

logger = logging.getLogger(__name__)


class SyncSource:
    def __init__(
        self,
        source: DocumentSource,
        ingest: IngestDocument,
        index_provider: VectorIndexProvider,
        spec: IndexSpec,
        *,
        delete_missing: bool = True,
    ) -> None:
        self._source = source
        self._ingest = ingest
        self._index_provider = index_provider
        self._spec = spec
        self._delete_missing = delete_missing

    async def execute(self) -> IngestionReport:
        """Raises:
        FatalError: (a subclass) when the source, the embedder or the index is unusable.
        """
        with sync_span(self._spec.collection) as span:
            documents = await self._source.list_documents()
            span.set_attribute(ATTR_SOURCE_DOCUMENTS, len(documents))
            logger.info(
                "Sync started",
                extra={"documents": len(documents), "collection": self._spec.collection},
            )
            async with self._index_provider.open(self._spec) as index:
                results = [await self._ingest.execute(doc, index) for doc in documents]
                removed, warnings = await self._remove_missing(documents, index)
            report = IngestionReport(tuple(results + removed), tuple(warnings), current_trace_id())
            logger.info(
                "Sync finished",
                extra={outcome.value: count for outcome, count in report.counts.items()},
            )
            return report

    async def _remove_missing(
        self, documents: Sequence[SourceDocument], index: VectorIndex
    ) -> tuple[list[DocumentResult], list[str]]:
        present = {document.document_id for document in documents}
        indexed = {item.document_id for item in await index.list_documents()}
        missing = sorted(indexed - present)
        if not missing:
            return [], []
        if not self._delete_missing:
            return [], [f"{len(missing)} indexed document(s) are no longer in the source"]
        if not documents:
            # An empty source usually means a wrong path or an unmounted volume, not that
            # every document was deleted on purpose. Wiping the index would be the worst
            # possible reaction to a configuration mistake.
            warning = (
                f"The source is empty: kept the {len(missing)} indexed document(s). "
                "Use the reset command to clear the index on purpose."
            )
            logger.warning(warning)
            return [], [warning]
        removed: list[DocumentResult] = []
        for document_id in missing:
            with index_span("delete", self._spec.collection):
                await index.delete(document_id)
            logger.info("Document removed", extra={"document_id": document_id})
            removed.append(DocumentResult(document_id, Outcome.REMOVED))
        return removed, []
