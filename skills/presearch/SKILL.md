---
name: presearch
description: "Thin orchestrator: routes /scope -> /research -> /clarify+/scout (parallel) -> /briefing, with scope-based /quickfix shortcuts. Produces a structured briefing (presearch/<slug>.md) for /ship. Use when the user says \"/presearch <topic>\", \"/presearch path/to/requirements.md\", \"/presearch presearch/existing-briefing.md\", or \"/presearch --deep <topic>\"."
args:
  - name: args
    type: string
    description: "Topic (quoted string or free text), requirements file path, presearch briefing path (refine mode), or flags (--deep, --quick, --no-ship)."
---

# Presearch Skill Invoked

User has requested: `/presearch {{args}}`

---

## Step 0: Parse args and detect mode

Parse `{{args}}` to determine mode and flags:

**Flags** (strip from args after detection):
- `--deep` -> extra research rounds (passed to /research and /scout)
- `--quick` -> skip Q&A phase (passed to /clarify)
- `--no-ship` -> produce the doc but don't prompt to ship (handled locally in Step 5)

**Mode detection** (after stripping flags):
1. **Refine mode**: remaining arg is a path starting with `presearch/` and ending `.md`, and the file exists -> read it as existing briefing. Any text after the path is the refinement instruction.
2. **Requirements mode**: remaining arg is a path ending `.md` (not under `presearch/`), and the file exists -> treat path as the topic for /scope.
3. **Idea mode**: everything else -> treat as the topic/idea.

**Slug derivation**: from the topic text, generate a slug -- lowercase, hyphenated, max 40 chars. Strip articles and filler words. Examples:
- "Add presence cursors to the canvas" -> `add-presence-cursors`
- "path/to/auth-requirements.md" -> slug from the filename stem

Hold `topic`, `slug`, `flags`, and `mode` for routing.

---

## Step 1: Scope (skip if refine mode)

If refine mode: skip to Step 3. Decisions are already established in the existing briefing.

Invoke the /scope skill:

`Skill: scope, args: "<topic>"`

After /scope completes, read `.scope-<slug>.json` to get `needs_research`, `slug`, `scope`, and `route_hint`. Update the local slug if the artifact produced a different one.

---

## Router A: Post-scope check

Read `.scope-<slug>.json` and check `scope.complexity` and `route_hint`:

- If `route_hint == "quickfix"` or (`scope.complexity == "small"` and `scope.files <= 3`):
  Ask the user: `"Small scope detected (<scope.files> files). Use /quickfix instead? (y/n)"`
  - **y** -> `Skill: quickfix, args: "--context .scope-<slug>.json <topic>"` then **STOP**. Presearch is done.
  - **n** -> continue to Step 2.
- Otherwise -> continue to Step 2.

---

## Step 2: Research (conditional)

Check `.scope-<slug>.json` field `data.needs_research`:

- If `needs_research == false`: skip to Step 3.
- If `needs_research == true`: invoke /research.

**Invoke /research:**
- Base args: `--scope .scope-<slug>.json <topic>`
- If `--deep` flag is set: `Skill: research, args: "--deep --scope .scope-<slug>.json <topic>"`
- Otherwise: `Skill: research, args: "--scope .scope-<slug>.json <topic>"`

After /research completes, read `presearch/.research-<slug>.json`.

---

## Router B: Post-research scope check

**Skip this router in refine mode** -- scope is already established.

Read `presearch/.research-<slug>.json` and check `scope.complexity` (may have been updated from scope's estimate):

- If `small` (<=3 files):
  Ask the user: `"Research confirms small scope (<scope.files> files). Use /quickfix instead? (y/n)"`
  - **y** -> `Skill: quickfix, args: "--context presearch/.research-<slug>.json <topic>"` then **STOP**.
  - **n** -> continue to Step 3.
- If not `small` -> continue to Step 3.

---

## Step 3: Clarify + Scout (parallel)

Launch BOTH simultaneously:

**Foreground (clarify):**
- If research ran: `Skill: clarify, args: "--research presearch/.research-<slug>.json <topic>"`
- If research skipped: `Skill: clarify, args: "<topic>"`
- If `--quick` flag is set: add `--quick` flag to whichever variant above

**Background (scout):**
- Use Agent tool with `run_in_background: true`
- If research ran: `Skill: scout, args: "--research presearch/.research-<slug>.json <topic>"`
- If research skipped: `Skill: scout, args: "--scope .scope-<slug>.json <topic>"`
- If `--deep` flag is set: add `--deep` flag

Wait for both to complete. Read `.clarify-<slug>.json` and `presearch/.scout-<slug>.json`.

---

## Step 4: Briefing

Invoke the /briefing skill.

**Refine mode**: `Skill: briefing, args: "--refine presearch/<slug>.md"`

**Standard mode**: `Skill: briefing, args: "<slug>"`

/briefing handles loading the full artifact chain via prev pointers, Gemini synthesis, Claude critique, scope check, test strategy, decision recording, and file writing internally. This orchestrator does not participate in those steps.

---

## Step 5: Report

After /briefing completes:

```
Briefing: presearch/<slug>.md
```

Unless `--no-ship` was set:
```
Ship it? (/ship presearch/<slug>.md)
```

---

## Refine mode adjustments

When refine mode is detected (Step 0):
- Skip scope (decisions already established)
- Skip research (context already exists)
- Run clarify in refine-compatible mode + scout in background
- Proceed to briefing with `--refine`

---

## What this orchestrator does NOT do

These are child skill responsibilities -- never call them directly from here:
- `gemini_chat` or any `mcp__gemini__*` tools (scope/research/scout handle their own Gemini calls)
- `WebSearch` / `WebFetch`
- `AskUser` for Q&A (only for router y/n prompts)
- `pm_add_decision` / `openmemory_store` (decision recording is /briefing's job)

The orchestrator passes **file paths** between skills, never raw content. The artifact contract (`refs/artifact-contract.md`) governs the data exchange format.
