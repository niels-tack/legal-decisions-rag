import { composePrompt } from "./promptComposer";
import { createSearchProvider } from "./search/provider";
import type { CaseSearchResult, SortOption } from "./search/types";
import { strings } from "./strings";
import {
  applyUrlStateToForm,
  populateFilterOptions,
  populateSortOptions,
  readFilters,
  readSort,
  type FilterElements,
} from "./ui/filters";
import { renderExampleQueries, type ExampleQuery } from "./ui/exampleQueries";
import { renderFooter } from "./ui/footer";
import { renderPagination } from "./ui/pagination";
import { renderResults } from "./ui/resultsList";
import { setStatus } from "./ui/status";
import { readUrlState, writeUrlState, type SearchUrlState } from "./urlState";

const PAGE_SIZE = 10;
const PROMPT_MAX_RESULTS = 10;
const DEFAULT_SELECTION_COUNT = 5;

// Real terms/identifiers that work against the current dev fixture corpus
// (tests/indexing/fixtures, via `just frontend-dev-data`), so the example
// queries give a genuine working demo end to end rather than a placeholder
// that 404s until real corpus data lands. Swap these for representative
// real-corpus queries once that data is live.
const EXAMPLE_QUERIES: ExampleQuery[] = [
  { label: "discriminatie leeftijd", query: "discriminatie leeftijd" },
  { label: "gelijkheidsbeginsel", query: "gelijkheidsbeginsel" },
  { label: "strafuitvoering", query: "strafuitvoering" },
  { label: "arrest 1/2025", query: "1/2025" },
];

function requireElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`Missing required element #${id}`);
  }
  return element as T;
}

function applyStaticStrings(elements: {
  heading: HTMLElement;
  privacyNote: HTMLElement;
  queryInput: HTMLInputElement;
  searchButton: HTMLButtonElement;
  queryGuidance: HTMLElement;
  filtersLegend: HTMLElement;
  labelDateFrom: HTMLElement;
  labelDateTo: HTMLElement;
  labelProcedureType: HTMLElement;
  labelSource: HTMLElement;
  labelSort: HTMLElement;
  filterProcedureType: HTMLSelectElement;
  filterSource: HTMLSelectElement;
  copyPromptButton: HTMLButtonElement;
}): void {
  document.title = strings.pageTitle;
  elements.heading.textContent = strings.heading;
  elements.privacyNote.textContent = strings.privacyNote;
  elements.queryInput.placeholder = strings.searchPlaceholder;
  elements.searchButton.textContent = strings.searchButton;
  elements.queryGuidance.textContent = strings.queryGuidance;
  elements.filtersLegend.textContent = strings.filtersLegend;
  elements.labelDateFrom.textContent = strings.filterDateFrom;
  elements.labelDateTo.textContent = strings.filterDateTo;
  elements.labelProcedureType.textContent = strings.filterProcedureType;
  elements.labelSource.textContent = strings.filterSource;
  elements.labelSort.textContent = strings.sortLabel;
  elements.copyPromptButton.textContent = strings.handoffCopyButton;

  for (const select of [elements.filterProcedureType, elements.filterSource]) {
    const allOption = document.createElement("option");
    allOption.value = "";
    allOption.textContent = strings.filterAllOption;
    select.append(allOption);
  }
}

async function main(): Promise<void> {
  const heading = requireElement<HTMLHeadingElement>("heading");
  const privacyNote = requireElement<HTMLParagraphElement>("privacy-note");
  const form = requireElement<HTMLFormElement>("search-form");
  const queryInput = requireElement<HTMLInputElement>("query-input");
  const searchButton = requireElement<HTMLButtonElement>("search-button");
  const queryGuidance = requireElement<HTMLElement>("query-guidance");
  const exampleQueriesEl = requireElement<HTMLDivElement>("example-queries");
  const filtersLegend = requireElement<HTMLElement>("filters-legend");
  const labelDateFrom = requireElement<HTMLElement>("label-date-from");
  const labelDateTo = requireElement<HTMLElement>("label-date-to");
  const labelProcedureType = requireElement<HTMLElement>("label-procedure-type");
  const labelSource = requireElement<HTMLElement>("label-source");
  const labelSort = requireElement<HTMLElement>("label-sort");
  const statusEl = requireElement<HTMLParagraphElement>("status");
  const resultsList = requireElement<HTMLUListElement>("results-list");
  const paginationEl = requireElement<HTMLElement>("pagination");
  const handoff = requireElement<HTMLDivElement>("handoff");
  const copyButton = requireElement<HTMLButtonElement>("copy-prompt-button");
  const copyFeedback = requireElement<HTMLSpanElement>("copy-feedback");
  const footerEl = requireElement<HTMLElement>("trust-footer");

  const filterElements: FilterElements = {
    dateFrom: requireElement<HTMLInputElement>("filter-date-from"),
    dateTo: requireElement<HTMLInputElement>("filter-date-to"),
    procedureType: requireElement<HTMLSelectElement>("filter-procedure-type"),
    source: requireElement<HTMLSelectElement>("filter-source"),
    sort: requireElement<HTMLSelectElement>("filter-sort"),
  };

  applyStaticStrings({
    heading,
    privacyNote,
    queryInput,
    searchButton,
    queryGuidance,
    filtersLegend,
    labelDateFrom,
    labelDateTo,
    labelProcedureType,
    labelSource,
    labelSort,
    filterProcedureType: filterElements.procedureType,
    filterSource: filterElements.source,
    copyPromptButton: copyButton,
  });
  populateSortOptions(filterElements.sort);
  renderFooter(footerEl);
  renderExampleQueries(exampleQueriesEl, EXAMPLE_QUERIES, (query) => {
    queryInput.value = query;
    form.requestSubmit();
  });

  const provider = createSearchProvider();

  let currentResults: CaseSearchResult[] = [];
  const selectedIndices = new Set<number>();

  function resetSelection(resultCount: number): void {
    selectedIndices.clear();
    for (let i = 0; i < Math.min(DEFAULT_SELECTION_COUNT, resultCount); i++) {
      selectedIndices.add(i);
    }
  }

  function renderCurrentResults(): void {
    renderResults(resultsList, currentResults, {
      isSelected: (index) => selectedIndices.has(index),
      onToggleSelect: (index) => {
        if (selectedIndices.has(index)) {
          selectedIndices.delete(index);
        } else {
          selectedIndices.add(index);
        }
      },
    });
  }

  async function runSearch(state: SearchUrlState): Promise<void> {
    if (!state.query.trim()) {
      currentResults = [];
      resultsList.replaceChildren();
      renderPagination(paginationEl, 1, 1, () => {});
      handoff.hidden = true;
      setStatus(statusEl, "");
      return;
    }

    setStatus(statusEl, strings.statusSearching);
    handoff.hidden = true;

    try {
      const offset = (state.page - 1) * PAGE_SIZE;
      const [results, total] = await Promise.all([
        provider.search(state.query, state.filters, {
          limit: PAGE_SIZE,
          offset,
          sort: state.sort,
        }),
        provider.count(state.query, state.filters),
      ]);

      currentResults = results;
      resetSelection(results.length);
      renderCurrentResults();

      const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
      renderPagination(paginationEl, state.page, totalPages, (page) => {
        writeUrlState({ ...state, page });
        void runSearch({ ...state, page });
      });

      handoff.hidden = results.length === 0;
      setStatus(statusEl, results.length > 0 ? strings.statusResultsCount(total) : strings.statusNoResults);
    } catch (error) {
      console.error(error);
      setStatus(statusEl, strings.statusSearchFailed);
    }
  }

  function currentFormState(page: number): SearchUrlState {
    return {
      query: queryInput.value.trim(),
      filters: readFilters(filterElements),
      sort: readSort(filterElements.sort) as SortOption,
      page,
    };
  }

  setStatus(statusEl, strings.statusLoadingIndex);
  try {
    const filterOptions = await provider.listFilterOptions();
    populateFilterOptions(filterElements, filterOptions);
    setStatus(statusEl, "");
  } catch (error) {
    console.error(error);
    setStatus(statusEl, strings.statusLoadIndexFailed);
    return;
  }

  const initialState = readUrlState();
  applyUrlStateToForm(queryInput, filterElements, initialState);
  if (initialState.query) {
    await runSearch(initialState);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const state = currentFormState(1);
    writeUrlState(state);
    void runSearch(state);
  });

  filterElements.sort.addEventListener("change", () => {
    if (!queryInput.value.trim()) return;
    const state = currentFormState(1);
    writeUrlState(state);
    void runSearch(state);
  });

  window.addEventListener("popstate", () => {
    const state = readUrlState();
    applyUrlStateToForm(queryInput, filterElements, state);
    void runSearch(state);
  });

  copyButton.addEventListener("click", () => {
    const selected = [...selectedIndices].sort((a, b) => a - b).map((i) => currentResults[i]!);
    if (selected.length === 0) {
      copyFeedback.textContent = strings.handoffNoneSelected;
      return;
    }
    const prompt = composePrompt(queryInput.value.trim(), selected, PROMPT_MAX_RESULTS);
    navigator.clipboard
      .writeText(prompt)
      .then(() => {
        copyFeedback.textContent = strings.handoffCopySuccess;
      })
      .catch((error: unknown) => {
        console.error(error);
        copyFeedback.textContent = strings.handoffCopyFailure;
      });
  });
}

main().catch((error: unknown) => {
  console.error(error);
});
