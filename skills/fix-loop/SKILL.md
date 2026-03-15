---
name: fix-loop
description: >
  Unified detect-diagnose-fix-revalidate loop. Iteratively validates code in a
  worktree via a strictly gated validation pyramid (compile -> lint -> tests),
  launches fix agents to resolve failures, tracks error hashes for oscillation
  detection, and escalates models (Sonnet -> Opus) when fixes stall. Atomic git
  commits per passing layer enable granular rollback. Returns DONE/NEED_DECISION/BLOCKED.
  Callable by /run-stories, /quickfix, and standalone via "/fix-loop --worktree-path <path>".
args:
  - name: --worktree-path
    type: string
    required: true
    description: >
      Absolute path to an existing worktree containing committed code to validate and fix.
      Fix-loop never creates worktrees — the caller must provide one.
  - name: --max-retries
    type: int
    default: 3
    max: 10
    description: >
      Hard iteration cap. Each detect-diagnose-fix-revalidate cycle counts as one iteration.
      Minimum 1, maximum 10.
  - name: --skip-visual
    type: bool
    default: true
    description: >
      Skip visual regression checks. Always true for MVP (Phase 2 adds visual regression).
  - name: --story-branch
    type: string
    required: false
    description: >
      Branch name for commit messages. If omitted, inferred from
      git -C <worktree-path> branch --show-current.
  - name: --story-id
    type: string
    required: false
    default: standalone
    description: >
      Story ID for structured reporting. Defaults to "standalone" when invoked directly.
  - name: --skip-compile
    type: bool
    default: false
    description: >
      Skip the compile layer of the validation pyramid. Used by run-stories Step 5b
      when compile has already passed in Step 5.0.
  - name: --error-context
    type: string
    required: false
    description: >
      Pre-existing error output to seed the first iteration's diagnosis (e.g., test failure
      output from merge-gate.py). If provided, fix-loop uses this for the first fix attempt
      instead of running the full validation pyramid.
---

# Fix-Loop Skill Invoked

User has requested: `/fix-loop {{args}}`

---

## Output policy

- Do not emit any text between tool calls. Run all tools silently.
- The only user-facing output is the terminal status line (DONE/NEED_DECISION/BLOCKED).
- Iteration progress is logged to stderr for caller visibility but not displayed inline.

---

## Step 0: Parse args and resolve context

1. **Parse arguments** from `{{args}}`:
   - `--worktree-path` (required) -> `WORKTREE_PATH`
   - `--max-retries` (default 3, clamped to 1..10) -> `MAX_RETRIES`
   - `--skip-visual` (default true) -> `SKIP_VISUAL`
   - `--story-branch` (optional) -> `STORY_BRANCH`
   - `--story-id` (default "standalone") -> `STORY_ID`
   - `--skip-compile` (default false) -> `SKIP_COMPILE`
   - `--error-context` (optional) -> `ERROR_CONTEXT`

2. **Validate worktree**:
   ```bash
   git -C $WORKTREE_PATH branch --show-current
   ```
   If this fails, return immediately:
   > `BLOCKED: Worktree does not exist or is not a git repository: $WORKTREE_PATH`

3. **Infer story branch** if not provided:
   ```bash
   STORY_BRANCH=$(git -C $WORKTREE_PATH branch --show-current)
   ```

4. **Verify validation-runner.sh exists**:
   ```bash
   ls ~/.claude/scripts/validation-runner.sh
   ```
   If missing, return immediately:
   > `BLOCKED: scripts/validation-runner.sh not found. Story-795 (validation runner) must be deployed first.`

---

## Step 1: Initial validation (detect phase)

Run the validation pyramid to establish the baseline error state.

If `ERROR_CONTEXT` is provided, skip this step for the first iteration only — use the provided error context as the initial diagnosis and proceed directly to Step 3 (fix phase).

Otherwise, run the validation pyramid:

```bash
VALIDATION_RESULT=$(bash ~/.claude/scripts/validation-runner.sh \
  --project-root $WORKTREE_PATH \
  --layer $( [ "$SKIP_COMPILE" = true ] && echo "lint" || echo "all" ))
```

Parse the JSON result. The validation runner returns:
```json
{
  "project_type": "<detected type>",
  "layers": [
    {"name": "compile", "status": "pass|fail", "output": "<raw output>", "error_count": 0},
    {"name": "lint", "status": "pass|fail", "output": "<raw output>", "error_count": 0},
    {"name": "test", "status": "pass|fail", "output": "<raw output>", "error_count": 0}
  ],
  "overall_status": "pass|fail"
}
```

**If overall_status is "pass"**: No errors found. Return immediately:
> `DONE: All validation layers passed. Iterations: 0. Commits: none. Model: N/A.`

**If overall_status is "fail"**: Identify the first failing layer (strict gating — compile blocks lint, lint blocks tests per decision-113). Proceed to Step 2.

---

## Step 2: Initialize iteration state

Track these values across iterations (transient — logged to stdout, not persisted to run-state.db per decision-76; the caller owns DB writes):

| State variable | Initial value | Description |
|---|---|---|
| `iteration_count` | 0 | Current iteration number |
| `last_error_hash` | null | SHA-256 of combined error output from previous iteration |
| `consecutive_no_progress` | 0 | Increments when error hash unchanged |
| `error_hash_counts` | {} | Maps hash -> occurrence count |
| `error_count_by_layer` | {} | Maps layer name -> error count |
| `current_model` | sonnet | Active model for fix agents |
| `escalated` | false | Whether model has been escalated to Opus |
| `fix_commits` | [] | List of commit hashes from successful fixes |

---

## Step 3: Main loop — detect, diagnose, fix, revalidate

Repeat until termination (Step 5):

### 3a. Detect — identify the failing layer

Run the validation pyramid from the lowest layer upward. Stop at the first failing layer. With `--skip-compile`, start from lint.

```bash
VALIDATION_RESULT=$(bash ~/.claude/scripts/validation-runner.sh \
  --project-root $WORKTREE_PATH \
  --layer $( [ "$SKIP_COMPILE" = true ] && echo "lint" || echo "all" ))
```

Identify `FAILING_LAYER` as the first layer with `status: "fail"`.

### 3b. Diagnose — extract and hash the error

1. **Extract error output** from the failing layer's JSON `output` field.

2. **Truncate** to the last 100 lines to prevent context window exhaustion (per briefing "Gotchas"):
   ```bash
   ERROR_OUTPUT=$(echo "$FAILING_LAYER_OUTPUT" | tail -100)
   ```

3. **Compute error hash**:
   ```bash
   CURRENT_HASH=$(echo "$ERROR_OUTPUT" | shasum -a 256 | cut -d' ' -f1)
   ```

4. **Update state tracking**:
   - Increment `iteration_count`
   - If `CURRENT_HASH == last_error_hash`: increment `consecutive_no_progress`
   - If `CURRENT_HASH != last_error_hash`: reset `consecutive_no_progress` to 0
   - Update `last_error_hash = CURRENT_HASH`
   - Increment `error_hash_counts[CURRENT_HASH]`
   - Update `error_count_by_layer[FAILING_LAYER] = FAILING_LAYER_ERROR_COUNT`

5. **Check for regression**: If `FAILING_LAYER_ERROR_COUNT > previous error_count_by_layer[FAILING_LAYER]` (error count increased after a fix attempt), this is active regression:
   - Roll back the last fix commit: `git -C $WORKTREE_PATH reset --hard HEAD~1`
   - Remove the rolled-back commit hash from `fix_commits`
   - Log: `fix-loop: regression detected in $FAILING_LAYER (errors: $PREVIOUS -> $CURRENT), rolled back`
   - Proceed to circuit breaker check (Step 4), then retry with a different approach

### 3c. Check circuit breakers (Step 4)

See Step 4 below. If any breaker fires, exit the loop.

### 3d. Check model escalation (Step 4b)

See Step 4b below. Escalate if conditions are met.

### 3e. Fix — launch a coder subagent

Launch a background `general-purpose` agent with the fix prompt:

```
You are fixing validation errors for $STORY_ID (iteration $ITERATION_COUNT of $MAX_RETRIES)
$( [ "$current_model" = "opus" ] && echo "You are running on Opus because previous Sonnet attempts did not resolve the issue." || echo "" )

WORKTREE: $WORKTREE_PATH
All reads and writes MUST use paths under this directory.
Story branch: $STORY_BRANCH

## Failing validation layer: $FAILING_LAYER

$ERROR_OUTPUT

## Affected files (extracted from error output)

$AFFECTED_FILES

## Instructions

1. Read the error output carefully. Identify the root cause.
2. Fix ONLY what's broken. Do not refactor working code.
3. If the errors require an architectural decision you cannot make, return NEED_DECISION with the question and two options.
4. Stage and commit your fix (only changed files — never git add -A):
   git -C $WORKTREE_PATH add <changed-files>
   git -C $WORKTREE_PATH commit -m "fix-loop: $FAILING_LAYER fix (iteration $ITERATION_COUNT)"
5. Return "DONE: fix applied" or "NEED_DECISION: <question>" or "BLOCKED: <reason>"

## Tool constraints
Do NOT call any mcp__gemini__* tools.
Do NOT call any pm_* tools.
Focus exclusively on fixing the $FAILING_LAYER errors.
```

**Extract affected files** from the error output by parsing file paths mentioned in compiler/linter/test errors. Include them in the prompt so the fix agent knows where to look.

### 3f. Process fix agent result

Wait for the fix agent to return.

- **DONE**: Record the commit hash from `git -C $WORKTREE_PATH log -1 --format=%H`. Append to `fix_commits`. Proceed to Step 3g (revalidate).
- **NEED_DECISION**: Return immediately to the caller:
  > `NEED_DECISION: $FAILING_LAYER has errors requiring judgment. $AGENT_QUESTION`
  The caller (run-stories or user) resolves the decision and can re-invoke fix-loop.
- **BLOCKED**: Return immediately:
  > `BLOCKED: Fix agent reports unable to resolve $FAILING_LAYER errors. Agent reason: $AGENT_REASON. Suggestion: Review the error output and consider a different approach.`

### 3g. Revalidate

After a successful fix, re-run the validation pyramid from Layer 1 (not from the layer that failed — a compile fix might introduce lint issues):

```bash
VALIDATION_RESULT=$(bash ~/.claude/scripts/validation-runner.sh \
  --project-root $WORKTREE_PATH \
  --layer $( [ "$SKIP_COMPILE" = true ] && echo "lint" || echo "all" ))
```

- **If overall_status is "pass"**: All layers clean. Record the current layer's commit if not already recorded. Proceed to Step 5 (termination gate).
- **If overall_status is "fail"**: Loop back to Step 3a with the new failing layer.

---

## Step 4: Circuit breakers

Three independent breakers. Any one firing triggers termination (per decision-112 and briefing):

| Breaker | Threshold | Condition | Action |
|---------|-----------|-----------|--------|
| Max retries | `MAX_RETRIES` (default 3) | `iteration_count >= MAX_RETRIES` | BLOCKED |
| No progress | 3 consecutive | `consecutive_no_progress >= 3` | Escalate first, then BLOCKED |
| Same error recurrence | 5 total | `error_hash_counts[CURRENT_HASH] >= 5` | BLOCKED |

**Max retries**: Hard stop. Return:
> `BLOCKED: Fix-loop exhausted after $ITERATION_COUNT iterations. Breaker: max-retries. Last failing layer: $FAILING_LAYER. Last error output: $ERROR_OUTPUT_TRUNCATED. Suggestion: Review errors manually or increase --max-retries if the errors are making progress.`

**No progress (3 consecutive)**: If not yet escalated, trigger model escalation (Step 4b) instead of BLOCKED. If already escalated to Opus and 2 more no-progress iterations occur, then BLOCKED:
> `BLOCKED: Fix-loop exhausted after $ITERATION_COUNT iterations. Breaker: no-progress (Opus also stalled). Last failing layer: $FAILING_LAYER. Last error output: $ERROR_OUTPUT_TRUNCATED. Suggestion: This error likely requires architectural changes beyond automated fixing.`

**Same error recurrence (5 total)**: Hard stop regardless of model:
> `BLOCKED: Fix-loop exhausted after $ITERATION_COUNT iterations. Breaker: same-error-recurrence ($CURRENT_HASH seen $COUNT times). Last failing layer: $FAILING_LAYER. Last error output: $ERROR_OUTPUT_TRUNCATED. Suggestion: The same error pattern keeps recurring — this likely needs a different approach entirely.`

---

## Step 4b: Model escalation

Per decision-112 and ORCHESTRATION.md section 2:

- **Default model**: Sonnet (standard coder model)
- **Escalation trigger**: `consecutive_no_progress >= 3` OR error count increases after fix (regression detected)
- **Escalation action**: Set `current_model = opus`, set `escalated = true`, reset `consecutive_no_progress` to 0
- **Opus budget**: Remaining iterations after escalation (`MAX_RETRIES - iteration_count`)
- **Opus stall limit**: If Opus accumulates 2 consecutive no-progress iterations, fire the no-progress breaker as BLOCKED (no further escalation available)

The fix agent prompt includes model awareness:
> "You are running on Opus because previous Sonnet attempts did not resolve the issue."

---

## Step 5: Termination gate

When the validation pyramid reports all layers passing during revalidation (Step 3g), run a final full-suite validation to confirm nothing regressed:

```bash
FINAL_RESULT=$(bash ~/.claude/scripts/validation-runner.sh \
  --project-root $WORKTREE_PATH \
  --layer all)
```

**Full suite means ALL layers** regardless of `--skip-compile` — the termination gate always validates everything.

- **If overall_status is "pass"**: Genuine DONE. Proceed to Step 6.
- **If overall_status is "fail"**: A regression was introduced. Re-enter the loop at Step 3a. This counts toward the iteration cap.

---

## Step 6: Return result

### DONE

All validation layers passed the termination gate.

> `DONE: All validation layers passed. Iterations: $ITERATION_COUNT. Commits: $FIX_COMMITS_LIST. Model: $CURRENT_MODEL.`

Where `$FIX_COMMITS_LIST` is a comma-separated list of commit hashes from `fix_commits`.

### NEED_DECISION

The fix agent encountered errors requiring architectural judgment, or a circuit breaker fired but the remaining errors look like design choices (not bugs).

> `NEED_DECISION: $FAILING_LAYER has errors that require architectural judgment. Remaining errors: $ERROR_COUNT. Error summary: $ERROR_OUTPUT_TRUNCATED. Option A: $SUGGESTION_A. Option B: $SUGGESTION_B.`

### BLOCKED

A circuit breaker fired and the errors are genuine failures, not design choices.

> `BLOCKED: Fix-loop exhausted after $ITERATION_COUNT iterations. Breaker: $BREAKER_NAME. Last failing layer: $FAILING_LAYER. Last error output: $ERROR_OUTPUT_TRUNCATED. Suggestion: $ACTIONABLE_NEXT_STEP.`

---

## Git commit strategy

Per briefing "Patterns > Git atomicity":

- **After each layer passes clean**: The fix agent stages and commits only the files it changed:
  ```bash
  git -C $WORKTREE_PATH add <changed-files>
  git -C $WORKTREE_PATH commit -m "fix-loop: $LAYER clean (iteration $ITERATION_COUNT)"
  ```
  Never `git add -A` — stage only files the fix agent modified.

- **On regression** (error count increases after fix): Roll back the fix:
  ```bash
  git -C $WORKTREE_PATH reset --hard HEAD~1
  ```
  This restores the last clean checkpoint before the bad fix.

- **Commit verification**: After each fix agent returns DONE, verify the commit happened:
  ```bash
  LATEST_COMMIT=$(git -C $WORKTREE_PATH log -1 --format=%H)
  ```
  The fix agent is responsible for staging and committing. The orchestrator verifies, not creates.

- **Commit message pattern**: `fix-loop: compile clean (iteration 2)`, `fix-loop: lint clean (iteration 3)`, `fix-loop: test fix (iteration 4)`

---

## Caller expectations

- The worktree exists and contains committed code (fix-loop never creates worktrees)
- `scripts/validation-runner.sh` exists and implements the `--layer compile|lint|test|all` and `--project-root` interface (provided by story-795)
- Git is available and the worktree is on a valid branch with push access
- The caller handles NEED_DECISION routing (per ORCHESTRATION section 15)
- State is transient — fix-loop does not write to run-state.db or epics.db. The caller owns persistence (per decision-76).
