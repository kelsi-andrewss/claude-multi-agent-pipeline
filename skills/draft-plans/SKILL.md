---
name: draft-plans
description: >
  Graph-node skill: reads .ship-manifest.json (or story/epic IDs), launches one
  background agent per story to write plans/*.md files, applies critique checklist,
  updates DB with plan_file paths. Artifact-chain-aware version of /draft-plan.
  Consumes manifest from /plan-stories, produces plans/*.md for /env-preflight.
triggers:
  - /draft-plans
  - /draft-plans .ship-manifest.json
  - /draft-plans story-NNN story-NNN
  - /draft-plans epic-NNN
args:
  - name: args
    type: string
    description: >
      Manifest path (.json), story IDs (story-NNN), epic IDs (epic-NNN),
      --briefing <path>, and/or --skip-critique. At least one input required.
---

# Draft Plans Skill Invoked

User has requested: `/draft-plans {{args}}`

## Phases

Read each phase file as you enter it.

1. **Resolve** → Read [resolve.md](resolve.md)
   - Parse args, detect input mode (manifest/ID/mixed)
   - Resolve stories, classify frontend/fast-path

2. **Prepare** → Read [prepare.md](prepare.md)
   - Read critique checklist, generate plan names
   - Decision lookup, exemplar matching, preference prediction

3. **Write plans** → Read [plan-writer.md](plan-writer.md)
   - Frontend gemini_design calls
   - Fast-path: write inline. Agent-path: launch background agents
   - Collect results, frontend validation

4. **Critique** → Read [critique-loop.md](critique-loop.md)
   - Skip if `--skip-critique` or caller handles separately
   - Delegate to subagent: 5-lens self-critique, Gemini escalation, contract gate
   - Report results

## Child files
- [resolve.md](resolve.md) — Parse args, resolve stories, frontend/fast-path detection
- [prepare.md](prepare.md) — Critique checklist, plan names, decisions, exemplars
- [plan-writer.md](plan-writer.md) — Plan templates, agent prompts, result collection
- [critique-loop.md](critique-loop.md) — Critique subagent, Gemini escalation, report
