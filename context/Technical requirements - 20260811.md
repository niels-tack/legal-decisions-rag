# Technical requirements: legal-decisions-rag

> **Single source of truth for technical architecture and constraints**
>
> This document defines how the project should be built. Update this as technical decisions are made.
> AI coding assistants will reference this to ensure code follows the right patterns and constraints.

## Technical preferences

**Language**: Python 3.13 (Ingestion Pipeline & Index Builder), Vanilla JavaScript / HTML5 / CSS3 (PWA Frontend)

**Package Manager**: uv (Python)

**Code Quality**:
- Linting: Ruff
- Type Checking: Ty
- Testing: pytest

## Engineering context

**Web Framework**: Static Web Application hosted on GitHub Pages, configured as a Progressive Web App (PWA) with a Service Worker and Web Manifest. No backend HTTP server or serverless compute layer required.

**Database / Search Index**: A static pre-compiled search index (e.g. Pagefind or Orama) generated during CI. Runs 100% client-side in the user's browser via WebAssembly / JavaScript. No external database or hosted search API, keeping recurring hosting costs strictly at €0.00/month.

**Other Preferences**:
- Keep ingestion, index building, and the web interface as separate, independently testable modules.
- All CI secrets (Scaleway credentials for raw storage if used, GitHub access tokens) live in GitHub Secrets, never committed.
- Prefer lightweight static site generation without heavy JS frameworks (Vite + Vanilla JS or Pagefind static assets).

## Existing systems

**APIs**: Client-side Deep-Link URL Generators targeting public web interfaces (Microsoft Copilot, ChatGPT, Claude) to auto-fill constructed prompt payloads containing retrieved legal excerpts.

**Databases**: None external or hosted - static search index assets (Pagefind/Orama index chunks) built by CI and served directly via GitHub Pages CDN.

**Services**:
- GitHub (public repo + Actions + Pages) for source Markdown, CI index build, PWA static web asset compilation, and public CDN hosting.

**Authentication**: No authentication required. The PWA web portal and public search indices are open access.

## Architecture ideas

**Data flow**:

1. **Local ingestion (offline, maintainer's own hardware, weekly, Dutch-language rulings only for the POC)**:
   - **Discover**: scrape the Court's official case overview listing for case number, docket number ("rolnummer"), date, procedure type, controlled norm, outcome, official keywords, and PDF URL per ruling.
   - **Extract**: convert each PDF to text with `pdfplumber`, preserving the ruling's section structure (numbered facts, `-A-` party arguments, `-B-` the Court's reasoning, operative ruling). Strip repeated header/footer boilerplate via pattern matching.
   - **Assemble**: merge metadata and extracted text into one Markdown file per ruling with YAML frontmatter. Capture distinct identifier fields: ECLI identifier, official case number (e.g. `1/2025`), role/docket number ("rolnummer", e.g. `8115`), and file/URL slug (e.g. `2025-001n`), plus date, language, procedure type, controlled norm, outcome, subject tags, and source PDF URL.

   This machine is never reachable from the public internet; it only pushes finished Markdown to GitHub over outbound git.
2. **CI index & web app build (GitHub Actions, free runners)**:
   - Parses committed Markdown + frontmatter.
   - Builds static client-side search index chunks (using Pagefind/Orama).
   - Bundles PWA static assets (HTML, CSS, JS, manifest.json, service worker).
   - Deploys static build output to GitHub Pages (`gh-pages` branch).
3. **Client-side execution (User's browser via Edge PWA / Web Portal)**:
   - User opens Edge PWA or web portal.
   - Search query runs locally in browser against Pagefind/Orama WebAssembly engine (<100ms lexical/topical search).
   - App renders relevant ruling passages with ECLI citations and metadata.
4. **Deep-Link prompt handoff**:
   - User clicks **`[ 🚀 Ask Microsoft Copilot ]`** or **`[ 💬 Ask ChatGPT ]`** button.
   - Web app constructs a structured, URL-encoded prompt payload (`https://copilot.microsoft.com/?q=...`).
   - Browser opens the AI tool in a new tab or Edge sidebar with the full legal context pre-filled, ready for 1-click LLM synthesis.

**Patterns to Consider**:
- Web App Manifest + Service Worker to enable Edge "Install site as app" (PWA) functionality for desktop taskbar integration on locked-down enterprise PCs.
- Client-side deep-link URL parameter construction to bypass browser extension blocks and corporate IT restrictions.
- Pagefind static indexing for instant, zero-backend full-text keyword and metadata retrieval.
- Idempotent, full-rebuild index generation in CI triggered on push to `main` under the cases directory.

**Patterns to Avoid**:
- No serverless container hosting, query backend APIs, or custom domain subscription costs.
- No requirement for end users to hold API keys, install browser extensions, clone repos, or hold paid enterprise Copilot licenses.
- No per-query external API costs.

## Technical constraints

**Deployment Target**: GitHub Pages (static CDN) hosting PWA web application assets; GitHub Actions for CI (index build and static deployment); public GitHub repo for source Markdown.

**Scaling Requirements**:
- Expected users: non-technical corporate legal users. Static CDN delivery handles unlimited traffic scale within GitHub Pages free tier limits.
- Expected data volume: Belgian Constitutional Court ruling archive (Markdown + frontmatter). Static index split into lightweight downloadable chunks.

**Security Requirements**:
- All published case law data is public domain.
- EU data residency alignment (GitHub Pages / public static distribution).
- Maintainer's local ingestion hardware remains strictly unreachable from the public internet (outbound-only git push).

## Non-Functional Requirements

**Performance**:
- Response time: Sub-100ms instant client-side search rendering. Deep-link prompt handoff executes in 1 click.
- Offline support: PWA Service Worker caches UI and static assets for local re-use.

**Availability**:
- Uptime target: 99.9%+ backed by GitHub Pages infrastructure.

**Observability**:
- Basic static site analytics or GitHub repository traffic insights. No server logs or database monitoring required.

## Team Context

**Team Size**: Solo maintainer.

**Skill Levels**: Senior/technical maintainer; end users are explicitly non-technical corporate workers on locked-down Windows hardware.

**Maintenance Plan**: Maintainer runs ingestion locally and pushes updates; GitHub Actions builds static index and updates GitHub Pages with no manual hosting steps.

## Dependencies & Risks

**External Dependencies**:
- GitHub Actions and GitHub Pages free tier.
- Pagefind / Orama static search library.
- Public URL query parameter schemas for Microsoft Copilot (`copilot.microsoft.com`) and OpenAI ChatGPT (`chatgpt.com`).
- `pdfplumber` for PDF text extraction in local ingestion pipeline.

**Known Risks**:
- Changes to third-party web query URL parameter schemas (e.g. Microsoft changing Copilot URL parameter handling).
- URL length limits in web browsers if retrieved legal excerpts are exceptionally long (mitigated by excerpt truncation/compression before deep-linking).
