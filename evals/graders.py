"""Code-based retrieval metrics for one case.

- **hit@k**: a relevant document is in the top k. The question "can the agent find it at all?".
- **reciprocal rank**: 1 / rank of the first relevant chunk (0 when absent). Averaged over
  cases it is the MRR: whether the right chunk comes *first*, which matters because the agent
  reads the top results and the context window is finite.
- **recall@k**: share of the relevant documents found, for questions that need several.
- **evidence**: a relevant chunk in the top k contains the answer text. A hit on the right
  document with the wrong chunk is a chunking problem, not an embedding problem.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from evals.dataset import Expect
from src.domain.documents import SearchHit

_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Scores:
    hit: bool
    reciprocal_rank: float
    recall: float
    first_relevant_rank: int | None


def score(hits: Sequence[SearchHit], expect: Expect) -> Scores:
    relevant = set(expect.sources)
    ranks = [rank for rank, hit in enumerate(hits, start=1) if hit.document_id in relevant]
    found = {hit.document_id for hit in hits} & relevant
    first = ranks[0] if ranks else None
    return Scores(
        hit=first is not None,
        reciprocal_rank=1 / first if first else 0.0,
        recall=len(found) / len(relevant),
        first_relevant_rank=first,
    )


def grade(hits: Sequence[SearchHit], expect: Expect, k: int) -> tuple[Scores, tuple[Check, ...]]:
    scores = score(hits, expect)
    retrieved = ", ".join(f"{hit.document_id}#p{hit.page}" for hit in hits) or "nothing"
    checks = [
        Check(
            f"hit@{k}",
            scores.hit,
            f"first relevant at rank {scores.first_relevant_rank}"
            if scores.hit
            else f"no relevant document in the top {k}: {retrieved}",
        ),
        Check(
            f"recall@{k}",
            scores.recall == 1.0,
            f"found {scores.recall:.0%} of {sorted(expect.sources)}",
        ),
    ]
    if expect.evidence_any:
        checks.append(_evidence(hits, expect))
    return scores, tuple(checks)


def _evidence(hits: Sequence[SearchHit], expect: Expect) -> Check:
    wanted = [_normalise(text) for text in expect.evidence_any]
    for rank, hit in enumerate(hits, start=1):
        if hit.document_id in expect.sources and any(w in _normalise(hit.text) for w in wanted):
            return Check("evidence", True, f"answer text in the chunk at rank {rank}")
    return Check(
        "evidence", False, f"no relevant chunk contains any of {list(expect.evidence_any)}"
    )


def _normalise(text: str) -> str:
    return _SPACES.sub(" ", text).strip().casefold()
