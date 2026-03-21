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

## Step 0: Parse flags

Strip flags from `{{args}}` before processing story/epic tokens:

- `--project-root <path>` — override the project root directory. The next token after `--project-root` is the absolute path. Defaults to the current working directory if not provided. Use this when the target codebase is in a different git repo than the orchestration project (e.g., `/factory` created stories for an external repo).

After stripping flags, the remaining tokens are story/epic IDs processed by Step 1.

All references to `<project-root>` throughout this skill use the resolved value from this flag.

---

## Output policy
- Do not emit any text between tool calls. Run all tools silently.
- The only output is the final summary (Step 6). No execution plan block, no progress narration.

---

## Run state management

At the start of execution (before MCP delegation), initialize the run state database:

```bash
SESSION_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
python3 ~/.claude/scripts/init-run-db.py --session-id "$SESSION_ID" --dev-branch dev
```

If init fails (exit code 2), stop and report: "Run state initialization failed: <stderr>".

Store $SESSION_ID for use throughout the run. Pass it to scripts that write to run-state.db.

At the end of execution (after Step 6 report, or on any early exit), clean up:

```bash
python3 ~/.claude/scripts/cleanup_run_state.py --session-id "$SESSION_ID"
```

---

## Script output handling

All scripts in `~/.claude/scripts/` emit a single JSON object on stdout. Parse with:

```bash
RESULT=$(bash ~/.claude/scripts/<script>.sh <args>)
echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['status'])"
```

If JSON parsing fails (python3 exits non-zero), log the raw output and treat as a system error:
- For build-verify: treat as FAIL
- For diff-gate: treat as non-blocking warning
- For worktree-setup: treat as BLOCKED for that story
- For worktree-cleanup: note in report, continue
- For merge-gate: treat as BLOCKED for that story

Exit codes: 0 = success (check JSON for functional result), 1 = functional error (check JSON), 2 = system error.

---

## MCP Delegation (ORCHESTRATION §15)

Steps 1–3 and the enrichment portion of Step 4 (pitfalls, learnings, gitignore checks) involve 10+ MCP calls whose verbose JSON responses consume main-session context. **Delegate them to a single foreground `general-purpose` subagent.**

**How to delegate:**

1. Construct a subagent prompt containing:
   - The full text of Steps 1, 2 (all sub-steps), and 3 below
   - The enrichment instructions (pitfalls, learnings, read-only context, gitignore — copied from Step 4's "Enrichment reference" section)
   - The resolved `{{args}}` value and project root path
   - ToolSearch instructions: `select:mcp__gemini__pm_get_story,mcp__gemini__pm_view,mcp__gemini__pm_list_stories,mcp__gemini__pm_check_conflicts,mcp__gemini__pm_dev_branch,mcp__gemini__pm_list_patterns` and `select:mcp__openmemory__openmemory_query`
   - For each story in the execution plan, call worktree-setup.sh to pre-create the worktree:
     ```bash
     WORKTREE_RESULT=$(bash ~/.claude/scripts/worktree-setup.sh --project-root <project-root> --branch <story-branch> --worktree-path <worktree-path> --dev-branch <dev-branch>)
     ```
     Include the result status in the STORIES return data. If setup fails, mark the story as SKIPPED with reason.
2. Append the return format below to the prompt
3. Launch: `Agent(subagent_type="general-purpose", prompt=<constructed>)` — **foreground**, not background
4. Parse the structured response
5. If NEEDS_PLANNING stories are returned: handle auto-planning in the main session (call `pm_plan_story` + launch plan-writing agents), then call `pm_get_story` inline for each newly-planned story to fill in plan_file

**Required return format:**

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

After parsing, proceed to Step 2c (if bootstrap detected) then Step 4 (coder launch).

---

## Step 1: Resolve story list (subagent-scoped)

Parse each token in `{{args}}`:

- **`story-\d+`** → call `pm_get_story(id)`, read the detail file for full story data
- **`epic-\d+`** → call `pm_list_stories(epic_id=...)`, collect all non-archived stories
- **No args** → call `pm_view(detail="summary")`, collect all stories where `state` is `draft` or `ready`

After collecting, validate each story and **skip with a warning** if any of the following:
- `state` is `done` or `archived` — note: "story-NNN is already {state} — skipping"
- `state` is `in-progress` — note: "story-NNN is in-progress (claimed by another session) — skipping"
- `agent` is null or empty — warn: "story-NNN has no agent assigned — set it with pm_update_story"
- `agent` is `"manual"` — note: "story-NNN requires manual execution — skipping"
- `plan_file` is null or empty:
  - Load `ToolSearch: select:mcp__gemini__pm_plan_story` and call `pm_plan_story(story_id=<id>)` for all unplanned stories **in parallel** (single message).
  - Wait for all `pm_plan_story` calls to complete.
  - Launch one background `general-purpose` agent per unplanned story to write the plan file (same prompt as draft-plan Step 5).
  - Wait for all agents to complete, then re-fetch each story to confirm `plan_file` is now set.
  - If still missing after auto-planning, skip with warning: "story-NNN: auto-planning failed — skipping."

> **Note:** Stories in `ready` or `draft` state are the primary target. `in-progress` means another session claimed it — always skip.

**Session claim (anti-collision):** After validation, immediately claim all eligible stories by transitioning them to `in-progress`:

```
For each eligible story:
  pm_update_story(story_id, state="in-progress", force=True)
```

This happens in the resolution subagent BEFORE worktree creation or coder launch. The state transition is the lock — any other session running `/run-stories` concurrently will see `in-progress` and skip. If this session crashes before completing a story, the story stays `in-progress` and must be manually reset via `pm_update_story(story_id, state="ready", force=True)` or `/recover`.

**Why state-based, not a separate lock table:** Adding a lock column or table creates a second source of truth that can drift from the actual state. The story state IS the lock. `in-progress` means "someone is working on this." If the state says `ready`, no one is. This is the simplest mechanism that prevents the collision.

Deduplicate by story ID. If the list is empty after validation, stop and report all skips with reasons.

---

## Step 2: Determine execution groups (subagent-scoped)

Build an execution plan from two analyses:

### 2a. Dependency ordering (topological sort)

- **Group 0**: stories with no `depends_on`, or all dependencies already `done`
- **Group 1**: stories whose `depends_on` entries are all in Group 0
- **Group N**: stories whose `depends_on` entries are all in earlier groups
- If a story's dependency (same or different epic) is not yet `done` and is not in the current run batch, place it in a named deferred group and explain when it will run:
  > "story-NNN deferred: depends on story-MMM (not done, not in this run). Will run after story-MMM is merged."
- **Never skip a story just because it has dependencies** — place it in the correct dependency group. Every story passed to `/run-stories` MUST appear in the execution plan, either in a parallel batch or a sequential deferred group with a clear "runs after story-NNN merges" label.

### 2a-post. Bootstrap detection

After building dependency groups, scan Group 0 for bootstrap stories:

1. A story is a **bootstrap story** if its title matches `/bootstrap/i` AND it has no `depends_on` of its own.
2. If a bootstrap story is found: move all other Group 0 stories **from the same epic** (non-bootstrap) to Group 1, with an implicit dependency on the bootstrap story. Stories from other epics in Group 0 are unaffected. Log: "Auto-serialized: story-NNN (bootstrap) runs before all others in epic-MMM"
3. A story titled like "Bootstrap payment provider" that has `depends_on` entries is NOT treated as bootstrap — it runs normally in its dependency group.
4. If no bootstrap story exists in the batch, no change to execution order.

### 2b. File conflict detection (across all stories in the run)

Load `ToolSearch: select:mcp__gemini__pm_check_conflicts`, then:

1. Collect ALL story IDs across all dependency groups and call `pm_check_conflicts(story_ids=[...])` once. This catches write-target overlaps regardless of which epic a story belongs to.
2. Apply the conflict results to each dependency group: stories within the same group that conflict get serialized; stories in different groups already run sequentially by dependency ordering.
3. Read the detail file. It contains:
   - `conflicts`: list of `{file, stories}` write-write overlap entries
   - `read_conflicts`: list of `{file, writer, reader}` write-read overlap entries
   - `safe_parallel`: story IDs with no write-file overlaps (launch together)
   - `sequential`: story IDs that must run after conflicting stories merge
4. Use `safe_parallel` as batch 0. For `sequential` stories, chain them after their conflicting partner from `safe_parallel` finishes.
5. For `read_conflicts`: ensure the `reader` story runs in a batch after the `writer` story's batch. This prevents a reader from seeing stale file content.
6. Within each batch, order stories by ID (lowest first) for determinism.

> **Note:** A story may be placed in a later sequential batch even if it doesn't directly conflict with the story immediately before it. This happens when a downstream story conflicts with *both*, forcing them into a strict order. Stories are always chained safely to prevent merge conflicts.

### Function-level granularity

Write targets support optional symbol annotations using colon syntax:
- `route.ts` — whole file (conflicts with ANY other `route.ts` target)
- `route.ts:queryPinecone` — specific function/export (conflicts only with `route.ts:queryPinecone` or bare `route.ts`)
- `route.ts:POST handler` — named section (same rules)

**Conflict rules:**
- `file` vs `file` → CONFLICT (whole-file overlap)
- `file` vs `file:symbol` → CONFLICT (whole-file subsumes any symbol)
- `file:symbolA` vs `file:symbolB` → SAFE (different symbols, parallel OK)
- `file:symbolA` vs `file:symbolA` → CONFLICT (same symbol)

When `pm_check_conflicts` returns file-level conflicts, check if ALL stories in the conflict use symbol-annotated targets for that file. If so, compare symbols — if all symbols are distinct, reclassify as `safe_parallel` for that file.

If ANY story uses a bare filename (no symbol), it conflicts with all other stories targeting that file regardless of their annotations.

### 2b-hybrid. Git merge-tree confirmation

After `pm_check_conflicts` classifies stories into `safe_parallel` and `sequential`, run a second pass using `conflict-check.sh` to confirm or reclassify sequential pairs via actual git merge-tree simulation and symbol analysis.

For each pair of stories in the `sequential` list that have branches already pushed:

1. Call `conflict-check.sh` to compare the two story branches:
   ```bash
   CONFLICT_RESULT=$(bash ~/.claude/scripts/conflict-check.sh \
     --branch-a <story-a-branch> \
     --branch-b <story-b-branch> \
     --project-root <project-root>)
   ```

2. Parse the JSON result. Check the `severity` and `conflict` fields.

3. Reclassification:
   - `severity` is `"green"` or `"yellow"` (`conflict: false`) — move the story pair from `sequential` to `safe_parallel`. Log: `"story-NNN + story-MMM: pm_check_conflicts flagged file overlap but git merge-tree confirms no textual conflict — parallelizing."`
   - `severity` is `"red"` or `"black"` (`conflict: true`) — keep in `sequential`. Log: `"story-NNN + story-MMM: confirmed conflict in <files> (<symbols if available>)."`

4. If stories don't have branches yet (first run — branches are created during Step 4), skip hybrid check for that pair. Fall back to `pm_check_conflicts` decision. Hybrid confirmation is opportunistic, not blocking.

5. If `conflict-check.sh` returns `status: "error"` (exit code 2), log the error and keep the pair in `sequential` (conservative fallback).

6. After processing all sequential pairs, the updated `safe_parallel` and `sequential` lists are used for batch construction in the remaining steps.

> **Why opportunistic:** On first run, story branches don't exist yet — they're created in Step 4 from the dev branch. `git merge-tree` needs actual refs to compare. The hybrid check adds value on re-runs (branches exist from a previous partial execution), sequential batches (batch 0 creates branches before batch 1 launches), and the merge queue (branches exist by queue ordering time).

---

## Step 2c: Build verification (via shared script)

This block defines the reusable build verification logic referenced by both the bootstrap gate and Step 4.1 (batch verification). It is not executed directly — it is invoked by those steps.

### Build verification

Run build verification using the shared script:

```bash
RESULT=$(bash ~/.claude/scripts/build-verify.sh --project-root <project-root>)
```

Parse the JSON result:
- `status: "success"` with `build_result: "pass"` → PASS
- `status: "success"` with `build_result: "pass"` and `lint_warnings` > 0 → PASS with warnings (log warning count, do not block)
- `status: "success"` with `build_result: "skip"` (project_type is `"unknown"`) → SKIP (no recognized build system). Log: "No recognized build system — skipping batch verification."
- `status: "error"` with `build_result: "fail"` (exit code 1) → build FAIL (blocks downstream). Build output is in `build_output` field.
- `status: "error"` (exit code 2) → system error, treat as FAIL

If JSON parse fails, log raw output and mark as FAIL.

### Bootstrap gate (existing behavior, unchanged)

After the bootstrap batch (Group 0) completes and merges into the dev branch, before launching Group 1:

1. Checkout the dev branch (post-bootstrap-merge).
2. Run build verification using `build-verify.sh` as described above.
3. If PASS → continue to Group 1 (launch feature stories).
4. If FAIL → report the error, mark all remaining stories as BLOCKED with reason "Bootstrap build verification failed: <error>", stop execution.

**This gate ONLY fires when a bootstrap story was detected in Step 2a-post AND that story's batch has completed and merged.** If no bootstrap story, skip entirely — zero overhead.

---

## Step 3: Ensure dev branch exists (subagent-scoped)

For each unique epic referenced by the stories being run:

1. Call `pm_dev_branch(epic_id)` → read the detail file for `epic_slug`.
2. Store the mapping: `epic_id → {dev_branch: "dev", epic_slug}` for use in step 4.

After collecting all epic slugs, ensure the `dev` branch exists on origin:
```bash
git fetch origin dev 2>/dev/null || { git branch dev main && git push -u origin dev; }
```

---

## Step 3.5: Context sharding (large batches only)

When a parallel batch contains >8 stories, split into shards of 3-5 stories each.
For each shard, launch a "lead" agent (general-purpose, Sonnet) that:
1. Receives the shard's stories with their full coder prompts
2. Launches coder agents for its shard stories (as background agents)
3. Handles tactical NEED_DECISION responses autonomously
4. Escalates strategic/critical NEED_DECISION to the main session
5. Runs fix-loop for each completed coder
6. Returns a shard summary: DONE/NEED_DECISION/BLOCKED per story

The main session manages leads, not individual stories. Leads return the same
contract as individual coders: one status per story in their shard.

When batch size <=8, skip sharding — launch coders directly as before.

---

## Step 4: Execute groups in order

Process each dependency group sequentially. Within each group, process conflict batches.

After each batch's stories complete and merge via Step 5c, run **Step 4.1 Batch Verification** before launching the next batch. If verification fails, skip all remaining batches.

### For each parallel batch — launch all stories simultaneously

Launch all stories in the batch in **a single message** as `general-purpose` agents with `run_in_background: true`.

**Lifecycle event**: After dispatching each coder agent, emit:
```bash
bash ~/.claude/scripts/emit-event.sh "story.launched" "claude" '{"story_id":"<story_id>","batch":<batch_num>,"agent":"<agent-type>","branch":"<story-branch>"}'
```

Compute for each story:
- `story-slug`: lowercase title, replace spaces/special chars with `-`, collapse consecutive `-`, truncate to 40 chars, then append `-<NNN>` where NNN is the numeric part of the story ID (e.g., story-352 → `-352`)
- `epic-slug`: the `epic_slug` from the `pm_dev_branch` detail file in Step 3
- `story-branch`: `<epic-slug>--<story-slug>`
- `has-test-files`: true if the story's `test_files` list is non-empty
- `worktree-path`:
  - If `has-test-files`: `<project-root>/.claude/worktrees/story/<story-slug>--code` (coder) and `<project-root>/.claude/worktrees/story/<story-slug>--test` (test agent)
  - If NOT `has-test-files`: `<project-root>/.claude/worktrees/story/<story-slug>` (unchanged, backward compatible)
- `dev-branch`: from the epic mapping computed in step 3
- `agent-approach`: based on the `agent` field:
  - `quick-fixer` → "Make surgical, minimal changes. No refactoring beyond what the plan specifies."
  - `architect` → "Make full architectural changes as specified in the plan. Follow all structural decisions."
  - anything else → "Follow the plan exactly."

**Per-story data** was gathered by the resolution subagent. Use the `pitfalls`, `learnings`, `read_only_context`, and `gitignore_warnings` fields from the STORIES data returned in the MCP Delegation step. Do **not** make additional MCP calls for this information. If a story has gitignore warnings for ALL write targets, skip it as BLOCKED.

**Protected files:** Read `<project-root>/.claude/protected-files.md` if it exists (single file read — acceptable inline).

### Enrichment reference (for resolution subagent prompt)

> The following instructions are included in the skill for reference and must be passed verbatim to the resolution subagent as part of its prompt:
>
> **Pitfalls:** Read `<project-root>/refs/pattern-categories.json`. Use `extension_map` to map write_file extensions to categories, and `path_overrides` to override by path prefix. Deduplicate categories, then call `pm_list_patterns(category=<cat>)` for each. Format results as bullet points.
>
> **Learnings:** Call `openmemory_query(query="<tech-stack-keywords> <write-target-filenames>", user_id="global", n=5)`. Filter to procedural/semantic sectors. Format non-empty results as bullet points. Tech-stack keywords: derive from file extensions and framework indicators in the plan (e.g., "react hooks", "python mcp", "firebase firestore").
>
> **Read-only context:** Read each story's plan file, extract paths from the `## Read-only context` section (if present). Return as a list of absolute paths.
>
> **Gitignore check:** Run `git -C <project-root> check-ignore <write_files>` (space-separated). Return any gitignored files as warnings.

Before including the plan file content in the coder prompt, strip any `<!-- TESTER_ONLY -->` / `<!-- END_TESTER_ONLY -->` blocks and their contents. Use: `plan_content = re.sub(r'<!-- TESTER_ONLY -->.*?<!-- END_TESTER_ONLY -->', '', plan_content, flags=re.DOTALL).strip()`

Each background agent receives this prompt (fill all placeholders before launching):

```
You are executing story <story_id>: "<title>"

Plan file: <plan_file>
Agent approach: <agent-approach>
Dev branch: <dev-branch>
Story branch: <story-branch>
Write files scope: <write_files list, or "not specified">
If write targets include symbol annotations (e.g., "file.ts:functionName"), limit your changes in that file to the annotated symbol/section. Do not modify other functions or sections in the same file.
Read-only context files: <read-only context paths prefixed with worktree path, or "none">
Project root: <project-root>

WORKTREE: <worktree-path>
All reads and writes MUST use paths under this directory.
Do NOT edit files outside this worktree.

Do not edit any protected files. <If protected-files.md exists: "Protected files: <list>">

## Tool constraints
You are the coder. Write all code yourself.
Do NOT call any mcp__gemini__* tools (gemini_generate, analyze, audit, find_bug, plan, test, etc.) UNLESS `ui_codegen: true` — then `mcp__gemini__gemini_ui_code` is allowed and required for visual code.
Do NOT call any pm_* tools except pm_update_story (for state transitions).
Gemini is a research tool for the orchestrator — not available to coders.

**UI codegen exception:** If the story has `ui_codegen: true` in its DB record:
- You MUST call `mcp__gemini__gemini_ui_code` for all visual/layout component code.
- Define the props contract first (what data the component receives, what callbacks it exposes).
- Call the tool with component_name, props_contract, requirements, and exemplar_paths (1-2 similar components from the project).
- Drop the returned code into the target file as-is. Do not modify Gemini's markup or styles.
- Run build/lint. If errors, call `gemini_ui_code` again with `error_feedback` containing the error output. Repeat until clean.
- NEED_DECISION only if Gemini returns the same error on consecutive attempts (stuck, not iterating).
- You own: imports, exports, props wiring, state management, data fetching, integration with the rest of the app. Gemini owns: what renders on screen.

## Decision autonomy

You may resolve these WITHOUT emitting NEED_DECISION:
- Naming: variable names, function names, file organization
- Imports: import ordering, module resolution
- Test structure: test grouping, assertion style
- Error messages: wording, formatting

You MUST emit NEED_DECISION for:
- API shape: function signatures visible to other modules
- Architecture: data flow, state management patterns
- Dependencies: adding new packages or imports from outside the project

You MUST emit NEED_DECISION with "CRITICAL:" prefix for:
- Security: auth, permissions, token handling
- Data migration: schema changes, data transformation
- Breaking changes: removing or renaming public APIs

**Format requirement**: All NEED_DECISION emissions must use the structured block format shown in step 9. Include the Level field and at least 2 numbered options with tradeoff descriptions.

## Pitfalls

<pitfalls from pm_list_patterns, or "No pitfalls for this story's file types.">

## Learnings

<openmemory results formatted as bullet points, or omit section if none>

## Steps

1. Verify the story worktree (pre-created by the resolution subagent):

   ```bash
   git -C <worktree-path> branch --show-current
   ```

   Must print `<story-branch>`. If not, STOP and report branch mismatch.

   If the worktree was not pre-created (worktree_status was error), create it now:
   ```bash
   WORKTREE_RESULT=$(bash ~/.claude/scripts/worktree-setup.sh --project-root <project-root> --branch <story-branch> --worktree-path <worktree-path> --dev-branch <dev-branch>)
   ```

   Parse the JSON result. If `status` is not `"success"` or `verified` is not `true`, STOP and report: "Worktree setup failed: <error from JSON>".

2. Record the branch/worktree in the DB (story is already in-progress — claimed by the resolution subagent in Step 1):
   Call: pm_update_story("<story_id>", branch="<story-branch>", worktree_path="<worktree-path>", worktree_active=True)

3. Read the plan file at `<plan_file>`. Understand what changes are required.

4. Work **exclusively** inside `<worktree-path>`. Never edit files in `<project-root>` directly.

5. Implement the plan: <agent-approach>
   - Focus on the files listed in the write scope if provided
   - Do not modify files outside the write scope unless the plan explicitly requires it
   - Reference read-only context files for interfaces and utilities but do not modify them

6. Stage and commit changes inside the worktree:
   - Stage only the files you modified or created: `git -C <worktree-path> add <file1> <file2> ...`
   - Do NOT use `git add -A` or `git add .`
   - Commit: `git -C <worktree-path> commit -m "<story_id>: <title>"`

7. Push the story branch:
   ```bash
   git -C <worktree-path> push -u origin <story-branch>
   ```

8. After all changes are committed and pushed, mark done:
   Call: pm_update_story("<story_id>", state="done")

9. Return exactly one of:
   - Success: "DONE: <story-branch> pushed. Commit: <short-hash>. State: done. Files changed: <list of files staged>. Notes: <any relevant notes or 'none'>"
   - Decision needed (max 1 strategic per story; critical always escalates):
     ```
     NEED_DECISION: <one-line question>
     Level: strategic | critical
     Option 1: <title> — <description with tradeoffs>
     Option 2: <title> — <description with tradeoffs>
     Option 3: <title> — <description with tradeoffs> (if applicable)
     Context: <what you're doing and why this matters for the story>
     ```
   - Research needed: "NEED_RESEARCH: <specific question>\nContext: <what you've tried>"
   - Failure: "BLOCKED: <clear reason why the story could not be completed>"
```

**When `has-test-files` is true**, additionally modify the coder prompt and launch a parallel test agent:

**Coder prompt addition** (append to the coder prompt above, before the Steps section):
```
## Test file prohibition
You are the CODER. Do NOT create or modify test files. Test files for this story: <test_files list>. Leave them to the test agent.
```

**Test agent** — launched simultaneously with the coder as a second `general-purpose` background agent (model: Sonnet):

Before including the plan file content in the test agent prompt, strip any `<!-- CODER_ONLY -->` / `<!-- END_CODER_ONLY -->` blocks and their contents. Use: `plan_content = re.sub(r'<!-- CODER_ONLY -->.*?<!-- END_CODER_ONLY -->', '', plan_content, flags=re.DOTALL).strip()`

```
You are the TEST AGENT for story <story_id>: "<title>"

Plan file: <plan_file>
Dev branch: <dev-branch>
Story branch: <story-branch>--test
Write files scope: <test_files list>
Read-only context files (prefix with worktree path): <read-only context paths, or "none">
Project root: <project-root>

WORKTREE: <worktree-path for --test>
All reads and writes MUST use paths under this directory.
Before doing anything else, run: git -C <test-worktree-path> branch --show-current
Confirm it prints <story-branch>--test. If not, STOP and report branch mismatch.
Do NOT edit files outside this worktree.

## Tool constraints
You are the test agent. Write all tests yourself.
Do NOT call any mcp__gemini__* tools.
Do NOT call any pm_* tools.

## Instructions

Write tests from the plan's acceptance criteria and function signatures ONLY. You must:
- Read the plan file for acceptance criteria, function signatures, and interface contracts
- Reference read-only context files for type definitions and interfaces
- Do NOT read or reference any source implementation files
- Write ONLY to these test files: <test_files list>
- Do NOT run the tests — they will be run against the real implementation in the merge gate

The plan file you receive has been filtered — implementation tasks and approach details have been removed. Write tests purely from the acceptance criteria and contract signatures you see. If acceptance criteria are ambiguous, test the contract surface (function signatures, return types, error cases) rather than guessing implementation details.

## Steps

1. Create the test worktree from the dev branch (NOT the story branch — you must not see the coder's changes):
   ```bash
   WORKTREE_RESULT=$(bash ~/.claude/scripts/worktree-setup.sh --project-root <project-root> --branch <story-branch>--test --worktree-path <test-worktree-path> --dev-branch <dev-branch>)
   ```
   Parse the JSON result. If `status` is not `"success"` or `verified` is not `true`, STOP and report: "Test worktree setup failed: <error from JSON>".

2. Read the plan file. Extract acceptance criteria and function signatures.

3. Write test files based solely on the plan's spec. Do not look at implementation code.

4. Stage and commit:
   ```bash
   git -C <test-worktree-path> add <test_files>
   git -C <test-worktree-path> commit -m "<story_id>: add spec tests"
   ```

5. Push:
   ```bash
   git -C <test-worktree-path> push -u origin <story-branch>--test
   ```

6. Return exactly one of:
   - "DONE: <story-branch>--test pushed. Commit: <short-hash>. Files changed: <list>. Notes: <any>"
   - "BLOCKED: <reason>"
```

**When `has-test-files` is false**, skip test agent launch entirely. The coder runs solo with the standard worktree path (no `--code` suffix). This preserves the existing flow for stories without test files.

### Agent health monitoring

After launching all agents in a parallel batch, start the watchdog in the background:

```bash
python3 ~/.claude/scripts/agent-watchdog.py \
  --session-id "$SESSION_ID" \
  --story-ids "<comma-separated story IDs in this batch>" \
  --agent-pids "<comma-separated PIDs from launched agents, same order>" \
  --agent-types "<comma-separated agent types: quick-fixer|architect, same order>"
```

Run this in the background (do not wait for it). Store the watchdog PID.

When collecting results in Step 5, also check watchdog output:
- If the watchdog killed any agents, those stories are BLOCKED with the kill reason.
- Include killed agents in the Step 6 report under "Blocked during execution" with prefix "Watchdog killed: ".

On early exit or cleanup, send SIGTERM to the watchdog PID if it's still running.

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

## Step 4.1: Batch Verification

After each batch's stories are merged into dev via Step 5c, verify the dev branch still builds before launching the next batch. This step uses the build verification logic defined in Step 2c.

### When to run

- Run after each non-final batch merges into dev. (The final batch is covered by merge-worktree's Step 2.5 — no double-verification.)
- **Single-batch runs**: When all stories land in a single batch (no conflicts, no multi-group dependencies beyond bootstrap), skip inter-wave verification entirely. Log: "Single batch — skipping inter-wave verification (merge gate covers)."
- **Bootstrap batch**: The bootstrap gate in Step 2c already handles post-bootstrap verification. Step 4.1 handles all subsequent non-bootstrap batches. No double-verification on the bootstrap batch.

### Procedure

1. Checkout the dev branch (post-merge state).
2. Run the full validation pyramid:
   ```bash
   RESULT=$(bash ~/.claude/scripts/validation-runner.sh --project-root <project-root> --layer all)
   ```
3. Parse the JSON result. Check `overall_status`:
   - `"pass"` → all layers passed
   - `"fail"` → at least one layer failed (check `layers` array for details)
   - `"skip"` → no recognized project type
4. Results:
   - **PASS** (`overall_status` is `"pass"`): Log `"Batch N verification: PASS"`. Continue to the next batch. If any layer has non-zero `error_count` with `status: "pass"`, log as warnings.
   - **FAIL** (`overall_status` is `"fail"`): Find the first failed layer in the `layers` array. Log `"Batch N verification: FAIL — <layer.name>: <layer.output>"`. Mark ALL stories in subsequent batches as BLOCKED with reason `"Blocked: batch N verification failed"`. Stop executing further batches.
   - **SKIP** (`overall_status` is `"skip"`): Log `"Batch N verification: SKIP (no build system)"`. Continue.

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
4. Create the decision review artifact:
   ```bash
   mkdir -p decisions/reviews/
   DECISION_NUM=$(ls decisions/reviews/ 2>/dev/null | grep -c '^decision-' || echo 0)
   DECISION_NUM=$((DECISION_NUM + 1))
   ```
   Write the artifact to `decisions/reviews/decision-${DECISION_NUM}.md` using the format from ORCHESTRATION.md section 7. Populate Context from the coder's NEED_DECISION context field, Options from the numbered options, Resolution from Claude's pick.
5. Emit lifecycle event:
   ```bash
   bash ~/.claude/scripts/emit-event.sh "decision.made" "claude" '{"story_id":"<story_id>","decision_id":"decision-<N>","level":"<strategic|critical>","chosen_option":<N>,"artifact":"decisions/reviews/decision-<N>.md"}'
   ```
6. Resume the agent using its agent ID: "Decision: Option <X>. Continue from where you left off."
7. Wait for the resumed agent to return DONE or BLOCKED.
8. If DONE, add to the merge list. If BLOCKED, add to blocked list. When adding to blocked list, emit:
   ```bash
   bash ~/.claude/scripts/emit-event.sh "story.blocked" "claude" '{"story_id":"<story_id>","reason":"<blocked reason>","batch":<batch_num>}'
   ```

**NEED_RESEARCH handling:** If any agent returns NEED_RESEARCH:
1. Parse the research question and context from the response.
2. Dispatch targeted Gemini research: `web_search` with the specific question.
3. Resume the agent with: "Research result: <Gemini response>. Continue from where you left off."
4. Wait for the resumed agent to return DONE, NEED_DECISION, or BLOCKED.
5. NEED_RESEARCH does not count toward the BLOCKING escalation counter.

### Step 5.0: Fix-loop auto-review (coder self-correction)

After each coder agent returns DONE (and before the diff gate in Step 5a), run build verification against the coder's worktree to confirm the code actually works:

```bash
VERIFY_RESULT=$(bash ~/.claude/scripts/build-verify.sh --project-root <worktree-path>)
```

Parse the JSON result using the same logic as Step 2c:
- **PASS** or **SKIP** (no build system): proceed to Step 5a (diff gate). No retry needed.
- **FAIL**: delegate to `/fix-loop` below.

If the coder returned BLOCKED, skip build verification entirely (nothing to verify) — the story goes straight to the blocked list.

#### Fix-loop delegation

On FAIL, delegate iterative correction to the `/fix-loop` skill (decision-111). Fix-loop handles error hashing, circuit breakers, model escalation, and atomic commits internally — run-stories only needs to invoke it and parse the result.

Invoke `/fix-loop` with:
```
/fix-loop \
  --worktree-path <worktree-path> \
  --max-retries 3 \
  --story-branch <story-branch> \
  --story-id <story_id>
```

Parse fix-loop's return per the subagent contract (ORCHESTRATION section 15):
- **DONE**: Proceed to Step 5a (diff gate). Fix-loop's termination gate guarantees all validation layers (compile, lint, tests) pass. Do NOT re-run `build-verify.sh` — fix-loop already validated.
- **NEED_DECISION**: Surface to main session for resolution, then resume fix-loop.
- **BLOCKED**: Mark story BLOCKED with fix-loop's reason. Log friction: `category: blocked, type: automatic, skill: run-stories, detail: "fix-loop exhausted: <reason>"`. Emit:
   ```bash
   bash ~/.claude/scripts/emit-event.sh "story.blocked" "claude" '{"story_id":"<story_id>","reason":"fix-loop exhausted: <reason>","batch":<batch_num>}'
   ```
   Skip Steps 5a and 5b.

#### Dual-exit gate

A coder's work is only considered complete when BOTH conditions are met:
1. The coder agent returned DONE (completion indicator)
2. Either `build-verify.sh` returned PASS/SKIP on first check (no fix-loop needed), OR `/fix-loop` returned DONE (fix-loop's termination gate guarantees all validation layers pass)

If the coder returned DONE but build verification fails, `/fix-loop` handles iterative correction and returns DONE (all layers pass) or BLOCKED (exhausted retries). If the coder returned BLOCKED, skip build verification entirely (nothing to verify).

#### Stories without a build system

When `build-verify.sh` returns `build_result: "skip"` (project_type is "unknown"), the dual-exit gate is satisfied by condition 1 alone. Fix-loop is never invoked. This preserves existing behavior for projects without lint/test infrastructure.

#### Interaction with existing steps

The fix-loop delegation (Step 5.0) runs BEFORE Step 5a (diff gate) and Step 5b (per-story testing). The purpose is different:
- Step 5.0 catches build/lint failures via fix-loop's validation pyramid (does the code compile and pass basic checks?)
- Step 5b runs acceptance tests (does the code meet the spec?)

A story must pass Step 5.0 before entering Step 5a. If Step 5.0 marks a story BLOCKED, it skips Step 5a and Step 5b entirely.

### Step 5a: Diff gate (per story)

For each DONE story, verify only expected files changed:

```bash
DIFF_RESULT=$(bash ~/.claude/scripts/diff-gate.sh --worktree-path <worktree-path> --dev-branch <dev-branch> --write-files "<comma-separated write_files>" --blocking)
```

Parse the JSON result:
- If `blocked` is `true`: mark the story BLOCKED with reason `"Scope violation: unexpected files changed: <unexpected_files list>"`. Log a friction event: `category: blocked, type: automatic, skill: run-stories, detail: "diff-gate blocked: <unexpected_files>"`. Skip Steps 5b and 5c for this story.
- If `blocked` is `false` and `unexpected_files` is non-empty: log the unexpected files as a warning, but continue (non-blocking). The coder may have legitimately needed adjacent files.
- If `status` is `"error"`: log the error, continue (non-blocking).

### Step 5b: Per-story testing

#### Stories WITH `test_files` (merge gate)

For each DONE story that has `test_files` and both the coder and test agent returned DONE:

1. **Run the merge gate**:
   ```bash
   GATE_RESULT=$(python3 ~/.claude/scripts/merge-gate.py \
     --merge-candidate "<project-root>/.claude/worktrees/merge-candidate/<story-slug>" \
     --story-branch <story-branch> \
     --test-branch <story-branch>--test \
     --dev-branch <dev-branch> \
     --test-cmd "<detected-test-command>" \
     --test-files "<comma-separated test_files>")
   ```

   Parse the JSON result.

2. **If `test_passed` is true**: proceed to step 5 (merge test commits into code worktree).

3. **If `test_passed` is false**: use `classification` to decide retry strategy:

   | `classification` | Attribution | Action |
   |---|---|---|
   | `compile_error` | **Test agent** — wrong interface | Log friction. Re-launch test agent with error output + actual exports. Max 1 retry. |
   | `logic_failure` | **Coder** — implementation wrong | Log friction. Re-launch coder with failing tests as read-only context. Max 1 retry. |
   | `ambiguous` | **Coder** (default) | Same as logic_failure path. |
   | `low_coverage` | **Coder** — insufficient test coverage | Log friction. Delegate to `/fix-loop` — coder adds covered code paths or more tests. |

   Use `error_output` from the JSON result to construct the retry prompt.

   **Test agent retry** (compile_error):
   Re-launch test agent with error output + actual exports from coder's source files as read-only context:
   ```
   Your tests have compile/import errors when run against the real implementation.
   Fix test imports and types to match the actual interface.

   Error output:
   <error_output from merge-gate.py JSON>

   Actual exports from coder's source files (read-only — match your imports to these):
   <relevant export signatures from coder's files in the merge-candidate>
   ```
   Test agent pushes fix to `<story-branch>--test`. Re-run merge-gate.py from step 1.

   **Coder retry via fix-loop** (logic_failure or ambiguous):
   Delegate iterative correction to `/fix-loop` with `--skip-compile` (compile already passed in Step 5.0) and the error context from merge-gate.py:

   ```
   /fix-loop \
     --worktree-path <worktree-path> \
     --skip-compile \
     --max-retries 3 \
     --story-branch <story-branch> \
     --story-id <story_id> \
     --error-context "<error_output from merge-gate.py JSON>"
   ```

   Parse fix-loop's return:
   - **DONE**: Re-run merge-gate.py from step 1. If second attempt also fails, mark BLOCKED.
   - **NEED_DECISION**: Surface to main session.
   - **BLOCKED**: Mark story BLOCKED. Log friction: `category: blocked, type: automatic, skill: run-stories, detail: "fix-loop exhausted: <reason>"`.

   Fix-loop handles error hashing, circuit breakers, and model escalation internally.
   The `compile_error` classification retains its existing inline test-agent retry — it's a test agent fix, not a coder fix, so fix-loop doesn't apply.

4. **After retry**: re-run merge-gate.py from step 1. If second attempt also fails, mark story BLOCKED with the failure output. Log friction: `category: blocked, type: automatic, skill: run-stories, detail: "Merge gate failed after retry: <last error summary>"`. Emit:
   ```bash
   bash ~/.claude/scripts/emit-event.sh "story.blocked" "claude" '{"story_id":"<story_id>","reason":"Merge gate failed after retry: <last error summary>","batch":<batch_num>}'
   ```

5. **On pass** — before cleanup, merge test commits into the code worktree and push:
   ```bash
   # The merge-candidate has coder code + cherry-picked test commits, all validated.
   # Pull the test files into the code worktree so the story branch includes both.
   git -C <code-worktree> fetch origin <story-branch>--test
   git -C <code-worktree> checkout origin/<story-branch>--test -- <test_files>
   git -C <code-worktree> add <test_files>
   git -C <code-worktree> commit -m "<story_id>: add spec tests (validated)"
   git -C <code-worktree> push origin <story-branch>
   ```
   Story proceeds to merge (Step 5c).

6. **Clean up** the merge-candidate worktree (always — on both pass and fail):
   ```bash
   git worktree remove --force "$MERGE_CANDIDATE"
   ```

#### Stories WITHOUT `test_files` (unified merge-gate path)

For each DONE story that passes the diff gate and has no `test_files`:

1. Check if test infrastructure exists in the project (look for test directories, test configs, `jest.config`, `pytest.ini`, `_test.go` files, etc.). If none exists, skip testing for this story — proceed directly to merge.

2. Launch unit-tester agent (background, **Sonnet**) in the worktree. The unit-tester writes tests from the plan file's **acceptance criteria**, not from the implementation.

3. After the unit-tester completes, commit tests to a test branch in the worktree:
   ```bash
   git -C <worktree-path> checkout -b <story-branch>--test
   git -C <worktree-path> add <test-files>
   git -C <worktree-path> commit -m "tests: unit-tester generated tests for <story-id>"
   git -C <worktree-path> push -u origin <story-branch>--test
   git -C <worktree-path> checkout <story-branch>
   ```

4. Run merge-gate.py with the test branch — same as the `test_files` path:
   ```bash
   MERGE_GATE_RESULT=$(python3 ~/.claude/scripts/merge-gate.py \
     --merge-candidate <merge-candidate-path> \
     --story-branch <story-branch> \
     --test-branch <story-branch>--test \
     --dev-branch dev \
     --test-cmd "<detected test command>" \
     --test-files "<unit-tester-generated test files>" \
     --session-id "$SESSION_ID" \
     --story-id <story_id>)
   ```

5. Parse the JSON result. If `test_passed` is false, use `classification` to decide retry strategy — same as the `test_files` path:

   | `classification` | Attribution | Action |
   |---|---|---|
   | `compile_error` | **Unit-tester** — wrong interface | Log friction. Re-launch unit-tester with error output + actual exports. Max 1 retry. |
   | `logic_failure` | **Coder** — implementation wrong | Log friction. Delegate to `/fix-loop` with `--skip-compile` and the error context. |
   | `ambiguous` | **Coder** (default) | Same as logic_failure path. |
   | `low_coverage` | **Coder** — insufficient test coverage | Log friction. Delegate to `/fix-loop` — coder adds covered code paths or more tests. |

   After retry, re-run merge-gate.py. If second attempt also fails, mark story BLOCKED. Log friction: `category: blocked, type: automatic, skill: run-stories, detail: "Merge gate failed after retry: <last error summary>"`.

6. On pass — merge test commits into the code worktree (same as `test_files` path step 5):
   ```bash
   git -C <worktree-path> fetch origin <story-branch>--test
   git -C <worktree-path> checkout origin/<story-branch>--test -- <test-files>
   git -C <worktree-path> add <test-files>
   git -C <worktree-path> commit -m "<story_id>: add spec tests (validated)"
   git -C <worktree-path> push origin <story-branch>
   ```
   Story proceeds to merge (Step 5c).

### Step 5c: Merge

For each story that passes validation (diff gate + testing), invoke `/merge-worktree` (pass all validated story IDs space-separated as args).

After merge completes, update any decision review artifacts created during this run:
```bash
for artifact in decisions/reviews/decision-*.md; do
  if grep -q "story-<story_id>" "$artifact" && grep -q "Status: pending" "$artifact"; then
    sed -i '' 's/Status: pending/Status: success/' "$artifact"
    sed -i '' "s|Merge result:.*|Merge result: merged to dev at $(git rev-parse --short dev)|" "$artifact"
  fi
done
```
For BLOCKED stories, update matching artifacts with `Status: failure` and the block reason.

---

## Step 6: Report

Print a final summary:

```
Run complete.  Dev branch: dev

story-001  batch 0   my-feature--fix-auth-flow      DONE    abc1234   tests: pass    verify: pass
story-003  batch 0   my-feature--update-dashboard   DONE    def5678   tests: skip    verify: pass
story-002  batch 1   my-feature--refactor-handlers  DONE    ghi9012   tests: pass    verify: pass
story-005  batch 0   my-feature--add-search         BLOCKED                          verify: pass

Batch verification:
  batch 0: PASS
  batch 1: PASS

Skipped (validation):
  story-006: state is 'done' — already complete

Deferred (dependency not yet merged):
  story-007: runs after story-005 merges

Blocked during execution:
  story-005: plan file references missing utility function `buildSearchIndex`
  story-008: Watchdog killed: stuck (Read x7) + 68% budget elapsed
```

**Example with batch verification failure:**

```
story-001  batch 0   my-feature--fix-auth         DONE      abc1234  tests: pass  verify: pass
story-003  batch 0   my-feature--update-dash       DONE      def5678  tests: skip  verify: pass
story-002  batch 1   my-feature--refactor-hdl      BLOCKED                         verify: batch 0 failed

Batch verification:
  batch 0: FAIL — src/index.ts(42): Cannot find module './newService'
  batch 1: BLOCKED (batch 0 failed)
```

The `batch` column shows the parallel batch each story ran in (batch 0 = first parallel wave; batch 1 = ran after batch 0 due to conflict; `deferred` = dependency not in this run, not yet merged).

The `verify` column shows the batch verification result for each story's batch. Stories in batches that were blocked by a prior verification failure show `verify: batch N failed`.

If all stories complete successfully, print: "All stories executed successfully."

If any story is BLOCKED, list it with its reason in a "Blocked" section. Never stop other stories due to one failure — they run independently.

If all stories were BLOCKED or skipped (zero DONE), stop after printing the summary.

After printing the report, run `cleanup_run_state.py` as described in "Run state management" above.
