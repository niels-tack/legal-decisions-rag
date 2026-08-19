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

**Database**: SQLite as a single portable `cases.db` artifact - the one canonical index for both phases, and for every judicial body:
- `cases` table: one row per ruling with all frontmatter metadata (**source** - the issuing judicial body, e.g. `GHCC` for the Constitutional Court - ECLI, case number, rolnummer, slug, date, language, procedure type, controlled norm, outcome, tags, source PDF URL). `source` is a plain column, not a separate table: at POC scale a handful of bodies never justifies a join, and every query that cares about it (the source filter, citations) already reads from `cases` directly.
- `chunks` table: one row per **numbered paragraph** (see chunking pattern below - this is finer-grained than one row per section), keyed to its case, with the broad section label (facts/arguments/reasoning/ruling) kept as metadata, its own paragraph number where the source ruling numbers paragraphs (e.g. `B.7.3`, nullable - not every body/section numbers its text), the JSON-encoded list of that paragraph's ancestor numbers (e.g. `["B", "B.7"]` for `B.7.3`; empty when there's no numbering to derive ancestors from), and order.
- FTS5 virtual table over `chunks` for BM25 (contentless or external-content mode referencing `chunks`, to avoid storing text twice).
- Phase 2 adds embeddings over the same `chunks` rows: an `embeddings` table or `sqlite-vec` virtual table keyed by chunk id. Reserve the naming now; do not redesign the schema later. The stored ancestor-number list is what makes *layered* embeddings (one vector per paragraph, plus one per broader numbered section like `B.7`) an additive change later rather than a schema change - not built in this phase, but the reference is captured now so it doesn't have to be reconstructed retroactively.
- Full ruling text for the per-case pages is pre-rendered into static HTML at build time, not fetched from `cases.db` at runtime, so browser queries touch only small index/metadata pages.

**Range-request tuning (Phase 1 critical)**: build `cases.db` with a small page size (1024 bytes, the documented sweet spot for HTTP VFS access), run `VACUUM` and `ANALYZE` after build, and keep hot-path rows small. Verify in CI that a representative query completes within a bounded number of range requests / bytes transferred, so index bloat is caught before deploy.

**Other Preferences**:
- Keep ingestion, index-build, and frontend/query-serving as separate, independently testable modules - the local pipeline must not couple to how search is served.
- Keep ingestion itself organized per judicial body: each source (Constitutional Court now, Council of State later) gets its own discovery/extraction module and its own paragraph-numbering marker pattern, registered against a shared, small source-config abstraction. Index-build's chunker, the schema, and the query service read that registry rather than hard-coding any one body's conventions.
- Define the search result contract once (JSON shape: chunk text, source, ECLI, case number, date, outcome, section label, paragraph number, PDF URL, score) and use it identically for the Phase 1 client-side path and the Phase 2 API. This contract is what makes the backend swap invisible to the UI. Filtering by source works the same way as the existing date-range/procedure-type filters - a `WHERE`/query-param addition, not a different code path.
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
   - **Discover (metadata)**: scrape the Court's official case overview listing (`https://nl.const-court.be/nl/judgments?year={year}`) for case number, docket number ("rolnummer"), date, procedure type, controlled norm, outcome, and official keywords. This page is a server-rendered Vuetify SPA that applies TLS fingerprinting blocking the Python `requests` library; in practice the HTML is saved from a browser session and passed to the parser, which is a pure function with no live network dependency.
   - **Discover (PDFs)**: PDFs are downloaded from the Court's public document server (`https://nl.const-court.be/public/n/`), which serves a plain Apache directory listing accessible without TLS fingerprinting. Year subdirectories (`/public/n/{year}/`) list files following the convention `{year}-{seq:03d}n.pdf` (zero-padded three-digit sequence, Dutch-language `n` suffix). Some rulings have a companion `-info.pdf` (e.g. `2026-002n-info.pdf`); these are information-card PDFs, not body text, and are not ingested. The download URL for a given slug is `https://nl.const-court.be/public/n/{year}/{slug}.pdf`.
   - **URL patterns** (per the Court's referencing guidelines at `https://nl.const-court.be/rule/referencing-judgments`): three canonical URL patterns are in use. (a) **PDF permalink** `https://{lang}.const-court.be/{number}/{year}.pdf` - the stable citation link, stored in `cases` as `source_pdf_url`. (b) **Info card** `https://{lang}.const-court.be/ARR/{number}/{year}` - the metadata/fiche page, exposed in search results as `permalink_info_card`. (c) **Download** `https://{lang}.const-court.be/public/n/{year}/{slug}.pdf` - used only by the ingestion pipeline, never stored. Language-specific subdomains (`nl.`, `fr.`, `de.`, `en.`) are the canonical form since August 2025; `www.const-court.be` still resolves but redirects.
   - **Extract**: convert each PDF to text with `pdfplumber`, preserving the ruling's section structure (numbered facts, `-A-` party arguments, `-B-` the Court's reasoning, operative ruling). Strip repeated header/footer boilerplate (e.g. the `ECLI:BE:GHCC:\d{4}:ARR\.\d+` line, page numbers) via pattern matching rather than coordinate-based cropping.
   - **Assemble**: merge the discovered metadata and extracted text into one Markdown file per ruling with YAML frontmatter. Capture every readily available field rather than a minimal set: the ECLI identifier (canonical citation), the official case number (e.g. `1/2025`), the role/docket number ("rolnummer", e.g. `8115`), and the file/URL slug (e.g. `2025-001n`) as three distinct fields - these are different identifiers and must not be collapsed into one ambiguous "case number" - plus ruling date, language, procedure type, controlled norm, outcome, and subject tags/keywords.

   This machine is never reachable from the public internet; it only pushes finished Markdown to GitHub over outbound git.
2. **CI build (GitHub Actions, free runners)** - on push to `main` under the cases directory: parse committed Markdown + frontmatter; chunk by ruling structure; build `cases.db` (metadata + chunks + FTS5, tuned for range access); render the static site (search page, per-case HTML pages); deploy site + database to GitHub Pages via the Pages artifact workflow. In Phase 2 the same job additionally computes embeddings for all chunks on the CI runner (4-vCPU/16 GB x86, free for public repos - faster than any consumer local hardware and zero added maintenance). Embedding is model-agnostic by design: model name, dimension count, required prefixes, and a SHA-256 hash of the weights file are stored in a `model_meta` table in `cases.db`; a model swap automatically invalidates and triggers a full re-embed, consistent with the full-rebuild philosophy. The realistic model shortlist is: **multilingual-e5-small** (~118 MB ONNX int8, 384 dims, MIT) - proven, tiny in the container, well-validated on Dutch; requires `"query: "` / `"passage: "` prefixes hard-coded in the embed call and tested; or **EmbeddingGemma-300M** (~200 MB quantized, 768-dim with Matryoshka truncation to 128 dims) - stronger small-model alternative, Matryoshka support lets stored vectors be shrunk later without re-embedding. The model choice is settled by a 50-100 question evaluation set (see Known Risks), not by leaderboard scores. Hugging Face is used only as a weights download source, never as an inference provider: the serverless Inference API is credit-metered, rate-limited for bulk use, and would introduce a third-party runtime dependency in the query path. BGE-M3 (~2.2 GB) is the multilingual quality reference but wrong-shaped for this system: it strains the container RAM budget and its primary edge is built-in sparse retrieval, which this project already covers with FTS5 BM25.
3. **Query execution**:
   - **Phase 1 (client-side)**: the browser loads the SQLite WASM runtime, opens `cases.db` over HTTP range requests, and runs FTS5 BM25 queries plus metadata filters locally. Queries never leave the browser.
   - **Phase 2 (server-side)**: the Scaleway Serverless Container downloads/caches `cases.db` on cold start; per request it computes the query embedding using the identical ONNX weights bundled in the container image (byte-for-byte the same model used at build time, including any required text prefixes - for e5-small this means prepending `"query: "` to every query string), runs BM25 + cosine similarity, merges via reciprocal rank fusion, and returns results in the shared JSON contract. Vector similarity uses brute-force dot-product over stored float32 embeddings in NumPy - no ANN index; at ~300k chunks × 384 dims ≈ 460 MB float32 (≈115 MB int8-quantized), brute-force in NumPy takes tens of milliseconds, which is well within the sub-1 s API budget.
4. **Client layer** - the static site is the only client. Its `SearchProvider` interface has two implementations, `LocalSqliteProvider` and `RemoteApiProvider`, selected by build-time config. Result rendering, filters, and the assistant handoff (prompt composer + copy button + deep links) are identical across providers.

**Patterns to Consider**:
- One canonical `cases.db` artifact across both phases - never fork retrieval logic or schema between the client-side and server-side paths.
- Chunk at the ruling's own *numbered paragraph* granularity (e.g. `A.1`, `B.7`, `B.7.3`), not a fixed delimiter, word count, or the coarser section boundary alone - case lengths vary enormously (roughly 700 to 340,000+ words across the sample corpus), so naive splitting produces wildly inconsistent, low-quality chunks, and a whole section (arguments/reasoning) can itself run to hundreds of numbered points that deserve independent retrieval and citation. The broad section (facts / `-A-` arguments / `-B-` reasoning / operative ruling) is still recorded, as metadata on each chunk, not as the chunk boundary. A section or body with no numbering (the facts and operative-ruling sections, in the Constitutional Court's own rulings) falls back to one whole-section chunk - the splitter must degrade gracefully per section, not assume every ruling numbers everything. Each judicial body owns its own numbering-marker pattern (see the source-config abstraction above); the Constitutional Court's is `<letter>(.<number>)+.` (e.g. `B.7.3.`), with the chunk's ancestor numbers (`B`, `B.7`) derived from splitting that identifier on `.` - a different body's pattern is a new regex, not new chunker logic. Chunking happens in Phase 1 and is the unit for both BM25 and later embeddings; getting it right once is what makes Phase 2 an additive change.
- Idempotent, full-rebuild index generation in CI while the corpus is small; revisit incremental builds only if rebuild time or CI minutes become a problem.
- The prompt composer treats prompts as data: a template with the question, N passages, and citations, unit-tested for size limits and citation completeness.
- Phase 2 infrastructure as code via Terraform (official `scaleway` provider): Object Storage bucket, container registry namespace, container namespace + container, IAM application/policy - committed to the repo. Terraform state goes to a durable remote backend (private Scaleway Object Storage bucket, S3-compatible) from day one of Phase 2; no local state.
- Phase 2 CI builds the query-service image and pushes to Scaleway Container Registry before `terraform apply` points the container at the new tag.

**Patterns to Avoid**:
- No servers, containers, Docker, or Terraform in Phase 1. The Phase 1 deliverable is static files; resist infrastructure that Phase 2 will introduce properly.
- No self-hosting of the query API on the maintainer's own network/hardware.
- No requirement for end users to hold API keys, create accounts, clone repos, or install anything.
- No shared static API key in browser-delivered code, ever - it is public the moment it ships. Machine-client keys return only if V2 (GPT/MCP) does.
- No per-query calls to paid or rate-limited external embedding APIs. Embeddings are computed at build time in CI (Phase 2); query-time embedding uses a small ONNX model bundled inside the container. The Hugging Face serverless Inference API is explicitly excluded: it is credit-metered, rate-limited for bulk batch use, and would place a third-party runtime dependency in the query path. Use HF as a model download source only.
- No ANN (approximate nearest-neighbor) index or dedicated vector database at this corpus scale. Brute-force cosine similarity over stored float32 vectors in NumPy is both simpler and correct; an ANN index trades correctness for speed only worth the trade-off at >1M vectors. Revisit only if the corpus grows by an order of magnitude.
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
- The Court's own website/case listing as the sole source of truth for metadata, and its public document server (`https://nl.const-court.be/public/n/`) as the source for PDF downloads. The listing page applies TLS fingerprinting that blocks automated `requests` clients; the document server does not. Both the listing markup and the document server's Apache directory structure could change without notice. The Court's published referencing guidelines (`https://nl.const-court.be/rule/referencing-judgments`) define the stable URL patterns the code relies on for permalinks and info cards.
- Phase 2: Scaleway (Serverless Containers + Container Registry + Object Storage, `fr-par`) - free-tier limits and future pricing are outside the maintainer's control.
- Assistant deep-link URL schemes (ChatGPT/Copilot prompt prefill) - third-party surfaces that can change without notice; the clipboard handoff is deliberately immune to this.

**Known Risks**:
- Range-request behavior on GitHub Pages' CDN is the load-bearing Phase 1 assumption - de-risk with a spike before frontend work starts.
- `cases.db` growth: a page-size-1024 database with FTS5 over a large corpus can get big; the CI size/query-budget check plus the "full text stays out of the DB hot path" rule are the mitigations, and splitting the index or moving static hosting to Object Storage are the fallbacks.
- BM25-only retrieval in Phase 1 will underperform on fuzzy layperson phrasing; this is an accepted, explicitly communicated gap that Phase 2 closes. Use the gap productively: note query types that fail, to validate the hybrid ranker later.
- Retrieval quality for Dutch legal terminology needs empirical validation (FTS5 tokenizer choice - unicode61 with diacritics handling as the starting point; evaluate stemming needs against real queries). Extending to French/German later requires its own tokenization/embedding validation.
- Embedding model choice for Dutch legal text (Phase 2): Phase 1 is privacy-first by design - queries never leave the browser, so there are no query logs to mine. Build a 50-100 question evaluation set instead: half in lawyer phrasing, half in layperson phrasing, each mapped to known-relevant rulings and paragraphs; an LLM can draft candidates from real rulings, the maintainer verifies. Measure recall@10 for BM25-alone, BM25+e5-small, and BM25+EmbeddingGemma-300M. Keep the eval set in the repo; it becomes the regression test for every future model change, tokenizer tuning, or language extension. Dutch-specific RobBERT-derived embedders and English legal embedders are deprioritized: the former are typically stale community fine-tunes that underperform larger multilingual models, and the latter don't cover Dutch. Legal-domain precision in this system comes primarily from BM25 on exact legal terminology and the Court's own keywords; the dense model needs only to capture conceptual paraphrasing, which small multilingual models handle adequately.
- No text-quality QA workflow is defined yet for catching PDF-extraction errors before or after publishing.
- Terraform state durability (Phase 2): remote S3-compatible backend from the first apply; losing state on a solo maintainer's machine would leave infrastructure unmanaged.
- Free-tier quota exhaustion or a Scaleway policy change could reintroduce hosting cost in Phase 2; per-IP rate limiting deters casual abuse but not a determined bad actor.

## Open Technical Questions

- `sql.js-httpvfs` vs. `wa-sqlite`: which offers the better maintained, better performing range-request VFS for this use? Decide via a spike against a realistic fixture database.
- What FTS5 tokenizer configuration best serves Dutch legal text (diacritics, compound words, stemming), and does it need a custom tokenizer or is unicode61 adequate?
- Exact CI query-budget thresholds: what byte/request ceiling per representative query keeps Phase 1 search feeling fast on a mediocre corporate network?
- Phase 2 embedding model: shortlist is **multilingual-e5-small** (safe default, 384 dims, requires prefix discipline) and **EmbeddingGemma-300M** (stronger challenger, Matryoshka dims). Decision deferred to the evaluation set described in Known Risks; the implementation is model-agnostic so the choice does not block development. Open sub-question: does EmbeddingGemma's Matryoshka support give meaningful recall at 256 dims vs 768, and does the storage saving justify the extra evaluation effort?
- Phase 2 vector storage: **resolved** - plain `embeddings` table in `cases.db` with brute-force NumPy cosine similarity in the query service. At ~300k chunks × 384 dims the float32 blob is ~460 MB (≈115 MB int8); brute-force takes tens of milliseconds, well inside the latency budget. `sqlite-vec` and ANN indexes are ruled out for this corpus scale.
- What triggers re-ingestion of an already-published case when a text-quality or metadata bug is found - manual reprocessing only, or an automated re-check?
- Is a full rebuild of `cases.db` on every push acceptable indefinitely, or does incremental indexing become necessary past a certain corpus size (also a CI-minutes question once embedding lands in Phase 2)?
- Which assistant deep links are worth supporting at launch (ChatGPT `?q=` is documented; Copilot and Claude prefill support to be verified), given the clipboard path covers all of them?
- When French/German coverage is picked up later, does the `n`-suffix PDF naming pattern (`{year}-{sequence}n.pdf`) extend to `f`/`d`-suffixed siblings at the same host?
- Council of State paragraph-numbering convention: **resolved** - Arabic dot-notation (`1.`, `1.2.`, `1.2.3.`), captured by `r"(?m)^\s*(\d+(?:\.\d+)*)\.\s+"`. Roman-numeral headings (`I.`, `II.`) mark major document sections and are handled by the heading normalization layer, not as paragraph markers. The `SourceConfig` entry and `RVS_HEADING_MAP` are registered in `src/sources.py`; the ingestion pipeline (discovery, extraction, assemble) remains to be written.
