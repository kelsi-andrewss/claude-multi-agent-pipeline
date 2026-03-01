# Pipeline Capability Expansion — Comprehensive Plan

## Context

The multi-agent pipeline at `~/.claude/` is architecturally sound but has known gaps across four dimensions: doc/code inconsistencies that cause confusion, thin error recovery that relies on manual re-attachment, missing new-capability features that would reduce friction, and soft enforcement that lets the pipeline be bypassed. This plan covers a full capability expansion across all four areas.

---

## Epic Structure

One epic: `epic/pipeline-expansion`

Stories are grouped by theme and ordered by dependency. Most can run in parallel within a theme.

---

## Theme 1: Bug Fixes & Doc Sync (run first — unblocks everything else)

### Story 1A — Fix ORCHESTRATION.md doc bug + sync agent files
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**Files (write):**
- `~/.claude/ORCHESTRATION.md`
- `~/.claude/agents/epic-planner.md`
- `~/.claude/agents/unit-tester.md`
- `~/.claude/KNOWN-ISSUES.md`

**Changes:**
1. `ORCHESTRATION.md §13`: change `gh pr merge --merge` → `gh pr merge --squash --delete-branch`
2. `epic-planner.md`: add integration surface reconciliation algorithm (currently only in ORCHESTRATION.md §19.2, not in agent file)
3. `unit-tester.md`: add simple-fix policy decision logic (when to fix inline vs re-delegate) — currently missing
4. `KNOWN-ISSUES.md`: mark the `--merge` bug as resolved

### Story 1B — Replace TaskUpdate hook stub with real context-check script
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**Files (write):**
- `~/.claude/hooks/context-check.sh` (new)
- `~/.claude/settings.json`

**Changes:**
- Replace the `echo 'Context check...'` stub in `settings.json` PostToolUse/TaskUpdate with a real shell script
- Script checks `/tmp/stories-closed-<SESSION_ID>` counter; increments on each TaskUpdate where status=completed; if count ≥ 3, echoes the standardized clearing message
- Wire in `settings.json` pointing to `hooks/context-check.sh`

---

## Theme 2: Error Recovery & Resilience

### Story 2A — Mid-coder crash recovery skill
**Agent**: architect | **Model**: sonnet | **Trivial**: no

**Files (write):**
- `~/.claude/skills/recover/SKILL.md` (extend existing)

**Changes:**
Extend `/recover` to handle two additional cases beyond the current "story was running at session start":
1. **Mid-coder crash**: worktree exists + has uncommitted changes + no TaskUpdate for that coder group → offer: (a) re-launch coder with same prompt, (b) keep changes and proceed to diff-gate, (c) discard worktree changes
2. **Partial merge-queue failure**: story A merged, story B failed rebase → surface exactly which stories merged vs failed; offer: re-run merge-queue for failed stories only, or discard and reset

Add a `/tmp/coder-progress-<SESSION_ID>-<story-id>.json` scratch file that coders write on each TaskUpdate so recovery can reconstruct partial state.

### Story 2B — Rebase conflict detection and pause protocol
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**Files (write):**
- `~/.claude/ORCHESTRATION.md` (§12 and §14)

**Changes:**
Document the rebase conflict pause protocol explicitly:
1. When merge-queue.sh exits non-zero on a rebase step: surface the exact conflicting files, pause pipeline for that epic branch, leave all other epic branches running
2. User resolution path: `git -C <worktree> rebase --continue` or `--abort` → then re-run merge for that story
3. Batch merge window: extend from 10s to 30s to reduce rebase races on fast-finishing parallel stories

### Story 2C — Reviewer blocked-story resume protocol
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**Files (write):**
- `~/.claude/ORCHESTRATION.md` (§11 Escalation section)

**Changes:**
Document the full `blocked → running` recovery path:
1. How user manually resets: `update-epics.sh '{"storyId":"story-X","fields":{"state":"running"}}'`
2. Whether the same coder is re-launched or user provides new instructions
3. Whether the reviewer retry budget resets after user intervenes (answer: no — budget is per-story, not per-session)

---

## Theme 3: New Capabilities

### Story 3A — Cost alert hook
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**Files (write):**
- `~/.claude/hooks/cost-alert.sh` (new)
- `~/.claude/settings.json`

**Changes:**
- New `Stop` hook (runs alongside existing stop-hook.sh) that reads the `tokens.json` updated by the tracker
- If today's `estimated_cost_usd` exceeds a configurable threshold (default: $5.00), prints a warning to stderr: `[cost-alert] Today: $X.XX / threshold: $Y.YY — consider reviewing usage`
- Threshold stored in `~/.claude/hooks/cost-alert-config.json` so user can change it without editing the script
- Wire into `settings.json` as second `Stop` hook entry

### Story 3B — Draft PR creation before merge
**Agent**: architect | **Model**: sonnet | **Trivial**: no

**Files (write):**
- `~/.claude/skills/merge/SKILL.md` (extend)
- `~/.claude/ORCHESTRATION.md` (§12)

**Changes:**
Add an optional `--draft` flag to the `/merge` skill:
- When used, merge-queue.sh creates the epic PR as a **draft** (`gh pr create --draft`) instead of a ready PR
- Draft PRs are visible on GitHub but not merge-ready; useful for review before the epic is complete
- Auto-converts draft → ready when user says "merge epic X" (via `gh pr ready <prNumber>` before `gh pr merge`)
- Document the draft→ready transition in ORCHESTRATION.md §12 and §13

### Story 3C — Diff preview before coder runs
**Agent**: architect | **Model**: sonnet | **Trivial**: no

**Files (write):**
- `~/.claude/skills/run-story/SKILL.md` (extend)
- `~/.claude/ORCHESTRATION.md` (§9)

**Changes:**
Add a "pre-flight summary" step to the run-story sequence before launching coders:
- After worktree is created (setup-story.sh exits 0), print a structured summary:
  ```
  Story: <title>
  Agent: quick-fixer | architect
  Write targets: <list>
  Read context: <list>
  Protected files: <any in write targets?>
  Estimated scope: <line count estimate from plan>
  ```
- User sees this before any file changes are made
- Add `--no-preview` flag to skip for experienced users

### Story 3D — `/lint` skill for pre-commit checks
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**Files (write):**
- `~/.claude/skills/lint/SKILL.md` (new)

**Changes:**
New skill `/lint [story-id]` that:
1. Finds the story worktree path from epics.json
2. Runs `npm run lint` (or project linter) from the worktree
3. Surfaces errors inline; skips if no linter configured
4. Used as a quick pre-merge sanity check without running full unit-tester pipeline

---

## Theme 4: Tighter Enforcement

### Story 4A — Smarter guard-direct-edit.sh
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**Files (write):**
- `~/.claude/hooks/guard-direct-edit.sh`

**Changes:**
Current guard only allows edits to `~/.claude/`, `.claude/`, `/tmp/`, and `worktrees/`. Improve it:
1. Parse the active story's `writeFiles` list from `epics.json` (read from disk)
2. If the file being edited is NOT in `writeFiles` AND is NOT in `~/.claude/` or `/tmp/`, **block** with: `[guard] <file> is not in this story's writeFiles. Add it to the plan or edit in the correct worktree.`
3. Graceful fallback: if `epics.json` can't be found or no story is running, warn-only (don't block)
4. This catches scope creep at the Edit/Write level before it reaches the diff gate

### Story 4B — Protected-file enforcement hook
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**Files (write):**
- `~/.claude/hooks/guard-protected-files.sh` (new)
- `~/.claude/settings.json`

**Changes:**
New `PreToolUse` hook for `Edit|Write` that checks against the Tier 1 protected Konva file list:
- `BoardCanvas.jsx`, `StickyNote.jsx`, `Frame.jsx`, `Shape.jsx`, `LineShape.jsx`, `Cursors.jsx`
- If a write targets any of these files, **block** with: `[guard] <file> is a protected Konva file. Grant explicit permission in the current session first.`
- Permission signal: if `/tmp/konva-permission-<SESSION_ID>-<filename>` exists, allow
- Permission is granted by the main session writing that file when user says "I grant permission to edit X"
- Add to `settings.json` as second `Edit|Write` PreToolUse hook entry (runs after existing guard)

### Story 4C — `warn-sync-heavy-bash.sh` → detect + suggest background flag
**Agent**: quick-fixer | **Model**: haiku | **Trivial**: no

**Files (write):**
- `~/.claude/hooks/warn-sync-heavy-bash.sh`

**Changes:**
Current hook just warns. Improve it to:
1. Detect the specific command type (npm run build, npm test, git push, npx vitest)
2. Suggest the exact corrected call with `run_in_background: true` included in the output
3. Also detect `find`, `grep`, `cat`, `head`, `tail` — suggest the dedicated tools (Glob, Grep, Read) instead
4. Keep as `async: true` (warn-only, never blocks)

---

## Implementation Order & Dependencies

```
Theme 1 (1A, 1B) — run first, no dependencies
  ↓
Theme 2 (2A, 2B, 2C) — run in parallel after Theme 1
Theme 3 (3A, 3D) — run in parallel after Theme 1 (no Theme 2 dependency)
  ↓
Theme 3 (3B, 3C) — depend on 2A/2B for recovery context
Theme 4 (4A, 4B, 4C) — run in parallel, depend only on 1A for ORCH.md baseline
```

Stories 2A, 2B, 2C, 3A, 3D, 4A, 4B, 4C can run in parallel after Theme 1 completes.
Stories 3B and 3C should run after 2A+2B have established the recovery/pause protocol.

---

## Verification

After all stories merge:
1. **Bug fixes**: Read ORCHESTRATION.md §13 and confirm `--squash --delete-branch`; read `epic-planner.md` and confirm §19.2 algorithm is present
2. **Context-check hook**: Trigger 3 TaskUpdate completions in a session, confirm clearing message appears
3. **Cost alert**: Manually set threshold to $0.01 in `cost-alert-config.json`, end session, confirm warning in output
4. **Guard (scope)**: Try editing a file not in any story's writeFiles — confirm block message
5. **Guard (Konva)**: Try editing `BoardCanvas.jsx` without permission file — confirm block
6. **Diff preview**: Run `/run-story` on any open story, confirm pre-flight summary prints before coders launch
7. **Lint skill**: Run `/lint` from a project with a linter, confirm output

---

## Files Modified Summary

| File | Stories |
|------|---------|
| `ORCHESTRATION.md` | 1A, 2B, 2C, 3B, 3C |
| `KNOWN-ISSUES.md` | 1A |
| `agents/epic-planner.md` | 1A |
| `agents/unit-tester.md` | 1A |
| `hooks/guard-direct-edit.sh` | 4A |
| `hooks/warn-sync-heavy-bash.sh` | 4C |
| `hooks/context-check.sh` (new) | 1B |
| `hooks/cost-alert.sh` (new) | 3A |
| `hooks/guard-protected-files.sh` (new) | 4B |
| `settings.json` | 1B, 3A, 4B |
| `skills/recover/SKILL.md` | 2A |
| `skills/merge/SKILL.md` | 3B |
| `skills/run-story/SKILL.md` | 3C |
| `skills/lint/SKILL.md` (new) | 3D |
