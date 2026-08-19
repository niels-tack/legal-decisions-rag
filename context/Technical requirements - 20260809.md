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

**Web Framework**: A minimal ASGI framework (e.g. FastAPI) for the query service, which runs as a Scaleway Serverless Container - a Docker image exposing an HTTP server, built from the repo's existing `Dockerfile`.

**Database**: SQLite as a single portable `cases.db` artifact - an FTS5 virtual table for BM25 lexical search plus a vector-capable store (e.g. the `sqlite-vec` extension, or a bundled sidecar embeddings file) for semantic retrieval. No external managed database, to keep cost at €0 and avoid exposing the maintainer's hardware.

**Other Preferences**:
- Keep ingestion, index-build, and query-serving as separate, independently testable modules - avoid coupling the local pipeline to the query service.
- All secrets (shared API key, Scaleway credentials) live in environment variables / GitHub Secrets, never committed.
- Prefer composition over inheritance; no ORM needed given the single-file SQLite design.

## Existing systems

**APIs**: Microsoft Copilot Studio (Declarative Agent / OpenAPI Action), OpenAI Custom GPT Actions, and an MCP server for Claude Desktop / Cursor / VS Code Copilot - all consuming one shared hosted search API.

**Databases**: None external - a single SQLite file (`cases.db`) rebuilt by CI and hosted as a static object in Scaleway Object Storage.

**Services**:
- GitHub (public repo + Actions) for source Markdown, CI, index build, and container image build/push.
- Scaleway Object Storage (`fr-par`) for hosting the built `cases.db`.
- Scaleway Container Registry (`fr-par`, public visibility) for the query-service Docker image - comfortably within its free tier (75GB storage, free inbound bandwidth) for a single small image.
- Scaleway Serverless Containers (`fr-par`) for the query API, pulling the image from the registry above.

**Authentication**: No end-user authentication. The query API is protected by a single shared static key issued by the maintainer and embedded server-side in each client integration (OpenAPI connector config, MCP server environment) - never exposed to or entered by end users.

## Architecture ideas

**Data flow**:

1. **Local ingestion (offline, maintainer's own hardware, weekly, Dutch-language rulings only for the POC)**:
   - **Discover**: scrape the Court's official case overview listing for case number, docket number ("rolnummer"), date, procedure type, controlled norm, outcome, official keywords, and PDF URL per ruling.
   - **Extract**: convert each PDF to text with `pdfplumber`, preserving the ruling's section structure (numbered facts, `-A-` party arguments, `-B-` the Court's reasoning, operative ruling). Strip repeated header/footer boilerplate (e.g. the `ECLI:BE:GHCC:\d{4}:ARR\.\d+` line, page numbers) via pattern matching rather than coordinate-based cropping.
   - **Assemble**: merge the discovered metadata and extracted text into one Markdown file per ruling with YAML frontmatter. Capture every readily available field rather than a minimal set: the ECLI identifier (canonical citation), the official case number (e.g. `1/2025`), the role/docket number ("rolnummer", e.g. `8115`), and the file/URL slug (e.g. `2025-001n`) as three distinct fields - these are different identifiers and must not be collapsed into one ambiguous "case number" - plus ruling date, language, procedure type, controlled norm, outcome, and subject tags/keywords.

   This machine is never reachable from the public internet; it only pushes finished Markdown to GitHub over outbound git.
2. **CI index build (GitHub Actions, free runners)** - parses committed Markdown + frontmatter, builds a single `cases.db` containing an FTS5 table (BM25) and a vector store for hybrid retrieval, then uploads the artifact to Scaleway Object Storage. Triggered on push to `main` under the cases directory.
3. **Query serving (Scaleway Serverless Container, Paris)** - a small containerized HTTP service (FastAPI) built from the repo's `Dockerfile`; on cold start, downloads/caches `cases.db` into local storage; on each request, validates the shared static key, computes the query embedding, runs BM25 + vector similarity, merges/re-ranks, and returns JSON with case identifiers, date, title, excerpt, and language.
4. **Client layer** - (a) Microsoft Copilot Studio / Custom GPT calls the container's HTTP endpoint via an OpenAPI action with the shared key baked into the connector config; (b) an MCP server (hosted or thin local proxy) exposes the same search as an MCP tool for Claude Desktop / Cursor / VS Code, holding the shared key itself so end users never see it.

**Patterns to Consider**:
- One canonical `cases.db` artifact shared by both client integrations - do not fork retrieval logic between the Copilot and MCP paths.
- Idempotent, full-rebuild index generation in CI while the corpus is small; revisit incremental builds only if rebuild time becomes a problem.
- Keep the shared API key server-side only (connector config / MCP server env var), never distributed to end users.
- Chunk passages using the rulings' own section structure (facts / `-A-` arguments / `-B-` reasoning / operative ruling), not a fixed delimiter like blank lines or a fixed word count - case lengths vary enormously (roughly 700 to 340,000+ words across the sample corpus), so naive splitting produces wildly inconsistent, low-quality chunks.
- Manage all Scaleway infrastructure as code via Terraform, using the official `scaleway` provider: the Object Storage bucket, the container registry namespace, the container namespace + container (`scaleway_container_namespace` / `scaleway_container`), and IAM application/policy for scoped credentials - committed to the repo rather than configured by hand in the console.
- Build the query-service Docker image in CI and push it to the Scaleway Container Registry before `terraform apply` points the `scaleway_container` resource at the new image tag.

**Patterns to Avoid**:
- No self-hosting of the query API on the maintainer's own network/hardware.
- No requirement for end users to hold API keys, clone repos, or install a CLI.
- No per-query calls to paid external embedding APIs unless verified to stay within a free tier - prefer a small bundled/self-hosted embedding model inside the query service.
- No pulling the query-service image from external registries (Docker Hub, GHCR) for production - Scaleway advises against this for Serverless Containers due to uncontrolled external rate limits; use Scaleway Container Registry instead.

## Technical constraints

**Deployment Target**: Scaleway Serverless Containers (Docker image built from the repo's `Dockerfile`, `fr-par`) for the query API; Scaleway Container Registry (`fr-par`, public, free tier) hosting that image; Scaleway Object Storage (`fr-par`) for the `cases.db` artifact; GitHub Actions for CI (index build and image build/push); public GitHub repo for source Markdown. All Scaleway infrastructure is defined as code with Terraform (official `scaleway` provider), applied from CI or the maintainer's machine rather than clicked together manually.

**Scaling Requirements**:
- Expected users: unknown/low initially (awareness-driven); design should comfortably stay within Scaleway's free tier (1,000,000 requests/month, 400,000 GB-s compute, 75GB registry storage).
- Expected data volume: the Belgian Constitutional Court ruling archive (Markdown + frontmatter), likely low thousands of documents - to be confirmed once the ingestion pipeline is built.
- Peak load expectations: low and bursty, driven by ad hoc user questions rather than sustained traffic.

**Security Requirements**:
- Shared static API key required on every query request; rejected/malformed requests logged.
- No PII expected in ruling text, but frontmatter and content should be spot-checked before publishing.
- EU-only data residency (Scaleway Paris) for sovereignty/GDPR alignment.
- The maintainer's local ingestion hardware must remain fully unreachable from the public internet (outbound-only git push).

## Non-Functional Requirements

**Performance**:
- Response time: sub-1s for the search API call itself is the target; container cold starts are not user-perceptible given downstream LLM synthesis already takes 2-5s.
- Throughput: no sustained high-throughput requirement; must not exceed Scaleway free-tier limits under expected usage.

**Availability**:
- Uptime target: best-effort - personal/community project, no SLA.
- Acceptable downtime: yes, for maintenance windows or free-tier resets.

**Observability**:
- Logging: Scaleway container logs for request volume, key-rejection attempts, and errors - sufficient to spot abuse or breakage without paid monitoring.
- Monitoring: periodic manual check of Scaleway free-tier usage to avoid unexpected overage.
- Alerting: not required for MVP; revisit if traffic grows meaningfully.

## Team Context

**Team Size**: Solo maintainer.

**Skill Levels**: Senior/technical maintainer; end users are explicitly non-technical.

**Maintenance Plan**: Maintainer runs ingestion locally and pushes updates; GitHub Actions handles index build, image build/push, and deployment with no manual step beyond `git push`.

## Dependencies & Risks

**External Dependencies**:
- Scaleway (Serverless Containers + Container Registry + Object Storage, `fr-par`) - free-tier limits and future pricing policy are outside the maintainer's control.
- GitHub Actions free-tier runner minutes for CI index builds and Docker image build/push.
- Microsoft Copilot Studio / OpenAI Custom GPT Action platforms - third-party surfaces whose plugin/schema formats could change independently.
- `pdfplumber` for PDF text extraction in the ingestion pipeline.
- The Court's own website/case listing as the sole source of truth - its markup, overview page structure, and PDF URL pattern could change without notice, breaking the scraper.

**Known Risks**:
- Free-tier quota exhaustion or a Scaleway policy change could reintroduce hosting cost; the shared static key deters casual scraping but not a determined bad actor.
- Retrieval quality for Dutch legal terminology needs empirical validation; extending to French/German later will require its own tokenization/embedding validation, not an assumption that the Dutch setup generalizes.
- No text-quality QA workflow is defined yet for catching PDF-extraction errors before or after publishing.
- OpenAPI/Custom GPT and MCP integration formats are external platforms the maintainer doesn't control and could change independently.
- Terraform state for the Scaleway infrastructure needs a durable, non-local home (e.g. a private Scaleway Object Storage bucket as an S3-compatible backend) - losing local state on a solo maintainer's machine would leave the deployed infrastructure unmanaged.
- Container cold starts are typically slower than lightweight zip-based functions (image pull + start vs. a runtime invoke); acceptable given downstream LLM synthesis latency, but worth confirming empirically once deployed.

## Open Technical Questions

- How is the query-time embedding computed inside the query service at €0 cost - a small bundled model (e.g. an ONNX MiniLM-class model) versus a free-tier embedding API?
- What vector storage/index approach fits a single-file SQLite artifact (e.g. the `sqlite-vec` extension vs. a separate numpy/parquet sidecar) at the expected corpus size?
- Should the MCP integration be a remotely hosted MCP endpoint (once clients broadly support remote MCP over HTTP), or a minimal local stdio proxy users add to their MCP config?
- What triggers a re-ingestion of a case that's already been published if a text-quality or metadata bug is found after the fact - manual reprocessing only, or an automated re-check?
- Is a full rebuild of `cases.db` on every push acceptable indefinitely, or does incremental indexing become necessary past a certain corpus size?
- Where should Terraform state for the Scaleway resources live, and how are Scaleway API credentials supplied when Terraform runs from CI vs. the maintainer's machine?
- When French/German coverage is picked up later, does the `n`-suffix PDF naming pattern (`{year}-{sequence}n.pdf`) extend to `f`/`d`-suffixed siblings at the same host?
