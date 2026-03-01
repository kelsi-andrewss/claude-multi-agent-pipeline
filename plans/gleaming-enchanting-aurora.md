# Plan: Add `audit` tool to Gemini MCP Server

## Context

The Gemini MCP server (`mcp-servers/gemini/server.py`) currently has 6 tools (gemini_generate, gemini_chat, fetch_doc, plan, analyze, test). There's a separate Claude Code `/audit` skill that launches a Claude subagent, but we want a Gemini-powered MCP tool that can analyze codebases without ever writing code. It should auto-discover requirements/research docs and produce a structured markdown report.

## Files to Modify

- `mcp-servers/gemini/server.py` — add constants, 4 helpers, 1 tool
- `mcp-servers/gemini/test_server.py` — add test classes for new code

## Reference Files (read-only)

- `~/.claude/AUDIT-PROMPT.md` — base audit prompt loaded at runtime

---

## Implementation

### 1. Add constants (after `NO_CODE_INSTRUCTION`, ~line 22)

```
AUDIT_PROMPT_PATH = Path.home() / ".claude" / "AUDIT-PROMPT.md"
MAX_CODE_BYTES = 200_000        # source code budget
MAX_CONTEXT_BYTES = 50_000      # requirements/research budget
DEFAULT_IGNORE_DIRS = {".git", "node_modules", ".venv", "__pycache__", "build", ...}
DEFAULT_IGNORE_EXTENSIONS = {".pyc", ".png", ".jpg", ".lock", ".so", ...}
SOURCE_EXTENSIONS = {".py", ".dart", ".ts", ".js", ".tsx", ".jsx", ".go", ...}
VALID_AUDIT_SECTIONS = {"quality", "bugs", "completeness", "security"}
```

### 2. Add `_discover_files(paths, ignore_patterns)` → `list[Path]`

- If `paths` provided: resolve each relative to `PROJECT_ROOT`, walk dirs recursively
- If `paths` is None: walk `PROJECT_ROOT`
- Skip dirs in `DEFAULT_IGNORE_DIRS`, files with extensions in `DEFAULT_IGNORE_EXTENSIONS`
- Only include files with extensions in `SOURCE_EXTENSIONS`
- Apply `ignore_patterns` via `fnmatch`
- Sort by file size ascending (maximize file count within budget)

### 3. Add `_read_files_within_budget(file_list, budget)` → `(content_str, skipped_paths)`

- Iterate files, read each with `encoding="utf-8", errors="replace"`
- Include whole files only (never truncate mid-file)
- Format: `### <relative_path>\n\n<content>\n\n---`
- Track skipped files for reporting

### 4. Add `_load_audit_context()` → `str`

Dynamic filesystem scan (not tied to DOCUMENTS dict):
- Look for `REQUIREMENTS.md`, `ARCHITECTURE.md`, `BOUNTY.md` at `PROJECT_ROOT`
- Scan for `project_requirements_and_research/` dir — load all `.md` files inside
- Concatenate with headers, truncate total to `MAX_CONTEXT_BYTES`
- Return empty string if nothing found (audit still works, just no completeness check)

### 5. Add `_load_audit_prompt()` → `str`

- Read `~/.claude/AUDIT-PROMPT.md` if it exists
- Fallback: embed a minimal audit prompt covering quality, bugs, completeness, priority levels, and report structure

### 6. Add `audit()` tool

```python
@mcp.tool()
async def audit(
    paths: list[str] | None = None,           # specific files/dirs (default: full project)
    sections: list[str] | None = None,         # filter: "quality", "bugs", "completeness", "security"
    summary_only: bool = False,                # executive summary only
    ignore_patterns: list[str] | None = None,  # globs to exclude
    model: str | None = None,                  # override gemini model
) -> str:
```

**Flow:**
1. Validate `sections` if provided → return error string for invalid values
2. `_discover_files(paths, ignore_patterns)` → error if empty
3. `_read_files_within_budget(files, MAX_CODE_BYTES)` → code content + skipped list
4. `_load_audit_context()` → requirements/research context
5. `_load_audit_prompt()` → base prompt
6. Compose full prompt:
   - `[System: NO_CODE_INSTRUCTION + audit_prompt + section_filter + summary_instruction]`
   - `## Project Context\n<context>`
   - `## Files Under Audit\n<code>`
   - `## Skipped Files\n<list>` (if any)
7. `await _gemini(full_prompt, model=model)` → report
8. Write report to `PROJECT_ROOT / "AUDIT-GEMINI.md"`
9. Return the report content

**Error handling** (return strings, not exceptions):
- Invalid sections → `"Error: invalid section(s): ..."`
- No files found → `"Error: no source files found to audit."`
- Non-existent path → `"Error: path not found: ..."`
- `_gemini()` errors pass through as-is

### 7. Add tests to `test_server.py`

**TestDiscoverFiles** (~7 tests): temp dirs with various file types, ignore patterns, explicit paths, sort order

**TestReadFilesWithinBudget** (~5 tests): budget enforcement, skipped list, formatting, encoding errors

**TestLoadAuditContext** (~4 tests): finds docs at PROJECT_ROOT, handles missing gracefully, truncation

**TestLoadAuditPrompt** (~3 tests): reads from disk, fallback when missing

**TestAuditTool** (~10 tests): NO_CODE_INSTRUCTION enforcement, full/scoped audit, section filters, summary_only, model passthrough, error cases, prompt structure, skipped files noted, file write

---

## What This Tool Does NOT Do

- Never generates or writes code
- No git-diff scoping (v1 — paths only)
- No Flutter auto-detection (generic prompt only)
- No DOCUMENTS dict dependency (dynamic filesystem scan)
- No subagent orchestration (single Gemini call)

## Verification

1. Run existing tests: `cd mcp-servers/gemini && .venv/bin/python3 -m pytest test_server.py -v`
2. Run new tests: same command, verify all pass
3. Manual smoke test: start the server and call `audit()` with no args on a small project
4. Verify `AUDIT-GEMINI.md` is written and report is returned
5. Test with `sections=["bugs"]` and `summary_only=True` to confirm filtering works
