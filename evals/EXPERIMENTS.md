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
- **Measure the unit that matters.** Contamination per document over-reported: a document
  with one malicious paragraph is harmful only through the chunk that holds it.
- **GitHub's "rebase and merge" gives commits new hashes.** A report records the commit it ran
  on, which is the branch commit; eval branches are therefore kept after merging, so every
  `git_commit` in a report stays reachable.
- **A saturated dataset cannot compare anything.** E0 on v2 passed 18/18 with hit@5 100%, so
  E1 and E2 could only differ by a few hundredths of MRR. Dataset v3 grows the corpus to 16
  documents (long documents, a PDF, distractors, an archived policy, planted attacks) and 37
  cases, before any experiment runs. The E0 baseline is therefore re-run on v3 (E0').

## Log

### E0': defaults on dataset v4 (the baseline for E1 onwards)

Same settings as E0 (`nomic-embed-text`, no prefixes, chunks 1000/200, cosine, k = 5) on
the v3 corpus (16 documents), with contamination measured per chunk (dataset v4). Commit
`7fe52a6` on branch `eval/corpus-v3-b`, clean tree; report
`evals/baselines/20261121-173133-tessera-kb-knowledge_base.json`. A first run on dataset v3,
which counted whole documents, was used to design v4 and is not kept.

| Metric | E0 (v2, 6 documents) | **E0' (v4, 16 documents)** |
|---|---|---|
| hit@5 | 100% | **94.6%** |
| **MRR** | 0.889 | **0.809** |
| recall@5 | 100% | 94.6% |
| evidence | 100% | 94.6% |
| **contamination** | - | **48.6%** (18/37) |
| pass rate | 100% | 51.4% (mostly contamination) |

The corpus did its job: the numbers now say things. Read quality (hit, MRR) and safety
(contamination) separately; the pass rate mixes them.

**1. One spam document does most of the damage.** `community/billing-tips.md` (keyword
stuffing plus an instruction) is in the top 5 of 17 of the 37 questions, and at rank 1 in
two: `cancelled-workspace` and `pt-monthly-refund`, which lose their relevant document
entirely. Those are the only two hit failures: a single malicious document took hit@5 from
100% to 94.6%. Without it, contamination would be 5/37 (13.5%). Screening at ingestion
(ADR 0007, decision 4) is therefore a quality measure as much as a security one.

**2. The archived policy outranks the current one.** In 3 of the 4 refund questions,
`archive/refund-policy-2024.md` (14 days) is at rank 1, ahead of `refund-policy.md` (30 days):
it is shorter and more focused, so its vector is "purer". The agent would read the wrong rule
first. No embedding can fix this, because both versions say the same thing with different
numbers: it needs document lifecycle metadata (status, validity dates) and a filter in the
retriever. Candidate ADR.

**3. The planted paragraph travels with its neighbours.** `release-notes/2026-10.md` has two
chunks; the first holds the Teams, search and satisfaction sections *and* the malicious
paragraph. `dark-theme` (a question about the September notes) pulls that chunk at rank 3.
Smaller chunks would isolate the paragraph: E2 is also a security experiment.

**4. The rest of the index is healthy.**
- PDF: 5/5 at rank 1, with the right page (encryption on page 3, incidents on page 7).
- Long documents: hit 100%, MRR 0.82; `evidence` finds the right section inside a
  2,800-word guide.
- Weak: `price-increase-notice` (rank 4: "Changing plan" in the pricing article beats the
  price clause of the terms), `liability-cap` (2), `free-seat-limit` (3),
  `erasure-request` (3), Portuguese (hit 0.67).
- Holdout: hit 100%, MRR 0.75, in line with the rest (nothing has been tuned yet).

**Next, in order:** E1 (prefixes), which may also weaken the keyword-stuffing effect; then
E2 (chunks of 500/100), for ranking and for isolating the planted paragraph; then the
lifecycle metadata for archived documents and the screening of ADR 0007, whose target is
contamination 0 without losing relevant documents.

### E0: defaults (baseline on dataset v2)

Setting: `nomic-embed-text` (Ollama), no prefixes, chunks 1000/200, cosine, k = 5.
Collection `tessera-kb`. The v1 run was on commit `3c75894`.

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

**Baseline run, dataset v2** (commit `181b4b2` on branch `eval/e0-baseline`, kept for
provenance; the rebase merge put it on `main` as `adcf20d`. Clean tree; report
`evals/baselines/20261119-173333-tessera-kb-knowledge_base.json`):

| Metric | Value |
|---|---|
| pass rate | 18/18 (100%) |
| hit@5 | 100% |
| **MRR** | **0.889** |
| recall@5 | 100% |
| evidence | 100% |
| latency per question | 0.04 s |

The 17 unchanged cases repeated their v1 ranks exactly (retrieval is deterministic). The new
`two-factor-plans-price` found both documents at ranks 1 and 2. The weak ranks are the targets
of the next experiments: `cancelled-workspace` (4), `pt-monthly-refund` (4),
`no-answer-escalation` (2). With every check passing, **MRR is the number E1 and E2 must beat**.
