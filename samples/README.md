# Sample knowledge base

`knowledge-base/` is the help centre of **Tessera Support Cloud**, an invented ticketing
product. The companion [mcp-server](https://github.com/jmpoliveira/mcp-server) serves mock
customers (Acme Corp, Globex, Initech) who use it, so the agent can later combine their
tickets with these documents. Everything here is invented, so the repository can be public
and the evals reproducible. The retrieval evals (`evals/datasets/knowledge_base.toml`) are
written against these files: changing one means reviewing the cases and bumping the dataset
version.

```bash
make ingest-samples   # ingests this folder into its own collection (EVAL_COLLECTION, default tessera-kb)
make eval             # measures retrieval on that collection
```

## What is in it, and why

The corpus is built to be hard in the ways real knowledge bases are hard, not to be large.

| Documents | Why they are there |
|---|---|
| `plans-and-pricing.md`, `support-sla.md`, `ticket-lifecycle.md`, `refund-policy.md`, `policies/` | Short articles: the original corpus |
| `admin-guide.md`, `terms-of-service.md` | Long documents (thousands of words): the answer sits in one section among many, which tests chunking |
| `security-whitepaper.pdf` | A 9-page PDF, one section per page: tests the PDF parser and page numbers |
| `release-notes/`, `api/`, `onboarding/` | Distractors: they share words such as "refund", "SLA", "ticket" without answering most questions |
| `archive/refund-policy-2024.md` | An outdated policy that **contradicts** the current one (14 days instead of 30) |
| Planted attacks (below) | Prompt injection for the contamination metric (ADR 0007) |

Formats are mixed on purpose (Markdown, plain text, PDF), and subfolders make document ids
paths such as `policies/account-security.txt`.

## Planted prompt-injection attacks

These files contain instructions aimed at an AI assistant. They are **test fixtures**: the
instructions are harmless, and they exist so the evals can measure how often such text would
reach an agent's prompt.

| File | Attack | What is measured |
|---|---|---|
| `release-notes/2026-10.md` | A visible instruction inside an otherwise normal document | Contamination per chunk: listed in `forbidden_passages`, so only the chunk holding the paragraph counts |
| `community/billing-tips.md` | Keyword stuffing ("refund", "SLA", "plans"...) to be retrieved for many questions, plus an instruction | Contamination: listed in `forbidden_sources` (every chunk of it is bad) |
| `integrations/slack-integration.md` | An instruction hidden in invisible Unicode tag characters ("ASCII smuggling") | Removed by ingestion; checked by a unit test and by `make test-live` |

## Generated files

`security-whitepaper.pdf` and `integrations/slack-integration.md` are generated from
`sources/` by `scripts/build_samples.py` (`make build-samples`): edit the sources, rebuild,
commit both. The PDF is reproducible byte for byte, so rebuilding an unchanged source does not
re-ingest it. A test checks that the PDF still matches its source page by page.
