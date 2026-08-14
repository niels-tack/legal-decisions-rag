/**
 * Shared search contract - field names mirror `src/schemas.py::SearchResultItem`
 * (camelCase instead of snake_case) so a `LocalSqliteProvider` (Phase 1) and a
 * `RemoteApiProvider` (Phase 2) are interchangeable behind this one interface.
 * This is what makes the backend swap invisible to the UI, per the technical
 * requirements.
 */
export interface SearchResultItem {
  source: string;
  ecli: string;
  arrestNumber: string;
  roleNumber: string;
  caseNumber: string;
  rulingDate: string;
  language: string;
  procedureType: string;
  controlledNorm: string;
  outcome: string;
  title: string;
  section: string;
  paragraphNumber: string | null;
  /** Full-ish excerpt (response-size-capped), used for the assistant handoff prompt. */
  excerpt: string;
  /**
   * A short snippet with matched terms wrapped in ``/`` sentinel
   * markers (never raw HTML - the caller escapes the text first, then swaps
   * the escaped sentinels for `<mark>`/`</mark>`). `null` when the provider
   * doesn't support highlighting (the Phase 2 API doesn't yet) - callers
   * fall back to a plain, escaped `excerpt`.
   */
  highlightedSnippet: string | null;
  sourcePdfUrl: string;
  score: number;
}

/** Basic metadata filters - date range, procedure type, and judicial body/source. */
export interface SearchFilters {
  dateFrom?: string;
  dateTo?: string;
  procedureType?: string;
  sources?: string[];
}

/** Options available to populate the filter controls, read from the index itself. */
export interface FilterOptions {
  procedureTypes: string[];
  sources: string[];
}

/** Result ordering: relevance (the index's own ranking) or ruling date. */
export type SortOption = "relevance" | "date-desc" | "date-asc";

export interface SearchOptions {
  limit: number;
  offset: number;
  sort: SortOption;
}

/**
 * A search backend. `LocalSqliteProvider` (client-side BM25 over `cases.db`)
 * is the Phase 1 default; `RemoteApiProvider` (the hosted hybrid-search API)
 * is Phase 2's - selected by `src/search/provider.ts`, never by the UI code.
 */
export interface SearchProvider {
  search(query: string, filters: SearchFilters, options: SearchOptions): Promise<SearchResultItem[]>;
  /** Total matching results for `query`/`filters` (ignoring limit/offset) - drives pagination. */
  count(query: string, filters: SearchFilters): Promise<number>;
  listFilterOptions(): Promise<FilterOptions>;
}
