from __future__ import annotations

import io
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from phoenix.client import AsyncClient

import evals.__main__ as cli
from config.settings import PhoenixSettings
from evals.phoenix_sink import PhoenixSink, open_phoenix_sink, phoenix_dataset_name
from evals.report import summarise, write_report
from evals.sink import EvalResults, Published, ResultSink, SinkError
from tests.evals.helpers import case, dataset, record
from tests.evals.phoenix_fake import FakePhoenix

DATA = dataset(case("c1", "Where?", ["a.md"], tags=["tag"]), case("c2", "Why?", ["b.md"]))
META: dict[str, Any] = {
    "embedding_model": "nomic-embed-text",
    "k": 2,
    "collection": "kb",
    "started_at": "2026-11-19T12:00:00+00:00",
    "dataset_fingerprint": DATA.fingerprint,
    "not_copied": "x",
}


def _results(report: str = "20261119-120000-kb-kb.json") -> EvalResults:
    return EvalResults(DATA, META, [record("c1"), record("c2", passed=False)], report)


async def _publish(fake: FakePhoenix, results: EvalResults) -> Published:
    async with fake.client() as http:
        return await PhoenixSink(AsyncClient(http_client=http)).publish(results)


async def test_publish_creates_dataset_experiment_runs_and_metric_evaluations():
    # Arrange
    fake = FakePhoenix()

    # Act
    published = await _publish(fake, _results())

    # Assert
    assert published.created
    [phoenix_dataset] = fake.datasets.values()
    assert phoenix_dataset["name"] == phoenix_dataset_name(DATA)
    [experiment] = fake.experiments
    assert experiment["metadata"]["report"] == "20261119-120000-kb-kb.json"
    assert experiment["metadata"]["embedding_model"] == "nomic-embed-text"
    assert "not_copied" not in experiment["metadata"]
    assert len(fake.runs) == 2
    assert fake.runs[0]["trace_id"] == "ab" * 16
    assert fake.runs[0]["output"]["hits"][0]["document_id"] == "a.md"
    first = fake.evaluations_for(fake.runs[0]["id"])
    assert set(first) == {"reciprocal_rank", "hit@2", "recall@2", "passed"}
    assert first["reciprocal_rank"]["result"]["label"] == "rank 1"
    second = fake.evaluations_for(fake.runs[1]["id"])
    assert second["passed"]["result"]["score"] == 0.0
    assert "hit@2" in second["passed"]["result"]["explanation"]


async def test_publishing_the_same_report_twice_does_nothing_new():
    # Arrange
    fake = FakePhoenix()
    await _publish(fake, _results())

    # Act
    again = await _publish(fake, _results())

    # Assert
    assert not again.created
    assert len(fake.experiments) == 1
    assert fake.uploads == 1


async def test_a_phoenix_failure_becomes_a_sink_error():
    # Arrange
    fake = FakePhoenix(fail_with=500)

    # Act / Assert
    with pytest.raises(SinkError):
        await _publish(fake, _results())


async def test_open_sink_needs_a_base_url():
    with pytest.raises(SinkError, match="PHOENIX_BASE_URL"):
        async with open_phoenix_sink(PhoenixSettings(_env_file=None, base_url=None)):  # type: ignore[call-arg]
            pass


async def test_open_sink_builds_an_authenticated_client():
    # Arrange
    settings = PhoenixSettings(_env_file=None, base_url="http://phoenix.test:6006", api_key="k")  # type: ignore[call-arg]

    # Act
    async with open_phoenix_sink(settings) as sink:
        # Assert
        assert isinstance(sink, PhoenixSink)


class RecordingSink:
    def __init__(self, error: SinkError | None = None) -> None:
        self.published: list[EvalResults] = []
        self._error = error

    async def publish(self, results: EvalResults) -> Published:
        if self._error:
            raise self._error
        self.published.append(results)
        return Published("http://phoenix/x", created=True)


def _factory(sink: RecordingSink) -> cli.SinkFactory:
    @asynccontextmanager
    async def open_sink() -> AsyncGenerator[ResultSink]:
        yield sink

    return open_sink


def _saved_report(tmp_path: Path, fingerprint: str = DATA.fingerprint) -> Path:
    records = [record("c1"), record("c2")]
    path = tmp_path / "report.json"
    write_report(path, {**META, "dataset_fingerprint": fingerprint}, summarise(records), records)
    return path


def _dataset_file(tmp_path: Path) -> Path:
    path = tmp_path / "kb.toml"
    path.write_text(
        'name = "kb"\nversion = 1\nk = 2\ncorpus = "tests"\n'
        '[[cases]]\nid = "c1"\nquestion = "Where?"\ntags = ["tag"]\n'
        '[cases.expect]\nsources = ["a.md"]\n'
        '[[cases]]\nid = "c2"\nquestion = "Why?"\n[cases.expect]\nsources = ["b.md"]\n',
        encoding="utf-8",
    )
    return path


def test_publish_report_sends_a_saved_report(tmp_path: Path):
    # Arrange
    sink = RecordingSink()
    out = io.StringIO()

    # Act
    code = cli.publish_report(_saved_report(tmp_path), _dataset_file(tmp_path), _factory(sink), out)

    # Assert
    assert code == cli.EXIT_OK
    assert sink.published[0].report_name == "report.json"
    assert "Published: http://phoenix/x" in out.getvalue()


def test_publish_report_refuses_a_report_graded_by_another_dataset(tmp_path: Path):
    # Act
    code = cli.publish_report(
        _saved_report(tmp_path, "other"),
        _dataset_file(tmp_path),
        _factory(RecordingSink()),
        io.StringIO(),
    )

    # Assert
    assert code == cli.EXIT_USAGE


def test_publish_report_failure_exits_three(tmp_path: Path):
    # Act
    code = cli.publish_report(
        _saved_report(tmp_path),
        _dataset_file(tmp_path),
        _factory(RecordingSink(SinkError("down"))),
        io.StringIO(),
    )

    # Assert
    assert code == cli.EXIT_PUBLISH_FAILED


def test_publish_without_a_phoenix_url_is_a_usage_error(monkeypatch: pytest.MonkeyPatch):
    # Arrange
    monkeypatch.setattr(
        cli,
        "get_phoenix_settings",
        lambda: PhoenixSettings(_env_file=None, base_url=None),  # type: ignore[call-arg]
    )
    out = io.StringIO()

    # Act
    code = cli.main(["publish", "report.json"], out)

    # Assert
    assert code == cli.EXIT_USAGE
    assert "PHOENIX_BASE_URL" in out.getvalue()


def test_invalid_fail_under_is_a_usage_error():
    out = io.StringIO()
    assert cli.main(["run", "--fail-under", "2"], out) == cli.EXIT_USAGE


def test_git_revision_outside_a_repository_is_unknown(tmp_path: Path):
    assert cli.git_revision(tmp_path) == {"git_commit": None, "git_dirty": None}


def test_main_run_wires_the_service_components(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # Arrange: real settings and dataset file; the index and embedder are in-memory fakes
    from tests.config.test_settings import settings
    from tests.fakes import FakeEmbedder, InMemoryIndexProvider

    provider = InMemoryIndexProvider()
    monkeypatch.setattr(cli, "get_settings", lambda: settings(app_env="test"))

    def embedder(_settings: object) -> FakeEmbedder:
        return FakeEmbedder()

    def index_provider(_settings: object) -> InMemoryIndexProvider:
        return provider

    monkeypatch.setattr(cli, "build_embedder", embedder)
    monkeypatch.setattr(cli, "build_index_provider", index_provider)
    out = io.StringIO()

    # Act: the in-memory index is empty, so the corpus check aborts the eval
    code = cli.main(
        ["run", "--dataset", str(_dataset_file(tmp_path)), "--collection", "other"], out
    )

    # Assert
    assert code == cli.EXIT_USAGE
    assert "Eval aborted" in out.getvalue()
    assert provider.opened[0].collection == "other"
    assert provider.opened[0].embedding_model == "bag-of-words"
