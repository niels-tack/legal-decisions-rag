import { describe, expect, it } from "vitest";

import { composePrompt } from "../src/promptComposer";
import type { SearchResultItem } from "../src/search/types";

function makeResult(overrides: Partial<SearchResultItem> = {}): SearchResultItem {
  return {
    source: "GHCC",
    ecli: "ECLI:BE:GHCC:2025:ARR.001",
    arrestNumber: "1/2025",
    roleNumber: "8115",
    caseNumber: "2025-001n",
    rulingDate: "2025-01-15",
    language: "nl",
    procedureType: "Prejudiciele vraag",
    controlledNorm: "Artikel 1",
    outcome: "Vernietiging",
    title: "Test ruling",
    section: "reasoning",
    paragraphNumber: "B.7",
    excerpt: "Het Hof oordeelt dat de bepaling ongrondwettig is.",
    highlightedSnippet: null,
    sourcePdfUrl: "https://example.test/2025-001n.pdf",
    score: 1.0,
    ...overrides,
  };
}

describe("composePrompt", () => {
  it("includes the question both up front and at the end", () => {
    const prompt = composePrompt("Wat oordeelde het Hof?", [makeResult()]);

    expect(prompt).toContain('"Wat oordeelde het Hof?"');
    expect(prompt).toContain("Question: Wat oordeelde het Hof?");
  });

  it("cites every included result's ECLI, paragraph, and PDF URL", () => {
    const results = [
      makeResult({ ecli: "ECLI:BE:GHCC:2025:ARR.001", paragraphNumber: "B.7" }),
      makeResult({
        ecli: "ECLI:BE:GHCC:2025:ARR.002",
        paragraphNumber: null,
        section: "facts",
        sourcePdfUrl: "https://example.test/2025-002n.pdf",
      }),
    ];

    const prompt = composePrompt("q", results);

    for (const result of results) {
      expect(prompt).toContain(result.ecli);
      expect(prompt).toContain(result.sourcePdfUrl);
    }
    expect(prompt).toContain("paragraph B.7");
    expect(prompt).toContain("ECLI:BE:GHCC:2025:ARR.002, facts");
  });

  it("never includes more than maxResults passages", () => {
    const results = Array.from({ length: 10 }, (_, i) =>
      makeResult({ ecli: `ECLI:BE:GHCC:2025:ARR.${i}`, caseNumber: `2025-00${i}n` }),
    );

    const prompt = composePrompt("q", results, 3);

    expect(prompt).toContain("ECLI:BE:GHCC:2025:ARR.2");
    expect(prompt).not.toContain("ECLI:BE:GHCC:2025:ARR.3");
  });

  it("truncates an excerpt longer than the shared response-size cap", () => {
    const longExcerpt = "x".repeat(3000);
    const prompt = composePrompt("q", [makeResult({ excerpt: longExcerpt })]);

    expect(prompt).not.toContain("x".repeat(2001));
    expect(prompt).toContain("…");
  });

  it("returns an empty passages block gracefully when there are no results", () => {
    expect(() => composePrompt("q", [])).not.toThrow();
  });
});
