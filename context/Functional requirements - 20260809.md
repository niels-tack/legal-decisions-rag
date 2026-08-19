# Functional requirements: legal-decisions-rag

> **Single source of truth for project scope and requirements**
>
> This document defines what the project should do and for whom. Update this as requirements evolve.
> AI coding assistants will reference this to ensure code aligns with project goals.

## Problem statement

Belgian Constitutional Court rulings are only available as scattered PDF documents on the Court's own website (https://nl.const-court.be/), with no way for non-technical legal professionals or citizens to search across them semantically or ask natural-language questions and get cited passages back. Existing local RAG tools (e.g. qmd) require installing software, cloning repositories, and managing API keys - a barrier most target users will not cross. Without a zero-install, zero-cost way to query this case law conversationally through AI tools people already use, valuable constitutional jurisprudence stays effectively undiscoverable to anyone who isn't a developer.

## Target users

**Primary Users**: Non-technical legal professionals (lawyers, paralegals, policy staff, journalists) and interested citizens who already use Microsoft Copilot, ChatGPT, or Claude day-to-day and want to ask plain-language questions about Belgian Constitutional Court rulings without installing anything, cloning a repository, or holding an API key.

**Secondary Users**: The maintainer (solo, technical), who processes PDFs into Markdown, runs the ingestion pipeline on personal hardware, and keeps the public dataset and index current.

## Success criteria

- Non-technical users can get cited, relevant passages from Constitutional Court rulings using only their existing Copilot/ChatGPT/Claude account - zero installs, zero API keys, zero repo cloning.
- Recurring hosting cost stays at €0.00/month.
- The maintainer's home network/hardware is never exposed to the public internet.
- Retrieval surfaces relevant passages for both exact lookups (case number, article reference) and conceptual/topical questions. Initial (POC) scope is Dutch-language rulings only; French/German coverage is a later-phase goal, not required for the first working version.
- Every answer traces back to a verifiable ECLI identifier (the Court's standard citation, e.g. `ECLI:BE:GHCC:2025:ARR.001`) and ruling date, with a link to the original official PDF as published on the Court's website.

## Core requirements

### Must have (MVP)

- Local ingestion pipeline (run offline, on the maintainer's own hardware), initially scoped to Dutch-language rulings only, converting official Constitutional Court PDF rulings into structured Markdown with YAML frontmatter. Go for the most robust, complete metadata capture practical: every readily available field from the Court's official case overview listing and the PDF itself should be captured, not just a minimal set. At minimum this includes the ECLI identifier (canonical citation), the official case number (e.g. "1/2025"), the role/docket number ("rolnummer", e.g. "8115"), and the file/URL slug (e.g. "2025-001n") as three distinct, clearly labeled identifiers (they are not interchangeable and conflating them risks citation errors), plus ruling date, language, procedure type, controlled norm, outcome, subject tags/keywords, and the source PDF URL.
- Weekly automated scrape of the Court's official case overview listing and PDF publications for newly published rulings, run on the maintainer's local processing machine, with new/updated Markdown pushed from there to the public GitHub repository.
- Public GitHub repository hosting the processed Markdown as the canonical, versioned data source.
- Automated index build (GitHub Actions) combining BM25 full-text search (SQLite FTS5) and vector embeddings for hybrid lexical + semantic retrieval.
- Hosted, EU-based serverless search API (no self-hosting, no home-network exposure) that non-technical users' AI clients call to retrieve ranked passages with citations.
- A Microsoft Copilot Studio / Custom GPT integration (OpenAPI action) letting a user ask a plain-language question and get a cited answer, with zero setup on their end.
- Abuse protection on the public API via a shared static key embedded server-side in each client integration, never seen or entered by end users.
- Per-case hyperlinks back to the original official PDF on https://nl.const-court.be/ for verification.

### Should have

- An MCP server exposing the same search capability to Claude Desktop, Cursor, and VS Code Copilot users, backed by the same hosted API rather than a locally built index.
- A text-quality check on extracted rulings before publishing (e.g. flagging suspiciously broken tokens/spacing from PDF extraction) so garbled text doesn't silently degrade search results or mislead users.

### Could have

- Topic/date-range filtering in the search API, using the subject tags and article references already captured in frontmatter.
- Basic usage logging on the serverless function to detect abuse or breakage.
- French/German ruling coverage, and retrieval quality tuned for that trilingual mix, as a later-phase expansion once the Dutch-only POC is validated.

### Won't have (this version)

- Any requirement for end users to hold an API key, clone a repository, or install a CLI tool.
- Self-hosting the query API on the maintainer's own network/hardware exposed to the internet.
- Legal advice or generation beyond retrieval - the system retrieves and cites source passages; the user's own LLM (Copilot/Claude/ChatGPT) is responsible for synthesis.
- French- and German-language rulings (POC is Dutch-only).

## User workflows

### Workflow 1: Non-technical user via Microsoft Copilot / Custom GPT

1. User opens Microsoft Copilot (or a shared Custom GPT link) and asks, e.g., "What did the Constitutional Court decide about environmental permits in 2024?"
2. Copilot's declarative agent calls the hosted search API (OpenAPI action, shared key attached automatically) in the background.
3. The API returns the top-ranked passages (hybrid BM25 + vector) with case numbers, dates, and excerpts.
4. Copilot synthesizes a cited answer directly in the chat; the user never sees a terminal, API key, or file.

### Workflow 2: Technical user via MCP (Claude Desktop / Cursor / VS Code)

1. User adds the project's MCP server to their client configuration (one-time, minimal setup - no local index to build, no API key to obtain).
2. User asks a question about a ruling inside their existing AI chat.
3. The MCP server calls the same hosted search API server-side (holding the shared key itself) and returns structured results as an MCP tool response.
4. The client's LLM synthesizes a cited answer.

### Workflow 3: Weekly scrape and update of new rulings

1. On a weekly cadence, the local ingestion pipeline on the maintainer's own hardware checks https://nl.const-court.be/ for newly published rulings.
2. New PDFs are downloaded and processed through the pipeline, producing Markdown + frontmatter (including the source PDF URL) for each new case.
3. Maintainer pushes the new Markdown files to the public GitHub repository.
4. GitHub Actions rebuilds the hybrid index and publishes it to EU object storage, with no manual deployment step beyond the `git push`.

## Constraints

**Timeline**: Not yet specified - flexible.

**Budget**: €0.00/month recurring hosting cost. The maintainer's own hardware may be used for ingestion but must never be exposed to the public internet.

**Regulatory**: Data is Belgian public-sector case law. Reuse basis should be explicitly confirmed but is expected to fall under public-sector information reuse rules. EU-based hosting is preferred over US-based alternatives for data sovereignty/GDPR alignment.

**Other**:
- End users must never need an API key, GitHub account, or CLI tool.
- The maintainer is a solo developer; the system must be maintainable without a team.

