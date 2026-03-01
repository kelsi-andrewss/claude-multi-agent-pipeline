---
name: run-stories
description: >
  Execute stories in parallel (where safe) using background agents, each working in
  an isolated git worktree branched from a shared dev branch. Handles dependency
  ordering, write-file conflict detection, and reports results.
  Use when the user says "/run-stories", "/run-stories story-NNN", "/run-stories epic-NNN",
  or any combination of story and epic IDs.
args:
  - name: args
    type: string
    description: >
      Optional. Zero or more space-separated tokens: story-NNN IDs, epic-NNN IDs,
      or nothing (runs all ready/draft stories across all active epics).
---

# Run Stories Skill Invoked

User has requested: `/run-stories {{args}}`

---

## Step 1: Resolve story list

Parse each token in `{{args}}`:

- **`story-\d+`** → call `pm_get_story(id)`, collect the story object
- **`epic-\d+`** → call `pm_list_stories(epic_id=...)`, collect all non-archived stories
- **No args** → call `pm_list_epics(state="active", include_stories=true)`, collect all stories where `state` is `draft` or `ready`

After collecting, validate each story and **skip with a warning** if any of the following:
- `plan_file` is null or empty:
  - Load `ToolSearch: select:mcp__gemini__pm_plan` and call `pm_plan(story_id=<id>)` for all unplanned stories **in parallel** (single message).
  - Wait for all `pm_plan` calls to complete.
  - Launch one background `general-purpose` agent per unplanned story to write the plan file (same prompt as draft-plan Step 5).
  - Wait for all agents to complete, then re-fetch each story to confirm `plan_file` is now set.
  - If still missing after auto-planning, skip with warning: "story-NNN: auto-planning failed — skipping."
- `agent` is null or empty — warn: "story-NNN has no agent assigned — set it with pm_update_story"
- `agent` is `"manual"` — note: "story-NNN requires manual execution — skipping"
- `state` is `done`, `archived`, or `in-progress` — note: "story-NNN is already {state} — skipping"

Deduplicate by story ID. If the list is empty after validation, stop and report all skips with reasons.

---

## Step 2: Determine execution groups

Build an execution plan from two analyses:

### 2a. Dependency ordering (topological sort)

- **Group 0**: stories with no `depends_on`, or all dependencies already `done`
- **Group 1**: stories whose `depends_on` entries are all in Group 0
- **Group N**: stories whose `depends_on` entries are all in earlier groups
- If a story's dependency is in a **different epic** and not yet `done`, warn the user:
  > "story-NNN depends on story-MMM from a different epic that is not done. Run that story first, or proceed anyway?"
  Use `AskUserQuestion` to ask whether to skip or include it. If skip → add to skips.

### 2b. File conflict detection (within each dependency group)

For each dependency group:
1. Collect `write_files` arrays for all stories in the group
2. Build a conflict map: story A conflicts with story B if they share any path in `write_files`
3. Split the group into **parallel batches** using a greedy graph coloring approach:
   - Batch 0: stories with no conflicts among themselves
   - Subsequent batches: stories that conflict with something in batch 0 (run after batch 0 finishes)
   - Continue until all stories in the group are placed
4. Within each sequential batch, order stories by ID (lowest first) for determinism

**Display the full execution plan before running:**
```
Execution plan:
  [Dep Group 0 | Batch 0 — parallel]        story-001, story-003
  [Dep Group 0 | Batch 1 — sequential]      story-002  (conflicts: src/foo.js with story-001)
  [Dep Group 0 | Batch 2 — sequential]      story-004  (no direct conflict with story-002, but story-005 conflicts with both — serialized for safety)
  [Dep Group 1 | Batch 0 — after group 0]   story-005
```

> **Note:** A story may be placed in a later sequential batch even if it doesn't directly conflict with the story immediately before it. This happens when a downstream story conflicts with *both*, forcing them into a strict order. Stories are always chained safely to prevent merge conflicts.

If any skips occurred, list them after the plan. Ask the user to confirm before proceeding.

---

## Step 3: Ensure dev branches exist

First, ensure the `dev` integration branch exists:

```bash
git fetch origin
git show-ref --verify --quiet refs/heads/dev || git branch dev origin/main
git push -u origin dev 2>/dev/null || true
```

For each unique epic referenced by the stories being run:

1. Compute `dev-branch`:
   - Call `pm_get_epic(epic_id)` to get the epic title
   - Slugify: lowercase, replace spaces and non-alphanumeric chars with `-`, collapse consecutive `-`, truncate to 40 chars
   - Result: `dev/<slugified-title>` (e.g., `dev/my-feature-epic`)
   - If slugification fails or title is empty, fall back to `dev/<epic_id>` (e.g., `dev/epic-007`)

2. Run these git commands (in the project root):
   ```bash
   git show-ref --verify --quiet refs/heads/dev/<slug> || git branch dev/<slug> dev
   git push -u origin dev/<slug> 2>/dev/null || true
   ```

Store the mapping: `epic_id → dev-branch` for use in step 4.

---

## Step 4: Execute groups in order

Process each dependency group sequentially. Within each group, process conflict batches:

### For each parallel batch — launch all stories simultaneously

Launch all stories in the batch in **a single message** as `general-purpose` agents with `run_in_background: true`.

Compute for each story:
- `story-slug`: lowercase title, replace spaces/special chars with `-`, collapse consecutive `-`, truncate to 40 chars
- `epic-slug`: the slugified epic title used in step 3 (same slugification rule)
- `story-branch`: `dev/<epic-slug>/<story-slug>`
- `worktree-path`: `<project-root>/.claude/worktrees/story/<story-slug>`
- `dev-branch`: from the epic mapping computed in step 3
- `agent-approach`: based on the `agent` field:
  - `quick-fixer` → "Make surgical, minimal changes. No refactoring beyond what the plan specifies."
  - `architect` → "Make full architectural changes as specified in the plan. Follow all structural decisions."
  - anything else → "Follow the plan exactly."

Each background agent receives this prompt (fill all placeholders before launching):

```
You are executing story <story_id>: "<title>"

Plan file: <plan_file>
Agent approach: <agent-approach>
Dev branch: <dev-branch>
Story branch: <story-branch>
Worktree path: <worktree-path>
Write files scope: <write_files list, or "not specified">
Project root: <project-root>

## Steps

1. Read the plan file at `<plan_file>`. Understand what changes are required.

2. Create the story worktree using direct git commands:

   ```bash
   cd <project-root>
   git fetch origin <dev-branch>
   git show-ref --verify --quiet refs/heads/<story-branch> || git branch <story-branch> <dev-branch>
   git worktree list | grep -q '<worktree-path>' || git worktree add <worktree-path> <story-branch>
   ```

3. Work **exclusively** inside `<worktree-path>`. Never edit files in `<project-root>` directly.

4. Implement the plan: <agent-approach>
   - Focus on the files listed in the write scope if provided
   - Do not modify files outside the write scope unless the plan explicitly requires it

5. Stage and commit all changes inside the worktree:
   ```bash
   git -C <worktree-path> add -A
   git -C <worktree-path> commit -m "<story_id>: <title>"
   ```

6. Push the story branch:
   ```bash
   git -C <worktree-path> push -u origin <story-branch>
   ```

7. Update the story state in the database:
   Call: pm_update_story("<story_id>", state="done")

8. Return exactly one of:
   - Success: "DONE: <story-branch> pushed. Commit: <short-hash>. Notes: <any relevant notes or 'none'>"
   - Failure: "BLOCKED: <clear reason why the story could not be completed>"
```

### For sequential batches (conflict serialization)

After the previous batch completes, before launching the next story:

1. Check if its worktree exists yet (it may have been created). If the previous story in the conflict chain pushed changes, sync the dev branch into this story's branch:
   ```bash
   git fetch origin <dev-branch>
   ```
   If the story's branch already exists in the worktree, run:
   ```bash
   git -C <worktree-path> rebase origin/<dev-branch>
   ```
   If the rebase produces conflicts (non-zero exit), report:
   > "story-NNN: rebase on <dev-branch> produced conflicts — skipping. Resolve manually."
   Skip that story (mark BLOCKED) and continue.

2. Launch the story agent as described above.

---

## Step 5: Collect results and report

Wait for all background agents to complete. Then print a final summary:

```
Run complete.

Dev branch(es): dev/my-feature

story-001 → dev/my-feature/fix-auth-flow        DONE    commit abc1234
story-003 → dev/my-feature/update-dashboard     DONE    commit def5678
story-002 → dev/my-feature/refactor-handlers    DONE    commit ghi9012  [sequential — conflicted with story-001 on src/handlers/foo.js]
story-005 → dev/my-feature/add-search           BLOCKED plan file references missing utility

Skipped (validation):
  story-004: no plan file — run `/draft-plan` first
  story-006: state is 'done' — already complete

Blocked during execution:
  story-005: plan file references missing utility function `buildSearchIndex`
```

If all stories complete successfully, print: "All stories executed successfully."

If any story is BLOCKED, list it with its reason in a "Blocked" section. Never stop other stories due to one failure — they run independently.
