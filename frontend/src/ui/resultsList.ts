import { html, render, type TemplateResult } from "lit-html";

import { parseHighlightedSnippet } from "../search/snippetMarkers";
import type { CaseSearchResult, ChunkResult } from "../search/types";
import { strings } from "../strings";

export interface ResultsListCallbacks {
  isSelected: (index: number) => boolean;
  onToggleSelect: (index: number) => void;
}

/**
 * Build a case page URL that includes all relevant passage IDs in a `?p=`
 * query parameter and the specific chunk's paragraph as the `#hash`.
 * The case page's JS reads `?p=` to highlight and navigate between passages.
 */
function buildCaseUrl(result: CaseSearchResult, targetChunk?: ChunkResult): string {
  const base = `cases/${result.caseNumber}.html`;
  const passageIds = result.chunks
    .map((c) => c.paragraphNumber)
    .filter((id): id is string => id !== null);
  const params = passageIds.length > 0 ? `?p=${passageIds.join(",")}` : "";
  const anchor = targetChunk?.paragraphNumber;
  const hash = anchor ? `#${encodeURIComponent(anchor)}` : "";
  return `${base}${params}${hash}`;
}

/**
 * Render a chunk's excerpt with matched terms highlighted via `<mark>`.
 * Uses `parseHighlightedSnippet` to convert sentinel markers to real markup;
 * falls back to the plain excerpt when no highlighted snippet is available.
 */
function renderExcerpt(chunk: ChunkResult): TemplateResult {
  if (!chunk.highlightedSnippet) {
    return html`${chunk.excerpt}`;
  }
  const segments = parseHighlightedSnippet(chunk.highlightedSnippet);
  return html`${segments.map((segment) =>
    segment.matched ? html`<mark>${segment.text}</mark>` : segment.text,
  )}`;
}

/**
 * Render one matched chunk as a sub-row within a case card. The
 * paragraph/section label is a direct anchor link to the relevant passage in
 * the case markdown view; clicking it opens `cases/{caseNumber}.html#{anchor}`.
 */
function renderChunkRow(chunk: ChunkResult, result: CaseSearchResult): TemplateResult {
  const url = buildCaseUrl(result, chunk);
  return html`
    <li class="result-chunk">
      <a class="result-badge result-badge--paragraph" href=${url}>${chunk.paragraphNumber ?? chunk.section}</a>
      <p class="result-excerpt">${renderExcerpt(chunk)}</p>
    </li>
  `;
}

function renderResultCard(
  result: CaseSearchResult,
  index: number,
  callbacks: ResultsListCallbacks,
): TemplateResult {
  const url = buildCaseUrl(result, result.chunks[0]);

  return html`
    <li class="result-card">
      <div class="result-select">
        <label>
          <input
            type="checkbox"
            .checked=${callbacks.isSelected(index)}
            @change=${() => callbacks.onToggleSelect(index)}
          />
          ${strings.resultSelectLabel}
        </label>
      </div>
      <h2 class="result-title"><a href=${url}>${result.title}</a></h2>
      <div class="result-identifiers">
        <strong>${result.rulingDate}</strong> · ${result.ecli} · arrest ${result.arrestNumber}
      </div>
      <div class="result-badges">
        <span class="result-badge result-badge--outcome">${result.outcome}</span>
        <span class="result-badge">${result.procedureType}</span>
      </div>
      <ul class="result-chunks">
        ${result.chunks.map((chunk) => renderChunkRow(chunk, result))}
      </ul>
      <div class="result-links">
        <a href=${result.sourcePdfUrl} target="_blank" rel="noopener noreferrer">${strings.resultOpenPdf}</a>
      </div>
    </li>
  `;
}

/**
 * Render the ranked case results list: each card shows the case header and
 * its top matching chunks. The first chunk's paragraph anchor drives the
 * deep-link on the case title.
 *
 * @param container - The `<ul>` element to render results into.
 * @param results - Ranked cases, in the order to display.
 * @param callbacks - Selection state (for the assistant handoff) read/write hooks.
 */
export function renderResults(
  container: HTMLElement,
  results: CaseSearchResult[],
  callbacks: ResultsListCallbacks,
): void {
  render(
    html`${results.map((result, index) => renderResultCard(result, index, callbacks))}`,
    container,
  );
}
