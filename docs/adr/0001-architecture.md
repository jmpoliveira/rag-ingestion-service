# ADR 0001: Clean Architecture, with ingestion as explicit use cases

Status: accepted

## Context

This service replaces `rag-ingestion-service-old`, a script-like pipeline (`main.py` calling a
PDF loader, a splitter and a vector store class) that worked for a demo but:

- **dropped the whole collection on every run** and re-embedded everything, so the index was
  empty while a run was in progress, and a failed run left it empty;
- had no notion of a document's identity, so it could not skip unchanged files, replace a
  changed one, or remove a deleted one;
- read configuration from a global object imported by every module, hard-coded the OTLP
  endpoint (`localhost:4317`), and created the input folder when it was missing (hiding a
  wrong path behind "no documents found");
- was synchronous under an `async` name (`Chroma.from_documents` blocks), wrote log files
  itself, and had one test file.

Its sibling, `ai-agent-service`, already set the standard for these repositories: Clean
Architecture, ports, a composition root, a dependency rule enforced by a test, structured
logs with trace ids, OpenTelemetry, evals, and ADRs.

## Decision

1. **Same layering as ai-agent-service**: `domain` <- `application` <- `infrastructure` /
   `interface`, with `main.py` as the composition root. `tests/test_architecture.py`
   enforces it, plus two rules of this repository: the service never imports `evals`, and
   only `evals/phoenix_sink.py` imports Phoenix.
2. **The pipeline is two use cases**, not one function:
   - `IngestDocument`: one document into an open index (read, parse, clean, chunk, embed in
     batches, write, clean up). It is the unit of work for every trigger (ADR 0002).
   - `SyncSource`: reconcile a whole source with the index (ADR 0003).
   - `InspectIndex`: read-only view of a collection (contract, complete documents, the stored
     chunks of one document); never creates or changes it.
   - `ResetIndex`: drop the collection, only on explicit request.
3. **Ports for what changes independently**: `DocumentSource` (folder today, blob storage
   tomorrow), `DocumentParser` (one per media type), `Chunker`, `Embedder` (Ollama today; Azure
   OpenAI or Gemini through other LangChain partner packages), `VectorIndex` /
   `VectorIndexProvider` (Chroma today; pgvector is in docker-env too).
4. **Errors in two families** (`src/domain/errors.py`): `FatalError` stops the run (source
   missing, model unknown, vector store down, contract mismatch); everything else fails one
   document, which is reported while the run continues. Exit codes follow (0, 1, 2, 3).
5. **`opentelemetry-api` is allowed in `application`**, as in the agent: the API is already
   vendor-neutral, and span names live in one module (`application/telemetry.py`).
6. **Async where there is I/O; threads where there is CPU.** PDF parsing and file hashing run
   in `asyncio.to_thread`, so they never block the event loop that talks to Ollama and Chroma.

## Alternatives considered

- **Keep the old structure and fix the bugs.** The bugs come from the structure: without a
  document identity and a per-document use case, incremental ingestion and events have
  nowhere to go.
- **LangChain's indexing API (`index()` with a `RecordManager`).** It solves incremental
  ingestion, but its record manager needs a SQL database, and it hides the mechanics this
  project exists to show. ADR 0003 implements the same idea with the vector store alone.
- **A pipeline framework (LlamaIndex ingestion pipeline, Haystack).** Good for many
  connectors; heavier, and the agent would end up with two different stacks.

## Consequences

- Every use case is tested with in-memory fakes, with no network; the Chroma adapter is
  tested against a scripted client, and was checked by hand against a real Chroma 1.5.9.
- Adding a format is a new `DocumentParser`; adding a trigger is a new interface module
  calling the same use cases; adding a provider is a new `Embedder` adapter.
- More files than the old service. The dependency test keeps them honest.
