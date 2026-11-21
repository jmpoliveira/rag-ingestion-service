"""Retrieval eval datasets (TOML, validated by pydantic; unknown fields are errors).

A case is a question a user could ask and the document(s) that hold the answer. Questions
should be paraphrases, not copies of the text: a copied sentence finds itself and measures
nothing.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections.abc import Set
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class DatasetError(ValueError):
    """The dataset file is missing, not TOML, or does not match the schema."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Expect(_Strict):
    # Relevant document ids (paths relative to the source folder). Any of them counts as a
    # hit; recall counts how many of them appear in the top k.
    sources: tuple[str, ...] = Field(min_length=1)
    # Optional: some chunk of a relevant source in the top k contains one of these texts,
    # i.e. the retrieved chunk holds the actual answer, not just the right document.
    evidence_any: tuple[str, ...] = ()
    # Documents that must not appear in the top k for this question (for example an archived
    # policy that contradicts the current one). Added to the dataset's `forbidden_sources`.
    forbidden_sources: tuple[str, ...] = ()


class ForbiddenPassage(_Strict):
    """A poisoned passage inside an otherwise legitimate document.

    Contamination is about what reaches the agent's prompt, and that is a chunk, not a
    document: the harmless sections of a document that hides one malicious paragraph are fine
    to retrieve. A retrieved chunk whose text contains `text` counts as contamination,
    whatever document it comes from. `source` says where the passage was planted; it must be
    indexed, otherwise contamination would always read 0.
    """

    source: str = Field(min_length=1)
    text: str = Field(min_length=1)


class Case(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    question: str = Field(min_length=1)
    tags: tuple[str, ...] = ()
    expect: Expect


class Dataset(_Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    version: int = Field(ge=1)
    description: str = ""
    # Where the documents of this dataset live; informative, for the person running it.
    corpus: str = ""
    k: int = Field(default=5, ge=1, le=50)
    # Documents that must not reach the top k of any question that does not ask for them:
    # planted attacks (ADR 0007). Their presence is the contamination rate.
    forbidden_sources: tuple[str, ...] = ()
    # Poisoned passages inside legitimate documents: forbidden at chunk level, in every case.
    forbidden_passages: tuple[ForbiddenPassage, ...] = ()
    cases: tuple[Case, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [case.id for case in self.cases]
        duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate case ids: {duplicates}")
        return self

    @property
    def fingerprint(self) -> str:
        """Hash of what is graded (k and the cases), not of comments or formatting."""
        graded = {
            "k": self.k,
            "forbidden_sources": sorted(self.forbidden_sources),
            "forbidden_passages": [p.model_dump() for p in self.forbidden_passages],
            "cases": [case.model_dump(mode="json") for case in self.cases],
        }
        text = json.dumps(graded, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    @property
    def sources(self) -> frozenset[str]:
        """Every document the dataset refers to, relevant or forbidden: all must be indexed,
        otherwise a forbidden document could never appear and contamination would read 0."""
        relevant = {source for case in self.cases for source in case.expect.sources}
        forbidden = {source for case in self.cases for source in case.expect.forbidden_sources}
        planted = {passage.source for passage in self.forbidden_passages}
        return frozenset(relevant | forbidden | planted | set(self.forbidden_sources))

    def forbidden_for(self, case: Case) -> frozenset[str]:
        """Forbidden documents for one question; a document it asks for is never forbidden."""
        forbidden = set(self.forbidden_sources) | set(case.expect.forbidden_sources)
        return frozenset(forbidden - set(case.expect.sources))

    @property
    def passages(self) -> tuple[str, ...]:
        """Poisoned passage texts; forbidden in every case, even in a relevant document."""
        return tuple(passage.text for passage in self.forbidden_passages)

    def select(self, ids: Set[str], tags: Set[str]) -> tuple[Case, ...]:
        if not ids and not tags:
            return self.cases
        return tuple(case for case in self.cases if case.id in ids or tags & set(case.tags))


def load_dataset(path: Path) -> Dataset:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as err:
        raise DatasetError(f"cannot read dataset {path}: {err.strerror}") from err
    except tomllib.TOMLDecodeError as err:
        raise DatasetError(f"{path} is not valid TOML: {err}") from err
    try:
        return Dataset.model_validate(raw)
    except ValidationError as err:
        raise DatasetError(f"{path} does not match the dataset schema:\n{err}") from err
