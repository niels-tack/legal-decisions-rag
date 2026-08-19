import type {
  CaseSearchResult,
  ChunkResult,
  FilterOptions,
  SearchFilters,
  SearchOptions,
  SearchProvider,
} from "./types";

/** Mirrors `src/schemas.py::ChunkResult` field-for-field (snake_case, as sent over HTTP). */
interface ApiChunkResult {
  section: string;
  paragraph_number: string | null;
  excerpt: string;
  score: number;
}

/** Mirrors `src/schemas.py::CaseSearchResult` field-for-field (snake_case, as sent over HTTP). */
interface ApiCaseSearchResult {
  source: string;
  ecli: string;
  case_number: string;
  docket_number: string;
  case_number: string;
  ruling_date: string;
  language: string;
  procedure_type: string;
  controlled_norm: string;
  outcome: string;
  title: string;
  source_pdf_url: string;
  best_score: number;
  chunks: ApiChunkResult[];
}

interface ApiSearchResponse {
  query: string;
  results: ApiCaseSearchResult[];
}

// Matches src/query_service/main.py::MAX_LIMIT - the API rejects (422) any
// `limit` above this, so count()'s single-fetch approximation must respect
// it too, not just the UI's own page size.
const API_MAX_LIMIT = 20;

function mapChunk(chunk: ApiChunkResult): ChunkResult {
  return {
    section: chunk.section,
    paragraphNumber: chunk.paragraph_number,
    excerpt: chunk.excerpt,
    // Phase 2 API does not produce highlighted snippets yet.
    highlightedSnippet: null,
    score: chunk.score,
  };
}

/**
 * Phase 2's `SearchProvider`: calls the hosted hybrid BM25 + vector search
 * API (`src/query_service/main.py`) exactly as it's implemented today,
 * including the repeatable `sources` filter param. Not wired to a real
 * deployment yet (there is no `baseUrl` configured for any environment this
 * pass) - this class exists to prove the `SearchProvider` abstraction is
 * real, not just a `LocalSqliteProvider`-shaped interface.
 *
 * Known gaps vs. the full interface, until the hosted API grows matching
 * support: no date-range/procedure-type filtering, no sort-by-date, no
 * pagination (`options.offset` is ignored and `count()` is approximated
 * from the single page fetched), and no highlighted snippets (the API
 * returns a plain excerpt - `highlightedSnippet` is always `null`).
 */
export class RemoteApiProvider implements SearchProvider {
  constructor(private readonly baseUrl: string) {}

  async search(
    query: string,
    filters: SearchFilters,
    options: SearchOptions,
  ): Promise<CaseSearchResult[]> {
    const params = new URLSearchParams({ q: query, limit: String(options.limit) });
    for (const source of filters.sources ?? []) {
      params.append("sources", source);
    }

    const response = await fetch(`${this.baseUrl}/search?${params.toString()}`);
    if (!response.ok) {
      throw new Error(`Search API returned HTTP ${response.status}`);
    }
    const body = (await response.json()) as ApiSearchResponse;

    return body.results.map((item) => ({
      source: item.source,
      ecli: item.ecli,
      caseNumber: item.case_number,
      docketNumber: item.docket_number,
      caseNumber: item.case_number,
      rulingDate: item.ruling_date,
      language: item.language,
      procedureType: item.procedure_type,
      controlledNorm: item.controlled_norm,
      outcome: item.outcome,
      title: item.title,
      sourcePdfUrl: item.source_pdf_url,
      bestScore: item.best_score,
      chunks: item.chunks.map(mapChunk),
    }));
  }

  async count(query: string, filters: SearchFilters): Promise<number> {
    // No dedicated count endpoint yet - approximate from a single fetch
    // rather than adding a second network round trip for a number the UI
    // only uses for pagination, which Phase 2 doesn't support end-to-end yet.
    const results = await this.search(query, filters, {
      limit: API_MAX_LIMIT,
      offset: 0,
      sort: "relevance",
    });
    return results.length;
  }

  async listFilterOptions(): Promise<FilterOptions> {
    // The hosted API has no dedicated filter-options endpoint yet; Phase 1's
    // options come from querying cases.db directly, which isn't available to
    // this provider. Returning empty options degrades to "no filter UI",
    // rather than guessing at values the API might reject.
    return { procedureTypes: [], sources: [] };
  }
}
