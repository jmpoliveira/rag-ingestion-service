"""Builders for eval tests: a tiny dataset and an index filled through the real pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from evals.dataset import Dataset
from evals.graders import Check, Scores
from evals.runner import CaseRecord
from src.application.ingest_document import IngestConfig, IngestDocument
from src.domain.documents import SearchHit
from tests.fakes import FakeChunker, FakeEmbedder, FakeParser, FakeSource, InMemoryIndex

STARTED = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def dataset(
    *cases: dict[str, Any],
    k: int = 2,
    version: int = 1,
    forbidden_sources: list[str] | None = None,
    forbidden_passages: list[dict[str, str]] | None = None,
) -> Dataset:
    return Dataset.model_validate(
        {
            "name": "kb",
            "version": version,
            "k": k,
            "corpus": "tests",
            "forbidden_sources": forbidden_sources or [],
            "forbidden_passages": forbidden_passages or [],
            "cases": list(cases),
        }
    )


def case(case_id: str, question: str, sources: list[str], **extra: Any) -> dict[str, Any]:
    expect: dict[str, Any] = {"sources": sources}
    for key in ("evidence_any", "forbidden_sources"):
        if key in extra:
            expect[key] = extra.pop(key)
    return {"id": case_id, "question": question, "expect": expect, **extra}


async def filled_index(files: dict[str, str]) -> InMemoryIndex:
    """Index ``files`` (id -> text, one chunk per line) with the bag-of-words embedder."""
    source = FakeSource({key: value.encode() for key, value in files.items()})
    ingest = IngestDocument(
        source, [FakeParser()], FakeChunker(), FakeEmbedder(), IngestConfig("kb", 8)
    )
    index = InMemoryIndex()
    for document in await source.list_documents():
        await ingest.execute(document, index)
    return index


def hit(document_id: str, text: str = "", page: int = 1) -> SearchHit:
    return SearchHit(f"{document_id}:{page}", document_id, page, text, 0.1)


def record(
    case_id: str = "c1", *, passed: bool = True, trace_id: str | None = "ab" * 16
) -> CaseRecord:
    return CaseRecord(
        case_id=case_id,
        question="Where?",
        tags=("tag",),
        hits=(hit("a.md", "answer here"),),
        scores=Scores(
            hit=passed,
            reciprocal_rank=1.0 if passed else 0.0,
            recall=float(passed),
            first_relevant_rank=1 if passed else None,
        ),
        checks=(Check("hit@2", passed, "detail"), Check("recall@2", passed)),
        latency_seconds=0.25,
        started_at=STARTED,
        trace_id=trace_id,
    )
