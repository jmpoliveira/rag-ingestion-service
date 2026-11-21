# rag-ingestion-service

[![CI](https://github.com/jmpoliveira/rag-ingestion-service/actions/workflows/ci.yml/badge.svg)](https://github.com/jmpoliveira/rag-ingestion-service/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

The ingestion side of a RAG system. It keeps a **ChromaDB** collection in sync with a set of
documents (PDF, Markdown, text): parse, clean, chunk, embed with **Ollama**, write. Runs are
**incremental and idempotent**: unchanged documents are skipped, changed ones replaced,
deleted ones removed, and a re-run or a crash never duplicates or loses a document. Every run
is traced with **OpenTelemetry** (Jaeger, Phoenix) and the resulting index is measured with
**retrieval evals**.

It is the companion of [ai-agent-service](https://github.com/jmpoliveira/ai-agent-service):
this service writes the knowledge base; the agent will read it through a
`search_knowledge_base` MCP tool (the agent's ADR 0004: retrieval is a tool, ingestion is a
separate deployable).

```
 SOURCE_DIR ──► FolderDocumentSource ──► IngestDocument (per document) ──► ChromaDB collection
  (events later: ADR 0002)                 read → parse → clean → chunk          ▲
                                           → embed (Ollama, batched) → write ─────┘
                                                                         contract + versions
```

## How a sync works

1. The source lists its documents: id (path relative to the folder), media type, SHA-256 of
   the content, size.
2. The collection is opened and its **index contract** checked: same embedding model, task
   prefixes, distance and schema as this configuration, or the run stops
   ([ADR 0004](docs/adr/0004-index-contract.md)).
3. For each document, a **version** is computed from its content hash and the pipeline
   settings. If exactly that version is already in the index, nothing happens. Otherwise the
   document is read, parsed, cleaned of hidden characters, chunked page by page, embedded in
   batches, and written: new chunks first, the completion marker last, then the old version's
   chunks are deleted ([ADR 0003](docs/adr/0003-idempotent-incremental-ingestion.md)).
4. Documents that left the folder are removed from the index (never when the folder is empty:
   a wrong path must not wipe the index).
5. A summary (and, with tracing on, the trace id) is printed; the exit code tells a scheduler what happened.

```
$ make ingest-samples
Sync finished: 6 indexed, 0 unchanged, 0 empty, 0 failed, 0 removed
$ make ingest-samples
Sync finished: 0 indexed, 6 unchanged, 0 empty, 0 failed, 0 removed
```

## Design goals

A RAG index is only as good as the pipeline that keeps it current. A first ingestion script
usually loads every file, embeds everything and writes the result; that works once, and fails
in ways that are easy to miss when it runs every night or on every upload. These are the
goals this service is built around, and where each one is decided:

| Goal | How | Decided in |
|---|---|---|
| Re-running costs nothing when nothing changed | each document has a version (content hash + pipeline settings); a version already indexed is skipped | [ADR 0003](docs/adr/0003-idempotent-incremental-ingestion.md) |
| A run never leaves the index empty or half-written | new chunks first, a completion marker last, old versions deleted after; a crash at any point is repaired by the next run | [ADR 0003](docs/adr/0003-idempotent-incremental-ingestion.md) |
| Deleted documents leave the index, but a wrong path never wipes it | reconciliation with the source, refused when the source looks empty | [ADR 0003](docs/adr/0003-idempotent-incremental-ingestion.md) |
| Vectors from different models are never mixed | the index contract (model, prefixes, distance, schema) is stored on the collection and checked on every write | [ADR 0004](docs/adr/0004-index-contract.md) |
| One bad file never stops the others; a broken dependency stops everything | per-document failures are reported; fatal errors (source, model, store) end the run with exit code 3 | [ADR 0001](docs/adr/0001-architecture.md) |
| Moving from a folder to events changes no pipeline code | the source is a port; one document is the unit of work | [ADR 0002](docs/adr/0002-document-sources.md) |
| Documents are treated as untrusted input | hidden characters removed, paths and sizes checked, content never silently altered | [ADR 0007](docs/adr/0007-untrusted-content.md) |
| Every run can be followed and every setting measured | one trace per sync with GenAI and DB spans; retrieval evals with hit@k, MRR, recall and evidence | [ADR 0006](docs/adr/0006-observability.md), [ADR 0005](docs/adr/0005-retrieval-evals.md) |

## Architecture

Clean Architecture, the same layering as ai-agent-service. Reasoning in [docs/adr](docs/adr).

| Layer | Contents | May depend on |
|---|---|---|
| `src/domain` | Documents, chunks, versions, the index contract, outcomes, errors. Pure Python. | nothing |
| `src/application` | Use cases `IngestDocument`, `SyncSource`, `InspectIndex`, `ResetIndex`; ports; text cleaning; span names | domain (+ `opentelemetry-api`, a documented exception) |
| `src/infrastructure` | Folder source, pypdf and text parsers, LangChain splitter, Ollama embedder with retry, Chroma index | domain, application |
| `src/interface` | The command line (`sync`, `inspect`, `reset`) and its exit codes | domain, application |
| `config/` | Settings (`pydantic-settings`), logging profiles, OpenTelemetry bootstrap | nothing in `src` |
| `main.py` | **Composition root**: the only place that wires everything | everything |
| `evals/` | Retrieval evals; uses the service, never used by it | everything above |

`tests/test_architecture.py` fails the build if a layer imports something it should not.

## Design decisions

| ADR | Decision | Trade-off accepted |
|---|---|---|
| [0001](docs/adr/0001-architecture.md) | Clean Architecture; ingestion as explicit use cases; fatal vs per-document errors | More files than a script; every step is testable without a network |
| [0002](docs/adr/0002-document-sources.md) | A folder today, events tomorrow: the source is a port, one document is the unit of work | Every sync hashes every file; fine up to thousands of documents |
| [0003](docs/adr/0003-idempotent-incremental-ingestion.md) | Versioned chunks, completion marker written last, old versions deleted after | Two versions can be briefly visible together; never none |
| [0004](docs/adr/0004-index-contract.md) | The index contract (model, prefixes, distance, schema) is stored on the collection and checked | A model change needs a new collection; mixing vector spaces becomes impossible |
| [0005](docs/adr/0005-retrieval-evals.md) | Retrieval evals over a public fictional corpus, published to Phoenix | A hand-written dataset is small; LLM-generated questions come later |
| [0006](docs/adr/0006-observability.md) | Traces through the docker-env collector to Jaeger and Phoenix; no document text in spans | Large syncs make large traces |
| [0007](docs/adr/0007-untrusted-content.md) | Documents are untrusted: remove hidden characters, never alter content; the agent defends at use; flag and quarantine proposed | Plain-language injections stay in the index until screening exists |

## Quick start

Requirements: Python 3.12+, Ollama with an embedding model, and ChromaDB 1.5 (a shared local
Docker stack, `docker-env`, runs both plus the OpenTelemetry Collector, Jaeger and Phoenix; or
use `make up` below).

```bash
make install
cp .env.example .env            # SOURCE_DIR, OLLAMA_BASE_URL, CHROMA_HOST/PORT, collection
ollama pull nomic-embed-text
make ingest                     # sync SOURCE_DIR into CHROMA_COLLECTION
```

| Command | What it does |
|---|---|
| `make ingest` | `python main.py sync`: incremental sync of `SOURCE_DIR` |
| `make ingest-samples` | sync `samples/knowledge-base` into `EVAL_COLLECTION` (for the evals) |
| `make inspect DOC=<id>` | read-only view of `CHROMA_COLLECTION`: contract, complete documents, and the chunks of `DOC` (optional) |
| `make inspect-samples DOC=<id>` | the same for `EVAL_COLLECTION`, e.g. `DOC=refund-policy.md` |
| `make reset CONFIRM=yes` | `python main.py reset --yes`: drop `CHROMA_COLLECTION` |
| `make reset-samples CONFIRM=yes` | drop `EVAL_COLLECTION` (the samples) |
| `make eval` | measure retrieval on `EVAL_COLLECTION` |

Exit codes: `0` everything is in the index, `1` some documents failed (the rest were indexed),
`2` invalid arguments or settings, `3` stopped: source missing, Ollama or Chroma unreachable,
model not pulled, or index contract mismatch.

## Configuration

Everything is in environment variables ([.env.example](.env.example)). Key points:

- **No hosts, ports or model names in code.** `SOURCE_DIR`, `OLLAMA_BASE_URL`,
  `EMBEDDING_MODEL`, `CHROMA_HOST` and `CHROMA_COLLECTION` are required.
- **Chunking** (`CHUNK_SIZE`, `CHUNK_OVERLAP`) is part of each document's version: changing it
  re-ingests everything on the next sync, automatically.
- **Embedding model, task prefixes and distance** are part of the collection's contract:
  changing them needs a new collection (or `make reset CONFIRM=yes`).
- **Limits**: `MAX_FILE_BYTES`, `MAX_PDF_PAGES`, `EMBEDDING_BATCH_SIZE`, `CHROMA_BATCH_SIZE`.
- `DELETE_MISSING=false` keeps documents that left the folder.
- `APP_ENV` selects the logging profile (`production` = JSON lines).

## Docker

The image is a one-shot job: it syncs the folder mounted at `/data` and exits with the CLI's
exit code, as a non-root user on a read-only filesystem.

| Command | Reaches Ollama, Chroma and tracing at |
|---|---|
| `make up` | its own Ollama (pulls `EMBEDDING_MODEL`), Chroma and Jaeger (profile `standalone`) |
| `make up-env` | the shared docker-env network; traces to the collector, so Jaeger and Phoenix |

`HOST_SOURCE_DIR=/path/to/docs make up-env` ingests another folder (default: the samples).

## Observability

With `OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT` pointing at the docker-env
collector, every sync is one trace:

```
ingest sync                                  (documents in the source)
└── ingest document  plans-and-pricing.md    (outcome, chunks, size)
    ├── read
    ├── parse                                (pages)
    ├── chunk                                (chunks)
    ├── embeddings nomic-embed-text          (gen_ai.*: provider, model, dimensions)
    ├── upsert knowledge-base                (db.*: collection, batch size)
    ├── upsert knowledge-base                (the completion marker)
    └── delete knowledge-base                (older versions)
```

Spans and logs carry ids, counts and outcomes, never document text. Logs carry the trace and
span ids ([ADR 0006](docs/adr/0006-observability.md)).

## Evals

Tests prove the pipeline works; **evals measure whether the index answers questions**. The
dataset ([evals/datasets/knowledge_base.toml](evals/datasets/knowledge_base.toml)) has 37
paraphrased support questions over a fictional help centre ([samples/](samples/README.md)) built
to be hard in realistic ways: long documents, a 9-page PDF, distractors that share the
question's words, an archived policy that contradicts the current one, and **planted
prompt-injection documents**. Besides hit@k, MRR, recall and evidence, the evals measure
**contamination**: how often a poisoned or outdated chunk reaches the top results, i.e. the
agent's prompt. Cases tagged `holdout` are never tuned against.

```bash
make ingest-samples
make eval                                   # hit@5, MRR, recall@5, evidence, contamination, per tag
make eval ARGS="--publish"                  # also explore it case by case in Phoenix
make eval ARGS="--baseline evals/baselines/<report>.json"
```

How to run and extend them: [evals/README.md](evals/README.md). The experiment plan is in
[evals/EXPERIMENTS.md](evals/EXPERIMENTS.md).

## Security notes

- Documents are untrusted input ([ADR 0007](docs/adr/0007-untrusted-content.md)). Text is
  NFC-normalised and stripped of control, zero-width and bidi-override characters before
  indexing. **Prompt injection written in plain words stays in the text**, on purpose: content
  is never altered on a guess, and the consumer (the agent) treats retrieved text as data, as
  it does with tool results. Flagging and quarantining suspicious documents is proposed.
- The folder source never follows symlinks, ignores hidden files, re-checks every id against
  the folder (ids will come from events), and enforces size and page limits. Encrypted and
  corrupted PDFs are rejected per document.
- Errors shown to users are fixed messages; upstream details stay in the logs.
- No secrets are needed today; `.env` is git-ignored and the Phoenix key is a `SecretStr`.
- Chroma's anonymous product telemetry is switched off in the client.

## Development

```bash
make check        # ruff + pyright (strict) + pytest
make cov          # coverage (minimum enforced in pyproject.toml)
```

CI runs the checks on Python 3.12, 3.13 and 3.14, and builds the image. Tests use in-memory
fakes for Ollama and Chroma; no network is needed.

`make test-live` is the smoke test of your own environment: with Ollama and Chroma from your
`.env` running (docker-env), it ingests the samples into a temporary collection, checks that
a second sync does nothing, that the contract and the vectors are real, and that a question
finds its document, then drops the collection. It is skipped by `make test` and in CI. Run
it before a pull request that touches an adapter or the settings. Workflow and releases:
[CONTRIBUTING.md](CONTRIBUTING.md).

## Status and known limits

**Verified automatically**: the use cases (incremental sync, versioning, interrupted writes,
deletions, the empty-folder guard, fatal vs per-document errors), the folder source's path
safety, the PDF and text parsers on real and malformed files, the chunker, error translation
for Ollama and Chroma, retries, settings, logging, the CLI (including `inspect`), the evals and the Phoenix sink
(against a fake of its REST API), and the dependency rule.

**Verified on request** (`make test-live`): the same pipeline against the real services in
your `.env`.

**Verified by hand**, against a real ChromaDB 1.5.9 server with a toy embedder: first sync,
no-op second sync, a changed file, a deleted file, a chunking change, the contract check, and
`inspect` on a missing, a mismatched and a matching collection.

**Not verified yet** (needs your environment): calls to a real Ollama, the Docker build and
run, the export to Jaeger and Phoenix through the collector, and the first eval baseline with
`nomic-embed-text`.

Known limits: chunks never cross page boundaries; scanned PDFs have no text (no OCR); every
sync hashes every file; documents are ingested one at a time.

## Next steps

In order, following the agent's rule: **measure first, then protect, then add features.**

| #   | Step                                                                                                        | Why                                                                   |
| --- | ----------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| 1   | **First baselines** (E0: defaults; E1: `nomic-embed-text` prefixes; E2: chunk size)                         | Every later change needs a number to beat                             |
| 2   | **Retrieval as an MCP tool** (`search_knowledge_base`, reading the index contract) and the agent's RAG step | The point of the index: the agent can finally answer from it          |
| 3   | **Structure-aware chunking** for Markdown (by heading) and chunk context (title + section in each chunk)    | Usually the largest retrieval gain after prefixes; measured by step 1 |
| 4   | **Event-driven trigger** (worker + blob source + dead-letter queue, ADR 0002)                               | Ingestion as soon as a document changes; horizontal scaling           |
| 5   | **Hybrid search and reranking** (BM25 + vectors, a cross-encoder)                                           | Exact terms (ids, error codes) that embeddings miss                   |
| 6   | **More formats and OCR** (DOCX, HTML; OCR for scanned PDFs)                                                 | Real corpora are mixed                                                |
| 7   | **Metrics and a dashboard** (documents per outcome, embedding latency)                                      | Alerts on scheduled runs                                              |
| 8   | **Access control metadata** (who may see a document, filtered at query time)                                | Required before indexing anything that is not public                  |
| 9   | **pgvector adapter**, compared with Chroma by the evals                                                     | Transactions make the write protocol atomic                           |
