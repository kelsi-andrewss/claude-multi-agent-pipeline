# Main Session Orchestration Rules

These rules apply to the main Claude Code session only. Spawned agents (coders, reviewers, testers) do not load this file.

## Todo orchestrator agent rules
**CRITICAL — the todo-orchestrator agent MUST NEVER:**
- Run tests (no `npm test`, `vitest`, `jest`, or any test command)
- Edit or write any source files
- Run builds (`npm run build`)
- Commit files
- Push branches or open PRs

The orchestrator is a **pure research and classification agent**. Its only permitted actions are: reading files (Glob, Grep, Read), reading epics.json, and returning a staging payload. All implementation, testing, reviewing, and merging is delegated to specialist agents (quick-fixer, architect, reviewer, unit-tester).

## Todo orchestration
- For code-changing prompts, spawn the todo-orchestrator agent (foreground, `model: "haiku"`) for research and classification.
- **SKIP the orchestrator** when ALL of the following are true: (1) the affected file(s) are already known, (2) the root cause is clear, (3) no new story/epic needs to be created, (4) no schema/frame/AI tool changes. In these cases go directly to coder. Still create a `TaskCreate` entry afterward for tracking.
- A "code-changing prompt" is any request that would modify, create, or delete project files. Bypass the orchestrator for: pure questions or explanations, read-only research (Glob/Grep only), git/commit/PR operations, and non-project tasks
- The "todo:" prefix is an explicit trigger and always routes through the orchestrator, even if the intent is ambiguous
- **Orchestrators MAY run in parallel.** Multiple orchestrators can run simultaneously since they only read files and return staging payloads — they never write files. The main session creates `TaskCreate` entries from orchestrator results. Safeguards: (1) assign story IDs before spawning by pre-incrementing a counter in memory — never let two orchestrators pick the same ID; (2) process all staging payloads sequentially after all orchestrators complete; (3) if two orchestrators target the same file in their write lists, note the conflict and sequence those stories. The orchestrator MAY also be spawned while coders, reviewers, or unit-testers are running in the background.
- Before spawning the orchestrator, preprocess the user message: strip filler, extract the core intent as one sentence, and append a one-line summary of the current story context (what's already queued in the target story, if any). Pass this condensed prompt to the orchestrator — not the raw user message.
- After todo-orchestrator completes, the main session validates the staging payload, presents the summary to the user, and creates `TaskCreate` entries only after approval. No coder launches until a run trigger.
- Before spawning quick-fixer or architect agents, warn the user if the session is not in auto-edit mode
- The orchestrator recommends the coder model based on task complexity: `haiku` for trivial/mechanical, `sonnet` for standard, `opus` for high-risk or ambiguous. The main session passes that model to the coder. The unit-tester always runs on Haiku.
- The main session decides what model to run the orchestrator on (default: Haiku). Bump to Sonnet or Opus when the task is known to be architecturally complex before research even begins.
- **Default models by role**: orchestrator → Haiku, coder → orchestrator's recommendation, reviewer → Haiku (Sonnet only if coder was Opus), unit-tester → Haiku. Opus only on escalation.

## In-session tracking

During a session, use `TaskCreate` to register todos and `TaskUpdate` to track progress. Do not write to any JSON tracking file on every state change. Recovery snapshots handle cross-session persistence (see "Cross-session recovery" section). `epics.json` is the sole persistent file — written only on story merge and updated with simplified fields.

## Agent execution rules
**CRITICAL**: Coders (quick-fixer, architect), the reviewer, and the unit-tester MUST ALWAYS be launched with `run_in_background: true`. No exceptions. Never use foreground mode for any of these agents.

**Check-in cadence**: Ping long-running background agents every 3 minutes via `TaskOutput` with `block: false`. If an agent shows no new tool uses after 2 consecutive check-ins (6 minutes), stop it and re-split the task into smaller pieces. Do not wait longer.

**Unit-tester and reviewer launch rules (non-trivial stories)**:
1. Unit-tester launches FIRST. Do not launch the reviewer until the tester passes.
2. Both use `run_in_background: true`.
3. Do NOT launch either one inline or via Bash. Always use the `Task` tool with `subagent_type: "unit-tester"` and `subagent_type: "reviewer"`.
4. After launching the tester, wait for its result before doing anything else for that story.
5. If the tester fails with a trivial issue (missing import, typo), fix it inline immediately — do not spawn a coder agent. Re-run the tester.
6. Only after tester PASS: launch the reviewer. Wait for its result.
7. If the reviewer finds a trivial issue, fix it inline — do not spawn a coder agent. Re-run the tester then reviewer.

- Coders only execute approved plans — they never plan.
- The user stays unblocked during coding, review, and testing phases.

## Orchestrator output format (strict template)

The orchestrator must return its output in this exact structure. The main session must not accept output that deviates from it.

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

STAGING_PAYLOAD
<valid JSON object — see schema below>
```

**Coder groups format** (orchestrator decides grouping, not main session):
```
Group 1 [architect|quick-fixer]: todo-xxx — <one-line rationale>
Group 2 [quick-fixer]: todo-yyy, todo-zzz — <one-line rationale>
Sequential after group 1: todo-aaa — <reason for dependency>
```

**Staging payload schema:**
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
    "needsReview": false
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

## Orchestrator responsibilities

The orchestrator is the source of truth for classification. It must, in order:

1. **Dedup check first**: Read `epics.json` before any codebase exploration. If an existing story already covers this request, return `DUPLICATE: <story-id>` and stop — skip all further exploration.
2. **Classify**: Explore only the files needed to understand the task. No broad surveys.
3. **Assign story/epic**: Find the best-fit story in `epics.json`. If none fits, propose a new story (and epic if needed) in the staging payload.
4. **Decide coder grouping**: Apply the grouping decision tree using codebase knowledge from step 2. Flag write-target files vs. read-only context files per group.
5. **Return the staging payload**: Structured JSON + human summary. Do not write any files.

## Staging payload validation

Before updating `epics.json`, validate the staging payload:
- `storyUpdate` has all required fields: `id`, `epicId`, `title`, `state`, `branch`, `writeFiles`, `needsTesting`, `needsReview`
- `state` is a valid value (`filling`, `running`, `closed`, etc.)
- `writeFiles` is a non-empty array
- If `epicUpdate` is present: all required fields present (`id`, `title`, `branch`, `prNumber`, `persistent`)
- If validation fails: surface the error to the user, do not write, do not re-launch orchestrator automatically

## Epic / Story structure

Work is organized in two persistent levels:
- **Epic** — a broad theme. Lives in `.claude/epics.json`.
- **Story** — a scoped deliverable under an epic. Has its own branch and worktree. Stories are the unit of execution.

Todos are session-scoped — tracked via `TaskCreate`/`TaskList`/`TaskUpdate` during the session, not persisted to disk.

### epics.json field reference

Each epic entry: `id`, `title`, `branch` (string, null until first story runs), `prNumber` (number, null until PR created), `persistent` (boolean, default true — branch not auto-deleted).

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
  "needsReview": false
}
```

### Valid story state transitions
```
filling → running         (run trigger)
running → merging         (all coders done, default path — no tester or reviewer)
running → testing         (all coders done, story flagged needsTesting or user requests)
testing → merging         (unit-tester PASS)
testing → running         (unit-tester FAILED — send back to coder)
running → reviewing       (user explicitly requests review, or story flagged needsReview)
reviewing → running       (reviewer BLOCKING — send back to coder)
reviewing → merging       (reviewer PASS)
merging → closed          (merged into epic branch)
any → blocked             (Opus escalation still blocking — see Escalation section)
```
Note: `reviewing` state is only entered on-demand (user request or `needsReview: true`). Normal pipeline goes `running → testing → merging` without ever entering `reviewing`.

### Epic feature branch lifecycle

**Epic branch creation**:
- When the first story in an epic transitions to `running`, create the epic feature branch: `epic/<epic-slug>` off `origin/main`
- Do NOT create a PR immediately — wait until the first story merges into the epic branch (so the PR has content)
- Store `branch` on the epic in `epics.json`

**Story worktree creation**:
- Before creating a story worktree, the epic branch pulls from main: `git fetch origin main && git rebase origin/main` (on the epic branch)
- Story worktrees branch off the epic branch (not main): `git worktree add .claude/worktrees/<story-branch> -b <story-branch> epic/<epic-slug>`
- Symlinks same as before (.env, node_modules)

**Story merge → epic branch (no PR)**:
- Stories merge into the epic branch directly — no PR needed for story → epic
- Sequence:
  1. `git -C <story-worktree> rebase epic/<epic-slug>`
  2. `git checkout epic/<epic-slug>`
  3. `git merge --ff-only story/<slug>` (or `--no-ff` if ff not possible)
  4. `git push origin epic/<epic-slug>`
  5. Clean up story worktree + branch
  6. Update the epic PR body if it exists (append merged story title)

**Epic PR to main**:
- Created after the first story merges into the epic branch
- Title: epic title, body: list of merged stories
- Updated (body appended) as each subsequent story merges
- Squash-merged to main when user says "merge epic" or all stories are closed
- Use `--delete-branch=false` because epic branches persist

**Cross-epic sync**:
- After an epic merges to main, all other active epic branches fetch + rebase onto `origin/main` before their next story worktree is created
- Enforced at story worktree creation time (the "pull before branching" rule above covers it)
- No automatic trigger needed

**Epic branch persistence**:
- Epic branches are NOT deleted after merge to main — they persist until the user explicitly says "delete epic branch X"
- This allows reopening the epic for follow-up stories

### Ephemeral plans

Plans are ephemeral — write to `$TMPDIR/plan-<story-id>.md`. Do not persist plans in `~/.claude/plans/`. Architecture decisions and findings that survive sessions go in `CLAUDE.md` (project) or `~/.claude/CLAUDE.md` (global). Plans are working documents, not records.

### Fill phase (default behavior)
After the main session creates `TaskCreate` entries from the approved staging payload, it stops — no coder launches. The user adds more todos until ready to trigger.

**Context clearing**: Clear the context window (`/clear`) to save tokens. Clear at these points — these are mandatory, not discretionary:
1. **After a story merges** — after completing all merge cleanup steps and before auto-launching any queued story, run `/clear`.
2. **After reviewer + unit-tester both launch** — once both are running in background, run `/clear`. They will wake the session when done.
3. **After any background agent completes with no immediate follow-up action** — if reporting a result to the user and no coder/reviewer/tester launch is needed right now, run `/clear`.
4. **When a background agent is running and the user asks if it's a good time to clear** — if no result is immediately needed, confirm yes and suggest `/clear`.
Never clear if a background agent is currently running and its result is needed to proceed.

### Run trigger
Coders only launch when you explicitly say "run story-X" (or "run all open stories"). Main session then:

1. Reads the story from `epics.json`, creates `TaskCreate` entries for each todo if not already created
2. **Assigns the story branch** if `branch` is null: generates `story/<slug>`, writes to `epics.json`
3. **Creates/updates the epic branch** if needed:
   - If epic has no `branch`: create `epic/<epic-slug>` from `origin/main`, push to origin, store `branch` on the epic in `epics.json`
   - If epic already has a `branch`: `git fetch origin main && git checkout epic/<epic-slug> && git rebase origin/main && git push origin epic/<epic-slug>`
4. **Creates the story worktree from the epic branch** — idempotent:
   - If worktree already exists AND story `state` is `running`: run `git -C <worktree> status --porcelain` first. If the worktree has uncommitted changes and no coder tasks are in-progress, a previous agent likely crashed — warn the user and do NOT launch until they confirm (stash, discard, or resume). If some tasks are done and others pending, the worktree is in a valid partial state — proceed normally. After the dirty check, launch only pending tasks
   - If worktree exists but state is not `running`: warn user, do not proceed
   - Otherwise: check if branch exists (`git branch --list <branch>`), delete if so (`git branch -d <branch>` or `-D` if unmerged), then `git worktree add .claude/worktrees/<branch> -b <branch> epic/<epic-slug>`, then symlink: `ln -sf <project-root>/.env .claude/worktrees/<branch>/.env && ln -sf <project-root>/node_modules .claude/worktrees/<branch>/node_modules`
5. Launches coder tasks in BACKGROUND; tracks status via `TaskUpdate`
6. Updates story `state` to `running` in `epics.json`

### Coder grouping decision tree
Applied by the orchestrator at classification time. Coder groups are tracked via `TaskCreate` during the session.

```
For each todo in the story:

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

Launch order (encoded as dependsOn relationships):
  - Architect groups with no overlap: parallel (dependsOn: null)
  - Quick-fixer groups with no architect overlap: parallel with architects (dependsOn: null)
  - Quick-fixer groups overlapping an architect: dependsOn that architect group
```

**Task size ceiling**: If a coder group's write-targets span >5 files or the estimated change is >200 lines, split it into 2+ atomic sub-tasks. Two 5-minute tasks are faster and more recoverable than one 15-minute task. Each sub-task gets its own `TaskCreate` entry and can run sequentially within the same worktree.

Coder prompts must include:
- Todo descriptions — **list every todo explicitly**. If a group has multiple todos, number them. The coder must confirm all are implemented before committing.
- Write-target files (these will be modified), read-only context files (read but do not modify)
- **Edge cases extracted from codebase research** — e.g. "GroupPage's root onDrop passes the real groupId, not null — guard against this", "buffered local state needs a useEffect resync when the prop updates externally". Pull these from the orchestrator's exploration output before writing the prompt. This is the highest-leverage way to reduce reviewer round-trips.
- **A "Pitfalls" section** — required for every non-trivial coder prompt. List specific gotchas relevant to the files being changed. Common pitfalls to always check and include when applicable:
  - Konva Groups return `0` from `.width()` and `.height()` — use `.getClientRect()` for live bounding box
  - `onDragMove` / async callbacks must read state from refs (`.current`), not closed-over props
  - If adding `:focus-visible` CSS, ensure the outline color **contrasts** with the button background (don't use the same color token as background)
  - Firestore `batch.update` throws if the document is also being deleted in the same batch — use `batch.set({merge:true})` or guard with a deleteSet check
  - Frame `childIds` and child `frameId` must always be updated atomically in the same `writeBatch`
  - Protected files scope — if story does NOT touch a protected file, say so explicitly in the prompt
- Specific invariants to preserve (e.g. "do not break the existing X behavior", "GroupPage is already correct — do not touch it")
- Known gotchas in the affected files
- **For new object types**: explicitly include the CLAUDE.md 6-step checklist (rendering component, creation handler, toolbar button, AI tool declaration, AI executor, sort order in BoardCanvas)
- **For CSS alignment fixes**: explicitly state "verify the parent container has `display: flex` before adding `margin-left: auto` or similar flex-child properties"
- **For any new props/params**: "Do not destructure or accept props/params you don't use in the component/function body. Verify every new prop is referenced."
- **For any new `async` event handler**: "Capture all React state and props you need into local `const` variables before the first `await`. React state can be nulled or updated by other handlers (e.g. `onClose`) between an `await` suspension and resume — never read state after an `await`."

Coders must only write to write-target files.

**Protected Konva files — MUST be included in every coder prompt**:
The following files are protected and must NEVER be edited unless explicit user permission is stated in the current session:
- `src/components/BoardCanvas.jsx`
- `src/components/StickyNote.jsx`
- `src/components/Frame.jsx`
- `src/components/Shape.jsx`
- `src/components/LineShape.jsx`
- `src/components/Cursors.jsx`

When writing a coder prompt, if the story does NOT require editing one of these files, include this line verbatim:
> "IMPORTANT: Do NOT edit any of these protected files: BoardCanvas.jsx, StickyNote.jsx, Frame.jsx, Shape.jsx, LineShape.jsx, Cursors.jsx — even if you think an edit would improve them. Scope creep into protected files will block the review."

If the story DOES require editing a protected file, include: "The user has explicitly granted permission to edit [filename] for this story."

**CWD mismatch warning**: Coder agents launched from the main session have their CWD set to the debug worktree, NOT the project root or story worktree. Always provide absolute file paths in coder prompts. Include this explicit note in every coder prompt: "Use absolute paths only — your CWD may not match the target directory. Do not use Glob/Grep without specifying the full absolute path."

### Story pipeline (shared reviewer + tester)
All coders write to the same story branch. Once all coder tasks are done:

**Trivial stories** (all todos marked trivial): skip reviewer entirely. Run `npm run build` inline via Bash (no agent spawn). If build passes → proceed to PR/merge.

**Non-trivial stories**: Unit-tester and reviewer are both skipped by default. After the diff gate passes, go straight to PR/merge.

**Unit-tester (on-demand only)**: Only run the unit-tester when the story touches any of:
- `src/utils/` (frameUtils, connectorUtils, colorUtils, slugUtils, etc.)
- `src/hooks/` (useBoard, useUndoStack, auth hooks)
- Permission / admin logic
- Firestore read/write paths (useBoard mutations, batchWriteAndDelete)
- AI tool declarations or executors
- Any file that already has a `.test.js` / `.test.jsx` counterpart

To trigger: user says "test this story", or the story is auto-flagged `needsTesting: true` by the orchestrator when any write-target file matches the above list.

**Protected testable files**: The files that auto-trigger testing are also protected from coder edits by default. If a story's write-targets include any file in `src/utils/`, `src/hooks/`, or any file with a `.test.*` counterpart, the main session MUST stop before launching the coder and ask the user:
> "This story needs to edit [filename(s)], which are protected testable files. Allow edits? (This will set `needsTesting: true` on the story.)"

Only proceed after explicit user approval. On approval: set `needsTesting: true` on the story in epics.json. Do NOT modify `.claude/settings.local.json` — the exception lives on the story only. If the user declines, remove those files from the write-targets and revise the plan.

**Unit-tester prompt (when triggered)**:
- Write-target file paths + all todo descriptions.
- **Runs existing tests + build only. Do NOT write new tests unless the story is a feature (not a fix).** For fixes: `npm test` + `npm run build` only.
- Tester FAIL → fix inline if trivial (missing import, off-by-one, typo in test); otherwise send back to coder with failure output. Re-run diff gate, then re-run tester.
- Tester PASS → proceed to PR/merge.

**Reviewer (on-demand only)**: The reviewer is NOT launched automatically. Only run it when the user explicitly requests a review, or when the story touches: frame system mutations, Firestore schema changes, AI tool logic, or complex multi-system interactions. To trigger: user says "review this story" or the story is flagged `needsReview: true` in epics.json.

**Reviewer prompt (when triggered)**:
- Write-target file paths from all groups + all todo descriptions + **the story branch diff** (`git diff main...<branch> -- <write-target files>`). Pass the diff inline in the prompt.
  - **Diff-only mode** (first pass): if the diff is ≤75 lines, instruct the reviewer to review from the diff only — do not open any full files. If context outside the diff is needed to make a call, flag it as `needs-context: <filename>` rather than BLOCKING. The main session then re-runs the reviewer with those specific files included. If the diff is >75 lines, reviewer opens full files as normal.
  - On send-back: include which coder task each finding belongs to, so only the affected task re-runs. Include **the coder's fix diff** (`git diff <pre-fix SHA>..<post-fix SHA> -- <affected files>`) in the send-back prompt so the reviewer focuses on what changed, not the full file.
  - **Reviewer checklist — shared pattern completeness**: enumerate all instances of a pattern before marking PASS.
- Reviewer PASS → proceed to PR/merge.
- Reviewer BLOCKING → fix inline if trivial; otherwise send back to coder. Re-run diff gate → tester → reviewer after fix.

**Per-story independence**: When multiple stories run in parallel, each story's pipeline is fully independent. Each story runs its own tester-then-reviewer sequence at its own pace. Never gate one story's next step on another story's state.

**Simple-fix policy**: If the reviewer or tester finds a trivial mechanical issue (missing import, wrong constant, typo), fix it inline as a Bash/Edit call rather than delegating back to a coder agent. This avoids a full agent round-trip for a one-line fix.

**Worktree threshold**: Any change — regardless of how simple it appears — that touches **more than 2 files** OR **any protected Konva file** (BoardCanvas.jsx, StickyNote.jsx, Frame.jsx, Shape.jsx, LineShape.jsx, Cursors.jsx) MUST go through the full worktree pipeline: create worktree → coder → diff gate → unit-tester → reviewer → PR → merge. Never commit these changes directly to main. The simple-fix policy only applies to single-file, non-protected changes.

- Single PR per story — PR body includes: story title, todo list with one-line descriptions, affected files
- Story `state` to `merging` → `closed` on merge

### Escalation: Opus still blocking
If reviewer retries reach 2 AND the Opus coder attempt still produces a BLOCKING review:
1. Set story `state` to `blocked`
2. Report all findings to the user — do not proceed to merge
3. Leave the worktree intact for manual resolution
The story stays `blocked` until the user intervenes. `blocked` → `running` is a valid manual reset.

### Auto-close rules
- Story closes on successful PR merge
- Epic closes when all its stories are `closed`

## Cross-session recovery

**Snapshot triggers** — write `epics.json` at exactly two points:
1. After each story merges into the epic branch (already in the merge flow)
2. On story state transitions that matter cross-session (`filling` → `running`, `running` → `closed`)

**Snapshot content** — the simplified `epics.json` with current story states. Todos are session-scoped and not persisted.

**Recovery on session start** — when a new session starts and `epics.json` shows a story in `running` state:
1. Check if the story worktree still exists (`git worktree list`)
2. Check if there are uncommitted changes in the worktree
3. Report to the user: "Story X was in-flight when the last session ended. Worktree at .claude/worktrees/story/X [has uncommitted changes | is clean]. Resume or discard?"
4. Do not auto-resume — wait for user decision

**What's lost on crash (no exit hook)**: only the in-session todo progress and current coder task status. The last merge snapshot tells the next session which stories are closed. Git state (branches, worktrees, commits) is the ground truth for anything in-flight.

**Recovery sources** (no stop hook changes needed):
1. `epics.json` on disk (updated on each story merge and state transition)
2. `git worktree list` (shows in-flight story worktrees)
3. `git branch --list 'story/*' 'epic/*'` (shows active branches)

The next session reconstructs state from these three sources.

## Pipeline execution — main session responsibility
**CRITICAL**: The todo-orchestrator agent MUST NEVER be used to run a full pipeline. It is a read-only classification agent — it cannot write source files, run tests, commit, push, or open PRs. If the main session passes a "branch, implement, review, test, and merge" prompt to todo-orchestrator, the orchestrator will attempt to do all of that itself inline, violating every constraint. **NEVER do this.**

The main session MUST directly spawn each pipeline stage as separate background agents:

Pipeline stage → agent type to spawn:
- Coder → `quick-fixer` or `architect` (per orchestrator recommendation)
- Reviewer → `reviewer`
- Unit-tester → `unit-tester`

The main session chains: wait for all coder tasks → diff gate (inline) → merge into epic branch. Each stage is a separate `Task` call with `run_in_background: true`. The todo-orchestrator is ONLY used for the classification/staging step — never for execution.

## Pipeline order
`coder tasks → diff gate (inline) → merge into epic branch`
- Unit-tester on-demand only: auto-triggered when write-targets include `src/utils/`, `src/hooks/`, permission/admin/Firestore/AI paths, or any file with a `.test.*` counterpart. Otherwise skipped.
- Reviewer on-demand only: user must explicitly request it, or story must be flagged `needsReview: true`.

Result handling: see **Story pipeline** section above.

**Model matching**: Reviewer defaults to Haiku. Use Sonnet only if the most complex coder ran on Opus. Unit-tester always Haiku.

**Reviewer send-back budget**: 2 round-trips. At 2: escalate coder to Opus, run once more. If still blocking: story → `blocked`.

**Reviewer: WARNINGS** — two categories:
- **Simple-fix warnings** (clear root cause, mechanical): route back to coder. Do NOT increment retry count. Re-run both reviewer + unit-tester after fix.
- **Log-only warnings** (judgment calls, trade-offs): append to `/Users/kelsiandrews/gauntlet/week1/.claude/review-findings.md` (always absolute path).
- Surface summary after merge: "X warnings logged to .claude/review-findings.md"

**Reviewer learnings threshold**: If reviewer output contains `⚠ reviewer-learnings.md has N entries`, surface it to the user after pipeline completes using this exact format:
> ⚠️ **reviewer-learnings.md has N entries — consider reviewing and promoting patterns.**

## Stale story detection
When checking on background agents, if any story has been in `running`, `reviewing`, or `testing` for more than 6 minutes (2 missed check-ins at 3-minute cadence) without progress:
- Stop the stalled agent
- Re-split the task into smaller pieces (each ≤5 files, ≤200 lines)
- Warn: "Story [id] ([title]) agent stalled after 6 minutes. Splitting and re-launching."

## Agent selection (risk-based)
- quick-fixer: clear scope, known root cause, no schema/frame/AI changes
- architect: ambiguous scope, schema changes, frame system mutations, new patterns, medium/high risk, bugs spanning multiple interacting systems
- Follow the orchestrator's recommendation. Only override to architect if the user explicitly asks or a new ambiguity surfaces after orchestration.

## Worktrees
- Every story gets its own worktree, branched off the epic branch at run trigger (not during fill).
- Worktree path: `.claude/worktrees/<story-branch>/`
- Coder, reviewer, and unit-tester all operate inside the worktree — never the main working tree.
- On successful merge into epic branch: follow the story merge sequence in the **Branch and merge rules** section below.
- On merge conflict: leave worktree intact, report path to user.
- Never reuse a worktree across stories.

## Parallel story execution
Stories can run in parallel if they share no write-target files.

Before launching a story, check `epics.json` for any story currently `running`, `reviewing`, or `testing`:
- **No write-file overlap**: launch the new story immediately in parallel. Each story runs in its own worktree on its own branch — no coordination needed.
- **Write-file overlap**: queue the story. When the blocking story merges, auto-launch the queued story immediately — do not ask the user.
- When a story completes (merges into epic branch), scan for any stories in `filling` state whose dependencies are resolved — set `state` to `running`, create the worktree, and launch its first coder task in BACKGROUND. Notify the user that the queued story has auto-started.

**Merge ordering for same-epic stories**: Stories within the same epic all merge into the same epic branch. First story to complete merges first. Second story rebases onto the updated epic branch before merging. If rebase produces a conflict → pause, report to user.

**Batch merge window**: After a story completes, wait 10 seconds before merging into the epic branch. If another story completes in that window, merge both sequentially in a single operation. This avoids redundant rebase/push cycles.

**Sequence decisions**: When multiple stories conflict and must run sequentially, the main session decides the order autonomously using this priority: (1) fewest overlapping files first, (2) lowest complexity first (quick-fixer before architect), (3) story id ascending as tiebreaker. Never ask the user to choose the sequence.

**Overlap check**: compare the union of `writeFiles` across stories. Read-only files do not create a conflict.

## TaskCompleted handling
When a coder task completes:
- Mark it done via `TaskUpdate`
- If blocked: stop, report to user
- Check for dependent tasks — if dependencies satisfied, launch them
- When all coder tasks for a story are done:
  - **MANDATORY inline diff gate** (run as a single Bash call — not an agent, takes ~5 seconds):
    ```bash
    git -C <worktree> fetch origin
    git -C <worktree> rebase epic/<epic-slug>   # rebase onto epic branch, not main
    git -C <worktree> diff epic/<epic-slug>..HEAD --name-only
    ```
    Compare the output against the story's `writeFiles` list. For every file that appears in the diff but is NOT in `writeFiles`:
    ```bash
    git -C <worktree> checkout epic/<epic-slug> -- <extra-file>
    ```
    If any files were restored, commit them in a single commit: `"fix: restore out-of-scope files to epic branch state"`. Then re-run the diff and confirm it matches `writeFiles` exactly. **Do not launch reviewer or tester until this gate passes.**
  - **Trivial stories**: run `npm run build` inline → if passes, story → `testing` → `merging`
  - **Default (no testing flag)**: story → `merging` immediately, handle merge
  - **needsTesting stories**: launch unit-tester (background, wait for result), story → `testing`
    - Tester FAIL → fix inline if trivial (missing import, typo), otherwise send back to coder; re-run tester
    - Tester PASS → story `state` to `merging`, handle merge
- When reviewer completes (on-demand only):
  - Reviewer PASS → story `state` to `merging`, handle merge
  - Reviewer BLOCKING → story `state` to `running`, re-launch owning coder task with findings; re-run tester then reviewer after fix
  - Reviewer simple-fix warnings → fix inline, re-run reviewer
- Successful merge (into epic branch) → story `state` to `closed` in `epics.json`, check epic auto-close, unblock dependent stories
  - **Architectural findings check**: After story merge, scan the coder's output, reviewer warnings, and test failure log for novel architectural findings (unexpected API behaviors, new invariants, patterns that should be documented). Check if finding is already in CLAUDE.md (Grep for key terms). If novel: append to the appropriate section (Common Gotchas, Architecture Rules, or Key Conventions). Format: one bullet, concise, actionable. Do NOT ask the user — append silently. Trigger conditions: coder hit an unexpected API behavior, reviewer flagged a documentable pattern, test failure root cause was "framework/API misuse" or "scope too narrow", or a new protected file/invariant was discovered. Only project-level findings go in CLAUDE.md — session-specific learnings go in tracking.

## Branch and merge rules

### Story merge (into epic branch — no PR)
- Story branches: `story/<slug>` (e.g. `story/subgroup-dnd-and-search-ux`)
- Stories merge into the epic branch directly — no PR required for story → epic
- **Diff gate before merge**: The mandatory inline diff gate (described in TaskCompleted handling) must pass before reviewer/tester/merge. This is not optional and is not delegated to an agent — it runs inline as a Bash call.
- **Stale branch rebase rule**: When a reviewer flags that the diff shows changes to files the story did NOT touch, do NOT treat it as a code bug. Instead: run the diff gate inline (fetch, rebase onto epic branch, restore out-of-scope files, commit, verify), then re-launch both reviewer and unit-tester.
- Before merging: unit-tester must have passed (skip if all todos trivial)

**Story merge sequence** (run inline, not as agent):
```bash
# Rebase story onto epic branch
git -C <story-worktree> fetch origin
git -C <story-worktree> rebase epic/<epic-slug>
# Merge into epic branch
git checkout epic/<epic-slug>
git merge --ff-only story/<slug>   # use --no-ff if ff not possible
git push origin epic/<epic-slug>
# Cleanup
git worktree remove .claude/worktrees/story/<slug> --force
git worktree prune
git branch -d story/<slug>
```

After the first story merges into an epic branch, create the epic PR:
```bash
gh pr create --base main --head epic/<epic-slug> --title "<epic title>" --body "## Stories merged\n- <story title>"
```
Store the PR number on the epic in `epics.json` as `prNumber`. On subsequent story merges, update the PR body:
```bash
gh pr edit <prNumber> --body "<updated body with new story>"
```

### Epic merge (into main — user-triggered)
Epic merges to main only when the user says "merge epic X" or all stories in the epic are `closed`.
```bash
git fetch origin main
git checkout epic/<epic-slug>
git rebase origin/main   # resolve conflicts if any
git push origin epic/<epic-slug> --force-with-lease
gh pr merge <prNumber> --squash --delete-branch=false
git fetch origin main
git update-ref refs/heads/main origin/main
```
Note: `--delete-branch=false` because epic branches persist until explicitly deleted by the user.

### General rules
- **Never `git branch -D`** — force-delete is forbidden. If `-d` fails, advance the local ref with `git update-ref` first, then retry `-d`.
- Never merge story branches directly to main — stories go through the epic branch
- Never commit without explicit instruction

## Error handling
- Tests run from the **root worktree** always. Build (`npm run build`) runs from the story worktree.
- Test/build failure (trivial): unit-tester fixes directly
- Test/build failure (non-trivial): re-delegate to the owning coder task with failing output → re-run both reviewer + unit-tester in parallel. Max 2 retries, then escalate to user.
- Reviewer blocking: handled by pipeline retry rules — do not re-run orchestrator
- Plan rejected: re-launch orchestrator in foreground with user's feedback
- Merge conflict: abort, notify user, pause

## Test failure logging
Whenever the unit-tester reports a non-trivial failure (i.e. one that requires re-delegation to the coder rather than an inline fix), append an entry to the **absolute path** of the test failure log before re-delegating. The log lives at the project root (not inside a worktree): `/Users/kelsiandrews/gauntlet/week1/.claude/test-failure-log.md`. Always use the full absolute path — never a relative path — to avoid writing to the wrong worktree directory. Use this format:

```
## [ISO date] — [story id] — [one-line failure title]
**Coder agent**: quick-fixer | architect
**Model**: haiku | sonnet | opus
**Failing test(s)**: [test name(s) or file(s)]
**Error**: [exact error message or assertion failure, truncated to ~300 chars]
**Root cause category**:
  - [ ] Careless mistake (wrong variable, off-by-one, typo)
  - [ ] Scope too narrow (coder didn't read enough context before writing)
  - [ ] Prompt gap (plan was missing a critical detail)
  - [ ] Framework/API misuse (wrong Konva/Firebase/React API)
  - [ ] Test environment issue (mock gap, timing, missing setup)
**Analysis**: [2-3 sentences: what went wrong and why]
**Resolution**: re-delegated to coder | escalated to user
```

**Threshold reminder**: Once `.claude/test-failure-log.md` reaches **5 entries**, surface this message to the user after the next successful pipeline completion:
> "test-failure-log.md has N entries. Worth reviewing to identify coder prompt patterns that need improvement."

Do not surface the reminder more than once per session after the threshold is crossed.

## Token and time optimizations

**Epic-planned stories**: If the epic plan document specifies `writeFiles`, `agent`, and `model` per story, the main session stages stories directly — no orchestrator needed. The orchestrator is only required when a new todo arrives without a pre-planned story assignment.

**Coder prompt size limit**: Keep coder prompts under 2000 tokens. Include: todo descriptions, write-target paths, read-only paths, and a Pitfalls section. Omit: full file contents (the coder reads them), architecture explanations the coder can find in CLAUDE.md, and verbose rationale. Link to CLAUDE.md sections by name instead of repeating them.

**CSS-only stories** (no JS/JSX changes): always use Haiku, skip testing, skip diff gate file restoration (CSS files can't break tests). Only run `npm run build` to verify no syntax errors.

**Inline parallelism**: Bash commands that don't gate the next write (build verification, lint, diff checks, git status) must run with `run_in_background: true` when there is other independent work to do in parallel. Never block on a build while the next file read is already known. Read the background result only when the next decision requires it.
