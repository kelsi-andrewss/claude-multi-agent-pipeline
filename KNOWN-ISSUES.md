# Claude Code Known Issues

## [2026-02-21] todo-orchestrator agent ignores pipeline delegation instructions

**Symptom**: When the `todo-orchestrator` agent type is given a prompt that says "run quick-fixer → reviewer → unit-tester in sequence", it ignores the delegation instruction and runs the full pipeline inline itself — editing files, running tests, committing, and opening PRs directly.

**Root cause**: The `todo-orchestrator` agent type has built-in behavior that overrides prompt-level instructions. It treats pipeline execution prompts as a signal to do the work itself rather than spawn subagents.

**Workaround**: Never use `todo-orchestrator` to run a full pipeline. The main session must directly spawn each stage as a separate `Task` call:
- Coder stage → `subagent_type: "quick-fixer"` or `"architect"`
- Review stage → `subagent_type: "reviewer"`
- Test stage → `subagent_type: "unit-tester"`

Chain them in sequence from the main session, each with `run_in_background: true`.

**Documented in**: `~/.claude/ORCHESTRATION.md` → "Pipeline execution — main session responsibility" section

---

## [2026-02-21] gh pr merge flag inconsistency

**Symptom**: `ORCHESTRATION.md` line 318 specifies `gh pr merge --merge` but actual story merges have been using `--squash --delete-branch`. The flag in the doc is wrong.

**Correct behavior**: Use `gh pr merge --squash --delete-branch` — squash keeps history clean, delete-branch avoids manual remote branch cleanup.

**Status**: RESOLVED — ORCHESTRATION.md §13 already uses `--squash --delete-branch`. Fixed 2026-02-23.
