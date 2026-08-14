import { describe, expect, it } from "vitest";

import { buildFtsMatchQuery } from "../src/search/ftsQuery";

describe("buildFtsMatchQuery", () => {
  it("quotes and joins tokens with OR", () => {
    expect(buildFtsMatchQuery("milieu vergunning")).toBe('"milieu" OR "vergunning"');
  });

  it("escapes an embedded double quote by doubling it", () => {
    expect(buildFtsMatchQuery('foo"bar')).toBe('"foo""bar"');
  });

  it("returns an empty string for whitespace-only input", () => {
    expect(buildFtsMatchQuery("   ")).toBe("");
  });

  it("collapses repeated whitespace between tokens", () => {
    expect(buildFtsMatchQuery("a   b\tc")).toBe('"a" OR "b" OR "c"');
  });
});
