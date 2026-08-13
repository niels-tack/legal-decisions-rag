# Technical requirements: legal-decisions-rag

> **Single source of truth for technical architecture and constraints**
>
> This document defines how the project should be built. Update this as technical decisions are made.
> AI coding assistants will reference this to ensure code follows the right patterns and constraints.

## Technical preferences

**Language**: Python 3.13 for ingestion and index build. Plain TypeScript/JavaScript for the static frontend - no heavy framework; prefer a zero- or minimal-build setup (e.g. Vite at most).

**Package Manager**: uv (Python); npm only if the frontend needs a build step.

**Code Quality**:
- Linting: Ruff
- Type Checking: Ty
- Testing: pytest for ingestion and index build; a small set of frontend tests asserting the search contract (given a fixture `cases.db`, known queries return expected passages and citation fields).

## Phasing model

Two phases share one data pipeline and one index artifact. Phase 2 is committed, near-term scope; every Phase 1 decision is evaluated against "does this make Phase 2 harder?".

- **Phase 1**: GitHub Pages hosts the static site and `cases.db`. Search runs fully client-side: SQLite compiled to WebAssembly reads the database over HTTP range requests and executes FTS5 (BM25) queries in the browser.
- **Phase 2**: a Scaleway Serverless Container (FastAPI) serves hybrid BM25 + vector retrieval from the same `cases.db`, now extended with embeddings. The frontend switches backend via a config flag; the local path is kept as fallback.
- **V2 (out of scope)**: MCP server, Custom GPT, shared-key auth for machine clients.

## Engineering context

**Web Framework**: None in Phase 1 - the site is static files. In Phase 2, a minimal ASGI framework (FastAPI) for the query service, running as a Scaleway Serverless Container built from the repo's `Dockerfile`.

**Frontend search runtime**: SQLite-in-the-browser over HTTP range requests, using `sql.js-httpvfs` or `wa-sqlite` with a range-request VFS. Evaluate both at project start and record the choice plus rationale here; `sql.js-httpvfs` is the proven reference implementation but is in maintenance mode, `wa-sqlite` is more actively maintained. Wrap whichever is chosen behind the frontend's own `SearchProvider` interface so the dependency is replaceable.

**Database**: SQLite as a single portable `cases.db` artifact - the one canonical index for both phases:
- `cases` table: one row per ruling with all frontmatter metadata (ECLI, arrest number, rolnummer, slug, date, language, procedure type, controlled norm, outcome, tags, source PDF URL).
- `chunks` table: one row per structure-aware passage (see chunking pattern below), keyed to its case, with section label and order.
- FTS5 virtual table over `chunks` for BM25 (contentless or external-content mode referencing `chunks`, to avoid storing text twice).
- Phase 2 adds embeddings over the same `chunks` rows: an `embeddings` table or `sqlite-vec` virtual table keyed by chunk id. Reserve the naming now; do not redesign the schema later.
- Full ruling text for the per-case pages is pre-rendered into static HTML at build time, not fetched from `cases.db` at runtime, so browser queries touch only small index/metadata pages.

**Range-request tuning (Phase 1 critical)**: build `cases.db` with a small page size (1024 bytes, the documented sweet spot for HTTP VFS access), run `VACUUM` and `ANALYZE` after build, and keep hot-path rows small. Verify in CI that a representative query completes within a bounded number of range requests / bytes transferred, so index bloat is caught before deploy.

**Other Preferences**:
- Keep ingestion, index-build, and frontend/query-serving as separate, independently testable modules - the local pipeline must not couple to how search is served.
- Define the search result contract once (JSON shape: chunk text, ECLI, arrest number, date, outcome, section label, PDF URL, score) and use it identically for the Phase 1 client-side path and the Phase 2 API. This contract is what makes the backend swap invisible to the UI.
- No secrets exist in Phase 1 at all. Phase 2 secrets (Scaleway credentials) live in GitHub Secrets, never committed. There is no shared API key in either phase - the browser is the only client, and a key shipped to a browser is public by definition.
- Prefer composition over inheritance; no ORM needed given the single-file SQLite design.

## Existing systems

**APIs**: None consumed in Phase 1. Phase 2 adds the project's own query API. Assistant integration is by handoff only: a composed prompt via clipboard, plus URL prompt-prefill deep links (e.g. ChatGPT's `?q=` parameter and equivalents) where available. Deep links must degrade gracefully - URL length limits (~2,000 characters to be safe) mean the clipboard route is the primary mechanism and deep links carry only short prompts or a pointer back to the site.

**Databases**: None external - a single SQLite file (`cases.db`) rebuilt by CI. Phase 1: hosted as a static file on GitHub Pages alongside the site. Phase 2: additionally uploaded to Scaleway Object Storage (`fr-par`) for the query service.

**Services**:
- GitHub (public repo + Actions + Pages) for source Markdown, CI, index build, and static hosting. This is the entire Phase 1 footprint.
- Phase 2 adds: Scaleway Object Storage (`fr-par`) for the built `cases.db`; Scaleway Container Registry (`fr-par`, public, free tier) for the query-service image; Scaleway Serverless Containers (`fr-par`) for the query API.

**Authentication**: No end-user authentication in any phase. Phase 1 needs no abuse protection beyond GitHub Pages' own limits. Phase 2 protects the keyless public API with per-IP rate limiting (in-process token bucket is sufficient at this scale), CORS locked to the site's origin, response-size caps, and logging of rejected requests.

## Architecture ideas

**Data flow**:

1. **Local ingestion (offline, maintainer's own hardware, weekly, Dutch-language rulings only for the POC)**:
   - **Discover**: scrape the Court's official case overview listing for case number, role number ("rolnummer"), date, procedure type, controlled norm, outcome, official keywords, and PDF URL per ruling.
   - **Extract**: convert each PDF to text with `pdfplumber`, preserving the ruling's section structure (numbered facts, `-A-` party arguments, `-B-` the Court's reasoning, operative ruling). Strip repeated header/footer boilerplate (e.g. the `ECLI:BE:GHCC:\d{4}:ARR\.\d+` line, page numbers) via pattern matching rather than coordinate-based cropping.
   - **Assemble**: merge the discovered metadata and extracted text into one Markdown file per ruling with YAML frontmatter. Capture every readily available field rather than a minimal set: the ECLI identifier (canonical citation), the official arrest number (e.g. `1/2025`), the role/docket number ("rolnummer", e.g. `8115`), and the file/URL slug (e.g. `2025-001n`) as three distinct fields - these are different identifiers and must not be collapsed into one ambiguous "case number" - plus ruling date, language, procedure type, controlled norm, outcome, and subject tags/keywords.

   This machine is never reachable from the public internet; it only pushes finished Markdown to GitHub over outbound git.
2. **CI build (GitHub Actions, free runners)** - on push to `main` under the cases directory: parse committed Markdown + frontmatter; chunk by ruling structure; build `cases.db` (metadata + chunks + FTS5, tuned for range access); render the static site (search page, per-case HTML pages); deploy site + database to GitHub Pages via the Pages artifact workflow. In Phase 2 the same job additionally computes embeddings for chunks (small multilingual model suitable for Dutch legal text, e.g. an ONNX MiniLM/E5-class model, run on the CI runner - embedding happens at build time, not per query, so CI minutes are the only cost), writes them into `cases.db`, and uploads the artifact to Scaleway Object Storage.
3. **Query execution**:
   - **Phase 1 (client-side)**: the browser loads the SQLite WASM runtime, opens `cases.db` over HTTP range requests, and runs FTS5 BM25 queries plus metadata filters locally. Queries never leave the browser.
   - **Phase 2 (server-side)**: the Scaleway Serverless Container downloads/caches `cases.db` on cold start; per request it computes the query embedding with the same bundled model family used at build time, runs BM25 + vector similarity, merges/re-ranks (e.g. reciprocal rank fusion), and returns results in the shared JSON contract.
4. **Client layer** - the static site is the only client. Its `SearchProvider` interface has two implementations, `LocalSqliteProvider` and `RemoteApiProvider`, selected by build-time config. Result rendering, filters, and the assistant handoff (prompt composer + copy button + deep links) are identical across providers.

**Patterns to Consider**:
- One canonical `cases.db` artifact across both phases - never fork retrieval logic or schema between the client-side and server-side paths.
- Chunk passages using the rulings' own section structure (facts / `-A-` arguments / `-B-` reasoning / operative ruling), not a fixed delimiter or word count - case lengths vary enormously (roughly 700 to 340,000+ words across the sample corpus), so naive splitting produces wildly inconsistent, low-quality chunks. Chunking happens in Phase 1 and is the unit for both BM25 and later embeddings; getting it right once is what makes Phase 2 an additive change.
- Idempotent, full-rebuild index generation in CI while the corpus is small; revisit incremental builds only if rebuild time or CI minutes become a problem.
- The prompt composer treats prompts as data: a template with the question, N passages, and citations, unit-tested for size limits and citation completeness.
- Phase 2 infrastructure as code via Terraform (official `scaleway` provider): Object Storage bucket, container registry namespace, container namespace + container, IAM application/policy - committed to the repo. Terraform state goes to a durable remote backend (private Scaleway Object Storage bucket, S3-compatible) from day one of Phase 2; no local state.
- Phase 2 CI builds the query-service image and pushes to Scaleway Container Registry before `terraform apply` points the container at the new tag.

**Patterns to Avoid**:
- No servers, containers, Docker, or Terraform in Phase 1. The Phase 1 deliverable is static files; resist infrastructure that Phase 2 will introduce properly.
- No self-hosting of the query API on the maintainer's own network/hardware.
- No requirement for end users to hold API keys, create accounts, clone repos, or install anything.
- No shared static API key in browser-delivered code, ever - it is public the moment it ships. Machine-client keys return only if V2 (GPT/MCP) does.
- No per-query calls to paid external embedding APIs - embeddings are computed at build time in CI (Phase 2), and query-time embedding uses a small bundled model inside the query service.
- No storing full ruling text on the browser's query hot path - full text lives in pre-rendered per-case pages.
- No pulling the Phase 2 image from external registries (Docker Hub, GHCR) for production - use Scaleway Container Registry, per Scaleway's guidance on Serverless Containers.

## Technical constraints

**Deployment Target**:
- Phase 1: GitHub Pages (static site + `cases.db`), built and deployed by GitHub Actions. Nothing else.
- Phase 2: Scaleway Serverless Containers (`fr-par`) for the query API; Scaleway Container Registry (`fr-par`, public, free tier); Scaleway Object Storage (`fr-par`) for `cases.db`; all defined in Terraform and applied from CI.

**Hosting limits (Phase 1, verify empirically once real data exists)**:
- GitHub Pages: ~1 GB site size, ~100 GB/month soft bandwidth cap. A corpus of low thousands of rulings (index in `cases.db` + rendered HTML) should fit with room; confirm after the first full pipeline run, since a few rulings exceed 300k words.
- Deploy via the Pages artifact workflow (`actions/upload-pages-artifact` / `actions/deploy-pages`), not by committing built artifacts to a branch - this avoids git's 100 MB per-file limit applying to `cases.db` and keeps build outputs out of history.
- GitHub Pages' CDN must serve correct `Accept-Ranges`/206 responses for the range-request VFS; verify this in an early spike before building the frontend on it. If it ever fails or the site outgrows Pages, Scaleway Object Storage static website hosting is the drop-in escape hatch (still no server).

**Scaling Requirements**:
- Expected users: unknown/low initially (awareness-driven). Phase 1 scales with GitHub's CDN at zero cost. Phase 2 must stay within Scaleway free tiers (1,000,000 requests/month, 400,000 GB-s compute, 75 GB registry storage).
- Expected data volume: the Belgian Constitutional Court ruling archive, likely low thousands of documents - to be confirmed once the ingestion pipeline is built.
- Peak load: low and bursty, driven by ad hoc user questions.

**Security Requirements**:
- Phase 1: no secrets, no server attack surface; supply-chain care for the WASM/JS dependencies (pin versions, no CDN-hosted script tags - vendor the runtime).
- Phase 2: keyless API hardened by per-IP rate limiting, origin-locked CORS, response caps, and rejection logging.
- No PII expected in ruling text, but frontmatter and content should be spot-checked before publishing.
- EU data residency: Phase 1 queries never leave the browser (strongest posture); Phase 2 processing is EU-only (Scaleway Paris). Static assets on GitHub Pages ride a US-owned CDN - acceptable for public case law, with Scaleway Object Storage as the alternative if this becomes a hard requirement.
- The maintainer's local ingestion hardware must remain fully unreachable from the public internet (outbound-only git push).

## Non-Functional Requirements

**Performance**:
- Phase 1: first search on a page load may take 1-3 s (WASM init + initial range requests); subsequent searches should feel near-instant on cached pages. Keep total bytes fetched per typical query in the low hundreds of KB - enforce via the CI query-budget check.
- Phase 2: sub-1 s for the API call itself; container cold starts are acceptable given the user's own downstream LLM synthesis already takes seconds.
- Throughput: no sustained high-throughput requirement; must not exceed free-tier limits under expected usage.

**Availability**:
- Uptime target: best-effort - personal/community project, no SLA. Phase 1 availability equals GitHub Pages availability.
- Acceptable downtime: yes, for maintenance windows or free-tier resets.

**Observability**:
- Phase 1: none at runtime by design (no server, no client-side analytics). CI is the observability surface: build logs, query-budget check, text-quality flags.
- Phase 2: Scaleway container logs for request volume, rate-limit rejections, and errors - enough to spot abuse or breakage without paid monitoring; periodic manual check of free-tier usage.
- Alerting: not required for MVP; revisit if traffic grows meaningfully.

## Team Context

**Team Size**: Solo maintainer.

**Skill Levels**: Senior/technical maintainer; end users are explicitly non-technical.

**Maintenance Plan**: Maintainer runs ingestion locally and pushes updates; GitHub Actions handles index build, site build, and deployment with no manual step beyond `git push`. Phase 2 adds image build/push and `terraform apply` to the same automated flow.

## Dependencies & Risks

**External Dependencies**:
- GitHub (Pages, Actions free tier) - the entire Phase 1 hosting and CI surface.
- `sql.js-httpvfs` / `wa-sqlite` + SQLite WASM - niche but stable ecosystem; the chosen library sits behind the `SearchProvider` abstraction to contain replacement cost.
- `pdfplumber` for PDF text extraction in the ingestion pipeline.
- The Court's own website/case listing as the sole source of truth - its markup, overview page structure, and PDF URL pattern could change without notice, breaking the scraper.
- Phase 2: Scaleway (Serverless Containers + Container Registry + Object Storage, `fr-par`) - free-tier limits and future pricing are outside the maintainer's control.
- Assistant deep-link URL schemes (ChatGPT/Copilot prompt prefill) - third-party surfaces that can change without notice; the clipboard handoff is deliberately immune to this.

**Known Risks**:
- Range-request behavior on GitHub Pages' CDN is the load-bearing Phase 1 assumption - de-risk with a spike before frontend work starts.
- `cases.db` growth: a page-size-1024 database with FTS5 over a large corpus can get big; the CI size/query-budget check plus the "full text stays out of the DB hot path" rule are the mitigations, and splitting the index or moving static hosting to Object Storage are the fallbacks.
- BM25-only retrieval in Phase 1 will underperform on fuzzy layperson phrasing; this is an accepted, explicitly communicated gap that Phase 2 closes. Use the gap productively: note query types that fail, to validate the hybrid ranker later.
- Retrieval quality for Dutch legal terminology needs empirical validation (FTS5 tokenizer choice - unicode61 with diacritics handling as the starting point; evaluate stemming needs against real queries). Extending to French/German later requires its own tokenization/embedding validation.
- Embedding model choice for Dutch legal text (Phase 2) needs a small evaluation set built from Phase 1 usage before committing.
- No text-quality QA workflow is defined yet for catching PDF-extraction errors before or after publishing.
- Terraform state durability (Phase 2): remote S3-compatible backend from the first apply; losing state on a solo maintainer's machine would leave infrastructure unmanaged.
- Free-tier quota exhaustion or a Scaleway policy change could reintroduce hosting cost in Phase 2; per-IP rate limiting deters casual abuse but not a determined bad actor.

## Open Technical Questions

- `sql.js-httpvfs` vs. `wa-sqlite`: which offers the better maintained, better performing range-request VFS for this use? Decide via a spike against a realistic fixture database.
- What FTS5 tokenizer configuration best serves Dutch legal text (diacritics, compound words, stemming), and does it need a custom tokenizer or is unicode61 adequate?
- Exact CI query-budget thresholds: what byte/request ceiling per representative query keeps Phase 1 search feeling fast on a mediocre corporate network?
- Phase 2 embedding model: which small multilingual model (MiniLM/E5-class, ONNX) performs acceptably on Dutch legal text, and can the identical model run both in CI (build-time chunk embeddings) and in the container (query-time)?
- Phase 2 vector storage: `sqlite-vec` virtual table inside `cases.db` vs. a plain embeddings table with brute-force similarity in the service - at low-thousands of documents, brute force may be simpler and fast enough.
- What triggers re-ingestion of an already-published case when a text-quality or metadata bug is found - manual reprocessing only, or an automated re-check?
- Is a full rebuild of `cases.db` on every push acceptable indefinitely, or does incremental indexing become necessary past a certain corpus size (also a CI-minutes question once embedding lands in Phase 2)?
- Which assistant deep links are worth supporting at launch (ChatGPT `?q=` is documented; Copilot and Claude prefill support to be verified), given the clipboard path covers all of them?
- When French/German coverage is picked up later, does the `n`-suffix PDF naming pattern (`{year}-{sequence}n.pdf`) extend to `f`/`d`-suffixed siblings at the same host?
