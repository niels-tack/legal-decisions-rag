import { html, render, type TemplateResult } from "lit-html";

import { parseHighlightedSnippet } from "../search/snippetMarkers";
import type { SearchResultItem } from "../search/types";
import { strings } from "../strings";

export interface ResultsListCallbacks {
  isSelected: (index: number) => boolean;
  onToggleSelect: (index: number) => void;
}

function casePageUrl(result: SearchResultItem): string {
  const base = `cases/${result.caseNumber}.html`;
  return result.paragraphNumber ? `${base}#${encodeURIComponent(result.paragraphNumber)}` : base;
}

/**
 * Render a snippet's matched terms as `<mark>` - via `parseHighlightedSnippet`,
 * never by treating the raw snippet as HTML. lit-html escapes every
 * interpolated string by default, so only the sentinel-delimited segments
 * flagged `matched` become real `<mark>` elements; everything else renders
 * as plain, safely-escaped text.
 */
function renderExcerpt(result: SearchResultItem): TemplateResult {
  if (!result.highlightedSnippet) {
    return html`${result.excerpt}`;
  }
  const segments = parseHighlightedSnippet(result.highlightedSnippet);
  return html`${segments.map((segment) =>
    segment.matched ? html`<mark>${segment.text}</mark>` : segment.text,
  )}`;
}

function renderResultCard(
  result: SearchResultItem,
  index: number,
  callbacks: ResultsListCallbacks,
): TemplateResult {
  const url = casePageUrl(result);

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
        <span class="result-badge result-badge--paragraph">${result.paragraphNumber ?? result.section}</span>
      </div>
      <p class="result-excerpt">${renderExcerpt(result)}</p>
      <div class="result-links">
        <a href=${url}>${strings.resultOpenCase}</a>
        <a href=${result.sourcePdfUrl} target="_blank" rel="noopener noreferrer">${strings.resultOpenPdf}</a>
      </div>
    </li>
  `;
}

/**
 * Render the ranked results list: each card links to the per-case page
 * (deep-linked to the exact paragraph anchor when the chunk has a paragraph
 * number - see `src/site/build_site.py`), and to the original PDF for
 * verification, per the functional requirements.
 *
 * @param container - The `<ul>` element to render results into.
 * @param results - Ranked results, in the order to display.
 * @param callbacks - Selection state (for the assistant handoff) read/write hooks.
 */
export function renderResults(
  container: HTMLElement,
  results: SearchResultItem[],
  callbacks: ResultsListCallbacks,
): void {
  render(
    html`${results.map((result, index) => renderResultCard(result, index, callbacks))}`,
    container,
  );
}
