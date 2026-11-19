# ADR 0006: Traces through the docker-env collector to Jaeger and Phoenix

Status: accepted

## Context

An ingestion run is a batch of many small steps (read, parse, chunk, embed, write) per
document, where the expensive one is usually not obvious: on a laptop CPU, embeddings
dominate; with a remote vector store, writes can. The old service exported spans over gRPC to
a hard-coded `localhost:4317` (Jaeger directly), wrote rotating log files itself, and had no
way to tell which document a slow span belonged to.

docker-env provides an OpenTelemetry Collector as the single OTLP entry point, fanning out to
Jaeger (traces) and Phoenix (LLM traces and evals). Its service contract asks consumers to
send to the collector and to use the standard `OTEL_*` variable names.

## Decision

1. **OTLP over HTTP to the collector**, configured with the standard names
   `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME`, plus `OTEL_ENABLED` (off by
   default, so tests and a quick local run need nothing). The service never knows Jaeger or
   Phoenix. (`ai-agent-service` uses the older `OTEL_EXPORTER_ENDPOINT` name; aligning it is a
   small follow-up there.)
2. **One trace per sync** (`ingest sync`), one child per document (`ingest document`, with id,
   media type, size, outcome and chunk count), and children per stage: `read`, `parse`,
   `chunk`, `embeddings <model>`, `upsert <collection>`, `delete <collection>`.
3. **Semantic conventions where they exist**: embedding spans follow the GenAI conventions
   (`gen_ai.operation.name = embeddings`, provider, model, `gen_ai.embeddings.dimension.count`),
   so Phoenix shows them as embedding calls; index writes use the database conventions
   (`db.operation.name`, `db.collection.name`, `db.operation.batch.size`). Names live only in
   `src/application/telemetry.py`, because both conventions are still in development.
4. **No document text in spans or logs**: ids, counts, sizes and outcomes only. Documents can
   hold personal data, and traces are kept and shared more loosely than the documents.
5. **Logs as in the agent**: standard `logging`, profiles in `config/logging.json` selected by
   `APP_ENV` (readable lines in development, JSON lines in production), every line with
   `trace_id` and `span_id`, stdout only, secrets redacted by exact key name.
6. **Flush before exit.** The exporter is batched; `main.py` calls the provider's shutdown in a
   `finally`, otherwise the last spans of a one-shot job are lost.
7. **The CLI prints the sync's trace id**, to jump from a run to its trace.

## Alternatives considered

- **Exporting to Jaeger directly** (the old service). Couples the service to one backend and
  duplicates what the collector does; Phoenix would need a second exporter.
- **Auto-instrumentation** (`opentelemetry-instrument`, the httpx instrumentation). Gives HTTP
  spans for free but no ingestion semantics (which document, which stage, how many chunks);
  can be added on top later.
- **Metrics now** (documents per outcome, chunks, embedding latency histograms). Useful for a
  dashboard and alerts once ingestion runs on a schedule; the per-run report and the spans
  cover the current use. Planned with the agent's observability step.

## Consequences

- With docker-env running and `OTEL_ENABLED=true`, a sync is visible in Jaeger
  (`rag-ingestion-service`) and its embedding spans in Phoenix. Not verified end to end yet:
  the export path is the agent's, which was verified; this service's spans were checked with
  an in-memory exporter in the tests.
- A trace of a large sync has thousands of spans. If that becomes a problem: one trace per
  document with a link to the sync, or sampling.
