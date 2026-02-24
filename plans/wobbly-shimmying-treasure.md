# Plan: Context Optimization + Pipeline Hardening

## Context

Context is being consumed from multiple overlapping sources: ORCHESTRATION.md is loaded 3 times per session (startup hook, require-orch-read guard, pre-response-check skill), agent return messages have no length cap, the todo-orchestrator returns large JSON payloads inline, and sequential stories create merge conflicts because worktrees are created before their dependencies merge. The goal is to eliminate redundant loads, cap return sizes, extract fixed sequences into skills, and make late worktree creation the default for sequential stories.

---

## Part 1 — Context drain fixes

### 1a. Eliminate triple-load of ORCHESTRATION.md

**Problem**: ORCHESTRATION.md is loaded at session start via `load-session-context.sh` (cat), then required again via `require-orch-read.sh` marker check (which forces an explicit Read tool call), then read again by `pre-response-check` on relevant turns. That's ~835 lines × 3.

**Fix**: Make the startup hook set the `orch-read` marker so the guard is pre-satisfied, eliminating the forced mid-session Read. Pre-response-check becomes the post-`/clear` safety net — it re-reads when needed after a clear wipes the startup context.

**File**: `/Users/kelsiandrews/.claude/hooks/load-session-context.sh`

Add after the cat commands:
```bash
# Satisfy the orch-read guard so no explicit Read is required this session
SESSION_ID=$(echo "$CLAUDE_SESSION_ID" | tr -dc 'a-zA-Z0-9')
touch "/tmp/orch-read-${SESSION_ID}"
```

### 1b. Narrow pre-response-check trigger

**Problem**: Skill fires on nearly every turn including follow-ups and Q&A, adding ~1000 lines each time.

**Fix**: Tighten the skill description to exclude: follow-up questions in an ongoing exchange, pure Q&A with no code/pipeline action, non-project topics. Trigger only on: first workflow/pipeline question in a session, code-changing requests, run triggers, merge triggers.

**File**: `/Users/kelsiandrews/.claude/skills/pre-response-check/SKILL.md`

Update description frontmatter:
```yaml
description: >
  Invoke before responding to: (1) the first workflow or pipeline question
  in a session, (2) any code-changing request, (3) run/merge triggers,
  (4) any request where ORCHESTRATION.md rules might change the answer.
  Do NOT invoke for: follow-up questions in an ongoing exchange where
  files were already read this turn or the prior turn, pure factual Q&A
  unrelated to pipeline, simple greetings, or non-project topics.
```

Also remove the verbose body — replace with a condensed version (~15 lines) that just states the required reads and the 5 constraint bullets. The full rules live in ORCHESTRATION.md; the skill doesn't need to restate them.

### 1c. Post-/clear warm-up convention

**Problem**: `/clear` can't be hooked. After a clear, startup hook doesn't re-run, so ORCHESTRATION.md is gone from context but the marker file still exists — guard passes but content is absent.

**Fix**: Document in ORCHESTRATION.md §8 that the first message after `/clear` should be a normal request (not a special command). Pre-response-check will re-read ORCHESTRATION.md on that first relevant turn, reloading content. No special user action needed beyond `/clear` itself.

Add to ORCHESTRATION.md §8 under context clearing:
```
**Post-clear behavior**: After /clear, ORCHESTRATION.md is reloaded automatically
on the first relevant request via pre-response-check. No warm-up message needed.
The orch-read marker persists in /tmp and does not block Task/Edit/Write calls.
```

---

## Part 2 — Agent return length caps

Add to ORCHESTRATION.md §10 "Coder prompt requirements":

```
**Return length caps** (include in every agent prompt):
- Coder (success): 1 line — "done: <what changed>"
- Coder (deviation/decision): ≤5 lines
- Coder (error/blocked): uncapped — include full error output
- Reviewer (PASS): 1 line
- Reviewer (BLOCKING): ≤10 lines per finding, uncapped on error
- git-ops (success): 1 line
- git-ops (error): uncapped
- unit-tester (PASS): 1 line — "tests passed: <N> tests"
- unit-tester (FAIL): uncapped — full output required for log + re-delegation
```

---

## Part 3 — todo-orchestrator writes staging payload to file

**Problem**: Orchestrator returns a STAGING_PAYLOAD inline (30-50 lines of JSON) which lands in main session context.

**Fix**: Orchestrator writes payload to `$TMPDIR/staging-<todo-slug>.json` and returns a single line: `STAGING_PAYLOAD written to $TMPDIR/staging-<todo-slug>.json`. Main session reads the file when it needs to validate and present.

**Files to update**:
- `ORCHESTRATION.md §5` — update orchestrator output format
- `ORCHESTRATION.md §4` — update "after orchestrator completes" to read file
- `/Users/kelsiandrews/.claude/skills/todo/SKILL.md` — update step 4/5 to read file

Orchestrator output format change (§5):
```
SUMMARY
Todo: <one-line description>
Story: <storyId> — <story title> [NEW]
Epic: <epicId> — <epic title> [NEW]
Agent: <quick-fixer|architect>
Model: <haiku|sonnet|opus>
Trivial: <yes|no>
Files:
  write: <comma-separated>
  read: <comma-separated>
Plan: <one sentence>
Coder groups: <see format>
STAGING_PAYLOAD written to: $TMPDIR/staging-<todo-slug>.json
```

---

## Part 4 — New skills

Create 5 new skill files under `/Users/kelsiandrews/.claude/skills/`:

### `/run-story/SKILL.md`
Encodes the exact run trigger sequence from ORCHESTRATION.md §9:
1. Read epics.json, find story by ID
2. Check if `dependsOn` stories are all `closed` — if not, block and report
3. Assign branch if null (`story/<slug>`)
4. Pre-flight worktree check
5. Launch git-ops (background): `setup-story.sh <repo-root> <epic-slug> <story-branch> <story-slug>`
6. Wait for git-ops exit 0
7. Launch coder (background) with appropriate prompt
8. Update story state to `running` via `update-epics.sh`

Args: `story_id`

### `/merge/SKILL.md`
Encodes the merge-queue sequence from ORCHESTRATION.md §12:
1. Read epics.json, find story/stories by ID(s)
2. Verify all stories are in `running`/`testing`/`reviewing` state with passing gate
3. Build JSON manifest
4. Launch git-ops (background): `merge-queue.sh <repo-root> '<manifest>'`
5. On exit 0: update each story to `closed`, update epic `prNumber` via `update-epics.sh`
6. Output context checkpoint message

Args: `story_ids` (comma-separated)

### `/status/SKILL.md`
Read-only summary of current pipeline state:
1. Read epics.json
2. Print table: epic → stories with state, branch, needsTesting, needsReview
3. Show any `running` stories with their worktree path
4. Show any `blocked` stories

No args.

### `/recover/SKILL.md`
Encodes cross-session recovery from ORCHESTRATION.md §15:
1. Read epics.json, find any stories in `running` state
2. Run `git worktree list` to check worktree existence
3. For each running story: check `git -C <worktree> status --porcelain`
4. Report state to user with resume/discard options
5. Output context checkpoint message

No args.

### `/clear-guide/SKILL.md`
Micro-skill: just outputs the safe-to-clear decision rule and current pipeline state summary. Helps user decide if it's safe to clear.

1. Check for any background agents running (TaskList)
2. Read epics.json for running stories
3. Output: "Safe to /clear: yes/no — [reason]"

No args.

---

## Part 5 — Sequential story late worktree creation

**Problem**: When Story B `dependsOn` Story A, B's worktree is created at run trigger time (before A merges), branching off a stale epic branch tip. When A merges and B tries to rebase in merge-story.sh, conflicts arise from B's stale base.

**Fix**: For stories with `dependsOn`, delay `setup-story.sh` until all blocking stories are `closed`. When the last blocker merges, auto-launch git-ops with `setup-story.sh` at that moment — branching off the freshly-updated epic branch tip.

**Files to update**:

**`ORCHESTRATION.md §9` (Run trigger)**:
Add preflight check:
```
Before launching git-ops for setup-story.sh: if story has `dependsOn` field,
verify all listed story IDs are `closed` in epics.json. If any are not closed,
set story state to `queued` (new valid state), do not create worktree, do not
launch git-ops. When a story closes (§11 after merge), scan for `queued` stories
whose dependsOn are now all closed — auto-launch setup-story.sh + coder for each.
```

**`ORCHESTRATION.md §7`** — add `queued` to valid states:
```
filling → queued     (run triggered but dependsOn not yet closed)
queued → running     (all dependsOn stories closed — auto-triggered)
```

**`/Users/kelsiandrews/.claude/skills/run-story/SKILL.md`** — encode the `queued` check as step 2 (see Part 4 above, already included).

No changes to `setup-story.sh` itself — the script is correct. The change is purely in *when* the main session calls it.

---

## Part 5b — ExitPlanMode clear hook (already built in)

The plan approval dialog (`ExitPlanMode`) already offers "clear context" as option 1. This covers the most important clear checkpoint — after planning, before implementation. No engineering needed here.

The remaining gap is mid-session clears after a story merges. That's covered by the `/clear-guide` skill (Part 4) and the improved checkpoint messaging below.

---

## Part 6 — /clear guidance in ORCHESTRATION.md §8

Replace the buried checkpoint message with a prominent decision box at the top of §8:

```
**Safe to /clear when ALL of the following are true:**
1. No background agent is currently running
2. No agent result is needed to proceed (coder done, diff gate passed, etc.)
3. You are between stories (not mid-pipeline)

**What survives /clear**: git branches, worktrees, epics.json, all disk state.
**What is lost**: in-session memory, coder task status, agent task list.
**Recovery**: run /recover after /clear if a story was in-flight.
```

---

## Files to create/modify

| File | Action |
|---|---|
| `/Users/kelsiandrews/.claude/hooks/load-session-context.sh` | Add marker-touch after cats |
| `/Users/kelsiandrews/.claude/skills/pre-response-check/SKILL.md` | Narrow trigger, shorten body |
| `/Users/kelsiandrews/.claude/skills/todo/SKILL.md` | Read staging file instead of inline payload |
| `/Users/kelsiandrews/.claude/skills/run-story/SKILL.md` | Create new |
| `/Users/kelsiandrews/.claude/skills/merge/SKILL.md` | Create new |
| `/Users/kelsiandrews/.claude/skills/status/SKILL.md` | Create new |
| `/Users/kelsiandrews/.claude/skills/recover/SKILL.md` | Create new |
| `/Users/kelsiandrews/.claude/skills/clear-guide/SKILL.md` | Create new |
| `/Users/kelsiandrews/.claude/ORCHESTRATION.md` | §5, §7, §8, §9, §10 updates |

No changes to any scripts in `.claude/scripts/`. No changes to project source files.

---

## Verification

- Start a new session: confirm ORCHESTRATION.md content is in system-reminder and marker file exists without a manual Read
- Invoke pre-response-check on a follow-up question: confirm it does not fire
- Invoke pre-response-check on a code-change request: confirm it fires and reads once
- Run `/clear`, then make a code request: confirm pre-response-check re-reads ORCHESTRATION.md
- Run `/todo` for a story with `dependsOn` on an open story: confirm state goes to `queued`, no worktree created
- Merge the blocking story: confirm queued story auto-launches setup-story.sh
- Run `/status`: confirm it prints pipeline state without reading ORCHESTRATION.md
- Check coder return message on a successful story: confirm it is 1 line
