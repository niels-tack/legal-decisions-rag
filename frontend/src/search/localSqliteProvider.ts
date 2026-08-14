import { createDbWorker, type WorkerHttpvfs } from "sql.js-httpvfs";

import { truncateExcerpt } from "./excerpt";
import { buildFtsMatchQuery } from "./ftsQuery";
import { SNIPPET_MATCH_END, SNIPPET_MATCH_START } from "./snippetMarkers";
import type {
  FilterOptions,
  SearchFilters,
  SearchOptions,
  SearchProvider,
  SearchResultItem,
  SortOption,
} from "./types";

// The page size src/db_schema.py::PAGE_SIZE tunes cases.db to, so httpvfs's
// chunk fetch size matches the database's own page size.
const REQUEST_CHUNK_SIZE = 1024;

// Root-relative, prefixed with Vite's configured base path (import.meta.env.BASE_URL,
// "/" unless deployed under a subpath) - NOT a bare relative "cases.db". The
// worker created by createDbWorker() resolves relative URLs against its own
// script location (under node_modules/sql.js-httpvfs/dist/), not the page's,
// so a bare relative path silently 404s (as text/html, from Vite's dev
// server) rather than reaching the real file.
const DEFAULT_DB_URL = `${import.meta.env.BASE_URL}cases.db`;

const SNIPPET_MAX_TOKENS = 40;

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
 * Phase 1's default `SearchProvider`: BM25-only full-text search running
 * entirely in the browser against the statically hosted `cases.db`, fetched
 * lazily over HTTP range requests via `sql.js-httpvfs`. No embeddings, no
 * hybrid re-ranking, no fusion score - Phase 1 has exactly one ranked list
 * (FTS5's own `rank`), unlike the Phase 2 API's RRF fusion of two.
 */
export class LocalSqliteProvider implements SearchProvider {
  private workerPromise: Promise<WorkerHttpvfs> | null = null;

  constructor(private readonly dbUrl: string = DEFAULT_DB_URL) {}

  private async getWorker(): Promise<WorkerHttpvfs> {
    if (!this.workerPromise) {
      // Bundler-relative asset URLs, per sql.js-httpvfs's own documented
      // Vite/webpack integration pattern - Vite resolves these to hashed,
      // vendored asset URLs at build time (no CDN script tags).
      const workerUrl = new URL("sql.js-httpvfs/dist/sqlite.worker.js", import.meta.url);
      const wasmUrl = new URL("sql.js-httpvfs/dist/sql-wasm.wasm", import.meta.url);

      this.workerPromise = createDbWorker(
        [
          {
            from: "inline",
            config: {
              serverMode: "full",
              url: this.dbUrl,
              requestChunkSize: REQUEST_CHUNK_SIZE,
            },
          },
        ],
        workerUrl.toString(),
        wasmUrl.toString(),
      );
    }
    return this.workerPromise;
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

  async search(
    query: string,
    filters: SearchFilters,
    options: SearchOptions,
  ): Promise<SearchResultItem[]> {
    const matchQuery = buildFtsMatchQuery(query);
    if (!matchQuery) {
      return [];
    }

    const worker = await this.getWorker();
    const where = this.buildWhereClause(matchQuery, filters);
    const orderBy = SORT_CLAUSES[options.sort];

    // Comlink's Remote<T> proxy type collapses query()'s own <T> generic (it
    // can't know the runtime row shape), so the result comes back untyped -
    // asserted to CaseRow[] here, the one place that shape is declared.
    //
    // sql.js-httpvfs's .query(sql, params) forwards straight to sql.js's own
    // Database.exec(sql, params) - which takes ALL bound values as one
    // params array (positional ? binding), not as separate trailing
    // arguments. The .d.ts's `...params: any[]` rest-parameter type is
    // misleading here: passing values as separate arguments silently drops
    // everything past the first (exec() only has two formal parameters),
    // leaving the rest of the ?s unbound and raising "SQLite: datatype
    // mismatch" - hence the single array below. The sentinel/ellipsis/
    // max-tokens snippet() arguments are bound rather than inlined into the
    // SQL text too, since sql.js's WASM string-marshaling mishandled the raw
    // control-byte sentinels when interpolated directly (plain `sqlite3` via
    // Python has no such issue - verified separately) - binding is also just
    // better practice regardless.
    const rows = (await worker.db.query(
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
       LIMIT ? OFFSET ?`,
      [SNIPPET_MATCH_START, SNIPPET_MATCH_END, "…", SNIPPET_MAX_TOKENS, ...where.params, options.limit, options.offset],
    )) as CaseRow[];

    return rows.map((row) => ({
      source: row.source,
      ecli: row.ecli,
      arrestNumber: row.arrest_number,
      roleNumber: row.role_number,
      caseNumber: row.file_slug,
      rulingDate: row.ruling_date,
      language: row.language,
      procedureType: row.procedure_type,
      controlledNorm: row.controlled_norm,
      outcome: row.outcome,
      title: row.title,
      section: row.section,
      paragraphNumber: row.paragraph_number,
      excerpt: truncateExcerpt(row.text),
      highlightedSnippet: row.highlighted_snippet,
      sourcePdfUrl: row.source_pdf_url,
      // No ranking score is exposed by FTS5's bare `rank` ordering in a
      // portable way here; Phase 1 has one ranked list, so relative order
      // (already applied via ORDER BY) is what matters, not a score value -
      // unlike the Phase 2 API's fused RRF score.
      score: 0,
    }));
  }

  async count(query: string, filters: SearchFilters): Promise<number> {
    const matchQuery = buildFtsMatchQuery(query);
    if (!matchQuery) {
      return 0;
    }

    const worker = await this.getWorker();
    const where = this.buildWhereClause(matchQuery, filters);

    const rows = (await worker.db.query(
      `SELECT COUNT(*) AS total
       FROM chunks_fts
       JOIN chunks ON chunks.chunk_id = chunks_fts.rowid
       JOIN cases ON cases.case_id = chunks.case_id
       WHERE ${where.sql}`,
      where.params,
    )) as { total: number }[];

    return rows[0]?.total ?? 0;
  }

  async listFilterOptions(): Promise<FilterOptions> {
    const worker = await this.getWorker();
    const [procedureTypeRows, sourceRows] = (await Promise.all([
      worker.db.query("SELECT DISTINCT procedure_type FROM cases ORDER BY procedure_type"),
      worker.db.query("SELECT DISTINCT source FROM cases ORDER BY source"),
    ])) as [{ procedure_type: string }[], { source: string }[]];
    return {
      procedureTypes: procedureTypeRows.map((row) => row.procedure_type),
      sources: sourceRows.map((row) => row.source),
    };
  }
}
