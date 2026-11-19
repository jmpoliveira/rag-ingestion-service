"""Metrics, the JSON report (the source of truth) and the comparison with a baseline."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from evals.graders import Check, Scores
from evals.runner import CaseRecord
from src.domain.documents import SearchHit


class ReportError(ValueError):
    """A report file cannot be read or is not an eval report."""


@dataclass(frozen=True, slots=True)
class Summary:
    cases: int
    pass_rate: float
    hit_rate: float
    mrr: float
    mean_recall: float
    evidence_rate: float | None
    mean_latency_seconds: float
    per_tag: dict[str, dict[str, float]]


@dataclass(frozen=True, slots=True)
class SavedReport:
    meta: dict[str, Any]
    summary: dict[str, Any]
    records: list[CaseRecord]


def summarise(records: Sequence[CaseRecord]) -> Summary:
    def mean(values: Sequence[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    evidence = [c.passed for r in records for c in r.checks if c.name == "evidence"]
    tags = sorted({tag for record in records for tag in record.tags})
    per_tag = {
        tag: {
            "cases": float(len(subset)),
            "hit_rate": mean([float(r.scores.hit) for r in subset]),
            "mrr": mean([r.scores.reciprocal_rank for r in subset]),
        }
        for tag in tags
        if (subset := [r for r in records if tag in r.tags])
    }
    return Summary(
        cases=len(records),
        pass_rate=mean([float(r.passed) for r in records]),
        hit_rate=mean([float(r.scores.hit) for r in records]),
        mrr=mean([r.scores.reciprocal_rank for r in records]),
        mean_recall=mean([r.scores.recall for r in records]),
        evidence_rate=mean([float(p) for p in evidence]) if evidence else None,
        mean_latency_seconds=mean([r.latency_seconds for r in records]),
        per_tag=per_tag,
    )


def render(
    meta: Mapping[str, Any],
    summary: Summary,
    records: Sequence[CaseRecord],
    baseline: Mapping[str, Any] | None = None,
) -> str:
    k = meta.get("k", "?")
    lines = [
        f"Dataset {meta.get('dataset')} v{meta.get('dataset_version')} "
        f"({meta.get('dataset_fingerprint')}), collection {meta.get('collection')}, "
        f"model {meta.get('embedding_model')}, k={k}",
        "",
        f"  cases          {summary.cases}",
        f"  pass rate      {summary.pass_rate:.0%}",
        f"  hit@{k:<10} {summary.hit_rate:.0%}",
        f"  MRR            {summary.mrr:.3f}",
        f"  recall@{k:<7} {summary.mean_recall:.0%}",
    ]
    if summary.evidence_rate is not None:
        lines.append(f"  evidence       {summary.evidence_rate:.0%}")
    lines.append(f"  latency (avg)  {summary.mean_latency_seconds:.2f}s")
    if summary.per_tag:
        lines += ["", "  per tag: hit rate / MRR"]
        lines += [
            f"    {tag:<16} {values['hit_rate']:.0%} / {values['mrr']:.2f}"
            for tag, values in summary.per_tag.items()
        ]
    failed = [r for r in records if not r.passed]
    if failed:
        lines += ["", "  failed cases:"]
        for record in failed:
            for check in record.checks:
                if not check.passed:
                    lines.append(f"    {record.case_id} [{check.name}] {check.detail}")
    if baseline is not None:
        lines += ["", *_compare(meta, summary, baseline)]
    return "\n".join(lines)


def _compare(meta: Mapping[str, Any], summary: Summary, baseline: Mapping[str, Any]) -> list[str]:
    base_meta = cast(dict[str, Any], baseline.get("meta", {}))
    base_summary = cast(dict[str, Any], baseline.get("summary", {}))
    lines = [f"  compared with baseline (model {base_meta.get('embedding_model')}):"]
    if base_meta.get("dataset_fingerprint") != meta.get("dataset_fingerprint"):
        lines.append("    WARNING: the baseline was graded with another dataset; deltas mislead")
    for name in ("pass_rate", "hit_rate", "mrr", "mean_recall"):
        before = base_summary.get(name)
        if isinstance(before, int | float):
            now = cast(float, getattr(summary, name))
            lines.append(f"    {name:<12} {before:.3f} -> {now:.3f} ({now - before:+.3f})")
    return lines


def write_report(
    path: Path, meta: Mapping[str, Any], summary: Summary, records: Sequence[CaseRecord]
) -> None:
    document = {
        "meta": dict(meta),
        "summary": asdict(summary),
        "records": [_record_to_json(record) for record in records],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_report(path: Path) -> SavedReport:
    try:
        document: Any = json.loads(path.read_text(encoding="utf-8"))
    except OSError as err:
        raise ReportError(f"cannot read report {path}: {err.strerror}") from err
    except json.JSONDecodeError as err:
        raise ReportError(f"{path} is not JSON: {err.msg}") from err
    if not isinstance(document, dict) or not {"meta", "summary", "records"} <= document.keys():
        raise ReportError(f"{path} is not an eval report")
    data = cast(dict[str, Any], document)
    try:
        records = [_record_from_json(item) for item in data["records"]]
    except (KeyError, TypeError, ValueError) as err:
        raise ReportError(f"{path} has a malformed record: {err}") from err
    return SavedReport(data["meta"], data["summary"], records)


def _record_to_json(record: CaseRecord) -> dict[str, Any]:
    return {
        "case_id": record.case_id,
        "question": record.question,
        "tags": list(record.tags),
        "passed": record.passed,
        "scores": asdict(record.scores),
        "checks": [asdict(check) for check in record.checks],
        "hits": [asdict(hit) for hit in record.hits],
        "latency_seconds": round(record.latency_seconds, 4),
        "started_at": record.started_at.isoformat(),
        "trace_id": record.trace_id,
    }


def _record_from_json(item: dict[str, Any]) -> CaseRecord:
    return CaseRecord(
        case_id=str(item["case_id"]),
        question=str(item["question"]),
        tags=tuple(str(tag) for tag in item["tags"]),
        hits=tuple(SearchHit(**hit) for hit in item["hits"]),
        scores=Scores(**item["scores"]),
        checks=tuple(Check(**check) for check in item["checks"]),
        latency_seconds=float(item["latency_seconds"]),
        started_at=datetime.fromisoformat(str(item["started_at"])),
        trace_id=item.get("trace_id"),
    )
