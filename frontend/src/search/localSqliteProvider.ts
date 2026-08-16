import initSqlJs, { type Database, type Statement } from "sql.js";
import sqlWasmUrl from "sql.js/dist/sql-wasm.wasm?url";

import { truncateExcerpt } from "./excerpt";
import { buildFtsMatchQuery } from "./ftsQuery";
import { SNIPPET_MATCH_END, SNIPPET_MATCH_START } from "./snippetMarkers";
import type {
  CaseSearchResult,
  ChunkResult,
  FilterOptions,
  SearchFilters,
  SearchOptions,
  SearchProvider,
  SortOption,
} from "./types";

// Root-relative, prefixed with Vite's configured base path (import.meta.env.BASE_URL,
// "/" unless deployed under a subpath) - NOT a bare relative "cases.db".
const DEFAULT_DB_URL = `${import.meta.env.BASE_URL}cases.db`;

const SNIPPET_MAX_TOKENS = 40;

// Maximum chunks to include per case in the grouped result. Must match the
// intent of the backend's _MAX_CHUNKS_PER_CASE (src/query_service/search.py).
const MAX_CHUNKS_PER_CASE = 3;

// Number of chunk rows to fetch from SQLite before case-level grouping. Sized
// generously so that even when a single case dominates the top FTS ranks we
// still accumulate enough distinct cases to fill several pages of results.
const POOL_SIZE = 500;

const SORT_CLAUSES: Record<SortOption, string> = {
  relevance: "rank",
  "date-desc": "cases.ruling_date DESC",
  "date-asc": "cases.ruling_date ASC",
};

interface CaseRow {
  section: string;
  paragraph_number: string | null;
  text: string;
  highlighted_snippet: string;
  source: string;
  ecli: string;
  arrest_number: string;
  role_number: string;
  file_slug: string;
  ruling_date: string;
  language: string;
  procedure_type: string;
  controlled_norm: string;
  outcome: string;
  title: string;
  source_pdf_url: string;
}

interface WhereClause {
  sql: string;
  params: unknown[];
}

/**
 * Execute a sql.js prepared statement and return all rows as plain objects.
 *
 * sql.js's `Database.exec()` returns column names and value arrays separately,
 * which is awkward to work with. This helper prepares the statement, binds
 * params, steps through all rows, and returns typed objects - matching the
 * ergonomics of the former sql.js-httpvfs `.query()` method.
 */
function queryAll<T extends object>(db: Database, sql: string, params: unknown[]): T[] {
  const stmt: Statement = db.prepare(sql);
  try {
    stmt.bind(params as Parameters<Statement["bind"]>[0]);
    const rows: T[] = [];
    while (stmt.step()) {
      rows.push(stmt.getAsObject({}) as T);
    }
    return rows;
  } finally {
    stmt.free();
  }
}

/**
 * Phase 1's default `SearchProvider`: BM25-only full-text search running
 * entirely in the browser against the statically hosted `cases.db`, fetched
 * once over HTTP and held in memory via `sql.js` (WebAssembly SQLite). No
 * embeddings, no hybrid re-ranking, no fusion score - Phase 1 has exactly one
 * ranked list (FTS5's own `rank`), unlike the Phase 2 API's RRF fusion of two.
 *
 * The full database is fetched once (the browser auto-decompresses any
 * Content-Encoding: gzip the CDN applies, so the ArrayBuffer is always the
 * real uncompressed SQLite bytes). Subsequent queries run synchronously in the
 * WASM sandbox with no additional network traffic.
 *
 * Results are grouped by case: each returned item is one `CaseSearchResult`
 * with up to `MAX_CHUNKS_PER_CASE` matching chunks (best-ranked first).
 */
export class LocalSqliteProvider implements SearchProvider {
  private dbPromise: Promise<Database> | null = null;

  constructor(private readonly dbUrl: string = DEFAULT_DB_URL) {}

  private async getDb(): Promise<Database> {
    if (!this.dbPromise) {
      this.dbPromise = (async () => {
        const [SQL, buffer] = await Promise.all([
          // Bundler-relative WASM URL, resolved to a hashed asset path by Vite
          // at build time - no CDN script tags or separate server config needed.
          initSqlJs({ locateFile: () => sqlWasmUrl }),
          // The browser automatically decompresses Content-Encoding: gzip (as
          // GitHub Pages/Fastly applies to cases.db), so arrayBuffer() always
          // yields the real uncompressed SQLite bytes regardless of CDN
          // compression.
          fetch(this.dbUrl).then((r) => {
            if (!r.ok) throw new Error(`Failed to fetch cases.db: ${r.status} ${r.statusText}`);
            return r.arrayBuffer();
          }),
        ]);
        return new SQL.Database(new Uint8Array(buffer));
      })();
    }
    return this.dbPromise;
  }

  /**
   * Build the shared `WHERE ...` clause (and its bound params) for both the
   * results query and the count query, so the two can never drift apart.
   */
  private buildWhereClause(matchQuery: string, filters: SearchFilters): WhereClause {
    const conditions = ["chunks_fts MATCH ?"];
    const params: unknown[] = [matchQuery];

    if (filters.dateFrom) {
      conditions.push("cases.ruling_date >= ?");
      params.push(filters.dateFrom);
    }
    if (filters.dateTo) {
      conditions.push("cases.ruling_date <= ?");
      params.push(filters.dateTo);
    }
    if (filters.procedureType) {
      conditions.push("cases.procedure_type = ?");
      params.push(filters.procedureType);
    }
    if (filters.sources && filters.sources.length > 0) {
      conditions.push(`cases.source IN (${filters.sources.map(() => "?").join(", ")})`);
      params.push(...filters.sources);
    }

    return { sql: conditions.join(" AND "), params };
  }

  /**
   * Group a flat list of chunk rows (ordered by FTS5 rank) into case results.
   * Preserves the first-occurrence ordering of each case, so the case whose
   * best chunk ranked highest in FTS5 appears first in the output. Within
   * each case, chunks are in their original rank order (best first).
   */
  private groupIntoCases(rows: CaseRow[]): CaseSearchResult[] {
    const caseMap = new Map<string, { caseData: CaseRow; chunks: ChunkResult[] }>();

    for (const row of rows) {
      if (!caseMap.has(row.ecli)) {
        caseMap.set(row.ecli, { caseData: row, chunks: [] });
      }
      const entry = caseMap.get(row.ecli)!;
      if (entry.chunks.length < MAX_CHUNKS_PER_CASE) {
        entry.chunks.push({
          section: row.section,
          paragraphNumber: row.paragraph_number,
          excerpt: truncateExcerpt(row.text),
          highlightedSnippet: row.highlighted_snippet,
          // No ranking score is exposed by FTS5's bare `rank` ordering in a
          // portable way here; relative order (already applied via ORDER BY)
          // is what matters for Phase 1, not a score value.
          score: 0,
        });
      }
    }

    return [...caseMap.values()].map(({ caseData, chunks }) => ({
      source: caseData.source,
      ecli: caseData.ecli,
      arrestNumber: caseData.arrest_number,
      roleNumber: caseData.role_number,
      caseNumber: caseData.file_slug,
      rulingDate: caseData.ruling_date,
      language: caseData.language,
      procedureType: caseData.procedure_type,
      controlledNorm: caseData.controlled_norm,
      outcome: caseData.outcome,
      title: caseData.title,
      sourcePdfUrl: caseData.source_pdf_url,
      bestScore: 0,
      chunks,
    }));
  }

  async search(
    query: string,
    filters: SearchFilters,
    options: SearchOptions,
  ): Promise<CaseSearchResult[]> {
    const matchQuery = buildFtsMatchQuery(query);
    if (!matchQuery) {
      return [];
    }

    const db = await this.getDb();
    const where = this.buildWhereClause(matchQuery, filters);
    const orderBy = SORT_CLAUSES[options.sort];

    // Fetch a large flat pool (no SQL-level OFFSET) ordered by FTS5 rank, then
    // group into cases in JS. SQL OFFSET on chunk rows cannot directly represent
    // an OFFSET on cases, so pagination is handled after grouping by slicing the
    // full ordered case list. See comment on POOL_SIZE for sizing rationale.
    //
    // snippet() sentinel bytes are bound as params rather than inlined into the
    // SQL text: sql.js's WASM string-marshaling mishandles raw control-byte
    // sentinels when interpolated directly - binding is also just better
    // practice regardless.
    const rows = queryAll<CaseRow>(
      db,
      `SELECT chunks.section, chunks.paragraph_number, chunks.text,
              snippet(chunks_fts, 0, ?, ?, ?, ?) AS highlighted_snippet,
              cases.source, cases.ecli, cases.arrest_number, cases.role_number,
              cases.file_slug, cases.ruling_date, cases.language,
              cases.procedure_type, cases.controlled_norm, cases.outcome,
              cases.title, cases.source_pdf_url
       FROM chunks_fts
       JOIN chunks ON chunks.chunk_id = chunks_fts.rowid
       JOIN cases ON cases.case_id = chunks.case_id
       WHERE ${where.sql}
       ORDER BY ${orderBy}
       LIMIT ?`,
      [SNIPPET_MATCH_START, SNIPPET_MATCH_END, "…", SNIPPET_MAX_TOKENS, ...where.params, POOL_SIZE],
    );

    const allCases = this.groupIntoCases(rows);
    return allCases.slice(options.offset, options.offset + options.limit);
  }

  async count(query: string, filters: SearchFilters): Promise<number> {
    const matchQuery = buildFtsMatchQuery(query);
    if (!matchQuery) {
      return 0;
    }

    const db = await this.getDb();
    const where = this.buildWhereClause(matchQuery, filters);

    const rows = queryAll<{ total: number }>(
      db,
      `SELECT COUNT(DISTINCT cases.case_id) AS total
       FROM chunks_fts
       JOIN chunks ON chunks.chunk_id = chunks_fts.rowid
       JOIN cases ON cases.case_id = chunks.case_id
       WHERE ${where.sql}`,
      where.params,
    );

    return rows[0]?.total ?? 0;
  }

  async listFilterOptions(): Promise<FilterOptions> {
    const db = await this.getDb();
    const [procedureTypeRows, sourceRows] = await Promise.all([
      Promise.resolve(
        queryAll<{ procedure_type: string }>(
          db,
          "SELECT DISTINCT procedure_type FROM cases ORDER BY procedure_type",
          [],
        ),
      ),
      Promise.resolve(
        queryAll<{ source: string }>(
          db,
          "SELECT DISTINCT source FROM cases ORDER BY source",
          [],
        ),
      ),
    ]);
    return {
      procedureTypes: procedureTypeRows.map((row) => row.procedure_type),
      sources: sourceRows.map((row) => row.source),
    };
  }
}
