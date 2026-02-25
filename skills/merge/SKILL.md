---
name: merge
description: >
  Merge one or more stories into their epic branch. Use when the user says
  "merge story-X", "merge story X and Y", or after diff gate passes.
  Encodes ORCHESTRATION.md §12 exactly. Supports optional --draft flag to
  create the epic PR as a draft instead of a ready PR.
  To merge the epic branch into main, use /merge-epic instead.
args:
  - name: story_ids
    type: string
    description: "Comma-separated story IDs to merge (e.g. story-042,story-043). Optionally append --draft to create a draft epic PR."
---

# Merge: {{story_ids}}

Execute the merge-queue sequence per ORCHESTRATION.md §12.

## Draft flag

If `--draft` is present in `{{story_ids}}`:
- Extract the story IDs (everything before `--draft`)
- Pass `DRAFT_PR=true` context to the merge sequence
- The epic PR will be created as a draft (`gh pr create --draft`)
- Draft PRs are visible on GitHub but not merge-ready — useful for review before the epic is complete
- When the user later says "merge epic X", the main session runs `gh pr ready <prNumber>` to convert draft → ready BEFORE running `gh pr merge --squash --delete-branch`

## Steps

1. **Read** `.claude/epics.json`. Find each story in `{{story_ids}}` (strip `--draft` flag first). Report any not found and stop.

2. **Verify state**: Each story must be in `in-progress`, `in-review`, or `approved` state. If any are not, report and stop.

3. **Group by epic**: Stories targeting different epic branches can be processed in separate parallel git-ops agents. Stories targeting the SAME epic branch must go into one `merge-queue.sh` call — never run two agents on the same epic branch simultaneously.

4. **Build JSON manifest** for each epic group:
   ```json
   [
     {
       "storyBranch": "<branch>",
       "storyTitle":  "<title>",
       "epicSlug":    "<epic-slug>",
       "epicTitle":   "<epic title>",
       "prNumber":    "<existing PR number or empty string>",
       "writeFiles":  ["<file1>", "<file2>"]
     }
   ]
   ```

5. **Launch git-ops** (background) per epic group:
   ```
   Run: bash <project-root>/.claude/scripts/merge-queue.sh \
     <project-root> '<json-manifest>'
   Report exit code and full stdout/stderr. Do not edit any files.
   ```

6. **On exit 0**: For each `MERGED:<storyBranch>:PR_NUMBER=<n>` line in output:
   - Update epic's `prNumber` in epics.json via `update-epics.sh` (if changed)
   - Set story state to `done` via `update-epics.sh`

6a. **Branch cleanup**: For each merged story branch, delete it locally and remotely:
    ```bash
    git -C <project-root> branch -D <story-branch> 2>/dev/null || true
    git -C <project-root> push origin --delete <story-branch> 2>/dev/null || true
    git -C <project-root> worktree prune
    ```
    Use `-D` because squash merges are not recognized as merged by git's ancestry check. Skip silently if the branch is already gone.
    Run this even when `merge-queue.sh` handles the merge — it is a no-op if the branch was already deleted by the script.

7. **Check epic auto-close**: If all stories in an epic are now `done`, the epic is complete — note this to the user. Set epic state to `done`.

8. **Unblock ready stories**: Scan epics.json for `ready` or `draft` stories whose `dependsOn` are now all `done`. For each: auto-launch `setup-story.sh` + coder (background). Notify the user.

9. Output: "Context checkpoint reached (story merged). Run `/clear` to reset the session. All epic and story state is saved in epics.json."

10. **Cleanup ephemeral files**: Delete any `$TMPDIR` files whose slug matches a merged story. For each merged story slug, run:
    ```
    rm -f $TMPDIR/staging-<slug>.json $TMPDIR/epic-plan-<slug>.md $TMPDIR/planning-<slug>.md
    ```
    Use `rm -f` — do not fail if files are absent. This prevents unbounded accumulation of ephemeral pipeline files in the OS temp directory.
