# Retrieval evals

Measure the index this service builds: for a set of questions, does similarity search return
the document (and the passage) that answers each one? Unit tests prove the pipeline works;
evals tell whether a chunk size, a model or a prefix makes the index **better**.

Design and alternatives: [ADR 0005](../docs/adr/0005-retrieval-evals.md).

## Running

Ollama (with `EMBEDDING_MODEL` pulled) and Chroma must be running, as for `make ingest`.

```bash
make ingest-samples                         # samples/knowledge-base -> EVAL_COLLECTION (tessera-kb)
make eval                                   # all cases
make eval ARGS="--tag portuguese"           # some cases (also --case <id>, repeatable)
make eval ARGS="--baseline evals/baselines/<report>.json"
make eval ARGS="--publish"                  # also publish to Phoenix
make publish REPORT=evals/results/<report>.json
EVAL_COLLECTION=tessera-kb-e1 make eval     # measure another collection
```

| Option | Default | What it does |
|---|---|---|
| `--dataset PATH` | `evals/datasets/knowledge_base.toml` | Dataset to run |
| `--collection NAME` | `CHROMA_COLLECTION` (the Makefile passes `EVAL_COLLECTION`) | Collection to measure |
| `--case ID` / `--tag TAG` | all | Select cases; repeatable |
| `--baseline PATH` | none | Compare with an earlier report (warns if the dataset differs) |
| `--output-dir DIR` | `evals/results` | Where the JSON report goes (git-ignored) |
| `--fail-under RATE` | none | Exit 1 when the hit rate is below RATE, for a later CI gate |
| `--publish` | off | Publish the report to Phoenix after writing it |
| `--verbose` | off | Show the service logs |

Exit codes: `0` done, `1` below `--fail-under`, `2` invalid options or settings, or the eval
was aborted (expected documents missing from the collection, Ollama or Chroma down),
`3` `publish` could not reach Phoenix.

The eval embeds each question with the same embedder the service uses (same model and query
prefix), so it measures the index as the retriever will see it. It refuses to run when the
dataset's documents are not in the collection.

## Metrics

| Metric | Question it answers |
|---|---|
| **hit@k** | Is a relevant document in the top k at all? |
| **MRR** | Does the right chunk come *first*? (mean of 1 / rank of the first relevant chunk) |
| **recall@k** | For questions needing several documents, how many were found? |
| **evidence** | Does a relevant chunk in the top k contain the answer text? A hit with the wrong chunk points at chunking. |
| **per tag** | Where the failures are: paraphrases, Portuguese, multi-document... |

A case passes when every check passes. Retrieval is deterministic for a fixed model and index,
so each case runs once.

## Writing a case

```toml
[[cases]]
id = "refund-annual"                       # lowercase, digits and dashes
question = "We bought a yearly plan two weeks ago. Can we still get our money back?"
tags = ["refunds", "paraphrase"]
[cases.expect]
sources = ["refund-policy.md"]             # document ids: paths relative to the source folder
evidence_any = ["within 30 days"]          # optional: text the retrieved chunk must contain
```

Rules of thumb:

- Paraphrase. A question that copies the document's sentence finds itself and measures
  nothing; write it the way a customer would ask.
- Bump `version` whenever a case or an expectation changes; reports from different dataset
  fingerprints are not comparable (the comparison warns, publishing refuses).
- A test checks that every source exists in `samples/knowledge-base` and every evidence text
  appears in it.
- Keep a few cases you never tune against, to notice overfitting.

## Reports and Phoenix

The JSON report is the source of truth: settings (collection, model, prefixes, distance,
chunking, k), dataset fingerprint, git commit, and per case the ranked hits with their text,
the scores, the checks and the trace id. Copy a report to `evals/baselines/` to keep it.

Published to Phoenix (`PHOENIX_BASE_URL`, the `.[evals]` extra): one dataset per
`<name>-v<version>-<fingerprint>`, one experiment per report, one run per case with the
ranked hits, and one evaluation per metric. With `OTEL_ENABLED=true`, each case's trace
(query embedding, then search) opens from its run.
