# Plan: Restructure Agent Workflow System

## Context

The current agent workflow uses 4 agents (todo-delegator, ui-quickfix, refactor-architect, unit-test-writer) dispatched via Gas Town. The user wants to restructure this into a cleaner system with:
- Renamed agents with refined roles
- Foreground planning (questions relay to user) followed by background execution (user stays unblocked)
- Parallel todos with file-overlap conflict detection
- Gas Town fully replaced by Claude Code's native Task tool
- Coders commit on their feature branches during background execution

---

## Files to Change

### Delete (old agent configs)
- `~/.claude/agents/todo-delegator.md`
- `~/.claude/agents/ui-quickfix.md`
- `~/.claude/agents/refactor-architect.md`
- `~/.claude/agents/unit-test-writer.md`

### Create (new agent configs)
- `~/.claude/agents/todo-orchestrator.md`
- `~/.claude/agents/quick-fixer.md`
- `~/.claude/agents/architect.md`
- `~/.claude/agents/unit-tester.md`

### Edit
- `~/.claude/CLAUDE.md` — rewrite `## Workflow` section (lines 3-14)

### Add to .gitignore
- `.claude/todo-tracking.json` in project repo

---

## 1. todo-orchestrator.md

**Model:** haiku (routing and state management only — doesn't need Sonnet-level reasoning)
**Role:** Orchestrate only. Never implement. Manages the full lifecycle: classify -> plan (foreground) -> conflict check -> execute (background) -> test (background) -> merge -> cleanup.

### Workflow phases:

**Phase 1 — Classify**
- Receive todo(s) from user
- Classify each: quick-fixer vs architect (see decision table below)
- If ambiguous, ask one clarifying question

**Phase 2 — Foreground Planning**
- Create feature branch: `git checkout -b <descriptive-branch-name>`
- Launch chosen coder via Task tool, **foreground** (`run_in_background: false`)
- Coder prompt includes: "PLANNING MODE. Explore codebase, produce a plan listing files to touch and changes per file. Ask clarifying questions. Do NOT implement."
- Questions from the coder relay back through orchestrator to user
- Present the coder's plan to user for approval
- If rejected: re-launch coder foreground with user's feedback

**Phase 3 — Conflict Check**
- Read `.claude/todo-tracking.json`
- Compare plan's file list against all in-progress todos
- If overlap: queue this todo, set `blockedBy`, inform user
- If no overlap: register this todo in tracking file, proceed

**Phase 4 — Background Execution**
- Re-launch coder via Task tool, **background** (`run_in_background: true`)
- Prompt: "EXECUTION MODE. Implement the following approved plan: [plan]. Commit on the feature branch when done. Do not ask questions."

**Phase 5 — Background Testing**
- When coder completes, launch unit-tester in **background**
- Prompt: "Run existing tests, write new tests for changes on branch [branch]. Files changed: [list]. Run build. Fix trivial errors. Report non-trivial failures."
- Skip for pure CSS/styling or trivial config changes

**Phase 6 — Merge & Cleanup**
- `git checkout main && git merge <branch>`
- `git branch -d <branch>`
- Remove todo from tracking file
- Check if any queued todos are now unblocked — if so, resume them from Phase 2

### Agent selection — risk-based, not file-count-based:

**Use quick-fixer when ALL of these are true:**
- Scope is clear — root cause is known or the feature is well-defined
- No Firestore schema changes
- No frame system mutations (childIds/frameId sync, expandAncestors)
- No new architectural patterns or abstractions
- No AI tool changes (toolDeclarations/toolExecutors/system prompt)
- Can be any number of files as long as the work is straightforward (e.g., rename a prop across 8 files, add a CSS class to 5 components)

**Use architect when ANY of these are true:**
- Ambiguous scope — root cause unknown, multiple valid approaches
- Firestore schema changes
- Frame system mutations
- New architectural patterns needed
- AI tool additions or modifications
- Risk: medium or high
- Genuinely novel work with no established pattern in the codebase

**Tie-breaker:** When in doubt, use architect. But lean toward quick-fixer for cost efficiency when the scope is clear.

### Error handling:
- **Test failure (trivial):** unit-tester fixes directly
- **Test failure (non-trivial):** re-delegate to coder with failing test output. Max 2 retries, then escalate to user
- **Build failure:** same as test failure
- **Plan rejected:** re-run foreground planning with user's feedback
- **Merge conflict:** `git merge --abort`, notify user, pause. Do not auto-resolve

---

## 2. quick-fixer.md

**Model:** sonnet
**Based on:** current ui-quickfix.md (preserve all scope constraints and codebase awareness)

**Changes from ui-quickfix:**
- Rename all self-references
- Broaden scope: not just "UI" fixes but any clear-scope task regardless of file count
- Remove hard 1-3 file limit. New constraint: scope must be clear, no architectural decisions, no risky domain mutations (frame system, Firestore schema)
- Add dual-mode behavior:
  - **PLANNING MODE** (foreground): Explore codebase, produce plan listing files/changes/side-effects. Ask clarifying questions. Do NOT implement.
  - **EXECUTION MODE** (background): Implement the approved plan. Commit on the feature branch. Do not ask questions.
- Keep: no refactoring surrounding code, no new dependencies/abstractions, flag out-of-scope when hitting risk boundaries

---

## 3. architect.md

**Model:** opus
**Based on:** current refactor-architect.md (preserve all invariants, decision framework, output standards)

**Changes from refactor-architect:**
- Rename all self-references
- Expanded scope: not just refactors but also complex features, ambiguous tasks, multi-file bug fixes
- Split existing Phase 1/2 into explicit modes:
  - **PLANNING MODE** (foreground): Run full audit. Produce ordered plan with files, sequence, invariants. Ask questions. Do NOT implement.
  - **EXECUTION MODE** (background): Receive approved plan. Implement in sequence. Verify. Commit on feature branch. Do not ask questions.
- Keep: all CollabBoard invariants, atomicity rules, scope discipline, risk ordering

---

## 4. unit-tester.md

**Model:** sonnet
**Based on:** current unit-test-writer.md (preserve all test writing rules, mocking guidelines, source file boundaries)

**Expanded responsibilities:**
1. **Run existing tests** (`npm test`) before writing new ones — report failures caused by new changes
2. **Write new tests** for changed code (existing behavior preserved)
3. **Run build** (`npm run build`) after tests pass
4. **Fix trivial errors** directly: missing imports, missing exports, typos in test files, wrong paths. Criteria: fix is in a test file OR is a single-token fix in source. Non-trivial failures (behavioral bugs, logic errors) → stop and report back with failing test as evidence
5. Source file boundary rules unchanged from current config

---

## 5. Global CLAUDE.md — Workflow Section Rewrite

Replace lines 3-14 with:

```markdown
### Todo orchestration
- When a message starts with "todo:", immediately delegate it to the todo-orchestrator agent — no planning or implementation before delegating
- The todo-orchestrator does NOT implement — it orchestrates. The quick-fixer and architect agents handle all code changes
- Before spawning quick-fixer or architect agents, warn the user if the session is not in auto-edit mode

### Foreground planning, background execution
- The orchestrator launches the chosen coder (quick-fixer or architect) in FOREGROUND for the planning phase
- During foreground planning, the coder asks questions which funnel back through the orchestrator to the user
- The orchestrator presents the plan and waits for explicit approval
- Once approved, the orchestrator re-launches the coder in BACKGROUND for execution
- After execution completes, the orchestrator launches the unit-tester in BACKGROUND
- The user stays unblocked during coding and testing phases

### Agent selection (risk-based, not file-count-based)
- quick-fixer: clear scope, known root cause, no schema/frame/AI changes, any number of files if work is straightforward
- architect: ambiguous scope, schema changes, frame system mutations, new patterns, medium/high risk

### Parallel todos with conflict checking
- Multiple todos can run simultaneously on separate feature branches
- Before launching execution, the orchestrator checks .claude/todo-tracking.json for file overlap with in-progress todos
- If overlap: queue the conflicting todo and inform the user
- When a todo completes and merges: remove from tracking, check if queued todos are now unblocked

### TaskCompleted handling
- When a background coder agent completes, re-launch the todo-orchestrator to handle the testing phase
- When a background unit-tester completes, re-launch the todo-orchestrator to handle the merge phase

### Branch and merge rules
- Descriptive feature branch names (e.g. "feature/sticky-note-text-formatting" not "feature/text-formatting")
- Before merging, unit-tester must have passed (skip for pure CSS/styling or trivial config)
- After merging, delete feature branch with git branch -d
- Never commit without explicit instruction
- Never push to remote unless explicitly asked

### Error handling
- Test/build failure (trivial): unit-tester fixes directly
- Test/build failure (non-trivial): orchestrator re-delegates to coder with failing output. Max 2 retries, then escalate
- Plan rejected: re-run foreground planning with user feedback
- Merge conflict: abort merge, notify user, pause

### Batch sequencing
- Independent single-file fixes first, moderate multi-file second, complex/high-risk last
- Recommend one approach and explain why, don't list all options
```

---

## 6. Conflict Tracking File

**Path:** `.claude/todo-tracking.json` (gitignored)

```json
{
  "todos": [
    {
      "id": "todo-<timestamp>",
      "description": "short description",
      "branch": "feature/branch-name",
      "agent": "quick-fixer|architect",
      "status": "planning|executing|testing|merging|queued",
      "blockedBy": null,
      "files": ["src/components/Foo.jsx", "src/hooks/useFoo.js"],
      "startedAt": "ISO timestamp"
    }
  ]
}
```

**Lifecycle:** Created during planning (Phase 2) -> updated through each phase -> removed after merge. On removal, scan for queued todos whose blockedBy matches the removed id.

---

## 7. Execution Sequence for the Handoff Flow

```
USER: "todo: Fix sticky note blur behavior"

MAIN AGENT:
  1. Recognizes "todo:" prefix
  2. Launches todo-orchestrator (foreground)

TODO-ORCHESTRATOR (foreground):
  3. Classifies: 1-2 files, clear root cause -> quick-fixer
  4. Creates branch: git checkout -b fix/sticky-note-blur
  5. Launches quick-fixer (FOREGROUND) in planning mode
  6. Quick-fixer asks questions -> relay to user -> user answers
  7. Quick-fixer returns plan
  8. Orchestrator presents plan to user -> user approves
  9. Checks todo-tracking.json for conflicts -> none found
  10. Registers todo in tracking file
  11. Launches quick-fixer (BACKGROUND) in execution mode
  12. Reports to user: "Approved. Running in background. You're unblocked."

QUICK-FIXER (background):
  13. Implements plan, commits on branch
  14. Completes -> main agent notified

MAIN AGENT:
  15. Re-launches todo-orchestrator for testing phase

TODO-ORCHESTRATOR:
  16. Launches unit-tester (BACKGROUND)

UNIT-TESTER (background):
  17. Runs tests, writes new tests, runs build
  18. Completes -> main agent notified

MAIN AGENT:
  19. Re-launches todo-orchestrator for merge phase

TODO-ORCHESTRATOR:
  20. Merges branch, deletes branch, removes from tracking
  21. Reports: "fix/sticky-note-blur merged. All tests pass."
```

---

## Implementation Order

1. Create `~/.claude/agents/todo-orchestrator.md`
2. Create `~/.claude/agents/quick-fixer.md`
3. Create `~/.claude/agents/architect.md`
4. Create `~/.claude/agents/unit-tester.md`
5. Edit `~/.claude/CLAUDE.md` — rewrite Workflow section
6. Add `.claude/todo-tracking.json` to project `.gitignore`
7. Delete old agent files (todo-delegator.md, ui-quickfix.md, refactor-architect.md, unit-test-writer.md)

---

## Verification

1. Start a new Claude Code session
2. Send: `todo: Fix a small UI bug` — verify orchestrator launches, selects quick-fixer, runs foreground planning, relays questions, presents plan
3. Approve the plan — verify background execution launches, user is unblocked
4. Wait for completion — verify unit-tester chains, merge happens, branch is deleted
5. Send a second todo while the first is executing — verify conflict check works
6. Send a complex todo — verify architect is selected instead of quick-fixer
