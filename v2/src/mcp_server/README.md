# Belgian Constitutional Court search - MCP server

An [MCP](https://modelcontextprotocol.io) server that exposes the hosted
`legal-decisions-rag` search API (hybrid BM25 + vector retrieval over
Dutch-language Belgian Constitutional Court rulings) as a single tool,
`search_constitutional_court_rulings`, for MCP-capable clients such as
Claude Desktop, Cursor, and VS Code Copilot.

It performs no retrieval itself. Every tool call is a server-side
authenticated HTTP proxy to the hosted query service
(`GET {QUERY_SERVICE_URL}/search`), so the client's user asks a question in
plain language and gets back cited passages (ECLI, ruling date, excerpt,
source PDF link) without ever installing the ingestion pipeline, holding an
API key, or building a local index.

## What this is (and isn't)

This is a **local stdio proxy**: your MCP client (Claude Desktop, Cursor,
VS Code Copilot) starts this server as a subprocess on your own machine and
talks to it over stdio, exactly like any other local MCP server. It still
requires:

- `uv` installed locally.
- This repository cloned locally.

It does **not** require you to hold or enter the shared API key - that key
lives only in the server's environment (set once in your MCP client's
config, per the snippet below) and is attached to every outbound request
server-side. You never see it, type it into a chat, or pass it as a tool
argument.

A fully zero-install, remotely hosted MCP endpoint (no local `uv`/clone
needed at all) is a documented future option once MCP clients broadly
support remote MCP over HTTP - see `context/Technical requirements.md`
("Open Technical Questions"). It is intentionally out of scope for this
version; the Copilot/Custom GPT integration is the zero-install path for
non-technical users today.

## Required environment variables

Both are read server-side, at call time, from the process environment -
never as tool parameters an MCP client's user could see or edit.

| Variable            | Description                                                                 |
| ------------------- | ---------------------------------------------------------------------------- |
| `QUERY_SERVICE_URL`  | Base URL of the hosted query service, e.g. `https://<deployed-container-url>` (no trailing `/search`). |
| `SHARED_API_KEY`     | The shared static key the query service expects on the `X-API-Key` header.  |

If either is missing, or the query service returns a non-200 response, or
the HTTP request itself fails (DNS, timeout, connection refused, ...), the
tool returns a normal (non-crashing) result shaped like
`{"error": "<human-readable message>"}` instead of raising - the server
process keeps running and the client's LLM sees the failure reason.

## Running it directly

```bash
QUERY_SERVICE_URL=https://<deployed-container-url> \
SHARED_API_KEY=<the shared key> \
uv run python -m src.mcp_server.server
```

This starts the server on the stdio transport, as MCP clients expect when
they launch a server as a subprocess.

## Adding it to Claude Desktop / Cursor

Add this to the client's MCP server config (for Claude Desktop:
`claude_desktop_config.json`; Cursor and VS Code Copilot use an analogous
`mcpServers` block in their own MCP settings):

```json
{
  "mcpServers": {
    "belgian-constitutional-court": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/legal-decisions-rag", "python", "-m", "src.mcp_server.server"],
      "env": {
        "QUERY_SERVICE_URL": "https://<deployed-container-url>",
        "SHARED_API_KEY": "<the shared key>"
      }
    }
  }
}
```

Replace `/absolute/path/to/legal-decisions-rag` with the absolute path to
your local clone of this repository, and fill in the deployed query
service's URL and the shared key issued by the maintainer. Restart the MCP
client after editing its config.

## The tool

### `search_constitutional_court_rulings(query: str, limit: int = 5)`

- `query`: a plain-language question or exact term (case number, article
  reference, ...).
- `limit`: maximum number of ranked results to return.

Returns the query service's parsed JSON response on success (a `query`
string and a `results` list of passages, each with `ecli`, `case_number`,
`docket_number`, `case_number`, `ruling_date`, `language`, `procedure_type`,
`controlled_norm`, `outcome`, `title`, `section`, `excerpt`,
`source_pdf_url`, and `score`), or `{"error": "..."}` on failure.
