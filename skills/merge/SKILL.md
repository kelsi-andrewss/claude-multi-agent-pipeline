---
name: merge
description: >
  Merge one or more stories into their epic branch. Use when the user says
  "merge story-X", "merge story X and Y", or after diff gate passes.
  Encodes ORCHESTRATION.md §12 exactly.
args:
  - name: story_ids
    type: string
    description: "Comma-separated story IDs to merge (e.g. story-042,story-043)."
---

# Merge: {{story_ids}}

Execute the merge-queue sequence per ORCHESTRATION.md §12.

## Steps

1. **Read** `.claude/epics.json`. Find each story in `{{story_ids}}`. Report any not found and stop.

2. **Verify state**: Each story must be in `running`, `testing`, `reviewing`, or `merging` state. If any are not, report and stop.

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
   - Set story state to `closed` via `update-epics.sh`

7. **Check epic auto-close**: If all stories in an epic are now `closed`, the epic is complete — note this to the user.

8. **Unblock queued stories**: Scan epics.json for `queued` stories whose `dependsOn` are now all `closed`. For each: auto-launch `setup-story.sh` + coder (background). Notify the user.

9. Output: "Context checkpoint reached (story merged). Run `/clear` to reset the session. All epic and story state is saved in epics.json."
