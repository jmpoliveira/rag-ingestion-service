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

## Lessons so far

- On a corpus this small (6 documents, about 20 chunks), **hit@5 saturates**: a top 5 is a
  quarter of the index. MRR is the metric that tells experiments apart; read it first.
- **Read every failure before changing the system.** The only failure of the first run was a
  wrong expectation in the dataset, not a retrieval problem.

## Log

### E0: defaults (baseline)

Setting: `nomic-embed-text` (Ollama), no prefixes, chunks 1000/200, cosine, k = 5.
Collection `tessera-kb`. Commit `3c75894`.

**First run, dataset v1** (report not kept; replaced by the v2 run below):
17/18 passed, hit@5 100%, MRR 0.889, recall@5 97%, evidence 100%.

What the failures and weak ranks said:

| Case | Result | Reading |
|---|---|---|
| `uptime-and-credits` | recall 50% (failed) | **Dataset error.** The "Service credits" chunk of `support-sla.md` (rank 1) states the 99.9% commitment and the credits, so it answers the whole question alone; expecting `plans-and-pricing.md` too was wrong. Fixed in dataset v2 with a question that really needs two documents. |
| `cancelled-workspace` | rank 4 | "our **tickets** after we **cancel**" pulls `ticket-lifecycle.md` and `refund-policy.md` ahead of the privacy article: surface words over meaning. Candidate for E1 (prefixes) and E2 (smaller, more focused chunks). |
| `pt-monthly-refund` | rank 4 | Portuguese: every distance above 0.52 (relevant hits usually 0.25 to 0.40). The model is English-centric. Candidate for E3. |
| `no-answer-escalation` | rank 2 | A tie (0.350 vs 0.350) between the SLA and the ticket lifecycle. |
| `pt-medium-priority-pro` | rank 1 | Passed, probably through the shared tokens "ticket" and "Pro" rather than understanding. |

Also noted: margins between rank 1 and rank 2 are often a few hundredths of a distance, so
rankings are right but fragile; with 1000-character chunks most documents are one or two
chunks, so `evidence` is easy here (E2 will make it meaningful).

**Baseline run, dataset v2**: to be recorded from the committed report in
`evals/baselines/`. The 17 unchanged cases are deterministic and should repeat the numbers
above; only `two-factor-plans-price` is new.
