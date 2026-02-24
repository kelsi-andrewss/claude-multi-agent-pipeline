# Plan: NEEDS_PLANNING Exit Path for Orchestrator

## Context

The orchestrator is currently forced to either produce a full STAGING_PAYLOAD or ask one clarifying question. For ambiguous tasks (unclear scope, multiple valid approaches, schema/architectural questions), one question isn't enough and deep planning is out of scope for a thin classifier. We need a `NEEDS_PLANNING` exit path that delegates deep interactive research to the epic-planner, then feeds the resolved plan back to the orchestrator for staging.

Also: the todo-orchestrator agent file has vestigial Phases 3-4 referencing `todo-tracking.json`, which doesn't exist in the current workflow (epics.json + TaskCreate replaced it). We'll clean that up as part of this change.

---

## Flow

```
User: /todo "ambiguous task"
  |
  v
todo-orchestrator (Haiku, foreground)
  |
  +--> STAGING_PAYLOAD --> validate --> present --> approve (existing flow)
  +--> DUPLICATE --> inform user (existing flow)
  +--> NEEDS_PLANNING (new)
        |
        v
      Main: group bullets, select model, derive slug
        |
        v
      epic-planner (Sonnet/Opus, foreground, planning mode)
        |  <-- asks user questions interactively
        |  <-- writes $TMPDIR/planning-<slug>.md
        v
      todo-orchestrator (Haiku, foreground, with PLANNING_CONTEXT)
        |
        +--> STAGING_PAYLOAD --> validate --> present --> approve
        +--> NEEDS_PLANNING 2nd time --> surface to user, stop (no infinite loop)
        +--> UNRESOLVABLE --> surface to user, stop
```

---

## Files to Modify

### 1. `~/.claude/ORCHESTRATION.md`

**Section 2 (Agent Roles)** — Update epic-planner description to document two modes:

> **epic-planner** — research and planning agent. Two modes:
>
> 1. **Epic mode** (background): Takes an epic description and produces a multi-story plan. Trigger: "plan epic: ...". Always `run_in_background: true`. Writes to `$TMPDIR/epic-plan-<epic-slug>.md`. See ss19.
>
> 2. **Planning mode** (foreground): Takes orchestrator NEEDS_PLANNING bullets and conducts interactive research — asks user questions, makes suggestions, produces a refined plan. Trigger: orchestrator returns NEEDS_PLANNING. Always **foreground** (interactive). Writes to `$TMPDIR/planning-<todo-slug>.md`. See ss19.1.
>
> Permitted actions (both modes): Glob, Grep, Read, WebFetch. MUST NEVER: edit/write source files, run builds, run tests, commit, push. Model: Sonnet default; Opus if Complexity is "high", Touches includes "AI tools"/"Firestore schema", or Files explored > 10.

**Section 4 (After orchestrator completes)** — Replace the single-path handler with a three-path check + add ss4.1:

After orchestrator completes, check output type:
1. STAGING_PAYLOAD → validate (ss6), present, approve, TaskCreate (existing)
2. NEEDS_PLANNING → enter planning loop (ss4.1)
3. DUPLICATE → inform user (existing)

**New ss4.1 — NEEDS_PLANNING handling:**
1. Group bullets into categories (scope, approach, schema, UX) — cosmetic, helps planner structure research
2. Select model: Opus if Complexity "high" or Touches includes "AI tools"/"Firestore schema" or Files explored > 10; Sonnet otherwise
3. Derive `<todo-slug>` (kebab-case, <=5 words)
4. Launch epic-planner foreground with planning prompt:
   ```
   MODE: planning
   Original task: <user's todo>
   Orchestrator findings:
     Complexity: <from NEEDS_PLANNING>
     Touches: <from NEEDS_PLANNING>
     Files already explored: <from NEEDS_PLANNING>
   Open questions (grouped):
   ## Scope
   - <bullet>
   ## Approach
   - <bullet>
   Instructions: Research, ask user questions, make suggestions, write output to $TMPDIR/planning-<todo-slug>.md
   ```
5. Wait for planner to complete (foreground blocks)
6. Read `$TMPDIR/planning-<todo-slug>.md`
7. Re-launch orchestrator (Haiku, foreground) with:
   ```
   PLANNING_CONTEXT
   Original task: <user's todo>
   Resolved plan: <full planning output>
   Files already explored: <union of all explored files>
   Produce STAGING_PAYLOAD. Do not return NEEDS_PLANNING.
   ```
8. If orchestrator returns NEEDS_PLANNING again: surface remaining questions to user, stop. No infinite loop.
9. If UNRESOLVABLE: surface reason, stop.
10. If STAGING_PAYLOAD: validate as normal.

**Section 5 (Output Format)** — Add NEEDS_PLANNING variant after the existing STAGING_PAYLOAD format:

```
NEEDS_PLANNING
Todo: <one-line description>
Complexity: <low|medium|high>
Touches: <comma-separated areas>
Files explored: <comma-separated files already read>

Questions:
- <specific, actionable question>
- <specific, actionable question>

Suggestions:
- <approach the orchestrator leans toward, if any>
```

Rules:
- Minimum 2 questions, maximum 8. If only 1 question, ask it directly.
- Questions must be specific — not "what do you want?" but "should the field be denormalized or queried separately?"
- Each question independently answerable — no chaining.
- Complexity reflects the full task: "high" if >5 files, touches frames/AI/schema, or new patterns.
- If >5 files explored without converging, that's the signal to return NEEDS_PLANNING.

**New ss19.1 — Epic Planner Planning Mode:**

| Aspect | Epic mode (ss19) | Planning mode (ss19.1) |
|---|---|---|
| Trigger | "plan epic: ..." | Orchestrator NEEDS_PLANNING |
| Launch | Background | Foreground (interactive) |
| User interaction | None | Required — must ask questions |
| Output | Multi-story plan + staging payloads | Single refined plan document |
| Consumer | Main stages stories directly | Main feeds back to orchestrator |

Behavior:
1. Research areas in Touches, skip files already explored unless deeper context needed
2. For each open question: resolve via research or ask user. Do NOT silently assume.
3. Propose concrete approach for each question with brief trade-offs
4. Wait for user response before proceeding (batch 2-3 independent questions at once)
5. Write output to `$TMPDIR/planning-<todo-slug>.md`

Output format:
```
PLANNING_RESULT
Original task: <one-line>
Questions resolved: <count>

## Decisions
- Q: <question>
  A: <answer>
  Rationale: <one sentence>

## Recommended approach
<2-5 sentences>

## Scope
Write files: <comma-separated>
Read files: <comma-separated>
Agent: <quick-fixer|architect>
Model: <haiku|sonnet|opus>

## Constraints and edge cases
- <bullet>
```

If user says "you decide" on a question: planner decides, tags with `(planner decision)`.
If user cancels mid-planning: planner writes partial output, main asks user whether to proceed or abandon.

### 2. `~/.claude/agents/todo-orchestrator.md`

**Phase 1 — Classify** (rewrite):
1. Check for `PLANNING_CONTEXT` block. If present, skip to Phase 2 — ambiguity is already resolved.
2. Classify: quick-fixer vs architect.
3. If ambiguous and narrow (1 question resolves it): ask one clarifying question.
4. If ambiguous and broad (2+ questions, scope unclear, explored >5 files without converging): return NEEDS_PLANNING. Do NOT attempt deep planning.

**Phase 2 — Produce Staging Payload** (rewrite):
1. If PLANNING_CONTEXT present: use resolved plan as primary input. Only read files NOT in "Files already explored."
2. Otherwise: explore codebase. Stay under 5 file reads — if you need more, return NEEDS_PLANNING.
3. Produce STAGING_PAYLOAD (existing format, ss5).
4. If still can't produce even with planning context: return `UNRESOLVABLE: <reason>`.

**Add NEEDS_PLANNING format block** (between Phase 2 and Phase 3).

**Phase 3 — Remove todo-tracking.json** (vestigial — conflicts with epics.json). Replace Phases 3+4 with:

> ### Phase 3 — Return
> Return one of: STAGING_PAYLOAD, NEEDS_PLANNING, DUPLICATE, or UNRESOLVABLE. Your job ends here. Do not launch any coder, reviewer, or tester.

### 3. `~/.claude/skills/todo/SKILL.md`

Replace the Steps section to add NEEDS_PLANNING handling:

Step 5 becomes a three-path check:
- A. STAGING_PAYLOAD → validate, present, approve, TaskCreate (existing)
- B. DUPLICATE → inform user (existing)
- C. NEEDS_PLANNING → enter planning loop:
  - Group bullets, select model, derive slug
  - Launch epic-planner foreground with planning prompt
  - Read output
  - Re-launch orchestrator with PLANNING_CONTEXT
  - Handle result (STAGING_PAYLOAD, second NEEDS_PLANNING, UNRESOLVABLE)

---

### 4. `~/.claude/agents/epic-planner.md` (NEW)

The epic-planner currently has no agent file — it's only described in ORCHESTRATION.md ss19. All other agents (architect, quick-fixer, reviewer, etc.) have dedicated files in `~/.claude/agents/`. For the Task tool to launch it as a named agent, it needs one.

Contents:
- Frontmatter: name, description (covering both modes), model: sonnet
- Mode detection: check prompt for `MODE: planning` vs epic-mode context
- **Planning mode** behavior: research, ask user questions, make suggestions, write to `$TMPDIR/planning-<slug>.md`
- **Epic mode** behavior (existing ss19 logic): deep research, produce multi-story plan, write to `$TMPDIR/epic-plan-<slug>.md`
- Shared constraints: read-only (Glob, Grep, Read, WebFetch only), never edit/write source files, never build/test/commit

### 5. No changes needed to hooks or other skills

- `require-orch-read.sh` — already gates Task launches on ORCHESTRATION.md read. NEEDS_PLANNING flow happens inside `/todo` which reads ORCHESTRATION.md first. No conflict.
- `load-session-context.sh` — dumps ORCHESTRATION.md at session start. New sections will be included automatically.
- `pre-response-check` — routes "todo:" requests through the pipeline. NEEDS_PLANNING loop is inside the pipeline. No change needed.
- `guard-direct-edit.sh` — blocks Edit/Write on project files. Epic-planner is read-only. No conflict.

---

## Edge Cases

- **NEEDS_PLANNING twice**: Max 1 planning loop. Second time surfaces questions to user directly, no re-entry.
- **Planner can't resolve all questions**: Partial decisions tagged `(planner decision)`, orchestrator treats as resolved.
- **User cancels mid-planning**: Partial output written, main asks resume or abandon.
- **Simple task returns NEEDS_PLANNING**: 2-question minimum prevents this for trivial tasks. If it happens anyway, planner resolves quickly — minimal overhead.
- **Concurrent /todo invocations**: Each uses a separate `<todo-slug>`, writes to separate temp files, blocks independently.

---

## Verification

1. Read updated ORCHESTRATION.md ss2, ss4, ss4.1, ss5, ss19.1 for consistency
2. Read updated todo-orchestrator.md to confirm Phases 1-3 are clean (no todo-tracking.json references)
3. Read updated SKILL.md to confirm the three-path flow is clear
4. Manually test: run `/todo "ambiguous task"` and verify the orchestrator returns NEEDS_PLANNING, epic-planner launches in foreground, asks questions, and the orchestrator re-runs to produce STAGING_PAYLOAD
