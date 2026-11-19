# CLAUDE.md

Guidance for Claude Code and other AI assistants working in this repository.

## What this is

The ingestion side of a RAG system: `SyncSource` reconciles a document source (a folder
today) with a ChromaDB collection, calling `IngestDocument` per document (read, parse, clean,
chunk, embed with Ollama, write). Read `README.md` and `docs/adr/` before changing the
architecture. The companion `ai-agent-service` will read the index through an MCP tool.

Non-negotiables from the ADRs:

- Ingestion is incremental and idempotent (ADR 0003): versioned chunk ids, the marker chunk
  (index 0) written last, old versions deleted after. Never drop the collection in a sync.
- The index contract lives on the collection (ADR 0004): never write into a collection
  created with another model, prefixes or distance.
- New triggers (events) call the same use cases (ADR 0002); new formats are new parsers.
- Documents are untrusted (ADR 0007): never alter or drop content on a guess; never log or
  trace document text (`inspect` prints it to the operator's terminal only).

## Commands

```bash
make install      # create .venv and install with dev dependencies
make check        # ruff + pyright (strict) + pytest. Run before saying a task is done.
make cov          # coverage, fails under the minimum in pyproject.toml
make test-live    # smoke test against the real Ollama and Chroma in .env (skipped otherwise)
make ingest       # sync SOURCE_DIR (needs Ollama and Chroma)
make inspect DOC=<id>  # read-only view of the collection and one document's chunks
make eval         # retrieval evals (needs Ollama and Chroma; not part of make check)
```

## Language and style

- All code, docstrings, comments, identifiers, test names, commit and PR text: **English**.
- Python 3.12+, full type hints (pyright strict), `async/await` for I/O, CPU-bound work
  (PDF parsing, hashing) in `asyncio.to_thread`, context managers, `pathlib`, ruff.

## Architecture rules (enforced by `tests/test_architecture.py`)

- `domain` -> nothing. `application` -> domain (+ `opentelemetry-api`). `infrastructure` ->
  domain, application. `interface` -> domain, application. `config/` never imports `src`.
- `main.py` is the **composition root**. Ports live in `src/application/ports.py`.
- Span and attribute names live **only** in `src/application/telemetry.py`. Never put document
  text in spans or logs.
- The service never imports `evals`; only `evals/phoenix_sink.py` imports `phoenix`.

## Configuration

- All configuration is in `config/settings.py` (`pydantic-settings`). Never hard-code hosts,
  ports, URLs or model names. Update `.env.example` whenever a setting is added.
- Secrets are `SecretStr`. Never log them, never commit `.env`, never ask for them in chat.

## Dependencies

- Official, stable libraries only: no pre-releases, no `langchain-community` or
  `langchain-experimental`. Pin the **major** version. Check the current stable version on
  PyPI before adding or bumping one; do not rely on memory.
- `chromadb-client` must stay on the same major as the Chroma server in docker-env.

## Errors

- `FatalError` subclasses stop the run (exit 3); other domain errors fail one document.
- Catch specific exceptions; no bare `except:`; no unlogged `except Exception:`; chain with
  `raise ... from err`. Domain errors carry safe messages.

## Tests

- `pytest`, mirroring `src/` under `tests/`, Arrange-Act-Assert, runnable from the repo root.
- Mock external services (Ollama, Chroma, Phoenix): fakes in `tests/fakes.py`. The only tests
  that reach real services are marked `live` (`tests/integration/`), skipped unless `--live`.
- Cover edge cases: empty input, oversized input, corrupted and encrypted files, malformed
  provider output, missing settings.
- Changing a sample document or an eval case: bump the dataset `version`.
- Do not commit or push unless asked.

## Git workflow

`main` and tags are protected on GitHub (once the rulesets are set up, see `CONTRIBUTING.md`):
changes go through a branch and a pull request with green checks, merges are squash or rebase,
and a release is tagged on `main` after the merge. Never suggest `git push origin main`,
`--follow-tags` or tagging on a branch.
