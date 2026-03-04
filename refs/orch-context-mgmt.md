# Context Management Reference — Handoff, Debrief & Recovery

Extracted from ORCHESTRATION.md §10 and §12. Loaded on demand before /clear and at session start if recovery needed.

---

## Handoff

Before suggesting `/clear`, write `~/.claude/session-handoff.md`:
- What was being worked on and what the next action would be
- Any context the next session needs that isn't captured in epics.db or corrections.md
- For story sessions: current status, pending decisions, coder state
- For work sessions: files changed, intent behind changes
- For discussion sessions: decisions reached, options considered, open questions

Keep it under 10 lines. Overwrite any existing handoff file.

Additionally, store a session summary to OpenMemory (episodic sector) before `/clear`.

---

## Debrief template (execute before `/clear`)

1. Write `session-handoff.md` per above.
2. `openmemory_store(content="Session [date]: [session shape]. [What happened, 1-2 sentences]. Key: [1-sentence takeaway].", tags=["session-summary"], user_id="proj:dotclaude")`
3. For story sessions: evaluate attributed memories against outcomes (see `refs/orch-memory.md` debrief reinforcement).
4. For friction events that occurred WITHOUT a memory predicting them: `openmemory_store(content="[observation from friction]", tags=["tool-learning"], user_id="global")`
5. Then `/clear`.

Note: The Stop hook auto-writes session records and detects corrections. The debrief captures what automation can't: judgment about memory reinforcement and intentional observations.

**Clearing prompt**: "Context checkpoint reached [reason]. Run `/clear` to reset. All state is in `epics.db`."

Prompt `/clear` after: story merges, 3+ stories done in session, or user asks if safe.

---

## Recovery queries

On session start (or after `/clear` with in-flight work):

```bash
sqlite3 ~/.claude/.claude/epics.db "SELECT id, title, state, branch FROM stories WHERE state NOT IN ('done','shipped') AND archived=0;"
git worktree list
git branch --list 'dev-*'         # epic dev branches
git branch --list '*--*'          # story branches (<epic-slug>--<story-slug>)
```

**Decision rules:**
- Stories in `in-progress` with an existing worktree → resume from coder step.
- Stories in `in-progress` with no worktree → reset to `ready`, re-run `/draft-plan` if no plan file.
