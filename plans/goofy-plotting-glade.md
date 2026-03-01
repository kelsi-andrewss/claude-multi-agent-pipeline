# Apply Guide Recommendations to Pipeline

## Context

Two Gauntlet guides were reviewed:
1. **Improved Session Persistence** — recommends a 3-layer defense: CLAUDE.md directive, /todo skill, PreToolUse hook
2. **Orchestrator Context Management** — recommends sub-agent delegation, ORCHESTRATION.md checkpoints, PostToolUse TaskUpdate hook

**Current state vs. guide recommendations:**

| Guide recommendation | Already implemented? |
|---|---|
| Layer 2: `/todo` skill | Yes — fully built |
| Layer 3: PreToolUse block hook | Yes — `guard-direct-edit.sh` already does the *advanced* worktree-scoped version |
| ORCHESTRATION.md checkpoints (§8) | Yes — 5 trigger points already defined |
| PostToolUse TaskUpdate hook | Yes — `context-check.sh` counts stories and prompts at 3 |
| Layer 1: CLAUDE.md mandate at top | **No — missing** |

**Only one thing is unimplemented**: the Layer 1 CLAUDE.md directive. The global `~/.claude/CLAUDE.md` has no "CRITICAL WORKFLOW MANDATE" block at the top priming the orchestrator role before any user input.

---

## Change

Add a CRITICAL WORKFLOW MANDATE block to the **top** of `~/.claude/CLAUDE.md` (before all other content).

The block should:
- Establish the orchestrator identity ("you are a pipeline orchestrator")
- State that direct edits to source files are blocked (true — `guard-direct-edit.sh` enforces this)
- Point to `/todo` as the entry point for code changes
- Be short enough to scan instantly (3-5 lines of substance)

**File**: `~/.claude/CLAUDE.md` — prepend only, no other changes

---

## Exact content to prepend

```markdown
# CRITICAL WORKFLOW MANDATE

You are a pipeline orchestrator. Do NOT edit, write, or create source files directly.
ALL code changes go through the pipeline — use `/todo "description"` to initiate any change.
Direct edits to source files are blocked by hooks. The pipeline is the only path.

---

```

This matches the guide's Layer 1 intent while staying accurate to actual enforcement (hooks do block, not just suggest).

---

## Files to modify

- `~/.claude/CLAUDE.md` — prepend the mandate block (6 lines)

No other files need changes.

---

## Verification

After the edit, open a fresh session and confirm:
1. The mandate block appears at the top of the loaded CLAUDE.md context
2. The pipeline identity is established before any user input is processed
3. Attempting a direct edit in a project source file still hits `guard-direct-edit.sh` (unchanged)
