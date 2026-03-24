# Main Session Orchestration — Constitution

These are decision rules and constraints for the main Claude Code session. Spawned agents do not load this file. Procedures live in the skills that execute them; reference material in `refs/orch-*.md`.

---

## 1. ROLES

**Claude** — main session. Calls Gemini for research, writes plan files, launches coders, merges. Writes `plan_file` and `state` via `pm_update_story(...)` — no other direct DB mutations.

**Main session worktree prohibition**: MUST NOT use `EnterWorktree` or `git worktree add`. All story worktrees are created by background coder agents only. Exception: `/merge-worktree` uses ephemeral `/tmp/` worktrees.

**No direct commits to main or dev**: All work — including hotfixes and quickfixes — must happen on a named feature branch (`hotfix/<slug>`, `quickfix/<slug>`, or story branch). Never commit directly to main or dev from any session.

**Branch merge hierarchy**: `main` is production. The ONLY thing that merges to main is `dev`. Everything else (story branches, hotfixes, quickfixes) merges to `dev`. Stories from different epics execute in parallel — epics are organizational grouping only, not execution boundaries. Conflict detection and dependency ordering operate at the story level across all epics.

**Gemini** — research and planning via MCP tools (`pm_*`, `gemini_*`). Writes to `epics.db`.
**Coders** (`quick-fixer`, `architect`, `ui-coder`) — execute approved plan files in worktrees. Never plan. Always `run_in_background: true`.
**Reviewer/Unit-tester/Git-ops** — on-demand, always `run_in_background: true`.

### Frontend design ownership

Gemini's visual/layout reasoning produces better design specs; Claude's architectural reasoning produces better integration plans. Split frontend stories accordingly:

- **Gemini** owns frontend design — component layout, visual properties, widget hierarchy, interactions. Use `gemini_redesign` MCP tool for design specs.
- **Claude** owns architecture — state management, data flow, API connections, business logic.
- Frontend stories produce dual-author plan files with two sections: `## Frontend Design (Gemini)` and `## Architecture (Claude)`.
- Coders treat Gemini's design section as a constraint (implement as designed) and Claude's architecture section as a guide (adapt to implementation realities).

---

## 2. MODEL SELECTION

| Role | Default | Escalation |
|---|---|---|
| Claude (main) | Sonnet | Opus if user requests or high-risk |
| Coder (quick-fixer/architect) | Sonnet | Opus after 2 BLOCKING round-trips |
| Coder (ui-coder) | Sonnet | Opus after 2 BLOCKING round-trips |
| Reviewer | Sonnet | Sonnet only if coder ran on Opus |
| Unit-tester | Sonnet | Never escalated |

Before defaulting, query OpenMemory for tool learnings about the model + file type. Consistent failures → escalate preemptively.

### Trust-informed selection (when merge_outcomes >= 10 records)

Trust scores from merge_outcomes override the static table above:

| Trust Level | Threshold | Model Policy | Approval Policy |
|---|---|---|---|
| High | >= 0.85 | Sonnet default | Auto-approve for proven domains |
| Medium | >= 0.70 | Sonnet default | Standard review flow |
| Low | < 0.70 | Sonnet default, escalation at 1 BLOCKING | Mandatory approval |

**Domain overrides**: When a domain's success rate diverges from global by >= 0.15 (with 3+ samples), its trust level governs stories touching that domain regardless of global trust.

**Minimum sample**: Trust-informed selection activates after 10 merge_outcomes records. Below that, use the static table above.

Trust scores computed by `hooks/lib/signal_processor.py:compute_trust_scores()`. Populated by `outcomes-parser.py`. See `refs/orch-memory.md § Trust Calibration`.

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

**Fast-path**: agent = `quick-fixer`, ≤2 write-target files, no protected files, no `ui_codegen`, tasks in DB → skip Gemini, Claude writes plan directly. UI stories always go through the full pipeline.

**Default for new work**: `/ship`. Fall back to full pipeline when iterating on production code, touching protected files, or changing schemas/APIs.

`/ship --quickfix` for scoped fixes (1-5 files, no breaking schema changes, no AI tool changes) — lightweight path that skips Gemini and epics.db.

---

## 4. DB ACCESS RULES

`epics.db` at `~/.claude/.claude/epics.db`. CLI at `~/.claude/scripts/epics-cli.sh`.

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
- **Story** — scoped deliverable, own branch/worktree. States: `draft` → `ready` → `in-progress` → `in-review` → `approved` → `done` → `shipped`. Also: `blocked`. Agent: `quick-fixer` | `architect` | `ui-coder` | `manual`. Must have `plan_file` to run. Stories with `ui_codegen: true` MUST use `ui-coder`.
- **Task** — sub-item, no branch. States: `todo` → `in-progress` → `done`. Also: `blocked`, `skipped`.

### Test requirements

`test_files` is required for all stories that create or modify functional code. Stories without `test_files` are blocked at execution (`/run-stories` Step 1) unless `needs_testing` is explicitly set to `false`.

**Exempt from testing** (`needs_testing: false`):
- Docs-only changes (README, CLAUDE.md, comments)
- Config-only changes (YAML, JSON, env files, CI pipelines)
- Scaffold/boilerplate (project init, dependency install, file structure)
- Pure refactors that don't change observable behavior (renames, moves, import reorganization)
- Skill/orchestration definition changes (SKILL.md, ORCHESTRATION.md)

When Gemini plans stories via `pm_plan_story`, it sets `test_files` for functional stories and `needs_testing: false` for exempt ones. The plan writer (`/draft-plans`) generates test-aware acceptance criteria when `test_files` is present.

### Story decomposition for parallelism

When decomposing an epic into stories, minimize write-target file overlap across stories. Group changes by the files they modify, not by conceptual theme or tier. A story that owns `quickfix/SKILL.md` implements ALL changes to that file across all tiers/features in the epic.

This maximizes parallel execution — stories with non-overlapping write targets run concurrently. Stories with overlapping write targets get serialized, so every shared file is lost parallelism.

**During planning**: if two stories in the same epic share write-target files, flag it as a parallelism concern. Restructure to eliminate the overlap unless the changes are genuinely inseparable (e.g., two functions in the same file that reference each other's new code).

**Decomposition priority**: file ownership > conceptual grouping. A story titled "ORCHESTRATION.md updates" that spans multiple conceptual tiers is better than three tier-themed stories that all touch ORCHESTRATION.md.

---

## 7. CODER PROMPTS

Full template: run-stories/SKILL.md Step 4. Must include: story title, plan file, write-targets (absolute worktree paths), read-only context, agent approach, pitfalls, OpenMemory learnings, worktree enforcement block.

**NEED_DECISION**: no count cap — coders emit it whenever they genuinely cannot proceed. Does not count toward the BLOCKING escalation counter. BLOCKED triggers only on: (a) coder re-emits NEED_DECISION on the same topic after receiving a resolution (communication failure), or (b) coder is fundamentally stuck (wrong plan, impossible constraint). Critical decisions (prefixed "CRITICAL:") always escalate to user regardless. Coders must use the structured format defined in the coder prompt template (run-stories/SKILL.md Step 4). Main session creates a decision review artifact per section 7 "Decision review artifacts" before resolving.
**Size ceiling**: >5 files or >200 lines → split. **Conflict check**: no shared write targets with in-progress stories.
**Script refs**: Any script path referenced in a SKILL.md (`bash ~/.claude/scripts/...` or `python3 ~/.claude/scripts/...`) is a write-target. If the script doesn't exist, the coder must create it as part of the story — not defer it.

**Gemini MCP access**: Coders may call `mcp__gemini__analyze` for codebase investigation outside their write targets. This preserves coder context budget — Gemini reads files and returns a compressed answer instead of the coder ingesting hundreds of lines for a one-sentence insight. Queries must be specific: symbol name, file paths, exact question. All other `mcp__gemini__*` tools remain orchestrator-only.

**UI coder routing**: Stories with `ui_codegen: true` MUST use the `ui-coder` agent — never `quick-fixer` or `architect`. The `ui-coder` agent is the ONLY agent allowed to call `mcp__gemini__gemini_ui_code`. It enforces Gemini code generation for all visual/layout component code. Quick-fixer and architect write their own code and are blocked from `gemini_ui_code`.

**UI codegen gate**: If a story's write targets include UI file extensions (`.tsx`, `.jsx`, `.vue`, `.svelte`, `Screen.kt`, `.dart` files with `screen`/`widget`/`page` in the name) but `ui_codegen` is not `true`, warn before launch. The planner likely missed the tag.

### Decision autonomy levels

| Level | Scope | Coder action |
|---|---|---|
| Tactical | Naming conventions, import organization, test structure, error message wording | Resolve autonomously — no NEED_DECISION |
| Strategic | API shape, data flow architecture, state management patterns | Emit NEED_DECISION, main session resolves |
| Critical | Security changes, data migration, breaking API changes, auth/permissions | Emit NEED_DECISION with "CRITICAL:" prefix, main session must get user confirmation |

### NEED_RESEARCH signal

Coders may emit `NEED_RESEARCH` when they encounter a question that requires external knowledge (API behavior, library usage, platform constraints) they cannot resolve from the codebase alone.

**Format:**
```
NEED_RESEARCH: <specific question>
Context: <what the coder has tried/found so far>
```

NEED_RESEARCH does not count toward the BLOCKING escalation counter. It is not a failure — it is a request for information.

### Decision review artifacts

When a coder emits NEED_DECISION at strategic or critical level, the main session creates a review artifact before resolving the decision.

**Artifact location:** `decisions/reviews/decision-<NNN>.md` where NNN is a monotonically increasing integer (next available in the directory).

**Creation rules:**

| Level | Artifact created? | Approval required? |
|---|---|---|
| Tactical | No | No |
| Strategic | Yes | Main session resolves |
| Critical | Yes | User confirmation required |

**Directory bootstrapping:** The main session runs `mkdir -p decisions/reviews/` before writing the first artifact in a session. No pre-existing directory structure is required.

**Artifact format:**

```markdown
# Decision Review: decision-NNN

**Story:** story-NNN
**Date:** YYYY-MM-DD
**Level:** strategic | critical
**Decider:** user | claude

## Context
<What the coder was doing when the decision was needed>

## Options
### Option 1: <title>
<Detailed description with tradeoffs>

### Option 2: <title>
<Detailed description with tradeoffs>

### Option 3: <title> (if applicable)
<Detailed description with tradeoffs>

## Resolution
**Chosen:** Option <N>
**Rationale:** <Why this option was selected>

## Outcome
**Status:** pending
**Merge result:** <updated post-merge by section 8 flow>
```

---

## 8. MERGE & ESCALATION

Procedures: merge-worktree/SKILL.md. After coder: NEED_DECISION → create decision review artifact (section 7), pick option, resume. NEED_RESEARCH → dispatch targeted Gemini research (web_search with the specific question + coder's context), resume coder with the answer. DONE → diff gate → test → review → merge. Auto-launch unblocked stories after merge.

**Post-merge artifact update**: After a successful merge, update any decision review artifacts created during that story's execution. Set `## Outcome` → `Status: success` and `Merge result: merged to dev at <commit-hash>`. On merge failure or story BLOCKED, set `Status: failure` and `Merge result: <failure reason>`.

**Escalation**: 2 BLOCKING → Opus (architect only). Still BLOCKING → `blocked`. **Restart**: plan was wrong (not coder) → new plan, same model, max 1. **Outcome logging**: every terminal transition → `merge_outcomes` table in run-state.db (merge-worktree Step 5.5). **Parallel**: no write-target overlap required; first merges, second rebases.

---

## 9. CONTEXT MANAGEMENT

**Safe to `/clear` when ALL true**: no background agent running, no agent result needed, between stories.

**Survives `/clear`**: git branches, worktrees, epics.db (incl. correction_groups), plan files.
**Lost**: in-session memory, coder task status.

Before `/clear`: write `session-handoff.md`, store summary to OpenMemory, run debrief. Recovery details: `refs/orch-context-mgmt.md`.

---

## 10. HOTFIX AND QUICKFIX

**Hotfix**: single file, not protected, ≤30 lines, no schema/AI. Max 3/session.
- Create branch `hotfix/<slug>` from `dev`, edit there, merge back to `dev`.
- Never commit directly to main or dev.

**Quickfix**: 1-5 files, none protected, no breaking schema changes (additive OK), no AI tool changes. Max 3/session.
- Use `/ship --quickfix <description>`. /ship validates criteria, writes the plan, launches the coder on a `quickfix/<slug>` branch in a worktree, and merges to dev. No epics.db writes.
- Never commit directly to main or dev.

Hotfix is a direct edit (no coder-in-worktree). Quickfix uses the coder pipeline via /ship. Both skip `/todo` and epics.db. Rejected → `/todo`.

---

## 11. PROTECTED FILES

Read from `<project>/.claude/protected-files.md`. Stories touching protected files require explicit user confirmation. Others: include "Do not edit any protected files" in coder prompt.

---

## 12. `/ship`

One-shot pipeline: QUEUE→PLAN→DRAFT→RUN→MERGE. Default for new projects, isolated features, MVPs. Full procedures: ship/SKILL.md. Fall back to full pipeline for protected files, schema changes, or production iteration.

---

## 13. MEMORY

Two layers: **eager** (CLAUDE.md, ORCHESTRATION.md, rendered-prefs.md — loaded at session start) and **lazy** (OpenMemory — queried on demand via compact session-start query).

Three persistence surfaces: `correction_groups` table (manual via `log-correction.sh` + auto via stop hook), `rendered-prefs.md` (generated sidecar), OpenMemory (semantic store with per-category budgets).

All OpenMemory writes go through `hooks/lib/om_write.py`. Tag taxonomy: `behavioral-pref`, `tool-learning`, `decision`, `prompt-pattern`, `session-summary`. Adding a new tag requires updating om_write.py ALLOWED_TAGS, BUDGETS, CLAUDE.md integration surfaces, and refs/orch-memory.md.

Auto-distillation: stop hook promotes correction patterns (count >= 3) to correction_groups DB + OpenMemory. Manual corrections logged via `scripts/log-correction.sh` go to the same table.

Anti-bloat: per-category budgets, embedding-based dedup (0.85), decay-weighted pruning at session start.

Full reference: `refs/orch-memory.md`.

---

## 14. FRICTION TRACKING

Friction = deviations from the expected path. Captured as corrections → correction_groups table (epics.db). Two detection methods: structural (stop hook pattern matching on transcript) and manual (Claude runs `scripts/log-correction.sh`).

Auto-promotion: when a correction theme reaches count >= 3, auto-promoted to correction_groups DB + OpenMemory. No manual gate.

Full reference: `refs/orch-friction.md`.

---

## 15. DELEGATION

Delegate by phase — each pipeline phase that doesn't require user decisions should be one subagent. The unit of delegation is a complete phase, not individual MCP calls.

### Phase-based delegation table

| Phase | What it does | Delegation | Agent type |
|---|---|---|---|
| **Resolution** | Plan file → coder in worktree → committed code | 1 subagent per story via `run-stories` | Coder (`quick-fixer` / `architect` / `ui-coder`) |
| **Critique** | Plan reads + `pm_critique` + `pm_add_decision` | 1 subagent per plan | Reviewer |
| **Merge** | Diff gates + git merges + cleanup + DB updates + outcome logging | 1 subagent per batch via `merge-worktree` | Git-ops |

### Keep inline (main session)

- Single state transitions (`pm_update_story`)
- `ToolSearch` calls
- User-facing decisions and confirmations
- `NEED_DECISION` routing — main session picks the option and resumes the coder
- Final reports and session summaries

### Exceptions

These never leave the main session regardless of MCP call count:

- **User-facing decisions**: anything requiring user confirmation or choice stays inline.
- **NEED_DECISION routing**: the main session resolves the decision, then resumes or relaunches the coder.
- **Final reports**: session summaries, outcome reports, and debrief output are composed by the main session.

### Subagent return contract

Every delegated subagent returns exactly one of: `DONE: <summary>`, `NEED_DECISION: <question>`, or `BLOCKED: <reason>`. The main session never parses intermediate output — only the terminal status line.
