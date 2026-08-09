# Technical requirements: legal-decisions-rag

> **Single source of truth for technical architecture and constraints**
>
> This document defines how the project should be built. Update this as technical decisions are made.
> AI coding assistants will reference this to ensure code follows the right patterns and constraints.

## Technical preferences

**Language**: Python 3.13

**Package Manager**: uv

**Code Quality**:
- Linting: Ruff
- Type Checking: Ty
- Testing: pytest

## Engineering context

**Web Framework**: None required for the serverless query function (single-purpose HTTP handler on Scaleway's Python runtime). Introduce FastAPI only if it materially helps local development/testing of the handler.

**Database**: SQLite as a single portable `cases.db` artifact - an FTS5 virtual table for BM25 lexical search plus a vector-capable store (e.g. the `sqlite-vec` extension, or a bundled sidecar embeddings file) for semantic retrieval. No external managed database, to keep cost at €0 and avoid exposing the maintainer's hardware.

**Other Preferences**:
- Keep ingestion, index-build, and query-serving as separate, independently testable modules - avoid coupling the local pipeline to the serverless handler.
- All secrets (shared API key, Scaleway credentials) live in environment variables / GitHub Secrets, never committed.
- Prefer composition over inheritance; no ORM needed given the single-file SQLite design.

## Existing systems

**APIs**: Microsoft Copilot Studio (Declarative Agent / OpenAPI Action), OpenAI Custom GPT Actions, and an MCP server for Claude Desktop / Cursor / VS Code Copilot - all consuming one shared hosted search API.

**Databases**: None external - a single SQLite file (`cases.db`) rebuilt by CI and hosted as a static object in Scaleway Object Storage.

**Services**:
- GitHub (public repo + Actions) for source Markdown, CI, and index build.
- Scaleway Object Storage (`fr-par`) for hosting the built `cases.db`.
- Scaleway Serverless Functions (Python, `fr-par`) for the query API.

**Authentication**: No end-user authentication. The query API is protected by a single shared static key issued by the maintainer and embedded server-side in each client integration (OpenAPI connector config, MCP server environment) - never exposed to or entered by end users.

## Architecture ideas

**Data flow**:

1. **Local ingestion (offline, maintainer's own hardware)** - PDF to Markdown conversion using a legal-aware parser (e.g. `docling` or `marker`), preserving citations, paragraph numbering, and structure. YAML frontmatter captures case number, ruling date, language, title, subject tags, and articles referenced. This machine is never reachable from the public internet; it only pushes finished Markdown to GitHub over outbound git.
2. **CI index build (GitHub Actions, free runners)** - parses committed Markdown + frontmatter, builds a single `cases.db` containing an FTS5 table (BM25) and a vector store for hybrid retrieval, then uploads the artifact to Scaleway Object Storage. Triggered on push to `main` under the cases directory.
3. **Query serving (Scaleway Serverless Functions, Python, Paris)** - on cold start, downloads/caches `cases.db` into `/tmp`; on each request, validates the shared static key, computes the query embedding, runs BM25 + vector similarity, merges/re-ranks, and returns JSON with case number, date, title, excerpt, and language.
4. **Client layer** - (a) Microsoft Copilot Studio / Custom GPT calls the function via an OpenAPI action with the shared key baked into the connector config; (b) an MCP server (hosted or thin local proxy) exposes the same search as an MCP tool for Claude Desktop / Cursor / VS Code, holding the shared key itself so end users never see it.

**Patterns to Consider**:
- One canonical `cases.db` artifact shared by both client integrations - do not fork retrieval logic between the Copilot and MCP paths.
- Idempotent, full-rebuild index generation in CI while the corpus is small; revisit incremental builds only if rebuild time becomes a problem.
- Keep the shared API key server-side only (connector config / MCP server env var), never distributed to end users.

**Patterns to Avoid**:
- No self-hosting of the query API on the maintainer's own network/hardware.
- No requirement for end users to hold API keys, clone repos, or install a CLI.
- No per-query calls to paid external embedding APIs unless verified to stay within a free tier - prefer a small bundled/self-hosted embedding model inside the serverless function.

## Technical constraints

**Deployment Target**: Scaleway Serverless Functions (Python 3.11+ runtime, `fr-par`) for the query API; Scaleway Object Storage (`fr-par`) for the `cases.db` artifact; GitHub Actions for CI/index build; public GitHub repo for source Markdown.

**Scaling Requirements**:
- Expected users: unknown/low initially (awareness-driven); design should comfortably stay within Scaleway's free tier (1,000,000 requests/month, 400,000 GB-s compute).
- Expected data volume: the Belgian Constitutional Court ruling archive (Markdown + frontmatter), likely low thousands of documents - to be confirmed once the ingestion pipeline is built.
- Peak load expectations: low and bursty, driven by ad hoc user questions rather than sustained traffic.

**Security Requirements**:
- Shared static API key required on every query request; rejected/malformed requests logged.
- No PII expected in ruling text, but frontmatter and content should be spot-checked before publishing.
- EU-only data residency (Scaleway Paris) for sovereignty/GDPR alignment.
- The maintainer's local ingestion hardware must remain fully unreachable from the public internet (outbound-only git push).

## Non-Functional Requirements

**Performance**:
- Response time: sub-1s for the search API call itself is the target; cold starts (~300-500ms) are not user-perceptible given downstream LLM synthesis already takes 2-5s.
- Throughput: no sustained high-throughput requirement; must not exceed Scaleway free-tier limits under expected usage.

**Availability**:
- Uptime target: best-effort - personal/community project, no SLA.
- Acceptable downtime: yes, for maintenance windows or free-tier resets.

**Observability**:
- Logging: Scaleway function logs for request volume, key-rejection attempts, and errors - sufficient to spot abuse or breakage without paid monitoring.
- Monitoring: periodic manual check of Scaleway free-tier usage to avoid unexpected overage.
- Alerting: not required for MVP; revisit if traffic grows meaningfully.

## Team Context

**Team Size**: Solo maintainer.

**Skill Levels**: Senior/technical maintainer; end users are explicitly non-technical.

**Maintenance Plan**: Maintainer runs ingestion locally and pushes updates; GitHub Actions handles index build and deployment with no manual step beyond `git push`.

## Dependencies & Risks

**External Dependencies**:
- Scaleway (Serverless Functions + Object Storage, `fr-par`) - free-tier limits and future pricing policy are outside the maintainer's control.
- GitHub Actions free-tier runner minutes for CI index builds.
- Microsoft Copilot Studio / OpenAI Custom GPT Action platforms - third-party surfaces whose plugin/schema formats could change independently.
- A legal-aware PDF parser (`docling` or `marker`) for the ingestion pipeline.

**Known Risks**:
- Free-tier quota exhaustion or a Scaleway policy change could reintroduce hosting cost; the shared static key deters casual scraping but not a determined bad actor.
- Naive tokenization/embedding choices may underperform on Dutch/French/German legal text; retrieval quality needs empirical validation, not just assumption.
- PDF-to-Markdown conversion errors (OCR/structure loss) could misrepresent legal text; no correction/versioning workflow is defined yet.
- OpenAPI/Custom GPT and MCP integration formats are external platforms the maintainer doesn't control and could change independently.

## Open Technical Questions

- How is the query-time embedding computed inside the Scaleway function at €0 cost - a small bundled model (e.g. an ONNX MiniLM-class model) versus a free-tier embedding API?
- What vector storage/index approach fits a single-file SQLite artifact (e.g. the `sqlite-vec` extension vs. a separate numpy/parquet sidecar) at the expected corpus size?
- Should the MCP integration be a remotely hosted MCP endpoint (once clients broadly support remote MCP over HTTP), or a minimal local stdio proxy users add to their MCP config?
- What cadence and trigger should ongoing ingestion use on the maintainer's own hardware, and how does that push flow interact with the GitHub Actions rebuild?
- Is a full rebuild of `cases.db` on every push acceptable indefinitely, or does incremental indexing become necessary past a certain corpus size?
