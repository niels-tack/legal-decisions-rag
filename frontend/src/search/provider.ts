import { LocalSqliteProvider } from "./localSqliteProvider";
import { RemoteApiProvider } from "./remoteApiProvider";
import type { SearchProvider } from "./types";

/**
 * Selects the active `SearchProvider` at build time via `VITE_SEARCH_BACKEND`
 * (`"local"` by default). This is the only place that decides which backend
 * runs - everything else in the UI depends solely on the `SearchProvider`
 * interface, per the technical requirements' "swap is invisible to the UI".
 */
export function createSearchProvider(): SearchProvider {
  const backend = import.meta.env.VITE_SEARCH_BACKEND ?? "local";
  if (backend === "remote") {
    const baseUrl = import.meta.env.VITE_QUERY_SERVICE_URL;
    if (!baseUrl) {
      throw new Error(
        "VITE_SEARCH_BACKEND=remote requires VITE_QUERY_SERVICE_URL to be set.",
      );
    }
    return new RemoteApiProvider(baseUrl);
  }
  return new LocalSqliteProvider();
}
