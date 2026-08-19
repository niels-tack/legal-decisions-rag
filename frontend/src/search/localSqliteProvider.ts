import initSqlite3, {
  type BindableValue,
  type Database,
  type PreparedStatement,
} from "@sqlite.org/sqlite-wasm";

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
  case_number: string;
  docket_number: string;
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
 * Execute a prepared statement and return all rows as plain objects.
 *
 * @sqlite.org/sqlite-wasm's PreparedStatement uses `finalize()` (not `free()`),
 * and `get({})` (not `getAsObject()`). Calling `bind()` on a statement that
 * has no `?` placeholders throws "This statement has no bindable parameters",
 * so we skip the call when params is empty.
 */
function queryAll<T extends object>(db: Database, sql: string, params: unknown[]): T[] {
  const stmt: PreparedStatement = db.prepare(sql);
  try {
    if (params.length > 0) {
      stmt.bind(params as BindableValue[]);
    }
    const rows: T[] = [];
    while (stmt.step()) {
      // `get({})` returns the current row as a column-name → value object,
      // equivalent to sql.js's `getAsObject()`.
      rows.push(stmt.get({}) as T);
    }
    return rows;
  } finally {
    stmt.finalize();
  }
}

/**
 * Phase 1's default `SearchProvider`: BM25-only full-text search running
 * entirely in the browser against the statically hosted `cases.db`, fetched
 * once over HTTP and held in memory via `@sqlite.org/sqlite-wasm` (the
 * official SQLite WebAssembly build, which includes FTS5). No embeddings, no
 * hybrid re-ranking, no fusion score.
 *
 * The full database is fetched once (the browser auto-decompresses any
 * Content-Encoding: gzip the CDN applies, so the ArrayBuffer is always the
 * real uncompressed SQLite bytes). The bytes are loaded into WASM memory via
 * `sqlite3_deserialize`. Subsequent queries run synchronously in the WASM
 * sandbox with no additional network traffic.
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
        const [sqlite3, buffer] = await Promise.all([
          // @sqlite.org/sqlite-wasm resolves its own WASM file via
          // `new URL("sqlite3.wasm", import.meta.url)`, which Vite bundles as
          // a hashed static asset at build time - no manual locateFile needed.
          initSqlite3(),
          // The browser automatically decompresses Content-Encoding: gzip (as
          // GitHub Pages/Fastly applies to cases.db), so arrayBuffer() always
          // yields the real uncompressed SQLite bytes regardless of CDN
          // compression.
          fetch(this.dbUrl).then((r) => {
            if (!r.ok) throw new Error(`Failed to fetch cases.db: ${r.status} ${r.statusText}`);
            return r.arrayBuffer();
          }),
        ]);

        // Allocate WASM heap memory for the database bytes, then use
        // sqlite3_deserialize to open them as an in-memory database. The
        // FREEONCLOSE flag tells SQLite to free the heap allocation when the
        // database is closed; RESIZEABLE allows SQLite to grow the buffer if
        // needed (e.g. when running VACUUM - harmless for read-only use).
        const byteArray = new Uint8Array(buffer);
        const p = sqlite3.wasm.allocFromTypedArray(byteArray);
        const db = new sqlite3.oo1.DB();
        const rc = sqlite3.capi.sqlite3_deserialize(
          db,
          "main",
          p,
          byteArray.length,
          byteArray.length,
          sqlite3.capi.SQLITE_DESERIALIZE_FREEONCLOSE |
            sqlite3.capi.SQLITE_DESERIALIZE_RESIZEABLE,
        );
        if (rc !== 0) {
          db.close();
          throw new Error(`sqlite3_deserialize failed with code ${rc}`);
        }
        return db;
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
          score: 0,
        });
      }
    }

    return [...caseMap.values()].map(({ caseData, chunks }) => ({
      source: caseData.source,
      ecli: caseData.ecli,
      caseNumber: caseData.case_number,
      docketNumber: caseData.docket_number,
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

    const rows = queryAll<CaseRow>(
      db,
      `SELECT chunks.section, chunks.paragraph_number, chunks.text,
              snippet(chunks_fts, 0, ?, ?, ?, ?) AS highlighted_snippet,
              cases.source, cases.ecli, cases.case_number, cases.docket_number,
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
    const procedureTypeRows = queryAll<{ procedure_type: string }>(
      db,
      "SELECT DISTINCT procedure_type FROM cases ORDER BY procedure_type",
      [],
    );
    const sourceRows = queryAll<{ source: string }>(
      db,
      "SELECT DISTINCT source FROM cases ORDER BY source",
      [],
    );
    return {
      procedureTypes: procedureTypeRows.map((row) => row.procedure_type),
      sources: sourceRows.map((row) => row.source),
    };
  }
}
