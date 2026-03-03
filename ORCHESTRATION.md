# Main Session Orchestration Rules

These rules govern the main Claude Code session. Spawned agents (coders, reviewers, testers) do not load this file.

---

## 1. ROLES

**Claude** — main session agent. Calls Gemini for research and planning, analyzes results, writes plan files, manages worktrees, launches coders, merges. The only DB write Claude makes directly is linking a plan file to a story via `pm_update_story(plan_file=...)`.

**Gemini** — large-context research and planning engine, accessed via MCP tools (`pm_*`, `gemini_*`). Handles: epic/story/task creation, codebase research, bug finding, audits, and generating implementation plans. Writes to `epics.db` via its own MCP tools.

**Coders** (`quick-fixer`, `architect`) — implement approved plan files inside isolated git worktrees. Never plan. Always launched as background agents.

**Reviewer** — on-demand code review. Only when user requests or `needs_review: true`.

**Unit-tester** — on-demand test runner. Only when story touches testable files or user requests.

**Git-ops** — executes git operations via Bash. Never edits source files or makes architectural decisions. Always `run_in_background: true`.

**Agent launch rule**: Coders, reviewer, unit-tester, and git-ops MUST always be launched with `run_in_background: true` via the `Task` tool.

**Coders only execute approved plan files — they never plan.**

---

## 2. MODEL SELECTION

| Role | Default | Escalation |
|---|---|---|
| Claude (main) | Sonnet | Opus if user requests or high-risk |
| Coder | Haiku | Sonnet for standard; Opus after 2 BLOCKING round-trips |
| Reviewer | Haiku | Sonnet only if coder ran on Opus |
| Unit-tester | Haiku | Never escalated |

---

## 3. WORKFLOW

The full lifecycle from idea to merged code:

```
1. QUEUE     /todo "thing to build"        → appends to .claude/todos.md
2. PLAN      /todo plan                    → Gemini reads queue, writes epics/stories/tasks to epics.db
3. DRAFT     /draft-plan story-NNN         → Gemini researches + plans (Claude does NOT pre-explore) → Claude critiques + writes plan file
4. RUN       auto-triggered after draft (see §5)                      → Claude launches coders in isolated worktrees
5. MERGE     /merge-worktree story-NNN     → Claude merges worktree branch into dev branch
```

**Queue** is a scratchpad. Nothing is committed to the DB until `/todo plan` runs.

**Draft** is the critical gate. Gemini provides the large-context research and initial plan; Claude independently analyzes it, identifies gaps or risks, and writes the final plan file. Claude's plan file is what coders execute — not Gemini's raw output.

**Run** is auto-triggered after `/draft-plan` completes (see §5). No confirmation gate — coders launch immediately.

**One-shot alternative:**
```
/ship "title" features...     → pm_ship creates epic+stories → Claude writes plans → /run-stories executes
```

---

## 4. DB ACCESS RULES

`epics.db` lives at `~/.claude/.claude/epics.db`. CLI at `~/.claude/.claude/scripts/epics-cli.sh`.

- **Gemini** writes epics, stories, and tasks via `pm_*` MCP tools.
- **Claude** writes only `plan_file` via `pm_update_story(plan_file=...)`. No other direct DB mutations.
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

If Claude finds significant issues, it surfaces them to the user before writing the plan file. Minor gaps are incorporated silently into the plan file.

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

---

## 9. MERGE SEQUENCE

After a coder completes:

0. Before merging: verify story state is `done` or `approved`. If `in-progress`, wait for coder to finish or ask user to confirm forcing the merge.
1. Diff gate: confirm only expected files changed.
2. If `needs_testing`: launch unit-tester (background). PASS → `approved`. FAIL non-trivial → back to coder.
3. If `needs_review`: launch reviewer (background, after tester passes). BLOCKING → back to coder.
4. On `approved`: run `/merge-worktree story-NNN`.
5. Story → `done`. Check if epic can auto-close. Unblock dependent stories.
6. Auto-launch: immediately run `/run-stories` for any stories that became unblocked and are `ready` with a plan file. Do NOT ask for confirmation — just print a summary of what's launching and invoke the skill.

**Escalation**: 2 BLOCKING round-trips → escalate coder to Opus (architect stories only). Opus still BLOCKING → story → `blocked`, report to user.

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
Calls `pm_ship` (server-side orchestration) for epic/story/task creation and Gemini planning.
Claude writes plan files and controls coder execution — Gemini never codes.

**Accepts:** inline feature lists, PRD files, existing plan files, epic IDs.

**What it skips:**
- Confirmation gates (auto-commits)
- Clarification questions (defaults: agent=architect)
- Claude's §6 critique (user explicitly chose speed)

**When to use:** Greenfield projects, MVPs, prototypes.
**When NOT to use:** Production code, protected files, high-risk changes.

**Recovery:** `pm_ship` creates epic + stories in epics.db. Resume with `/ship epic-NNN`,
or fall back to `/draft-plan` + `/run-stories` for individual stories.
