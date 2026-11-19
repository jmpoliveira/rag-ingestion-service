.DEFAULT_GOAL := help

VENV   := .venv
BIN    := $(VENV)/bin
PYTHON := $(BIN)/python
IMAGE  := rag-ingestion-service:latest
# Collection used by the sample corpus and the retrieval evals (never your real one).
EVAL_COLLECTION ?= tessera-kb
COMPOSE     := docker compose
COMPOSE_ENV := docker compose -f docker-compose.yml -f docker-compose.docker-env.yml

.PHONY: help venv install ingest ingest-samples inspect inspect-samples reset reset-samples eval publish test cov lint format \
        typecheck check test-live docker-build up up-env clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ---------- Environment ----------
venv:  ## Create the virtual environment
	python3 -m venv $(VENV)

install: venv  ## Install the project with dev dependencies
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

# ---------- Run ----------
ingest:  ## Sync SOURCE_DIR into CHROMA_COLLECTION (incremental; from .env)
	$(PYTHON) main.py sync

# Environment variables override .env, so this never touches your real collection.
ingest-samples:  ## Sync samples/knowledge-base into EVAL_COLLECTION (for the evals)
	SOURCE_DIR=samples/knowledge-base CHROMA_COLLECTION=$(EVAL_COLLECTION) $(PYTHON) main.py sync

inspect:  ## Show CHROMA_COLLECTION (read-only); add DOC=<document id> to list its chunks
	$(PYTHON) main.py inspect $(if $(DOC),--document "$(DOC)")

inspect-samples:  ## Show EVAL_COLLECTION (read-only): make inspect-samples DOC=refund-policy.md
	CHROMA_COLLECTION=$(EVAL_COLLECTION) $(PYTHON) main.py inspect $(if $(DOC),--document "$(DOC)")

reset:  ## Drop CHROMA_COLLECTION: make reset CONFIRM=yes
	@test "$(CONFIRM)" = "yes" || (echo "Refusing: run 'make reset CONFIRM=yes'"; exit 2)
	$(PYTHON) main.py reset --yes

reset-samples:  ## Drop EVAL_COLLECTION (the samples): make reset-samples CONFIRM=yes
	@test "$(CONFIRM)" = "yes" || (echo "Refusing: run 'make reset-samples CONFIRM=yes'"; exit 2)
	CHROMA_COLLECTION=$(EVAL_COLLECTION) $(PYTHON) main.py reset --yes

# ---------- Evals (need Ollama and Chroma; see evals/README.md) ----------
eval:  ## Measure retrieval on EVAL_COLLECTION: make eval ARGS="--baseline <report>"
	$(PYTHON) -m evals run --collection $(EVAL_COLLECTION) $(ARGS)

publish:  ## Explore a saved report in Phoenix: make publish REPORT=<path>
	$(PYTHON) -m evals publish $(REPORT) $(ARGS)

# ---------- Quality ----------
test:  ## Run the test suite
	$(PYTHON) -m pytest

# Needs docker-env (llm + vector) and the embedding model pulled. Uses a temporary collection.
test-live:  ## Smoke test against the real Ollama and Chroma from .env
	$(PYTHON) -m pytest --live -m live -v

cov:  ## Run tests with a coverage report (fails under the configured minimum)
	$(PYTHON) -m pytest --cov

lint:  ## Lint and check formatting with ruff
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format:  ## Format and auto-fix with ruff
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

typecheck:  ## Static type checking with pyright (strict)
	$(BIN)/pyright --pythonpath $(PYTHON)

check: lint typecheck test  ## Run lint, typecheck and tests (use before a commit)

# ---------- Docker ----------
docker-build:  ## Build the Docker image
	docker build -t $(IMAGE) .

up:  ## One-shot sync in a container, with its own Ollama, Chroma and Jaeger
	$(COMPOSE) --profile standalone run --rm --build ingestion

up-env:  ## One-shot sync in a container on the shared docker-env network
	$(COMPOSE_ENV) run --rm --build ingestion

# ---------- Cleanup ----------
clean:  ## Remove caches and build artifacts
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) \
		-not -path "./$(VENV)/*" -prune -exec rm -rf {} +
	rm -rf build dist *.egg-info .coverage htmlcov
