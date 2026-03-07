# Pitfalls: Python MCP Server

- Every tool module exposes a single `register(mcp)` function — tools are closures defined inside it, not top-level functions
- `_db_op(readonly=True)` for reads, `_db_op()` for writes — the context manager commits on success and closes on exit; never hold a connection outside the `with` block
- Tool return values are always strings via `fmt_*` formatters in `format_response.py` — keep the dict shape stable because callers parse the one-liner and detail file
- Detail-heavy responses write to `/tmp/gemini/<name>.md` and return a one-liner with ` → <path>` — the caller reads the detail file separately
- State transitions use constants from `constants.py` (`VALID_STORY_TRANSITIONS`, `VALID_EPIC_TRANSITIONS`) — add new states there, not inline
- Shared helpers live in `tools_pm_helpers.py` — if two tool modules need the same function, extract it there rather than duplicating
- When extending a regex, preserve existing patterns — add new alternations, don't rewrite the whole expression
- Imports are flat (no package hierarchy) — `from constants import X`, not `from mcp_servers.gemini.constants import X`
- SQLite row access uses `row["column"]` (row factory is `sqlite3.Row`) — not tuple indexing
- Tool docstrings are user-facing (shown in tool listings) — keep them concise and accurate about what the tool does, not how
