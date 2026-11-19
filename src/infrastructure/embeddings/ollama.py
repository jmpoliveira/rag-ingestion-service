"""Embeddings on Ollama through the official LangChain partner package.

Same choice as the agent's chat adapters (ai-agent-service ADR 0002): the LangChain
``Embeddings`` interface is shared by the partner packages for Azure OpenAI, Gemini and
others, so a second provider is a second small adapter behind the same port.

Task prefixes: some embedding models are trained with an instruction in front of the text
(``nomic-embed-text`` expects ``search_document: `` and ``search_query: ``). They are
configuration, applied here, and recorded in the index contract so the retriever uses the
same ones (ADR 0004).
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx
from langchain_ollama import OllamaEmbeddings
from ollama import ResponseError

from src.domain.errors import EmbeddingConfigError, EmbeddingError, EmbeddingUnavailableError

_PROVIDER = "ollama"
_CONFIG_STATUSES = frozenset({401, 403, 404})


class OllamaEmbedder:
    def __init__(
        self,
        embeddings: OllamaEmbeddings,
        *,
        document_prefix: str = "",
        query_prefix: str = "",
    ) -> None:
        self._embeddings = embeddings
        self._document_prefix = document_prefix
        self._query_prefix = query_prefix

    @property
    def provider(self) -> str:
        return _PROVIDER

    @property
    def model(self) -> str:
        return self._embeddings.model

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return await self._embed([self._document_prefix + text for text in texts])

    async def embed_query(self, text: str) -> Sequence[float]:
        vectors = await self._embed([self._query_prefix + text])
        if len(vectors) != 1:
            raise EmbeddingError("Embedding provider returned no vector for the query")
        return vectors[0]

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return await self._embeddings.aembed_documents(texts)
        except ResponseError as err:
            raise _from_response_error(err, self.model) from err
        # The ollama client turns a refused connection into the builtin ConnectionError.
        except (httpx.TransportError, ConnectionError, TimeoutError) as err:
            raise EmbeddingUnavailableError("Embedding provider is unreachable") from err


def _from_response_error(err: ResponseError, model: str) -> EmbeddingError:
    status = err.status_code
    if status == 404:
        return EmbeddingConfigError(f"Embedding model '{model}' is not available on Ollama")
    if status in _CONFIG_STATUSES:
        return EmbeddingConfigError("Embedding provider rejected the credentials")
    if status == 429 or status >= 500:
        return EmbeddingUnavailableError(f"Embedding provider failed (status {status})")
    return EmbeddingError(f"Embedding provider rejected the request (status {status})")


def create_ollama_embedder(
    *,
    base_url: str,
    model: str,
    timeout_seconds: float,
    document_prefix: str = "",
    query_prefix: str = "",
) -> OllamaEmbedder:
    embeddings = OllamaEmbeddings(
        model=model,
        base_url=base_url,
        client_kwargs={"timeout": timeout_seconds},
        # Checked on the first request instead, where a missing model becomes a clean
        # EmbeddingConfigError; validating here would make a network call at wiring time.
        validate_model_on_init=False,
    )
    return OllamaEmbedder(embeddings, document_prefix=document_prefix, query_prefix=query_prefix)
