set dotenv-load

@_:
    just --list

[group('qa')]
test *args:
    uv run -m pytest -q 

[group('qa')]
security *args:
    uv run python -m pip_audit --ignore-vuln CVE-2025-53000 --skip-editable 

[group('qa')]
lint *args:
    uv run ruff check --fix  

[group('qa')]
typing *args:
    uv run ty check 

[group('qa')]
check *args:
    just lint 
    just typing 


run:
    uv run python -m src.main

# Remove temporary files
[group('lifecycle')]
clean:
    rm -rf .venv .pytest_cache .ruff_cache .uv-cache
    find . -type d -name "*.egg-info" -exec rm -rf {} +
    find . -type d -name "__pycache__" -exec rm -r {} +

# Update dependencies
[group('lifecycle')]
update:
    uv sync --upgrade

# Ensure project virtualenv is up to date
[group('lifecycle')]
install:
    uv sync

# Install frontend npm dependencies
[group('frontend')]
frontend-install:
    npm --prefix frontend ci

# Build cases.db + per-case pages from the shared test fixtures into
# frontend/public/, so `frontend-dev`/`frontend-build` have a real, working
# sample corpus (no separate dev-only dataset to maintain).
[group('frontend')]
frontend-dev-data:
    uv run python -m src.indexing.build_index --markdown-dir tests/indexing/fixtures --db-path frontend/public/cases.db
    uv run python -m src.site.build_site --markdown-dir tests/indexing/fixtures --out-dir frontend/public/cases

# Run the frontend dev server against the fixture corpus
[group('frontend')]
frontend-dev: frontend-dev-data
    npm --prefix frontend run dev

# Run frontend unit tests (Vitest)
[group('frontend')]
frontend-test:
    npm --prefix frontend run test

# Type-check the frontend
[group('frontend')]
frontend-typecheck:
    npm --prefix frontend run typecheck

# Build the production frontend bundle (dist/ is the complete Pages artifact:
# Vite copies public/, including the generated cases.db and cases/ pages)
[group('frontend')]
frontend-build: frontend-dev-data
    npm --prefix frontend run build

# Run the weekly Constitutional Court ingestion pipeline.
#
# Required:
#   data_repo_path   local clone of the niels-tack/legal_decisions data repository
#
# Optional positional overrides (supply "" to keep defaults):
#   year             calendar year to discover (defaults to current year)
#
# Optional flags (append after positional args):
#   --push           commit + push new Markdown files to the data repo remote
#   --force          re-process slugs that already have a .md file (re-ingest mode)
#   --no-pdf-cache   re-download PDFs even if a .pdf is already cached locally
#   --delay-seconds N  seconds to wait between PDF downloads (default: 2.0)
#
# Examples:
#   just ingest /path/to/legal_decisions                        # current year, dry run
#   just ingest /path/to/legal_decisions 2026 --push            # push new files
#   just ingest /path/to/legal_decisions 2026 --force           # re-ingest all (use cached PDFs)
#   just ingest /path/to/legal_decisions 2025 --force --no-pdf-cache  # full re-download
[group('lifecycle')]
ingest data_repo_path year=`date +%Y` *args="":
    uv run python -m src.ingestion.pipeline \
        --data-repo-path "{{data_repo_path}}" \
        --year {{year}} \
        {{args}}

# Process the checked-in sample PDFs (reference/sample_decisions/CoC_pdf) into
# Markdown: real PDF extraction, no network access - see
# scripts/process_sample_pdfs.py for what's real vs. placeholder.
[group('frontend')]
process-samples:
    uv run python scripts/process_sample_pdfs.py --pdf-dir reference/sample_decisions/CoC_pdf --out-dir sample-data/markdown

# Build cases.db + per-case pages from the real sample-PDF corpus instead of
# the tiny test fixtures - a richer, more realistic local demo (11 real
# rulings, ~800 chunks) than `frontend-dev-data`. Overwrites whatever
# frontend/public/cases.db currently has; re-run `frontend-dev-data` to
# switch back to the fixture corpus.
[group('frontend')]
frontend-dev-data-samples: process-samples
    uv run python -m src.indexing.build_index --markdown-dir sample-data/markdown --db-path frontend/public/cases.db
    uv run python -m src.site.build_site --markdown-dir sample-data/markdown --out-dir frontend/public/cases

# Run the frontend dev server against the real sample-PDF corpus
[group('frontend')]
frontend-dev-samples: frontend-dev-data-samples
    npm --prefix frontend run dev

# --- Backend (Phase 2 query service) ---------------------------------------

# Build a local cases.db for the query service from the shared test fixtures
[group('backend')]
backend-dev-data:
    mkdir -p .dev-data
    uv run python -m src.indexing.build_index --markdown-dir tests/indexing/fixtures --db-path .dev-data/cases.db

# Run the Phase 2 query service locally (FastAPI/uvicorn) against that db.
# BM25-only (no embeddings) unless `add-embeddings` has been run first -
# hybrid_search's semantic branch checks for stored embeddings *before*
# calling the embedding function, so this never touches
# sentence-transformers (an optional extra, see pyproject.toml) as long as
# the db has none. If you've run `add-embeddings` against this same db,
# add `--extra embeddings` here too, or /search will crash on the now-real
# semantic branch.
[group('backend')]
backend-dev: backend-dev-data
    CASES_DB_PATH=.dev-data/cases.db ALLOWED_ORIGIN=http://localhost:5173 uv run uvicorn src.query_service.main:app --reload --port 8080

# Compute real embeddings for .dev-data/cases.db (downloads the
# sentence-transformers model on first run - needs network access, and
# `--extra embeddings` to install torch/sentence-transformers, which
# plain `uv run`/`just` commands don't pull in by default).
[group('backend')]
add-embeddings: backend-dev-data
    uv run --extra embeddings python -c "from pathlib import Path; from src.indexing.build_index import add_embeddings; n = add_embeddings(Path('.dev-data/cases.db')); print(f'Embedded {n} chunk(s).')"

# --- Both together (Phase 2 path: frontend calling the local backend) ------

# Run the query service and the frontend together, with the frontend's
# SearchProvider switched to RemoteApiProvider pointed at the local
# service - exercises the Phase 2 code path end to end, not just Phase 1's
# default LocalSqliteProvider. Ctrl-C stops both.
[group('frontend')]
fullstack-dev: backend-dev-data frontend-install
    #!/usr/bin/env sh
    set -e
    CASES_DB_PATH=.dev-data/cases.db ALLOWED_ORIGIN=http://localhost:5173 uv run uvicorn src.query_service.main:app --port 8080 &
    backend_pid=$!
    trap 'kill "$backend_pid" 2>/dev/null' EXIT
    VITE_SEARCH_BACKEND=remote VITE_QUERY_SERVICE_URL=http://localhost:8080 npm --prefix frontend run dev

