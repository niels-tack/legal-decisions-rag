/**
 * Sentinel control characters U+0001 (SOH) and U+0002 (STX) - never
 * occur in ordinary extracted-ruling text - marking the start/end of a
 * matched term inside a `LocalSqliteProvider` highlighted snippet (via
 * SQLite FTS5's `snippet()`). Shared between the provider (which asks
 * FTS5 to wrap matches in these) and the results UI (which escapes the
 * whole snippet as plain text, then swaps the escaped sentinels for real
 * `<mark>`/`</mark>` tags) - see SearchResultItem.highlightedSnippet's
 * docstring in ./types for why raw HTML markers from FTS5 would be unsafe
 * to use directly.
 *
 * These are literal control bytes in this source file, which is valid,
 * unambiguous TypeScript - do not run a tool over this file that might
 * normalize/strip control characters.
 */
export const SNIPPET_MATCH_START = "";
export const SNIPPET_MATCH_END = "";

export interface SnippetSegment {
  text: string;
  matched: boolean;
}

/**
 * Split a raw `highlightedSnippet` string into plain/matched segments.
 *
 * Pure and DOM-free so it's directly unit-testable; `ui/resultsList.ts`
 * maps the result into escaped, `<mark>`-wrapped lit-html templates - never
 * treating the raw snippet text itself as HTML.
 *
 * @param snippet - The raw snippet, containing SNIPPET_MATCH_START/END pairs
 *   around each matched term.
 * @returns Segments in order; `matched` marks text that fell between one
 *   START/END pair. A missing END for a given START degrades to treating the
 *   remainder as unmatched plain text, rather than dropping it.
 */
export function parseHighlightedSnippet(snippet: string): SnippetSegment[] {
  const segments: SnippetSegment[] = [];
  let remaining = snippet;

  while (remaining.length > 0) {
    const startIndex = remaining.indexOf(SNIPPET_MATCH_START);
    if (startIndex === -1) {
      segments.push({ text: remaining, matched: false });
      break;
    }
    if (startIndex > 0) {
      segments.push({ text: remaining.slice(0, startIndex), matched: false });
    }

    const afterStart = remaining.slice(startIndex + SNIPPET_MATCH_START.length);
    const endIndex = afterStart.indexOf(SNIPPET_MATCH_END);
    if (endIndex === -1) {
      segments.push({ text: afterStart, matched: false });
      break;
    }

    segments.push({ text: afterStart.slice(0, endIndex), matched: true });
    remaining = afterStart.slice(endIndex + SNIPPET_MATCH_END.length);
  }

  return segments;
}
