# Plan: Lightweight Pipeline with Cross-Session Recovery

## Context
The current pipeline writes `epics.json` and `todo-tracking.json` on every state transition — overhead that duplicates what Claude's built-in `TaskCreate`/`TaskList` already does within a session. Meanwhile, we lack fast check-ins on background agents and task size limits. The goal: adopt the speed of the "CEO mode" pattern (in-session task tools, check-in cadence, atomic splitting) while keeping our regression-prevention mechanisms (diff gate, protected files, epic branches) and adding cross-session recovery via exit snapshots.

---

## File: `~/.claude/ORCHESTRATION.md`

### Change 1: Drop per-transition JSON writes, use TaskList in-session

**Remove** all references to writing `todo-tracking.json` during the session. Todos are tracked via `TaskCreate`/`TaskList`/`TaskUpdate` during the session. They don't need to survive the session — stories and epics do.

**Replace** the "Fill phase" and "Run trigger" sections' JSON-writing steps with:
> During a session, use `TaskCreate` to register todos and `TaskUpdate` to track progress. Do not write to `todo-tracking.json` on every state change. Recovery snapshots handle persistence (see "Recovery Snapshots" section).

**Keep** `epics.json` (simplified — see Change 5) as the source of truth for cross-session state.

### Change 2: Add 3-minute check-in cadence

**Add** to "Agent execution rules":
> **Check-in cadence**: Ping long-running background agents every 3 minutes via `TaskOutput` with `block: false`. If an agent shows no new tool uses after 2 consecutive check-ins (6 minutes), stop it and re-split the task into smaller pieces. Do not wait 30 minutes.

**Update** stale story detection from 30 minutes to 6 minutes (2 missed check-ins).

### Change 3: Task size ceiling

**Add** to "Coder grouping decision tree":
> **Task size ceiling**: If a coder group's write-targets span >5 files or the estimated change is >200 lines, split it into 2+ atomic sub-tasks. Two 5-minute tasks are faster and more recoverable than one 15-minute task. Each sub-task gets its own `TaskCreate` entry and can run sequentially within the same worktree.

### Change 4: Ephemeral plans

**Replace** the current plan persistence rule:
> Plans are ephemeral — write to `$TMPDIR/plan-<story-id>.md`. Do not persist plans in `~/.claude/plans/`. Architecture decisions and findings that survive sessions go in `CLAUDE.md` (project) or `~/.claude/CLAUDE.md` (global). Plans are working documents, not records.

### Change 5: Simplify epics.json

**Current schema** has: `id`, `epicId`, `title`, `body`, `state`, `labels`, `branch`, `worktree`, `todos` (array of IDs), `coderGroups` (full schema with groupId, type, writeFiles, readFiles, dependsOn, status), `reviewerRetries`, `startedAt`, `stageStartedAt`.

**New schema** — story entries:
```json
{
  "id": "story-001",
  "epicId": "epic-001",
  "title": "Ghost placement accuracy",
  "state": "closed|running|filling",
  "branch": "story/ghost-placement",
  "writeFiles": ["src/handlers/stageHandlers.js", "src/components/BoardCanvas.jsx"],
  "needsTesting": false,
  "needsReview": false
}
```

**Dropped fields**: `body` (in plan file or TaskCreate description), `labels`, `worktree` (derivable from branch), `todos` (in TaskList), `coderGroups` (in TaskList), `reviewerRetries` (in-session only), `startedAt`, `stageStartedAt` (in-session only).

**Epic entries** stay the same: `id`, `title`, `branch`, `prNumber`, `persistent`.

### Change 6: Recovery snapshots (write-on-merge + exit hook)

**Add** new section "Cross-session recovery":

> **Snapshot triggers** — write `epics.json` at exactly two points:
> 1. After each story merges into the epic branch (already in the merge flow)
> 2. On session exit via the stop hook
>
> **Snapshot content** — the simplified `epics.json` with current story states. No `todo-tracking.json` — todos are session-scoped.
>
> **Recovery on session start** — when a new session starts and `epics.json` shows a story in `running` state:
> 1. Check if the story worktree still exists (`git worktree list`)
> 2. Check if there are uncommitted changes in the worktree
> 3. Report to the user: "Story X was in-flight when the last session ended. Worktree at .claude/worktrees/story/X [has uncommitted changes | is clean]. Resume or discard?"
> 4. Do not auto-resume — wait for user decision
>
> **What's lost on crash (no exit hook)**: only the in-session todo progress and current coder group status. The last merge snapshot tells the next session which stories are closed. Git state (branches, worktrees, commits) is the ground truth for anything in-flight.

### Change 7: Stop hook integration

**Modify** the existing stop hook at `/Users/kelsiandrews/.claude/tracking/stop-hook.sh` to add a recovery snapshot step. After the existing token-tracking logic, add:

```bash
# Write recovery snapshot of epics.json
# The session may have updated story states in memory —
# the epics files on disk are already current (written on merge)
# This is a safety net for stories that were running but didn't merge
```

Actually, since `epics.json` is already written on merge, and the stop hook can't access Claude's in-memory state, the hook doesn't need to write epics.json. It's already current for closed stories. For running stories, the git worktree existence is the recovery signal.

**Revised approach**: No stop hook changes needed. Recovery works from:
1. `epics.json` on disk (updated on each story merge)
2. `git worktree list` (shows in-flight story worktrees)
3. `git branch --list 'story/*' 'epic/*'` (shows active branches)

The next session reconstructs state from these three sources.

### Change 8: Drop todo-tracking.json

**Remove** all references to `todo-tracking.json` from ORCHESTRATION.md. Delete the file reference, the field reference section, and the validation rules. In-session tracking uses `TaskCreate`/`TaskList`. Cross-session recovery uses `epics.json` + git state.

### Change 9: Update orchestrator output format

The orchestrator no longer needs to produce a `todo` entry for `todo-tracking.json`. Simplify the staging payload:

```
STAGING_PAYLOAD
{
  "storyUpdate": { /* simplified story fields */ },
  "epicUpdate": { /* epic fields, if new epic */ }
}
```

The main session creates `TaskCreate` entries from the orchestrator's plan — not JSON file writes.

---

## File: `~/.claude/ORCHESTRATION.md` — sections to delete entirely

- "todo-tracking.json field reference" section
- "Main session: staging payload validation" — simplify to just validate storyUpdate fields
- "Main session in-memory state" paragraph — no longer needed (no JSON cache to manage)
- "Context clearing" rule #1 "after fill phase" — filling no longer writes JSON, so clearing isn't mandatory

---

## Verification

1. Trace a full flow: user requests feature → orchestrator classifies → `TaskCreate` entries → run trigger → epic branch → story worktree → coder (3-min check-ins) → diff gate → merge into epic → `epics.json` written → `/clear`
2. Trace recovery: session crashes mid-story → new session → read `epics.json` + `git worktree list` → detect in-flight story → ask user to resume or discard
3. Verify no references to `todo-tracking.json` remain
4. Verify diff gate, protected files, and epic branch rules are unchanged
