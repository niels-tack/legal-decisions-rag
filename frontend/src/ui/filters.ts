import type { SearchFilters, SortOption } from "../search/types";
import { strings } from "../strings";
import type { SearchUrlState } from "../urlState";

export interface FilterElements {
  dateFrom: HTMLInputElement;
  dateTo: HTMLInputElement;
  procedureType: HTMLSelectElement;
  source: HTMLSelectElement;
  sort: HTMLSelectElement;
}

const SORT_OPTIONS: { value: SortOption; label: () => string }[] = [
  { value: "relevance", label: () => strings.sortByRelevance },
  { value: "date-desc", label: () => strings.sortByDateNewest },
  { value: "date-asc", label: () => strings.sortByDateOldest },
];

/** Populate the always-present sort options (unlike procedure type/source, these don't depend on the index). */
export function populateSortOptions(sortSelect: HTMLSelectElement): void {
  for (const { value, label } of SORT_OPTIONS) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label();
    sortSelect.append(option);
  }
}

/**
 * Populate the procedure-type and source `<select>` options from whatever
 * is actually indexed (`FilterOptions`, read from `cases.db` itself). With
 * only the Constitutional Court onboarded, the source select ends up with
 * one real option below "Alle" (all) - harmless, and already wired for a
 * second body's rulings to show up with no UI change, per the functional
 * requirements.
 *
 * @param elements - The filter form's input/select elements.
 * @param options - Distinct procedure types and sources found in the index.
 */
export function populateFilterOptions(
  elements: Pick<FilterElements, "procedureType" | "source">,
  options: { procedureTypes: string[]; sources: string[] },
): void {
  for (const procedureType of options.procedureTypes) {
    const option = document.createElement("option");
    option.value = procedureType;
    option.textContent = procedureType;
    elements.procedureType.append(option);
  }
  for (const source of options.sources) {
    const option = document.createElement("option");
    option.value = source;
    option.textContent = source;
    elements.source.append(option);
  }
}

/**
 * Read the filter form's current values into a `SearchFilters` object.
 *
 * @param elements - The filter form's input/select elements.
 * @returns The current filter selection, omitting any field left blank.
 */
export function readFilters(elements: FilterElements): SearchFilters {
  const filters: SearchFilters = {};
  if (elements.dateFrom.value) {
    filters.dateFrom = elements.dateFrom.value;
  }
  if (elements.dateTo.value) {
    filters.dateTo = elements.dateTo.value;
  }
  if (elements.procedureType.value) {
    filters.procedureType = elements.procedureType.value;
  }
  if (elements.source.value) {
    filters.sources = [elements.source.value];
  }
  return filters;
}

/** Read the sort control's current value. */
export function readSort(sortSelect: HTMLSelectElement): SortOption {
  return (sortSelect.value || "relevance") as SortOption;
}

/**
 * Populate the form (query, filters, sort) from a `SearchUrlState` - used
 * on initial load (a shared/bookmarked link) and on browser back/forward,
 * so the visible controls always match what's about to be (re-)searched.
 *
 * @param queryInput - The search query input.
 * @param elements - The filter form's input/select elements.
 * @param state - The state to apply.
 */
export function applyUrlStateToForm(
  queryInput: HTMLInputElement,
  elements: FilterElements,
  state: SearchUrlState,
): void {
  queryInput.value = state.query;
  elements.dateFrom.value = state.filters.dateFrom ?? "";
  elements.dateTo.value = state.filters.dateTo ?? "";
  elements.procedureType.value = state.filters.procedureType ?? "";
  elements.source.value = state.filters.sources?.[0] ?? "";
  elements.sort.value = state.sort;
}
