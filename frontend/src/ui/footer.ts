import { html, render } from "lit-html";

import { strings } from "../strings";

/**
 * The permanent trust strip: source attribution, a not-legal-advice
 * disclaimer, and (when the build sets it) a data-freshness line. These
 * lines are load-bearing for a legal-professional audience, not filler
 * boilerplate - they're a large part of why someone would trust the tool.
 *
 * @param container - The `<footer>` element to render into.
 */
export function renderFooter(container: HTMLElement): void {
  const builtAt = import.meta.env.VITE_BUILT_AT;
  render(
    html`
      <p>${strings.footerSourceAttribution}</p>
      <p>${strings.footerDisclaimer}</p>
      ${builtAt ? html`<p>${strings.footerBuiltAtPrefix} ${builtAt}</p>` : ""}
    `,
    container,
  );
}
