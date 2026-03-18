---
name: draft-plans
description: >
  Graph-node skill: reads .ship-manifest.json (or story/epic IDs), launches one
  background agent per story to write plans/*.md files, applies critique checklist,
  updates DB with plan_file paths. Artifact-chain-aware version of /draft-plan.
  Consumes manifest from /plan-stories, produces plans/*.md for /env-preflight.
triggers:
  - /draft-plans
  - /draft-plans .ship-manifest.json
  - /draft-plans story-NNN story-NNN
  - /draft-plans epic-NNN
args:
  - name: args
    type: string
    description: >
      Manifest path (.json), story IDs (story-NNN), epic IDs (epic-NNN),
      --briefing <path>, and/or --skip-critique. At least one input required.
---

# Draft Plans Skill Invoked

User has requested: `/draft-plans {{args}}`

---

## Step 1: Parse args and detect input mode

Parse `{{args}}` to extract inputs and flags.

**Flags (strip before processing tokens):**
- `--briefing <path>` — store `briefing_path` for agent prompt injection. The next token after `--briefing` is the path.
- `--skip-critique` — set `skip_critique = true`. Skips the critique loop in Step 4.

**Input modes (remaining tokens after flag stripping):**

1. **Manifest mode**: a token ends with `.json` and the file exists (e.g., `.ship-manifest.json`).
   - Read the artifact JSON. Extract story list from `data.stories` (array of story IDs or objects with `story_id` fields).
   - If artifact `data` contains a `briefing_path` field and `--briefing` was not explicitly set, use it as `briefing_path`.
   - Store `manifest` for provenance tracking.

2. **ID mode**: tokens matching `story-\d+` or `epic-\d+`.
   - `story-\d+` tokens: add directly to story ID list.
   - `epic-\d+` tokens: call `pm_list_stories(epic_id=<id>)` and add all non-archived story IDs to the list.

3. **Mixed**: manifest + IDs can coexist. Deduplicate the combined story list.

4. **No args**: error — print usage and stop:
   ```
   Usage: /draft-plans <manifest.json | story-NNN... | epic-NNN...> [--briefing <path>] [--skip-critique]

   Examples:
     /draft-plans .ship-manifest.json
     /draft-plans story-100 story-101 story-102
     /draft-plans epic-50
     /draft-plans .ship-manifest.json --briefing presearch/my-feature.md
   ```

---

## Step 2: Resolve stories

For each story ID in the list:

1. Call `pm_get_story(story_id=<id>)` and read the detail file for tasks, write_files, read_files, agent, title.
2. **Skip** stories that are `done` or `archived` — warn: `"story-NNN: already done/archived — skipping."`
3. **Skip** stories with no tasks — warn: `"story-NNN: no tasks — skipping. Run /plan-stories first."`

**Frontend detection** — classify each story by scanning `write_files`:

- **Flutter**: files under `lib/src/features/*/` with `widget`/`screen`/`page` in name, or `.dart` files in `layout`/`ui`/`widget` directories
- **React**: `.tsx`/`.jsx` files in `components/`/`pages/`/`views/` directories
- **Vue**: `.vue` files
- **CSS/styling**: `.css`, `.scss`, `.sass`, `.less`, `.styl` files

Classification rules:
- If ANY write_file matches a frontend pattern: set `frontend: true`
- If ALL write_files match frontend patterns: set `frontend_only: true`
- If SOME (but not all) match: set `mixed: true`
- If NO write_files match (backend-only): no flag set, existing flow unchanged

**Fast-path detection** (mirrors `/draft-plan` Step 2):
A story qualifies for fast-path when ALL of:
- `agent` = `quick-fixer`
- `write_files` count <= 2
- No file in `write_files` appears in the project's protected-files list
- `pm_get_story` returned at least one task

Fast-path stories: write plan directly in main session (Step 3b). No agent needed.
All other stories: agent-path (Step 3b).

Frontend flags are orthogonal to fast-path — a fast-path story can also be `frontend: true`. Frontend flags affect the plan template and whether `gemini_design` is called in Step 3b.

If no stories remain after filtering, stop: `"No eligible stories to plan."`

---

## Step 3a: Prepare plan-writer launches

1. Read `refs/orch-critique-checklist.md` once — keep content for agent prompts.
2. Glob `plans/*.md` to get existing plan file names.
3. For each story, generate a unique plan file name: `plans/<random-adjective>-<random-noun>.md` — must not collide with existing names.
4. For stories from a manifest, call `pm_predict_preference(domain=<domain>)` where domain is inferred from write_files:
   - `hooks` for hook files, `tracking` for tracking files, `skills` for skill files, `refs` for refs files, `scripts` for script files, etc.
   - If predictions returned, store per-story for inclusion in agent prompts.
5. **Decision lookup** — for each story, query `query_project_decisions(active_files=<write_files>)` via the decisions MCP tool.
   - Load the tool first: `ToolSearch: select:mcp__decisions__query_project_decisions`
   - Call once per story with the story's `write_files` list as `active_files`.
   - Store the result as `decision_constraints` per story.
   - If no decisions found, `decision_constraints` is empty (omit the section from the plan).

6. **Exemplar matching** — for each story, find the most similar existing file to each write target. This captures file-level conventions that bootstrap misses (e.g., registration patterns, import style, function naming within a specific directory).

   For each write_file in the story:
   - Find existing files in the same directory (Glob `<dir>/*.{ext}`).
   - Exclude test files (`*_test.*`) when matching implementation files, and vice versa.
   - If matches found, pick the file with the closest name or purpose (heuristic: shortest edit distance to the write target's filename, or the first non-test file alphabetically).
   - Read the exemplar file (first 100 lines max — enough for conventions, not entire implementation).
   - Extract: package/module declaration, import patterns, exported function signatures, registration patterns (init(), Register*, export style), error handling style, comment conventions.

   Store as `exemplar_conventions` per story. Format for inclusion in the plan-writer prompt:
   ```
   ## Exemplar Conventions

   Nearest existing file to `<write_target>`: `<exemplar_path>`
   Conventions observed:
   - <pattern 1: e.g., "Exported functions use IsFoo naming (IsSemver, IsCron)">
   - <pattern 2: e.g., "No init() — functions exported for manual registration via RegisterValidation()">
   - <pattern 3: e.g., "Uses fl.Field().String() then regex match">
   ```

   If no exemplar found (greenfield directory), note: `"No exemplar — greenfield directory. Follow project-level conventions from CLAUDE.md."`

   **Why this matters:** Bootstrap captures "non-standard validators in separate package" (architectural). Exemplar matching captures "notblank.go exports IsFoo functions without init()" (file-level). The plan writer sees both, so the plan matches actual conventions, not generic assumptions.

---

## Step 3b: Launch plan-writer agents

**Frontend/mixed stories — gemini_design call (before agent launch):**

For each story with `frontend: true` or `mixed: true`:

1. Load the tool: `ToolSearch: select:mcp__gemini__gemini_design`
2. Call `gemini_design(paths=<write_files>, output="plans/<plan-name>-design.md")`
3. Read the design spec output file (`plans/<plan-name>-design.md`)
4. Store the design spec content as `gemini_design_spec` for inclusion in the plan-writer agent prompt

Backend-only stories skip this block entirely.

---

**Fast-path stories** — write directly in main session using metadata-only template (no file reads needed):

```
# <story title>

Story: <story_id>
Agent: <agent>

## Context

<story title>
Files: <write_files>

<If decision_constraints is non-empty for this story:>
## Decision Constraints

These recorded decisions apply to files in this story's write scope. Treat as constraints — violating one requires NEED_DECISION.

<decision_constraints output, verbatim from query_project_decisions>

## What changes

| File | Change |
|---|---|
| <write_file> | <task description> |

<!-- CODER_ONLY -->
## Tasks

1. <task 1>
2. <task 2>
<!-- END_CODER_ONLY -->

## Acceptance criteria

- <one testable statement per task, derived from task description>

## Verification

- Confirm each task is implemented correctly
- No changes outside write scope

<!-- TESTER_ONLY -->
<!-- END_TESTER_ONLY -->
```

No `## Contract` section for fast-path stories.

**Fast-path frontend/mixed stories** — same as above but use this template instead (includes the design spec from the `gemini_design` call):

```
# <story title>

Story: <story_id>
Agent: <agent>

## Context

<story title>
Files: <write_files>

<If decision_constraints is non-empty for this story:>
## Decision Constraints

These recorded decisions apply to files in this story's write scope. Treat as constraints — violating one requires NEED_DECISION.

<decision_constraints output, verbatim from query_project_decisions>

## What changes

| File | Change |
|---|---|
| <write_file> | <task description> |

## Frontend Design (Gemini)

<verbatim content from gemini_design_spec>

## Architecture (Claude)

<state management, data flow, integration points — written by main session based on task descriptions>

<!-- CODER_ONLY -->
## Tasks

1. <task 1>
2. <task 2>
<!-- END_CODER_ONLY -->

## Acceptance criteria

- <one testable statement per task, derived from task description>

## Verification

- Confirm each task is implemented correctly
- No changes outside write scope

<!-- TESTER_ONLY -->
<!-- END_TESTER_ONLY -->
```

Backend-only fast-path stories continue using the existing template above (no Frontend Design section, no Architecture section).

**Agent-path stories** — launch one `general-purpose` background agent per story with `run_in_background: true`. Prompt template:

```
You are writing a plan file for story <story_id>: "<title>"

Agent: <agent>
Tasks: <task list from pm_get_story>
Write files: <write_files list>
Read files: <read_files list>
Output file: plans/<name>.md

<If predicted preferences exist for this story:>
## Predicted Preferences
  - <domain>: <preference text> (confidence: <score>)

<If decision_constraints is non-empty for this story:>
## Decision Constraints (include verbatim in plan)

These recorded decisions apply to files in this story's write scope.
Include this section in the plan file after ## Context and before ## What changes.
Coders must treat these as constraints — violating one requires NEED_DECISION.

<decision_constraints output>

<If exemplar_conventions is non-empty for this story:>
## Exemplar Conventions (include verbatim in plan)

These file-level conventions were extracted from the nearest existing file to each write target.
The plan's tasks MUST follow these conventions. They override generic pattern defaults.

<exemplar_conventions output>

<If story has frontend: true or mixed: true, include:>
## Gemini Design Spec (include verbatim in plan)
<gemini_design_spec content from the gemini_design call in Step 3b>

Include the above design spec as the `## Frontend Design (Gemini)` section of the plan file.
Write the `## Architecture (Claude)` section yourself, ensuring it integrates with the design.
The Architecture section covers: state management, data flow, API connections, integration points.

## Critique Checklist
<full checklist content from refs/orch-critique-checklist.md>

## Instructions

1. Read the story's write_files to understand what exists today.
2. Read files referenced by tasks but not in write_files — these become read-only context.
   Identify all new or modified public interfaces from write_files.
3. Apply the critique checklist against the Gemini-planned tasks:
   - If SIGNIFICANT issues found (missing files, scope creep, convention violations):
     Return: "NEED_DECISION: <issue>\nOption A: <fix>\nOption B: <fix>"
   - If MINOR gaps (edge cases, existing utilities): incorporate silently.
3.5. Extract function/class signatures for every new or modified public interface found
   in step 2. Write the `## Contract` section with signatures in the format:
   `functionName(param: Type, param2: Type) -> ReturnType` — one-line purpose.
   Include import paths for shared interfaces that the test agent needs.
3.6. Convert Gemini tasks into testable acceptance criteria (given/when/then or
   equivalent). Each criterion should map to at least one task. If the story has
   `test_files`, each criterion must reference the specific test file that will verify
   it. Write the `## Acceptance criteria` section.
4. Write the plan file to plans/<name>.md with this structure:

   # <story title>

   Story: <story_id>
   Agent: <agent>

   ## Context

   <Brief description of what this story accomplishes>

   ## Decision Constraints

   <If provided in the prompt above, include verbatim. Omit section if none.>

   ## What changes

   | File | Change |
   |---|---|
   | <write_file> | <description from tasks> |

   <!-- CODER_ONLY -->
   ## Read-only context

   These files inform the implementation but should not be modified:
   - `path/to/file` — why it's relevant
   <!-- END_CODER_ONLY -->

   ## Contract

   <for each new/modified public function or class>
   - `functionName(param: Type, param2: Type) -> ReturnType` — one-line purpose
   - `ClassName` — purpose
     - `method(param: Type) -> ReturnType`
   <import paths for shared interfaces that test agent needs>

   <!-- CODER_ONLY -->
   ## Tasks

   1. <task 1>
   2. <task 2>
   <!-- END_CODER_ONLY -->

   ## Acceptance criteria

   These define correctness independently of the implementation:
   - Given <precondition>, when <action>, then <expected outcome>

   ## Verification

   - <how to verify the changes work>

   <!-- TESTER_ONLY -->
   <!-- END_TESTER_ONLY -->

   **For frontend/mixed stories** (when Gemini Design Spec is provided), use this
   alternate structure instead — replaces `## Read-only context` through `## Tasks`:

   # <story title>

   Story: <story_id>
   Agent: <agent>

   ## Context

   <Brief description of what this story accomplishes>

   ## Decision Constraints

   <If provided in the prompt above, include verbatim. Omit section if none.>

   ## What changes

   | File | Change |
   |---|---|
   | <write_file> | <description from tasks> |

   ## Frontend Design (Gemini)

   <verbatim from Gemini Design Spec section above>

   ## Architecture (Claude)

   <state management, data flow, integration points — written by the agent>

   <!-- CODER_ONLY -->
   ## Read-only context

   These files inform the implementation but should not be modified:
   - `path/to/file` — why it's relevant
   <!-- END_CODER_ONLY -->

   ## Contract

   <same contract rules as backend template>

   <!-- CODER_ONLY -->
   ## Tasks

   1. <task 1>
   2. <task 2>
   <!-- END_CODER_ONLY -->

   ## Acceptance criteria

   These define correctness independently of the implementation:
   - Given <precondition>, when <action>, then <expected outcome>

   ## Verification

   - <how to verify the changes work>

   <!-- TESTER_ONLY -->
   <!-- END_TESTER_ONLY -->

   Backend-only stories use the template above (no Frontend Design or Architecture sections).

4.5. Wrap the `## Tasks` section and `## Read-only context` section in
   `<!-- CODER_ONLY -->` / `<!-- END_CODER_ONLY -->` HTML comment delimiters.
   These are invisible to markdown renderers but parsed by run-stories to filter
   what each agent sees. Shared sections (Context, Decision Constraints, What changes,
   Contract, Acceptance criteria, Verification) must NOT be wrapped — both agents need them.
5. If briefing_path was provided, include it in read-only context and reference
   specific sections in task descriptions.
   Format: (see briefing ## <Section> > <Subsection> for <what>)
6. Return: "DONE: plans/<name>.md"
```

**If `briefing_path` is set**, append to each agent's prompt:
```
Briefing path: <briefing_path>
Include this file in read-only context. Reference specific briefing sections in
task descriptions for any task involving APIs, data models, patterns, or gotchas.
```

---

## Step 3c: Collect results

Wait for all background agents to complete. For each result:

- **`DONE: plans/<name>.md`** — call `pm_update_story(story_id=<id>, plan_file="plans/<name>.md")`.
- **`NEED_DECISION: <issue>`** — surface to user with the options provided, get answer, resume agent with the decision.
- **`BLOCKED: <reason>`** — report to user, skip story, do not update DB.

**Frontend section validation** — for stories with `frontend: true` or `mixed: true`, read the plan file and check:

- `## Frontend Design (Gemini)` section must be present and non-empty
- `## Architecture (Claude)` section must be present and non-empty

If either section is missing or empty, reject the plan:
> "Plan rejected: frontend story requires both ## Frontend Design (Gemini) and ## Architecture (Claude) sections."

Retry once — re-launch the plan-writer agent with the rejection message appended. If the second attempt also fails, mark as `BLOCKED` and surface to user.

Backend-only stories skip this validation entirely.

Also call `pm_update_story(story_id=<id>, plan_file="plans/<name>.md")` for each fast-path story written in the main session.

---

## Step 4: Critique loop (MCP Delegation — ORCHESTRATION section 15)

**Skip when:** `skip_critique = true` (`--skip-critique` flag) or when the caller will invoke `/critique --plans` separately (the graph-node pattern). If skipping, proceed directly to Step 5.

After all plan files are written and stored in the DB, delegate the entire critique phase to a single foreground subagent. This avoids bloating main-session context with verbose `pm_critique` and `pm_add_decision` JSON responses.

### 4a: Construct the subagent prompt

Build the prompt from the following pieces:

```
You are the critique subagent for /draft-plans. Your job is to critique plan files,
record decisions, and store learnings — then return a compact summary.

## Plan files to critique

<For each plan file from Step 3c, include:>
- Plan file path: <plan_file_path>
  Story ID: <story_id>
  Has test_files: <true/false>
  Agent: <agent field from story>

## Tool loading

Before starting, load the tools you need:
```
ToolSearch: select:mcp__gemini__pm_critique,mcp__gemini__pm_add_decision
ToolSearch: select:mcp__openmemory__openmemory_query,mcp__openmemory__openmemory_store
```

## Critique logic

For each plan file, execute this sequence:

### 1. Query OpenMemory for past learnings

openmemory_query(query="critique learnings [domain keywords from plan write_files]", tags=["critique-learning"], user_id="proj:<current-project>")
openmemory_query(query="critique blind spot [domain keywords from plan write_files]", tags=["gemini-blind-spot"], user_id="proj:<current-project>")

Collect into past_learnings and past_blind_spots lists. If OpenMemory is unavailable, proceed without.

### 2. Self-critique (2 passes max, 5 plan-scoped lenses)

Apply these 5 lenses per plan file:

1. **Requirement coverage**: Do plan tasks cover all story requirements? Cross-reference ## Tasks against ## Acceptance criteria and the story description.
2. **Gap analysis**: Missing error paths, edge cases in the planned implementation? Check each task for unhandled failure modes, missing rollback/validation/logging.
3. **Weakest part**: Which task is most likely to fail or be incomplete? Flag tasks with vague descriptions, unverified assumptions, or unfamiliar APIs.
4. **Alternative design**: Simpler approach the plan missed? Could fewer files change? Could tasks be consolidated? Existing utility that eliminates a task?
5. **Assumption audit**: What does the plan assume about existing code that might be wrong? Flag assumptions about file structure, function signatures, data shapes.

**Past Omissions check**: If past_blind_spots is non-empty, force-check relevant patterns against the plan.

For each lens, either:
- **Improve**: describe the issue and fix the plan file in place (Edit tool).
- **NMIP**: declare "No Material Improvements Possible" with a one-line justification.

**Iteration 1**: Apply all 5 lenses. If any improvements made, proceed to Iteration 2.
If all 5 are NMIP, skip Iteration 2.

**Iteration 2**: Apply the same 5 lenses to the improved plan. Max 2 iterations per plan.

### 3. Gemini escalation

For each plan file, call pm_critique with the story ID:

pm_critique(story_id="<story_id>", input="<current plan file content>", context="Plan critique — iteration 3 (external review). Claude's critique history: [iterations and NMIP declarations]. Past blind spots: [list or 'None recorded']. Your job: challenge NMIP declarations, check for missing tasks, flag hidden complexity, be specific.")

Process Gemini's response:
- **Valid and material**: fix the plan file in place. Note as Gemini-sourced.
- **Valid but minor**: incorporate if easy, note if not.
- **Disagree**: record why — don't silently discard.

### 4. Contract gate (agent-path stories only, skip for fast-path)

- If test_files exist on the story AND ## Contract section is missing or empty: reject. Return the plan to the plan-writer agent with: "Plan rejected: missing ## Contract section. Story has test_files — test agent needs function signatures to write tests. Extract signatures from write_files and add ## Contract." Retry once.
- If ## Acceptance criteria section is missing or contains fewer criteria than tasks: reject. Return with: "Plan rejected: missing or insufficient ## Acceptance criteria. Each task needs at least one testable criterion." Retry once.
- Stories without test_files: contract section is recommended but not gating. Acceptance criteria still required (minimum 1 per story).

### 5. Record decisions and store learnings

- For any significant design decisions made during critique, call pm_add_decision with the decision details.
- Store critique learnings: openmemory_store(content="Critique of [plan_file]: [1-2 sentence summary]", tags=["critique-learning"], user_id="proj:<current-project>")
- If Gemini found something Claude NMIP'd: openmemory_store(content="Critique blind spot: Claude NMIP'd [question] but Gemini found [issue]. Pattern: [what to check for].", tags=["gemini-blind-spot"], user_id="proj:<current-project>")

### 6. Do NOT append ## Self-critique sections to plan files

Coders don't need critique metadata. Findings go in the summary only.

## Required return format

Return EXACTLY this structured text (no other output):

CRITIQUE_SUMMARY:
  plans_improved: <N>
  plans_clean: <M>
  total_plans: <N+M>

PLAN_RESULTS:
  <plan_file_path>:
    status: improved | clean
    improvements: ["<description>"] | []
    gemini_findings: <count> (<addressed> addressed, <noted> noted, <disagreed> disagreed)
    unresolved: ["<concern>"] | []
    decisions_recorded: ["<decision summary>"] | []
    blind_spots_checked: ["<pattern>"] | []

LEARNINGS_STORED: <count> | 0
DECISIONS_RECORDED: ["decision-NNN: <summary>"] | []
```

### 4b: Launch the subagent

Launch as a **foreground** (not background) subagent:

```
Agent(subagent_type="general-purpose", prompt=<constructed prompt from 4a>)
```

Wait for the subagent to return. The main session receives only the compact CRITIQUE_SUMMARY text — no raw pm_critique or pm_add_decision JSON responses appear in main-session context.

### 4c: Parse the subagent result

After the subagent returns:

1. Parse the CRITIQUE_SUMMARY block for the Step 5 report:
   - Extract `plans_improved`, `plans_clean`, `total_plans` for the summary line.
   - Extract per-plan results from PLAN_RESULTS for detailed reporting.
   - Extract DECISIONS_RECORDED for provenance tracking.

2. **Unresolved concerns**: If any plan has non-empty `unresolved` entries, surface them to the user before proceeding to Step 5:
   > "Critique found unresolved concerns in <plan_file>: <concerns>. Proceed anyway?"
   Wait for user confirmation before continuing.

3. **Contract gate rejections**: If a plan was rejected by the contract gate (missing Contract or Acceptance criteria), the subagent will have already retried with the plan-writer agent. If the retry also failed, the plan's status will include the rejection in `unresolved` — surface it per rule 2 above.

---

## Step 5: Report results

Print summary:

```
Draft plans complete.

  story-NNN -> plans/<name>.md
  story-NNN -> plans/<name>.md (fast-path)
  story-NNN -> BLOCKED: <reason>

<If critique ran:>
Critique: N plans improved, M passed clean. <Notable findings if any.>
```

If any agents failed or returned errors, list under an `Errors:` section.

---

## Artifact contract

**Reads:** `.ship-manifest.json` (from `/plan-stories`) or inline story/epic IDs
**Writes:** `plans/*.md` (one per story)
**DB side effects:** `pm_update_story(plan_file=...)` for each successful plan

When invoked as a graph node by `/ship`, the caller proceeds to `/env-preflight` after this skill completes. When invoked standalone, the user decides next steps.
