# Main Session Orchestration Rules

These rules apply to the main Claude Code session only. Spawned agents (coders, reviewers, testers) do not load this file.

---

## 1. ENFORCEMENT

**ZERO-SKIP RULE**: Every code change — no matter how small — that touches >1 file or any protected file MUST go through: story in epics.json → worktree → coder (background) → merge. No exceptions. No "it's just a small fix." If you find yourself thinking "this is too small for the pipeline," that is the exact moment you must use the pipeline.

**Exceptions**: Single-file non-protected fixes may use `/hotfix` (§20). 1-3 file non-protected fixes with known root cause may use `/quickfix` (§21). These are the only valid fast lanes.

**Corollary — epics.json is git-ops-only**: The main session MUST NEVER write `epics.json` directly (no Edit, Write, or inline Bash writes). All mutations go through git-ops agent running `update-epics.sh`. The epic-planner is also read-only.

**Corollary — no pre-reading before delegation**: Do not read source files before launching a coder. The coder reads its own files. Set up the pipeline (story, worktree, prompt) and launch.

---

## 2. AGENT ROLES

**todo-orchestrator** — pure research and classification. Permitted: Glob, Grep, Read, read epics.json, return staging payload. MUST NEVER: run tests, edit/write source files, run builds, commit, push, or open PRs.

**quick-fixer** — coder for clear-scope changes with known root cause, no schema/frame/AI changes.

**architect** — coder for ambiguous scope, schema changes, frame system mutations, new patterns, medium/high risk.

**reviewer** — on-demand code review. Launched only when user requests or `needsReview: true`.

**unit-tester** — on-demand test runner. Launched when story touches testable files or user requests.

**epic-planner** — research and planning agent. Epic mode (background): "plan epic: ...". Planning mode (foreground): orchestrator NEEDS_PLANNING. Permitted: Glob, Grep, Read, WebFetch. MUST NEVER: edit/write source files, run builds/tests, commit/push. Model: Sonnet default; Opus if touches AI tools/Firestore schema.

**git-ops** — executes pipeline scripts via Bash. MUST NEVER: edit source files (except epics.json), read source, make architectural decisions, run builds/tests. Always `run_in_background: true`. Scripts in `.claude/scripts/`: `setup-story.sh`, `diff-gate.sh`, `merge-story.sh`, `merge-queue.sh`, `merge-epic.sh`, `update-epics.sh`. When launched by a skill, reads the skill file and executes only the designated bash steps.

**Agent launch rule**: Coders, reviewer, unit-tester, and git-ops MUST ALWAYS be launched with `run_in_background: true`. Use `Task` tool, never Bash.

**Coders only execute approved plans — they never plan.**

---

## 3. MODEL SELECTION

| Role | Default | Escalation |
|---|---|---|
| Orchestrator | Haiku | Sonnet if architecturally complex |
| Epic-planner | Sonnet | Opus if AI tools/Firestore schema |
| Coder | Orchestrator's recommendation | Opus after 2 BLOCKING round-trips |
| Reviewer | Haiku | Sonnet only if coder ran on Opus |
| Unit-tester | Haiku | Never escalated |

**Recommendation logic**: Haiku for trivial/mechanical; Sonnet for standard; Opus for high-risk or ambiguous.

---

## 4. INCOMING REQUEST → ORCHESTRATION

**A "code-changing prompt"** is any request that would modify, create, or delete project files.

**Route through orchestrator** (foreground, Haiku) when: code-changing prompt arrives, or "todo:" prefix is present.

**Skip orchestrator** when ALL true: (1) affected files known, (2) root cause clear, (3) no new story/epic needed, (4) no schema/frame/AI changes. Go directly to coder.

**Bypass orchestrator entirely** for: pure questions, read-only research, git/commit/PR operations, tasks modifying zero files.

> "non-project tasks" is NOT a bypass. Documentation files in the repo are project files.

**Preprocessing**: Strip filler, extract core intent as one sentence, append story context summary.

**Parallel orchestrators**: Assign story IDs before spawning. Process staging payloads sequentially. Flag same-file conflicts.

**Epic-planned stories**: If plan specifies `writeFiles`, `agent`, `model` per story, stage directly.

**After orchestrator completes**: See `/todo` skill for full procedure. Output types: STAGING_PAYLOAD, NEEDS_PLANNING (→ §4.1), DUPLICATE.

**In-session tracking**: `TaskCreate`/`TaskUpdate` for session state. `epics.json` is the sole persistent file.

### §4.1 — NEEDS_PLANNING handling

When orchestrator returns NEEDS_PLANNING:

1. Group bullets by category (scope, approach, schema, UX).
2. Select model: Opus if Touches includes "AI tools" or "Firestore schema". Sonnet otherwise.
3. Derive `<todo-slug>` (kebab-case, ≤5 words).
4. Launch epic-planner **foreground** with planning prompt (MODE: planning, original task, orchestrator findings, open questions grouped).
5. Wait for planner to complete. Read `$TMPDIR/planning-<todo-slug>.md`.
6. Re-launch orchestrator (Haiku, foreground) with PLANNING_CONTEXT + resolved plan. Must produce STAGING_PAYLOAD.
7. If NEEDS_PLANNING again: surface questions to user directly, stop. Max 1 planning loop.
8. If UNRESOLVABLE: surface reason, stop.
9. If STAGING_PAYLOAD: validate (see `~/.claude/refs/staging-schema.md`), write to epics.json via update-epics.sh.

---

## 5. ORCHESTRATOR OUTPUT FORMAT

Output formats and schemas are defined in `~/.claude/refs/output-formats.md` and `~/.claude/refs/staging-schema.md`.

**Orchestrator responsibilities** (in order):
1. **Dedup check first**: Read `epics.json`. If existing story covers request, return `DUPLICATE: <story-id>`.
2. **Classify**: Explore only files needed to understand the task.
3. **Assign story/epic**: Best-fit in `epics.json`, or propose new.
4. **Decide coder grouping**: Apply §10 decision tree.
5. **Return staging payload**: Write to `$TMPDIR/staging-<todo-slug>.json`.

---

## 6. STAGING PAYLOAD VALIDATION

See `~/.claude/refs/staging-schema.md` for full schema, required fields, and validation rules.

---

## 7. EPIC / STORY / TASK STRUCTURE

Work is organized in three levels:
- **Epic** — a broad theme. Lives in `.claude/epics.json`. States: `active`, `done`, `shipped`.
- **Story** — a scoped deliverable under an epic. Has its own branch and worktree.
- **Task** — a lightweight sub-item within a story. No branch, no worktree. Tracked inline in the story object.

Todos are session-scoped via `TaskCreate`/`TaskList`/`TaskUpdate`.

**epics.json field reference**: See `~/.claude/refs/staging-schema.md` for full field definitions.

**Special agent value — `"manual"`**: Used by `/checklist` for human-executed stories. No worktree, no branch, no coder. Skip all pipeline steps.

**Valid story state transitions**: See `~/.claude/refs/staging-schema.md`.

**Story states**: `draft`, `ready`, `in-progress`, `in-review`, `approved`, `done`, `blocked`, `shipped`.

**Epic states**: `active`, `done`, `shipped`.

**Task sub-items**: Stories may include an optional `tasks` array:
```json
{
  "id": "story-042",
  "tasks": [
    {"id": "t1", "title": "Implement Google OAuth endpoint", "state": "done"},
    {"id": "t2", "title": "Implement GitHub OAuth endpoint", "state": "in-progress"},
    {"id": "t3", "title": "Add OAuth callback handler", "state": "todo"},
    {"id": "t4", "title": "Write integration tests", "state": "blocked", "blockedBy": "t3"}
  ]
}
```
Task states: `todo`, `in-progress`, `done`, `blocked`, `skipped`. Tasks are managed via `/task` skill and `update-epics.sh`.

**Backlog epic**: A persistent pseudo-epic for uncommitted work:
```json
{
  "id": "epic-backlog",
  "title": "Backlog",
  "branch": null,
  "prNumber": null,
  "persistent": true,
  "isBacklog": true,
  "state": "active"
}
```
Auto-created on first use if not present. Stories in backlog are always `draft`. Use `/backlog` to manage, `/defer` to move stories here.

**Ephemeral plans**: Write to `$TMPDIR/plan-<story-id>.md`. Architecture decisions go in CLAUDE.md.

---

## 8. FILL PHASE

After staging payload approval, main session creates `TaskCreate` entries and stops. Stories land in `draft` state. No coder launches until run trigger.

**Safe to /clear when ALL true:**
1. No background agent running
2. No agent result needed to proceed
3. Between stories (not mid-pipeline)

**What survives /clear**: git branches, worktrees, epics.json, all disk state.
**What is lost**: in-session memory, coder task status, agent task list.
**Recovery**: run `/recover` after `/clear` if a story was in-flight.

**Context clearing** (mandatory):
1. After a story merges.
2. After reviewer + unit-tester both launch.
3. After background agent completes with no follow-up.
4. When user asks if safe to clear and no result is needed — confirm yes.
5. After 3+ stories done in session — prompt `/clear`.

**Standardized clearing message**: "Context checkpoint reached [reason]. Run `/clear` to reset the session. All epic and story state is saved in epics.json."

---

## 9. RUN TRIGGER

Coders launch only on explicit "run story-X" (or "run all open stories"). See `/run-story` skill for full procedure.

**Key rules** (policy, not procedure):
- Dependency check: verify `dependsOn` stories are `done`. If not → `ready` (if deps not met, story stays `draft`).
- Pre-flight worktree check: warn on uncommitted changes, don't auto-launch.
- Launch git-ops for `setup-story.sh` (background), wait for completion, then launch coders (background).
- Warn user if session is not in auto-edit mode before launching coder.
- When a story completes (`done`): scan for `draft`/`ready` stories now unblocked, auto-launch them.

---

## 10. CODER GROUPING

**Decision tree**:
```
1. architect → solo group, always
2. quick-fixer, no file overlap with architect → eligible for grouping
3. quick-fixer, file overlap with architect → dependsOn that architect group
4. Two quick-fixers share write-target:
   - Different functions/sections → same group
   - Same function/section → separate groups, second dependsOn first
5. blockedBy → dependsOn propagation
Launch: parallel where no overlap, sequential where dependent.
```

**Task size ceiling**: >5 files or >200 lines → split into sub-tasks.

**Return length caps**: See `~/.claude/refs/output-formats.md`.

**Coder prompt requirements** (every prompt must include):
- Todo descriptions (list every todo explicitly)
- Write-target files and read-only context files (as absolute paths under the worktree)
- Edge cases from codebase research
- **Pitfalls section** — see pitfalls routing table below
- Specific invariants and known gotchas
- **Worktree enforcement block** (copy verbatim, substituting actual paths):
  ```
  WORKTREE: <absolute-worktree-path>
  All file reads and writes MUST use paths under this directory.
  Example: edit <absolute-worktree-path>/src/foo.py — NOT /Users/.../project/src/foo.py
  Before doing anything else, verify: run `git -C <absolute-worktree-path> branch --show-current`
  and confirm it prints `<story-branch>`. If it prints anything else, STOP and report the branch mismatch.
  Do NOT commit or edit files outside this worktree.
  ```

### Pitfalls routing table

Include pitfalls relevant to write-targets from `<project>/.claude/project-orchestration.md`.
If no project-orchestration.md exists, read global refs directly:
- Components using Konva: `~/.claude/refs/pitfalls-konva.md`
- Hooks/async handlers: `~/.claude/refs/pitfalls-react.md`
- Firestore mutations: `~/.claude/refs/pitfalls-firebase.md`
- CSS/styling changes: `~/.claude/refs/pitfalls-css.md`

### Protected files

Read from `<project>/.claude/protected-files.md`. If it doesn't exist, fall back to the hardcoded Konva list:
- `src/components/BoardCanvas.jsx`, `StickyNote.jsx`, `Frame.jsx`, `Shape.jsx`, `LineShape.jsx`, `Cursors.jsx`

If story does NOT edit protected files, include in coder prompt:
> "IMPORTANT: Do NOT edit any protected files listed in project-orchestration.md or the Konva list — scope creep into protected files will block the review."

If story DOES edit a protected file: "The user has explicitly granted permission to edit [filename] for this story."

**Protected testable files**: If write-targets include files in `src/utils/`, `src/hooks/`, or files with `.test.*` counterpart → ask user before launching coder, set `needsTesting: true` on approval.

Coders must only write to write-target files.

---

## 11. PIPELINE EXECUTION

`coder tasks → diff gate → [in-review?] → merge`

### When a coder task completes
- Mark done via `TaskUpdate`. If blocked: stop, report.
- Check dependent tasks — launch if satisfied.
- All tasks done → run diff gate.

### Diff gate (mandatory — git-ops agent, background)

See `/merge-story` skill for the `diff-gate.sh` invocation. Exit codes: 0 = pass, 1 = empty diff, 2 = unexpected files remain.

If reviewer flags untouched files: stale-branch issue. Re-run diff gate, then re-launch reviewer/tester.

### After diff gate

**Trivial stories**: `npm run build` inline → if passes, story → `approved`, merge. Skip reviewer and tester.

**Default**: story → `approved`, proceed to merge immediately.

**needsTesting**: launch unit-tester (background), story → `in-review`.

### Unit-tester (on-demand)

Auto-triggered for: `src/utils/`, `src/hooks/`, permission/admin logic, Firestore paths, AI tool declarations, files with `.test.*` counterpart, or user request.

**Prompt**: writeFiles list + todo descriptions + worktree path. Agent uses `npx vitest related --run <files>`.

**Results**: PASS → `approved`. FAIL trivial → fix inline. FAIL non-trivial → log to test failure log (§17), send back to coder (`in-progress`). Lint errors = FAIL, lint warnings = surface after merge.

### Reviewer (on-demand)

Only on explicit request or `needsReview: true`. Unit-tester must pass first.

**Prompt**: write-target paths + todo descriptions + branch diff. Diff-only mode if ≤75 lines.

**Results**: PASS → `approved`. BLOCKING → fix inline if trivial, else send back to coder (`in-progress`). Log-only warnings → `review-findings.md`.

### Escalation

2 BLOCKING round-trips → escalate coder to Opus (architect stories only, never CSS-only or skill-file-only). If Opus still BLOCKING → story state `blocked`, report to user, leave worktree intact.

**Blocked-story resume**: User resets to `in-progress` via git-ops. Main session asks: re-launch coder with revised instructions, or proceed to diff-gate with current state? Retry budget does NOT reset.

### Simple-fix policy

Trivial mechanical issues (missing import, typo): fix inline. Only when file is not protected AND total change ≤2 files.

### After successful merge
- Story → `done`, check epic auto-close, unblock dependent stories.
- **Architectural findings check**: Scan for novel findings not already in CLAUDE.md. Append silently if novel.
- **Integration surface check**: If merged story introduces new registry/hook/plugin API, update `## Integration surfaces` in project CLAUDE.md.

---

## 12. STORY MERGE SEQUENCE

See `/merge-story` skill for full procedure. Key policy rules:

- **Prefer merge-queue.sh** for multiple stories into same epic (one agent, sequential).
- **merge-story.sh** only for single-story fallback.
- **Draft PR**: `--draft` flag creates draft epic PR. Convert with `gh pr ready` before epic merge.
- **Git rules**: No `git branch -D`. Stories merge through epic branch, never directly to main. No commits without instruction. Never two agents targeting same epic branch simultaneously.
- **Git-ops agents execute skill steps directly** — read the skill file, run only the bash steps, report output.

---

## 13. EPIC MERGE SEQUENCE

See `/merge-epic` skill for full procedure. Key rules:

- Only when user says "merge epic X" or all stories `done`.
- Draft → ready conversion: check `isDraft`, run `gh pr ready` first if needed.
- After merge: "Context checkpoint reached (epic merged). Run `/clear`."
- Auto-close: story → `done` on epic-branch merge, epic → `shipped` when merged to main. All stories → `shipped`.

**Partial merge**: `/merge-epic --partial` merges done stories to main and moves open stories to a continuation epic. See /merge-epic skill.

---

## 14. PARALLEL STORY EXECUTION

Stories run in parallel if no write-target overlap (read-only files don't conflict).

Before launching: check `in-progress`/`in-review` stories for write-file overlap. Overlap → keep in `ready`. No overlap → launch.

When a story completes: scan for `ready` stories now unblocked → auto-launch. Scan `draft` stories with no blockers → notify user.

**Merge ordering**: First to complete merges first. Second rebases. Conflict → pause, report.

**Batch merge window**: Wait 30s after completion. If another finishes, merge both sequentially.

**Rebase conflict protocol**: Parse output → pause that epic branch only → report conflicting files → user resolves manually → re-run merge.

**Sequence decisions** (autonomous): fewest overlapping files → lowest complexity → story ID ascending.

---

## 15. CROSS-SESSION RECOVERY

**Snapshot triggers** — write epics.json at: story merge, state transitions, staging approval, branch/PR assignment.

**§15.1 — update-epics.sh protocol**: See `/run-story` and `/merge-story` skills for invocation patterns. JSON patch format:
```
'{"storyId":"story-X","fields":{"state":"in-progress","branch":"story/slug"}}'
'{"newStory":{...},"epicId":"epic-X"}'
```

**Recovery on session start**: See `/recover` skill.

**What's lost on crash**: only in-session todo progress and coder task status. Git state is ground truth.

**Recovery sources**: epics.json, `git worktree list`, `git branch --list 'story/*' 'epic/*'`.

**State migration**: On read, `update-epics.sh` auto-migrates old state names: `filling`→`draft`, `queued`→`ready`, `running`→`in-progress`, `testing`→`in-review`, `reviewing`→`in-review`, `merging`→`approved`, `closed`→`done`.

---

## 16. BACKGROUND AGENT MANAGEMENT

**Check-in cadence**: Ping every 3 minutes via `TaskOutput` with `block: false`. 2 consecutive no-progress check-ins (6 min) → stop, re-split (≤5 files, ≤200 lines), warn user.

**Error handling**:
- Tests from root worktree. Build from story worktree.
- Trivial failure → unit-tester fixes.
- Non-trivial → re-delegate to coder (story → `in-progress`), re-run reviewer + tester. Max 2 retries → escalate to user.
- Reviewer blocking → pipeline retry rules (story → `in-progress`).
- Plan rejected → re-launch orchestrator with feedback.
- Merge conflict → abort, notify, pause.

---

## 17. LOGGING

**Test failure log**: Append to `/Users/kelsiandrews/gauntlet/week1/.claude/test-failure-log.md` on non-trivial failures. Format:

```
## [ISO date] — [story id] — [one-line title]
**Coder agent**: quick-fixer | architect
**Model**: haiku | sonnet | opus
**Failing test(s)**: [names/files]
**Error**: [message, ~300 chars]
**Root cause category** (one, from unit-tester):
  - [ ] Careless mistake
  - [ ] Scope too narrow
  - [ ] Prompt gap
  - [ ] Framework/API misuse
  - [ ] Test environment issue
**Analysis**: [2-3 sentences from unit-tester]
**Coverage gap**: [yes/no]
**Resolution**: re-delegated | escalated
```

Reject unit-tester output without pre-filled root cause. At 5 entries, surface once: "Worth reviewing for coder prompt patterns."

**Review findings log**: `/Users/kelsiandrews/gauntlet/week1/.claude/review-findings.md`.

---

## 18. TOKEN OPTIMIZATIONS

**Coder prompt size limit**: Under 2000 tokens. Include: todos, paths, pitfalls. Omit: file contents, verbose rationale. Link to CLAUDE.md.

**CSS-only stories**: Haiku, skip testing, skip diff gate restoration. Only `npm run build`.

**Inline parallelism**: Independent bash commands run with `run_in_background: true`.

---

## 19. EPIC PLANNER

### Trigger
"plan epic: ..." or requirements doc. Do not route through todo-orchestrator.

### Launch sequence
1. Derive `<epic-slug>` (kebab-case, ≤5 words).
2. Assign new epic ID from epics.json.
3. Launch epic-planner (background, Sonnet).
4. On completion: read `$TMPDIR/epic-plan-<epic-slug>.md`, validate, present to user.
5. On approval: write stories to epics.json (state: `draft`).

### Prompt requirements
- Epic description, epics.json path (for dedup), project root path, output path
- Dedup instruction, integration surface check block (§19.2)

### Output format
See `~/.claude/refs/output-formats.md` for epic-planner output structure.

### Constraints
- Research only — no writes, builds, tests, commits.
- Dedup first. Group by write-file overlap. Flag testable/protected files.
- Task size ceiling: >5 write-targets or >200 lines → split.

---

## 19.1. EPIC PLANNER — PLANNING MODE

| Aspect | Epic mode (§19) | Planning mode (§19.1) |
|---|---|---|
| Trigger | "plan epic: ..." | Orchestrator NEEDS_PLANNING |
| Launch | Background | Foreground (interactive) |
| Output | Multi-story plan | Single refined plan |

**Behavior**: Research, ask user via AskUserQuestion, propose approaches, batch 2-3 questions. Write to `$TMPDIR/planning-<todo-slug>.md`.

**Output format**: See `~/.claude/refs/output-formats.md`.

**Edge cases**: "you decide" → planner decides, tags `(planner decision)`. Cancel → partial output. Unresolved → partial decisions, orchestrator treats as resolved.

---

## 19.2. EPIC PLANNER — INTEGRATION SURFACE RECONCILIATION

An **integration surface** is a registry, hook, or plugin API that other features must wire into.

Projects declare surfaces in `## Integration surfaces` in their CLAUDE.md (surface name, owner files, registration pattern).

### Detection algorithm (run after all feature stories drafted)

For each story pair (A, B):
1. Does A's writeFiles include a surface owner? → A modifies a surface.
2. Does B introduce a consumer feature? Confident yes → generate story. Confident no (infrastructure) → skip. Uncertain → ask user.
3. Does B's writeFiles include the surface owner? If no and consumer = yes → gap.
4. Generate integration story: wire B into surface, `dependsOn: [A, B]`.
5. Dedup against existing stories.

Every epic-planner prompt must include the integration surface check block. Skip if no `## Integration surfaces` section in CLAUDE.md.

---

## 20. HOTFIX PATH

See `/hotfix` skill for full procedure.

**Qualification** (ALL must pass):
- Exactly 1 file, exists, not protected, not testable
- No schema/frame/AI changes
- No existing story covers this file
- Post-edit: ≤30 lines changed

**Policy**:
- Edits inline on a temp branch (no worktree, no coder agent)
- Guard hook sentinel at `/tmp/hotfix-active-$$` allows the edit
- Auto-squash PR to main
- Frequency cap: warn after 3/session
- Audit: logged to `<project>/.claude/hotfix-log.md`

**Rejected → suggest**: >1 file → `/quickfix`. Protected/testable/schema → `/todo`. >30 lines post-edit → `/quickfix`.

---

## 21. QUICKFIX PATH

See `/quickfix` skill for full procedure.

**Qualification** (ALL must pass):
- 1-3 files, all exist, none protected
- Testable file check: ask user, set `needsTesting` if present
- No schema/frame/AI changes
- No existing story covers these files

**Policy**:
- Uses worktree + background coder (quick-fixer, Haiku)
- Skips orchestrator and epics.json tracking
- Inline diff gate after coder completes
- Optional unit-tester if `needsTesting`
- Auto-squash PR to main
- Frequency cap: warn after 2/session
- Audit: logged to `<project>/.claude/hotfix-log.md`

**Rejected → suggest**: >3 files → `/todo`. Protected/schema → `/todo`.
