"""The outcome of ingesting documents."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum


class Outcome(StrEnum):
    INDEXED = "indexed"  # new or changed: chunks written
    UNCHANGED = "unchanged"  # same content and pipeline already in the index: nothing done
    EMPTY = "empty"  # no extractable text (for example a scanned PDF): nothing indexed
    FAILED = "failed"  # rejected or failed; any previous version stays in the index
    REMOVED = "removed"  # gone from the source: its chunks were deleted


@dataclass(frozen=True, slots=True)
class DocumentResult:
    document_id: str
    outcome: Outcome
    chunks: int = 0
    detail: str = ""


@dataclass(frozen=True, slots=True)
class IngestionReport:
    results: tuple[DocumentResult, ...]
    warnings: tuple[str, ...] = field(default=())
    trace_id: str | None = None

    @property
    def counts(self) -> dict[Outcome, int]:
        found = Counter(result.outcome for result in self.results)
        return {outcome: found.get(outcome, 0) for outcome in Outcome}

    @property
    def failed(self) -> bool:
        return any(result.outcome is Outcome.FAILED for result in self.results)
