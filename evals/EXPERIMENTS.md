# Retrieval experiments

One change at a time, measured on the same dataset against the run before. Each experiment
records the setting changed, the report, the numbers and what the failures say, so a decision
can be traced back to evidence (the same method as ai-agent-service's `evals/EXPERIMENTS.md`).

A change to the embedding model or the prefixes needs a **new collection** (the index contract
refuses to mix them): ingest the samples into e.g. `EVAL_COLLECTION=tessera-kb-e1` and compare
reports with `--baseline`.

## Plan

| Id | Change | Hypothesis | Collection |
|---|---|---|---|
| E0 | Defaults: `nomic-embed-text`, no prefixes, chunks of 1000/200 | The baseline | `tessera-kb` |
| E1 | `EMBEDDING_DOCUMENT_PREFIX="search_document: "`, `EMBEDDING_QUERY_PREFIX="search_query: "` | The model was trained with them: MRR goes up, most on paraphrases | `tessera-kb-e1` |
| E2 | `CHUNK_SIZE=500`, `CHUNK_OVERLAP=100` (on the E0/E1 winner) | Smaller chunks rank the right passage higher (evidence up), maybe at the cost of the multi-document case | same as the winner (chunking re-ingests by itself) |
| E3 | Another embedding model (for example a multilingual one) | The Portuguese cases improve | new collection |

## Log

No runs yet. The first entry is E0, run with `make ingest-samples && make eval`; copy its
report to `evals/baselines/` and commit it.
