"""Composition root: the only module that knows every layer and wires them together.

python main.py sync          # incremental ingestion of SOURCE_DIR
python main.py reset --yes   # drop CHROMA_COLLECTION
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from pydantic import ValidationError

from config.log_setup import configure_logging
from config.settings import Settings, get_settings
from config.telemetry import setup_telemetry
from src.application.ingest_document import IngestConfig, IngestDocument
from src.application.inspect_index import InspectIndex
from src.application.ports import DocumentParser, Embedder, VectorIndexProvider
from src.application.reset_index import ResetIndex
from src.application.sync_source import SyncSource
from src.domain.index import IndexSpec
from src.infrastructure.chunking.recursive import RecursiveChunker
from src.infrastructure.embeddings.ollama import create_ollama_embedder
from src.infrastructure.embeddings.resilience import RetryingEmbedder, RetryPolicy
from src.infrastructure.parsing.pdf import PdfParser
from src.infrastructure.parsing.text import TextParser
from src.infrastructure.sources.folder import DEFAULT_MEDIA_TYPES, FolderDocumentSource
from src.infrastructure.vectorstore.chroma import ChromaIndexProvider
from src.interface.cli import EXIT_USAGE, build_parser, run_cli


def build_embedder(settings: Settings) -> Embedder:
    embedder = create_ollama_embedder(
        base_url=str(settings.ollama_base_url),
        model=settings.embedding_model,
        timeout_seconds=settings.embedding_timeout_seconds,
        document_prefix=settings.embedding_document_prefix,
        query_prefix=settings.embedding_query_prefix,
    )
    policy = RetryPolicy(
        max_attempts=settings.embedding_max_attempts,
        base_delay_seconds=settings.embedding_retry_base_delay_seconds,
        max_delay_seconds=settings.embedding_retry_max_delay_seconds,
    )
    return RetryingEmbedder(embedder, policy)


def build_index_spec(settings: Settings, embedder: Embedder) -> IndexSpec:
    return IndexSpec(
        collection=settings.chroma_collection,
        embedding_provider=embedder.provider,
        embedding_model=embedder.model,
        document_prefix=settings.embedding_document_prefix,
        query_prefix=settings.embedding_query_prefix,
        distance=settings.chroma_distance,
    )


def build_index_provider(settings: Settings) -> VectorIndexProvider:
    return ChromaIndexProvider(
        host=settings.chroma_host,
        port=settings.chroma_port,
        ssl=settings.chroma_ssl,
        batch_size=settings.chroma_batch_size,
    )


def build_sync(settings: Settings) -> SyncSource:
    parsers: list[DocumentParser] = [PdfParser(max_pages=settings.max_pdf_pages), TextParser()]
    supported = {media for parser in parsers for media in parser.media_types}
    source = FolderDocumentSource(
        settings.source_dir,
        media_types={k: v for k, v in DEFAULT_MEDIA_TYPES.items() if v in supported},
        max_file_bytes=settings.max_file_bytes,
    )
    embedder = build_embedder(settings)
    ingest = IngestDocument(
        source,
        parsers,
        RecursiveChunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap),
        embedder,
        IngestConfig(
            collection=settings.chroma_collection,
            embedding_batch_size=settings.embedding_batch_size,
        ),
    )
    return SyncSource(
        source,
        ingest,
        build_index_provider(settings),
        build_index_spec(settings, embedder),
        delete_missing=settings.delete_missing,
    )


def build_inspect(settings: Settings) -> InspectIndex:
    # The spec only needs the embedder's provider and model names: no network call is made.
    return InspectIndex(
        build_index_provider(settings), build_index_spec(settings, build_embedder(settings))
    )


def build_reset(settings: Settings) -> ResetIndex:
    return ResetIndex(build_index_provider(settings), settings.chroma_collection)


def main(argv: Sequence[str] | None = None, out: TextIO = sys.stdout) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {"-h", "--help"}:
        build_parser().print_help(out)
        return 0 if arguments else EXIT_USAGE
    try:
        settings = get_settings()
    except ValidationError as err:
        print(f"Invalid settings (check your .env):\n{err}", file=out)
        return EXIT_USAGE
    configure_logging(settings.app_env, settings.log_level)
    shutdown_telemetry = setup_telemetry(settings)
    try:
        return run_cli(
            arguments,
            sync=lambda: build_sync(settings),
            reset=lambda: build_reset(settings),
            inspect=lambda: build_inspect(settings),
            out=out,
        )
    finally:
        shutdown_telemetry()  # a batch job must flush its spans before exiting


if __name__ == "__main__":
    sys.exit(main())
