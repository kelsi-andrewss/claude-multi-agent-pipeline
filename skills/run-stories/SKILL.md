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

## Output policy
- Do not emit any text between tool calls. Run all tools silently.
- The only output is the final summary (Step 6). No execution plan block, no progress narration.

---

## Step 1: Resolve story list

Parse each token in `{{args}}`:

- **`story-\d+`** → call `pm_get_story(id)`, read the detail file for full story data
- **`epic-\d+`** → call `pm_list_stories(epic_id=...)`, collect all non-archived stories
- **No args** → call `pm_view(detail="summary")`, collect all stories where `state` is `draft` or `ready`

After collecting, validate each story and **skip with a warning** if any of the following:
- `plan_file` is null or empty:
  - Load `ToolSearch: select:mcp__gemini__pm_plan_story` and call `pm_plan_story(story_id=<id>)` for all unplanned stories **in parallel** (single message).
  - Wait for all `pm_plan_story` calls to complete.
  - Launch one background `general-purpose` agent per unplanned story to write the plan file (same prompt as draft-plan Step 5).
  - Wait for all agents to complete, then re-fetch each story to confirm `plan_file` is now set.
  - If still missing after auto-planning, skip with warning: "story-NNN: auto-planning failed — skipping."
- `agent` is null or empty — warn: "story-NNN has no agent assigned — set it with pm_update_story"
- `agent` is `"manual"` — note: "story-NNN requires manual execution — skipping"
- `state` is `done`, `archived`, or `in-progress` — note: "story-NNN is already {state} — skipping"

> **Note:** Stories in `ready` state are the primary target — do NOT skip them. Only skip states that indicate the story is already complete (`done`, `archived`) or already running elsewhere (`in-progress`).

Deduplicate by story ID. If the list is empty after validation, stop and report all skips with reasons.

---

## Step 2: Determine execution groups

Build an execution plan from two analyses:

### 2a. Dependency ordering (topological sort)

- **Group 0**: stories with no `depends_on`, or all dependencies already `done`
- **Group 1**: stories whose `depends_on` entries are all in Group 0
- **Group N**: stories whose `depends_on` entries are all in earlier groups
- If a story's dependency is in a **different epic** and not yet `done`, place it in a named deferred group and explain when it will run:
  > "story-NNN deferred: depends on story-MMM (different epic, not done). Will run after story-MMM is merged."
- **Never skip a story just because it has dependencies** — place it in the correct dependency group. Every story passed to `/run-stories` MUST appear in the execution plan, either in a parallel batch or a sequential deferred group with a clear "runs after story-NNN merges" label.

### 2a-post. Bootstrap detection

After building dependency groups, scan Group 0 for bootstrap stories:

1. A story is a **bootstrap story** if its title matches `/bootstrap/i` AND it has no `depends_on` of its own.
2. If a bootstrap story is found: move all other Group 0 stories (non-bootstrap) to Group 1, with an implicit dependency on the bootstrap story. Log: "Auto-serialized: story-NNN (bootstrap) runs before all others in this epic"
3. A story titled like "Bootstrap payment provider" that has `depends_on` entries is NOT treated as bootstrap — it runs normally in its dependency group.
4. If no bootstrap story exists in the batch, no change to execution order.

### 2b. File conflict detection (within each dependency group)

Load `ToolSearch: select:mcp__gemini__pm_check_conflicts`, then for each dependency group:

1. Collect all story IDs in the group and call `pm_check_conflicts(story_ids=[...])`.
2. Read the detail file. It contains:
   - `conflicts`: list of `{file, stories}` write-write overlap entries
   - `read_conflicts`: list of `{file, writer, reader}` write-read overlap entries
   - `safe_parallel`: story IDs with no write-file overlaps (launch together)
   - `sequential`: story IDs that must run after conflicting stories merge
3. Use `safe_parallel` as batch 0. For `sequential` stories, chain them after their conflicting partner from `safe_parallel` finishes.
4. For `read_conflicts`: ensure the `reader` story runs in a batch after the `writer` story's batch. This prevents a reader from seeing stale file content.
5. Within each batch, order stories by ID (lowest first) for determinism.

> **Note:** A story may be placed in a later sequential batch even if it doesn't directly conflict with the story immediately before it. This happens when a downstream story conflicts with *both*, forcing them into a strict order. Stories are always chained safely to prevent merge conflicts.

---

## Step 2c: Post-bootstrap build verification

**This step ONLY runs when a bootstrap story was detected in Step 2a-post AND that story's batch has completed and merged.** If no bootstrap story, skip entirely — zero overhead.

After the bootstrap story's batch (Group 0) completes and merges into the dev branch, before launching Group 1:

1. Checkout the dev branch (post-bootstrap-merge).
2. Detect project type from the worktree and run the appropriate build command:
   - `package.json` → `npm install && npm run build` (or `npx tsc --noEmit` if no build script)
   - `pubspec.yaml` → `flutter pub get && flutter analyze`
   - `pyproject.toml` → `pip install -e . 2>&1 | tail -5`
   - `Cargo.toml` → `cargo check`
   - `go.mod` → `go build ./...`
3. If build succeeds → continue to Group 1 (launch feature stories).
4. If build fails → report the error, mark all remaining stories as BLOCKED with reason "Bootstrap build verification failed: <error>", stop execution.

---

## Step 3: Ensure dev branch exists

For each unique epic referenced by the stories being run:

1. Call `pm_dev_branch(epic_id)` → read the detail file for `epic_slug`.
2. Store the mapping: `epic_id → {dev_branch: "dev", epic_slug}` for use in step 4.

After collecting all epic slugs, ensure the `dev` branch exists on origin:
```bash
git fetch origin dev 2>/dev/null || { git branch dev main && git push -u origin dev; }
```

---

## Step 4: Execute groups in order

Process each dependency group sequentially. Within each group, process conflict batches:

### For each parallel batch — launch all stories simultaneously

Launch all stories in the batch in **a single message** as `general-purpose` agents with `run_in_background: true`.

Compute for each story:
- `story-slug`: lowercase title, replace spaces/special chars with `-`, collapse consecutive `-`, truncate to 40 chars, then append `-<NNN>` where NNN is the numeric part of the story ID (e.g., story-352 → `-352`)
- `epic-slug`: the `epic_slug` from the `pm_dev_branch` detail file in Step 3
- `story-branch`: `<epic-slug>--<story-slug>`
- `worktree-path`: `<project-root>/.claude/worktrees/story/<story-slug>`
- `dev-branch`: from the epic mapping computed in step 3
- `agent-approach`: based on the `agent` field:
  - `quick-fixer` → "Make surgical, minimal changes. No refactoring beyond what the plan specifies."
  - `architect` → "Make full architectural changes as specified in the plan. Follow all structural decisions."
  - anything else → "Follow the plan exactly."

**Model-specific warnings:** When the story's agent is `quick-fixer` (Haiku-tier), append to agent-approach: "CRITICAL: PRESERVE existing patterns. When extending or expanding code (regexes, arrays, switch cases, config objects), ADD new entries — never replace the existing block wholesale. Read the target section first, then insert your additions alongside what's already there."

**Before constructing each coder's prompt**, perform per-story enrichment:

**Pitfalls:** Extract file extensions from write_files (from the detail file), map to categories (`jsx`/`tsx`/`js` → `react`, `css`/`scss` → `css`, `dart` → `flutter`, Firestore ops → `firebase`, `py` in `mcp-servers/` → `python-mcp`, `md` in `skills/` → `skill-markdown`, `md` in `CLAUDE.md`/`ORCHESTRATION.md` → `claude-md`), call `pm_list_patterns(categories=[...])`. Include results in the prompt.

**Read-only context:** Read the story's plan file, extract paths from the `## Read-only context` section (if present). Prefix paths with the worktree path.

**Protected files:** Check if `<project-root>/.claude/protected-files.md` exists. If so, read it and include the list in the prompt.

**Learnings:** Call `openmemory_query(query="<tech-stack-keywords> <write-target-filenames>", user_id="global", n=5)`. Filter to procedural/semantic sectors. Include non-empty results in the coder prompt as a `## Learnings` section after `## Pitfalls`. Tech-stack keywords: derive from file extensions and framework indicators in the plan (e.g., "react hooks", "python mcp", "firebase firestore"). If no results, omit the section.

**Gitignore check:** Run `git -C <project-root> check-ignore <write_files>` (space-separated). If any file is gitignored, remove it from the write scope and add a warning to the coder prompt: "WARNING: <file> is gitignored — do not create or modify it. Achieve the story's goal without this file, or report NEED_DECISION." If ALL write targets are gitignored, skip the story and report as BLOCKED.

Each background agent receives this prompt (fill all placeholders before launching):

```
You are executing story <story_id>: "<title>"

Plan file: <plan_file>
Agent approach: <agent-approach>
Dev branch: <dev-branch>
Story branch: <story-branch>
Write files scope: <write_files list, or "not specified">
Read-only context files: <read-only context paths prefixed with worktree path, or "none">
Project root: <project-root>

WORKTREE: <worktree-path>
All reads and writes MUST use paths under this directory.
Before doing anything else, run: git -C <worktree-path> branch --show-current
Confirm it prints <story-branch>. If not, STOP and report branch mismatch.
Do NOT edit files outside this worktree.

Do not edit any protected files. <If protected-files.md exists: "Protected files: <list>">

## Tool constraints
You are the coder. Write all code yourself.
Do NOT call any mcp__gemini__* tools (gemini_generate, gemini_chat, analyze, audit, find_bug, plan, test, etc.).
Do NOT call any pm_* tools except pm_update_story (for state transitions).
Gemini is a research tool for the orchestrator — not available to coders.

## Pitfalls

<pitfalls from pm_list_patterns, or "No pitfalls for this story's file types.">

## Learnings

<openmemory results formatted as bullet points, or omit section if none>

## Steps

1. Create the story worktree using direct git commands:

   ```bash
   cd <project-root>
   git fetch origin <dev-branch>
   git show-ref --verify --quiet "refs/heads/<story-branch>" || git branch "<story-branch>" <dev-branch>
   git worktree list | grep -q '<worktree-path>' || git worktree add <worktree-path> "<story-branch>"
   ```

2. Verify worktree branch:
   ```bash
   git -C <worktree-path> branch --show-current
   ```
   Must print `<story-branch>`. If not, STOP and report branch mismatch.

3. Mark the story in-progress and record the branch/worktree in the DB:
   Call: pm_update_story("<story_id>", state="in-progress", branch="<story-branch>", worktree_path="<worktree-path>", worktree_active=True, force=True)
   (Use force=True so this succeeds regardless of whether the story is in ready or draft state)

4. Read the plan file at `<plan_file>`. Understand what changes are required.

5. Work **exclusively** inside `<worktree-path>`. Never edit files in `<project-root>` directly.

6. Implement the plan: <agent-approach>
   - Focus on the files listed in the write scope if provided
   - Do not modify files outside the write scope unless the plan explicitly requires it
   - Reference read-only context files for interfaces and utilities but do not modify them

7. Stage and commit changes inside the worktree:
   - Stage only the files you modified or created: `git -C <worktree-path> add <file1> <file2> ...`
   - Do NOT use `git add -A` or `git add .`
   - Commit: `git -C <worktree-path> commit -m "<story_id>: <title>"`

8. Push the story branch:
   ```bash
   git -C <worktree-path> push -u origin <story-branch>
   ```

9. After all changes are committed and pushed, mark done:
   Call: pm_update_story("<story_id>", state="done")

10. Return exactly one of:
   - Success: "DONE: <story-branch> pushed. Commit: <short-hash>. State: done. Files changed: <list of files staged>. Notes: <any relevant notes or 'none'>"
   - Decision needed (max 1 per story): "NEED_DECISION: <blocker>\nOption A: <option>\nOption B: <option>\n[Option C: <option>]"
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

## Step 5: Collect results and validate

Wait for all background agents to complete.

For each completed agent, write usage metadata to `/tmp/coder-effort-<story-id>.json`:
```json
{
  "story_id": "<story-id>",
  "model": "<model used>",
  "total_tokens": "<from agent result>",
  "tool_uses": "<from agent result>",
  "duration_ms": "<from agent result>"
}
```
If the agent result doesn't include usage metadata, skip — merge-worktree handles the fallback.

**NEED_DECISION handling:** If any agent returns NEED_DECISION:
1. Parse blocker description and options from the response.
2. Log a friction event: category `decision`, type automatic, skill `run-stories`.
3. Claude picks the best option (with one-line reasoning).
4. Resume the agent using its agent ID: "Decision: Option <X>. Continue from where you left off."
5. Wait for the resumed agent to return DONE or BLOCKED.
6. If DONE, add to the merge list. If BLOCKED, add to blocked list.

### Step 5a: Diff gate (per story)

For each DONE story, verify only expected files changed:

```bash
git -C <worktree-path> diff --name-only <dev-branch>
```

Compare against the story's write_files. If unexpected files changed, warn but continue — the coder may have legitimately needed adjacent files. Log any discrepancies.

### Step 5b: Per-story testing

For each DONE story that passes the diff gate:

1. Check if test infrastructure exists in the project (look for test directories, test configs, `jest.config`, `pytest.ini`, `_test.go` files, etc.). If none exists, skip testing for this story.
2. Launch unit-tester agent (background, **Haiku**) in the worktree. The unit-tester writes tests from the plan file's **acceptance criteria**, not from the implementation.
3. Results:
   - PASS → story proceeds to merge.
   - FAIL trivial → log a friction event (category `retry`, type automatic, skill `run-stories`),
     resume coder with failures, wait for fix. If fix succeeds, proceed to merge.
   - FAIL non-trivial → log a friction event (category `blocked`, type automatic, skill `run-stories`),
     story marked BLOCKED.

### Step 5c: Merge

For each story that passes validation (diff gate + testing), invoke `/merge-worktree` (pass all validated story IDs space-separated as args).

---

## Step 6: Report

Print a final summary:

```
Run complete.  Dev branch: dev

story-001  batch 0   my-feature--fix-auth-flow      DONE    abc1234   tests: pass
story-003  batch 0   my-feature--update-dashboard   DONE    def5678   tests: skipped (no infra)
story-002  batch 1   my-feature--refactor-handlers  DONE    ghi9012   tests: pass  (conflicted with story-001 on src/handlers/foo.js)
story-005  batch 0   my-feature--add-search         BLOCKED plan file references missing utility

Skipped (validation):
  story-006: state is 'done' — already complete

Deferred (dependency not yet merged):
  story-007: runs after story-005 merges

Blocked during execution:
  story-005: plan file references missing utility function `buildSearchIndex`
```

The `batch` column shows the parallel batch each story ran in (batch 0 = first parallel wave; batch 1 = ran after batch 0 due to conflict; `deferred` = cross-epic dependency not yet merged).

If all stories complete successfully, print: "All stories executed successfully."

If any story is BLOCKED, list it with its reason in a "Blocked" section. Never stop other stories due to one failure — they run independently.

If all stories were BLOCKED or skipped (zero DONE), stop after printing the summary.
