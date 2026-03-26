# Fix-Loop Integration

Called from [validate.md](validate.md) Step 5.0 when build-verify fails.

## Delegation

```
/fix-loop \
  --worktree-path <worktree-path> \
  --max-retries 3 \
  --story-branch <story-branch> \
  --story-id <story_id>
```

Parse fix-loop's return:
- **DONE**: Proceed to diff gate (Step 5a). Fix-loop's termination gate guarantees all validation layers pass. Do NOT re-run build-verify.
- **NEED_DECISION**: Surface to main session for resolution, then resume fix-loop.
- **BLOCKED**: Mark story BLOCKED. Log friction: `category: blocked, type: automatic, skill: run-stories, detail: "fix-loop exhausted: <reason>"`. Emit blocked event. Skip Steps 5a and 5b.

## For merge gate failures (Step 5b logic_failure/ambiguous)

Delegate with `--skip-compile` (compile already passed in Step 5.0):

```
/fix-loop \
  --worktree-path <worktree-path> \
  --skip-compile \
  --max-retries 3 \
  --story-branch <story-branch> \
  --story-id <story_id> \
  --error-context "<error_output from merge-gate.py>"
```

Same return handling. After DONE, re-run merge-gate.py. If second attempt fails → BLOCKED.
