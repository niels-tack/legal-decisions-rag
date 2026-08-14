/**
 * Response-size cap for excerpts, matching
 * `src/query_service/search.py::_MAX_EXCERPT_CHARS` for contract parity: a
 * whole-section fallback chunk (no paragraph numbering) can run to tens of
 * thousands of characters, which a result card should never render in full.
 */
const MAX_EXCERPT_CHARS = 2000;

/**
 * Cap a chunk's text at `MAX_EXCERPT_CHARS` for display.
 *
 * @param text - The full chunk text.
 * @returns `text` unchanged if short enough, otherwise truncated with a
 *   trailing ellipsis.
 */
export function truncateExcerpt(text: string): string {
  if (text.length <= MAX_EXCERPT_CHARS) {
    return text;
  }
  return `${text.slice(0, MAX_EXCERPT_CHARS).trimEnd()}…`;
}
