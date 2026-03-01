# Pipeline Efficiency Refinements

## Context

The development pipeline has accumulated latency at every stage. The user described slowness across the entire pipeline, not any single bottleneck. The goal is to cut wall-clock time on the three highest-impact areas: (1) /todo orchestrator overhead, (2) story setup blocking coder launch, and (3) merge pipeline sequential operations.

---

## Changes

### 1. setup-story.sh — combine two sequential git fetches into one

**File**: `/Users/kelsiandrews/.claude/.claude/scripts/setup-story.sh` (lines 25–30)

**Current**: Two separate `git fetch` calls — one for `main`, one for the epic branch.
```bash
git fetch origin main > /dev/null 2>&1 || true
...
git fetch origin "${EPIC_BRANCH}" > /dev/null 2>&1 && \
```

**Change**: Single fetch for both refs in one call:
```bash
git fetch origin main "${EPIC_BRANCH}" > /dev/null 2>&1 || true
```
Then keep the two `git update-ref` lines unchanged (they still run on the now-synced local refs).

**Why**: Each `git fetch` is a network round-trip to origin. Combining them into one refspec-list call halves the network latency at story setup time. The `|| true` guards already handle the case where the epic branch doesn't exist remotely yet — that just means origin ignores that refspec.

**Risk**: Low. `git fetch origin ref1 ref2` is standard; if `ref2` doesn't exist on origin, git prints a warning but exits 0 (with `|| true`).

---

### 2. run-story SKILL.md — launch coder without waiting for setup-story.sh

**File**: `/Users/kelsiandrews/.claude/skills/run-story/SKILL.md` (steps 6–7)

**Current** (step 6): "Wait for git-ops to exit. If non-zero, report error and stop." → coder launches only after setup completes.

**Change**: Restructure steps 6–7 so git-ops and a pre-coder prompt fire simultaneously. Coder's first action is the worktree branch-verification (`git -C <worktree> branch --show-current`) — this naturally blocks the coder until setup has created the worktree. If that check fails (worktree not ready yet), coder should retry once after a short pause before reporting failure.

New step 6:
```
6. **Launch git-ops** (background) for setup-story.sh. Do NOT wait for it to complete before step 7.

7. **Launch coder** (background) immediately. The coder prompt already requires:
   > Before doing anything else, verify: run `git -C <worktree-path> branch --show-current`
   > If that path does not yet exist, wait up to 10 seconds (check every 2s) then retry.
   > If it prints anything other than `<story-branch>` after 10s, STOP and report branch mismatch.

8. **Wait for git-ops exit code** (background result, non-blocking). If non-zero: report error AND send stop signal to coder (TaskStop). Else: continue.
```

**Why**: The worktree-verification step in the coder prompt is the natural synchronization point. The coder cannot do any file reads until it verifies the worktree exists. For a story with 3–5 files to read, the coder spends ~0.5–2s on initial reads while setup completes in the background. In the common case these overlap completely.

**Risk**: Medium. The coder's first step must actually be the worktree-verify (already required by §10 enforcement block). The new retry logic is safe: `git -C <path> branch --show-current` returns an error if `<path>` doesn't exist, so the check is reliable.

---

### 3. /todo SKILL.md — skip orchestrator for unambiguous single-story requests

**File**: `/Users/kelsiandrews/.claude/skills/todo/SKILL.md`

**Current**: Step 1.5 tries to fast-lane to `/hotfix` or `/quickfix`, but if neither qualifies, always spawns the orchestrator (a foreground Haiku agent) even when the main session already has full context.

**Change**: Add a "direct-stage" path between fast-lane and orchestrator. Before spawning the orchestrator, check:

> **Direct-stage check** (after fast-lane pre-screen fails): If ALL of these are true:
> - Write-target files are explicitly named in the request (no "figure out which files" needed)
> - Root cause stated (no investigation needed)
> - No schema/frame/AI changes
> - Files are not protected
> - A single best-fit epic is unambiguous from epics.json
>
> → Main session builds the STAGING_PAYLOAD inline (no orchestrator agent), using the pattern from `~/.claude/refs/staging-schema.md`. Assign next story ID, pick quick-fixer as agent, set state `draft`. Write via `update-epics.sh`. Skip steps 3–4.
>
> **Ambiguity rule**: If any doubt about file scope, epic assignment, or coder grouping → fall through to orchestrator as before.

**Why**: The orchestrator agent's value is classifying ambiguous requests, deduplicating, and applying §10 grouping rules. For clear requests (e.g., "fix the X bug in src/foo.py") the main session can produce the staging payload in zero agent round-trips. This removes one full foreground agent invocation — typically the slowest single step.

**Risk**: Low, because the ambiguity rule is conservative. Any doubt → orchestrator. The direct-stage path only fires when all five signals are unambiguous.

Also keep the epics.json read-once constraint added earlier (already done).

---

### 4. diff-gate.sh — skip redundant `git fetch origin` when called from merge-queue

**File**: `/Users/kelsiandrews/.claude/.claude/scripts/diff-gate.sh` (line 29)

**Current**: Every diff-gate call does `git fetch origin` — when `merge-queue.sh` calls diff-gate in a loop for N stories, that's N fetch calls to origin.

**Change**: Accept an optional env var `SKIP_FETCH=1` to bypass the fetch. Update `merge-queue.sh` to:
1. Do one `git fetch origin` before the loop
2. Pass `SKIP_FETCH=1` when calling diff-gate for all but the first story

In `diff-gate.sh`, wrap the fetch block:
```bash
if [ -z "$SKIP_FETCH" ]; then
  git fetch origin 2>/dev/null || git fetch 2>/dev/null || true
  git update-ref refs/heads/main origin/main 2>/dev/null || true
fi
```

In `merge-queue.sh`, add before the loop:
```bash
git -C "$PROJECT_ROOT" fetch origin > /dev/null 2>&1 || true
git -C "$PROJECT_ROOT" update-ref refs/heads/main origin/main 2>/dev/null || true
export SKIP_FETCH=1
```

**Why**: For a 3-story merge queue, this eliminates 2 redundant network fetches. Each fetch is a TLS handshake + round-trip to GitHub; saves ~300–600ms per extra story.

**Risk**: Low. The one upfront fetch still syncs everything. The per-story fetch was defensive redundancy; removing it doesn't affect correctness since the rebase in diff-gate uses local refs.

---

## Files Modified

| File | Change |
|------|--------|
| `.claude/scripts/setup-story.sh` | Lines 25–30: combine two fetches into one |
| `.claude/scripts/diff-gate.sh` | Lines 29–31: wrap fetch in `SKIP_FETCH` guard |
| `.claude/scripts/merge-queue.sh` | Add one-time fetch before loop, export `SKIP_FETCH=1` |
| `skills/run-story/SKILL.md` | Steps 6–8: parallel git-ops + coder launch |
| `skills/todo/SKILL.md` | Step 1.5 → add direct-stage path before orchestrator |

---

## What's Deliberately NOT Changed

- **merge-queue.sh inner loop**: Sequential within an epic is correct — each merge must complete before the next story rebases. This is not a bug.
- **Orchestrator for ambiguous requests**: The orchestrator catches duplicates and applies §10 grouping. Only clear requests bypass it.
- **30s batch merge window**: Left as-is; it's a user-comfort policy not a performance issue.
- **update-epics.sh full-file writes**: Atomic; ~50ms total per story. Not worth complicating.

---

## Verification

1. Run a story through the full pipeline with `VERBOSE=1` on setup-story.sh — confirm one fetch line instead of two.
2. Trigger a `/todo "fix X in src/foo.py"` with explicit filename — confirm no orchestrator agent spawns in the transcript.
3. Merge 3 stories in a queue — confirm only one `git fetch origin` appears in diff-gate output (first story fetches, second and third skip).
4. Run a story and observe the git-ops + coder launch in the same turn, confirming they're parallel.
