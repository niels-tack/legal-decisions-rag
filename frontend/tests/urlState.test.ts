import { describe, expect, it } from "vitest";

import { buildUrlParams, parseUrlState, type SearchUrlState } from "../src/urlState";

describe("parseUrlState", () => {
  it("defaults to an empty query, no filters, relevance sort, page 1", () => {
    expect(parseUrlState(new URLSearchParams(""))).toEqual({
      query: "",
      filters: {},
      sort: "relevance",
      page: 1,
    });
  });

  it("reads query, date range, procedure type, and repeated sources", () => {
    const params = new URLSearchParams(
      "q=omgevingsvergunning&dateFrom=2024-01-01&dateTo=2024-12-31&procedureType=Beroep&sources=GHCC&sources=OTHER",
    );

    expect(parseUrlState(params)).toEqual({
      query: "omgevingsvergunning",
      filters: {
        dateFrom: "2024-01-01",
        dateTo: "2024-12-31",
        procedureType: "Beroep",
        sources: ["GHCC", "OTHER"],
      },
      sort: "relevance",
      page: 1,
    });
  });

  it("falls back to relevance for an unrecognized sort value", () => {
    expect(parseUrlState(new URLSearchParams("sort=alphabetical")).sort).toBe("relevance");
  });

  it("accepts a valid sort value", () => {
    expect(parseUrlState(new URLSearchParams("sort=date-desc")).sort).toBe("date-desc");
  });

  it("falls back to page 1 for a non-positive or non-numeric page", () => {
    expect(parseUrlState(new URLSearchParams("page=0")).page).toBe(1);
    expect(parseUrlState(new URLSearchParams("page=abc")).page).toBe(1);
  });

  it("reads a valid page number", () => {
    expect(parseUrlState(new URLSearchParams("page=3")).page).toBe(3);
  });
});

describe("buildUrlParams", () => {
  it("omits every field at its default value", () => {
    const state: SearchUrlState = { query: "", filters: {}, sort: "relevance", page: 1 };

    expect(buildUrlParams(state).toString()).toBe("");
  });

  it("round-trips through parseUrlState", () => {
    const state: SearchUrlState = {
      query: "milieu",
      filters: { dateFrom: "2024-01-01", sources: ["GHCC", "OTHER"] },
      sort: "date-asc",
      page: 2,
    };

    const roundTripped = parseUrlState(buildUrlParams(state));

    expect(roundTripped).toEqual(state);
  });
});
