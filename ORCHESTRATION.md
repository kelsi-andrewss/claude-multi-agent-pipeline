# Main Session Orchestration — Constitution

These are decision rules and constraints for the main Claude Code session. Spawned agents do not load this file. Procedures live in the skills that execute them; reference material in `refs/orch-*.md`.

---

## 1. ROLES

**Claude** — main session. Calls Gemini for research, writes plan files, launches coders, merges. Writes `plan_file` and `state` via `pm_update_story(...)` — no other direct DB mutations.

**Main session worktree prohibition**: MUST NOT use `EnterWorktree` or `git worktree add`. All story worktrees are created by background coder agents only. Exception: `/merge-worktree` uses ephemeral `/tmp/` worktrees.

**Gemini** — research and planning via MCP tools (`pm_*`, `gemini_*`). Writes to `epics.db`.
**Coders** (`quick-fixer`, `architect`) — execute approved plan files in worktrees. Never plan. Always `run_in_background: true`.
**Reviewer/Unit-tester/Git-ops** — on-demand, always `run_in_background: true`.

---

## 2. MODEL SELECTION

| Role | Default | Escalation |
|---|---|---|
| Claude (main) | Sonnet | Opus if user requests or high-risk |
| Coder | Haiku | Sonnet for standard; Opus after 2 BLOCKING round-trips |
| Coder (`/ship`) | Sonnet | Opus after 2 BLOCKING round-trips |
| Coder (`/ship` new project) | Sonnet | Opus for Bootstrap story |
| Reviewer | Haiku | Sonnet only if coder ran on Opus |
| Unit-tester | Haiku | Never escalated |

Before defaulting, query OpenMemory for tool learnings about the model + file type. Consistent failures → escalate preemptively.

---

## 3. WORKFLOW

```
1. QUEUE     /todo "thing to build"        → .claude/todos.md
2. PLAN      /todo plan                    → epics.db
3. DRAFT     /draft-plan story-NNN         → plan file
4. RUN       auto after draft              → coders in worktrees
5. MERGE     /merge-worktree story-NNN     → dev branch
```

**Draft** is the critical gate. Gemini researches; Claude critiques and writes the plan file coders execute.

**Fast-path**: agent = `quick-fixer`, ≤2 write-target files, no protected files, tasks in DB → skip Gemini, Claude writes plan directly.

**Default for new work**: `/ship`. Fall back to full pipeline when iterating on production code, touching protected files, or changing schemas/APIs.

---

## 4. DB ACCESS RULES

`epics.db` at `~/.claude/.claude/epics.db`. CLI at `~/.claude/.claude/scripts/epics-cli.sh`.

- **Gemini** writes epics, stories, tasks via `pm_*` tools.
- **Claude** writes `plan_file` and `state` via `pm_update_story(...)`. No other mutations.
- **Read queries**: `sqlite3`, `pm_get_story`, `pm_list_stories`.
- No raw `INSERT`/`UPDATE`/`DELETE` except through `epics-cli.sh`.

---

## 5. PLAN CRITIQUE

Before writing a plan file, Claude independently reviews Gemini's output. Full checklist: `refs/orch-critique-checklist.md`.

**Disagreement model**: State positions with reasoning. Hold until convinced or overridden. On override: request rationale per CLAUDE.md, comply, log, never re-raise.

**Model disagreement**: If Claude's critique substantially contradicts Gemini's plan, surface both perspectives to the user. Never silently discard Gemini's output when disagreement is material.

---

## 6. STORY STRUCTURE

- **Epic** — broad theme. States: `active` → `done` → `shipped`.
- **Story** — scoped deliverable, own branch/worktree. States: `draft` → `ready` → `in-progress` → `in-review` → `approved` → `done` → `shipped`. Also: `blocked`. Agent: `quick-fixer` | `architect` | `manual`. Must have `plan_file` to run.
- **Task** — sub-item, no branch. States: `todo` → `in-progress` → `done`. Also: `blocked`, `skipped`.

---

## 7. CODER PROMPTS

Full template: run-stories/SKILL.md Step 4. Must include: story title, plan file, write-targets (absolute worktree paths), read-only context, agent approach, pitfalls, OpenMemory learnings, worktree enforcement block.

**NEED_DECISION**: once per story, does not count toward escalation. Second → BLOCKED.
**Size ceiling**: >5 files or >200 lines → split. **Conflict check**: no shared write targets with in-progress stories.

---

## 8. MERGE & ESCALATION

Procedures: merge-worktree/SKILL.md. After coder: NEED_DECISION → pick, resume. DONE → diff gate → test → review → merge. Auto-launch unblocked stories after merge.

**Escalation**: 2 BLOCKING → Opus (architect only). Still BLOCKING → `blocked`. **Restart**: plan was wrong (not coder) → new plan, same model, max 1. **Outcome logging**: every terminal transition → `outcomes.md` (merge-worktree Step 5.5). **Parallel**: no write-target overlap required; first merges, second rebases.

---

## 9. CONTEXT MANAGEMENT

**Safe to `/clear` when ALL true**: no background agent running, no agent result needed, between stories.

**Survives `/clear`**: git branches, worktrees, epics.db, plan files, corrections.md.
**Lost**: in-session memory, coder task status.

Before `/clear`: write `session-handoff.md`, store summary to OpenMemory, run debrief. Recovery details: `refs/orch-context-mgmt.md`.

---

## 10. HOTFIX AND QUICKFIX

**Hotfix**: single file, not protected, ≤30 lines, no schema/AI. Inline edit, squash PR. Max 3/session.
**Quickfix**: 1-3 files, none protected, no schema/AI. Worktree + quick-fixer (Haiku). Max 2/session.
Both skip `/todo` and epics.db. Rejected → `/todo`.

---

## 11. PROTECTED FILES

Read from `<project>/.claude/protected-files.md`. Stories touching protected files require explicit user confirmation. Others: include "Do not edit any protected files" in coder prompt.

---

## 12. SPECULATIVE EXECUTION

User-requested only. Two plan files, two parallel worktrees, same base branch. Max 1/session, architect only. Loser worktree cleaned up.

---

## 13. `/ship`

One-shot pipeline: QUEUE→PLAN→DRAFT→RUN→MERGE. Default for new projects, isolated features, MVPs. Full procedures: ship/SKILL.md. Fall back to full pipeline for protected files, schema changes, or production iteration.

---

## 14. MEMORY

Two layers: **eager** (CLAUDE.md, ORCHESTRATION.md, behavioral-prefs.md — loaded at session start) and **lazy** (OpenMemory — queried on demand).

All templates, tag taxonomy, scoping rules, synthesis, debrief: `refs/orch-memory.md`.

---

## 15. FRICTION TRACKING

Friction = deviations from the expected path. Two types: **automatic** (escalation, restart, blocked, need_decision, conflict, test retry) and **judgment** (with counterfactual). Corrections capture what the user said; friction captures what went wrong. Not every correction is friction.

Format, categories, pre-creation gate, pattern promotion, response protocol: `refs/orch-friction.md`.
