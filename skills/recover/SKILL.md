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
