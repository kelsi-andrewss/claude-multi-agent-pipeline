---
name: presearch
description: "Thin orchestrator: routes /clarify -> /research -> /briefing, with scope-based /quickfix shortcuts after each stage. Produces a structured briefing (presearch/<slug>.md) for /ship. Use when the user says \"/presearch <topic>\", \"/presearch path/to/requirements.md\", \"/presearch presearch/existing-briefing.md\", or \"/presearch --deep <topic>\"."
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
- `--deep` -> extra research rounds (passed to /research)
- `--quick` -> skip Q&A phase (passed to /clarify)
- `--no-ship` -> produce the doc but don't prompt to ship (handled locally in Step 4)

**Mode detection** (after stripping flags):
1. **Refine mode**: remaining arg is a path starting with `presearch/` and ending `.md`, and the file exists -> read it as existing briefing. Any text after the path is the refinement instruction.
2. **Requirements mode**: remaining arg is a path ending `.md` (not under `presearch/`), and the file exists -> treat path as the topic for /clarify.
3. **Idea mode**: everything else -> treat as the topic/idea.

**Slug derivation**: from the topic text, generate a slug -- lowercase, hyphenated, max 40 chars. Strip articles and filler words. Examples:
- "Add presence cursors to the canvas" -> `add-presence-cursors`
- "path/to/auth-requirements.md" -> slug from the filename stem

Hold `topic`, `slug`, `flags`, and `mode` for routing.

---

## Step 1: Clarify (skip if refine mode)

If refine mode: skip to Step 2. Decisions are already established in the existing briefing.

Invoke the /clarify skill:

- If `--quick` flag is set: `Skill: clarify, args: "--quick <topic>"`
- Otherwise: `Skill: clarify, args: "<topic>"`

After /clarify completes, read `.clarify-<slug>.json` to get `scope` and `slug`. Update the local slug if the artifact produced a different one.

---

## Router A: Post-clarify scope check

Read `.clarify-<slug>.json` and check `scope.complexity`:

- If `small` (<=3 files):
  Ask the user: `"Small scope detected (<scope.files> files). Use /quickfix instead? (y/n)"`
  - **y** -> `Skill: quickfix, args: "--context .clarify-<slug>.json <topic>"` then **STOP**. Presearch is done.
  - **n** -> continue to Step 2.
- If not `small` -> continue to Step 2.

---

## Step 2: Research

Invoke the /research skill with the clarify artifact as upstream context.

**Standard / requirements / idea mode** (clarify artifact exists):
- Base args: `--clarify .clarify-<slug>.json <topic>`
- If `--deep` flag is set: `Skill: research, args: "--deep --clarify .clarify-<slug>.json <topic>"`
- Otherwise: `Skill: research, args: "--clarify .clarify-<slug>.json <topic>"`

**Refine mode** (no clarify artifact):
- `Skill: research, args: "<refinement instruction>"`
- If `--deep` flag is set, prepend `--deep` to args.

After /research completes, read `presearch/.research-<slug>.json`.

---

## Router B: Post-research scope check

Read `presearch/.research-<slug>.json` and check `scope.complexity` (may have been updated from clarify's estimate):

- If `small` (<=3 files):
  Ask the user: `"Research confirms small scope (<scope.files> files). Use /quickfix instead? (y/n)"`
  - **y** -> `Skill: quickfix, args: "--context presearch/.research-<slug>.json <topic>"` then **STOP**.
  - **n** -> continue to Step 3.
- If not `small` -> continue to Step 3.

**Skip this router in refine mode** -- scope is already established.

---

## Step 3: Briefing

Invoke the /briefing skill.

**Refine mode**: `Skill: briefing, args: "--refine presearch/<slug>.md"`

**Standard mode**: `Skill: briefing, args: "<slug>"`

/briefing handles Gemini synthesis, Claude critique, scope check, test strategy, decision recording, and file writing internally. This orchestrator does not participate in those steps.

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

## What this orchestrator does NOT do

These are child skill responsibilities -- never call them directly from here:
- `gemini_chat` or any `mcp__gemini__*` research tools
- `WebSearch` / `WebFetch`
- `AskUser` for Q&A (only for router y/n prompts)
- `pm_add_decision` / `openmemory_store` (decision recording is /briefing's job)

The orchestrator passes **file paths** between skills, never raw content. The artifact contract (`refs/artifact-contract.md`) governs the data exchange format.
