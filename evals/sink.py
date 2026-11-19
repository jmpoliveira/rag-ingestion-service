"""Port for publishing eval results somewhere they can be explored (ADR 0005).

The JSON report is the source of truth: written first, committed as a baseline. A sink is a
view of it. Phoenix is the first implementation, as in ai-agent-service.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from evals.dataset import Dataset
from evals.runner import CaseRecord


@dataclass(frozen=True, slots=True)
class EvalResults:
    dataset: Dataset
    meta: Mapping[str, Any]
    records: Sequence[CaseRecord]
    # The report file name: identifies the run, so publishing it twice can be detected.
    report_name: str


@dataclass(frozen=True, slots=True)
class Published:
    url: str
    created: bool  # False when this report had already been published


class SinkError(RuntimeError):
    """The results could not be published. The report itself is not affected."""


class ResultSink(Protocol):
    async def publish(self, results: EvalResults) -> Published: ...


SinkFactory = Callable[[], AbstractAsyncContextManager[ResultSink]]
