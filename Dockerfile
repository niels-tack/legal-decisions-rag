
FROM python:3.13-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-install-project

# Copy application code
COPY . .

# Install the project
RUN uv sync --frozen

EXPOSE 8080

# Run the query-service HTTP API, listening on the Scaleway-provided PORT.
CMD ["sh", "-c", "uv run uvicorn src.query_service.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
