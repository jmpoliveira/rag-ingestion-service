"""Command line: the trigger of the folder-based ingestion (ADR 0002).

    python main.py sync              # make the index match the source folder
    python main.py inspect [--document ID]   # what is in the collection (read-only)
    python main.py reset --yes       # drop the collection (destructive, explicit)

Run it by hand, from a scheduler (cron, a Kubernetes CronJob) or as a one-shot container.
An event consumer will be another module in this layer, calling the same use cases.

Exit codes are part of the interface, so a scheduler can alert on them:
0 every document is in the index, 1 at least one document failed (the others were indexed),
2 invalid arguments or settings, 3 the run stopped: a dependency is down or misconfigured.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Sequence
from typing import TextIO

from src.application.inspect_index import InspectIndex, Inspection
from src.application.reset_index import ResetIndex
from src.application.sync_source import SyncSource
from src.domain.errors import FatalError
from src.domain.ingestion import IngestionReport, Outcome

EXIT_OK = 0
EXIT_DOCUMENTS_FAILED = 1
EXIT_USAGE = 2
EXIT_FATAL = 3

_PREVIEW_CHARS = 80


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py", description="Ingest documents into the RAG vector index."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="make the index match the source (incremental)")
    inspect = commands.add_parser(
        "inspect", help="show the collection's contract, documents and chunks (read-only)"
    )
    inspect.add_argument("--document", help="also list the chunks of this document id")
    reset = commands.add_parser("reset", help="drop the whole collection")
    reset.add_argument("--yes", action="store_true", help="confirm the deletion")
    return parser


def run_cli(
    argv: Sequence[str],
    *,
    sync: Callable[[], SyncSource],
    reset: Callable[[], ResetIndex],
    inspect: Callable[[], InspectIndex],
    out: TextIO,
) -> int:
    """Parse ``argv`` and run one command. Use cases are built lazily by the callables, so
    ``--help`` and argument errors need no settings."""
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exit_:
        return EXIT_OK if exit_.code == 0 else EXIT_USAGE
    try:
        if args.command == "reset":
            if not args.yes:
                print("Refusing to drop the collection without --yes.", file=out)
                return EXIT_USAGE
            dropped = asyncio.run(reset().execute())
            print("Collection dropped." if dropped else "Collection did not exist.", file=out)
            return EXIT_OK
        if args.command == "inspect":
            inspection = asyncio.run(inspect().execute(args.document))
            print(render_inspection(inspection, args.document), file=out)
            return EXIT_OK if inspection.exists else EXIT_USAGE
        report = asyncio.run(sync().execute())
    except FatalError as err:
        print(f"Ingestion stopped: {err}", file=out)
        return EXIT_FATAL
    print(render(report), file=out)
    return EXIT_DOCUMENTS_FAILED if report.failed else EXIT_OK


def render(report: IngestionReport) -> str:
    counts = report.counts
    lines = [
        "Sync finished: " + ", ".join(f"{counts[outcome]} {outcome.value}" for outcome in Outcome),
    ]
    lines += [
        f"  {result.outcome.value.upper():9} {result.document_id}: {result.detail}"
        for result in report.results
        if result.outcome in (Outcome.FAILED, Outcome.EMPTY)
    ]
    lines += [f"Warning: {warning}" for warning in report.warnings]
    if report.trace_id:
        lines.append(f"Trace id: {report.trace_id}")
    return "\n".join(lines)


def render_inspection(inspection: Inspection, document_id: str | None = None) -> str:
    """Readable view of a collection. Prints chunk text on purpose: this command exists to
    look at what was stored, on the operator's own terminal (it never goes to the logs)."""
    info = inspection.info
    if info is None:
        return f"Collection '{inspection.collection}' does not exist."
    lines = [f"Collection '{info.name}': {info.chunks} chunks", "Contract:"]
    lines += [f"  {key} = {value!r}" for key, value in sorted(info.metadata.items())]
    if inspection.contract_problem:
        lines += ["", f"Does not match the settings: {inspection.contract_problem}"]
        return "\n".join(lines)
    lines += ["", f"Complete documents: {len(inspection.documents)}"]
    lines += [
        f"  {doc.document_id}  version {doc.version}  {doc.chunk_count} chunks"
        for doc in sorted(inspection.documents, key=lambda d: d.document_id)
    ]
    if document_id is not None:
        lines += ["", f"Chunks of {document_id}: {len(inspection.chunks)}"]
        lines += [
            f"  {chunk.chunk_id}  page {chunk.page}  chunk {chunk.chunk_index + 1}/"
            f"{chunk.chunk_count}  {chunk.dimensions} dims  "
            f"{' '.join(chunk.text.split())[:_PREVIEW_CHARS]!r}"
            for chunk in inspection.chunks
        ]
    return "\n".join(lines)
