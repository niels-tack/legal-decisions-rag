# Functional requirements: legal-decisions-rag

> **Single source of truth for project scope and requirements**
>
> This document defines what the project should do and for whom. Update this as requirements evolve.
> AI coding assistants will reference this to ensure code aligns with project goals.

## Problem statement

Belgian high-court rulings are only available as scattered PDF documents on each court's own website, with no way for non-technical legal professionals or citizens to search across them or ask natural-language questions and get cited passages back. The POC starts with the Constitutional Court (https://nl.const-court.be/), but the same problem applies to other Belgian judicial bodies (e.g. the Council of State's case-law search at https://raadvanstate.be/), so the project's data model and ingestion pipeline are designed to add a body without re-architecting, not to lock in a single-court assumption. Existing local RAG tools (e.g. qmd) require installing software, cloning repositories, and managing API keys - a barrier most target users will not cross. Chat-platform distribution channels (Copilot Studio agents, Custom GPTs, MCP) are not viable primary channels either: each requires paid licensing on the maintainer's side, per-tenant IT approval on the user's side, or technical configuration - and often all three.

The only channel that reaches every target user with zero installs, zero accounts, zero IT clearance, and zero recurring cost is a plain public website. This project therefore delivers the case law as a searchable website, with a built-in handoff that carries retrieved, cited passages into whatever AI assistant the user already has (Copilot, ChatGPT, Claude) for synthesis on the user's own account and terms.

## Target users

**Primary Users**: Non-technical legal professionals (lawyers, in-house counsel, paralegals, policy staff, journalists, researchers) and interested citizens. They need only a web browser - including a locked-down corporate one. Many will additionally use their existing Microsoft Copilot, ChatGPT, or Claude account to synthesize answers from the passages the site retrieves, but no AI account is required to use the site.

**Secondary Users**: The maintainer (solo, technical), who processes PDFs into Markdown, runs the ingestion pipeline on personal hardware, and keeps the public dataset and index current.

## Phasing

The project runs in two closely spaced phases plus a deferred V2. Phase 2 is committed scope on a short lead time, not an optional enhancement, so Phase 1 decisions must not make Phase 2 harder (the technical requirements pin down how).

- **Phase 1 (POC/MVP)**: static website on GitHub Pages; lexical (BM25) search runs entirely in the browser against a statically hosted SQLite index; assistant handoff via copy-prompt and deep links.
- **Phase 2 (fast follow)**: hosted, EU-based serverless search API (Scaleway) adding vector embeddings for hybrid lexical + semantic retrieval. The website switches its search backend from local to remote by configuration; the UI, data pipeline, and citations stay identical.
- **V2 (deferred)**: MCP server, Custom GPT, and any Microsoft-marketplace agent.

## Success criteria

- Non-technical users can find and read cited, relevant passages from Constitutional Court rulings using only a web browser - zero installs, zero accounts, zero API keys, zero IT clearance.
- Recurring hosting cost is €0.00/month in Phase 1 and stays within provider free tiers in Phase 2.
- The maintainer's home network/hardware is never exposed to the public internet.
- In Phase 1, search queries never leave the user's browser (search executes client-side against a static index). The site states this privacy property visibly, because queries from legal professionals can reveal matter context.
- Retrieval surfaces relevant passages for exact lookups (case number, ECLI, article reference) and keyword/terminology questions from Phase 1; conceptual, plain-language questions retrieve well from Phase 2 (vector search). Initial (POC) scope is Dutch-language Constitutional Court rulings only; French/German coverage and additional judicial bodies (e.g. the Council of State) are later-phase goals.
- Every result traces back to a verifiable ECLI identifier (the Court's standard citation, e.g. `ECLI:BE:GHCC:2025:ARR.001`) and ruling date, with a link to the original official PDF as published on the Court's website, plus the specific numbered paragraph (e.g. `B.7.3`) the passage was taken from wherever the source ruling numbers its paragraphs - not just "somewhere in this document".
- Users can scope a search to one judicial body, several, or all of them (a source filter alongside the date-range/procedure-type filters) - meaningful as soon as a second body is onboarded, and harmless with only one.
- The assistant handoff produces a self-contained prompt (user question + retrieved passages + citations) that any external LLM can turn into a cited answer without further tooling.

## Core requirements

### Must have - Phase 1 (POC/MVP)

- Local ingestion pipeline (run offline, on the maintainer's own hardware), initially scoped to Dutch-language Constitutional Court rulings only, converting official PDF rulings into structured Markdown with YAML frontmatter. Go for the most robust, complete metadata capture practical: every readily available field from the Court's official case overview listing and the PDF itself should be captured, not just a minimal set. At minimum this includes which judicial body issued the ruling (the "source" - Constitutional Court for the POC), the ECLI identifier (canonical citation), the official case number (e.g. "1/2025"), the role/docket number ("rolnummer", e.g. "8115"), and the file/URL slug (e.g. "2025-001n") as distinct, clearly labeled identifiers (they are not interchangeable and conflating them risks citation errors), plus ruling date, language, procedure type, controlled norm, outcome, subject tags/keywords, and the source PDF URL. Each judicial body gets its own discovery/extraction logic (courts publish differently) behind a shared per-source plug-in point, so onboarding the Council of State later means writing that body's ingestion module and registering its own paragraph-numbering convention, not modifying the shared pipeline, schema, or chunking logic.
- Weekly automated scrape of the Court's official case overview listing and PDF publications for newly published rulings, run on the maintainer's local processing machine, with new/updated Markdown pushed from there to the public GitHub repository.
- Public GitHub repository hosting the processed Markdown as the canonical, versioned data source.
- Automated build (GitHub Actions) producing two artifacts from the committed Markdown: (a) a single SQLite database (`cases.db`) containing an FTS5 full-text index (BM25) over structure-aware passage chunks plus all frontmatter metadata, and (b) the static website. Both deploy to GitHub Pages on push, with no manual step beyond `git push`.
- Client-side search: the website queries the statically hosted `cases.db` directly in the browser via HTTP range requests, fetching only the database pages a query needs rather than the whole file. No server component exists in Phase 1.
- Search results show ranked passages with ECLI, case number, ruling date, outcome, and an excerpt; each result links to a per-case page and to the original official PDF on https://nl.const-court.be/ for verification.
- Basic metadata filters in the search UI (at minimum date range, procedure type, and judicial body/source) - the frontmatter already carries this data and client-side SQL makes filtering cheap. With only the Constitutional Court onboarded, the source filter has one option and is effectively a no-op, but the filter itself (and the underlying `source` field) exists from Phase 1 so a second body is a data addition, not a UI or schema change.
- Assistant handoff: a "copy prompt" button that composes the user's question, the top retrieved passages, and full citations (ECLI, date, official PDF URL) into a clipboard-ready prompt for pasting into Copilot, ChatGPT, or Claude; plus "open in ..." deep links where a platform's URL prompt-prefill allows, respecting URL length limits. The copy button is the primary mechanism; deep links are convenience on top.
- Per-case pages rendering the full ruling text with its metadata, so users (and their assistants, via paste) can work with a complete ruling.

### Must have - Phase 2 (fast follow)

- Hosted, EU-based serverless search API (Scaleway, no self-hosting, no home-network exposure) serving hybrid retrieval: BM25 plus vector similarity over the same passage chunks, merged and re-ranked, returning the same citation fields the Phase 1 frontend already renders.
- The same `cases.db` artifact, extended with embeddings, remains the single canonical index consumed by the API. No forked retrieval logic between phases.
- The website's search backend is switchable by configuration between local (Phase 1 behavior, retained as fallback) and the remote API. The UI does not change.
- Abuse protection appropriate for a keyless browser client: per-IP rate limiting, CORS restricted to the site's origin, response-size caps, and request/rejection logging. No end-user keys.
- The site's privacy statement is updated to reflect that queries reach the API in Phase 2, with logging kept to the minimum needed to spot abuse and breakage.

### Should have

- A text-quality check on extracted rulings before publishing (e.g. flagging suspiciously broken tokens/spacing from PDF extraction) so garbled text doesn't silently degrade search results or mislead users.
- An honest note in the Phase 1 UI that search is keyword-based, with short guidance on effective queries (legal terminology, case numbers), until semantic search lands in Phase 2.

### Could have

- Additional filters (outcome, subject tags, controlled norm) beyond the Phase 1 minimum.
- Lightweight usage signals in Phase 2 (from API logs only, no client-side tracking) to learn what people actually search, informing retrieval tuning.
- French/German ruling coverage, and retrieval quality tuned for that trilingual mix, as a later-phase expansion once the Dutch-only POC is validated.
- A second judicial body - the Council of State (Raad van State), whose published case law is time-window-searchable at raadvanstate.be - onboarded as a new ingestion module against the existing per-source plug-in point. Its own paragraph-numbering convention (likely different from the Constitutional Court's `A.`/`B.`-lettered scheme) needs its own investigation before it can be registered.

### Won't have (this version)

- MCP server, Custom GPT, Copilot Studio agent, or any other chat-platform integration (all moved to V2). Each requires a paid subscription, per-tenant IT approval, or both; none is needed once the website plus assistant handoff exists.
- Any requirement for end users to hold an API key, create an account, clone a repository, or install anything.
- Self-hosting the query API on the maintainer's own network/hardware exposed to the internet.
- Answer generation by the system itself - the site retrieves and cites source passages; synthesis happens in the user's own LLM via the handoff, on their account and responsibility.
- French- and German-language rulings (POC is Dutch-only).

## User workflows

### Workflow 1: Search and verify in the browser (core, both phases)

1. User opens the public website and types a question or keywords, e.g. "omgevingsvergunning 2024", an case number, or an ECLI, optionally narrowing to one or more judicial bodies via the source filter (only the Constitutional Court exists as an option until a second body is onboarded).
2. Phase 1: the browser fetches only the needed index pages from the statically hosted `cases.db` and ranks passages with BM25 locally. Phase 2: the site calls the hosted API, which runs hybrid BM25 + vector retrieval over the same chunks. Filters narrow by date, procedure type, and source in both.
3. Results show ranked passages with ECLI, date, outcome, the specific numbered paragraph (e.g. `B.7.3`) where available, and an excerpt.
4. User opens the per-case page for the full text, or clicks through to the original official PDF to verify.

### Workflow 2: Handoff to the user's own AI assistant

1. After a search, the user clicks "copy prompt" (or an "open in ..." deep link where supported).
2. The site composes a self-contained prompt: the user's question, the top passages, and full citations (ECLI, date, official PDF URL).
3. The user pastes it into the assistant they already use - Copilot at work, ChatGPT, Claude - which synthesizes a cited answer under the user's own account, terms, and IT policy.
4. The embedded citations let the user trace every claim back to the official PDF.

### Workflow 3: Weekly scrape and update of new rulings

1. On a weekly cadence, the local ingestion pipeline on the maintainer's own hardware checks https://nl.const-court.be/ for newly published rulings.
2. New PDFs are downloaded and processed through the pipeline, producing Markdown + frontmatter (including the source PDF URL) for each new case.
3. Maintainer pushes the new Markdown files to the public GitHub repository.
4. GitHub Actions rebuilds `cases.db` and the static site and deploys to GitHub Pages, with no manual deployment step beyond the `git push`. In Phase 2 the same workflow additionally computes embeddings for new chunks, uploads the extended `cases.db` to Scaleway Object Storage, and the API picks it up.

## Constraints

**Timeline**: Phase 1 first; Phase 2 is a committed fast follow on a short lead time. Exact dates flexible.

**Budget**: €0.00/month recurring hosting cost in Phase 1 (GitHub Pages and Actions free tiers). Phase 2 must fit within Scaleway free tiers. The maintainer's own hardware may be used for ingestion but must never be exposed to the public internet.

**Regulatory**: Data is Belgian public-sector case law. Reuse basis should be explicitly confirmed but is expected to fall under public-sector information reuse rules. Phase 1 has the strongest possible privacy posture (queries never leave the browser); Phase 2 introduces an EU-hosted (Scaleway Paris) API for sovereignty/GDPR alignment, with minimal logging. Note that GitHub Pages serves via a US-owned CDN; since the content is public case law and Phase 1 queries stay client-side, exposure is minimal, but if EU static hosting becomes a matter of principle, the same static artifacts can move to Scaleway Object Storage website hosting without architectural change.

**Other**:
- End users must never need an API key, account, GitHub knowledge, or CLI tool.
- The maintainer is a solo developer; the system must be maintainable without a team. Phase 1 deliberately contains no servers, containers, or infrastructure-as-code.
- Phase 1 design choices must not obstruct Phase 2: chunking, schema, and citation fields are shared across phases, and the frontend's search backend is swappable (see technical requirements).
- The corpus is expected to grow beyond the Constitutional Court eventually: every case carries an explicit judicial-body/source field, and ingestion is organized so a new body is a new, independently-testable module rather than a change to shared schema, chunking, or query logic (see technical requirements).
