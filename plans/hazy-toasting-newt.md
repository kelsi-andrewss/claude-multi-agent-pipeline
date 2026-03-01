# Token savings: pipeline script noise reduction

## Context

The pipeline emits several categories of verbose output that get fed back to the main
Claude session and consumed as input tokens on every story lifecycle event. The previous
plan (already implemented) silenced git network operations. Remaining sources of noise:

1. **Script echo statements** — `setup-story.sh`, `merge-story.sh`, `merge-queue.sh`,
   `diff-gate.sh` all echo diagnostic lines that are useful for human debugging but
   redundant when the main session only needs exit code + the structured sentinel line
   (e.g. `MERGED:branch:PR_NUMBER=N`).
2. **`update-epics.sh` confirmation line** — prints `epics.json updated` on every patch,
   which gets echoed back to the main session after every state transition.
3. **`merge-queue.sh` node JSON parsing** — parses the full manifest 6× per story in
   the loop instead of once.
4. **`worktree add` in `setup-story.sh`** — unsilenced; emits "Preparing worktree" line.

The highest-leverage fix is making the scripts follow a **silent-success, loud-failure**
convention: no output on success paths except the required sentinel lines; full output
only on error.

## Approach

Prefix all diagnostic `echo` lines in the success paths with a `VERBOSE` guard, so they
are suppressed unless `VERBOSE=1` is set. Keep all `echo` lines that carry structured
output the main session must parse (MERGED:, exit-code-bearing errors, etc.). Keep all
`>&2` error lines — those only appear on failure.

Separately, silence the two remaining unsilenced git commands in `setup-story.sh`.

## Changes

### 1. `setup-story.sh` — silence worktree add + verbose echoes

File: `/Users/kelsiandrews/.claude/.claude/scripts/setup-story.sh`

- Redirect `git worktree add` (line 38) and `git worktree add -b` (line 41) to
  `> /dev/null 2>&1`
- Wrap diagnostic echoes in `[ -n "$VERBOSE" ] &&` guard:
  - "Epic branch already exists" (line 26)
  - "Creating epic branch from main" (line 28)
  - "Worktree already exists" (line 34)
  - "Story branch already exists — adding worktree" (line 37)
  - "Creating story branch from epic" (line 40)
  - "Main worktree remains on" (line 47)
- Keep: "Setup complete: worktree at ..." — the main session reads this to confirm success

### 2. `diff-gate.sh` — verbose echo guard

File: `/Users/kelsiandrews/.claude/.claude/scripts/diff-gate.sh`

- Wrap in `[ -n "$VERBOSE" ] &&` guard:
  - "Rebasing ... onto ..." (line 32)
  - "Changed files in story branch:" (line 50)
  - the `echo "$CHANGED_FILES"` dump (line 51)
  - "Restoring out-of-scope file: ..." (line 65)
  - "Committing restoration of out-of-scope files" (line 74)
- Keep: "Diff gate passed" (line 95) — main session may parse this
- Keep all `>&2` error lines (lines 46, 90-91) — these only fire on failure

### 3. `merge-story.sh` — verbose echo guard

File: `/Users/kelsiandrews/.claude/.claude/scripts/merge-story.sh`

- Wrap in `[ -n "$VERBOSE" ] &&` guard:
  - "Merging ... into ... via worktree" (line 27)
  - "Updating epic PR #..." (line 60)
  - "Epic PR already exists: #..." (line 66)
  - "Creating epic PR for ..." (line 69)
  - "Removing story worktree at ..." (line 86)
  - "Deleting story branch ..." (line 91)
  - "Main worktree remains on: ..." (line 95)
- Keep: "Created epic PR #${FINAL_PR}" — needed for PR number confirmation
- Keep: "MERGED:${STORY_BRANCH}:PR_NUMBER=${FINAL_PR}" (line 96) — sentinel the
  main session parses

### 4. `merge-queue.sh` — verbose echo guard + parse manifest once

File: `/Users/kelsiandrews/.claude/.claude/scripts/merge-queue.sh`

- Wrap in `[ -n "$VERBOSE" ] &&` guard:
  - "--- Processing story: ... ---" (line 36)
- Parse manifest fields once per iteration using a single `node` call instead of
  6 separate calls (minor, but eliminates redundant JSON.parse × 6 per story):
  ```bash
  read -r STORY_BRANCH STORY_TITLE EPIC_SLUG EPIC_TITLE PR_NUMBER WRITE_FILES_JSON < <(node -e "
    const m=JSON.parse(process.argv[1])[$i];
    process.stdout.write([m.storyBranch,m.storyTitle,m.epicSlug,m.epicTitle,m.prNumber||'',JSON.stringify(m.writeFiles)].join('\t')+'\n');
  " -- "$JSON_MANIFEST" | awk -F'\t' '{print $1,$2,$3,$4,$5,$6}')
  ```
  (Keep the `readarray` for WRITE_FILES_ARR since that requires per-line output.)
- Keep: "merge-queue complete" (line 71)

### 5. `update-epics.sh` — silence success confirmation

File: `/Users/kelsiandrews/.claude/.claude/scripts/update-epics.sh`

- Line 166: change `process.stdout.write('epics.json updated\n')` to nothing, or guard
  it: `if (process.env.VERBOSE) process.stdout.write('epics.json updated\n');`
- The main session never parses this line — it only checks the exit code.

## Files to modify

- `/Users/kelsiandrews/.claude/.claude/scripts/setup-story.sh`
- `/Users/kelsiandrews/.claude/.claude/scripts/diff-gate.sh`
- `/Users/kelsiandrews/.claude/.claude/scripts/merge-story.sh`
- `/Users/kelsiandrews/.claude/.claude/scripts/merge-queue.sh`
- `/Users/kelsiandrews/.claude/.claude/scripts/update-epics.sh`

## What is preserved

- All `>&2` error output — only fires on failure, needed for diagnosis
- All sentinel lines the main session parses: `MERGED:...`, `Diff gate passed`,
  `Setup complete: worktree at ...`, `Created epic PR #N`, `merge-queue complete`
- `set -e` + exit codes — failures still abort correctly

## Verification

1. Run a full story cycle (setup → coder → diff-gate → merge-story) on a test story
2. Confirm git-ops agent output contains only sentinel lines, no diagnostic chatter
3. Set `VERBOSE=1` and re-run — confirm all suppressed echoes reappear
4. Force a failure (e.g. bad story branch) — confirm error output is still emitted
