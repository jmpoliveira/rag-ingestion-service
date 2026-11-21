"""Runs the cases against the real embedder and the real index.

Retrieval with a fixed model and index is deterministic, so each case runs once (unlike the
agent evals, which repeat runs to measure a non-deterministic model). Each case is its own
trace, so a bad result can be opened in Jaeger or Phoenix: query embedding, then search.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from opentelemetry import trace

from evals.dataset import Case, Dataset
from evals.graders import Check, Scores, grade
from src.application.ports import Embedder, VectorIndex
from src.domain.documents import SearchHit
from src.domain.errors import FatalError

_tracer = trace.get_tracer("rag_ingestion_service.evals")


class EvalAbortedError(RuntimeError):
    """The environment is broken (index empty, embedder down): every case would fail."""


@dataclass(frozen=True, slots=True)
class CaseRecord:
    case_id: str
    question: str
    tags: tuple[str, ...]
    hits: tuple[SearchHit, ...]
    scores: Scores
    checks: tuple[Check, ...]
    latency_seconds: float
    started_at: datetime
    trace_id: str | None = None

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


class RetrievalEvalRunner:
    def __init__(
        self,
        dataset: Dataset,
        embedder: Embedder,
        index: VectorIndex,
        *,
        on_record: Callable[[CaseRecord], None] | None = None,
    ) -> None:
        self._dataset = dataset
        self._embedder = embedder
        self._index = index
        self._on_record = on_record

    async def check_corpus(self) -> None:
        """Fail fast when the dataset's documents are not in the collection."""
        indexed = {item.document_id for item in await self._index.list_documents()}
        missing = sorted(self._dataset.sources - indexed)
        if missing:
            raise EvalAbortedError(
                f"{len(missing)} expected document(s) are not in the collection, for example "
                f"{missing[0]!r}. Ingest the corpus first: {self._dataset.corpus or '?'}"
            )

    async def run(self, cases: Sequence[Case]) -> list[CaseRecord]:
        records: list[CaseRecord] = []
        for case in cases:
            record = await self._run_case(case)
            records.append(record)
            if self._on_record:
                self._on_record(record)
        return records

    async def _run_case(self, case: Case) -> CaseRecord:
        k = self._dataset.k
        started = datetime.now(UTC)
        clock = time.perf_counter()
        with _tracer.start_as_current_span(
            f"retrieval_eval {case.id}", attributes={"eval.case.id": case.id, "eval.k": k}
        ) as span:
            try:
                vector = await self._embedder.embed_query(case.question)
                hits = tuple(await self._index.search(vector, k))
            except FatalError as err:
                raise EvalAbortedError(str(err)) from err
            scores, checks = grade(
                hits,
                case.expect,
                k,
                self._dataset.forbidden_for(case),
                self._dataset.passages,
            )
            span.set_attribute("eval.passed", all(check.passed for check in checks))
            context = span.get_span_context()
        return CaseRecord(
            case_id=case.id,
            question=case.question,
            tags=case.tags,
            hits=hits,
            scores=scores,
            checks=checks,
            latency_seconds=time.perf_counter() - clock,
            started_at=started,
            trace_id=f"{context.trace_id:032x}" if context.is_valid else None,
        )
