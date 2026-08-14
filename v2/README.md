# V2 (deferred / out of scope)

This directory holds functionality that the current `context/Functional
requirements.md` and `context/Technical requirements.md` explicitly move to
V2 or list under "Won't have (this version)":

- `src/mcp_server/` - an MCP server exposing the hosted search API to Claude
  Desktop / Cursor / VS Code Copilot.
- `docs/copilot-studio-setup.md`, `docs/custom-gpt-setup.md`,
  `docs/openapi.json` - wiring the hosted search API into a Microsoft
  Copilot Studio agent or an OpenAI Custom GPT Action.

It is parked here rather than deleted so it can be picked up again once V2
work starts, but it is **not** part of the active build, CI, or test suite -
nothing in `src/`, `tests/`, or the GitHub Actions workflows imports or runs
anything under this directory.

## Known rework needed before this is usable again

All of this code was written against an earlier requirements iteration
where the query service was protected by a single shared static API key
(`SHARED_API_KEY`, checked via `src/query_service/auth.require_api_key`).
That auth model has since been removed from the active query service (see
`src/query_service/rate_limit.py`) because the current technical
requirements explicitly forbid any end-user/shared key - the keyless public
API is now protected by per-IP rate limiting, origin-locked CORS, and
response-size caps instead. Reviving anything in this directory will need a
replacement auth/identification story for these machine clients (the shared
key doesn't come back just because the file does).
