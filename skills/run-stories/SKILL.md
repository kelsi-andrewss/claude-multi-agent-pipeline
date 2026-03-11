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

---

## Step 2c: Build verification (reference)

This block defines the reusable build verification logic referenced by both the bootstrap gate and Step 4.1 (batch verification). It is not executed directly — it is invoked by those steps.

### Project-type detection

Detect the project type by checking for build system files in the project root:

| File | Project type | Build command | Lint command |
|---|---|---|---|
| `package.json` | Node/TS | `npm install && npm run build` (or `npx tsc --noEmit` if no `build` script in package.json) | `npm run lint` (only if `lint` script exists in package.json) |
| `pubspec.yaml` | Flutter | `flutter pub get && flutter analyze` | (included in analyze) |
| `pyproject.toml` | Python | `pip install -e . 2>&1 \| tail -5` | — |
| `Cargo.toml` | Rust | `cargo check && cargo clippy --quiet 2>&1` | (included in clippy) |
| `go.mod` | Go | `go build ./... && go vet ./...` | (included in vet) |

### Failure semantics

- Non-zero exit code on build/typecheck command = **FAIL** (blocks downstream).
- Lint warnings with zero exit code = **PASS with warnings** (log warning count, do not block).
- No recognized build system file found = **SKIP** verification. Log: "No recognized build system — skipping batch verification."

### Bootstrap gate (existing behavior, unchanged)

After the bootstrap batch (Group 0) completes and merges into the dev branch, before launching Group 1:

1. Checkout the dev branch (post-bootstrap-merge).
2. Run build verification using the commands above.
3. If PASS → continue to Group 1 (launch feature stories).
4. If FAIL → report the error, mark all remaining stories as BLOCKED with reason "Bootstrap build verification failed: <error>", stop execution.

**This gate ONLY fires when a bootstrap story was detected in Step 2a-post AND that story's batch has completed and merged.** If no bootstrap story, skip entirely — zero overhead.

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

Process each dependency group sequentially. Within each group, process conflict batches.

After each batch's stories complete and merge via Step 5c, run **Step 4.1 Batch Verification** before launching the next batch. If verification fails, skip all remaining batches.

### For each parallel batch — launch all stories simultaneously

Launch all stories in the batch in **a single message** as `general-purpose` agents with `run_in_background: true`.

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
If write targets include symbol annotations (e.g., "file.ts:functionName"), limit your changes in that file to the annotated symbol/section. Do not modify other functions or sections in the same file.
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

**When `has-test-files` is true**, additionally modify the coder prompt and launch a parallel test agent:

**Coder prompt addition** (append to the coder prompt above, before the Steps section):
```
## Test file prohibition
You are the CODER. Do NOT create or modify test files. Test files for this story: <test_files list>. Leave them to the test agent.
```

**Test agent** — launched simultaneously with the coder as a second `general-purpose` background agent (model: Sonnet):

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

## Steps

1. Create the test worktree from the dev branch (NOT the story branch — you must not see the coder's changes):
   ```bash
   cd <project-root>
   git fetch origin <dev-branch>
   git show-ref --verify --quiet "refs/heads/<story-branch>--test" || git branch "<story-branch>--test" <dev-branch>
   git worktree list | grep -q '<test-worktree-path>' || git worktree add <test-worktree-path> "<story-branch>--test"
   ```

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
2. Run build verification using the project-type detection and commands from Step 2c.
3. Results:
   - **PASS**: Log `"Batch N verification: PASS"`. Continue to the next batch.
   - **PASS with lint warnings**: Log `"Batch N verification: PASS (warnings: <count>)"`. Continue to the next batch. Include warning summary in Step 6 report.
   - **FAIL**: Log `"Batch N verification: FAIL — <error output (last 30 lines)>"`. Mark ALL stories in subsequent batches as BLOCKED with reason `"Blocked: batch N verification failed"`. Do NOT block stories in the current batch (they already merged successfully). Stop executing further batches.

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

#### Stories WITH `test_files` (merge gate)

For each DONE story that has `test_files` and both the coder and test agent returned DONE:

1. **Create a merge-candidate worktree** from the story branch:
   ```bash
   MERGE_CANDIDATE="<project-root>/.claude/worktrees/merge-candidate/<story-slug>"
   git worktree add "$MERGE_CANDIDATE" <story-branch>
   ```

2. **Cherry-pick the test agent's commit(s)** into the merge-candidate worktree:
   ```bash
   # Get the test agent's commit hash(es) from the --test branch
   TEST_COMMITS=$(git -C "$MERGE_CANDIDATE" log --oneline origin/<story-branch>--test --not origin/<dev-branch> --reverse --format=%H)
   git -C "$MERGE_CANDIDATE" cherry-pick $TEST_COMMITS
   ```
   If cherry-pick conflicts, this is a file overlap between coder and test agent — attribute to **test agent** (wrote to files outside test_files scope). Log friction: `category: retry, type: automatic, skill: run-stories, detail: "cherry-pick conflict — test agent wrote outside test_files scope"`. Skip to test agent retry (step 4).

3. **Run the test suite** in the merge-candidate worktree. Use the project's test runner (detect from `package.json` scripts, `pytest.ini`, `_test.go`, etc.). Run only the test files from `test_files`, not the full suite:
   ```bash
   cd "$MERGE_CANDIDATE" && <test-command> <test_files>
   ```
   Capture exit code and full output.

4. **Failure attribution** — classify test output and retry (max 1 retry per agent, max 2 total):

   | Signal | Attribution | Action |
   |--------|------------|--------|
   | Test **compile/import error** | **Test agent** — wrong interface from plan | Log friction `category: retry, type: automatic, skill: run-stories`. Re-launch test agent (see below). Max 1 retry. |
   | Test **logic failure** (assertion failed, wrong value, timeout) | **Coder** — implementation doesn't match spec | Log friction `category: retry, type: automatic, skill: run-stories`. Re-launch coder (see below). Max 1 retry. |
   | **Mixed** (some compile, some logic) | Prioritize compile errors first | Fix compile errors (test agent retry), then re-run. If logic failures remain, retry coder. |
   | **Ambiguous** (runtime error that could be either) | **Coder** — default attribution | Same as logic failure path. Coder owns runtime behavior. |

   **Detection heuristic** — classify from test runner exit code + output:
   - **Compile/import error**: output contains `Cannot find module`, `is not a function`, `has no exported member`, `ImportError`, `ModuleNotFoundError`, `undefined is not`, `TypeError:`, `SyntaxError:`, or other type/parse errors
   - **Logic failure**: output contains `AssertionError`, `Expected .* to equal`, `expected .* but got`, `FAIL` with assertion details, `TimeoutError`, `timed out`
   - If output matches neither pattern clearly, default to **coder** attribution (logic failure)

   **Test agent retry** (compile/import error):
   Re-launch test agent with error output + actual exports from coder's source files as read-only context:
   ```
   Your tests have compile/import errors when run against the real implementation.
   Fix test imports and types to match the actual interface.

   Error output:
   <test runner output>

   Actual exports from coder's source files (read-only — match your imports to these):
   <relevant export signatures from coder's files in the merge-candidate>
   ```
   Test agent pushes fix to `<story-branch>--test`. Re-run merge-candidate validation from step 1.

   **Coder retry** (logic failure):
   Before cleaning up the merge-candidate, read the failing test files. Re-launch coder with:
   ```
   Your implementation failed spec-derived tests. The tests were written independently from
   your code, based on the acceptance criteria in the plan.

   Failing tests:
   <test runner output>

   Test file (read-only — do not modify):
   <test file contents>

   Fix your implementation to pass these tests. The tests define correct behavior.
   ```
   Coder pushes fix commit to `<story-branch>`. Re-run merge-candidate validation from step 1.

   **After retry**: if second attempt also fails, mark story BLOCKED with the failure output. Log friction: `category: blocked, type: automatic, skill: run-stories, detail: "Merge gate failed after retry: <last error summary>"`.

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

#### Stories WITHOUT `test_files` (existing behavior)

For each DONE story that passes the diff gate and has no `test_files`:

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

The `batch` column shows the parallel batch each story ran in (batch 0 = first parallel wave; batch 1 = ran after batch 0 due to conflict; `deferred` = cross-epic dependency not yet merged).

The `verify` column shows the batch verification result for each story's batch. Stories in batches that were blocked by a prior verification failure show `verify: batch N failed`.

If all stories complete successfully, print: "All stories executed successfully."

If any story is BLOCKED, list it with its reason in a "Blocked" section. Never stop other stories due to one failure — they run independently.

If all stories were BLOCKED or skipped (zero DONE), stop after printing the summary.
