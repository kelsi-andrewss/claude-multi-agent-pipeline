# Claude Multi-Agent Development Pipeline

A structured multi-agent workflow for software development using Claude Code. Epics group related stories, each story gets an isolated worktree branched off the epic feature branch, and specialized agents handle each pipeline stage. In-session tracking uses Claude's built-in `TaskCreate`/`TaskList`/`TaskUpdate` tools; cross-session recovery relies on `epics.json` + git state.

---

## Overview

```
User Request
     |
     v
+--------------+
| Orchestrator |  <-- classify, plan, group todos
|   (Haiku)    |
+------+-------+
       | staging payload
       v
+--------------+
| Main Session |  <-- validate, create TaskCreate entries, trigger run
+------+-------+
       | run trigger
       v
+--------------------------------------+
|           Epic Feature Branch        |
|         epic/<epic-slug>             |
|                                      |
|  +----------+    +----------+        |
|  | Story A  |    | Story B  |  ...   |
|  | worktree |    | worktree |        |
|  +----+-----+    +----+-----+        |
|       | merge          | merge       |
|       +--------+-------+            |
|                v                     |
|        epic branch HEAD              |
+------------------+-------------------+
                   | epic PR (when ready)
                   v
                 main
```

---

## Hierarchy

| Level | Unit | Persistence |
|-------|------|-------------|
| **Epic** | Broad theme (e.g. "UI Polish") | `.claude/epics.json` (on disk) |
| **Story** | Scoped deliverable, owns a branch + worktree | `.claude/epics.json` (on disk) |
| **Todo** | Atomic task under a story | `TaskCreate`/`TaskList` (in-session only) |

Todos are **session-scoped** -- tracked via Claude's built-in task tools during the session, not persisted to disk. Cross-session recovery uses `epics.json` + git worktree/branch state.

---

## Agent Roster

| Agent | Model | Role |
|-------|-------|------|
| `todo-orchestrator` | Haiku (default) | Research, classify, group todos -> staging payload. Never writes code. |
| `epic-planner` | Sonnet/Opus | Two modes: (1) epic mode -- background multi-story planning; (2) planning mode -- foreground interactive research for ambiguous tasks |
| `quick-fixer` | Haiku/Sonnet | Clear-scope fixes, style tweaks, mechanical changes |
| `architect` | Sonnet/Opus | Ambiguous scope, schema changes, new patterns |
| `reviewer` | Haiku | On-demand code review of diffs |
| `unit-tester` | Haiku | Discover relevant tests, run them, assert coverage, lint, build |
| `git-ops` | Haiku | Background-only: runs pipeline scripts and git commands. Never reads or edits source files. |

### Model Selection

```
orchestrator  -> Haiku  (bump to Sonnet/Opus if architecturally complex)
epic-planner  -> Sonnet (default) | Opus (high complexity, AI/schema, >10 files)
quick-fixer   -> Haiku (trivial) | Sonnet (standard) | Opus (escalation)
architect     -> Sonnet (standard) | Opus (high-risk, escalation)
reviewer      -> Haiku  (Sonnet only if coder was Opus)
unit-tester   -> Haiku  always
git-ops       -> Haiku  always (never escalated)
```

---

## Epic Feature Branch Lifecycle

```
main
 |
 +--- epic/ui-polish  ------------------------------------------+
 |         |                                                     |
 |         +-- story/ghost-placement  (worktree)                |
 |         |      +-- [coder] -> [diff gate] -> merge -->       |
 |         |                                                     |
 |         +-- story/zoom-controls  (worktree)                  |
 |         |      +-- [coder] -> [diff gate] -> merge -->       |
 |         |                                                     |
 |         +-- story/text-readability  (worktree)               |
 |                +-- [coder] -> [diff gate] -> merge -->       |
 |                                                               |
 |         [epic PR created after first story merges]           |
 |         [epic PR updated as each story merges]               |
 |                                                               |
 +-- <-- squash merge when user says "merge epic" -------------+
```

### Key Rules

- **Epic branch** -- `epic/<slug>`, created off `origin/main` when first story runs
- **Epic branch is deleted after squash merge** -- `merge-epic.sh` passes `--delete-branch` to `gh pr merge --squash`; the remote ref is deleted immediately. Local ref is also deleted. Epic branches do not persist after merge to main.
- **Story branches** -- `story/<slug>`, created off the epic branch (not main)
- **Stories merge without PRs** -- directly into the epic branch via fast-forward or merge commit
- **Epic PR** -- created after the first story merges (so the PR has content); updated as more stories land
- **Cross-epic sync** -- before creating a story worktree, `setup-story.sh` rebases the epic branch onto `origin/main` only if the epic has diverged (i.e. `origin/main` has commits not yet in the epic). If the epic already contains all of main, the rebase is skipped to avoid spurious conflicts.

---

## Story Pipeline

```
filling --> running --> [testing] --> merging --> closed
               |            |
               |       (FAIL: back to running)
               |
               +--> reviewing (on-demand only)
                        |
                   (PASS: merging)
                   (BLOCK: back to running)
```

### State Transitions

| From | To | Trigger |
|------|----|---------|
| `filling` | `running` | User says "run story-X" |
| `running` | `merging` | All coder tasks done (default -- no tests) |
| `running` | `testing` | All coders done + `needsTesting: true` |
| `testing` | `merging` | Unit-tester PASS |
| `testing` | `running` | Unit-tester FAIL -> back to coder |
| `running` | `reviewing` | User requests or `needsReview: true` |
| `reviewing` | `merging` | Reviewer PASS |
| `reviewing` | `running` | Reviewer BLOCKING -> back to coder |
| `merging` | `closed` | Merged into epic branch |
| `any` | `blocked` | 2 reviewer retries still blocking (Opus escalation) |

---

## Full Story Run Flow

```
User: "run story-X"
       |
       v
1. Read story from epics.json, create TaskCreate entries for todos
       |
       v
2. Create/update epic branch
   +-- No branch yet -> create epic/<slug> from origin/main, push
   +-- Branch exists -> fetch + rebase onto origin/main
       |
       v
3. Create story worktree from epic branch
   git worktree add .claude/worktrees/story/<slug> -b story/<slug> epic/<epic-slug>
   ln -sf <root>/.env + node_modules
       |
       v
4. Launch coder tasks (background, parallel where possible)
   Track progress via TaskUpdate
       |
       v
5. Check in every 3 minutes (TaskOutput block: false)
   Stalled after 6 min (2 missed check-ins) -> stop + re-split
       |
       v
6. Wait for all coder tasks -> done
       |
       v
7. MANDATORY DIFF GATE (inline, ~5 seconds)
   git -C <worktree> rebase epic/<epic-slug>
   git -C <worktree> diff epic/<epic-slug>..HEAD --name-only
   -> restore any out-of-scope files, commit, verify
       |
       v
8. Testing? (needsTesting or write-targets include utils/hooks/testable files)
   +-- YES -> pass writeFiles list to unit-tester (background)
   |         +-- PASS -> proceed
   |         +-- FAIL (with root-cause diagnosis) -> fix inline or back to coder
   +-- NO  -> skip
       |
       v
9. Review? (user requested or needsReview: true)
   +-- YES -> launch reviewer (background)
   |         +-- PASS -> proceed
   |         +-- BLOCK -> back to coder (max 2 retries)
   +-- NO  -> skip
       |
       v
10. Merge into epic branch (via merge-queue.sh)
    One git-ops agent runs diff-gate + merge sequentially for all ready stories
    -- Stories for same epic: one merge-queue.sh agent (sequential)
    -- Stories for different epics: separate parallel agents (safe)
    merge-queue.sh manifest per story: { storyBranch, storyTitle, epicSlug, epicTitle, prNumber, writeFiles }
    Each story: diff-gate -> rebase -> git checkout epic/<slug> -> merge --ff-only -> push -> cleanup
       |
       v
11. Write epics.json snapshot (story -> closed)
       |
       v
12. Create/update epic PR
    +-- First story -> gh pr create --base main --head epic/<slug>
    +-- Subsequent -> gh pr edit <prNumber> --body (append story)
       |
       v
13. Check architectural findings -> append novel ones to CLAUDE.md
       |
       v
14. Story -> closed. Check epic auto-close. /clear
```

---

## In-Session Tracking

Todos are tracked via Claude's built-in task tools during the session:

```
TaskCreate  -> register a new todo (from orchestrator staging payload)
TaskUpdate  -> mark in_progress, completed, or blocked
TaskList    -> see all todos and their status
TaskOutput  -> check on background agents (block: false for non-blocking)
```

No JSON tracking files are written on every state change. `epics.json` is the sole persistent file, written only on story merge and state transitions.

---

## Cross-Session Recovery

When a session ends (crash or normal exit), the next session reconstructs state from three sources:

```
1. epics.json on disk
   -> Which stories are closed, running, or filling

2. git worktree list
   -> Which story worktrees still exist (in-flight work)

3. git branch --list 'story/*' 'epic/*'
   -> Which branches are active
```

**Recovery flow:**
- If `epics.json` shows a story in `running` state:
  1. Check if the story worktree still exists
  2. Check for uncommitted changes
  3. Report to user: "Story X was in-flight. Resume or discard?"
  4. Do not auto-resume -- wait for user decision

**What's lost on crash:** in-session todo progress and coder task status. Git state (branches, worktrees, commits) is the ground truth for anything in-flight.

---

## Coder Grouping

The orchestrator assigns todos to parallel or sequential groups:

```
For each todo in the story:

1. agent == "architect"
   +-- solo group, always (architect never shares a group)

2. agent == "quick-fixer", no overlap with architect
   +-- eligible for parallel grouping with other quick-fixers

3. agent == "quick-fixer", overlaps an architect todo
   +-- dependsOn that architect group

4. Two quick-fixers share a write-target file
   +-- Different sections -> same group
   +-- Same section -> separate groups, second dependsOn first

5. todo A has blockedBy: todo B (same story)
   +-- A's group gets dependsOn = B's group
```

### Task Size Ceiling

If a coder group's write-targets span **>5 files** or the estimated change is **>200 lines**, split into 2+ atomic sub-tasks. Two 5-minute tasks are faster and more recoverable than one 15-minute task. Each sub-task gets its own `TaskCreate` entry.

### Example: UI Polish Epic (4 stories, 2 parallel groups)

```
Group A (sequential -- share stageHandlers.js):
  Story 1: ghost placement fix  ->  Story 2: zoom controls

Group B (sequential -- share CSS files):
  Story 3: text readability  ->  Story 4: M3 contrast

Groups A and B run in parallel (no file overlap).
```

---

## Simplified epics.json Schema

### Epic entry
```json
{
  "id": "epic-001",
  "title": "UI Polish",
  "branch": "epic/ui-polish",
  "prNumber": 42,
  "persistent": true
}
```

### Story entry
```json
{
  "id": "story-001",
  "epicId": "epic-001",
  "title": "Ghost placement accuracy",
  "state": "closed",
  "branch": "story/ghost-placement",
  "writeFiles": ["src/handlers/stageHandlers.js"],
  "needsTesting": false,
  "needsReview": false
}
```

Dropped from previous schema: `body`, `labels`, `worktree` (derivable from branch), `todos` (in TaskList), `coderGroups` (in TaskList), `reviewerRetries` (in-session only), `startedAt`, `stageStartedAt` (in-session only).

---

## Protected Files

### Tier 1 -- Protected Konva Files (rendering layer)
Agents cannot edit without explicit user permission granted in the current session.

```
src/components/BoardCanvas.jsx
src/components/StickyNote.jsx
src/components/Frame.jsx
src/components/Shape.jsx
src/components/LineShape.jsx
src/components/Cursors.jsx
```

**To unlock:** Say "I grant permission to edit [filename] for this story." The main session notes it in the coder prompt verbatim.

### Tier 2 -- Protected Testable Files (have test coverage)
Editing any of these auto-enables `needsTesting: true`. Requires user approval.

```
src/hooks/useBoard.js          src/handlers/objectHandlers.js
src/hooks/useBoardsList.js     src/handlers/stageHandlers.js
src/hooks/useRouting.js        src/handlers/transformHandlers.js
src/utils/frameUtils.js        src/components/BoardAccessDenied.jsx
src/utils/connectorUtils.js    src/components/GroupPage.jsx
src/utils/colorUtils.js        src/components/GroupSettings.jsx
src/utils/slugUtils.js         src/components/GroupCard.jsx
src/utils/tooltipUtils.js      src/components/BoardSelector.jsx
                               src/components/BoardSettings.jsx
```

---

## Diff Gate (Mandatory)

Runs inline after all coder tasks complete -- before tester, reviewer, or merge:

```bash
git -C <worktree> fetch origin
git -C <worktree> rebase epic/<epic-slug>
git -C <worktree> diff epic/<epic-slug>..HEAD --name-only
# Compare against story writeFiles list
# Restore any out-of-scope file:
git -C <worktree> checkout epic/<epic-slug> -- <extra-file>
# If files restored: commit "fix: restore out-of-scope files to epic branch state"
# Re-run diff and verify matches writeFiles exactly
```

---

## Git Merge Strategy

### The Problem: Concurrent Merge Agents Cause Git Checkout Races

`merge-story.sh` checks out the epic branch on the **main worktree**:

```bash
git -C "$REPO_ROOT" checkout "${EPIC_BRANCH}"
git -C "$REPO_ROOT" merge --ff-only "${STORY_BRANCH}"
```

Launching multiple merge agents simultaneously means multiple agents run `git checkout epic/...` on the same working directory -- they race, producing checkout conflicts and worktree cleanup failures.

### The Solution: merge-queue.sh

Instead of one agent per story, launch **one git-ops agent** with a JSON manifest of all stories to merge. The script processes them sequentially:

```
merge-queue.sh manifest:
[
  { storyBranch, storyTitle, epicSlug, epicTitle, prNumber, writeFiles },
  { storyBranch, storyTitle, epicSlug, epicTitle, prNumber, writeFiles },
  ...
]
```

For each story in order:
1. Run `diff-gate.sh` (rebase + scope check + restore out-of-scope files)
2. Run `merge-story.sh` (merge into epic branch + update epic PR)
3. Print `MERGED:<storyBranch>:PR_NUMBER=<n>` for the main session to update epics.json

The PR number is threaded through automatically -- if the first story creates the epic PR, subsequent stories in the same manifest get that number applied.

### Parallelism Rules

```
Stories targeting SAME epic branch:
  -> One merge-queue.sh agent (sequential within agent)
  -> Never two agents on same epic branch simultaneously

Stories targeting DIFFERENT epic branches:
  -> Separate merge-queue.sh agents (parallel is safe)
  -> Epic branches are independent git refs
```

### Why Not Just Serial Individual Agents?

A single background agent handles N stories sequentially with ~constant overhead -- one agent spinup, no context switching. Chaining N separate agents would require the main session to wait for each, read the result, then launch the next: O(N) round-trips through the main context. merge-queue.sh does it in O(1) round-trips.

### git-ops Agent

All git pipeline work is delegated to the `git-ops` subagent (`subagent_type: "git-ops"`). It is always launched with `run_in_background: true` and executes exactly the script(s) specified in the prompt — nothing more.

**Permitted:** Bash (git commands, the six pipeline scripts below, direct `epics.json` writes via node/python/jq when `update-epics.sh` is unavailable).

**Forbidden:** reading or editing source files, architectural decisions, running builds or tests, committing or pushing without explicit instruction, force-deleting branches (`-D`).

### Script Reference

| Script | Purpose |
|--------|---------|
| `setup-story.sh` | Epic branch setup + story worktree creation |
| `diff-gate.sh` | Post-coder fetch, rebase, scope check, out-of-scope file restoration |
| `merge-story.sh` | Single story -> epic branch merge + PR create/update + worktree cleanup |
| `merge-queue.sh` | **Preferred** -- sequential diff-gate + merge for a list of stories |
| `merge-epic.sh` | Epic -> main squash merge via PR |
| `update-epics.sh` | Read/write epics.json for state transitions and field updates |

---

## Unit-Tester: How It Works

The unit-tester is the most strictly defined agent in the pipeline. Its workflow is ordered and non-negotiable.

### Step 1 — Discover Relevant Tests

The main session passes the story's `writeFiles` list when launching the unit-tester. The agent uses Vitest's `--related` flag to find all test files that import or are imported by the changed source files:

```bash
npx vitest related --run <writeFile-1> <writeFile-2> ...
```

This scopes the run to tests that actually exercise the changed code — not the entire test suite. If `--related` finds no tests, the agent notes "no existing tests cover these files" and proceeds directly to writing new ones.

### Step 2 — Run Only the Relevant Tests

```bash
npx vitest run <discovered-test-file-1> <discovered-test-file-2> ...
```

### Step 3 — Coverage Attestation (mandatory output)

After the run, the agent emits a coverage attestation:

```
Coverage attestation:
  src/utils/frameUtils.js: covered by frameUtils.test.js — tests: expandAncestors, findOpenSpot
  src/handlers/stageHandlers.js: NO COVERAGE — no existing test exercises this file
```

Any `NO COVERAGE` entry on a write-target triggers new test writing.

### Step 4 — Write New Tests

New tests are written when any of the following is true:
- A write-target has `NO COVERAGE` (mandatory)
- The story is a feature (not just a fix)
- The changed code path has no test that would have caught the original bug

### Step 5 — Lint

```bash
npm run lint
```

Lint errors → FAIL (blocks merge). Lint warnings → log-only (surface in summary after merge, do not block).

### Step 6 — Build

```bash
npm run build
```

Must pass before reporting PASS.

### Failure Classification (non-trivial failures)

The agent must classify every non-trivial failure before re-delegating to the coder. The coder receives a diagnosis, not a raw failure dump:

```
Root cause: <exactly one category>
  - Careless mistake (wrong variable, off-by-one, typo)
  - Scope too narrow (coder didn't read enough context)
  - Prompt gap (plan was missing a critical detail)
  - Framework/API misuse (wrong Konva/Firebase/React/Vitest API)
  - Test environment issue (mock gap, timing, missing setup)

Analysis: <2-3 sentences on what went wrong and why>
Failing test: <test name and file>
Error: <exact error message, truncated to ~300 chars>
```

The main session rejects any tester output that is missing classification — the agent is sent back to fill it out before re-delegation proceeds.

### Konva Component Smoke Tests

For stories with explicit permission to touch protected Konva components, the tester writes at minimum a smoke test: render with minimal props, assert it does not throw. `react-konva` and `konva` are mocked at the module boundary. No canvas pixel assertions.

---

## On-Demand Testing and Review

### Unit-tester triggers (auto)
| Condition | Result |
|-----------|--------|
| Write-targets include `src/utils/`, `src/hooks/` | `needsTesting: true` |
| Write-targets include any file with `.test.*` counterpart | `needsTesting: true` |
| Story touches permission/admin/Firestore/AI paths | `needsTesting: true` |
| User says "test this story" | `needsTesting: true` |

### Reviewer triggers (on-demand only)
| Condition | Result |
|-----------|--------|
| User says "review this story" | Launch reviewer |
| Story flagged `needsReview: true` | Launch reviewer |
| Story touches frame system, Firestore schema, AI tools | Orchestrator flags `needsReview: true` |

### Diff-only review mode
If the story diff is <=75 lines, the reviewer reads the diff only -- no full files opened. Saves ~80% of reviewer tokens for small stories.

---

## Orchestrator Output Format

The orchestrator returns one of four output types:

### STAGING_PAYLOAD (normal path)

```
SUMMARY
Todo: <one-line description>
Story: <storyId> -- <story title> [NEW if creating]
Epic: <epicId> -- <epic title> [NEW if creating]
Agent: <quick-fixer|architect>
Model: <haiku|sonnet|opus>
Trivial: <yes|no>
Files:
  write: <comma-separated files the coder will modify>
  read: <comma-separated files needed for context only>
Plan: <one sentence describing what the coder will do>
Coder groups: <grouping decision>

STAGING_PAYLOAD
{ "storyUpdate": {...}, "epicUpdate": {...} }
```

The main session creates `TaskCreate` entries from the orchestrator's plan -- not JSON file writes.

### NEEDS_PLANNING (ambiguous tasks)

When a task is too ambiguous for a single clarifying question (2+ open questions, scope unclear, >5 files explored without converging):

```
NEEDS_PLANNING
Todo: <one-line description>
Complexity: <low|medium|high>
Touches: <comma-separated areas>
Files explored: <comma-separated files already read>

Questions:
- <specific, actionable question>
- <specific, actionable question>

Suggestions:
- <approach the orchestrator leans toward, if any>
```

This triggers the **planning loop**:

```
todo-orchestrator returns NEEDS_PLANNING
       |
       v
Main session: group bullets, select model, derive slug
       |
       v
epic-planner (foreground, planning mode)
  |-- asks user questions interactively
  |-- writes $TMPDIR/planning-<slug>.md
       |
       v
todo-orchestrator (re-launch with PLANNING_CONTEXT)
       |
       +-- STAGING_PAYLOAD -> validate, present, approve
       +-- NEEDS_PLANNING again -> surface to user, stop (max 1 loop)
       +-- UNRESOLVABLE -> surface reason, stop
```

### DUPLICATE

```
DUPLICATE: <story-id>
```

### UNRESOLVABLE

```
UNRESOLVABLE
Todo: <one-line description>
Reason: <why this cannot be staged>
```

---

## Agent Check-In and Stall Detection

```
Every 3 minutes:
  TaskOutput(agent_id, block: false)
       |
       +-- Agent making progress -> continue
       +-- No new tool uses after 2 consecutive checks (6 min)
              |
              v
           Stop agent
           Re-split task into smaller pieces (<=5 files, <=200 lines each)
           Re-launch sub-tasks
```

---

## Ephemeral Plans

Plans are working documents, not records:
- Write to `$TMPDIR/plan-<story-id>.md`
- Do not persist in `~/.claude/plans/`
- Architecture decisions that survive sessions go in `CLAUDE.md`

---

## Context Clearing Rules

Clear (`/clear`) at these mandatory checkpoints:

1. **After a story merges** -- before auto-launching any queued story
2. **After reviewer + unit-tester both launch** -- they wake the session when done
3. **After any background agent completes with no immediate follow-up**

Never clear if a background agent is running and its result is needed to proceed.

---

## Token & Time Optimizations

| Optimization | Savings |
|---|---|
| **In-session TaskList** -- no JSON writes per state change | Eliminates ~15 file writes/story |
| **Epic-planned stories** -- skip orchestrator when epic plan specifies writeFiles/agent/model | ~2000 tokens/story |
| **CSS-only stories** -- always Haiku, skip testing, skip diff gate restoration | ~60% cost reduction |
| **Coder prompt compression** -- cap at 2000 tokens; link CLAUDE.md by section name | ~30-40% token reduction |
| **`vitest --related`** -- run only tests that exercise changed files | Eliminates full-suite noise |
| **Diff-only review** -- <=75 line diffs reviewed from diff alone | ~80% reviewer token reduction |
| **Parallel orchestrators** -- multiple orchestrators can run simultaneously (read-only) | Wall-time reduction |
| **Batch merge window** -- 10-second window to batch same-epic story merges | Fewer rebase cycles |
| **3-min check-in + 6-min stall detection** -- catch stuck agents early | Prevents wasted compute |
| **Task size ceiling** -- split >5 files or >200 lines into sub-tasks | Faster recovery from failures |

---

## Escalation

If reviewer retries reach 2 and the coder is still producing blocking findings:

```
reviewer retries == 2
       |
       v
Escalate coder to Opus (one more attempt)
       |
       +-- PASS -> proceed to merge
       +-- Still BLOCKING -> story.state = "blocked"
                            Report findings to user
                            Leave worktree intact
                            Wait for user intervention
```

---

## Test Failure Log

When the unit-tester reports a non-trivial failure, the main session appends to `.claude/test-failure-log.md` before re-delegating. The tester is responsible for filling in root cause and analysis; the main session copies these verbatim.

```
## [ISO date] — [story id] — [one-line failure title]
Coder agent: quick-fixer | architect
Model: haiku | sonnet | opus
Failing test(s): [test name(s) or file(s)]
Error: [exact error message, truncated to ~300 chars]
Root cause (exactly one, pre-filled by unit-tester):
  - [ ] Careless mistake
  - [ ] Scope too narrow
  - [ ] Prompt gap
  - [ ] Framework/API misuse
  - [ ] Test environment issue
Analysis: [2-3 sentences from unit-tester]
Coverage gap: yes (no test existed) | no (existing test should have caught this)
Resolution: re-delegated to coder | escalated to user
```

If the unit-tester output omits classification, the main session rejects it and sends the agent back to classify before re-delegating.

Once the log reaches 5 entries, the main session surfaces: "test-failure-log.md has N entries — worth reviewing to improve coder prompts."

---

## Architectural Findings -> CLAUDE.md

After each story merge, scan coder output + reviewer warnings + test failure log for novel findings:

- Check if already in CLAUDE.md (Grep for key terms)
- If novel: silently append to appropriate section (Common Gotchas, Architecture Rules, Key Conventions)
- Format: one bullet, concise, actionable
- Triggers: unexpected API behavior, reviewer pattern flag, "framework/API misuse" test failure, new invariant discovered

---

## Integration Surface Reconciliation

When parallel stories share a "registry" surface (command palette, context menu, keyboard shortcuts, settings panel, etc.), the epic-planner automatically detects and generates an integration story.

### How it works

1. **Declare surfaces in project CLAUDE.md** -- when a feature ships that exposes a registry or hook API, add an entry to the `## Integration surfaces` section of the project's CLAUDE.md:

```
## Integration surfaces
- **Command palette** -- `src/components/CommandPalette.jsx` + `src/hooks/useCommandRegistry.js`
  Registration: call `registerCommand({ id, label, action })` from the feature's hook or component.
```

2. **Epic-planner detects gaps** -- after drafting all feature stories, the planner checks each pair against declared surfaces. For story B adding a user-facing feature that should appear in a surface story A introduced/modified:

```
Confident YES (story explicitly mentions registering) -> generate integration story automatically
Confident NO  (infrastructure-only: CSS, rules, config) -> skip, no question asked
Uncertain     (new user-facing feature, unclear intent) -> ask developer via AskUserQuestion
```

3. **Integration story generated automatically**:

```
Title: Wire <feature> into <surface-name>
Agent: quick-fixer
Model: haiku
Files:
  write: <surface owner file(s)>
  read: <feature file(s)>
dependsOn: [story-A-id, story-B-id]   <- runs after both parallel features merge
```

4. **Main session surfaces them in the approval summary**:
   > "Integration stories generated: Wire following into command palette. These wire parallel features together and will run after their dependencies merge."

### Why this matters

Without this step, parallel features built in separate worktrees silently miss each other. Feature A (command palette) merges first. Feature B (following) merges second. "Follow user" never appears in the palette because neither story's coder knew the other existed. The integration story closes the gap automatically.

---

## File Structure

```
~/.claude/
+-- CLAUDE.md              # Global preferences (communication, code style, React, Firebase)
+-- ORCHESTRATION.md       # This pipeline (main session only)
+-- agents/
|   +-- quick-fixer.md
|   +-- architect.md
|   +-- reviewer.md
|   +-- unit-tester.md
|   +-- todo-orchestrator.md
|   +-- epic-planner.md    # Dual-mode: epic planning (background) + task planning (foreground)
|   +-- git-ops.md         # Git pipeline executor: scripts, rules, forbidden actions
+-- tracking/
    +-- key-prompts/       # High-signal prompt logs (YYYY-MM-DD.md)

<project>/.claude/
+-- epics.json             # Epic + story state (sole persistent tracking file)
+-- settings.local.json    # File deny rules (protected files)
+-- tracking/
|   +-- key-prompts/
|   +-- test-failure-log.md
|   +-- review-findings.md
+-- worktrees/             # Active story worktrees (cleaned up after merge)
```

---

## Guides

Reference documents on specific pipeline topics, available as PDFs in the `guides/` directory:

| Guide | Description |
|-------|-------------|
| [Improved Session Persistence for Multi-Agent Pipeline](guides/Improved-Session-Persistence-for-Multi-Agent-Pipeline.pdf) | 3-layer defense (CLAUDE.md directive, /todo skill, PreToolUse hook) for enforcing pipeline usage |
| [Orchestrator Context Management in Claude Code](guides/Orchestrator-Context-Management-in-Claude-Code.pdf) | Why context bloat happens and three solutions: sub-agent delegation, deterministic /clear checkpoints, PostToolUse hooks |

---

## Quick Reference

```
New feature request (clear scope)
  +-- todo-orchestrator -> STAGING_PAYLOAD -> user approval
      -> TaskCreate entries -> fill phase

New feature request (ambiguous)
  +-- todo-orchestrator -> NEEDS_PLANNING
      -> epic-planner (foreground, interactive) -> resolved plan
      -> todo-orchestrator (re-run with PLANNING_CONTEXT) -> STAGING_PAYLOAD

"run story-X"
  +-- epic branch created/updated -> story worktree created
      -> coder tasks launched (3-min check-ins)

Coder done
  +-- diff gate -> [unit-tester (vitest --related)] -> [reviewer]
      -> merge-queue.sh (one agent, sequential per epic branch)
      -> epics.json snapshot -> epic PR updated

"merge epic X"
  +-- epic branch rebases main -> gh pr merge --squash
      -> main updated (epic branch deleted)

Session crash recovery
  +-- epics.json + git worktree list + git branch --list
      -> detect in-flight stories -> ask user: resume or discard?
```
