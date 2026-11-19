"""Centralised configuration. The only place that reads environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]
Distance = Literal["cosine", "l2", "ip"]


class Settings(BaseSettings):
    """All runtime configuration, loaded from environment variables and an optional .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # --- Application -------------------------------------------------------------------
    app_name: str = "rag-ingestion-service"
    # Selects the logging profile in config/logging.json.
    app_env: AppEnv = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] | None = None

    # --- Source (ADR 0002) -------------------------------------------------------------
    # Required, never created: a missing folder is a configuration error.
    source_dir: Path
    max_file_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    max_pdf_pages: int = Field(default=500, ge=1)
    # When a document disappears from the source, delete its chunks. Never applied when the
    # source is empty (a wrong path must not wipe the index).
    delete_missing: bool = True

    # --- Chunking ----------------------------------------------------------------------
    chunk_size: int = Field(default=1000, ge=100, le=20_000)
    chunk_overlap: int = Field(default=200, ge=0)

    # --- Embeddings (part of the index contract, ADR 0004) -----------------------------
    ollama_base_url: AnyHttpUrl
    embedding_model: str = Field(min_length=1)
    # Task instructions some models expect, e.g. "search_document: " for nomic-embed-text.
    embedding_document_prefix: str = ""
    embedding_query_prefix: str = ""
    embedding_batch_size: int = Field(default=32, ge=1, le=1024)
    embedding_timeout_seconds: float = Field(default=60.0, gt=0)
    embedding_max_attempts: int = Field(default=3, ge=1, le=10)
    embedding_retry_base_delay_seconds: float = Field(default=0.5, ge=0)
    embedding_retry_max_delay_seconds: float = Field(default=8.0, ge=0)

    # --- Vector store (names from the docker-env service contract) ---------------------
    chroma_host: str = Field(min_length=1)
    chroma_port: int = Field(default=8000, ge=1, le=65535)
    chroma_ssl: bool = False
    chroma_collection: str = Field(
        min_length=3, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$"
    )
    chroma_distance: Distance = "cosine"
    chroma_batch_size: int = Field(default=100, ge=1, le=5000)

    # --- OpenTelemetry (OTLP over HTTP; standard variable names) -----------------------
    otel_enabled: bool = False
    # Base URL of the collector; /v1/traces is appended. Read from OTEL_EXPORTER_OTLP_ENDPOINT.
    otel_exporter_otlp_endpoint: AnyHttpUrl | None = None
    otel_service_name: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if self.embedding_retry_max_delay_seconds < self.embedding_retry_base_delay_seconds:
            raise ValueError(
                "EMBEDDING_RETRY_MAX_DELAY_SECONDS must be >= EMBEDDING_RETRY_BASE_DELAY_SECONDS"
            )
        if self.otel_enabled and self.otel_exporter_otlp_endpoint is None:
            raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT is required when OTEL_ENABLED=true")
        return self


class PhoenixSettings(BaseSettings):
    """Where ``python -m evals`` publishes results (ADR 0005). Read only by the evals."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True, env_prefix="PHOENIX_"
    )

    base_url: AnyHttpUrl | None = None
    api_key: SecretStr | None = None
    request_timeout_seconds: float = Field(default=30.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process."""
    return Settings()  # pyright: ignore[reportCallIssue]  # required fields come from the environment


@lru_cache
def get_phoenix_settings() -> PhoenixSettings:
    return PhoenixSettings()
