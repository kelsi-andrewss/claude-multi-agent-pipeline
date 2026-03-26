# Resolution Phase

Delegate Steps 1–3 and enrichment to a single foreground `general-purpose` subagent. This keeps verbose MCP JSON out of main-session context.

## Subagent prompt contents

Include in the subagent prompt:
1. The full text of Step 1 (story resolution), Step 2 (execution groups), and Step 3 (dev branch) from this file
2. The enrichment instructions from [execute.md](execute.md) § Enrichment reference
3. The resolved `{{args}}` value and project root path
4. ToolSearch: `select:mcp__gemini__pm_get_story,mcp__gemini__pm_view,mcp__gemini__pm_list_stories,mcp__gemini__pm_check_conflicts,mcp__gemini__pm_dev_branch,mcp__gemini__pm_list_patterns` and `select:mcp__openmemory__openmemory_query`
5. For each story in the execution plan, pre-create the worktree:
   ```bash
   WORKTREE_RESULT=$(bash ~/.claude/scripts/worktree-setup.sh --project-root <project-root> --branch <story-branch> --worktree-path <worktree-path> --dev-branch <dev-branch>)
   ```
   Include result status in STORIES data. If setup fails, mark SKIPPED.

Launch: `Agent(subagent_type="general-purpose", prompt=<constructed>)` — **foreground**.

If NEEDS_PLANNING stories returned: handle auto-planning in main session (call `pm_plan_story` + launch plan-writing agents), then re-fetch each story.

## Required return format

```
EXECUTION_PLAN:
  bootstrap: story-NNN | none
  dev_branch: dev
  groups:
    - batch: 0, parallel: [story-NNN, story-MMM], sequential: []
    - batch: 1, parallel: [], sequential: [story-PPP after story-NNN (conflict: file.ts)]

STORIES:
  story-NNN:
    title: ...
    agent: quick-fixer
    plan_file: /abs/path/plan.md
    write_files: [file1.ts, file2.ts]
    story_branch: epic-slug--story-slug-NNN
    worktree_path: /abs/path/.claude/worktrees/story/story-slug-NNN
    epic_slug: epic-slug
    pitfalls: |
      <formatted pm_list_patterns output, or "none">
    learnings: |
      <formatted openmemory_query output, or "none">
    read_only_context: [path1, path2] | []
    gitignore_warnings: [warning] | []
    worktree_status: success | error:<message>

NEEDS_PLANNING: [story-XXX] | none
SKIPPED: story-AAA (reason) | none
DEFERRED: story-CCC depends on story-DDD | none
WARNINGS: text | none
```

After parsing, proceed to bootstrap gate (if detected) then execute phase.

---

## Step 1: Resolve story list

Parse each token in `{{args}}`:

- **`story-\d+`** → call `pm_get_story(id)`, read detail file
- **`epic-\d+`** → call `pm_list_stories(epic_id=...)`, collect all non-archived stories
- **No args** → call `pm_view(detail="summary")`, collect stories where `state` is `draft` or `ready`

**Skip with warning** if:
- `state` is `done` or `archived`
- `state` is `in-progress` (claimed by another session)
- `agent` is null/empty or `"manual"`
- `plan_file` is null/empty → auto-plan via background agents, skip if still missing
- `test_files` null/empty AND `needs_testing` not explicitly `false` → BLOCK

**Session claim**: After validation, claim all eligible stories:
```
For each eligible story:
  pm_update_story(story_id, state="in-progress", force=True)
```

The state transition is the lock — concurrent sessions see `in-progress` and skip.

Deduplicate by story ID. If empty after validation, stop and report.

---

## Step 2: Determine execution groups

### 2a. Dependency ordering (topological sort)

- **Group 0**: no `depends_on`, or all dependencies already `done`
- **Group N**: all `depends_on` entries in earlier groups
- External dependency not `done` and not in batch → defer with explanation

Every story MUST appear in the plan — either in a batch or deferred.

### 2a-post. Bootstrap detection

A story is bootstrap if title matches `/bootstrap/i` AND no `depends_on`. If found: move other Group 0 stories **from the same epic** to Group 1. Cross-epic Group 0 stories unaffected.

### 2b. File conflict detection

Read [conflicts.md](conflicts.md) for the full conflict detection procedure (pm_check_conflicts, symbol granularity, hybrid git merge-tree confirmation).

---

## Step 3: Ensure dev branch exists

For each unique epic: call `pm_dev_branch(epic_id)` → store `epic_id → {dev_branch: "dev", epic_slug}`.

```bash
git fetch origin dev 2>/dev/null || { git branch dev main && git push -u origin dev; }
```
