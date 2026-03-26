# Testing Gates

Called from [single.md](single.md) Step 2.5.

## Step 2.5: Smoke test

```bash
VERIFY_RESULT=$(bash ~/.claude/scripts/build-verify.sh --project-root <worktree-path>)
```

Parse JSON:
- `project_type: "unknown"` + `build_result: "skip"` → `test_result = "skipped (--no-build)"`. Continue.
- `project_type: "unknown"` + `build_result: "fail"` → `test_result = "FAIL"`. Stop.
- `build_result: "pass"` → `test_result = "pass"`. Continue.
- `build_result: "fail"` → `test_result = "FAIL"`. Stop.

## Step 2.5b: Test validation gate (test_files stories only)

Skip if `test_files` empty/null or `story_id` null.

If `test_files` non-empty:
1. Check for test file commits: `git -C <worktree-path> log --oneline --diff-filter=A -- <test_files_glob>`. Warn if none (non-blocking).
2. Run tests: `cd <worktree-path> && <test-command> <test_files>`
3. Pass → `test_result = "pass (spec tests)"`. Continue.
4. Fail → run diagnosis:
   ```bash
   DIAG_RESULT=$(bash ~/.claude/scripts/test-diagnosis.sh \
     --worktree-path <worktree-path> --dev-branch <dev-branch> \
     --test-cmd "<test-command>" --test-files "<test_files>" \
     --story-branch <story-branch>)
   ```
   - `test_invalid` → test fails on dev too — relaunch test agent
   - `code_regression` → test passes on dev, fails on story — fix implementation
   - `inconclusive` → could not determine
   Stop. Do NOT merge.

## Step 2.5c: Coverage delta check (advisory)

Only when test_files non-empty AND spec tests passed. Never blocks.

Detect project type → run coverage:
- **Node/JS:** `npx c8 --reporter=text <test-command> <test_files>`
- **Python:** `python -m pytest --cov=<write_files_dirs> --cov-report=term <test_files>`

Warn on 0% coverage per write_file. Skip silently if coverage command fails.

## Step 2.6: Project test suite gate

```bash
for candidate in "<project-root>/.claude/.claude/tests" "<project-root>/tests" "<project-root>/test"; do
  if [ -d "$candidate" ]; then TEST_DIR="$candidate"; break; fi
done
```

If found: `python3 -m pytest "$TEST_DIR" -x -q --tb=short`. Non-zero → stop. Zero → continue.
If not found: skip silently.
