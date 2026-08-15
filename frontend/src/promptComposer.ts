import { truncateExcerpt } from "./search/excerpt";
import type { CaseSearchResult } from "./search/types";

const DEFAULT_MAX_RESULTS = 5;

/**
 * Compose the assistant hand-off prompt: the user's question, the top
 * retrieved passages, and full citations for each - a self-contained prompt
 * any external LLM (Copilot, ChatGPT, Claude) can turn into a cited answer
 * without further tooling, per the functional requirements. This is a
 * template over data, not a network call, so it's cheap to unit-test for
 * size limits and citation completeness.
 *
 * Each case contributes its best-matching chunk (chunks[0]) to the prompt so
 * the passage is always the most relevant excerpt for that case.
 *
 * @param question - The user's original search query/question.
 * @param results - Ranked cases, already in the order to present (best first).
 * @param maxResults - Maximum number of cases to include.
 * @returns The composed, clipboard-ready prompt text.
 */
export function composePrompt(
  question: string,
  results: CaseSearchResult[],
  maxResults: number = DEFAULT_MAX_RESULTS,
): string {
  const included = results.slice(0, maxResults);

  const passages = included
    .map((result, index) => {
      const chunk = result.chunks[0];
      if (!chunk) return null;
      const label = chunk.paragraphNumber
        ? `${result.ecli}, paragraph ${chunk.paragraphNumber}`
        : `${result.ecli}, ${chunk.section}`;
      return [
        `[${index + 1}] ${label}, ${result.rulingDate}`,
        `"${truncateExcerpt(chunk.excerpt)}"`,
        `Source PDF: ${result.sourcePdfUrl}`,
      ].join("\n");
    })
    .filter(Boolean)
    .join("\n\n");

  return [
    `I have a question about Belgian case law: "${question}"`,
    "",
    "Here are relevant passages retrieved from official rulings. Please answer " +
      "my question using ONLY these passages, and cite the ECLI (and paragraph, " +
      "where given) for every claim.",
    "",
    passages,
    "",
    `Question: ${question}`,
  ].join("\n");
}
