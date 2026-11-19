# ADR 0003: Idempotent, incremental ingestion with versioned chunks

Status: accepted

## Context

The old service deleted the collection and re-embedded every document on every run. Besides
the cost, the index was empty for the whole run, and empty for good if the run failed. Event
delivery (ADR 0002) adds another requirement: the same message can arrive twice, and a worker
can die halfway through writing a document.

We want: unchanged documents skipped, changed documents replaced, deleted documents removed,
re-runs harmless, and no moment where a document is missing from search results.

## Decision

1. **A document version identifies the content and the pipeline**:
   `version = sha256(content_hash | pipeline_fingerprint)[:16]`, where the pipeline
   fingerprint covers the chunker settings and the text-cleaning version. Same bytes + same
   pipeline = same version = skip. Changing `CHUNK_SIZE` re-ingests every document on the next
   sync, with no manual step. (The embedding model is not in it: it is fixed per collection by
   the index contract, ADR 0004.)
2. **Deterministic chunk ids**: `sha256(document_id)[:16] : version : chunk_index`. Writing the
   same version twice upserts the same ids: no duplicates.
3. **Write new, then delete old**:
   1. upsert chunks `1..n` of the new version;
   2. upsert chunk `0` last: it is the **completion marker**;
   3. delete the document's chunks whose `version` is not the new one.

   A version is listed as present only when its marker exists. If the process dies before
   step 2, the next attempt does not see a complete version and writes it again (step 3 then
   removes the partial leftovers). If it dies before step 3, two complete versions exist; the
   next attempt sees "not exactly one version" and ingests the document again, which ends
   with the clean-up. During the window,
   a search may return chunks of both versions, never of none.
4. **Reconciliation for the folder trigger** (`SyncSource`): documents in the index but no
   longer in the folder are deleted, **except when the folder is empty**: an empty folder
   usually means a wrong path or an unmounted volume, and the reaction to a configuration
   mistake must not be wiping the index. `DELETE_MISSING=false` disables deletions entirely.
   Clearing the index on purpose is a separate command (`reset --yes`).
5. **Failures keep the previous version.** A document that now fails to parse or embed is
   reported as failed and its last good version stays searchable (stale beats missing); the
   next sync retries it. A document whose new content has no text (a scanned PDF) is reported
   as `empty` and its old chunks are removed, because they describe content that is gone.

## Alternatives considered

- **Drop and rebuild (the old behaviour).** Simple and always consistent at the end, but the
  index is unusable during the run and lost on failure, and every run pays for every embedding.
- **Blue/green collections** (build `kb-v2`, then switch an alias). Gives atomic switches and
  is the right tool for a *model change* (ADR 0004), but rebuilding everything for one changed
  file is the same cost problem. Chroma has no aliases; the retriever would need to be told.
- **A separate record manager** (LangChain indexing API, or a table in Postgres). Keeps
  hashes outside the vector store and avoids metadata queries; costs a second store that must
  stay consistent with the first. Worth it when the index has millions of chunks.
- **Delete first, then write.** Simpler, but the document is missing from search between the
  two steps, and missing for good if the write fails.

## Consequences

- Re-running a sync is free when nothing changed (one metadata query per document, no
  parsing, no embeddings). The end-to-end check against a real Chroma 1.5.9: the second sync
  over the sample corpus did nothing; a changed file was replaced; a deleted file was removed;
  a new chunk size re-ingested everything and left exactly one version per document.
- Listing complete versions is a `get` on marker chunks (`chunk_index == 0`), paged. It grows
  with the number of documents, not chunks.
- Orphan chunks of a document that disappears from the source *before* its marker was ever
  written are not listed and so not deleted. Rare (a crash during the first ingestion of a
  file that is then deleted); a periodic consistency check or a reset fixes it.
