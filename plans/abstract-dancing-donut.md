# Plan: Wire hotfix/quickfix into /todo pre-screening

## Context

When a user runs `/todo` with a simple 1-3 file fix, the current pipeline always routes through the orchestrator (a foreground Haiku agent), stages a story in epics.json, waits for a run trigger, then spins up a worktree and background coder. For a fix that qualifies as hotfix or quickfix, this is 5-7 unnecessary steps.

The ORCHESTRATION.md §4 says "Skip orchestrator when affected files known, root cause clear, no new story/epic needed, no schema/frame/AI changes — go directly to coder." But it doesn't wire this to the fast-lane skills. The `/todo` skill has no pre-screen step at all — it always hits the orchestrator.

The fix: add a fast-lane pre-screen to the `/todo` skill's step sequence. If the request clearly qualifies as hotfix or quickfix (files parseable from the request, count ≤3, not protected), invoke that skill directly and skip the orchestrator entirely.

---

## Also fixing: ORCHESTRATION.md sentinel path inconsistency

ORCHESTRATION.md §20 still says `/tmp/hotfix-active-$$` (PID-based), but commit `e685cc3` fixed the actual sentinel to `/tmp/hotfix-active` (fixed path), and the hotfix skill already uses the fixed path. ORCHESTRATION.md is stale — update it to match.

---

## Changes

### 1. `/Users/kelsiandrews/.claude/skills/todo/SKILL.md`

Add a new **Step 1.5: Fast-lane pre-screen** between the current Step 1 (read ORCHESTRATION/CLAUDE.md) and Step 2 (read epics.json).

```
## Step 1.5: Fast-lane pre-screen

Before launching the orchestrator, check if the request qualifies for a fast lane:

**Hotfix candidate** — ALL must be inferrable from the user's message:
- Exactly 1 file path mentioned or unambiguously implied
- Root cause is stated (not "investigate" or "figure out why")
- No schema/frame/AI tool language in the description
- File is not in the protected list

→ If all pass: invoke `/hotfix <description>` directly. Stop here.

**Quickfix candidate** — ALL must be inferrable:
- 1-3 file paths mentioned or unambiguously implied
- Root cause is stated
- No schema/frame/AI tool language
- No file is in the protected list

→ If all pass: invoke `/quickfix <description>` directly. Stop here.

**Ambiguity rule**: If file paths are not clearly stated or the root cause requires investigation, skip pre-screen and continue to Step 2 (orchestrator path). Do NOT ask the user to clarify just to attempt a fast lane — only pre-screen when the signal is unambiguous.
```

The rest of the steps remain unchanged (Step 2 onward = orchestrator path for anything that doesn't pre-screen).

### 2. `/Users/kelsiandrews/.claude/ORCHESTRATION.md` — §20 sentinel fix

Change:
```
Guard hook sentinel at `/tmp/hotfix-active-$$` allows the edit
```
To:
```
Guard hook sentinel at `/tmp/hotfix-active` allows the edit
```

---

## What this does NOT change

- The orchestrator's role and output format are unchanged
- The hotfix and quickfix skill steps are unchanged
- epics.json, update-epics.sh, and all pipeline machinery are unchanged
- The orchestrator can still return STAGING_PAYLOAD for complex requests — pre-screen only fires on unambiguous fast-lane signals

---

## Verification

1. Run `/todo fix button color in src/components/Toolbar.jsx` — should invoke hotfix directly, not orchestrator
2. Run `/todo fix drag offset in src/handlers/dragHandler.js and src/components/DragPreview.jsx` — should invoke quickfix directly
3. Run `/todo investigate why auth fails on mobile` — no file paths, ambiguous root cause → should hit orchestrator normally
4. Run `/todo refactor the auth system` — no fast-lane signal → orchestrator
5. Check ORCHESTRATION.md §20 shows `/tmp/hotfix-active` (no `$$`)
