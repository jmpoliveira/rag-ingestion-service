"""Live tests run only on request: ``pytest --live`` (``make test-live``)."""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs Ollama and Chroma: run with --live (make test-live)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
