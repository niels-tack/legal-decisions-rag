/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SEARCH_BACKEND?: "local" | "remote";
  readonly VITE_QUERY_SERVICE_URL?: string;
  /** Set by the (future) CI build to the build timestamp, for the trust footer's "last updated" line. */
  readonly VITE_BUILT_AT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
