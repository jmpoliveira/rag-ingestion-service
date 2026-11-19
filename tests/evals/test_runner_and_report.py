from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from evals.__main__ import EXIT_BELOW_THRESHOLD, EXIT_OK, EXIT_USAGE, RunOptions, run_evals
from evals.report import ReportError, load_report, render, summarise, write_report
from evals.runner import EvalAbortedError, RetrievalEvalRunner
from src.domain.errors import EmbeddingUnavailableError
from src.domain.index import IndexSpec
from tests.evals.helpers import case, dataset, filled_index, record
from tests.fakes import FakeEmbedder, InMemoryIndexProvider

FILES = {
    "refunds.md": "refund within 30 days of purchase\nmonthly plans are not refunded",
    "sla.md": "urgent tickets answered within 1 hour\nsupport hours are 08:00 to 18:00",
}
DATA = dataset(
    case(
        "refund",
        "refund within 30 days",
        ["refunds.md"],
        tags=["refunds"],
        evidence_any=["30 days"],
    ),
    case("hours", "support hours 08:00", ["sla.md"], tags=["sla"]),
    case("miss", "nothing matches xyz", ["missing-from-top.md"]),
)
SPEC = IndexSpec("kb", "fake", "bag-of-words")


async def test_runner_scores_each_case_in_its_own_trace(spans: InMemorySpanExporter):
    # Arrange
    index = await filled_index(FILES)
    embedder = FakeEmbedder()
    runner = RetrievalEvalRunner(DATA, embedder, index)

    # Act
    records = await runner.run(DATA.cases[:2])

    # Assert
    assert [r.passed for r in records] == [True, True]
    assert records[0].scores.first_relevant_rank == 1
    assert embedder.queries == ["refund within 30 days", "support hours 08:00"]
    eval_spans = [s for s in spans.get_finished_spans() if s.name.startswith("retrieval_eval")]
    assert {f"{s.context.trace_id:032x}" for s in eval_spans} == {r.trace_id for r in records}  # type: ignore[union-attr]


async def test_corpus_check_fails_fast_when_documents_are_missing():
    # Arrange
    index = await filled_index(FILES)

    # Act / Assert
    with pytest.raises(EvalAbortedError, match=r"missing-from-top\.md"):
        await RetrievalEvalRunner(DATA, FakeEmbedder(), index).check_corpus()


async def test_an_unavailable_embedder_aborts_the_eval():
    # Arrange
    index = await filled_index(FILES)
    embedder = FakeEmbedder(error=EmbeddingUnavailableError("down"))

    # Act / Assert
    with pytest.raises(EvalAbortedError):
        await RetrievalEvalRunner(DATA, embedder, index).run(DATA.cases[:1])


def test_summary_metrics_and_per_tag():
    # Arrange
    records = [record("a", passed=True), record("b", passed=False)]

    # Act
    summary = summarise(records)

    # Assert
    assert summary.cases == 2
    assert summary.hit_rate == pytest.approx(0.5)
    assert summary.mrr == pytest.approx(0.5)
    assert summary.evidence_rate is None
    assert summary.per_tag["tag"]["hit_rate"] == pytest.approx(0.5)


def test_report_round_trips_through_json(tmp_path: Path):
    # Arrange
    records = [record("a"), record("b", passed=False, trace_id=None)]
    path = tmp_path / "r.json"

    # Act
    write_report(path, {"k": 2}, summarise(records), records)
    saved = load_report(path)

    # Assert
    assert saved.records == records
    assert saved.summary["hit_rate"] == pytest.approx(0.5)


@pytest.mark.parametrize("content", ["not json", "[]", '{"meta": {}}'])
def test_unreadable_reports_are_rejected(tmp_path: Path, content: str):
    # Arrange
    path = tmp_path / "r.json"
    path.write_text(content, encoding="utf-8")

    # Act / Assert
    with pytest.raises(ReportError):
        load_report(path)


def test_render_shows_failures_and_warns_on_a_different_baseline_dataset():
    # Arrange
    records = [record("a"), record("b", passed=False)]
    baseline: dict[str, Any] = {
        "meta": {"dataset_fingerprint": "old", "embedding_model": "m0"},
        "summary": {"pass_rate": 1.0, "hit_rate": 1.0, "mrr": 1.0, "mean_recall": 1.0},
    }

    # Act
    text = render({"k": 2, "dataset_fingerprint": "new"}, summarise(records), records, baseline)

    # Assert
    assert "b [hit@2] detail" in text
    assert "another dataset" in text
    assert "hit_rate     1.000 -> 0.500 (-0.500)" in text


async def test_run_evals_writes_the_report_and_applies_the_threshold(tmp_path: Path):
    # Arrange
    provider = InMemoryIndexProvider(await filled_index(FILES))
    data = dataset(*[c.model_dump(mode="json") for c in DATA.cases[:2]])
    out = io.StringIO()
    options = RunOptions(dataset=Path("unused"), output_dir=tmp_path, fail_under=1.0)

    # Act
    code = await run_evals(options, data, FakeEmbedder(), provider, SPEC, {"k": 2}, out)

    # Assert
    assert code == EXIT_OK
    [report] = [p for p in tmp_path.iterdir() if p.name.endswith("-kb-kb.json")]  # noqa: ASYNC240
    assert json.loads(report.read_text())["summary"]["hit_rate"] == 1.0
    assert "Report:" in out.getvalue()


async def test_run_evals_below_the_threshold_exits_one(tmp_path: Path):
    # Arrange: "miss" expects a document that is not indexed, so check_corpus is skipped by
    # indexing a decoy with that id
    files = {**FILES, "missing-from-top.md": "zzz qqq"}
    provider = InMemoryIndexProvider(await filled_index(files))
    options = RunOptions(dataset=Path("unused"), output_dir=tmp_path, fail_under=1.0)
    data = dataset(case("miss", "refund within 30 days", ["missing-from-top.md"]), k=1)

    # Act
    code = await run_evals(options, data, FakeEmbedder(), provider, SPEC, {}, io.StringIO())

    # Assert
    assert code == EXIT_BELOW_THRESHOLD


async def test_run_evals_with_no_matching_case_is_a_usage_error(tmp_path: Path):
    # Arrange
    options = RunOptions(dataset=Path("unused"), output_dir=tmp_path, cases=frozenset({"nope"}))

    # Act
    code = await run_evals(
        options, DATA, FakeEmbedder(), InMemoryIndexProvider(), SPEC, {}, io.StringIO()
    )

    # Assert
    assert code == EXIT_USAGE
