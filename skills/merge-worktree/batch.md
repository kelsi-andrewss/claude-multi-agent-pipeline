# Batch Mode (Subagent Delegation)

Use when caller has **2+ stories** to merge. Launch ONE foreground `general-purpose` subagent.

**Use:** run-stories Step 5c with 2+ validated stories, /ship with multiple stories completing.
**Don't use:** single `/merge-worktree story-NNN`, `/quickfix` merge step.

## Subagent prompt

Include:
1. Full text of [single.md](single.md) Steps 1–6 (the single-story merge procedure)
2. Batch story list with pre-resolved data per story: `story_id`, `title`, `epic_id`, `story-branch`, `worktree-path`, `dev-branch: dev`, `test_result`, `write_files`, `plan_file`, `acceptance_criteria`
3. ToolSearch: `select:mcp__gemini__pm_update_story,mcp__gemini__pm_update_epic,mcp__gemini__pm_get_story`
4. Queue coordination protocol (below)
5. Return format (below)

## Diff gate (per story)

```bash
DIFF_RESULT=$(bash ~/.claude/scripts/diff-gate.sh --worktree-path <worktree-path> --dev-branch <dev-branch> --write-files "<comma-separated>")
```

Non-empty `unexpected_files` → log warning, continue (non-blocking).

## Queue coordination

Merges coordinated through `merge-queue.py`. Non-conflicting stories proceed immediately; conflicting stories wait.

**Phase 0 — Stale cleanup:**
```bash
STALE=$(python3 ~/.claude/scripts/merge-queue.py status)
```
Cancel any `merging` or `queued` rows from previous sessions.

**Phase 1 — Enqueue all stories:**
Run diff gate, then:
```bash
ENQUEUE_RESULT=$(python3 ~/.claude/scripts/merge-queue.py enqueue \
  --story-id <story_id> --write-targets '<write_files_json>' --priority <priority>)
```
Priority: quickfix=2, architect=1, others=0.

**Phase 2 — Drain the queue:**
`stall_counter = 0`. Loop:
```bash
NEXT_RESULT=$(python3 ~/.claude/scripts/merge-queue.py next)
```
- `action: "next"` → merge, dequeue on success, cancel on conflict. Reset stall_counter.
- `action: "none"` + `queue_empty` → done.
- `action: "none"` + `all_blocked` → increment stall_counter. At 3 → fallback to sequential.

**Phase 3 — Report** (return format below).

## Return format

```
MERGE_SUMMARY:
  merged: [story-NNN, story-MMM, ...]
  blocked: [story-PPP (conflict: file.ts)] | none
  commit_hashes: {story-NNN: abc1234, story-MMM: def5678}
  epic_closures: [epic-NNN] | none
  warnings: ["story-NNN: unexpected files changed: foo.ts"] | none
  test_results: {story-NNN: "pass", story-MMM: "skip"}
  outcomes_logged: [story-NNN, story-MMM]
  queue_stats: {enqueued: 5, merged_via_skip: 3, waited: 2, stall_fallbacks: 0}
  regressions: {story-NNN: {checked: 3, failed: 0}} | none
```

## After batch completes

Main session:
1. Parse MERGE_SUMMARY
2. Use merged/blocked/commit_hashes for report
3. No further MCP calls needed — subagent updated DB state
4. Blocked stories go to run-stories blocked section
