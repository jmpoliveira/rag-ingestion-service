"""The index contract: what a collection promises to whoever queries it (ADR 0004).

Vectors are only comparable when they come from the same embedding model with the same
task prefixes. A retriever that embeds a question differently from how the documents were
embedded gets plausible-looking but wrong results, with no error anywhere. So the contract
is stored *on the collection* when it is created, checked every time this service opens
it, and readable by the retriever, which learns from it how to embed its queries.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from src.domain.errors import IndexContractError

# Bump when the chunk metadata schema changes in a way a retriever would notice.
SCHEMA_VERSION = 1

Distance = Literal["cosine", "l2", "ip"]

# Collection metadata keys. The retriever reads the same names.
KEY_SCHEMA = "rag.schema_version"
KEY_PROVIDER = "rag.embedding.provider"
KEY_MODEL = "rag.embedding.model"
KEY_DOCUMENT_PREFIX = "rag.embedding.document_prefix"
KEY_QUERY_PREFIX = "rag.embedding.query_prefix"
KEY_DISTANCE = "rag.distance"


@dataclass(frozen=True, slots=True)
class IndexSpec:
    collection: str
    embedding_provider: str
    embedding_model: str
    document_prefix: str = ""
    query_prefix: str = ""
    distance: Distance = "cosine"
    schema_version: int = SCHEMA_VERSION

    def as_metadata(self) -> dict[str, str | int]:
        return {
            KEY_SCHEMA: self.schema_version,
            KEY_PROVIDER: self.embedding_provider,
            KEY_MODEL: self.embedding_model,
            KEY_DOCUMENT_PREFIX: self.document_prefix,
            KEY_QUERY_PREFIX: self.query_prefix,
            KEY_DISTANCE: self.distance,
        }

    def check(self, existing: Mapping[str, object] | None) -> None:
        """Refuse to write into a collection built under another contract.

        Raises:
            IndexContractError: naming every field that differs.
        """
        if not existing or KEY_SCHEMA not in existing:
            raise IndexContractError(
                f"Collection '{self.collection}' has no index contract: it was not created by "
                "this service. Use another collection name, or reset it."
            )
        expected = self.as_metadata()
        differences = [
            f"{key}: collection has {existing.get(key)!r}, settings say {value!r}"
            for key, value in expected.items()
            if existing.get(key) != value
        ]
        if differences:
            raise IndexContractError(
                f"Collection '{self.collection}' was built under another contract ("
                + "; ".join(differences)
                + "). Re-index into a new collection, or reset this one."
            )
