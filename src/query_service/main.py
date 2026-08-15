"""FastAPI application for the hosted hybrid-search query service.

Deployed as a Scaleway Serverless Container: on startup it fetches the
prebuilt ``cases.db`` artifact (if not already present) and keeps a single
SQLite connection open for the container's lifetime, then serves
``GET /search`` requests. Per the technical requirements the API is keyless
(no end-user or shared client key of any kind); abuse protection instead
comes from origin-locked CORS (below), per-IP rate limiting
(``src.query_service.rate_limit``), and a response-size cap on excerpts
(``src.query_service.search``).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from src.indexing.embeddings import embed_texts
from src.query_service.rate_limit import rate_limit
from src.query_service.search import hybrid_search
from src.schemas import SearchResponse

# The deployed website's origin - the only one the keyless API's CORS
# policy allows to call it from a browser. Empty by default so an
# unconfigured deployment fails closed (no origin allowed) rather than
# silently permitting every site to call the API.
ALLOWED_ORIGIN_ENV_VAR = "ALLOWED_ORIGIN"

CASES_DB_PATH_ENV_VAR = "CASES_DB_PATH"
CASES_DB_URL_ENV_VAR = "CASES_DB_URL"
DEFAULT_CASES_DB_PATH = "/tmp/cases.db"
CASES_DB_OBJECT_KEY = "cases.db"

# Set by Terraform (infra/terraform/main.tf) on the deployed container: the
# bucket holding cases.db is private, so the app authenticates to it with
# its own narrowly-scoped IAM credentials rather than a public URL - a
# public bucket would let anyone scrape the whole corpus directly, bypassing
# the API's rate limiting and response-size caps entirely.
CASES_BUCKET_NAME_ENV_VAR = "CASES_BUCKET_NAME"
CASES_BUCKET_REGION_ENV_VAR = "CASES_BUCKET_REGION"
CASES_BUCKET_ENDPOINT_ENV_VAR = "CASES_BUCKET_ENDPOINT"
CASES_BUCKET_ACCESS_KEY_ENV_VAR = "CASES_BUCKET_ACCESS_KEY"
CASES_BUCKET_SECRET_KEY_ENV_VAR = "CASES_BUCKET_SECRET_KEY"

MIN_LIMIT = 1
MAX_LIMIT = 20
DEFAULT_LIMIT = 5

# Module-level singleton: FastAPI needs the actual Query() instance as the
# parameter default (that's how it recognizes a query param and its
# metadata), but ruff's B008 flags a `list`-annotated parameter's default
# being a function call - defining it once here instead satisfies both.
_SOURCES_QUERY_DEFAULT = Query(
    default=None,
    description=(
        "Restrict results to these judicial-body keys (e.g. 'GHCC'), "
        "repeatable (?sources=GHCC&sources=...). Omit to search every "
        "registered body."
    ),
)


def _download_from_private_bucket(db_path: Path) -> bool:
    """Fetch ``cases.db`` from the private Scaleway bucket via boto3, if configured.

    Args:
        db_path: Local path to write the downloaded database to.

    Returns:
        True if ``CASES_BUCKET_NAME`` was set and the download was
        attempted (raising on failure), False if that env var is absent so
        the caller can fall back to a different download method.
    """
    bucket_name = os.environ.get(CASES_BUCKET_NAME_ENV_VAR)
    if not bucket_name:
        return False

    import boto3

    client = boto3.client(
        "s3",
        region_name=os.environ.get(CASES_BUCKET_REGION_ENV_VAR),
        endpoint_url=os.environ.get(CASES_BUCKET_ENDPOINT_ENV_VAR),
        aws_access_key_id=os.environ.get(CASES_BUCKET_ACCESS_KEY_ENV_VAR),
        aws_secret_access_key=os.environ.get(CASES_BUCKET_SECRET_KEY_ENV_VAR),
    )
    client.download_file(bucket_name, CASES_DB_OBJECT_KEY, str(db_path))
    return True


async def _ensure_cases_db(db_path: Path) -> None:
    """Download the ``cases.db`` artifact if it isn't already on disk.

    Tries the private-bucket path first (the production configuration set
    by Terraform); falls back to a plain ``CASES_DB_URL`` HTTP(S) GET for
    local development against a simpler, unauthenticated source.

    Args:
        db_path: Local path the database should live at.

    Raises:
        httpx.HTTPStatusError: If ``CASES_DB_URL`` is used but the download
            fails.
        botocore.exceptions.ClientError: If the private-bucket download is
            used but fails (e.g. bad credentials, missing object).
    """
    if db_path.exists():
        return

    db_path.parent.mkdir(parents=True, exist_ok=True)

    if _download_from_private_bucket(db_path):
        return

    db_url = os.environ.get(CASES_DB_URL_ENV_VAR)
    if not db_url:
        return
    async with httpx.AsyncClient() as client:
        response = await client.get(db_url, follow_redirects=True)
        response.raise_for_status()
    db_path.write_bytes(response.content)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open (downloading if needed) the shared SQLite connection for the app.

    Uses FastAPI's lifespan context rather than a module-level global so the
    connection is created once per running app instance - important for
    tests, which construct the app fresh against a temporary database.

    Args:
        app: The FastAPI application instance.
    """
    db_path = Path(os.environ.get(CASES_DB_PATH_ENV_VAR, DEFAULT_CASES_DB_PATH))
    await _ensure_cases_db(db_path)

    # check_same_thread=False: FastAPI runs sync path-operation functions
    # (like `search` below) in a worker thread pool, so the single
    # connection opened here on the event-loop thread must be usable from
    # those worker threads too. Safe here because requests are served one
    # at a time in practice at this project's expected traffic; revisit
    # with a per-request connection or a lock if concurrency grows.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    app.state.db_conn = conn
    try:
        yield
    finally:
        conn.close()


app = FastAPI(title="legal-decisions-rag query service", lifespan=lifespan)

# Origin-locked CORS: the only client is the static website, called directly
# from the user's browser (there is no other server-side client to exempt,
# now that the shared-key-holding integrations have moved to v2/). An unset
# ALLOWED_ORIGIN means the allow-list is empty, so no browser origin can
# call this API until a deployment explicitly configures its site's origin.
_allowed_origin = os.environ.get(ALLOWED_ORIGIN_ENV_VAR)
app.add_middleware(
    CORSMiddleware,  # ty: ignore[invalid-argument-type]
    allow_origins=[_allowed_origin] if _allowed_origin else [],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_db_connection(request: Request) -> sqlite3.Connection:
    """Return the app's shared SQLite connection.

    Args:
        request: The current request, used to reach ``app.state``.

    Returns:
        The connection opened at startup by ``lifespan``.
    """
    return request.app.state.db_conn


def get_embed_fn() -> Callable[[list[str]], np.ndarray]:
    """Return the callable used to embed query text.

    A plain function (rather than a direct import in the endpoint body) so
    tests can swap in a lightweight fake via
    ``app.dependency_overrides[get_embed_fn]`` instead of loading the real
    sentence-transformers model.

    Returns:
        ``src.indexing.embeddings.embed_texts`` by default.
    """
    return embed_texts


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check, exempt from rate limiting.

    Returns:
        A static ``{"status": "ok"}`` payload.
    """
    return {"status": "ok"}


@app.get(
    "/search",
    response_model=SearchResponse,
    dependencies=[Depends(rate_limit)],
)
def search(
    conn: Annotated[sqlite3.Connection, Depends(get_db_connection)],
    embed_fn: Annotated[Callable[[list[str]], np.ndarray], Depends(get_embed_fn)],
    q: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=MIN_LIMIT, le=MAX_LIMIT),
    sources: list[str] | None = _SOURCES_QUERY_DEFAULT,
) -> SearchResponse:
    """Run hybrid search and return cited passages for a plain-text query.

    Args:
        q: The user's search text. Required and must be non-blank.
        limit: Maximum number of results to return (1-20).
        sources: Optional judicial-body keys to restrict results to.
        conn: The shared SQLite connection (injected).
        embed_fn: The query-embedding callable (injected).

    Returns:
        The query echoed back alongside its ranked, cited results.

    Raises:
        HTTPException: With status 400 if ``q`` is missing or blank.
    """
    if q is None or not q.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query parameter 'q' is required and must not be blank.",
        )
    results = hybrid_search(conn, q, embed_fn, limit=limit, sources=sources)
    return SearchResponse(query=q, results=results)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
