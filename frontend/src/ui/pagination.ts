import { html, render } from "lit-html";

import { strings } from "../strings";

/**
 * Render pagination controls, or clear them entirely when there's only one
 * page - "page" is part of the URL-encoded search state (see
 * `src/urlState.ts`) alongside query/filters/sort.
 *
 * @param container - Element to render the controls into.
 * @param page - The current 1-based page number.
 * @param totalPages - Total number of pages for the current search.
 * @param onPageChange - Called with the newly requested page number.
 */
export function renderPagination(
  container: HTMLElement,
  page: number,
  totalPages: number,
  onPageChange: (page: number) => void,
): void {
  if (totalPages <= 1) {
    render(html``, container);
    return;
  }

  render(
    html`
      <button type="button" ?disabled=${page <= 1} @click=${() => onPageChange(page - 1)}>
        ${strings.paginationPrevious}
      </button>
      <span>${strings.paginationPageOf(page, totalPages)}</span>
      <button type="button" ?disabled=${page >= totalPages} @click=${() => onPageChange(page + 1)}>
        ${strings.paginationNext}
      </button>
    `,
    container,
  );
}
