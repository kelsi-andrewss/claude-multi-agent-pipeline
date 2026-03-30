# Session Procedures

Operational procedures for the main Claude Code session. Loaded on demand via Tier 2.

---

## DB Access

Gemini writes via `pm_*` tools. Claude writes `plan_file` and `state` only, via `pm_update_story`. No raw SQL except through `scripts/epics-cli.sh`.

---

## Plan Critique

Claude independently reviews Gemini's output before writing plan files. Full checklist: `refs/orch-critique-checklist.md`. On material disagreement, surface both perspectives to user.

---

## Merge & Escalation

Flow: NEED_DECISION → resolve and resume. NEED_RESEARCH → Gemini web_search, resume. DONE → diff gate → test → review → merge. Auto-launch unblocked stories after merge.

Escalation: 2 BLOCKING → Opus. Still BLOCKING → `blocked`. Log every terminal transition to `merge_outcomes`.

Details: `skills/merge-worktree/SKILL.md`.

---

## Hotfix & Quickfix

**Hotfix**: single file, ≤30 lines, direct edit on `hotfix/<slug>` branch. Max 3/session.
**Quickfix**: 1-5 files via `/ship --quickfix` on `quickfix/<slug>` branch. Max 3/session.

Both skip epics.db. Never commit directly to main or dev.

---

## Protected Files

Read from `<project>/.claude/protected-files.md`. Touching protected files requires user confirmation.

---

## Context Management

Safe to `/clear` when: no background agents running, no results pending, between stories.

Before `/clear`: write `session-handoff.md`, store summary to OpenMemory. Details: `refs/orch-context-mgmt.md`.

---

## Memory

Two layers: **eager** (CLAUDE.md, rendered-prefs.md — session start) and **lazy** (OpenMemory — on demand).

Three persistence surfaces: correction_groups DB, rendered-prefs.md sidecar, OpenMemory. Details: `refs/orch-memory.md`.

---

## Decisions

Record via `pm_add_decision`, shadow to OpenMemory. Check `pm_list_decisions` before proposing approaches.

---

## Self-critique

Run `/critique` before presenting significant work (2+ file plans, new files/skills/hooks, complex logic).

---

## Commits

Stage files by name, never `git add -A`. No secrets in code or commit messages. Run linter before committing.

---

## Corrections

Log before proceeding: `bash ~/.claude/scripts/log-correction.sh "[ISO date] — [message]: [context]"`. On "log" or "log that", capture immediately.

---

## Compaction

Preserve: current task + state, modified file paths, test commands run, NEED_DECISION/BLOCKED status, active skill pipeline step.
