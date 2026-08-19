# Functional requirements: legal-decisions-rag

> **Single source of truth for project scope and requirements**
>
> This document defines what the project should do and for whom. Update this as requirements evolve.
> AI coding assistants will reference this to ensure code aligns with project goals.

## Problem statement

Belgian Constitutional Court rulings are only available as scattered PDF documents on the Court's own website (https://nl.const-court.be/), with no way for non-technical legal professionals or citizens to search across them semantically or ask natural-language questions and get cited passages back. Target users operate in locked-down Microsoft corporate environments where installing software (`.exe`), side-loading browser extensions, or purchasing custom enterprise Copilot licenses is blocked by corporate IT. Existing local RAG tools require CLI installs and API keys. Without a zero-install, zero-cost, browser-native way to query this case law conversationally, valuable constitutional jurisprudence stays effectively undiscoverable.

## Target users

**Primary Users**: Non-technical legal professionals (lawyers, paralegals, policy staff, journalists) working on locked-down corporate Windows PCs who use Microsoft Edge, Copilot, or ChatGPT day-to-day and want to search and query Belgian Constitutional Court rulings without installing software, requesting IT approvals, or managing API keys.

**Secondary Users**: The maintainer (solo, technical), who processes PDFs into Markdown, runs the ingestion pipeline on personal hardware, and keeps the public GitHub repository and static index current.

## Success criteria

- Non-technical users can perform instant searches over Constitutional Court rulings and transfer retrieved legal contexts directly into Microsoft Copilot or ChatGPT with 1 click—zero installs, zero administrative rights, zero paid Copilot subscriptions, and zero API keys.
- Recurring hosting cost stays strictly at €0.00/month (hosted on GitHub Pages).
- The web search tool can be installed as an Edge Progressive Web App (PWA) onto the user's desktop taskbar in 1 click.
- The maintainer's home network/hardware is never exposed to the public internet.
- Every answer traces back to a verifiable ECLI identifier (e.g. `ECLI:BE:GHCC:2025:ARR.001`), official case number, ruling date, and a direct hyperlink to the official PDF on the Court's website. Initial (POC) scope is Dutch-language rulings only.

## Core requirements

### Must have (MVP)

- Local ingestion pipeline (offline on maintainer's hardware), initially Dutch-language rulings only, converting PDF rulings into structured Markdown with YAML frontmatter capturing ECLI identifier, official case number, role/docket number ("rolnummer"), URL slug, ruling date, language, procedure type, controlled norm, outcome, subject keywords, and source PDF URL.
- Weekly automated scrape of the Court's official case overview listing for newly published rulings, pushing updated Markdown to GitHub.
- Public GitHub repository hosting Markdown files as the canonical source.
- GitHub Actions CI workflow compiling static client-side search indices (Pagefind/Orama) and building Progressive Web App (PWA) static web assets deployed to GitHub Pages.
- Web search interface accessible via Microsoft Edge featuring instant client-side full-text search across ruling passages and metadata.
- PWA Manifest and Service Worker support allowing users to click "Install site as app" in Microsoft Edge for desktop taskbar integration.
- Deep-Link Prompt Generator button (`[ 🚀 Ask Microsoft Copilot ]` / `[ 💬 Ask ChatGPT ]`) that formats matching legal excerpts into a structured prompt payload and opens the user's preferred AI tool in a new tab with the prompt pre-filled.
- Direct per-case hyperlinks back to official PDFs on https://nl.const-court.be/.

### Should have

- Edge Sidebar Optimization: Layout and CSS formatted to run seamlessly when pinned as a narrow sidebar panel inside Microsoft Edge (`Alt + C` side-by-side workflow).
- Text-quality validation check during local ingestion to flag PDF extraction artifacts or garbled text before publishing.
- One-click "Copy Prompt Payload" fallback button for manual pasting into Edge Copilot sidebar.

### Could have

- Topic/date-range filtering in the client-side search UI using subject tags and article references captured in frontmatter.
- French/German ruling coverage as a later-phase expansion once the Dutch-only POC is validated.

### Won't have (this version)

- Backend HTTP serverless container APIs or hosted databases.
- Required browser extensions or local CLI software installations.
- Required paid Microsoft Copilot Studio licenses or enterprise tenant admin permissions.
- Legal advice generation - the system presents source passages and constructs grounded prompts; the user's own LLM performs synthesis.
- French and German rulings (POC is Dutch-only).

## User workflows

### Workflow 1: Non-technical user via Edge PWA & Deep-Link Handoff

1. User opens the "Constitutional Court Search" PWA app from their Windows Taskbar or Edge browser.
2. User types a topic or case number (e.g. "environmental permits 2024").
3. Client-side search engine returns top-ranked case passages instantly (<100ms).
4. User clicks **`[ 🚀 Ask Microsoft Copilot ]`**.
5. Microsoft Edge opens Copilot in a new tab with a fully constructed prompt (including retrieved case passages, ECLI citations, and user question) pre-filled in the prompt box.
6. User hits Enter to receive a synthesized, cited response.

### Workflow 2: Edge Sidebar Pinning Workflow

1. User visits the web portal in Microsoft Edge, right-clicks the tab, and selects "Pin to sidebar".
2. User opens the Edge Copilot sidebar (`Alt + C`) alongside the pinned search panel.
3. User searches cases in the pinned sidebar, clicks "Copy Prompt Payload", and pastes it directly into the adjacent Copilot sidebar chat.

### Workflow 3: Weekly scrape and index deployment

1. Maintainer's local pipeline checks https://nl.const-court.be/ for new rulings weekly.
2. New PDFs are processed into Markdown + YAML frontmatter.
3. Maintainer pushes new Markdown files to GitHub `main` branch.
4. GitHub Actions builds static Pagefind/Orama indices and deploys updated PWA assets to GitHub Pages automatically.

## Constraints

**Timeline**: Flexible.

**Budget**: €0.00/month recurring hosting cost (GitHub Pages). Maintainer hardware outbound-only.

**Regulatory**: Public-sector case law under open reuse rules.

**Other**:
- Zero software installations, zero extension approvals, zero paid AI subscriptions required from end users.
- Maintained completely by a solo developer.
