---
name: recover
description: >
  Cross-session recovery: find stories that were in-flight when the last
  session ended and offer resume or discard. Use when the user says
  "/recover", "recover session", "what was running last session", or at
  session start when epics.json shows a running story.
  Encodes ORCHESTRATION.md §15 exactly.
---

# Cross-Session Recovery

Execute recovery check per ORCHESTRATION.md §15.

## Steps

1. **Read** `.claude/epics.json`. Find all stories with state `running`, `testing`, `reviewing`, or `merging`.

2. If none found: output "No in-flight stories found. Nothing to recover." and stop.

3. **Run** `git worktree list` to get all worktrees and their paths.

4. For each in-flight story:
   a. Check if the story's branch worktree exists in the worktree list.
   b. If worktree exists: run `git -C <worktree-path> status --porcelain` to check for uncommitted changes.
   c. Report:
      ```
      Story <id> (<title>) — state: <state>
        Branch: <branch>
        Worktree: <path> [exists | MISSING]
        Uncommitted changes: yes/no
      ```

5. **Ask the user** for each story: "Resume or discard?"
   - **Resume**: proceed as normal — launch pending coder tasks or continue from current pipeline step.
   - **Discard**: run `git worktree remove --force <path>` and reset story state to `filling` via `update-epics.sh`.

6. After all decisions resolved, output:
   > "Context checkpoint reached (session recovery). Run `/clear` to start fresh. All epic and story state is saved in epics.json."

---

## Extended Case: Mid-Coder Crash Recovery

Detected when: worktree exists AND has uncommitted changes AND no TaskUpdate "completed" entry exists for that coder group in the current session.

Check for the scratch file `/tmp/coder-progress-<SESSION_ID>-<story-id>.json` to reconstruct partial coder state. If it exists, read it to identify which todos were completed before the crash.

Offer the user three options:

```
Story <id> has uncommitted coder changes with no completed checkpoint.
  a) Re-launch coder with the same prompt (discard uncommitted changes and start fresh)
  b) Keep changes and proceed to diff-gate (treat as complete — use if changes look correct)
  c) Discard worktree changes (git checkout -- .) and return story to filling state
```

- Option (a): run `git -C <worktree> checkout -- .` to discard, then re-launch coder agent with original prompt.
- Option (b): run diff-gate directly. If it passes, continue normal pipeline. If it fails, fall back to option (a).
- Option (c): run `git -C <worktree> checkout -- .` and set story state to `filling` via `update-epics.sh`.

---

## Extended Case: Partial merge-queue Failure

Detected when: merge-queue.sh exited non-zero AND at least one `MERGED:` line appears before the failure in the output.

1. Parse merge-queue.sh output to identify which stories merged successfully (have `MERGED:` lines) vs which failed.
2. Mark successfully merged stories as `closed` via `update-epics.sh`.
3. Report to user:
   ```
   Partial merge completed:
     Merged: <story-branch> (story-X)
     Failed: <story-branch> (story-Y) — <error reason>
   ```
4. Offer: "Re-run merge for failed stories only" or "Discard and reset failed stories to running state."
   - Re-run: construct a new JSON manifest with only the failed stories and re-launch merge-queue.sh.
   - Discard: set failed story state to `running` via `update-epics.sh`. Leave worktree intact for investigation.
