# Main Session Orchestration Rules

These rules apply to the main Claude Code session only. Spawned agents (coders, reviewers, testers) do not load this file.

---

## 1. ENFORCEMENT

**ZERO-SKIP RULE**: Every code change — no matter how small — that touches >1 file or any protected file MUST go through: story in epics.json → worktree → coder (background) → merge. No exceptions. No "it's just a small fix." If you find yourself thinking "this is too small for the pipeline," that is the exact moment you must use the pipeline.

**Corollary — no plan-to-coder shortcut**: When an approved plan exists, the sequence is still: create/find story → create worktree → launch coder into worktree (background). An approved plan does NOT authorize skipping the story/worktree steps. The plan tells the coder WHAT to do; the pipeline tells it WHERE to do it.

**Corollary — "Implement the following plan:" is not a bypass**: When a user message begins with "Implement the following plan:" and the plan involves modifying project files, treat it as a run trigger — not a direct execution instruction. The pipeline still applies: find/create story → create worktree → launch coder (background). Only plans that involve zero project file changes (e.g. documentation research, git ops, answering questions, editing `~/.claude/` files) may be executed inline.

**Corollary — read config before answering**: Before answering any workflow question — including hypotheticals — OR before acting on any code-changing prompt, read ORCHESTRATION.md and project CLAUDE.md first. Never answer from general knowledge when user-specific rules exist.

**Corollary — epics.json is git-ops-only**: The main session MUST NEVER write `epics.json` directly (no Edit, Write, or inline Bash writes). All `epics.json` mutations — new story/epic staging, state transitions (`filling`→`running`, `running`→`closed`), branch assignment, prNumber recording — must be delegated to a git-ops agent (background) running `update-epics.sh`. The epic-planner remains read-only and MUST NOT write `epics.json` either.

**Corollary — no pre-reading before delegation**: Do not read source files before launching a coder. The coder reads its own files. Your job is to set up the pipeline (story, worktree, prompt) and launch. Reading files first wastes tokens and blocks the user.

---

## 2. AGENT ROLES

**todo-orchestrator** — pure research and classification. Permitted actions: Glob, Grep, Read, read epics.json, return staging payload. MUST NEVER: run tests, edit/write source files, run builds, commit, push, or open PRs.

**quick-fixer** — coder for clear-scope changes with known root cause, no schema/frame/AI changes.

**architect** — coder for ambiguous scope, schema changes, frame system mutations, new patterns, medium/high risk, or bugs spanning multiple interacting systems.

**reviewer** — on-demand code review. Launched only when user requests or story is flagged `needsReview: true`.

**unit-tester** — on-demand test runner. Launched only when story touches protected testable files or user requests.

**epic-planner** — research and planning agent. Two modes:

1. **Epic mode** (background): Takes an epic description and produces a multi-story plan. Trigger: "plan epic: ...". Always `run_in_background: true`. Writes to `$TMPDIR/epic-plan-<epic-slug>.md`. See §19.

2. **Planning mode** (foreground): Takes orchestrator NEEDS_PLANNING bullets and conducts interactive research — asks user questions, makes suggestions, produces a refined plan. Trigger: orchestrator returns NEEDS_PLANNING. Always **foreground** (interactive). Writes to `$TMPDIR/planning-<todo-slug>.md`. See §19.1.

Permitted actions (both modes): Glob, Grep, Read, WebFetch. MUST NEVER: edit/write source files, run builds, run tests, commit, push. Model: Sonnet default; Opus if Complexity is "high", Touches includes "AI tools"/"Firestore schema", or Files explored > 10.

**git-ops** — registered subagent (`subagent_type: "git-ops"`). Executes one pipeline script per invocation via Bash. MUST NEVER: edit or write source files (except `epics.json`), read source files, make architectural decisions, run builds, or run tests. Only permitted actions: Bash (git commands, the six pipeline scripts, and direct `epics.json` writes via node/python/jq or a dedicated update script). Always launched with `run_in_background: true`. Scripts live in `.claude/scripts/`:
- `setup-story.sh` — epic branch setup + story worktree creation (§9)
- `diff-gate.sh` — post-coder fetch, rebase, and out-of-scope file restoration (§11)
- `merge-story.sh` — story → epic branch merge + epic PR create/update + worktree cleanup (§12)
- `merge-queue.sh` — sequential diff-gate + merge for a list of stories (§12) — preferred over individual merge-story.sh calls
- `merge-epic.sh` — epic → main squash merge via PR (§13)
- `update-epics.sh` — read/write `epics.json` for state transitions and field updates (§15.1)

**Agent launch rule**: Coders, reviewer, unit-tester, and git-ops MUST ALWAYS be launched with `run_in_background: true`. No exceptions. Never use foreground mode for any of these agents. Do NOT launch them via Bash — always use the `Task` tool.

**Coders only execute approved plans — they never plan.**

---

## 3. MODEL SELECTION

| Role | Default | Escalation |
|---|---|---|
| Orchestrator | Haiku | Sonnet/Opus if task is architecturally complex before research begins |
| Epic-planner | Sonnet | Opus if epic touches >10 write-target files or involves AI/schema changes |
| Coder | Orchestrator's recommendation | Opus after 2 BLOCKING reviewer round-trips |
| Reviewer | Haiku | Sonnet only if coder ran on Opus |
| Unit-tester | Haiku | Never escalated |

**Orchestrator recommendation logic**: Haiku for trivial/mechanical; Sonnet for standard; Opus for high-risk or ambiguous.

**Agent selection override**: Follow the orchestrator's recommendation. Only override to architect if the user explicitly asks or a new ambiguity surfaces after orchestration.

---

## 4. INCOMING REQUEST → ORCHESTRATION

**A "code-changing prompt"** is any request that would modify, create, or delete project files.

**Route through orchestrator** (foreground, Haiku) when:
- A code-changing prompt arrives
- The "todo:" prefix is present (always routes through orchestrator, even if intent is ambiguous)

**Skip orchestrator** when ALL of the following are true: (1) the affected file(s) are already known, (2) the root cause is clear, (3) no new story/epic needs to be created, (4) no schema/frame/AI tool changes. Go directly to coder. Still create a `TaskCreate` entry for tracking.

**Bypass orchestrator entirely** for: pure questions or explanations, read-only research, git/commit/PR operations, and tasks that modify zero files in the working directory.

> **Note**: "non-project tasks" is NOT a bypass category. Documentation files checked into the project repo (`.md`, `.txt`, config docs, `CLAUDE.md`, `ORCHESTRATION.md`, etc.) are project files — editing them requires the full pipeline like any other file change. The only true bypasses are the four categories listed above.

**Preprocessing**: Before spawning the orchestrator, strip filler from the user message, extract the core intent as one sentence, and append a one-line summary of current story context. Pass this condensed prompt — not the raw message.

**Parallel orchestrators**: Multiple orchestrators can run simultaneously (read-only). Safeguards: (1) assign story IDs before spawning by pre-incrementing a counter in memory — never let two orchestrators pick the same ID; (2) process all staging payloads sequentially after all orchestrators complete; (3) if two orchestrators target the same file, note the conflict and sequence those stories.

**Epic-planned stories**: If the epic plan document specifies `writeFiles`, `agent`, and `model` per story, stage stories directly — no orchestrator needed.

**After orchestrator completes**, check output type:
1. **STAGING_PAYLOAD** → orchestrator writes payload to `$TMPDIR/staging-<todo-slug>.json` and returns `STAGING_PAYLOAD written to $TMPDIR/staging-<todo-slug>.json`. Read that file, validate (§6), present summary to user, create `TaskCreate` entries only after approval. No coder launches until a run trigger.
2. **NEEDS_PLANNING** → enter planning loop (§4.1).
3. **DUPLICATE** → inform user, stop.

**In-session tracking**: Use `TaskCreate` to register todos and `TaskUpdate` to track progress. Do not write to any JSON tracking file on every state change. `epics.json` is the sole persistent file — written only on story merge and on state transitions.

### §4.1 — NEEDS_PLANNING handling

When the orchestrator returns NEEDS_PLANNING:

1. **Group bullets** into categories (scope, approach, schema, UX) — cosmetic, helps planner structure research.
2. **Select model**: Opus if Complexity is "high", or Touches includes "AI tools"/"Firestore schema", or Files explored > 10. Sonnet otherwise.
3. **Derive `<todo-slug>`** (kebab-case, ≤5 words) from the task description.
4. **Launch epic-planner foreground** with planning prompt:
   ```
   MODE: planning
   Original task: <user's todo>
   Orchestrator findings:
     Complexity: <from NEEDS_PLANNING>
     Touches: <from NEEDS_PLANNING>
     Files already explored: <from NEEDS_PLANNING>
   Open questions (grouped):
   ## Scope
   - <bullet>
   ## Approach
   - <bullet>
   Instructions: Research the codebase, ask the user questions via AskUserQuestion,
   make concrete suggestions, write output to $TMPDIR/planning-<todo-slug>.md
   ```
5. **Wait** for planner to complete (foreground blocks).
6. **Read** `$TMPDIR/planning-<todo-slug>.md`.
7. **Re-launch orchestrator** (Haiku, foreground) with:
   ```
   PLANNING_CONTEXT
   Original task: <user's todo>
   Resolved plan: <full planning output>
   Files already explored: <union of all explored files>
   Produce STAGING_PAYLOAD. Do not return NEEDS_PLANNING.
   ```
8. If orchestrator returns **NEEDS_PLANNING again**: surface remaining questions to user directly, stop. No infinite loop — max 1 planning loop.
9. If **UNRESOLVABLE**: surface reason to user, stop.
10. If **STAGING_PAYLOAD**: validate (§6) and present as normal.

---

## 5. ORCHESTRATOR OUTPUT FORMAT

The orchestrator must return output in this exact structure. Do not accept output that deviates from it.

```
SUMMARY
Todo: <one-line description>
Story: <storyId> — <story title> [NEW if creating]
Epic: <epicId> — <epic title> [NEW if creating]
Agent: <quick-fixer|architect>
Model: <haiku|sonnet|opus>
Trivial: <yes|no>
Files:
  write: <comma-separated files the coder will modify>
  read: <comma-separated files needed for context only>
Plan: <one sentence describing what the coder will do>
Coder groups: <see format below>
STAGING_PAYLOAD written to: $TMPDIR/staging-<todo-slug>.json
```

The orchestrator MUST write the staging payload JSON to `$TMPDIR/staging-<todo-slug>.json` before returning. The main session reads that file for validation. Do NOT include the JSON inline in the return message.

**Coder groups format**:
```
Group 1 [architect|quick-fixer]: todo-xxx — <one-line rationale>
Group 2 [quick-fixer]: todo-yyy, todo-zzz — <one-line rationale>
Sequential after group 1: todo-aaa — <reason for dependency>
```

**Staging payload schema**:
```json
{
  "storyUpdate": {
    "id": "story-001",
    "epicId": "epic-001",
    "title": "Story title",
    "state": "filling",
    "branch": null,
    "writeFiles": ["src/handlers/stageHandlers.js"],
    "needsTesting": false,
    "needsReview": false,
    "agent": "quick-fixer",
    "model": "sonnet"
  },
  "epicUpdate": {
    "id": "epic-001",
    "title": "Epic title",
    "branch": null,
    "prNumber": null,
    "persistent": true
  }
}
```

`epicUpdate` is null if no new epic is needed. The main session creates `TaskCreate` entries from the orchestrator's plan — not JSON file writes.

**NEEDS_PLANNING output format** (returned instead of STAGING_PAYLOAD when ambiguity is too broad for a single question):

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

Rules:
- Minimum 2 questions, maximum 8. If only 1 question needed, ask it directly via the normal clarification path.
- Questions must be specific — not "what do you want?" but "should the field be denormalized or queried separately?"
- Each question must be independently answerable — no chaining.
- Complexity reflects the full task: "high" if >5 files, touches frames/AI/schema, or new patterns.
- If >5 files explored without converging on a plan, that is the signal to return NEEDS_PLANNING.

**UNRESOLVABLE output format** (returned when even planning cannot resolve the task):

```
UNRESOLVABLE
Todo: <one-line description>
Reason: <why this cannot be staged>
```

**Orchestrator responsibilities** (in order):
1. **Dedup check first**: Read `epics.json`. If an existing story already covers this request, return `DUPLICATE: <story-id>` and stop.
2. **Classify**: Explore only the files needed to understand the task. No broad surveys.
3. **Assign story/epic**: Find the best-fit story in `epics.json`. If none fits, propose a new story (and epic if needed).
4. **Decide coder grouping**: Apply the grouping decision tree (§10). Flag write-target vs. read-only files per group.
5. **Return the staging payload**: Structured JSON + human summary. Do not write any files.

---

## 6. STAGING PAYLOAD VALIDATION

Before updating `epics.json`, validate:
- `storyUpdate` has all required fields: `id`, `epicId`, `title`, `state`, `branch`, `writeFiles`, `needsTesting`, `needsReview`
- `state` is a valid value (`filling`, `running`, `closed`, etc.)
- `writeFiles` is a non-empty array
- If `epicUpdate` is present: all required fields present (`id`, `title`, `branch`, `prNumber`, `persistent`)
- If validation fails: surface the error to the user, do not write, do not re-launch orchestrator automatically

---

## 7. EPIC / STORY STRUCTURE

Work is organized in two persistent levels:
- **Epic** — a broad theme. Lives in `.claude/epics.json`.
- **Story** — a scoped deliverable under an epic. Has its own branch and worktree. Stories are the unit of execution.

Todos are session-scoped — tracked via `TaskCreate`/`TaskList`/`TaskUpdate` during the session, not persisted to disk.

**epics.json field reference**

Each epic entry: `id`, `title`, `branch` (null until first story runs), `prNumber` (null until PR created), `persistent` (default true — tracking field only; branch is deleted after epic PR merges).

Each story entry:
```json
{
  "id": "story-001",
  "epicId": "epic-001",
  "title": "Ghost placement accuracy",
  "state": "closed|running|filling",
  "branch": "story/ghost-placement",
  "writeFiles": ["src/handlers/stageHandlers.js", "src/components/BoardCanvas.jsx"],
  "needsTesting": false,
  "needsReview": false,
  "agent": "quick-fixer",
  "model": "sonnet"
}
```

`agent` and `model` are optional fields set at staging time. Existing stories without these fields are valid — display them without agent/model columns.

**Special agent value — `"manual"`**: Used by the `/checklist` skill for human-executed stories. Manual stories have no worktree, no branch, and no coder. They go straight to `running` and are closed by the checklist skill after all steps complete. They skip all diff-gate, reviewer, and unit-tester pipeline steps.

**Valid story state transitions**:
```
filling → queued          (run triggered but dependsOn stories not yet closed)
filling → running         (run trigger, no blocking dependsOn)
queued → running          (all dependsOn stories closed — auto-triggered)
running → merging         (all coders done, default path — no tester or reviewer)
running → testing         (all coders done, story flagged needsTesting or user requests)
testing → merging         (unit-tester PASS)
testing → running         (unit-tester FAILED — send back to coder)
running → reviewing       (user explicitly requests review, or story flagged needsReview)
reviewing → running       (reviewer BLOCKING — send back to coder)
reviewing → merging       (reviewer PASS)
merging → closed          (merged into epic branch)
any → blocked             (Opus escalation still blocking — see §11 Escalation)
```

Note: `reviewing` is only entered on-demand. Normal pipeline: `running → testing → merging`.

**Ephemeral plans**: Write to `$TMPDIR/plan-<story-id>.md`. Do not persist in `~/.claude/plans/`. Architecture decisions go in `CLAUDE.md`.

---

## 8. FILL PHASE

After the main session creates `TaskCreate` entries from the approved staging payload, it stops — no coder launches. The user adds more todos until ready to trigger.

**Safe to /clear when ALL of the following are true:**
1. No background agent is currently running
2. No agent result is needed to proceed (coder done, diff gate passed, etc.)
3. You are between stories (not mid-pipeline)

**What survives /clear**: git branches, worktrees, epics.json, all disk state.
**What is lost**: in-session memory, coder task status, agent task list.
**Recovery**: run `/recover` after `/clear` if a story was in-flight.

**Post-clear behavior**: After `/clear`, ORCHESTRATION.md is reloaded automatically on the first relevant request via pre-response-check. No warm-up message needed. The orch-read marker persists in /tmp and does not block Task/Edit/Write calls.

**Context clearing** (mandatory, not discretionary):
1. After a story merges — after all merge cleanup, before auto-launching any queued story.
2. After reviewer + unit-tester both launch — once both are running in background.
3. After any background agent completes with no immediate follow-up action.
4. When a background agent is running and the user asks if it's a good time to clear — if no result is immediately needed, confirm yes.
5. After 3 or more stories have been closed in a single session — prompt the user to `/clear` before starting the next story.

Never clear if a background agent is currently running and its result is needed to proceed.

**Standardized clearing message**: At every checkpoint above, use this format:
> "Context checkpoint reached [reason]. Run `/clear` to reset the session. All epic and story state is saved in epics.json."

Examples: `[reason]` = "story merged", "3 stories closed this session", "session recovery complete", "epic merged".

---

## 9. RUN TRIGGER

Coders only launch when you explicitly say "run story-X" (or "run all open stories"). Use `/run-story` skill to execute this sequence. Main session then:

1. Read the story from `epics.json`, create `TaskCreate` entries for each todo if not already created.
2. **Dependency check**: If story has a `dependsOn` field, verify all listed story IDs are `closed` in epics.json. If any are NOT closed: set story state to `queued` via `update-epics.sh`, report which stories are blocking, and stop. The story will auto-launch when its last blocker merges (see §14).
3. **Assign the story branch** if `branch` is null: generate `story/<slug>`, write to `epics.json`.
4. **Pre-flight worktree check** (inline, before launching git-ops):
   - If worktree exists AND state is `running`: run `git -C <worktree> status --porcelain`. If uncommitted changes exist and no coder tasks are in-progress → warn user, do NOT launch until they confirm. If some tasks done and others pending → valid partial state, proceed. Launch only pending tasks.
   - If worktree exists but state is not `running`: warn user, do not proceed.
5. **Pre-flight summary** (printed before launching git-ops, skipped if `--no-preview` flag passed):
   ```
   Story: <title>
   Agent: <quick-fixer | architect>
   Write targets: <list of writeFiles>
   Read context: <read-only context files, if any>
   Protected files: <any writeFiles in the protected Konva list, or "none">
   Estimated scope: <line count estimate from plan, if available>
   ```
   The user sees this before any file changes begin. Add `--no-preview` to `/run-story` to skip for experienced users.

6. **Launch git-ops agent** (background) with prompt:
   ```
   Run: bash <project-root>/.claude/scripts/setup-story.sh \
     <project-root> <epic-slug> <story-branch> <story-slug>
   Report exit code and full stdout/stderr. Do not edit any files.
   ```
   Wait for git-ops to complete before launching coders. If it exits non-zero, report error to user and stop.
7. Launch coder tasks in BACKGROUND; track status via `TaskUpdate`.
7. Update story `state` to `running` in `epics.json`.

**Before launching a coder**: warn the user if the session is not in auto-edit mode.

**When a story closes**: scan epics.json for `queued` stories whose `dependsOn` are now all `closed`. For each: auto-launch `setup-story.sh` + coder (background). Notify the user.

---

## 10. CODER GROUPING

Applied by the orchestrator at classification time. Coder groups are tracked via `TaskCreate` during the session.

**Decision tree**:
```
1. agent == "architect"
   → solo group, always

2. agent == "quick-fixer" AND no file overlap with any architect todo
   → eligible for grouping with other quick-fixers

3. agent == "quick-fixer" AND file overlap with an architect todo
   → dependsOn that architect group

4. Two quick-fixers share a write-target file:
   - Different functions/sections → same group; note shared file in prompt
   - Same function/section → separate groups, second dependsOn first

5. blockedBy: if todo A has blockedBy: todo B, and both are in this story
   → todo A's group gets dependsOn = todo B's group id

Launch order:
  - Architect groups with no overlap: parallel (dependsOn: null)
  - Quick-fixer groups with no architect overlap: parallel with architects (dependsOn: null)
  - Quick-fixer groups overlapping an architect: dependsOn that architect group
```

**Task size ceiling**: If a coder group's write-targets span >5 files or estimated change is >200 lines, split into 2+ atomic sub-tasks. Each gets its own `TaskCreate` entry and runs sequentially within the same worktree.

**Return length caps** (include in every agent prompt):
- Coder (success): 1 line — "done: <what changed>"
- Coder (deviation/decision): ≤5 lines
- Coder (error/blocked): uncapped — include full error output
- Reviewer (PASS): 1 line
- Reviewer (BLOCKING): ≤10 lines per finding, uncapped on error
- git-ops (success): 1 line
- git-ops (error): uncapped
- unit-tester (PASS): 1 line — "tests passed: <N> tests"
- unit-tester (FAIL): uncapped — full output required for log + re-delegation

**Coder prompt requirements** (every prompt must include):
- Todo descriptions — list every todo explicitly. The coder must confirm all are implemented before committing.
- Write-target files (will be modified) and read-only context files (read but do not modify).
- Edge cases extracted from codebase research. This is the highest-leverage way to reduce reviewer round-trips.
- **A "Pitfalls" section** — required for every non-trivial prompt. Common pitfalls to include when applicable:
  - Konva Groups return `0` from `.width()` and `.height()` — use `.getClientRect()` for live bounding box
  - `onDragMove` / async callbacks must read state from refs (`.current`), not closed-over props
  - If adding `:focus-visible` CSS, ensure the outline color contrasts with the button background
  - Firestore `batch.update` throws if the document is also being deleted in the same batch — use `batch.set({merge:true})` or guard with a deleteSet check
  - Frame `childIds` and child `frameId` must always be updated atomically in the same `writeBatch`
  - For new object types: include the CLAUDE.md 6-step checklist
  - For CSS alignment fixes: verify the parent container has `display: flex` before adding flex-child properties
  - For any new props/params: "Do not destructure or accept props/params you don't use. Verify every new prop is referenced."
  - For any new `async` event handler: "Capture all React state and props you need into local `const` variables before the first `await`. Never read state after an `await`."
- Specific invariants to preserve and known gotchas in the affected files.
- **CWD mismatch note** (required in every coder prompt): "Use absolute paths only — your CWD may not match the target directory. Do not use Glob/Grep without specifying the full absolute path."

**Protected Konva files** (include in every coder prompt):

The following files must NEVER be edited unless explicit user permission is stated in the current session:
- `src/components/BoardCanvas.jsx`
- `src/components/StickyNote.jsx`
- `src/components/Frame.jsx`
- `src/components/Shape.jsx`
- `src/components/LineShape.jsx`
- `src/components/Cursors.jsx`

If the story does NOT require editing these files, include verbatim:
> "IMPORTANT: Do NOT edit any of these protected files: BoardCanvas.jsx, StickyNote.jsx, Frame.jsx, Shape.jsx, LineShape.jsx, Cursors.jsx — even if you think an edit would improve them. Scope creep into protected files will block the review."

If the story DOES require editing a protected file, include: "The user has explicitly granted permission to edit [filename] for this story."

**Protected testable files**: If a story's write-targets include any file in `src/utils/`, `src/hooks/`, or any file with a `.test.*` counterpart, stop before launching the coder and ask the user:
> "This story needs to edit [filename(s)], which are protected testable files. Allow edits? (This will set `needsTesting: true` on the story.)"

On approval: set `needsTesting: true` on the story in `epics.json`. Do NOT modify `.claude/settings.local.json`. If the user declines, remove those files from write-targets and revise the plan.

Coders must only write to write-target files.

---

## 11. PIPELINE EXECUTION

`coder tasks → diff gate → [testing?] → [reviewing?] → merge`

### When a coder task completes
- Mark done via `TaskUpdate`. If blocked: stop, report to user.
- Check for dependent tasks — if dependencies satisfied, launch them.
- When all coder tasks for a story are done: run the **diff gate**.

### Diff gate (mandatory — delegated to git-ops agent, background)

Launch git-ops agent (background) with prompt:
```
Run: bash <project-root>/.claude/scripts/diff-gate.sh \
  <project-root> <epic-slug> <story-branch> <write-file1> [<write-file2> ...]
Report exit code and full stdout/stderr. Do not edit any files.
```
Exit code semantics:
- `0` — diff matches write-targets; gate passes. Proceed to next pipeline step.
- `1` — diff is empty (nothing committed). Report to user and stop.
- `2` — unexpected files remain after restoration. Report to user; manual fix required before continuing.

If any files were restored, the script commits `"fix: restore out-of-scope files to epic branch state"` automatically. **Do not launch reviewer or tester until git-ops exits 0.**

If a reviewer flags files the story didn't touch: this is a stale-branch issue, not a code bug. Re-run the diff gate, then re-launch reviewer and unit-tester.

### After diff gate

**Trivial stories** (all todos marked trivial): run `npm run build` inline → if passes, proceed to merge. Skip reviewer and tester.

**Default (no testing flag)**: proceed to merge immediately.

**needsTesting stories**: launch unit-tester (background), story → `testing`. Wait for result.

### Unit-tester (on-demand)
Auto-triggered when write-targets include: `src/utils/`, `src/hooks/`, permission/admin logic, Firestore read/write paths, AI tool declarations or executors, or any file with a `.test.js` / `.test.jsx` counterpart. Also triggered when user says "test this story" or story is flagged `needsTesting: true`.

**Unit-tester prompt**: write-target paths (as `writeFiles` list) + all todo descriptions + worktree absolute path. The agent uses `writeFiles` as arguments to `npx vitest related --run <files>` to discover relevant tests before running anything. Do NOT omit `writeFiles` — the agent cannot use `--related` without them.

**Unit-tester results**:
- PASS → story state to `merging`, handle merge.
- FAIL (trivial — missing import, typo): fix inline, re-run tester.
- FAIL (non-trivial): the agent must include root cause classification + 2–3 sentence analysis before re-delegating. Log to test failure log (§17), send back to coder with the full diagnosis. Re-run diff gate, then re-run tester.
- Lint errors → treated as FAIL. Lint warnings → surfaced in summary after merge, do not block.

### Simple-fix policy
If the reviewer or tester finds a trivial mechanical issue (missing import, wrong constant, typo), fix it inline via Bash/Edit rather than delegating to a coder agent.

**Precedence**: Worktree threshold overrides simple-fix policy. Simple-fix only applies when the file is not protected AND the total change touches ≤2 files. Any change touching >2 files or any protected Konva file goes through the full worktree pipeline regardless of how trivial it appears.

### Reviewer (on-demand)
Only launched when user explicitly requests review OR story is flagged `needsReview: true`. Do NOT launch automatically. Trigger conditions include: frame system mutations, Firestore schema changes, AI tool logic, complex multi-system interactions.

Unit-tester must pass before reviewer launches. Never gate one story's pipeline on another story's state.

**Reviewer prompt**: write-target paths + todo descriptions + the story branch diff (`git diff main...<branch> -- <write-target files>`).
- **Diff-only mode** (first pass): if diff is ≤75 lines, review from diff only. If full-file context is needed, flag as `needs-context: <filename>` rather than BLOCKING. The main session re-runs the reviewer with those files included. If diff >75 lines, reviewer opens full files as normal.
- On send-back: include which coder task each finding belongs to. Include the coder's fix diff in the send-back prompt.
- Reviewer checklist: enumerate all instances of a pattern before marking PASS.

**Reviewer results**:
- PASS → story state to `merging`, handle merge.
- BLOCKING → fix inline if trivial; otherwise send back to coder. Re-run diff gate → tester → reviewer after fix. Do NOT increment retry count for simple-fix warnings.
- **Log-only warnings** (judgment calls, trade-offs): append to `/Users/kelsiandrews/gauntlet/week1/.claude/review-findings.md`. Surface summary after merge: "X warnings logged to .claude/review-findings.md"

If reviewer output contains `⚠ reviewer-learnings.md has N entries`, surface after pipeline completes:
> ⚠️ **reviewer-learnings.md has N entries — consider reviewing and promoting patterns.**

### Escalation
**Reviewer send-back budget**: 2 BLOCKING round-trips. After 2: escalate coder to Opus, run once more. Budget does not reset after escalation. If Opus attempt is still BLOCKING → set story state to `blocked`, report all findings to user, leave worktree intact. `blocked` → `running` is a valid manual reset.

**Blocked-story resume protocol**: When a story is in `blocked` state and the user wants to resume:

1. **Manual reset**: User runs:
   ```
   update-epics.sh '{"storyId":"story-X","fields":{"state":"running"}}'
   ```
   Or equivalently, tells the main session "reset story-X to running" — the main session delegates to git-ops.

2. **Re-launch options**: After state resets to `running`, the main session asks the user:
   - "Re-launch the same coder with revised instructions?" (user provides new instructions or constraints)
   - "Proceed to diff-gate with current worktree state?" (if user manually fixed the code)

3. **Reviewer retry budget**: Does NOT reset after user intervention. If the story already had 2 BLOCKING rounds, the Opus escalation has been used. A user reset does not grant additional retry budget — the story is now on borrowed time. The user should provide clear new instructions to avoid another BLOCKING.

4. **Worktree state**: The worktree is left intact when a story enters `blocked`. The user can inspect it with `git -C <worktree-path> diff` and `git -C <worktree-path> log --oneline`.

### After successful merge
- Story state to `closed` in `epics.json`, check epic auto-close, unblock dependent stories.
- **Architectural findings check**: Scan coder output, reviewer warnings, and test failure log for novel findings (unexpected API behaviors, new invariants, patterns to document). Novel = not already present as a bullet in CLAUDE.md (Grep for 3+ key terms before appending). If novel: append to appropriate CLAUDE.md section (one bullet, concise, actionable). Do NOT ask the user — append silently.
- **Integration surface check**: If the merged story introduces a new registry, hook, or plugin API that other features must wire into, check whether the project CLAUDE.md has a corresponding entry in `## Integration surfaces`. If not, add one (surface name, owner file(s), registration pattern). Create the section if it doesn't exist yet.

---

## 12. STORY MERGE SEQUENCE

**Preferred: merge-queue.sh (one agent, N stories)**

When one or more stories are ready to merge into the same epic, launch a single git-ops agent (background) with:
```
Run: bash <project-root>/.claude/scripts/merge-queue.sh \
  <project-root> '<json-manifest>'

where <json-manifest> is a JSON array:
[
  {
    "storyBranch": "story/my-feature",
    "storyTitle":  "My feature title",
    "epicSlug":    "my-epic",
    "epicTitle":   "My Epic Title",
    "prNumber":    "86",
    "writeFiles":  ["src/foo.js", "src/bar.css"]
  },
  ...
]

Pass "" for prNumber if this is the first story merging into the epic.
Report exit code and full stdout/stderr. Do not edit any files.
```

The script runs diff-gate + merge sequentially for each story and threads the PR number through automatically. Stories for *different* epic branches may run in separate parallel agents.

When git-ops exits 0:
- For each `MERGED:<storyBranch>:PR_NUMBER=<n>` line in the output: update the epic's `prNumber` in `epics.json` if it changed, and set the story state to `closed`.
- Check epic auto-close, unblock dependent stories.

**Single-story fallback**: Only use `merge-story.sh` directly when merging a single story and no queue is needed.

**Draft PR option**: When the user passes `--draft` to `/merge`, the epic PR is created as a draft (`gh pr create --draft`). This is useful when the epic has more stories pending — the PR is visible on GitHub but not merge-ready. The epic `prNumber` is recorded normally in `epics.json`. When the user triggers "merge epic X" later, the main session runs `gh pr ready <prNumber>` to convert draft → ready before running `gh pr merge --squash --delete-branch`.

**Git rules**:
- Never `git branch -D` — force-delete is forbidden. If `-d` fails, advance the local ref with `git update-ref` first, then retry `-d`.
- Never merge story branches directly to main — stories go through the epic branch.
- Never commit without explicit instruction.
- **Serial merges — use merge-queue.sh**: When multiple stories are ready to merge, always use `merge-queue.sh` with a JSON manifest rather than launching multiple `merge-story.sh` agents. A single git-ops agent runs all diff-gates and merges sequentially in one invocation. Stories targeting *different* epic branches can be sent to separate `merge-queue.sh` agents in parallel. Never launch two agents targeting the same epic branch simultaneously — `merge-story.sh` does `git checkout epic/...` on the main worktree and concurrent agents race on this checkout.

---

## 13. EPIC MERGE SEQUENCE

Only when user says "merge epic X" or all stories are `closed`.

Launch git-ops agent (background) with prompt:
```
Run: bash <project-root>/.claude/scripts/merge-epic.sh \
  <project-root> <epic-slug> <pr-number>
Report exit code and full stdout/stderr. Do not edit any files.
```

The script squash-merges via `gh pr merge --squash --delete-branch`, deleting the remote epic branch immediately. The local ref is also deleted. Epic branches do not persist after merge.

**Draft → ready conversion**: If the epic PR was created as a draft (see §12 Draft PR option), the main session must run `gh pr ready <prNumber>` BEFORE launching `merge-epic.sh`. Check the PR state with `gh pr view <prNumber> --json isDraft` first — if `isDraft` is true, run `gh pr ready <prNumber>` and wait for it to succeed before proceeding.

After the epic merge completes, prompt: "Context checkpoint reached (epic merged). Run `/clear` to reset the session. All epic and story state is saved in epics.json."

**Auto-close rules**:
- Story closes on successful merge into epic branch.
- Epic closes when all its stories are `closed`.

---

## 14. PARALLEL STORY EXECUTION

Stories can run in parallel if they share no write-target files (read-only files do not create a conflict).

Before launching a story, check `epics.json` for stories currently `running`, `reviewing`, or `testing`:
- **No write-file overlap**: launch immediately in parallel.
- **Write-file overlap**: queue the story. When the blocking story merges, auto-launch the queued story — do not ask the user.

When a story completes, scan for `queued` stories whose `dependsOn` are now all `closed` — run `setup-story.sh` (git-ops, background), set state to `running`, and launch the first coder task in BACKGROUND. Also scan for `filling` stories with no blocking dependencies and notify the user they are ready to run.

**Merge ordering**: Stories within the same epic merge into the same epic branch. First to complete merges first. Second story rebases onto the updated epic branch before merging. If rebase produces a conflict → pause, report to user (see rebase conflict protocol below).

**Batch merge window**: After a story completes, wait 30 seconds. If another story completes in that window, merge both sequentially in one operation.

**Rebase conflict pause protocol**: When merge-queue.sh exits non-zero on a rebase step:
1. Parse the output to identify which story's rebase failed and which files conflict.
2. Pause the pipeline for that epic branch only. All other epic branches continue running.
3. Report to user:
   ```
   Rebase conflict on <story-branch> rebasing onto <epic-branch>.
   Conflicting files: <list>
   Other epic branches: unaffected.
   ```
4. User resolution path:
   - Fix conflicts manually, then: `git -C <worktree-path> add <files> && git -C <worktree-path> rebase --continue`
   - Or abort rebase: `git -C <worktree-path> rebase --abort`
   - After resolution, re-run merge for the affected story only: `/merge <story-id>`
5. Do NOT auto-resolve conflicts — always surface to user.

**Sequence decisions** (autonomous): (1) fewest overlapping files first, (2) lowest complexity first (quick-fixer before architect), (3) story id ascending as tiebreaker. Never ask the user to choose the sequence.

---

## 15. CROSS-SESSION RECOVERY

**Snapshot triggers** — all `epics.json` writes are delegated to git-ops via `update-epics.sh`. Write at exactly these points:
1. After each story merges into the epic branch.
2. On state transitions that matter cross-session (`filling` → `running`, `running` → `closed`).
3. After new stories/epics are approved and staged.
4. After branch assignment (run trigger) and prNumber recording (merge).

**§15.1 — update-epics.sh protocol**: Launch git-ops (background) with:
```
Run: bash <project-root>/.claude/scripts/update-epics.sh \
  <project-root> '<json-patch>'
where <json-patch> is a JSON object describing the update, e.g.:
  '{"storyId":"story-053","fields":{"state":"running","branch":"story/connector-drag-fix"}}'
  '{"storyId":"story-053","fields":{"state":"closed"}}'
  '{"epicId":"epic-007","fields":{"prNumber":99}}'
  '{"newStory":{...full story object...},"epicId":"epic-007"}'
Report exit code and full stdout/stderr. Do not edit any files.
```
When staging a new story, include `agent` and `model` in the `newStory` object so they are persisted for display by `/status`.
The script reads `epics.json`, applies the patch atomically, and writes it back. If the script does not yet exist, the git-ops agent may write `epics.json` directly via a one-line node/python command instead, until the script is created.

**Recovery on session start** — when `epics.json` shows a story in `running` state:
1. Check if the story worktree still exists (`git worktree list`).
2. Check for uncommitted changes in the worktree.
3. Report: "Story X was in-flight when the last session ended. Worktree at .claude/worktrees/story/X [has uncommitted changes | is clean]. Resume or discard?"
4. Do not auto-resume — wait for user decision.

After recovery is resolved (user says resume or discard), prompt: "Context checkpoint reached (session recovery). Run `/clear` to start fresh. All epic and story state is saved in epics.json."

**What's lost on crash**: only in-session todo progress and coder task status. Git state (branches, worktrees, commits) is the ground truth for anything in-flight.

**Recovery sources**:
1. `epics.json` on disk
2. `git worktree list`
3. `git branch --list 'story/*' 'epic/*'`

---

## 16. BACKGROUND AGENT MANAGEMENT

**Check-in cadence**: Ping long-running background agents every 3 minutes via `TaskOutput` with `block: false`. If an agent shows no new tool uses after 2 consecutive check-ins (6 minutes), stop it, re-split the task into smaller pieces (each ≤5 files, ≤200 lines), and warn: "Story [id] ([title]) agent stalled after 6 minutes. Splitting and re-launching."

**Error handling**:
- Tests run from the **root worktree** always. Build (`npm run build`) runs from the story worktree.
- Test/build failure (trivial): unit-tester fixes directly.
- Test/build failure (non-trivial): re-delegate to coder with failing output → re-run reviewer + unit-tester in parallel. Max 2 retries, then escalate to user.
- Reviewer blocking: handled by pipeline retry rules — do not re-run orchestrator.
- Plan rejected: re-launch orchestrator in foreground with user's feedback.
- Merge conflict: abort, notify user, pause.

---

## 17. LOGGING

**Test failure log**: Whenever unit-tester reports a non-trivial failure (requires re-delegation), append to `/Users/kelsiandrews/gauntlet/week1/.claude/test-failure-log.md` (always absolute path) before re-delegating. The unit-tester agent is responsible for filling in root cause and analysis — the main session copies these verbatim from the agent output into the log.

```
## [ISO date] — [story id] — [one-line failure title]
**Coder agent**: quick-fixer | architect
**Model**: haiku | sonnet | opus
**Failing test(s)**: [test name(s) or file(s)]
**Error**: [exact error message, truncated to ~300 chars]
**Root cause category** (exactly one checked by unit-tester):
  - [ ] Careless mistake (wrong variable, off-by-one, typo)
  - [ ] Scope too narrow (coder didn't read enough context before writing)
  - [ ] Prompt gap (plan was missing a critical detail)
  - [ ] Framework/API misuse (wrong Konva/Firebase/React API)
  - [ ] Test environment issue (mock gap, timing, missing setup)
**Analysis**: [2-3 sentences from unit-tester: what went wrong and why]
**Coverage gap**: [yes — no test existed for this path | no — existing test should have caught this]
**Resolution**: re-delegated to coder | escalated to user
```

If the unit-tester output does not include a pre-filled root cause and analysis, reject it: send back to the tester with instruction to classify before re-delegating.

Once the log reaches **5 entries**, surface after the next successful pipeline completion (once per session):
> "test-failure-log.md has N entries. Worth reviewing to identify coder prompt patterns that need improvement."

**Review findings log**: Log-only reviewer warnings go to `/Users/kelsiandrews/gauntlet/week1/.claude/review-findings.md`.

---

## 18. TOKEN OPTIMIZATIONS

**Coder prompt size limit**: Keep coder prompts under 2000 tokens. Include: todo descriptions, write-target paths, read-only paths, Pitfalls section. Omit: full file contents, architecture explanations available in CLAUDE.md, verbose rationale. Link to CLAUDE.md sections by name.

**CSS-only stories** (no JS/JSX changes): always use Haiku, skip testing, skip diff gate file restoration. Only run `npm run build` to verify no syntax errors.

**Inline parallelism**: Bash commands that don't gate the next write (build verification, lint, diff checks, git status) must run with `run_in_background: true` when there is other independent work in parallel. Read the background result only when the next decision requires it.

---

## 19. EPIC PLANNER

### Trigger
User says `"plan epic: <description>"` or provides a requirements doc and asks to plan it. This is the only correct entry point — do not route through the todo-orchestrator for epic-level planning.

### Launch sequence
1. Derive an `<epic-slug>` from the description (kebab-case, ≤5 words).
2. Assign a new epic ID by reading `epics.json` and incrementing the highest existing epic number.
3. Launch epic-planner agent in **background** (`run_in_background: true`, model: Sonnet by default).
4. Proceed with other work. Do not block waiting for the result.
5. When the agent completes, read `$TMPDIR/epic-plan-<epic-slug>.md`.
6. Validate each story payload (same rules as §6). Surface any validation errors to the user.
7. Present the full plan summary to the user for approval.
8. On approval: write all stories to `epics.json` (state: `filling`), create `TaskCreate` entries for each story.

### Epic-planner agent prompt (required elements)
- Epic description / requirements doc content
- Absolute path to `epics.json` (for dedup check)
- Absolute path to project root (for Glob/Grep)
- Output path: `$TMPDIR/epic-plan-<epic-slug>.md`
- Instruction to deduplicate against existing stories before proposing new ones
- Integration surface check block (§19.2) — always include; planner skips it if no `## Integration surfaces` section exists in CLAUDE.md

### Epic-planner output format
The agent MUST write a file at the specified output path with this structure:

```
EPIC_PLAN
Epic: <epic-id> — <epic title>
Stories: <count>

STORY <n>
Title: <story title>
Agent: <quick-fixer|architect>
Model: <haiku|sonnet|opus>
Trivial: <yes|no>
Files:
  write: <comma-separated>
  read: <comma-separated>
Plan: <one sentence>

...repeat for each story...

STAGING_PAYLOAD
<valid JSON array of story staging payloads — same schema as §5, wrapped in { "epicUpdate": {...}, "stories": [...] }>
```

The main session reads this file, validates the JSON, then presents it to the user.

### Epic-planner constraints
- Research only — no writes, no builds, no tests, no commits.
- Dedup first: read `epics.json`, skip any story that duplicates an existing open story.
- Group stories by write-file overlap (same grouping logic as §10) and note dependencies.
- Flag any story that touches protected testable files (`needsTesting: true`) or protected Konva files (note: user permission required).
- Stay within the task size ceiling: if a logical unit spans >5 write-targets or >200 lines estimated, split into sub-stories.
- Do NOT write to `epics.json` — that is the main session's job after user approval.

---

## 19.1. EPIC PLANNER — PLANNING MODE

### Mode comparison

| Aspect | Epic mode (§19) | Planning mode (§19.1) |
|---|---|---|
| Trigger | "plan epic: ..." | Orchestrator NEEDS_PLANNING |
| Launch | Background | Foreground (interactive) |
| User interaction | None | Required — must ask questions |
| Output | Multi-story plan + staging payloads | Single refined plan document |
| Consumer | Main stages stories directly | Main feeds back to orchestrator |

### Behavior

1. Research areas listed in Touches, skip files already explored unless deeper context is needed.
2. For each open question: resolve via codebase research or ask the user via `AskUserQuestion`. Do NOT silently assume answers.
3. Propose a concrete approach for each question with brief trade-offs.
4. Wait for user response before proceeding. Batch 2–3 independent questions at once to reduce round-trips.
5. Write output to `$TMPDIR/planning-<todo-slug>.md`.

### Output format

```
PLANNING_RESULT
Original task: <one-line>
Questions resolved: <count>

## Decisions
- Q: <question>
  A: <answer>
  Rationale: <one sentence>

## Recommended approach
<2-5 sentences>

## Scope
Write files: <comma-separated>
Read files: <comma-separated>
Agent: <quick-fixer|architect>
Model: <haiku|sonnet|opus>

## Constraints and edge cases
- <bullet>
```

### Edge cases

- If user says "you decide" on a question: planner decides, tags with `(planner decision)`.
- If user cancels mid-planning: planner writes partial output, main session asks user whether to proceed with partial plan or abandon.
- If planner cannot resolve all questions: partial decisions tagged `(planner decision)`, orchestrator treats as resolved.

---

## 19.2. EPIC PLANNER — INTEGRATION SURFACE RECONCILIATION

### What is an integration surface?

An **integration surface** is a feature that exposes a registry, hook, or plugin API that other features must explicitly wire into to function correctly. Examples:
- A command palette that other features register commands with
- A keyboard shortcut registry
- A context menu that features add items to
- A notification/event bus that subscribers must register with
- A settings panel that features add sections to

### How to declare integration surfaces in CLAUDE.md

Projects maintain an `## Integration surfaces` section in their `CLAUDE.md`. Each entry names the surface, its owner file(s), and the registration pattern:

```
## Integration surfaces
- **Command palette** — `src/components/CommandPalette.jsx` + `src/hooks/useCommandRegistry.js`
  Registration: call `registerCommand({ id, label, action })` from a `useEffect` in the feature component or hook.
- **Context menu** — `src/components/ContextMenu.jsx`
  Registration: pass items via `contextMenuItems` prop on `<BoardCanvas>`.
```

The epic-planner reads this section at the start of every epic plan run.

### Detection algorithm (epic-planner, run after all feature stories are drafted)

For each pair of stories (A, B) in the epic plan:

1. **Surface owner check**: Does story A's `writeFiles` include a file listed as an integration surface owner? If yes, A *introduces or modifies* a surface.
2. **Consumer check**: Does story B introduce a user-facing capability that the surface is designed to expose? Apply in order:
   - **Confident yes**: story B's plan explicitly mentions registering, adding to, or wiring into the surface (e.g. "add command to palette", "register shortcut") — generate integration story, no question needed.
   - **Confident no**: story B is infrastructure-only (CSS, Firestore rules, config, tests, schema migration) with no user-visible action — skip, no question needed.
   - **Uncertain**: story B adds a user-facing feature (new component, new hook, new handler) but it's unclear whether it belongs in the surface — ask the developer via `AskUserQuestion` before deciding.
3. **Gap check**: Does story B's `writeFiles` include the surface owner file(s)? If **no** and consumer check is yes, the integration is missing.
4. **Generate integration story**: If gap detected, add a new story to the plan:

```
Title: Wire <story-B-feature> into <surface-name>
Agent: quick-fixer
Model: haiku
Trivial: no
Files:
  write: <surface owner file(s)>
  read: <story-B feature file(s)>
Plan: Register <feature> with <surface> so it appears in <surface-name>.
dependsOn: [story-A-id, story-B-id]
```

5. **Dedup**: If an existing open story already wires this pair, skip.

### Epic-planner prompt addition (required)

Every epic-planner invocation must include this block in its prompt:

```
Integration surface check (required — run after drafting all feature stories):
1. Read the "## Integration surfaces" section of CLAUDE.md if present.
2. For each surface listed, check whether any drafted story modifies the surface owner file AND any other story introduces a consumer feature without wiring into the surface.
3. Apply the consumer check heuristic from ORCHESTRATION.md §19.2 — generate automatically when confident, ask when uncertain, skip when clearly infrastructure-only.
4. For each gap found, append an integration story to the plan following the format in ORCHESTRATION.md §19.2.
5. If no "## Integration surfaces" section exists in CLAUDE.md, skip this step.
```

### Main session responsibilities

- After the epic-planner completes, scan the output for stories with `dependsOn` containing two or more other story IDs — these are integration stories. Surface them explicitly to the user in the approval summary:
  > "Integration stories generated: [list titles]. These wire parallel features together and will run after their dependencies merge."
- Integration stories are staged like any other story. No special handling needed beyond the `dependsOn` field.
