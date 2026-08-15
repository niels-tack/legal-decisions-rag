import type { SearchFilters, SortOption } from "./search/types";

const DEFAULT_SORT: SortOption = "relevance";
const DEFAULT_PAGE = 1;
const VALID_SORTS: readonly SortOption[] = ["relevance", "date-desc", "date-asc"];

/**
 * Everything that makes a search reproducible: query, filters, sort, and
 * page. Lawyers share links - to colleagues, in memos, in footnotes - so all
 * of this lives in the URL, not just in memory. This is deliberately *not*
 * where result-selection state (which passages a user ticked for the
 * handoff prompt) lives - that's a transient, in-page curation step, not
 * something a shared link should reproduce.
 */
export interface SearchUrlState {
  query: string;
  filters: SearchFilters;
  sort: SortOption;
  page: number;
}

function isValidSort(value: string | null): value is SortOption {
  return value !== null && (VALID_SORTS as string[]).includes(value);
}

/**
 * Parse a `SearchUrlState` out of URL query parameters.
 *
 * Pure function (no `window` access) so it's directly unit-testable; see
 * `readUrlState` for the wrapper that reads the real address bar.
 *
 * @param params - The URL's query string parameters.
 * @returns The parsed state, defaulting to an empty query, no filters,
 *   relevance sort, and page 1 for anything absent or malformed.
 */
export function parseUrlState(params: URLSearchParams): SearchUrlState {
  const filters: SearchFilters = {};
  const dateFrom = params.get("dateFrom");
  const dateTo = params.get("dateTo");
  const procedureType = params.get("procedureType");
  const sources = params.getAll("sources");

  if (dateFrom) filters.dateFrom = dateFrom;
  if (dateTo) filters.dateTo = dateTo;
  if (procedureType) filters.procedureType = procedureType;
  if (sources.length > 0) filters.sources = sources;

  const sortParam = params.get("sort");
  const pageParam = Number.parseInt(params.get("page") ?? "", 10);

  return {
    query: params.get("q") ?? "",
    filters,
    sort: isValidSort(sortParam) ? sortParam : DEFAULT_SORT,
    page: Number.isInteger(pageParam) && pageParam > 0 ? pageParam : DEFAULT_PAGE,
  };
}

/**
 * Build URL query parameters from a `SearchUrlState`, inverse of
 * `parseUrlState`. Fields at their default value are omitted so the URL
 * stays short for the common case (a plain query, no filters, page 1).
 *
 * @param state - The state to encode.
 * @returns The equivalent `URLSearchParams`.
 */
export function buildUrlParams(state: SearchUrlState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.filters.dateFrom) params.set("dateFrom", state.filters.dateFrom);
  if (state.filters.dateTo) params.set("dateTo", state.filters.dateTo);
  if (state.filters.procedureType) params.set("procedureType", state.filters.procedureType);
  for (const source of state.filters.sources ?? []) {
    params.append("sources", source);
  }
  if (state.sort !== DEFAULT_SORT) params.set("sort", state.sort);
  if (state.page !== DEFAULT_PAGE) params.set("page", String(state.page));
  return params;
}

/** Read the current `SearchUrlState` from the browser's address bar. */
export function readUrlState(): SearchUrlState {
  return parseUrlState(new URLSearchParams(window.location.search));
}

/**
 * Write `state` to the address bar.
 *
 * @param state - The state to encode into the URL.
 * @param mode - `"push"` (default) adds a history entry, so browser
 *   back/forward moves through prior searches - use for a new search.
 *   `"replace"` updates in place without a new entry - use for the initial
 *   load (parsing a shared link shouldn't itself become a back-button stop).
 */
export function writeUrlState(state: SearchUrlState, mode: "push" | "replace" = "push"): void {
  const params = buildUrlParams(state);
  const url = params.toString() ? `?${params.toString()}` : window.location.pathname;
  if (mode === "push") {
    window.history.pushState(state, "", url);
  } else {
    window.history.replaceState(state, "", url);
  }
}
