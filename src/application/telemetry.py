"""Tracing helpers: the only module that knows span and attribute names.

Embedding spans follow the OpenTelemetry GenAI semantic conventions (``embeddings <model>``,
``gen_ai.*`` attributes), so Phoenix and Jaeger show them like the agent's chat spans.
Index writes use the database conventions (``db.*``). Both conventions are still in
"Development" status: a rename touches this file only.

``opentelemetry-api`` in the application layer is a documented exception to the dependency
rule (ADR 0001): the API is vendor-neutral, and a tracing port would add code, not freedom.
Span attributes never hold document text, only ids, counts and sizes.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

_tracer = trace.get_tracer("rag_ingestion_service")

ATTR_OPERATION = "gen_ai.operation.name"
ATTR_PROVIDER = "gen_ai.provider.name"
ATTR_REQUEST_MODEL = "gen_ai.request.model"
ATTR_DIMENSIONS = "gen_ai.embeddings.dimension.count"
ATTR_DB_OPERATION = "db.operation.name"
ATTR_DB_COLLECTION = "db.collection.name"
ATTR_DB_BATCH_SIZE = "db.operation.batch.size"
ATTR_ERROR_TYPE = "error.type"

ATTR_SOURCE_DOCUMENTS = "ingest.source.documents"
ATTR_DOCUMENT_ID = "ingest.document.id"
ATTR_MEDIA_TYPE = "ingest.document.media_type"
ATTR_SIZE_BYTES = "ingest.document.size_bytes"
ATTR_OUTCOME = "ingest.document.outcome"
ATTR_PAGES = "ingest.document.pages"
ATTR_CHUNKS = "ingest.document.chunks"
ATTR_TEXTS = "ingest.embeddings.texts"


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return f"{context.trace_id:032x}" if context.is_valid else None


@contextmanager
def sync_span(collection: str) -> Generator[Span]:
    with _tracer.start_as_current_span(
        "ingest sync", attributes={ATTR_DB_COLLECTION: collection}
    ) as span:
        yield span


@contextmanager
def document_span(document_id: str, media_type: str, size_bytes: int) -> Generator[Span]:
    with _tracer.start_as_current_span(
        "ingest document",
        attributes={
            ATTR_DOCUMENT_ID: document_id,
            ATTR_MEDIA_TYPE: media_type,
            ATTR_SIZE_BYTES: size_bytes,
        },
    ) as span:
        yield span


@contextmanager
def stage_span(stage: str) -> Generator[Span]:
    """``read``, ``parse`` or ``chunk``: local work, timed separately from the network."""
    with _tracer.start_as_current_span(stage) as span:
        yield span


@contextmanager
def embeddings_span(provider: str, model: str, texts: int) -> Generator[Span]:
    with _tracer.start_as_current_span(
        f"embeddings {model}",
        kind=SpanKind.CLIENT,
        attributes={
            ATTR_OPERATION: "embeddings",
            ATTR_PROVIDER: provider,
            ATTR_REQUEST_MODEL: model,
            ATTR_TEXTS: texts,
        },
    ) as span:
        yield span


@contextmanager
def index_span(operation: str, collection: str, batch_size: int = 0) -> Generator[Span]:
    attributes: dict[str, str | int] = {
        ATTR_DB_OPERATION: operation,
        ATTR_DB_COLLECTION: collection,
    }
    if batch_size:
        attributes[ATTR_DB_BATCH_SIZE] = batch_size
    with _tracer.start_as_current_span(
        f"{operation} {collection}", kind=SpanKind.CLIENT, attributes=attributes
    ) as span:
        yield span


def mark_error(span: Span, error_type: str) -> None:
    """Flag a span as failed for errors that are handled (recorded, not raised)."""
    span.set_attribute(ATTR_ERROR_TYPE, error_type)
    span.set_status(Status(StatusCode.ERROR, error_type))
