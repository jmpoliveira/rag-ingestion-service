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
        graded = {"k": self.k, "cases": [case.model_dump(mode="json") for case in self.cases]}
        text = json.dumps(graded, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    @property
    def sources(self) -> frozenset[str]:
        return frozenset(source for case in self.cases for source in case.expect.sources)

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
