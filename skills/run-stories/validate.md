# Validate Phase

Wait for all background agents to complete. Collect results and run validation gates.

## Result collection

For each completed agent, write usage to `/tmp/coder-effort-<story-id>.json`:
```json
{"story_id": "...", "model": "...", "total_tokens": "...", "tool_uses": "...", "duration_ms": "..."}
```

### NEED_DECISION handling
1. Parse blocker description and options.
2. Log friction: category `decision`, type automatic, skill `run-stories`.
3. Claude picks best option with one-line reasoning.
4. Create decision review artifact:
   ```bash
   mkdir -p decisions/reviews/
   ```
   Write to `decisions/reviews/decision-${N}.md` per ORCHESTRATION §7 format.
5. Emit: `bash ~/.claude/scripts/emit-event.sh "decision.made" ...`
6. Resume agent: "Decision: Option X. Continue from where you left off."
7. DONE → merge list. BLOCKED → blocked list.

### NEED_RESEARCH handling
1. Parse question and context.
2. Dispatch: `web_search` with the specific question.
3. Resume agent with result.
4. Does NOT count toward BLOCKING escalation counter.

## Step 5.0: Fix-loop auto-review

After each coder returns DONE (before diff gate):
```bash
VERIFY_RESULT=$(bash ~/.claude/scripts/build-verify.sh --project-root <worktree-path>)
```

- **PASS or SKIP**: proceed to diff gate.
- **FAIL**: delegate to [fix-integration.md](fix-integration.md).

If coder returned BLOCKED, skip entirely.

**Dual-exit gate**: Work complete when BOTH: coder returned DONE AND (build-verify PASS/SKIP OR fix-loop DONE). Stories with `--no-build` opt-out satisfy on condition 1 alone.

## Step 5a: Diff gate

```bash
DIFF_RESULT=$(bash ~/.claude/scripts/diff-gate.sh --worktree-path <worktree-path> --dev-branch <dev-branch> --write-files "<comma-separated>" --blocking --test-files "<comma-separated test_files>")
```

- `blocked: true` with `test_file_violations` → BLOCKED: "Test file scope violation"
- `blocked: true` without → BLOCKED: "Scope violation: unexpected files"
- `blocked: false` with `unexpected_files` → warning, continue
- `status: "error"` → warning, continue

## Step 5b: Per-story testing

Read [merge-gate.md](merge-gate.md) for the full merge gate procedure (stories with and without test_files).

## Step 5c: Merge

For each story that passes validation, invoke `/merge-worktree` (pass all validated story IDs space-separated).

After merge, update decision review artifacts: `Status: pending` → `Status: success` with commit hash. BLOCKED stories → `Status: failure`.
