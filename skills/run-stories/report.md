# Report Phase

Print final summary after all batches complete.

## Format

```
Run complete.  Dev branch: dev

story-001  batch 0   my-feature--fix-auth-flow      DONE    abc1234   tests: pass    verify: pass
story-003  batch 0   my-feature--update-dashboard   DONE    def5678   tests: skip    verify: pass
story-002  batch 1   my-feature--refactor-handlers  DONE    ghi9012   tests: pass    verify: pass
story-005  batch 0   my-feature--add-search         BLOCKED                          verify: pass

Batch verification:
  batch 0: PASS
  batch 1: PASS

Skipped (validation):
  story-006: state is 'done' — already complete

Deferred (dependency not yet merged):
  story-007: runs after story-005 merges

Blocked during execution:
  story-005: plan file references missing utility function `buildSearchIndex`
  story-008: Watchdog killed: stuck (Read x7) + 68% budget elapsed
```

## Batch verification failure example

```
story-001  batch 0   my-feature--fix-auth         DONE      abc1234  tests: pass  verify: pass
story-003  batch 0   my-feature--update-dash       DONE      def5678  tests: skip  verify: pass
story-002  batch 1   my-feature--refactor-hdl      BLOCKED                         verify: batch 0 failed

Batch verification:
  batch 0: FAIL — src/index.ts(42): Cannot find module './newService'
  batch 1: BLOCKED (batch 0 failed)
```

Columns: `batch` = parallel wave number. `verify` = batch verification result.

If all stories complete: "All stories executed successfully."
If any BLOCKED: list with reasons. Never stop other stories due to one failure.
If all BLOCKED/skipped: stop after summary.

After printing, run cleanup:
```bash
python3 ~/.claude/scripts/cleanup_run_state.py --session-id "$SESSION_ID"
```
