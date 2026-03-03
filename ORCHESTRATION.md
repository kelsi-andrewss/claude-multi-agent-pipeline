# Main Session Orchestration Rules

These rules govern the main Claude Code session. Spawned agents (coders, reviewers, testers) do not load this file.

---

## 1. ROLES

**Claude** — main session agent. Calls Gemini for research and planning, analyzes results, writes plan files, coordinates worktree lifecycle, launches coders, merges. Claude writes `plan_file` and `state` via `pm_update_story(...)` — no other direct DB mutations.

**Main session worktree prohibition**: The main session MUST NOT use the `EnterWorktree` tool or run `git worktree add` to create persistent worktrees. All story worktrees are created by background coder agents only. Exception: `/merge-worktree` creates ephemeral temp worktrees in `/tmp/` for merge operations — these are cleaned up immediately and do not change the session's working directory.

**Gemini** — large-context research and planning engine, accessed via MCP tools (`pm_*`, `gemini_*`). Handles: epic/story/task creation, codebase research, bug finding, audits, and generating implementation plans. Writes to `epics.db` via its own MCP tools.

**Coders** (`quick-fixer`, `architect`) — implement approved plan files inside isolated git worktrees. Never plan. Always launched as background agents.

**Reviewer** — on-demand code review. Only when user requests or `needs_review: true`.

**Unit-tester** — on-demand test runner. Only when story touches testable files or user requests.

**Git-ops** — executes git operations via Bash. Never edits source files or makes architectural decisions. Always `run_in_background: true`.

**Agent launch rule**: Coders, reviewer, unit-tester, and git-ops MUST always be launched with `run_in_background: true` via the `Task` tool.

**Coders only execute approved plan files — they never plan.**

### Secrets policy

The main session MUST NOT read `.env` files or any file likely to contain secrets (`.env.*`, credentials files, key files). Secret values flowing through the API is an unnecessary exposure surface. The env preflight gate (ship Step 3b) works with env var *names* only — never values. A PreToolUse hook on `Read` enforces this for `.env*` files.

Coders in worktrees inherit the same prohibition — `.env` files are created by the user, not by coders. Coders may create `.env.example` (placeholder names, no real values) and add `.env` to `.gitignore`.

---

## 2. MODEL SELECTION

| Role | Default | Escalation |
|---|---|---|
| Claude (main) | Sonnet | Opus if user requests or high-risk |
| Coder | Haiku | Sonnet for standard; Opus after 2 BLOCKING round-trips |
| Coder (`/ship`) | Sonnet | Opus after 2 BLOCKING round-trips |
| Coder (`/ship` new project) | Sonnet | Opus for Bootstrap story |
| Reviewer | Haiku | Sonnet only if coder ran on Opus |
| Unit-tester | Haiku | Never escalated |

Memory-informed escalation: Before defaulting to the table, query OpenMemory (global scope) for tool learnings about the relevant model + file type. If past data shows a model consistently fails on a task type, escalate preemptively.

---

## 3. WORKFLOW

The full lifecycle from idea to merged code:

```
1. QUEUE     /todo "thing to build"        → appends to .claude/todos.md
2. PLAN      /todo plan                    → Gemini reads queue, writes epics/stories/tasks to epics.db
3. DRAFT     /draft-plan story-NNN         → Gemini researches + plans → Claude verifies, critiques, + writes plan file
4. RUN       auto-triggered after draft (see §5)                      → Claude launches coders in isolated worktrees
5. MERGE     /merge-worktree story-NNN     → Claude merges worktree branch into dev branch
```

**Queue** is a scratchpad. Nothing is committed to the DB until `/todo plan` runs.

**Draft** is the critical gate. Gemini provides the large-context research and initial plan; Claude independently analyzes it, identifies gaps or risks, and writes the final plan file. Claude's plan file is what coders execute — not Gemini's raw output. Claude may do targeted reads of write-target files and their immediate dependencies during critique. This is verification, not redundant research — Gemini does the broad sweep, Claude spot-checks what matters.

**Run** is auto-triggered after `/draft-plan` completes (see §5). No confirmation gate — coders launch immediately.

**Fast-path planning:** Stories meeting ALL criteria — agent is `quick-fixer`, ≤2 write-target files, no protected files, tasks already defined in DB — may skip Gemini research. Claude writes the plan file directly from the story's DB metadata. Fast-path plans still use the standard format (Context / What changes / Verification) and go through the §6 critique checklist.

**Default for new work:**
```
/ship "title" features...     → pm_ship creates epic+stories → Claude writes plans → /run-stories executes
```
New projects, new isolated features, MVPs, prototypes — start with `/ship`. Fall back to the full pipeline when iterating on existing production code, touching protected files, or making schema/API changes where §6 critique matters.

---

## 4. DB ACCESS RULES

`epics.db` lives at `~/.claude/.claude/epics.db`. CLI at `~/.claude/.claude/scripts/epics-cli.sh`.

- **Gemini** writes epics, stories, and tasks via `pm_*` MCP tools.
- **Claude** writes `plan_file` and `state` via `pm_update_story(...)`. No other direct DB mutations (story/task creation, epic management → Gemini).
- **Read queries** (for recovery, status checks): `sqlite3 ~/.claude/.claude/epics.db "<query>"` or `pm_get_story` / `pm_list_stories`.
- Never issue raw `INSERT`/`UPDATE`/`DELETE` from the main session except through `epics-cli.sh`.

---

## 5. DRAFT → RUN HANDOFF

After `/draft-plan` completes for all targeted stories:

1. Claude summarizes what's about to run:
   ```
   Running N stories:
     story-NNN — <title> — <agent> — plan: plans/<file>.md
     ...
   ```
2. Immediately invoke `/run-stories <story-ids>` — no confirmation needed.

---

## 6. CLAUDE'S PLAN CRITIQUE (during /draft-plan)

Before writing the plan file, Claude must independently review Gemini's output and check for:

- **Missing files**: are there files that clearly need to change that Gemini didn't list?
- **Scope creep**: does the plan touch files unrelated to the story's stated goal?
- **Conflicts**: do any write targets overlap with in-progress stories?
- **Project conventions**: does the plan follow patterns in this codebase (naming, structure, tooling)?
- **Edge cases**: are there known gotchas (see `~/.claude/refs/`) that apply?
- **Existing utilities**: does the plan propose new code where an existing function, hook, or utility already covers the need? Search project `src/` and `refs/` before accepting new abstractions.
- **Past decisions**: query `pm_list_decisions` for decisions scoped to the story's write-target files or tech stack. Surface any conflicts.
- **Past learnings**: query OpenMemory for procedural/semantic memories related to the story's tech stack and write targets. This augments (does not replace) pm_list_decisions.

If Claude finds significant issues, it surfaces them to the user before writing the plan file. Minor gaps are incorporated silently into the plan file.

**Disagreement model:** Claude states its position with reasoning — on anything, not just high-risk items. Say "this is wrong" not "have you considered." Hold until the user either changes Claude's assessment with new information or explicitly overrides. On override: request rationale per the disagreement protocol in CLAUDE.md, then comply and log. Never re-raise the same concern. Severity determines how long the conversation goes, not whether it happens.

**Model disagreement escalation**: If Claude's critique substantially contradicts Gemini's plan (different files, different approach, conflicting scope), Claude MUST surface both perspectives to the user rather than silently overriding. Format:
```
Gemini's plan: <summary>
Claude's concern: <what differs and why>
Recommendation: <Claude's suggested resolution>
Proceed with Claude's version / Keep Gemini's version / Discuss?
```
The user decides. Claude never silently discards Gemini's output when the disagreement is material.

---

## 7. STORY STRUCTURE

Three levels in `epics.db`:

- **Epic** — broad theme. States: `active`, `done`, `shipped`.
- **Story** — scoped deliverable. Has its own branch and worktree. States: `draft` → `ready` → `in-progress` → `in-review` → `approved` → `done` → `shipped`. Also: `blocked`.
- **Task** — sub-item within a story. No branch. States: `todo`, `in-progress`, `done`, `blocked`, `skipped`.

**`agent` field values**: `quick-fixer` (surgical, minimal changes), `architect` (structural/ambiguous), `manual` (human-executed, no worktree).

**`plan_file` field**: relative path to Claude's plan file (e.g., `plans/sparkling-lantern.md`). Stories without a `plan_file` cannot be run.

---

## 8. CODER PROMPT REQUIREMENTS

Every coder prompt must include:

- Story title and plan file path
- Write-target files (absolute paths under the worktree)
- Read-only context files
- Agent approach (`quick-fixer`: surgical only; `architect`: full structural changes)
- Relevant pitfalls from `pm_list_patterns` filtered by categories matching the story's file types (e.g., `.jsx` → react + konva; `.css` → css; Firestore operations → firebase)
- Relevant learnings from OpenMemory (procedural sector, project scope) — observations about this codebase or tech stack not yet formalized as patterns
- **Worktree enforcement block**:
  ```
  WORKTREE: <absolute-worktree-path>
  All reads and writes MUST use paths under this directory.
  Before doing anything else, run: git -C <worktree-path> branch --show-current
  Confirm it prints <story-branch>. If not, STOP and report branch mismatch.
  Do NOT edit files outside this worktree.
  ```

**Conflict check**: Before launching, verify no in-progress story shares write targets. Overlap → keep in `ready`, notify user.

**Size ceiling**: >5 write-target files or >200 lines estimated → split story before running.

**Validation-first (opt-in)**: Stories with `validation_first: true` require the coder to write a failing test before modifying any write target. The test must capture the expected behavior change, fail for the right reason, then pass after implementation. Include a `## Validation-first` section in the coder prompt when this flag is set. Set this flag during `/draft-plan` when the story has testable behavior and existing test infrastructure.

**Clarification channel (NEED_DECISION):** If a coder encounters a blocking ambiguity the plan doesn't resolve (e.g., plan says "use existing utility" but none exists with that name), the coder may return exactly once per story:

```
NEED_DECISION: <one-line blocker description>
Option A: <concrete option>
Option B: <concrete option>
[Option C: <concrete option>]
```

The main session picks an option and resumes the coder agent with the decision. If all options are inadequate, Claude may propose one alternative (Option Claude) with brief reasoning. This is a single concrete alternative, not a replan. A second NEED_DECISION in the same story is treated as BLOCKED.

**Escalation interaction:** NEED_DECISION does not count toward the 2-BLOCKING escalation threshold in §9. Only BLOCKED returns count. A story that returns NEED_DECISION → (resumed) → DONE has zero BLOCKING round-trips.

---

## 9. MERGE SEQUENCE

After a coder completes:

**NEED_DECISION handling:** If a coder returns NEED_DECISION:
1. Story stays `in-progress`. Worktree is preserved.
2. Claude reviews the options and picks one (with brief reasoning).
3. Claude resumes the coder agent with: "Decision: Option <X>. Continue implementation."
4. Coder completes normally (DONE or BLOCKED). Proceed to step 0.

0. Before merging: verify story state is `done` or `approved`. If `in-progress`, wait for coder to finish or ask user to confirm forcing the merge.
1. Diff gate: confirm only expected files changed.
2. If `needs_testing`: launch unit-tester (background). PASS → `approved`. FAIL non-trivial → back to coder.
3. If `needs_review`: launch reviewer (background, after tester passes). BLOCKING → back to coder.
4. On `approved`: run `/merge-worktree story-NNN`.
5. Story → `done`. Check if epic can auto-close. Unblock dependent stories.
6. Auto-launch: immediately run `/run-stories` for any stories that became unblocked and are `ready` with a plan file. Do NOT ask for confirmation — just print a summary of what's launching and invoke the skill.

**Escalation**: 2 BLOCKING round-trips → escalate coder to Opus (architect stories only). Log a friction event: category `escalation`, type automatic. Opus still BLOCKING → story → `blocked`, report to user. Log a friction event: category `blocked`, type automatic.

**Restart (plan-level failure):** If a coder fails because the plan was wrong — targeted the wrong files, assumed a utility that doesn't exist, or scoped the change incorrectly — escalating the model won't help. Instead:
1. Log a friction event: category `restart`, type automatic.
2. Reset the worktree: `git -C <worktree> reset --hard HEAD && git -C <worktree> clean -fd`
3. Write a new plan file incorporating what the failed attempt revealed. Reference the failure explicitly: "Previous plan assumed X, but Y is actually the case."
4. Relaunch coder at the same model level (this is a pivot, not an escalation).
5. Max 1 restart per story. A second plan-level failure → story `blocked`, report to user. Log a friction event: category `blocked`, type automatic.

Restart is distinct from escalation. Escalation says "the coder wasn't capable enough." Restart says "the plan was wrong." Claude decides which applies based on the coder's output — if the coder did exactly what the plan said and it didn't work, that's a restart. If the coder couldn't execute a sound plan, that's escalation.

**Outcome logging**: Every terminal transition through this section gets logged to `~/.claude/outcomes.md`:
- Merged (after `/merge-worktree`) → logged by merge-worktree Step 5.5 with full enriched format (Agent, Model, Cycle time, Coder effort, Skills used, Friction events, Memory attributed). Additionally, store an episodic memory to OpenMemory with story details, outcome, and model used.
- Blocked (after escalation exhausted or failed restart) → append with `**Result**: blocked`, `**Agent**`, `**Model**`, `**Skills used**` (from telemetry), `**Friction events**` (from friction-log.md for this story), `**Memory attributed**`, and the blocking reason
- Rejected by user → same fields with `**Result**: rejected` and the user's stated reason

**Parallel stories**: run if no write-target overlap. First to finish merges first; second rebases. Conflict → pause, report.

---

## 10. CONTEXT MANAGEMENT

**Safe to `/clear` when ALL true:**
1. No background agent running
2. No agent result needed to proceed
3. Between stories

**What survives `/clear`**: git branches, worktrees, `epics.db`, plan files, all disk state.
**What is lost**: in-session memory, coder task status.

**Recovery**: query `epics.db` + `git worktree list` + `git branch --list 'dev/*'` (epic branches) + `git branch --list '*/*'` (story branches).

**Handoff**: Before suggesting `/clear`, write `~/.claude/session-handoff.md`:
- Stories in progress: current status, pending decisions, coder state
- What was being worked on and what the next action would be
- Any context the next session needs that isn't captured in epics.db
- Friction summary: count and categories of friction events this session, recurring patterns noted

Keep it under 10 lines. Overwrite any existing handoff file.

Additionally, store a session summary to OpenMemory (episodic sector) before `/clear`. This provides historical context beyond the ephemeral `session-handoff.md`.

**Clearing prompt**: "Context checkpoint reached [reason]. Run `/clear` to reset. All state is in `epics.db`."

Prompt `/clear` after: story merges, 3+ stories done in session, or user asks if safe.

---

## 11. HOTFIX AND QUICKFIX

**Hotfix**: single file, not protected, not testable, ≤30 lines changed, no schema/AI changes. Inline edit on temp branch, squash PR to main. Max 3/session. Log to `<project>/.claude/hotfix-log.md`.

**Quickfix**: 1-3 files, none protected. No schema/AI changes. Worktree + background quick-fixer (Haiku). Inline diff gate. Squash PR to main. Max 2/session. Log to `<project>/.claude/hotfix-log.md`.

Both paths skip `/todo` and `epics.db`. Rejected → `/todo` if protected/schema/too large.

---

## 12. RECOVERY

On session start (or after `/clear` with in-flight work):

```bash
sqlite3 ~/.claude/.claude/epics.db "SELECT id, title, state, branch FROM stories WHERE state NOT IN ('done','shipped') AND archived=0;"
git worktree list
git branch --list 'dev/*'         # epic dev branches
git branch --list '*/*'           # story branches (<epic-slug>/<story-slug>)
```

Stories in `in-progress` with an existing worktree → resume from coder step.
Stories in `in-progress` with no worktree → reset to `ready`, re-run `/draft-plan` if no plan file.

---

## 13. LOGGING

**Test failure log**: `<project>/.claude/test-failure-log.md`

Format per entry:
```
## [ISO date] — [story-id] — [title]
Coder: quick-fixer | architect   Model: haiku | sonnet | opus
Failing test(s): [names]
Error: [~300 chars]
Root cause: careless mistake | scope too narrow | prompt gap | framework misuse | test env issue
Resolution: re-delegated | escalated
```

**Review findings log**: `<project>/.claude/review-findings.md`

---

## 14. PROTECTED FILES

Read from `<project>/.claude/protected-files.md`. If missing, fall back to:
- `src/components/BoardCanvas.jsx`, `StickyNote.jsx`, `Frame.jsx`, `Shape.jsx`, `LineShape.jsx`, `Cursors.jsx`

Stories touching protected files require explicit user confirmation before launching coders.
Stories NOT touching protected files: include in coder prompt — "Do not edit any protected files."

---

## 15. SPECULATIVE EXECUTION

For architect stories where the best approach is genuinely unclear, the user may request speculative execution: two coders run in parallel with different approaches.

**Requirements:**
- User explicitly requests it ("try both approaches")
- Two separate plan files exist (e.g., `plans/story-NNN-approach-a.md`, `plans/story-NNN-approach-b.md`)
- Both run in separate worktrees from the same base branch

**Process:**
1. `/draft-plan` produces two plan files with different approaches
2. User approves both
3. `/run-stories` launches both in parallel worktrees
4. When both complete, Claude summarizes:
   - Lines changed, files touched, approach taken
   - Test results (if applicable)
   - Recommendation with reasoning
5. User picks one. The other worktree is cleaned up.

**Limits:**
- Max 1 speculative execution per session (token cost is 2x)
- Only for architect stories, never quick-fixer
- If one approach fails outright, the other wins by default

---

## 16. ONE-SHOT PIPELINE (`/ship`)

`/ship` collapses QUEUE→PLAN→DRAFT→RUN→MERGE into one invocation.
Calls `pm_ship` for epic/story creation, `pm_plan_stories` for Gemini planning, and `analyze` for plan validation.
Claude writes plan files and controls coder execution — Gemini never codes.

**Default for:** New projects, new isolated features, MVPs, prototypes — anything without existing production constraints.
**Fall back to full pipeline when:** Touching protected files, changing schemas/API contracts, or iterating on existing production code where §6 critique matters.

**Accepts:** inline feature lists, PRD files, existing plan files, epic IDs.

**What it skips:**
- Confirmation gates (auto-commits)
- Clarification questions — **except for new projects without a complete presearch doc**, which get one round of clarification + suggestions (step 1)
- Environment confirmation — **except** when plan files reference external services (Step 3b)

**Quality gates:**
- Environment preflight (Step 3b): detects external service dependencies, presents env var names checklist, human gate before coder launch
- Analyze (Step 2d): single-pass plan review + acceptance criteria per story. Use `--argue` for adversarial debate.
- Per-story testing (via run-stories): unit-tester writes tests from acceptance criteria, not implementation
- Integrated review (Step 5b): Sonnet reviews the full combined diff for cross-story issues
- Integration verify (Step 5c): build + tests + behavioral checks against acceptance criteria
- Skip analyze, integrated review, and integration verify with `--quick`. Per-story testing and environment preflight always run.

**Recovery:** `pm_ship` creates epic + stories in epics.db. Resume with `/ship epic-NNN`,
or fall back to `/draft-plan` + `/run-stories` for individual stories.

### New-project flow (sequential — order matters)

When Claude detects a new project (no `src/` directory, no `package.json`/`pubspec.yaml`/`setup.py`/`go.mod`/`Cargo.toml`, or user says "new project"):

1. **Clarify and suggest.** `/ship` normally skips clarification — new projects are the exception. Before creating anything:
   - Ask for tech stack if not obvious.
   - Surface implied requirements the user didn't state: "Your features imply a database — should Bootstrap include Postgres setup?" / "Auth needs a provider — Firebase Auth, Supabase, or roll your own?"
   - Suggest structural additions: "You'll probably want a shared layout component for dashboard and settings — should I add that to Bootstrap?"
   - Flag scope concerns: "Feature X is ambiguous enough that coders will guess differently — can you clarify what 'dashboard' means?"
   - Ask about environment requirements: "Will this project need API keys or external services (database, auth, payments)? List them so Bootstrap includes `.env.example`."
   - Ask about CI/CD: "Do you want a GitHub Actions workflow? (install, lint, test on push/PR)" — default is no.
   - Keep it to one round. Ask everything at once, not one question at a time. This is a lightweight gate, not a design review.

2. **`pm_ship`** creates epic + feature stories in DB (draft state, no planning yet).

3. **Create Bootstrap story** via `pm_create_story`. Set `agent: architect`.

4. **Claude writes the Bootstrap plan** (from tech stack knowledge — no Gemini needed). Bootstrap plan defines:
   - Project structure (directories, entry point, config files, .gitignore)
   - Core dependencies to install
   - Minimal running app (builds and starts)
   - Stub registration files for shared entry points (route config, nav menu, app shell with placeholder sections) — feature coders add to these rather than creating conflicting versions in separate worktrees
   - `ARCHITECTURE.md` documenting structure and tech decisions
   - `.env.example` with placeholder names for all known env vars, plus `.env` in `.gitignore`
   - If CI/CD requested: `.github/workflows/ci.yml` — install, lint, test on push and PR
   - Attach via `pm_update_story(plan_file=...)`. Bootstrap coder runs on **Opus**.

5. **`pm_plan_stories`** plans the feature stories. Pass the Bootstrap plan content as the `context` parameter so Gemini sees the intended project structure when assigning write_files, tasks, and dependencies.

6. **Set all feature stories to depend on Bootstrap.** Nothing runs until scaffolding exists.

7. **Claude writes feature plan files**, incorporating Gemini's task decomposition but referencing Bootstrap's planned structure for file paths. Sanity-check:
   - write_files consistent with Bootstrap's project structure
   - No two stories create the same file
   - All agents are `architect` (nothing to quick-fix in a new project)

8. **`/run-stories`** executes. Bootstrap runs first (Opus), feature stories run after (Sonnet).

**Feature plan files must include:** tech stack, project structure (from Bootstrap plan), and concrete verification ("run `npm start` and confirm X renders" — not "verify it works").

### Presearch document path (`/ship path/to/presearch.md`)

A comprehensive presearch document can skip the clarification step entirely and produce stronger results. Minimum required sections for skip-clarification:

- **Tech stack**: Explicitly stated (framework, language, database, auth provider)
- **Project structure**: Directory layout, key files, entry points
- **Features**: Scoped feature list (what to build, what's out of scope)
- **Data model**: Entities, relationships, key fields
- **Dependencies**: Third-party libraries, external APIs, services

If the presearch doc has all five, Claude skips step 1 (clarification) and uses the doc directly as:
- Bootstrap plan source (tech stack + structure sections → Bootstrap plan)
- Gemini context (`pm_plan_stories` gets the full doc as `context`)
- Feature plan reference (coders see the intended architecture)

If the doc is missing any of the five, Claude asks for the missing pieces in one round (step 1) before proceeding.

### CI/CD setup (opt-in)

When requested during new-project clarification, Bootstrap includes a GitHub Actions workflow. The Bootstrap coder writes `.github/workflows/ci.yml` with install + lint + test steps, using the correct language-specific setup action (`actions/setup-node`, `subosito/flutter-action`, etc.).

CI/CD is not added retroactively to existing projects via `/ship`. For existing projects, suggest as a `/todo` item.

### Definition of done

**Done means:** The merged result builds, starts, and demonstrates the requested features. Code existing in files is not done.

---

## 17. MEMORY

Two-layer memory: eager (flat files at session start) and lazy (OpenMemory on demand).

### Eager layer
CLAUDE.md, ORCHESTRATION.md, behavioral-prefs.md, session-handoff.md — loaded by SessionStart hook. These are constraints; every action must comply. No queries needed.

### Lazy layer (OpenMemory)
Tool/model learnings, project conventions, session summaries, decision shadows. Queried via MCP tools at specific integration points.

### When to query
- **Plan critique (§6):** Before writing plan file — query for learnings about the story's tech stack and file types. Scope: project + global.
- **Model selection (§2):** When assigning coder model — query for tool learnings. Scope: global.
- **Coder prompts (§8):** After pitfalls from pm_list_patterns — query for unformalized observations. Scope: project.
- **Session start:** After interpreting SESSION AGENDA, one query if stories reference specific tech. Not per-story.

### When to store
- **After merge (§9 step 5.5):** Episodic session outcome. Scope: project.
- **After coder failure/escalation:** Procedural tool learning. Scope: global.
- **After pm_add_decision:** Shadow the decision for semantic search. Scope: project.
- **Before /clear:** Episodic session summary. Include: stories completed, skills invoked (from skill-telemetry.jsonl), friction events and patterns, memories that influenced decisions. Scope: project.
- **After key prompt logging:** Procedural prompt pattern. Scope: global.
- **When discovering a convention** during plan critique: Semantic. Scope: project.
- **After friction event (automatic):** Store to OpenMemory if pattern promotion threshold met (3+ recurrences of the same category for the same root cause). Scope: project for story-specific, global for model/tool learnings.

### Store failures
If openmemory_store fails, append the entry to `~/.claude/memory-queue.md` instead.
Do not drop the observation. The queue drains automatically (see below).

### Queue drain (session start)
After the OpenMemory health check passes, check if `memory-queue.md` has entries.
If so, store each entry to OpenMemory and remove it from the queue on success.

### Reinforcement
When a memory from OpenMemory directly influences a successful outcome — plan critique
catches an issue, model selection avoids a known failure, a convention prevents a bug —
call openmemory_reinforce on that memory. This is a judgment call, not an automatic trigger.
Do not reinforce speculatively.

### Graceful degradation
Reads: skip silently, proceed with eager-layer context only.
Writes: queue to memory-queue.md, never drop.
Health check at session start warns when Ollama is unreachable.

### Subagent access
Coder agents in worktrees do NOT query OpenMemory directly. The main session pre-fetches
relevant learnings during coder prompt construction (§8) and injects them as text.
This avoids MCP availability concerns in subagent environments.

### Tag taxonomy (use consistently — inconsistent tags fragment queries)
| Tag | Meaning |
|---|---|
| `tool-learning` | Model/tool capability observation |
| `convention` | Project convention or pattern |
| `decision` | Architectural decision shadow |
| `session-summary` | Session episodic recap |
| `prompt-pattern` | Effective prompt approach |
| `bootstrap` | Initial seed data (set once, never again) |

### Scoping
- Global (tool capabilities, prompt patterns): `user_id="global"`
- Per-project (conventions, decisions, sessions): `user_id="proj:<project-basename>"`

---

## 18. FRICTION TRACKING

Friction events are course corrections — when the workflow deviates from the expected path.
They are the primary signal for measuring skill effectiveness and identifying improvement
opportunities.

### Two types

**Automatic** — logged at existing workflow trigger points, every time:
- Escalation (§9): model upgrade because current model couldn't handle the task
- Restart (§9): plan rewrite because the plan was wrong
- BLOCKED (§9): coder couldn't complete the story
- NEED_DECISION (§8): coder hit an ambiguity the plan didn't resolve
- Merge conflict (merge-worktree Step 3): execution ordering was wrong
- Test failure → retry (run-stories Step 5b): code didn't pass tests

**Judgment** — logged when Claude recognizes a significant course correction not captured
by automatic events. Must include a counterfactual ("without this correction, X would have
happened"). The bar: "this changed what happens next in a material way." Not: minor retries,
normal iteration, expected backtracking.

### Friction event format

Append to `~/.claude/friction-log.md`:

```
## [date] — [category] — [story-id or "session"]
**Type**: automatic | judgment
**Skill**: which skill was running (or "manual" / "main-session")
**Expected**: what should have happened
**Actual**: what did happen
**Counterfactual**: what would have happened without this correction
**Recurrence**: first-seen | recurring (ref prior entries)
```

### Categories

| Category | Meaning |
|---|---|
| `escalation` | Model upgrade |
| `restart` | Plan rewrite |
| `blocked` | Story couldn't complete |
| `decision` | Coder needed human/Claude decision |
| `conflict` | Merge conflict |
| `retry` | Test failure → sent back |
| `reroute` | Changed approach mid-execution (judgment) |
| `discovery` | Assumption proven wrong (judgment) |

### Pattern promotion

When the same friction category recurs 3+ times for the same root cause:
1. Store as a tool-learning in OpenMemory (procedural sector, scoped appropriately)
2. Append to `tool-learnings.md`
3. This feeds model selection (§2), plan critique (§6), and coder prompts (§8)
4. If the pattern suggests a skill is needed, note it. If the pattern occurs inside
   an existing skill, the skill may need redesign — not just a retry.

### Memory integration

- Friction events stored to OpenMemory (episodic, project scope) at session end or
  when pattern promotion triggers
- Query friction history during plan critique (§6) to avoid known pitfalls
- The /skill-health dashboard reads friction-log.md for trend analysis

### Skill changelog

When a skill is created, significantly modified, or retired, append to `~/.claude/skill-changelog.md`:
`- [date] [action] /[skill-name] — [description]`. The /skill-health dashboard uses these
dates to draw before/after lines in friction trends. Skip trivial changes (typo fixes, comment edits).

### Response protocol

When the /skill-health dashboard flags a high-friction skill (>40% friction rate, or a new
friction category appearing after a skill modification per skill-changelog.md):

1. Verify the recurring pattern is promoted to tool-learning (OpenMemory) if threshold met
2. Surface to user with specific data: "X events of type Y in Z sessions since [date]"
3. Suggest a concrete response: modify skill, split the workflow, add a new skill, or
   accept the friction as inherent to the task
4. If user approves a change → create a `/todo` item targeting the skill

This keeps the human in the loop for design decisions while ensuring the signal doesn't
get lost. Pattern promotion means even without immediate action, future plan critiques
will surface the friction when someone touches that skill.

### What friction measurement answers

- "Did skill X eliminate the friction pattern it was designed for?" →
  compare friction rate before and after skill introduction (dates from skill-changelog.md)
- "Is skill X creating new friction?" →
  check for new categories appearing inside skill X's execution after its changelog date
- "Which stories had clean execution?" →
  friction count = 0 in the outcome entry
- "What's our overall friction trend?" →
  events per session over time, by category
- "What's the efficiency impact of friction?" →
  compare avg cycle time + coder effort for 0-friction vs. 2+-friction outcomes
