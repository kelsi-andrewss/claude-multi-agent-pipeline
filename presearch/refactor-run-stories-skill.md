# Refactor run-stories SKILL.md

## Overview

The run-stories SKILL.md has grown to ~640 lines, mixing deterministic procedural logic (git worktree commands, build tool invocation, file comparison) with orchestration decisions (dependency ordering, failure attribution, agent coordination). This refactor extracts the procedural logic into callable Python/bash scripts, reducing SKILL.md to ~480 lines focused on policy decisions and agent management. A separate `run-state.db` provides crash-resilient execution state without polluting epics.db.

## Summary

Extract 5 procedural blocks from the 640-line run-stories SKILL.md into shared scripts under `~/.claude/scripts/`. Scripts handle deterministic operations (worktree lifecycle, build verification, merge gate mechanics, diff comparison) and emit structured JSON on stdout. SKILL.md retains orchestration decisions, agent prompt assembly, conflict reclassification, and reporting. A transient `run-state.db` persists execution state across context compaction. Shared scripts (build-verify, worktree-cleanup) also serve merge-worktree, eliminating ~100 lines of duplication across both skills.

## Features

### MVP
0. **Shared scripts foundation**: Create `worktree-setup.sh`, `worktree-cleanup.sh`, `build-verify.sh`, `diff-gate.sh` in `~/.claude/scripts/`. Establish JSON stdout contract. Unit test each script.
1. **Merge gate + run-state.db**: Create `merge-gate.py` with cherry-pick mechanics, test execution, error classification. Create `run-state.db` schema and lifecycle (init, write, read, cleanup). Integration test the merge gate.
2. **SKILL.md rewrite**: Replace procedural blocks with script invocations. Update resolution subagent prompt to use scripts for enrichment. Update merge-worktree SKILL.md to use shared scripts. Verify end-to-end equivalence.

## Technical Research

### Architecture

**Policy-Mechanism Split**: SKILL.md is the policy layer (what to do). Scripts are the mechanism layer (how to do it). The boundary is: if it requires LLM judgment or Agent tool calls, it stays in SKILL.md. If it's deterministic and testable, it goes to a script.

**State externalization**: `run-state.db` is a transient SQLite database owned entirely by the scripts. Created at run start, cleaned up at run end. Not managed by Gemini pm_* tools. Survives context compaction and session crashes. Located at `~/.claude/.claude/run-state.db`.

**Subagent delegation preserved**: Steps 1-3 (MCP-heavy resolution) are already delegated to a foreground subagent. This pattern is unchanged — the subagent now additionally calls worktree-setup.sh and enrichment scripts before returning its EXECUTION_PLAN.

### Scripts

| Script | Language | Inputs | Outputs | Purpose |
|--------|----------|--------|---------|---------|
| `worktree-setup.sh` | bash | `--project-root <path> --branch <name> --worktree-path <path> --dev-branch <name>` | JSON: `{status, worktree_path, branch, verified}` | Create worktree, verify branch. Called by resolution subagent before coder launch. |
| `worktree-cleanup.sh` | bash | `--worktree-path <path> [--branch <name>] [--force]` | JSON: `{status, removed_worktree, removed_branch}` | Remove worktree and optionally delete branch. Handles orphaned/locked states. Shared with merge-worktree. |
| `build-verify.sh` | bash | `--project-root <path>` | JSON: `{status, project_type, build_cmd, lint_cmd, build_result, lint_warnings}` | Detect project type from markers, run build/lint, return results. Shared with merge-worktree. |
| `diff-gate.sh` | bash | `--worktree-path <path> --dev-branch <name> --write-files <comma-separated>` | JSON: `{status, changed_files, expected_files, unexpected_files}` | Compare `git diff --name-only` against expected write_files list. |
| `merge-gate.py` | python | `--merge-candidate <path> --test-branch <name> --test-cmd <cmd> --test-files <comma-separated>` | JSON: `{status, test_passed, error_type, error_output, classification}` where classification is `compile_error\|logic_failure\|ambiguous` | Cherry-pick test commits, run tests, classify failures. |

### Patterns

- **JSON stdout contract**: All scripts emit a single JSON object on stdout. `status` is always `"success"` or `"error"`. `stderr` is for debug logging only — never parsed by SKILL.md.
- **Exit codes**: 0 = success, 1 = functional error (build failed, test failed — check JSON for details), 2 = system error (missing dependency, permission denied).
- **Error handling**: bash scripts use `set -euo pipefail`. Python scripts use try/except with JSON error output on all paths.
- **Arg parsing**: bash uses `getopts` or positional args. Python uses `argparse`.
- **Absolute paths**: All worktree and file references use absolute paths — never relative.

### run-state.db Schema

```sql
CREATE TABLE IF NOT EXISTS run_sessions (
    id TEXT PRIMARY KEY,          -- UUID, created at run start
    started_at INTEGER NOT NULL,  -- unix timestamp
    dev_branch TEXT NOT NULL,
    status TEXT DEFAULT 'running' CHECK(status IN ('running','done','failed','interrupted')),
    completed_at INTEGER
);

CREATE TABLE IF NOT EXISTS story_executions (
    session_id TEXT NOT NULL REFERENCES run_sessions(id),
    story_id TEXT NOT NULL,
    batch INTEGER NOT NULL,       -- execution group number
    worktree_path TEXT,
    story_branch TEXT,
    agent_id TEXT,                 -- Claude Code agent ID for resume
    step TEXT DEFAULT 'pending' CHECK(step IN ('pending','worktree_created','launched','done','blocked','need_decision')),
    result_summary TEXT,          -- DONE/BLOCKED/NEED_DECISION message
    started_at INTEGER,
    completed_at INTEGER,
    PRIMARY KEY (session_id, story_id)
);

CREATE TABLE IF NOT EXISTS batch_verifications (
    session_id TEXT NOT NULL REFERENCES run_sessions(id),
    batch INTEGER NOT NULL,
    status TEXT CHECK(status IN ('pass','fail','skipped')),
    output TEXT,                   -- last 30 lines of build output on failure
    verified_at INTEGER,
    PRIMARY KEY (session_id, batch)
);

CREATE TABLE IF NOT EXISTS merge_results (
    session_id TEXT NOT NULL REFERENCES run_sessions(id),
    story_id TEXT NOT NULL,
    diff_gate TEXT CHECK(diff_gate IN ('pass','warn','fail')),
    unexpected_files TEXT,         -- JSON array
    test_passed INTEGER,           -- 0 or 1
    error_classification TEXT,     -- compile_error, logic_failure, ambiguous, null
    test_output TEXT,              -- truncated test runner output
    retry_count INTEGER DEFAULT 0,
    merged_at INTEGER,
    PRIMARY KEY (session_id, story_id)
);
```

**Lifecycle**: SKILL.md calls `init_run_state.py --session-id <uuid> --dev-branch <name>` at run start. Scripts write their results. SKILL.md reads via `sqlite3` queries between steps. At run end (success or failure), `cleanup_run_state.py --session-id <uuid>` drops all rows for that session.

### Shared Interfaces

- `~/.claude/scripts/worktree-setup.sh` — used by: run-stories (Step 4), resolution subagent
- `~/.claude/scripts/worktree-cleanup.sh` — used by: run-stories (Step 5c), merge-worktree (Step 4)
- `~/.claude/scripts/build-verify.sh` — used by: run-stories (Step 2c, Step 4.1), merge-worktree (Step 2.5)
- Story 0 creates all shared scripts. Stories 1-2 depend on story 0.

### Dependencies

- `sqlite3` — already in use (epics-cli.sh, signal_processor.py)
- `git` — already in use (worktree operations)
- `python3` — already in use (hooks, om_write.py)
- `jq` — NOT a dependency. Scripts use `python3 -c "import json..."` for JSON manipulation to avoid adding a new tool.
- No new external dependencies.

### Gotchas

- **index.lock contention**: Parallel git operations on the same repo can race on `.git/index.lock`. Worktree-setup.sh needs retry-with-backoff (3 attempts, 1s delay) for `git worktree add`.
- **Branch locking**: Git prevents the same branch from being checked out in multiple worktrees. Scripts must verify branch isn't already in a worktree before `git worktree add`.
- **Orphaned worktrees from interrupted runs**: If a session crashes mid-run, worktrees persist. `worktree-cleanup.sh --force` handles this, and `/recover` uses it.
- **run-state.db cleanup on crash**: If the session crashes, the DB persists with stale data. Next run should check for stale sessions (status='running' with started_at > 1 hour ago) and clean them up.
- **Merge-worktree SKILL.md must be updated in the same batch** as shared script extraction to avoid divergence (conflict C1).
- **ORCHESTRATION.md §1 compliance**: Worktree-setup.sh is called by the resolution subagent (a background agent), not the main session directly. This is consistent with the prohibition's intent. Add a clarifying note to §1 if ambiguity persists.

### Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| JSON parsing failure from malformed script output | High — blocks story execution | Low — scripts are deterministic | Wrap all script calls in SKILL.md with "if JSON parse fails, log raw output and mark story BLOCKED" |
| run-state.db concurrent write from parallel scripts | Med — corrupted state | Low — SQLite WAL mode handles most cases | Scripts use `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;` |
| Regression in end-to-end behavior after SKILL.md rewrite | High — stories fail to execute | Med — large surface area change | Story 2 includes end-to-end equivalence test (TA5 from scout) |
| merge-worktree SKILL.md out of sync after shared script extraction | Med — build verify or cleanup breaks | Med — if stories ship separately | Both SKILL.md files updated in the same story (story 2) |

## Test Strategy

### Critical paths
- worktree-setup.sh creates worktree on correct branch and exits 0, or exits non-zero with JSON error
- build-verify.sh detects project type from filesystem markers and returns correct commands
- merge-gate.py cherry-picks test commits, runs tests, returns pass/fail with error classification
- diff-gate.sh compares changed files against write_files and flags unexpected changes
- Refactored SKILL.md produces identical execution plans for same story inputs as current version

### Edge cases
- worktree-cleanup.sh handles: missing .git dir, already-removed worktree, locked worktree, branch not found
- build-verify.sh handles: no recognized build system (returns skip), multiple build systems (picks first match)
- merge-gate.py handles: cherry-pick conflict (returns compile_error), empty test output (returns ambiguous)
- run-state.db: stale session cleanup on next run start

### Integration boundaries
- Script JSON output must match SKILL.md's expected schema exactly — add schema validation in SKILL.md parse steps
- run-state.db must not interfere with epics.db (separate file, separate connection)
- Shared scripts must work from both run-stories and merge-worktree invocation contexts

### What NOT to test
- Agent tool invocations — they fail obviously if the prompt is wrong
- MCP tool calls (pm_get_story, pm_check_conflicts) — tested by the subagent, not by scripts
- SKILL.md prompt formatting — verify by running the skill end-to-end

## Decisions

- **State management**: Separate run-state.db SQLite — survives compaction, keeps epics.db contract intact (user decision)
- **Coder prompt construction**: Scripts provide data blocks, SKILL.md assembles prompt (user decision)
- **Failure attribution**: Python script heuristic with compile/logic/ambiguous classification (user decision)
- **Worktree setup timing**: Pre-launch in resolution subagent, coders verify branch only (gemini recommendation + agreed)
- **Symbol conflict reclassification**: Stays inline in SKILL.md — requires semantic judgment (gemini recommendation + agreed)
- **Cross-skill reuse**: build-verify and worktree-cleanup shared with merge-worktree (gemini recommendation + agreed)
- **Script location**: `~/.claude/scripts/` (shared namespace, not skill-specific subdirs) — matches existing epics-cli.sh pattern (Claude recommendation)
- **No jq dependency**: Use python3 for JSON manipulation — avoids adding tool to the stack (Claude recommendation)

## Constraints

- bash/python scripts only — no new dependencies or build systems
- epics.db contract (ORCHESTRATION §4) inviolable — Claude writes only plan_file and state
- Agent tool calls stay in SKILL.md — scripts cannot launch agents
- No changes to worktree isolation model, Gemini/Claude architecture, or merge-worktree contract
- Auto-planning (pm_plan_story + plan-writing agents) stays in SKILL.md
- Existing subagent delegation pattern (Steps 1-3) preserved
