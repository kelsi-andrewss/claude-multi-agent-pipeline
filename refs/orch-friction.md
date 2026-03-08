# Friction Reference — Formats, Gates & Protocols

Extracted from ORCHESTRATION.md §18. Loaded on demand when logging friction or running /skill-health.

---

## Friction event format

Friction events are a type of correction, captured via the correction pipeline:
1. Claude logs to `corrections.md` during session
2. Stop hook detects structural patterns in transcript → `correction_groups` table
3. Auto-promoted when count >= 3

No separate friction-log.md file.

---

## Pattern promotion

When the same correction theme recurs 3+ times (tracked in `correction_groups` table):
1. Stop hook auto-promotes to behavioral-prefs.md + OpenMemory via om_write
2. Feeds model selection, plan critique, and coder prompts
3. If pattern suggests a skill is needed, run the pre-creation gate (below).
   If pattern occurs inside an existing skill, the skill may need redesign.

---

## Pre-creation gate (before writing any SKILL.md)

Five questions. Gate is a judgment exercise — answers can be terse.

1. **What friction pattern does this eliminate?** — Cite 3+ correction_groups entries. No citations → hard stop.
2. **What's the current workaround, and what breaks about it?** — If "nothing, fine but verbose" → overhead. Consider CLAUDE.md constraint, hook, or `pm_add_pattern` instead.
3. **Could a simpler mechanism solve it?** — Evaluate: CLAUDE.md instruction → hook → `pm_add_pattern` → skill. Pick lightest.
4. **What ongoing cost does this add?** — Cognitive, maintenance, complexity. One sentence each.
5. **What condition would make this worth retiring?** — Record in skill-changelog.md.

**Outcomes:**
- All five answered + lighter alternatives ruled out → create skill, log to skill-changelog.md.
- Question 3 yields simpler mechanism → use that instead.
- Question 1 can't cite 3+ entries → don't create.

---

## Skill changelog

When a skill is created, significantly modified, or retired, append to `~/.claude/skill-changelog.md`:
`- [date] [action] /[skill-name] — [description]`

/skill-health uses these dates for before/after friction trends. Skip trivial changes.

---

## Response protocol

When /skill-health flags a high-friction skill (>40% rate, or new category after skill modification):

1. Verify recurring pattern is promoted to tool-learning if threshold met
2. Surface to user: "X events of type Y in Z sessions since [date]"
3. Suggest: modify skill, split workflow, add skill, or accept friction
4. If approved → `/todo` item targeting the skill

---

## Memory integration

- Correction patterns stored to OpenMemory via om_write when auto-promoted (count >= 3)
- Query correction history during plan critique to avoid known pitfalls
- /skill-health reads `correction_groups` table and `tracking/*.json` for trend analysis

---

## What friction measurement answers

These questions are answered by `correction_groups` data and /skill-health reading from `tracking/*.json`:
- "Did skill X eliminate its target friction?" → compare before/after (skill-changelog dates)
- "Is skill X creating new friction?" → new categories after its changelog date
- "Clean execution?" → friction count = 0
- "Overall trend?" → events per session by category
- "Efficiency impact?" → avg cycle time for 0-friction vs. 2+-friction outcomes
