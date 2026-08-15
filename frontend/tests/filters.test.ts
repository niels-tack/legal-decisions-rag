import { describe, expect, it } from "vitest";

import { readFilters, type FilterElements } from "../src/ui/filters";

// Plain objects shaped like the input/select elements readFilters actually
// touches (just `.value`) - no real DOM needed for this pure-logic piece.
// populateFilterOptions (which does touch `document`) is covered by manual
// browser verification instead, per this project's frontend-testing scope.
function makeElements(values: Partial<Record<keyof FilterElements, string>>): FilterElements {
  return {
    dateFrom: { value: values.dateFrom ?? "" } as HTMLInputElement,
    dateTo: { value: values.dateTo ?? "" } as HTMLInputElement,
    procedureType: { value: values.procedureType ?? "" } as HTMLSelectElement,
    source: { value: values.source ?? "" } as HTMLSelectElement,
    sort: { value: values.sort ?? "relevance" } as HTMLSelectElement,
  };
}

describe("readFilters", () => {
  it("omits every field left blank", () => {
    expect(readFilters(makeElements({}))).toEqual({});
  });

  it("reads a populated date range", () => {
    const filters = readFilters(makeElements({ dateFrom: "2024-01-01", dateTo: "2024-12-31" }));

    expect(filters).toEqual({ dateFrom: "2024-01-01", dateTo: "2024-12-31" });
  });

  it("wraps a single selected source into a one-element array", () => {
    const filters = readFilters(makeElements({ source: "GHCC" }));

    expect(filters.sources).toEqual(["GHCC"]);
  });

  it("reads the procedure type filter", () => {
    const filters = readFilters(makeElements({ procedureType: "Prejudiciele vraag" }));

    expect(filters.procedureType).toBe("Prejudiciele vraag");
  });
});
