from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from config.settings import PhoenixSettings, Settings

REQUIRED: dict[str, Any] = {
    "source_dir": "data",
    "ollama_base_url": "http://ollama.test:11434",
    "embedding_model": "nomic-embed-text",
    "chroma_host": "localhost",
    "chroma_collection": "knowledge-base",
}


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **{**REQUIRED, **overrides})  # type: ignore[call-arg]


def test_defaults_are_safe():
    # Act
    loaded = settings()

    # Assert
    assert loaded.source_dir == Path("data")
    assert loaded.delete_missing is True
    assert loaded.chroma_distance == "cosine"
    assert loaded.otel_enabled is False
    assert loaded.embedding_document_prefix == ""


@pytest.mark.parametrize("missing", sorted(REQUIRED))
def test_required_settings(missing: str, monkeypatch: pytest.MonkeyPatch):
    # Arrange
    monkeypatch.delenv(missing.upper(), raising=False)
    values = {k: v for k, v in REQUIRED.items() if k != missing}

    # Act / Assert
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_overlap_must_be_smaller_than_the_chunk():
    with pytest.raises(ValidationError, match="CHUNK_OVERLAP"):
        settings(chunk_size=500, chunk_overlap=500)


def test_retry_delays_must_be_ordered():
    with pytest.raises(ValidationError, match="RETRY_MAX_DELAY"):
        settings(embedding_retry_base_delay_seconds=5, embedding_retry_max_delay_seconds=1)


def test_tracing_needs_an_endpoint():
    with pytest.raises(ValidationError, match="OTEL_EXPORTER_OTLP_ENDPOINT"):
        settings(otel_enabled=True)


@pytest.mark.parametrize("name", ["a", "-kb", "kb-", "with space", "x" * 600])
def test_invalid_collection_names_are_rejected(name: str):
    with pytest.raises(ValidationError):
        settings(chroma_collection=name)


def test_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    # Arrange
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key.upper(), str(value))
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")
    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "search_query: ")

    # Act
    loaded = Settings(_env_file=None)  # type: ignore[call-arg]

    # Assert
    assert str(loaded.otel_exporter_otlp_endpoint) == "http://otel-collector:4318/"
    assert loaded.embedding_query_prefix == "search_query: "


def test_phoenix_publishing_is_off_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PHOENIX_BASE_URL", raising=False)
    assert PhoenixSettings(_env_file=None).base_url is None  # type: ignore[call-arg]
