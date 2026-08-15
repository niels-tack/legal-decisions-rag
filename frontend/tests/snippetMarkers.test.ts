import { describe, expect, it } from "vitest";

import {
  SNIPPET_MATCH_END,
  SNIPPET_MATCH_START,
  parseHighlightedSnippet,
} from "../src/search/snippetMarkers";

describe("parseHighlightedSnippet", () => {
  it("returns one unmatched segment for plain text", () => {
    expect(parseHighlightedSnippet("geen match hier")).toEqual([
      { text: "geen match hier", matched: false },
    ]);
  });

  it("marks a single wrapped term as matched", () => {
    const snippet = `voor de ${SNIPPET_MATCH_START}omgevingsvergunning${SNIPPET_MATCH_END} geweigerd`;

    expect(parseHighlightedSnippet(snippet)).toEqual([
      { text: "voor de ", matched: false },
      { text: "omgevingsvergunning", matched: true },
      { text: " geweigerd", matched: false },
    ]);
  });

  it("handles multiple matched terms in one snippet", () => {
    const snippet = `${SNIPPET_MATCH_START}milieu${SNIPPET_MATCH_END} en ${SNIPPET_MATCH_START}vergunning${SNIPPET_MATCH_END}`;

    expect(parseHighlightedSnippet(snippet)).toEqual([
      { text: "milieu", matched: true },
      { text: " en ", matched: false },
      { text: "vergunning", matched: true },
    ]);
  });

  it("treats an unterminated match marker as plain text rather than dropping it", () => {
    const snippet = `tekst ${SNIPPET_MATCH_START}zonder einde`;

    expect(parseHighlightedSnippet(snippet)).toEqual([
      { text: "tekst ", matched: false },
      { text: "zonder einde", matched: false },
    ]);
  });

  it("returns an empty array for an empty snippet", () => {
    expect(parseHighlightedSnippet("")).toEqual([]);
  });
});
