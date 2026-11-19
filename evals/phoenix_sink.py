"""Publishes retrieval eval results to Arize Phoenix (ADR 0005), as ai-agent-service does.

- dataset file -> Phoenix dataset ``<name>-v<version>-<fingerprint>`` (one example per case:
  input = the question, output = the expected sources, metadata = case id and tags), so only
  runs graded by the same rules are compared side by side;
- report -> experiment (collection, embedding model, prefixes, chunking, commit...);
- case -> experiment run (the ranked hits, linked to the case's trace by trace id);
- metric -> evaluation (hit@k, reciprocal rank, recall@k, evidence, passed).

Phoenix only records results the runner already produced; it never runs the retrieval.
This is the only module allowed to import ``phoenix`` (tests/test_architecture.py).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx
from phoenix.client import AsyncClient
from phoenix.client.exceptions import PhoenixException
from phoenix.client.resources.datasets import Dataset as PhoenixDataset
from phoenix.client.resources.datasets import DatasetUploadError

from config.settings import PhoenixSettings
from evals.dataset import Dataset
from evals.runner import CaseRecord
from evals.sink import EvalResults, Published, ResultSink, SinkError

logger = logging.getLogger(__name__)

OVERALL = "passed"
_EXPERIMENT_META = (
    "collection",
    "embedding_provider",
    "embedding_model",
    "document_prefix",
    "query_prefix",
    "distance",
    "pipeline_fingerprint",
    "k",
    "dataset_version",
    "dataset_fingerprint",
    "git_commit",
    "git_dirty",
    "started_at",
)
_MAX_HIT_CHARS = 1000


def phoenix_dataset_name(dataset: Dataset) -> str:
    return f"{dataset.name}-v{dataset.version}-{dataset.fingerprint}"


class PhoenixSink:
    def __init__(self, client: AsyncClient, *, timeout_seconds: int = 30) -> None:
        self._client = client
        self._timeout = timeout_seconds

    async def publish(self, results: EvalResults) -> Published:
        try:
            return await self._publish(results)
        except (httpx.HTTPError, PhoenixException, DatasetUploadError) as err:
            raise SinkError(f"Phoenix request failed: {err}") from err

    async def _publish(self, results: EvalResults) -> Published:
        dataset = await self._dataset_for(results.dataset)
        example_ids = {
            str(example["metadata"]["case_id"]): example["id"]
            for example in dataset.examples
            if "case_id" in example["metadata"]
        }
        missing = sorted({r.case_id for r in results.records} - example_ids.keys())
        if missing:
            raise SinkError(f"Phoenix dataset '{dataset.name}' has no example for cases {missing}")

        experiments = self._client.experiments
        listed = await experiments.list(dataset_id=dataset.id, timeout=self._timeout)
        existing = next(
            (e["id"] for e in listed if e["metadata"].get("report") == results.report_name), None
        )
        if existing is not None:
            return Published(experiments.get_experiment_url(dataset.id, existing), created=False)

        meta = results.meta
        experiment = await experiments.create(
            dataset_id=dataset.id,
            dataset_version_id=dataset.version_id,
            experiment_name=f"{meta.get('embedding_model')} k={meta.get('k')}"
            f" @ {meta.get('started_at', '?')}",
            experiment_description=f"Retrieval eval report {results.report_name}",
            experiment_metadata={
                "report": results.report_name,
                **{key: meta[key] for key in _EXPERIMENT_META if key in meta},
            },
            repetitions=1,
            timeout=self._timeout,
        )
        for record in results.records:
            await self._log_run(experiment["id"], example_ids[record.case_id], record)
        logger.info(
            "Eval results published",
            extra={"experiment": experiment["id"], "runs": len(results.records)},
        )
        return Published(experiments.get_experiment_url(dataset.id, experiment["id"]), True)

    async def _dataset_for(self, dataset: Dataset) -> PhoenixDataset:
        name = phoenix_dataset_name(dataset)
        datasets = self._client.datasets
        listed = await datasets.list(timeout=self._timeout)
        found = next((item for item in listed if item["name"] == name), None)
        if found is not None:
            return await datasets.get_dataset(dataset=found["id"], timeout=self._timeout)
        logger.info("Creating Phoenix dataset", extra={"dataset": name})
        # The optional `dataframe` parameter is typed with pandas, which we do not install.
        return await datasets.create_dataset(  # pyright: ignore[reportUnknownMemberType]
            name=name,
            inputs=[{"question": case.question} for case in dataset.cases],
            outputs=[case.expect.model_dump(mode="json") for case in dataset.cases],
            metadata=[{"case_id": case.id, "tags": list(case.tags)} for case in dataset.cases],
            dataset_description=dataset.description.strip()
            or f"Retrieval eval dataset {dataset.name} v{dataset.version}",
            timeout=self._timeout,
        )

    async def _log_run(self, experiment_id: str, example_id: str, record: CaseRecord) -> None:
        ended = record.started_at + timedelta(seconds=record.latency_seconds)
        run = await self._client.experiments.log_run(
            experiment_id=experiment_id,
            dataset_example_id=example_id,
            output=_output(record),
            start_time=record.started_at,
            end_time=ended,
            repetition_number=1,
            trace_id=record.trace_id,
            timeout=self._timeout,
        )
        for name, score, label, explanation in _evaluations(record):
            await self._client.experiments.log_evaluation(
                experiment_run_id=run["id"],
                name=name,
                annotator_kind="CODE",
                start_time=ended,
                end_time=ended,
                score=score,
                label=label,
                explanation=explanation or None,
                timeout=self._timeout,
            )


@asynccontextmanager
async def open_phoenix_sink(settings: PhoenixSettings) -> AsyncGenerator[ResultSink]:
    """A sink whose HTTP client is built from our settings only and closed afterwards."""
    if settings.base_url is None:
        raise SinkError("PHOENIX_BASE_URL is not set: there is nowhere to publish to")
    headers = (
        {"Authorization": f"Bearer {settings.api_key.get_secret_value()}"}
        if settings.api_key
        else {}
    )
    async with httpx.AsyncClient(
        base_url=str(settings.base_url),
        headers=headers,
        timeout=settings.request_timeout_seconds,
    ) as http:
        yield PhoenixSink(
            AsyncClient(http_client=http),
            timeout_seconds=max(1, round(settings.request_timeout_seconds)),
        )


def _output(record: CaseRecord) -> dict[str, Any]:
    return {
        "hits": [
            {
                "rank": rank,
                "document_id": hit.document_id,
                "page": hit.page,
                "distance": round(hit.distance, 4),
                "text": hit.text[:_MAX_HIT_CHARS],
            }
            for rank, hit in enumerate(record.hits, start=1)
        ],
        "first_relevant_rank": record.scores.first_relevant_rank,
        "latency_seconds": round(record.latency_seconds, 3),
    }


def _evaluations(record: CaseRecord) -> Iterator[tuple[str, float, str, str]]:
    """(name, score, label, explanation) per metric, then the overall verdict."""
    scores = record.scores
    rank = scores.first_relevant_rank
    yield (
        "reciprocal_rank",
        scores.reciprocal_rank,
        f"rank {rank}" if rank else "not found",
        "",
    )
    for check in record.checks:
        value = scores.recall if check.name.startswith("recall@") else float(check.passed)
        yield check.name, value, "pass" if check.passed else "fail", check.detail
    failed = ", ".join(check.name for check in record.checks if not check.passed)
    yield (
        OVERALL,
        float(record.passed),
        "pass" if record.passed else "fail",
        f"failed: {failed}" if failed else "",
    )
