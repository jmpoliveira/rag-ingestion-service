"""Retrieval evals: ``python -m evals run`` measures the index; ``python -m evals publish
<report>`` explores a saved report in Phoenix (ADR 0005).

Uses the same settings (.env) and composition root as the service, so the embedder and the
index under test are the ones the service writes with.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from config.log_setup import configure_logging
from config.settings import Settings, get_phoenix_settings, get_settings
from config.telemetry import setup_telemetry
from evals.dataset import Dataset, DatasetError, load_dataset
from evals.report import ReportError, load_report, render, summarise, write_report
from evals.runner import CaseRecord, EvalAbortedError, RetrievalEvalRunner
from evals.sink import EvalResults, SinkError, SinkFactory
from main import build_embedder, build_index_provider, build_index_spec
from src.application.ports import Embedder, VectorIndexProvider
from src.application.sanitization import CLEANING_VERSION
from src.domain.errors import FatalError
from src.domain.index import IndexSpec

DEFAULT_DATASET = Path("evals/datasets/knowledge_base.toml")
DEFAULT_OUTPUT_DIR = Path("evals/results")

EXIT_OK = 0
EXIT_BELOW_THRESHOLD = 1
EXIT_USAGE = 2
EXIT_PUBLISH_FAILED = 3


@dataclass(frozen=True, slots=True)
class RunOptions:
    dataset: Path
    collection: str | None = None
    cases: frozenset[str] = frozenset()
    tags: frozenset[str] = frozenset()
    baseline: Path | None = None
    output_dir: Path = DEFAULT_OUTPUT_DIR
    fail_under: float | None = None
    verbose: bool = False
    publish: bool = False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="measure retrieval on a collection")
    run.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    run.add_argument("--collection", help="collection to measure (default: CHROMA_COLLECTION)")
    run.add_argument("--case", action="append", default=[], help="only this case id")
    run.add_argument("--tag", action="append", default=[], help="only cases with this tag")
    run.add_argument("--baseline", type=Path, help="earlier report to compare with")
    run.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    run.add_argument("--fail-under", type=float, help="exit 1 if the hit rate is below this (0-1)")
    run.add_argument("--verbose", action="store_true", help="show the service logs")
    run.add_argument("--publish", action="store_true", help="also publish the report to Phoenix")
    publish = commands.add_parser("publish", help="publish a saved report to Phoenix")
    publish.add_argument("report", type=Path)
    publish.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    return parser


def parse_run_args(args: argparse.Namespace) -> RunOptions:
    if args.fail_under is not None and not 0 <= args.fail_under <= 1:
        raise ValueError("--fail-under must be between 0 and 1")
    return RunOptions(
        dataset=args.dataset,
        collection=args.collection,
        cases=frozenset(args.case),
        tags=frozenset(args.tag),
        baseline=args.baseline,
        output_dir=args.output_dir,
        fail_under=args.fail_under,
        verbose=args.verbose,
        publish=args.publish,
    )


def phoenix_sink_factory() -> SinkFactory:
    """Imported lazily: the Phoenix client is an optional extra, and ``run`` works without it."""
    try:
        settings = get_phoenix_settings()
    except ValidationError as err:
        raise SinkError(f"invalid Phoenix settings (check your .env):\n{err}") from err
    if settings.base_url is None:
        raise SinkError("PHOENIX_BASE_URL is not set: there is nowhere to publish to")
    try:
        from evals.phoenix_sink import open_phoenix_sink
    except ImportError as err:
        raise SinkError(
            f"the Phoenix client is not installed ({err.name}): pip install -e '.[evals]'"
        ) from err
    return lambda: open_phoenix_sink(settings)


async def publish_results(results: EvalResults, open_sink: SinkFactory, out: TextIO) -> bool:
    """A failure is reported, never raised: the report is already saved."""
    try:
        async with open_sink() as sink:
            published = await sink.publish(results)
    except SinkError as err:
        print(f"Publishing failed: {err}", file=out)
        return False
    print(f"{'Published' if published.created else 'Already published'}: {published.url}", file=out)
    return True


def publish_report(report: Path, dataset_path: Path, open_sink: SinkFactory, out: TextIO) -> int:
    try:
        dataset = load_dataset(dataset_path)
        saved = load_report(report)
    except (DatasetError, ReportError) as err:
        print(str(err), file=out)
        return EXIT_USAGE
    graded_with = saved.meta.get("dataset_fingerprint")
    if graded_with != dataset.fingerprint:
        print(
            f"{report} was graded with dataset fingerprint {graded_with}, but {dataset_path} "
            f"is {dataset.fingerprint}: publish it with the dataset version that graded it.",
            file=out,
        )
        return EXIT_USAGE
    results = EvalResults(dataset, saved.meta, saved.records, report.name)
    return EXIT_OK if asyncio.run(publish_results(results, open_sink, out)) else EXIT_PUBLISH_FAILED


async def run_evals(
    options: RunOptions,
    dataset: Dataset,
    embedder: Embedder,
    index_provider: VectorIndexProvider,
    spec: IndexSpec,
    meta: dict[str, Any],
    out: TextIO,
    open_sink: SinkFactory | None = None,
) -> int:
    baseline = None
    if options.baseline:
        saved = load_report(options.baseline)
        baseline = {"meta": saved.meta, "summary": saved.summary}
    cases = dataset.select(options.cases, options.tags)
    if not cases:
        print("No cases match the selection.", file=out)
        return EXIT_USAGE

    def progress(record: CaseRecord) -> None:
        status = "pass" if record.passed else "FAIL"
        rank = record.scores.first_relevant_rank or "-"
        print(f"{record.case_id}: {status} (first relevant rank {rank})", file=out, flush=True)

    started = datetime.now(UTC)
    try:
        async with index_provider.open(spec) as index:
            runner = RetrievalEvalRunner(dataset, embedder, index, on_record=progress)
            await runner.check_corpus()
            records = await runner.run(cases)
    except FatalError as err:
        raise EvalAbortedError(str(err)) from err
    summary = summarise(records)
    full_meta = {
        **meta,
        "cases": len(cases),
        "started_at": started.isoformat(timespec="seconds"),
        "duration_seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
    }
    path = options.output_dir / f"{started:%Y%m%d-%H%M%S}-{spec.collection}-{dataset.name}.json"
    write_report(path, full_meta, summary, records)
    print("", file=out)
    print(render(full_meta, summary, records, baseline), file=out)
    print(f"\nReport: {path}", file=out)
    if options.publish and open_sink is not None:
        results = EvalResults(dataset, full_meta, records, path.name)
        if not await publish_results(results, open_sink, out):
            print(f"Publish it later with: python -m evals publish {path}", file=out)
    if options.fail_under is not None and summary.hit_rate < options.fail_under:
        print(f"Hit rate is below --fail-under {options.fail_under:.2f}", file=out)
        return EXIT_BELOW_THRESHOLD
    return EXIT_OK


def build_meta(settings: Settings, dataset: Dataset, spec: IndexSpec) -> dict[str, Any]:
    return {
        "dataset": dataset.name,
        "dataset_version": dataset.version,
        "dataset_fingerprint": dataset.fingerprint,
        "k": dataset.k,
        "collection": spec.collection,
        "embedding_provider": spec.embedding_provider,
        "embedding_model": spec.embedding_model,
        "document_prefix": spec.document_prefix,
        "query_prefix": spec.query_prefix,
        "distance": spec.distance,
        # From the current settings: valid when the collection was synced with them.
        "pipeline_fingerprint": (
            f"recursive:{settings.chunk_size}:{settings.chunk_overlap};clean=v{CLEANING_VERSION}"
        ),
        **git_revision(),
    }


def git_revision(cwd: Path | None = None) -> dict[str, Any]:
    """The commit the eval ran on; ``git_dirty`` means uncommitted changes were present."""
    unknown: dict[str, Any] = {"git_commit": None, "git_dirty": None}
    git = shutil.which("git")
    if git is None:
        return unknown
    try:
        # Fixed arguments, no shell: nothing user-controlled reaches the command line.
        commit = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(  # noqa: S603
            [git, "status", "--porcelain"], cwd=cwd, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return unknown
    return {"git_commit": commit, "git_dirty": bool(status.strip())}


def main(argv: Sequence[str] | None = None, out: TextIO = sys.stdout) -> int:
    parser = _parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    open_sink: SinkFactory | None = None
    if args.command == "publish" or args.publish:
        try:
            open_sink = phoenix_sink_factory()  # fail before a run, not after it
        except SinkError as err:
            print(f"Cannot publish: {err}", file=out)
            return EXIT_USAGE
        if args.command == "publish":
            return publish_report(args.report, args.dataset, open_sink, out)
    try:
        options = parse_run_args(args)
        settings = get_settings()
        dataset = load_dataset(options.dataset)
    except (ValueError, ValidationError) as err:  # DatasetError is a ValueError
        print(str(err), file=out)
        return EXIT_USAGE
    configure_logging(settings.app_env if options.verbose else "test")
    embedder = build_embedder(settings)
    spec = build_index_spec(settings, embedder)
    if options.collection:
        spec = replace(spec, collection=options.collection)
    shutdown_telemetry = setup_telemetry(settings)
    try:
        return asyncio.run(
            run_evals(
                options,
                dataset,
                embedder,
                build_index_provider(settings),
                spec,
                build_meta(settings, dataset, spec),
                out,
                open_sink,
            )
        )
    except (EvalAbortedError, ReportError) as err:
        print(f"Eval aborted: {err}", file=out)
        return EXIT_USAGE
    finally:
        shutdown_telemetry()


if __name__ == "__main__":
    sys.exit(main())
