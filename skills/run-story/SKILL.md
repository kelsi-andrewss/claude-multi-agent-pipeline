---
name: run-story
description: >
  Execute the run trigger sequence for a story. Use when the user says
  "run story-X", "run story X", or "run all open stories". Encodes
  ORCHESTRATION.md §9 exactly.
args:
  - name: story_id
    type: string
    description: "The story ID to run (e.g. story-042)."
---

# Run Story: {{story_id}}

Execute the full run trigger sequence per ORCHESTRATION.md §9.

## Steps

1. **Read** `.claude/epics.json`. Find story `{{story_id}}`. If not found, stop and report.

2. **Dependency check**: If story has a `dependsOn` field, verify every listed story ID is `closed` in epics.json. If any are NOT closed:
   - Set story state to `queued` via `update-epics.sh`
   - Report: "Story {{story_id}} queued — waiting for: [list of open blocking stories]"
   - Stop. The story will auto-launch when its last blocker merges.

3. **Assign branch**: If story `branch` is null, generate `story/<slug>` (kebab-case of title, ≤5 words). Update via `update-epics.sh`.

4. **Pre-flight worktree check** (inline):
   - Run `git worktree list` to check if worktree already exists.
   - If worktree exists AND state is `running`: run `git -C <worktree-path> status --porcelain`. If uncommitted changes and no coder tasks in-progress → warn user, do NOT launch until confirmed. If some tasks done and others pending → proceed, launch only pending tasks.
   - If worktree exists but state is NOT `running` → warn user, do not proceed.

5. **Launch git-ops** (background) with:
   ```
   Run: bash <project-root>/.claude/scripts/setup-story.sh \
     <project-root> <epic-slug> <story-branch> <story-slug>
   Report exit code and full stdout/stderr. Do not edit any files.
   ```
   Wait for git-ops to exit. If non-zero, report error and stop.

6. **Launch coder** (background, `run_in_background: true`) with appropriate prompt per ORCHESTRATION.md §10. Agent type and model from story's orchestrator recommendation. Track via `TaskCreate`/`TaskUpdate`.

7. **Update story state** to `running` via `update-epics.sh`.

8. Warn the user if the session is not in auto-edit mode before launching the coder.
