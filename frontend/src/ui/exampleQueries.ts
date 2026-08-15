import { html, render } from "lit-html";

import { strings } from "../strings";

export interface ExampleQuery {
  label: string;
  query: string;
}

/**
 * Clickable example queries on the landing state. These do double duty per
 * the UX assessment this build follows: they teach first-time visitors what
 * kind of question works (BM25 rewards legal terminology and exact
 * identifiers over layperson phrasing), and they give an instant success
 * moment instead of a blank search box.
 *
 * @param container - Element to render the example buttons into.
 * @param examples - The example queries to offer.
 * @param onSelect - Called with an example's query text when clicked.
 */
export function renderExampleQueries(
  container: HTMLElement,
  examples: ExampleQuery[],
  onSelect: (query: string) => void,
): void {
  render(
    html`
      <span class="example-queries-label">${strings.exampleQueriesLabel}</span>
      ${examples.map(
        (example) => html`
          <button type="button" class="example-query" @click=${() => onSelect(example.query)}>
            ${example.label}
          </button>
        `,
      )}
    `,
    container,
  );
}
