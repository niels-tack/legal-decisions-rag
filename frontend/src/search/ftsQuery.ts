/**
 * Turn free-form user text into a safe FTS5 `MATCH` expression.
 *
 * Ports `src/query_service/search.py::_build_fts_match_query` 1:1: each
 * whitespace-separated token is quoted individually and any literal double
 * quote inside a token is escaped by doubling it, then the quoted tokens are
 * joined with implicit AND (space-separated, no operator keyword). FTS5
 * treats adjacent quoted terms as AND by default, so all terms must appear
 * in a matching chunk - matching legal search industry practice (EUR-Lex,
 * Hudoc, Caselaw.nl all default to AND). The quoting still prevents FTS5
 * syntax errors from characters like `-` or unbalanced quotes.
 *
 * @param queryText - The raw user search string.
 * @returns An FTS5 `MATCH` expression, or an empty string if `queryText` has
 *   no whitespace-separated tokens.
 */
export function buildFtsMatchQuery(queryText: string): string {
  const tokens = queryText.split(/\s+/).filter((token) => token.length > 0);
  const quoted = tokens.map((token) => `"${token.replaceAll('"', '""')}"`);
  return quoted.join(" ");
}
