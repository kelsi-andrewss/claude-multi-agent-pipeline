# Main Session Orchestration

Rules for the main Claude Code session. Spawned agents load `refs/agent-constraints.md` instead.

---

## 1. ROLES

| Role | Responsibility | Boundary |
|---|---|---|
| **Claude** (main) | Plan files, launch coders, merge | DB writes: `plan_file` + `state` via `pm_update_story` only. Worktree creation is coder agents' job. |
| **Gemini** | Research + planning via `pm_*` / `gemini_*` MCP | Writes to `epics.db` |
| **Coders** | Execute plan files in worktrees | Never plan. Always background. `ui_codegen: true` → `ui-coder` |

**Frontend split**: Gemini owns visual design (layout, properties, interactions). Claude owns architecture (state, data flow, APIs). Coders treat Gemini's design as constraint, Claude's architecture as guide.

---

## 2. DECISION GATE

These stay in the main session — **never delegate to coders**. If a coder encounters any of these, it MUST return `NEED_DECISION: <question>` — never resolve inline.

- **User-facing decisions**: anything that changes what the user sees or how the system behaves from their perspective
- **Scope changes**: adding/removing stories, changing write targets, splitting/merging work
- **State transitions**: marking stories done, blocked, or skipped
- **Stubs and placeholders**: never decide what a stub contains without explicit user input
- **Pipeline routing**: which skill to use, whether to skip a phase, whether to run in foreground vs background

When in doubt, return `NEED_DECISION`. False positives are cheap; unauthorized decisions erode trust.

---

## 3. PIPELINE

```
QUEUE → PLAN → DRAFT → RUN → MERGE
```

Entry point: `/ship`. Routes internally — quickfix for ≤5 files, full pipeline otherwise.

---

## 4. DELEGATION

Delegate by phase, not by MCP call. One subagent per pipeline phase.

| Phase | Agent type |
|---|---|
| Resolution | Coder (quick-fixer / architect / ui-coder) |
| Critique | Reviewer |
| Merge | Git-ops |

Subagent return contract: `DONE: <summary>`, `NEED_DECISION: <question>`, or `BLOCKED: <reason>`.

Model selection policy: [`refs/orch-memory.md`](refs/orch-memory.md) §Model Selection.

---

## 5. BRANCHES

`main` is production. Only `dev` merges to main. Everything else merges to `dev`.

Small changes (≤5 files, skip epics.db): `quickfix/<slug>` or `hotfix/<slug>`. Max 3/session.

---

## 6. STORY STRUCTURE

- **Epic** — broad theme. States: `active` → `done` → `shipped`.
- **Story** — scoped deliverable, own branch/worktree. Needs `plan_file` to run.
- **Task** — sub-item, no branch.

Split when a story has multiple independent failure modes. No shared write targets with in-progress stories.

---

## 7. MERGE FLOW

```
DONE → diff gate → test → review → merge
```

2 BLOCKING reviews → escalate coder to Opus. Still BLOCKING → mark `blocked`. Auto-launch unblocked stories after merge.

---

## 8. RECOVERY

Known failure modes and what to do:

| Failure | Symptom | Recovery |
|---|---|---|
| Story completes without decision | Coder returns `DONE` but made a choice that needed user input | Revert the unauthorized decision, re-run with explicit NEED_DECISION gate |
| Pipeline dies mid-run | Story stuck in `running`, no agent active | `/recover` to reconcile DB vs worktree state, re-launch |
| Coder makes unauthorized decision | Stub content, scope change, or skip decided by coder | Reject the merge, surface the decision to user, re-run |
| Worktree/DB mismatch | Worktree exists but DB says `done`, or vice versa | `/recover` detects and fixes; manual: check `git worktree list` vs DB state |
| Coder output diverges from plan | Diff shows files or changes not in plan's write targets | Reject merge, surface diff to user, re-run with tighter plan |
| Merge conflict between stories | Second story's merge hits conflicts from first story's merge | Pause second merge, surface conflict to user, rebase or re-run |

If a failure isn't in this table, investigate before acting — don't delete state to make the error go away.

---

> Procedures: [`refs/orch-procedures.md`](refs/orch-procedures.md) — commits, corrections, context management, self-critique
> Agent constraints: [`refs/agent-constraints.md`](refs/agent-constraints.md)
> Memory: [`refs/orch-memory.md`](refs/orch-memory.md) — trust calibration, distillation, OpenMemory budgets
> Plan critique: [`refs/orch-critique-checklist.md`](refs/orch-critique-checklist.md)
