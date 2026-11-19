# ADR 0002: Documents come from a folder today, from events tomorrow

Status: accepted

## Context

Today the documents to ingest are files in a folder. Later they will arrive as events: "a
file was uploaded to blob storage", "a page changed in the wiki", delivered by a message
broker (Azure Service Bus, Event Grid, Kafka, RabbitMQ). The two triggers are very different:

| | Folder (pull) | Events (push) |
|---|---|---|
| Who knows what changed | we do, by comparing the folder with the index | the producer tells us |
| Deletions | inferred: in the index, not in the folder | explicit `deleted` events |
| Delivery | one run sees everything | at least once: duplicates and reordering |
| Scaling | one job at a time | many workers, one message each |

What must not happen is a pipeline written for one trigger that has to be rewritten for the
other.

## Decision

1. **Split *where documents come from* from *what is done with one document*.**
   - `DocumentSource` port: `list_documents()` (id, media type, content hash, size) and
     `read_bytes(document)`. `FolderDocumentSource` implements it today.
   - `IngestDocument` use case: one document in, one result out. Every trigger calls it.
2. **Today's trigger is a command, run to completion**: `python main.py sync` (CLI in
   `src/interface/cli.py`), started by hand, by `make ingest`, by a scheduler (cron, a
   Kubernetes CronJob, an Azure Container Apps job) or as a one-shot container. Exit codes are
   the contract with the scheduler.
3. **The document id is the stable key.** For a folder it is the path relative to the folder
   (`policies/account-security.txt`). For events it will be the object key or URL. It keys the
   chunks in the index, so a re-delivered event replaces instead of duplicating (ADR 0003).
4. **Ids are untrusted input.** `read_bytes` re-checks that an id resolves inside the folder,
   because ids will one day come from messages written by someone else.
5. **The folder is defensive**: never created when missing (a fatal error instead), symlinks
   never followed, hidden files ignored, a size limit, and a file that changes between
   listing and reading is rejected and picked up by the next sync.

### The event-driven design this leaves room for

```
producer ──► broker topic ──► worker (src/interface/worker.py, new)
                                 │  per message: validate, then
                                 ├─ created / updated ──► IngestDocument(document, index)
                                 └─ deleted ────────────► index.delete(document_id)
                              failures after N attempts ──► dead-letter queue
```

- A new `BlobDocumentSource` implements `read_bytes` (and `list_documents` for a full
  reconciliation, which stays useful as a nightly safety net for lost events).
- The message carries the id and the content hash (or an ETag), so a stale message whose hash
  no longer matches is dropped instead of overwriting newer content.
- Concurrency: one worker per message; two messages for the same document are made safe by
  the versioning of ADR 0003 (the last complete version wins, older ones are deleted). A
  per-document lock or a partition key on the document id would make the order strict.
- Events are documented as CloudEvents, so the producer and the broker can change.

## Alternatives considered

- **Watch the folder (`watchdog`).** Reacts faster, but only works on one machine, misses
  changes while the process is down, and behaves differently on network shares. A periodic
  sync is simpler and catches up by construction.
- **Start with events now.** It needs a broker, a producer and dead-letter handling before a
  single document is indexed. The folder delivers value today, and the split above makes the
  later step additive.
- **Hash-free change detection (size + modification time).** Cheaper, but copies and restores
  change the time without changing the content, and some tools keep the time while changing
  the content. Hashing a few hundred MB per sync is acceptable; revisit for large corpora.

## Consequences

- Every sync reads and hashes every file to detect changes. Fine for thousands of documents;
  for more, keep a manifest of `(path, size, mtime) -> hash` and hash only what changed.
- An event worker reuses `IngestDocument` and the `VectorIndex` adapter unchanged; it adds an
  interface module, a source adapter and the broker client.
