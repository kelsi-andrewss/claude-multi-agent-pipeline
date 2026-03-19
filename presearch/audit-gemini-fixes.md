# Audit Gemini Fixes — PM Tool Bugs, Code Quality, Resilience

## Problem Statement
**What problem?** Two audit reports (AUDIT.md and AUDIT-GEMINI.md) identified 11 findings in the PM tools and MCP server: 3 correctness bugs in PM tools (BUG-7 unbounded recursion in cycle detection with dep wipe, BUG-8 pm_triage always-empty backlog with epic_id, BUG-9 hardcoded task IDs causing collision), 4 code quality issues (CQ-1 duplicated embedding utils, CQ-4 three identical _ensure_column functions, CQ-5 stale CHECK constraint, CQ-7 globals().update obscuring tools), 1 flag (CQ-11 format_response.py approaching decomposition), and 3 resilience gaps (silent embedding failures, cost calc defaulting to Opus pricing, unvalidated hook JSON input).

**Why fix it?** BUG-7 can crash the MCP server with RecursionError on normal dep management. BUG-8 makes pm_triage useless when scoped to an epic. BUG-9 silently drops tasks due to UNIQUE constraint violations. Silent embedding failures cascade to corrupted/missing OpenMemory entries. Cost calc overestimates Haiku costs by 12x.

**Why integral?** PM tools are the planning backbone — every story creation, dependency graph, and triage cycle depends on these working correctly. Embedding failures silently degrade the memory pipeline. Cost tracking drives budget decisions.

**End goal:** All 11 items resolved. PM tools produce correct results under all inputs. Embedding failures are logged. Cost calc recognizes all model families. Hook JSON parsing has a shared helper.

## Overview
Targeted fix pass across 6-9 files in the MCP server, hooks, and tracking modules. Three story groups: PM tool correctness (3 bugs), MCP server code quality (4 issues + 1 flag), and resilience improvements (3 gaps). All fixes follow patterns already established in the codebase — no new architectural concepts.

## Summary
Fix 11 findings from two audit reports. Group 1: PM tool correctness — convert _detect_cycles to iterative DFS and preserve valid deps on cycle detection, fix pm_triage WHERE contradiction, use _add_task_to_story consistently. Group 2: MCP code quality — deduplicate embedding utils, consolidate _ensure_column, remove stale CHECK, remove globals().update, flag format_response.py. Group 3: Resilience — log embedding failures, add Haiku pricing to cost calc, create shared hook JSON parser.

## Features

### Story 1: PM Tool Correctness (BUG-7, BUG-8, BUG-9)

**Write targets:** `tools_pm_helpers.py`, `tools_pm_organize.py`, `tools_pm_write.py`

1. **BUG-7: Fix _detect_cycles and _set_story_deps** (`tools_pm_helpers.py` lines 265-326)
   - Convert `_detect_cycles` from recursive DFS to iterative DFS with explicit stack
   - Current recursive `dfs()` inner function (line 276) will blow Python's 1000-deep recursion limit on large dep graphs
   - In `_set_story_deps` (line 316-324): currently deletes ALL deps of story_id when any cycle is detected. Fix to only remove the newly-inserted deps that participate in the cycle, preserving pre-existing valid deps
   - The function loads the full adjacency list from story_dependencies table (line 267), builds adj dict (line 268-270), then runs DFS from every unvisited node (line 291-293)

2. **BUG-8: Fix pm_triage backlog query** (`tools_pm_organize.py` lines 133-136)
   - Current query: `WHERE s.epic_id = 'epic-backlog' AND s.epic_id = ?` when epic_id is given — impossible condition
   - Fix: skip backlog query when epic_id is given (`if not epic_id: ... else: backlog_rows = []`)
   - Other triage sections (unassigned lines 139-143, draft_without_tasks lines 145-155) already use `epic_filter` correctly

3. **BUG-9: Use _add_task_to_story in pm_create_story and pm_plan_items** (`tools_pm_write.py` lines 162-169, 338-344)
   - Replace hardcoded `task_id = f't{i}'` with calls to `_add_task_to_story(conn, story_id, task_title)`
   - `_add_task_to_story` already imported (line 27), already used in `pm_add_task` (line 231) and `_apply_plan_to_story` (helpers line 478)
   - Same fix needed in `pm_plan_items` (line 338-344) which has the same hardcoded pattern

### Story 2: MCP Server Code Quality (CQ-1, CQ-4, CQ-5, CQ-7, CQ-11)

**Write targets:** `tools_knowledge.py`, `tools_pm_helpers.py`, `server.py`, `format_response.py`

1. **CQ-1: Deduplicate embedding utilities** (`tools_knowledge.py` lines 32-46)
   - `_get_embedding()` (30s timeout) and `_embedding_to_blob()` are identical to `hooks/lib/embedding_utils.py` `get_embedding()` (10s timeout) and `embedding_to_blob()`
   - Fix: add sys.path insert for project root, import from `hooks.lib.embedding_utils`. Delete local definitions.
   - `_om_shadow_decision` (line 49-90) catches all exceptions, so import failure is safe

2. **CQ-4: Consolidate _ensure_*_column functions** (`tools_pm_helpers.py` lines 329-363)
   - Three functions with identical structure: `_ensure_order_idx_column`, `_ensure_read_files_column`, `_ensure_test_files_column`
   - Consolidate into `_ensure_column(conn, table, name, col_type, default=None)`
   - `_ensure_epic_columns` (line 365) already uses a loop — extend pattern
   - Called only from `startup_migrate` (lines 58-60)

3. **CQ-5: Remove stale CHECK constraint** (`tools_pm_helpers.py` lines 406-413)
   - `_ensure_knowledge_tables` creates patterns table with `CHECK (category IN ('react', 'firebase', 'css', 'konva', 'architecture', 'general', 'python-mcp', 'skill-markdown', 'claude-md'))`
   - Migration v5 (line 135-158) removes this constraint. Initial table creation should match v5 target schema
   - Fix: change to `category TEXT NOT NULL` without CHECK

4. **CQ-7: Remove globals().update** (`server.py` lines 28-62)
   - 12 calls to `globals().update(_r_*(mcp) or {})`. FastMCP registers tools at `@mcp.tool()` decoration time
   - No code imports tool functions from server.py by name (verified by grep)
   - Fix: replace with plain calls, e.g., `_r_gemini(mcp)` — discard return values

5. **CQ-11: Flag format_response.py** (`format_response.py`)
   - 853 lines, 21 fmt_* functions. Approaching decomposition threshold
   - Fix: add TODO comment at module top. No code change

### Story 3: Resilience Improvements (Gemini-High, Gemini-Medium-1, Gemini-Medium-2)

**Write targets:** `hooks/lib/embedding_utils.py`, `tracking/cost.py`, `hooks/lib/parse_hook_input.py` (new)

1. **Gemini-High: Log embedding failures** (`hooks/lib/embedding_utils.py` lines 10-19)
   - `get_embedding()` returns None on any error with zero logging. 10+ callers silently degrade
   - Fix: add `print(f"embedding: {type(e).__name__} — {e}", file=sys.stderr)` in the except block
   - Keep None return for backward compatibility — all callers handle None correctly
   - `om_write.py` already logs "ollama_fallback" at line 65, but only after the first None propagates through dedup_check

2. **Gemini-Medium-1: Fix cost calc** (`tracking/cost.py` lines 1-7)
   - Only checks `if 'opus' in model`, else Sonnet pricing ($3/$15)
   - Haiku ($0.25 input, $1.25 output) gets charged at Sonnet rates — 12x overestimate
   - Fix: add explicit `'haiku' in model` branch with correct pricing ($0.25/$0.3125/$0.025/$1.25). Add `'sonnet' in model` check. Default unknown models to Sonnet with stderr warning
   - Callers: `tracking/write-turns.py`, `tracking/cost-summary.py`, `tracking/generate-charts.py`, `tracking/backfill.py`

3. **Gemini-Medium-2: Create hook JSON parsing helper** (`hooks/lib/parse_hook_input.py` — new file)
   - 10+ hooks copy-paste `echo "$INPUT" | python3 -c "import sys, json; d = json.load(sys.stdin); print(d.get('tool_input', {}).get('file_path', ''))"` with `2>/dev/null`
   - Fix: create `parse_hook_input.py` — reads stdin JSON, extracts dot-path field, prints result, exits 0 on any error
   - Usage: `VALUE=$(echo "$INPUT" | python3 "$CLAUDE_ROOT/hooks/lib/parse_hook_input.py" tool_input.file_path)`
   - Migrate 2-3 hooks as proof of concept. Full migration is follow-up work

## Technical Research

### Key Code Locations
| Bug | File | Lines | Function |
|-----|------|-------|----------|
| BUG-7 | tools_pm_helpers.py | 265-294 | `_detect_cycles` — recursive DFS |
| BUG-7 | tools_pm_helpers.py | 297-326 | `_set_story_deps` — dep wipe on cycle |
| BUG-8 | tools_pm_organize.py | 133-136 | pm_triage backlog query |
| BUG-9 | tools_pm_write.py | 162-169 | pm_create_story task insertion |
| BUG-9 | tools_pm_write.py | 338-344 | pm_plan_items task insertion |
| CQ-1 | tools_knowledge.py | 32-46 | `_get_embedding`, `_embedding_to_blob` |
| CQ-1 | hooks/lib/embedding_utils.py | 10-34 | `get_embedding`, `embedding_to_blob` |
| CQ-4 | tools_pm_helpers.py | 329-363 | Three `_ensure_*_column` functions |
| CQ-5 | tools_pm_helpers.py | 406-413 | Patterns CREATE TABLE with CHECK |
| CQ-7 | server.py | 28-62 | 12 `globals().update(...)` calls |
| CQ-11 | format_response.py | 1-853 | Full file — flag only |
| G-Hi | hooks/lib/embedding_utils.py | 10-19 | `get_embedding` — silent except |
| G-M1 | tracking/cost.py | 1-7 | `compute_cost` — Opus/Sonnet only |
| G-M2 | hooks/*.sh | various | 10+ inline JSON parsers |

### Dependency Graph
- `_detect_cycles` <- `_set_story_deps` <- `_apply_plan_to_story`, `pm_create_story`, `pm_update_story`
- `_set_story_deps` <- `tools_pm_write.py`, `tools_pm_plan.py`
- `_add_task_to_story` <- `tools_pm_write.py` (pm_add_task, _apply_plan_to_story), `tools_pm_ship.py`
- `get_embedding` <- `om_write.py`, `signal_processor.py`, `stop_processor.py`
- `_get_embedding` <- `_om_shadow_decision` <- `pm_add_decision`
- `compute_cost` <- `write-turns.py`, `cost-summary.py`, `generate-charts.py`, `backfill.py`

### Existing Patterns to Follow
- **_add_task_to_story** (tools_pm_helpers.py line 433): Correct MAX-based task ID generation — use this everywhere
- **_ensure_epic_columns** (tools_pm_helpers.py line 365): Loop pattern for column additions — extend to cover all
- **om_write.py logging** (line 65): `print(f"om_write: ...", file=sys.stderr)` — follow for get_embedding logging

### Gotchas
- **_detect_cycles iterative DFS**: Must handle multi-node cycles (A->B->C->A), not just direct cycles (A->B->A). The current recursive DFS correctly handles these via in_stack tracking — the iterative version needs equivalent state
- **_set_story_deps selective removal**: Need to track which deps were newly inserted vs pre-existing. Currently deletes all then re-inserts (line 308-313), so "newly inserted" = the full depends_on list passed in. On cycle detection, only remove deps where the story_id is in the cycle path
- **CQ-1 import path**: MCP server runs from `mcp-servers/gemini/`. Project root is `~/.claude`. Need `sys.path.insert(0, str(Path(__file__).resolve().parents[2]))` to reach `hooks/lib/`
- **Cost calc model strings**: Actual model strings in tracker data include versions like "claude-3-5-sonnet-20241022", "claude-3-haiku-20240307", "claude-opus-4-6". The `'opus' in model` check works for all Opus variants; `'haiku' in model` works for all Haiku variants

## Test Strategy

### Testable Assertions
1. `_detect_cycles` on 500-node linear chain completes without RecursionError
2. `_detect_cycles` correctly finds cycle in A->B->C->A
3. `_set_story_deps` with one cyclic dep and two valid deps keeps the valid deps
4. `pm_triage(epic_id='epic-42')` returns non-empty unassigned/draft sections when matching stories exist
5. `pm_triage(epic_id=None)` returns backlog stories from epic-backlog
6. `pm_create_story(tasks=['a','b'])` + `pm_add_task(title='c')` creates t1, t2, t3 — no collision
7. `tools_knowledge.py` contains no `def _get_embedding` or `def _embedding_to_blob`
8. Only one `def _ensure_column` exists (no `_ensure_order_idx_column` etc.)
9. Patterns CREATE TABLE has no `category IN` CHECK constraint
10. `server.py` contains no `globals()` calls
11. `get_embedding()` logs to stderr when Ollama is unreachable
12. `compute_cost(1000000, 1000000, 0, 0, 'claude-3-haiku')` returns ~1.50 not ~18.00
13. `parse_hook_input.py` returns empty string on invalid JSON, exits 0

### What NOT to test
- Hook registration in settings.json — fails obviously
- Full hook behavior (shell test infra doesn't exist — manual verification)
- format_response.py decomposition — flag only, no code change

## Blast Radius
- **Story 1 — PM correctness** (HIGH): _detect_cycles and _set_story_deps affect all dep management across pm_create_story, pm_update_story, pm_plan_story, pm_plan_stories, pm_plan_bulk. pm_triage fix is isolated. Task ID fix is low-risk (uses existing function).
- **Story 2 — Code quality** (LOW-MEDIUM): All changes are startup-only or static. CQ-1 import change affects _om_shadow_decision which already catches all exceptions. CQ-7 globals removal — verified no external imports.
- **Story 3 — Resilience** (MEDIUM): Embedding logging adds no behavior change. Cost calc fix affects dashboard numbers (correct direction). Hook parser is new file — no existing code depends on it until migration.
- **Confidence:** Exhaustive. All callers mapped via grep. All 11 files read in full.

## Success Criteria
- `_detect_cycles` handles 500-node graphs without stack overflow
- `_set_story_deps` preserves valid deps when rejecting cyclic deps
- `pm_triage(epic_id=X)` returns matching stories (not empty)
- `pm_create_story` + `pm_add_task` produces unique task IDs
- No duplicated embedding functions between tools_knowledge.py and embedding_utils.py
- One consolidated `_ensure_column` function
- No category CHECK constraint in patterns table creation
- No `globals().update` in server.py
- Embedding failures visible in stderr
- Haiku cost calc uses correct pricing ($0.25/$1.25 per 1M tokens)
- Hook JSON parser exists and handles malformed input gracefully

## Constraints
- No DB migration framework — fix schema issues inline
- CQ-11 is flag-only — no format_response.py decomposition in this epic
- Hook JSON parser: create helper + migrate 2-3 hooks; full migration is follow-up
- All PM tool fixes must preserve existing function signatures
- MCP server Python only — no new dependencies

## Decisions
- **Iterative DFS approach**: Use explicit stack + visited/in_stack sets mirroring current recursive logic. Return list[list[str]] cycle paths for backward compatibility with existing callers.
- **Selective dep removal**: Track newly-inserted dep IDs. On cycle detection, only remove those IDs that appear in the cycle path. If no newly-inserted deps are in the cycle, remove all newly-inserted deps (conservative fallback).
- **Embedding dedup approach**: Import from hooks/lib via sys.path insert. Accept 10s timeout (Ollama should be loaded by session start). Fall back gracefully if import fails.
- **Cost model matching**: Use substring matching (`'haiku' in model`, `'sonnet' in model`, `'opus' in model`). Covers all version strings observed in tracker data.
- **Hook parser scope**: New file + 2-3 proof-of-concept migrations. Full 10-hook migration is separate work.
