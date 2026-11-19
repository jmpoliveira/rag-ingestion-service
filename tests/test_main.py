from __future__ import annotations

import io
from pathlib import Path

import pytest

import main
from src.application.sync_source import SyncSource
from src.domain.index import IndexSpec
from src.infrastructure.embeddings.resilience import RetryingEmbedder
from src.interface.cli import EXIT_FATAL, EXIT_OK, EXIT_USAGE
from tests.config.test_settings import REQUIRED, settings


def test_build_sync_wires_the_pipeline_without_network_calls(tmp_path: Path):
    # Act
    sync = main.build_sync(settings(source_dir=tmp_path))

    # Assert
    assert isinstance(sync, SyncSource)


def test_the_embedder_is_resilient_and_the_spec_carries_the_prefixes():
    # Arrange
    configured = settings(
        embedding_document_prefix="search_document: ", embedding_query_prefix="search_query: "
    )

    # Act
    embedder = main.build_embedder(configured)
    spec = main.build_index_spec(configured, embedder)

    # Assert
    assert isinstance(embedder, RetryingEmbedder)
    assert spec == IndexSpec(
        collection="knowledge-base",
        embedding_provider="ollama",
        embedding_model="nomic-embed-text",
        document_prefix="search_document: ",
        query_prefix="search_query: ",
        distance="cosine",
    )


def test_build_inspect_targets_the_configured_collection():
    # Act
    inspect = main.build_inspect(settings(chroma_collection="tessera-kb"))

    # Assert
    assert inspect._spec.collection == "tessera-kb"  # pyright: ignore[reportPrivateUsage]


def test_help_needs_no_settings():
    # Arrange
    out = io.StringIO()

    # Act
    code = main.main(["--help"], out)

    # Assert
    assert code == EXIT_OK
    assert "sync" in out.getvalue()


def test_no_arguments_is_a_usage_error():
    assert main.main([], io.StringIO()) == EXIT_USAGE


def test_invalid_settings_are_reported_not_raised(monkeypatch: pytest.MonkeyPatch):
    # Arrange
    main.get_settings.cache_clear()
    monkeypatch.chdir(Path(__file__).parent)  # no .env here
    for key in REQUIRED:
        monkeypatch.delenv(key.upper(), raising=False)
    out = io.StringIO()

    # Act
    code = main.main(["sync"], out)

    # Assert
    assert code == EXIT_USAGE
    assert "Invalid settings" in out.getvalue()
    main.get_settings.cache_clear()


def test_a_missing_source_folder_stops_the_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # Arrange: valid settings, but the folder does not exist (checked before any network call)
    main.get_settings.cache_clear()
    monkeypatch.chdir(tmp_path)
    for key, value in {**REQUIRED, "source_dir": str(tmp_path / "missing")}.items():
        monkeypatch.setenv(key.upper(), value)
    monkeypatch.setenv("APP_ENV", "test")
    out = io.StringIO()

    # Act
    code = main.main(["sync"], out)

    # Assert
    assert code == EXIT_FATAL
    assert "Source folder does not exist" in out.getvalue()
    main.get_settings.cache_clear()
