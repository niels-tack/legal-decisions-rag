/**
 * Turn free-form user text into a safe FTS5 `MATCH` expression.
 *
 * Ports `src/query_service/search.py::_build_fts_match_query` 1:1: each
 * whitespace-separated token is quoted individually and any literal double
 * quote inside a token is escaped by doubling it, then the quoted tokens are
 * joined with `OR`. This treats the query as a bag of literal terms rather
 * than passing it through FTS5's own query syntax, so characters like `-` or
 * unbalanced quotes in arbitrary user input can't raise an FTS5 syntax error.
 *
 * @param queryText - The raw user search string.
 * @returns An FTS5 `MATCH` expression, or an empty string if `queryText` has
 *   no whitespace-separated tokens.
 */
export function buildFtsMatchQuery(queryText: string): string {
  const tokens = queryText.split(/\s+/).filter((token) => token.length > 0);
  const quoted = tokens.map((token) => `"${token.replaceAll('"', '""')}"`);
  return quoted.join(" OR ");
}
