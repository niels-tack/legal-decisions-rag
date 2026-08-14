import type { Plugin } from "vite";
import { defineConfig } from "vite";

/**
 * Dev-server-only shim: Vite's dev static server (sirv) only advertises
 * `Accept-Ranges: bytes` on a response that's *already* a ranged request -
 * a bare capability-probing HEAD/GET (no Range header) gets a plain 200
 * with no `Accept-Ranges` at all. `sql.js-httpvfs` does exactly that probe
 * before trusting the server's `Content-Length`, so without this it fails
 * locally with "Length of the file not known" even though ranged requests
 * themselves work fine (verified via `curl -H "Range: ..."`). Real static
 * hosts (GitHub Pages included) declare `Accept-Ranges: bytes`
 * unconditionally, so this just makes local dev match production - it has
 * no effect on the production build (`vite build` doesn't run this hook).
 */
function rangeCapabilityShim(): Plugin {
  return {
    name: "range-capability-shim",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.endsWith(".db")) {
          res.setHeader("Accept-Ranges", "bytes");
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [rangeCapabilityShim()],
  test: {
    environment: "node",
    globals: true,
    include: ["tests/**/*.test.ts"],
  },
});
