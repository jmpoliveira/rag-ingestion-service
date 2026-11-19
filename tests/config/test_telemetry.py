from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import config.telemetry as telemetry
from tests.config.test_settings import settings


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry, "_shutdown", None)


def test_disabled_telemetry_returns_a_harmless_shutdown():
    # Act
    shutdown = telemetry.setup_telemetry(settings(otel_enabled=False))

    # Assert
    shutdown()  # must not raise


def test_enabled_telemetry_exports_to_the_otlp_http_traces_path(monkeypatch: pytest.MonkeyPatch):
    # Arrange: replace everything that would touch the global provider or the network
    exporter_class = MagicMock(name="OTLPSpanExporter")
    set_provider = MagicMock(name="set_tracer_provider")
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", exporter_class)
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", MagicMock())
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", set_provider)
    configured = settings(
        otel_enabled=True, otel_exporter_otlp_endpoint="http://otel-collector:4318/"
    )

    # Act
    shutdown = telemetry.setup_telemetry(configured)

    # Assert
    exporter_class.assert_called_once_with(endpoint="http://otel-collector:4318/v1/traces")
    resource = set_provider.call_args.args[0].resource
    assert resource.attributes["service.name"] == "rag-ingestion-service"
    assert callable(shutdown)


def test_second_call_reuses_the_existing_provider(monkeypatch: pytest.MonkeyPatch):
    # Arrange
    set_provider = MagicMock()
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", MagicMock())
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", MagicMock())
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", set_provider)
    configured = settings(otel_enabled=True, otel_exporter_otlp_endpoint="http://c:4318")

    # Act
    first = telemetry.setup_telemetry(configured)
    second = telemetry.setup_telemetry(configured)

    # Assert
    assert first is second
    set_provider.assert_called_once()
