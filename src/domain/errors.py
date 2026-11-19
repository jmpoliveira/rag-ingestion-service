"""Domain errors.

Two families, because the pipeline reacts to them differently:

- ``FatalError``: the environment or the configuration is broken (source folder missing,
  embedding model unknown, vector store down, index contract mismatch). Every following
  document would fail the same way, so the whole run stops.
- Everything else is about **one document** (unparseable, too large, a malformed embedding
  response): it is recorded in the report and the run continues with the next document.

Messages are safe to show: upstream details stay in the logs (``raise ... from err``).
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain errors."""


class FatalError(DomainError):
    """The run cannot continue: retrying the next document would fail the same way."""


class SourceUnavailableError(FatalError):
    """The document source (for example the input folder) cannot be read."""


class DocumentRejectedError(DomainError):
    """One document cannot be ingested: unsupported, too large, encrypted or unparseable."""


class EmbeddingError(DomainError):
    """The embedding provider answered, but the answer is unusable for this document."""


class EmbeddingUnavailableError(EmbeddingError, FatalError):
    """Network failure, timeout or provider-side error, still failing after the retries."""


class EmbeddingConfigError(EmbeddingError, FatalError):
    """Unknown model or rejected credentials: a configuration problem."""


class VectorIndexError(DomainError):
    """The vector store rejected an operation for one document."""


class VectorIndexUnavailableError(VectorIndexError, FatalError):
    """The vector store cannot be reached."""


class IndexContractError(VectorIndexError, FatalError):
    """The collection was built with another embedding model, prefixes or schema."""
