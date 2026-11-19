# Sample knowledge base

`knowledge-base/` holds fictional help-centre articles for **Tessera Support Cloud**, an
invented ticketing product. The companion [mcp-server](https://github.com/jmpoliveira/mcp-server)
serves mock customers (Acme Corp, Globex, Initech) who use it, so the agent can later combine
their tickets with these articles.

Everything here is invented, so the repository can be public and the evals reproducible. The
retrieval evals (`evals/datasets/knowledge_base.toml`) are written against these files:
changing one means reviewing the cases and bumping the dataset version.

```bash
make ingest-samples   # ingests this folder into its own collection (EVAL_COLLECTION, default tessera-kb)
make eval             # measures retrieval on that collection
```

The formats are mixed on purpose: Markdown, plain text, and a subfolder (document ids are
paths relative to the source folder, for example `policies/account-security.txt`).
