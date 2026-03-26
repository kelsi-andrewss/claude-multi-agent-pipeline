# Merge Gate

Called from [validate.md](validate.md) Step 5b.

## Stories WITH test_files

For each DONE story with test_files where both coder and test agent returned DONE:

1. **Run merge gate:**
   ```bash
   GATE_RESULT=$(python3 ~/.claude/scripts/merge-gate.py \
     --merge-candidate "<project-root>/.claude/worktrees/merge-candidate/<story-slug>" \
     --story-branch <story-branch> \
     --test-branch <story-branch>--test \
     --dev-branch <dev-branch> \
     --test-cmd "<detected-test-command>" \
     --test-files "<comma-separated test_files>" \
     --coverage --mutation)
   ```

2. **`test_passed: true`** → merge test commits into code worktree (step 5 below).

3. **`test_passed: false`** → retry by classification:

   | classification | Attribution | Action |
   |---|---|---|
   | `compile_error` | Test agent — wrong interface | Re-launch test agent with error output + actual exports. Max 1 retry. |
   | `logic_failure` | Coder — implementation wrong | Delegate to `/fix-loop` via [fix-integration.md](fix-integration.md). |
   | `ambiguous` | Coder (default) | Same as logic_failure. |
   | `low_coverage` | Coder — insufficient coverage | Delegate to `/fix-loop`. |
   | `low_mutation_score` | Coder — weak test kill ratio | Delegate to `/fix-loop`. |

4. **After retry**: re-run merge-gate.py. Second failure → BLOCKED.

5. **On pass** — merge test commits into code worktree:
   ```bash
   git -C <code-worktree> fetch origin <story-branch>--test
   git -C <code-worktree> checkout origin/<story-branch>--test -- <test_files>
   git -C <code-worktree> add <test_files>
   git -C <code-worktree> commit -m "<story_id>: add spec tests (validated)"
   git -C <code-worktree> push origin <story-branch>
   ```

6. **Cleanup** merge-candidate worktree (always): `git worktree remove --force "$MERGE_CANDIDATE"`

## Stories WITHOUT test_files

1. Check for test infrastructure (jest.config, pytest.ini, _test.go, etc.). If none → skip testing, proceed to merge.
2. Launch unit-tester agent (background, Sonnet) to write tests from acceptance criteria.
3. Commit tests to `<story-branch>--test`, push.
4. Run merge-gate.py — same as above.
5. Same retry logic by classification.
6. On pass — merge test commits into code worktree, same as above.

Opt-out: `--no-coverage` or `--no-mutation` to skip those checks.
