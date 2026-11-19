from __future__ import annotations

import io

import pytest

from src.application.inspect_index import Inspection
from src.application.reset_index import ResetIndex
from src.application.sync_source import SyncSource
from src.domain.documents import CollectionInfo, IndexedDocument, StoredChunk
from src.domain.errors import VectorIndexUnavailableError
from src.domain.ingestion import DocumentResult, IngestionReport, Outcome
from src.interface.cli import (
    EXIT_DOCUMENTS_FAILED,
    EXIT_FATAL,
    EXIT_OK,
    EXIT_USAGE,
    render,
    render_inspection,
    run_cli,
)


class StubSync:
    def __init__(self, report: IngestionReport | None = None, error: Exception | None = None):
        self._report = report or IngestionReport(())
        self._error = error

    async def execute(self) -> IngestionReport:
        if self._error:
            raise self._error
        return self._report


class StubInspect:
    def __init__(self, inspection: Inspection | None = None) -> None:
        self.inspection = inspection or Inspection("kb", None)
        self.asked: list[str | None] = []

    async def execute(self, document_id: str | None = None) -> Inspection:
        self.asked.append(document_id)
        return self.inspection


class StubReset:
    def __init__(self, existed: bool = True) -> None:
        self.calls = 0
        self._existed = existed

    async def execute(self) -> bool:
        self.calls += 1
        return self._existed


def _run(
    argv: list[str], sync: StubSync | None = None, reset: StubReset | None = None
) -> tuple[int, str]:
    out = io.StringIO()
    code = run_cli(
        argv,
        sync=lambda: sync or StubSync(),  # type: ignore[arg-type,return-value]
        reset=lambda: reset or StubReset(),  # type: ignore[arg-type,return-value]
        inspect=StubInspect,  # type: ignore[arg-type]
        out=out,
    )
    return code, out.getvalue()


def test_a_clean_sync_exits_zero_and_prints_the_summary():
    # Arrange
    report = IngestionReport((DocumentResult("a.md", Outcome.INDEXED, 3),), trace_id="abc")

    # Act
    code, output = _run(["sync"], StubSync(report))

    # Assert
    assert code == EXIT_OK
    assert "1 indexed" in output
    assert "Trace id: abc" in output


def test_failed_documents_exit_one():
    # Arrange
    report = IngestionReport((DocumentResult("a.pdf", Outcome.FAILED, detail="encrypted"),))

    # Act
    code, output = _run(["sync"], StubSync(report))

    # Assert
    assert code == EXIT_DOCUMENTS_FAILED
    assert "a.pdf: encrypted" in output


def test_a_fatal_error_exits_three_with_a_safe_message():
    # Act
    code, output = _run(["sync"], StubSync(error=VectorIndexUnavailableError("unreachable")))

    # Assert
    assert code == EXIT_FATAL
    assert "Ingestion stopped: unreachable" in output


def test_reset_needs_explicit_confirmation():
    # Arrange
    reset = StubReset()

    # Act
    code, output = _run(["reset"], reset=reset)

    # Assert
    assert code == EXIT_USAGE
    assert reset.calls == 0
    assert "--yes" in output


@pytest.mark.parametrize(("existed", "message"), [(True, "dropped"), (False, "did not exist")])
def test_reset_with_confirmation_drops(existed: bool, message: str):
    # Act
    code, output = _run(["reset", "--yes"], reset=StubReset(existed))

    # Assert
    assert code == EXIT_OK
    assert message in output


def test_unknown_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]):
    code, _ = _run(["explode"])
    assert code == EXIT_USAGE


def test_render_lists_empty_documents_and_warnings():
    # Arrange
    report = IngestionReport(
        (DocumentResult("scan.pdf", Outcome.EMPTY, detail="No extractable text"),),
        warnings=("source is empty",),
    )

    # Act
    text = render(report)

    # Assert
    assert "EMPTY" in text
    assert "scan.pdf" in text
    assert "Warning: source is empty" in text


def test_use_cases_are_typed_as_the_application_classes():
    # The stubs above stand in for these; keep the import so a rename breaks this test.
    assert SyncSource.__name__ == "SyncSource"
    assert ResetIndex.__name__ == "ResetIndex"


def _run_inspect(argv: list[str], stub: StubInspect) -> tuple[int, str]:
    out = io.StringIO()
    code = run_cli(
        argv,
        sync=StubSync,  # type: ignore[arg-type]
        reset=StubReset,  # type: ignore[arg-type]
        inspect=lambda: stub,  # type: ignore[arg-type,return-value]
        out=out,
    )
    return code, out.getvalue()


def test_inspect_a_missing_collection_is_a_usage_error():
    # Act
    code, output = _run_inspect(["inspect"], StubInspect())

    # Assert
    assert code == EXIT_USAGE
    assert "does not exist" in output


def test_inspect_shows_the_contract_documents_and_chunks():
    # Arrange
    inspection = Inspection(
        "kb",
        CollectionInfo("kb", {"rag.embedding.model": "nomic-embed-text"}, 3),
        documents=(IndexedDocument("a.md", "v1", "h", 2),),
        chunks=(StoredChunk("id-0", "a.md", "v1", 1, 0, 2, "first   chunk\ntext", 768),),
    )
    stub = StubInspect(inspection)

    # Act
    code, output = _run_inspect(["inspect", "--document", "a.md"], stub)

    # Assert
    assert code == EXIT_OK
    assert stub.asked == ["a.md"]
    assert "rag.embedding.model = 'nomic-embed-text'" in output
    assert "a.md  version v1  2 chunks" in output
    assert "id-0  page 1  chunk 1/2  768 dims  'first chunk text'" in output


def test_inspect_explains_a_contract_mismatch():
    # Arrange
    inspection = Inspection(
        "kb", CollectionInfo("kb", {}, 10), contract_problem="no index contract"
    )

    # Act
    code, output = _run_inspect(["inspect"], StubInspect(inspection))

    # Assert
    assert code == EXIT_OK
    assert "Does not match the settings: no index contract" in output
    assert render_inspection(inspection).count("Complete documents") == 0
