import { truncateExcerpt } from "./search/excerpt";
import type { SearchResultItem } from "./search/types";

const DEFAULT_MAX_RESULTS = 5;

/**
 * Compose the assistant hand-off prompt: the user's question, the top
 * retrieved passages, and full citations for each - a self-contained prompt
 * any external LLM (Copilot, ChatGPT, Claude) can turn into a cited answer
 * without further tooling, per the functional requirements. This is a
 * template over data, not a network call, so it's cheap to unit-test for
 * size limits and citation completeness.
 *
 * @param question - The user's original search query/question.
 * @param results - Ranked results, already in the order to present (best first).
 * @param maxResults - Maximum number of passages to include.
 * @returns The composed, clipboard-ready prompt text.
 */
export function composePrompt(
  question: string,
  results: SearchResultItem[],
  maxResults: number = DEFAULT_MAX_RESULTS,
): string {
  const included = results.slice(0, maxResults);

  const passages = included
    .map((result, index) => {
      const label = result.paragraphNumber
        ? `${result.ecli}, paragraph ${result.paragraphNumber}`
        : `${result.ecli}, ${result.section}`;
      return [
        `[${index + 1}] ${label}, ${result.rulingDate}`,
        `"${truncateExcerpt(result.excerpt)}"`,
        `Source PDF: ${result.sourcePdfUrl}`,
      ].join("\n");
    })
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
