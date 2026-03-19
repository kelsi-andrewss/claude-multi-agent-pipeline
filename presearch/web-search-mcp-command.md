# Web Search MCP Tool

## Problem Statement
**What problem?** Claude Code has no dedicated web search tool in the Gemini MCP. The `/research` skill uses `gemini_chat` with grounding, but there's no standalone `web_search` tool for ad-hoc searches from skills, hooks, or direct use.
**Why fix it?** Without it, every search requires routing through `gemini_chat` with carefully worded prompts. A dedicated tool with a search-optimized system prompt would be more reliable and ergonomic.
**Why integral?** The orchestration system increasingly depends on current web information for research, scout, and clarify phases. A first-class search tool completes the MCP tool surface.
**End goal:** `web_search(query="...")` returns a grounded response with citations, usable by any Claude Code session or skill.

## Overview
Add a `web_search` tool to the existing Gemini MCP server. The tool uses Gemini's native Google Search grounding (via the `gemini` CLI) — no separate search API. Implementation follows the existing `register(mcp)` pattern: one new module (`tools_search.py`) and two lines added to `server.py`.

## Summary
Add a web_search MCP tool to the Gemini MCP server at ~/.claude/mcp-servers/gemini/. Uses Gemini's native Google Search grounding — no external search API. Single new file (tools_search.py) following the existing register(mcp) pattern, plus 2-line registration in server.py. System prompt forces grounding and citation inclusion. Returns synthesized markdown with sources, using the existing /tmp/gemini/ detail pattern for long responses.

## Features
### MVP
1. `web_search` tool — new `tools_search.py` module with `register(mcp)` function, `@mcp.tool()` decorated async function, system prompt that forces search grounding, citation formatting, and `/tmp/gemini/` detail output for long results. Add 2-line registration to `server.py`. Add tests to `test_server.py`.

## Technical Research

### APIs & Services
- Gemini CLI (`gemini` binary): shells out via `_gemini()` in `gemini_client.py`. Automatically uses `google_web_search` tool when queries involve current information. No API key management needed beyond existing setup.

### Architecture
- **Pattern**: follows the exact `register(mcp)` → `@mcp.tool()` → `_gemini()` pipeline used by all 11 existing tool modules
- **System prompt**: a search-specific system instruction prepended to the query that tells Gemini to act as a web research assistant, always use Google Search grounding, include inline citations with URLs, and produce a factual summary (not conversational filler)
- **Output**: Gemini returns synthesized markdown (not raw search result objects). The tool bridges this by requiring a `## Sources` section in the response. For long responses, uses `_write_detail()` from `format_response.py` to write to `/tmp/gemini/search_<query_slug>.md`

### Patterns
- **Imports**: flat (`from gemini_client import _gemini`), no package paths
- **System prompt**: define `SEARCH_INSTRUCTION` in `constants.py` (or inline if unique to this tool)
- **Tool docstring**: concise, user-facing ("Search the web for current information on a topic")
- **Error handling**: `_gemini()` already handles subprocess errors — tool just calls it
- **NO_CODE_INSTRUCTION**: likely not applicable — search results may include code snippets

### Dependencies
- None new. `_gemini()` + `gemini` CLI handle everything.

### Gotchas
- **Grounding is auto-triggered**: the gemini CLI decides when to use `google_web_search` based on query content. The system prompt must be "search-heavy" enough to trigger grounding consistently — phrases like "search the web for", "find current information about" help.
- **Latency**: search-grounded responses are slower than standard generation. Expected.
- **No raw results**: Gemini returns synthesized text, not a list of `{title, url, snippet}` objects. The tool returns a research summary with citations, not a traditional search engine response.
- **Import failure = full server crash**: if `tools_search.py` has a syntax or import error, all Gemini MCP tools go down (not just search). Server.py imports at module level.

### Risks
| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Grounding doesn't trigger | Med | Low | System prompt explicitly requests web search; test with current-events queries |
| Import error crashes all MCP tools | High | Very Low | Follow exact existing pattern; run `python -c "import tools_search"` before committing |
| Response lacks citations | Med | Med | System prompt mandates `## Sources` section; verify in tests |

## Test Strategy

### Critical paths
- `web_search(query="...")` returns a non-empty string response
- System prompt is prepended to the query via `_gemini()` system_instruction parameter
- Long responses trigger `_write_detail()` and return path reference

### Edge cases
- Empty query string
- Query that doesn't trigger grounding (purely theoretical question)
- Very long response exceeding detail threshold

### Integration boundaries
- `_gemini()` subprocess interface (already tested by other tool tests)
- `_write_detail()` file output (already tested)
- server.py import chain (new import must not break existing tools)

### What NOT to test
- Actual Gemini API responses (mocked in tests)
- `_gemini()` internals (tested by existing tests)
- server.py startup mechanics beyond import verification

## Blast Radius
- **tools_search.py** (new): only `server.py` depends on it. Failure isolated to `web_search` tool unless import error.
- **server.py** (2 lines added): all MCP tools depend on this file loading. Risk mitigated by following exact existing pattern.
- Confidence: exhaustive (scout mapped all 11 modules and all registration lines)

## Success Criteria
- `web_search` tool appears in Claude Code's tool listing
- Calling `web_search(query="latest Python 3.13 features")` returns a grounded response with URLs
- Existing tools are unaffected — no regression

## Decisions
- **Search backend**: Gemini API with Google Search grounding — consistent with every other tool in the server (user decision)
- **Result format**: Synthesized markdown with citations — Gemini doesn't return raw result objects, so structured summaries with a Sources section are the output (user decision)
- **Query handling**: Literal passthrough to Gemini with search-optimized system prompt — no preprocessing layer (user decision)

## Constraints
- Must be added to existing Gemini MCP server (Python), not a separate server
- Uses Gemini API with Google Search grounding — no separate search API
- Follows `register(mcp)` pattern exactly
- No new Python dependencies
- Out of scope: separate MCP server, browser automation, scraping
