---
name: presearch
description: "Core project research pipeline: routes /scope -> /clarify+/scout (parallel) -> /briefing. No web search — that's /research's job. Produces a structured briefing (presearch/<slug>.md) for /ship. Use when the user says \"/presearch <topic>\", \"/presearch path/to/requirements.md\", \"/presearch presearch/existing-briefing.md\", or \"/presearch --deep <topic>\"."
args:
  - name: args
    type: string
    description: "Topic (quoted string or free text), requirements file path, presearch briefing path (refine mode), or flags (--deep, --quick, --no-ship, --scope <path>, --research <path>)."
---

# Presearch Skill Invoked

User has requested: `/presearch {{args}}`

---

## Step 0: Parse args and detect mode

Parse `{{args}}` to determine mode and flags:

**Flags** (strip from args after detection):
- `--deep` -> extra depth (passed to /scout)
- `--quick` -> skip Q&A phase (passed to /clarify)
- `--no-ship` -> produce the doc but don't prompt to ship (handled locally in Step 4)
- `--scope <path>` -> path to a pre-existing `.scope-<slug>.json` artifact. Skip Step 1 (scope).
- `--research <path>` -> path to a pre-existing `.research-<slug>.json` artifact. Passed to /clarify and /scout.

**Mode detection** (after stripping flags):
1. **Refine mode**: remaining arg is a path starting with `presearch/` and ending `.md`, and the file exists -> read it as existing briefing. Any text after the path is the refinement instruction.
2. **Requirements mode**: remaining arg is a path ending `.md` (not under `presearch/`), and the file exists -> treat path as the topic for /scope.
3. **Idea mode**: everything else -> treat as the topic/idea.

**Slug derivation**: from the topic text, generate a slug -- lowercase, hyphenated, max 40 chars. Strip articles and filler words. If `--scope` provided, use the slug from the scope artifact instead. Examples:
- "Add presence cursors to the canvas" -> `add-presence-cursors`
- "path/to/auth-requirements.md" -> slug from the filename stem

Hold `topic`, `slug`, `flags`, and `mode` for routing.

---

## Step 1: Scope (skip if refine mode or --scope provided)

If refine mode: skip to Step 2. Decisions are already established in the existing briefing.
If `--scope <path>` provided: read the scope artifact to get `slug`, `scope`, and `route_hint`. Update the local slug if different. Skip to Router A.

Invoke the /scope skill:

`Skill: scope, args: "<topic>"`

After /scope completes, read `.scope-<slug>.json` to get `slug`, `scope`, and `route_hint`. Update the local slug if the artifact produced a different one.

---

## Router A: Post-scope check

Read `.scope-<slug>.json` and check `scope.complexity` and `route_hint`:

- If `route_hint == "quickfix"` or (`scope.complexity == "small"` and `scope.files <= 3`):
  Ask the user: `"Small scope detected (<scope.files> files). Use /quickfix instead? (y/n)"`
  - **y** -> `Skill: quickfix, args: "--context .scope-<slug>.json <topic>"` then **STOP**. Presearch is done.
  - **n** -> continue to Step 2.
- Otherwise -> continue to Step 2.

---

## Step 2: Clarify + Scout (parallel)

Launch BOTH simultaneously:

**Foreground (clarify):**
- If `--research <path>` provided: `Skill: clarify, args: "--research <path> <topic>"`
- Otherwise: `Skill: clarify, args: "<topic>"`
- If `--quick` flag is set: add `--quick` flag to whichever variant above

**Background (scout):**
- Use Agent tool with `run_in_background: true`
- If `--research <path>` provided: `Skill: scout, args: "--research <path> <topic>"`
- Otherwise: `Skill: scout, args: "--scope .scope-<slug>.json <topic>"`
- If `--deep` flag is set: add `--deep` flag

Wait for both to complete. Read `.clarify-<slug>.json` and `presearch/.scout-<slug>.json`.

---

## Step 3: Briefing

Invoke the /briefing skill.

**Refine mode**: `Skill: briefing, args: "--refine presearch/<slug>.md"`

**Standard mode**: `Skill: briefing, args: "<slug>"`

/briefing handles loading the full artifact chain via prev pointers, Gemini synthesis, Claude critique, scope check, test strategy, decision recording, and file writing internally. This orchestrator does not participate in those steps.

---

## Step 4: Report

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
- Run clarify in refine-compatible mode + scout in background
- Proceed to briefing with `--refine`

---

## What this orchestrator does NOT do

These are child skill responsibilities -- never call them directly from here:
- `gemini_chat` or any `mcp__gemini__*` tools (scope/scout handle their own Gemini calls)
- `WebSearch` / `WebFetch` (web research is /research's job -- /research calls /presearch, not the other way around)
- `AskUser` for Q&A (only for router y/n prompts)
- `pm_add_decision` / `openmemory_store` (decision recording is /briefing's job)

The orchestrator passes **file paths** between skills, never raw content. The artifact contract (`refs/artifact-contract.md`) governs the data exchange format.
