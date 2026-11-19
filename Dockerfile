# syntax=docker/dockerfile:1

# ---------- Stage 1: build the virtual environment ----------
FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# README.md and LICENSE are referenced by pyproject.toml
COPY pyproject.toml README.md LICENSE ./
COPY config ./config
COPY src ./src

RUN pip install .

# ---------- Stage 2: runtime ----------
FROM python:3.13-slim AS runtime

# A one-shot batch job: it syncs the folder mounted at /data and exits with the CLI's exit
# code (0 ok, 1 some documents failed, 2 bad settings, 3 a dependency is down). Everything
# else comes from the environment; no .env file is baked into the image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    SOURCE_DIR=/data

RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY main.py ./

USER appuser

# The application writes only to stdout, so the filesystem can stay read-only.
ENTRYPOINT ["python", "main.py"]
CMD ["sync"]
