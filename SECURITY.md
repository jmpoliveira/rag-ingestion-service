# Security policy

## Supported versions

This is a personal learning project. Only the latest release and the `main` branch receive
security fixes.

## Reporting a vulnerability

**Please do not open a public issue, pull request or discussion for security problems.**

Report it privately through GitHub's private vulnerability reporting:
[Report a vulnerability](https://github.com/jmpoliveira/rag-ingestion-service/security/advisories/new)
(also reachable from the **Security** tab of this repository).

Please include what the problem is and where, the steps or a minimal input to reproduce it
(for example a crafted file), what an attacker could do with it, and the version or commit
you tested. Do not include real personal data or secrets.

## What to expect

Responses are best effort: an acknowledgement within about one week, a fix or an explanation
as soon as is reasonable, and credit in the advisory if you want it. Please allow time for a
fix before disclosing publicly.

## Scope

In scope: the code and configuration in this repository (the ingestion pipeline, the folder
source, the parsers, the CLI, the Docker and CI files).

Out of scope: vulnerabilities in dependencies (pypdf, LangChain, the Chroma client...), which
belong upstream; the behaviour of Ollama and ChromaDB themselves.

Known, documented limitation: text that tries to instruct a model (prompt injection) is
stored as written. Hidden characters are removed, but plain-text instructions cannot be told
apart from content at ingestion time; the consumer must treat retrieved text as untrusted data.
A file that makes the parser exhaust memory or CPU despite the limits is a welcome report.
