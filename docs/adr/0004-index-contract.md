# ADR 0004: The index contract lives on the collection

Status: accepted

## Context

This service writes the index; other components read it: today the `rag-query-service`
prototype, tomorrow a `search_knowledge_base` MCP tool used by `ai-agent-service` (its
ADR 0004: retrieval is a tool). The reader must embed questions **exactly** as the documents
were embedded: same model, same task prefixes (`nomic-embed-text` expects
`search_document: ` for documents and `search_query: ` for questions), same distance. If not,
nothing fails: similarity search still returns five chunks, just worse ones. This is the
most dangerous kind of RAG bug, because only an eval notices it.

The old service and the query prototype each read `EMBEDDING_MODEL_NAME` from their own
`.env`, and nothing checked that the two agreed.

## Decision

1. **The contract is stored as collection metadata when the collection is created**:
   `rag.schema_version`, `rag.embedding.provider`, `rag.embedding.model`,
   `rag.embedding.document_prefix`, `rag.embedding.query_prefix`, `rag.distance`
   (`src/domain/index.py`). Readers take the model and the query prefix from the collection,
   not from their own configuration.
2. **Opening a collection checks it and never changes it.** A collection created under another
   contract, or without one (the old service's `rag_collection`), is refused with an error
   that names every difference (`IndexContractError`, a fatal error). Changing the model means
   a new collection (or `reset`), never a silent mix of two vector spaces.
3. **Per-chunk metadata is part of the contract (schema version 1)**: `document_id`,
   `media_type`, `content_hash`, `version`, `page`, `chunk_index`, `chunk_count`,
   `start_index`; the chunk text is the Chroma document. A reader can cite the source and the
   page, and fetch neighbouring chunks.
4. **Vectors are always ours.** The collection has no embedding function, so Chroma never
   downloads or runs a model of its own, and the Chroma client's anonymous telemetry is off.
5. **ChromaDB, through `chromadb-client`** (the HTTP client only, matching the 1.5.x server in
   docker-env). Cosine distance by default, fixed at creation.

## Alternatives considered

- **A shared configuration file or library** for both services. It still lets a deployment
  drift (one service redeployed with a new `.env`); the collection is the only place that
  cannot disagree with its own vectors.
- **pgvector** (also in docker-env). Transactions would make the write protocol of ADR 0003
  atomic, and SQL filters are richer. Chroma is simpler to run and to inspect while learning;
  the `VectorIndex` port keeps the move to pgvector a new adapter, and the evals would measure
  it.
- **`langchain-chroma`** (used by the old service). Adds little over the client: no control of
  ids or of the contract check, and its "async" was the blocking client.

## Consequences

- The first sync after this change refuses the old `rag_collection`: use a new name
  (`knowledge-base` by default) or reset it.
- Switching the embedding model is a blue/green operation: ingest into a new collection, run
  the retrieval evals on both, then point the readers at the winner.
- The retriever should be updated to read the contract (next steps in the README).
