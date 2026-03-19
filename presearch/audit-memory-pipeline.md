# Audit: Memory Pipeline Bug Fixes

## Problem Statement
**What problem?** The memory/correction pipeline has 7 correctness bugs: decision shadows are immediately pruned (feedback_score=0), budget enforcement is non-atomic (data loss on crash), correction counts are doubled per session, project root is computed wrong (breaks auto-distillation), signal processing logic is duplicated, and a hash function is misnamed.

**Why fix it?** The semantic memory persistence guarantee is hollow — `pm_add_decision` writes entries that get pruned within 24 hours. Correction counts are inflated 2x per session, causing premature preference promotion. Auto-distillation looks in `~/epics.db` instead of `~/.claude/.claude/epics.db`.

**Why integral?** OpenMemory is one of only 3 persistence surfaces (decision-79). If it doesn't persist decisions, the entire learning loop is broken — sessions can't recall prior decisions, corrections inflate, and the system degrades with use rather than improving.

**End goal:** Memory pipeline correctly persists decisions (surviving prune cycles), counts corrections exactly once per session, and computes correct paths for auto-distillation.

## Overview

Seven bugs identified by the code audit, all in the memory/correction pipeline. Grouped into 3 stories by subsystem: om_write core integrity, stop_processor orchestration, and infrastructure paths/naming. All fixes have exact file/line locations and 5 recorded decisions constraining the approach.

## Summary

Fix 7 bugs across 4 files in the memory/correction pipeline. Story 1: make om_write budget enforcement atomic and route decision shadows through om_write() per decision-104. Story 2: remove duplicate process_session_corrections call from stop_processor stage 2, extract shared signal logic per decision-43/75. Story 3: fix dirname count (2 not 3) at 3 locations, rename _compute_simhash to _content_hash. Stack: Python 3 + sqlite3 (hooks/lib), FastMCP (MCP server). No external dependencies or research needed.

## Features

### MVP
1. **OpenMemory write integrity + shadow routing** — Make enforce_budget atomic with insert (BUG-5), route _om_shadow_decision through om_write() (BUG-6/BUG-11 per decision-104). Requires sys.path fix in tools_knowledge.py to import from hooks/lib/. **Write:** `hooks/lib/om_write.py`, `mcp-servers/gemini/tools_knowledge.py`
2. **Stop processor orchestration cleanup** — Remove duplicate process_session_corrections call from stage_signal_processing (R-7), extract shared logic so stop_processor delegates to signal_processor.main_logic() (CQ-6 per decision-43/75). **Write:** `hooks/lib/stop_processor.py`, `hooks/lib/signal_processor.py`
3. **Path resolution + naming** — Fix dirname count from 3→2 at signal_processor.py:388, :732 and stop_processor.py:144 (BUG-10). Rename _compute_simhash→_content_hash in om_write.py (CQ-10). **Write:** `hooks/lib/signal_processor.py`, `hooks/lib/stop_processor.py`, `hooks/lib/om_write.py`

## Technical Research

### Architecture
- **om_write()** is the canonical write gate: tag whitelist validation, 0.85 cosine dedup, per-tag budget limits, default feedback_score=0.5 (salience param). API: `om_write(content, tags, user_id, sector, salience, decay_lambda) → id or None`
- **stop_processor** runs 3 stages via nohup: correction_detection → signal_processing → distillation. Launched by `hooks/stop-session.sh`
- **signal_processor.py** owns `process_session_corrections()` — the single entry point for correction detection (decision-43, decision-75)
- **tools_knowledge.py** registers MCP tools including `pm_add_decision`. Currently bypasses om_write with direct INSERT

### Patterns
- **DB access**: `sqlite3.connect(path, timeout=10)` + cursor queries. No ORM. Use `with conn:` for transactions
- **Error handling**: `print(..., file=sys.stderr)` for all hook-level errors. Silent failures are the norm (runs async via nohup)
- **Imports across boundaries**: MCP server at `mcp-servers/gemini/` needs `sys.path.insert` to import from `hooks/lib/`. This is the pattern for decision-104's fix
- **Naming**: private functions prefixed with `_`. Module-level constants UPPER_CASE

### Dependencies
- `sqlite3` (stdlib) — all DB access
- `hashlib` (stdlib) — content hashing
- `ollama` — embeddings via HTTP (fallback when unavailable)
- `fastmcp` — MCP server framework

### Gotchas
- `om_write()` opens/closes connection up to 3x per call — budget fix should use a single connection passed through
- `_om_shadow_decision` bypass means decision shadows have been effectively non-persisted since the feature was built
- Removing duplicate `process_session_corrections` call halves all correction counts going forward — existing inflated counts in DB remain
- `_content_hash` rename touches 4 call sites in om_write.py — must update all references

### Risks
| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| om_write() import fails in MCP server | High — pm_add_decision breaks | Low — sys.path pattern exists | Test import in MCP server startup |
| Halved correction counts break promotion threshold | Med — some corrections take longer to promote | Med — threshold is count >= 3 | Acceptable — correct counts are better than inflated |
| Transaction change affects om_write callers | High — all OM writes affected | Low — API unchanged, only internal behavior | Verify stop_processor + hook_generator callers still work |

### Cost Estimate
**Development complexity:**
| Feature | Size | Notes |
|---------|------|-------|
| 1. Write integrity + shadow routing | M | Transaction refactor + cross-boundary import |
| 2. Orchestration cleanup | S | Remove call + extract function |
| 3. Paths + naming | S | Mechanical find-replace at known locations |

## Test Strategy

### Critical paths (from scout testable assertions)
- om_write() wraps enforce_budget delete + new entry insert in a single `with conn:` transaction
- _om_shadow_decision calls om_write() — no raw `INSERT INTO memories` in tools_knowledge.py
- project_root uses exactly 2 dirname calls on db_file, not 3
- process_session_corrections called exactly once per session stop (grep stop_processor.py)
- No entries with feedback_score=0 written to openmemory.sqlite

### Edge cases
- enforce_budget when budget is not exceeded (no deletes needed, just insert)
- om_write when Ollama is unavailable (falls back to _content_hash for dedup)
- process_session_corrections with empty transcript (no corrections found)
- dirname resolution when db_file path has trailing slash

### Integration boundaries
- om_write() API contract unchanged: `(content, tags, user_id, sector, salience, decay_lambda) → id or None`
- stop_processor stage pipeline order preserved: correction_detection → signal_processing → distillation
- MCP server tool registration unaffected — only internal implementation of pm_add_decision changes

### What NOT to test
- MCP tool registration wiring — fails obviously at server startup
- Hook shell script invocations — integration-level, not unit-testable
- Embedding quality — Ollama model behavior is external

## Blast Radius

- **hooks/lib/om_write.py**: Callers: `stop_processor.py` (2 calls), `hook_generator.py` (2 calls). If breaks → all OpenMemory writes fail silently (stderr only). Decision shadows, tool learnings, session summaries stop persisting. Confidence: exhaustive
- **hooks/lib/stop_processor.py**: Caller: `hooks/stop-session.sh` (nohup). If breaks → corrections not detected, preferences not updated, session learning stops silently. Confidence: exhaustive
- **hooks/lib/signal_processor.py**: Callers: `stop_processor.py` (imports process_session_corrections), `load-session-context.sh` (calls main()). If breaks → correction counts wrong, auto-distillation fails. Confidence: exhaustive
- **mcp-servers/gemini/tools_knowledge.py**: Caller: `server.py` (registers tools). If breaks → pm_add_decision MCP tool errors out, all decision recording fails. Confidence: exhaustive

## Success Criteria
- Decision shadows survive prune cycles (query openmemory.sqlite after session stop — decision entries present with feedback_score >= 0.5)
- Correction counts match actual corrections in transcript (not 2x inflated)
- Auto-distillation finds and reads `~/.claude/.claude/epics.db` (not `~/epics.db`)
- Budget enforcement + insert is atomic — no partial state possible

## Constraints
- Python 3 + sqlite3 stdlib for all hook-level code
- FastMCP + google-genai for MCP server
- om_write.py is canonical write gate — all writers must use it (decision-104)
- signal_processor.py owns correction detection — stop_processor delegates (decision-43, decision-75)
- fcntl.flock for stop_processor lockfile — do not contradict (decision-103)
- Out of scope: BUG-1/2 (shell injection), BUG-3/4 (SQLite concurrency), BUG-7/8/9 (PM tool bugs)

## Decisions
- **decision-104**: Shadow decision writes route through om_write() (active, pre-existing)
- **decision-43**: Correction detection single source of truth in signal_processor.py (active, pre-existing)
- **decision-75**: Correction pipeline unified into signal_processor.py (active, pre-existing)
- **decision-79**: 3 persistence surfaces only (active, pre-existing)
- **decision-103**: fcntl.flock advisory locking for stop_processor (active, pre-existing)

## Reference
- AUDIT.md — source audit report with full bug descriptions and line numbers
- .scope-audit-memory-pipeline.json — scope artifact
- .clarify-audit-memory-pipeline.json — clarify artifact
- presearch/.scout-audit-memory-pipeline.json — scout artifact with completeness data
