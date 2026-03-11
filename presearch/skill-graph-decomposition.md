# Skill Graph Decomposition — Phase 1

## Overview

Decompose the monolithic /presearch and /ship skills into composable child skills connected by typed artifact edges. Each child skill loads only what it needs, does its job, writes its output artifact, and exits — preserving context across the pipeline without accumulating it in any single session. Phase 1 creates all new child skills and the artifact contract. Phase 2 (deferred) rewires the existing orchestrators.

## Summary

Break /presearch into /clarify, /research, /briefing. Break /ship into /plan-stories, /draft-plans, /env-preflight, /quickfix, /verify. Add --plans mode to /critique. All skills communicate via typed JSON artifacts with uniform headers (slug, scope, route_hint, prev pointer). Router logic at decision points reads scope metadata to route between standard and quickfix paths. Every node is independently invocable. Test strategy is planned during presearch phase, not invented by Gemini at story-planning time. Project CLAUDE.md files contain thinking frameworks, not toolchain instructions (decision-41).

## Features

### MVP

0. Bootstrap: Create `skills/` subdirectories for each new skill, define the shared artifact contract schema, create a `refs/skill-graph.md` reference doc for router logic
1. /clarify skill — Q&A ambiguity resolution. Gemini finds ambiguities, AskUser batches questions, writes `.clarify-<slug>.json` with resolved decisions and constraints
2. /research skill — Gemini seed research + web search/fetch. Reads clarify output (optional). Extracts testable assertions from findings. Writes `.research-<slug>.json` with raw findings, URLs, API shapes, test-relevant edge cases
3. /briefing skill — Gemini synthesis + Claude critique + scope check + decision recording. Reads research + clarify outputs. Writes `presearch/<slug>.md`. Patterns section is reference material for plan-stories, NOT a CLAUDE.md template. Includes ## Test Strategy section
4. /plan-stories skill — Wraps planner agent. Reads briefing (full doc, not just summary) or inline args. Creates epic/stories/tasks in DB via Gemini. Writes `.ship-manifest.json` with epic_id, dev_branch, story list
5. /draft-plans skill — Launches bg agents per story. Reads manifest + DB story details. Accepts --briefing flag. Applies critique checklist. Writes `plans/*.md`, updates DB with plan_file paths
6. /env-preflight skill — Scans plan files for external service dependencies. AskUser confirms env vars. Skips silently if nothing detected
7. /quickfix skill — Standalone extracted from ship Step 0b. Validates criteria, reads targets, writes plan, launches coder in worktree, merges. NEW: accepts artifact chain via --context flag (reads prev pointers to load upstream clarify/research context)
8. /verify skill — Combined integrated review + integration verify. Reviewer agent on full diff, build + test, acceptance criteria walk. Reads manifest for dev branch info
9. /critique --plans mode — Critique loop scoped to plan files. Self-critique + Gemini escalation. Mutates plans in place. Not a new skill — extends existing /critique

## Technical Research

### Architecture

Graph-based skill composition. Nodes = skills (stateless, read input artifacts, write output artifacts). Edges = typed JSON artifact files. Routers = decision points in orchestrators that read artifact scope metadata and pick next node.

### Artifact Contract

Every inter-skill temp file follows this schema:

```json
{
  "slug": "string — derived from topic, max 40 chars",
  "scope": {
    "files": "number — estimated write-target count",
    "stories": "number — estimated story count",
    "complexity": "small | medium | large"
  },
  "route_hint": "quickfix | standard | argue",
  "prev": "string | null — path to previous artifact in chain",
  "skill": "string — which skill produced this",
  "data": { }
}
```

`prev` creates the artifact chain. Any skill can walk prev pointers to load upstream context without loading everything. /quickfix uses this to access research findings without needing to understand the /clarify output format directly.

Final briefing files (`presearch/<slug>.md`) remain human-readable markdown — not JSON. The artifact contract applies to intermediate temp files only.

### Patterns

- Each skill is a SKILL.md file in its own `skills/<name>/` directory
- Skills invoke child skills via `Skill` tool calls
- Artifact files live in `presearch/` (presearch children) or project root (ship children like `.ship-manifest.json`)
- Temp artifacts (`.clarify-*.json`, `.research-*.json`) are prefixed with `.` to stay out of git
- Router logic lives in `refs/skill-graph.md` as a reference table, not embedded in each skill

### Router Logic

| After node | scope:small (≤3 files) | scope:standard | --argue flag |
|---|---|---|---|
| /clarify | → /quickfix | → /research | → /argue then /research |
| /research | → /quickfix | → /briefing | → /argue then /briefing |
| /briefing | → /quickfix | → /plan-stories | — |
| /draft-plans | skip critique | → /critique --plans | — |
| /run-stories | skip verify | → /verify | — |

### Test Strategy Integration

/research extracts testable assertions from its findings:
- API edge cases (rate limits, error shapes, auth failures)
- Data model constraints (required fields, valid ranges, relationships)
- Integration boundaries (what can break between services)

/briefing includes a ## Test Strategy section:
- Critical paths to test (from research)
- Edge cases (from gotchas)
- Integration boundaries (from API shapes)
- What NOT to test (wiring, types — per code philosophy)

/plan-stories receives test strategy as input → test stories are informed, not invented by Gemini in a vacuum.

### Project Structure

```
skills/
  clarify/SKILL.md
  research/SKILL.md
  briefing/SKILL.md
  plan-stories/SKILL.md
  draft-plans/SKILL.md
  env-preflight/SKILL.md
  quickfix/SKILL.md
  verify/SKILL.md
  critique/SKILL.md          ← existing, add --plans mode
  presearch/SKILL.md         ← Phase 2: refactor to orchestrator
  ship/SKILL.md              ← Phase 2: refactor to orchestrator
refs/
  skill-graph.md             ← router logic reference
```

### Dependencies

No new external dependencies. All skills use existing infrastructure:
- Gemini MCP tools (pm_*, gemini_chat)
- OpenMemory MCP tools
- WebSearch, WebFetch
- Agent tool (background agents for draft-plans)
- Skill tool (orchestrator → child skill invocation)
- AskUser (clarify, env-preflight)

### Gotchas

- Skills invoking child skills via Skill tool: verify this works (skill calling skill). If not, fall back to inline expansion within the orchestrator.
- Artifact temp files need cleanup strategy — stale `.clarify-*.json` files accumulate. Add to /cleanup skill scope.
- Phase 2 is the dangerous part: modifying live /ship and /presearch while they're being used. Must not break existing pipeline during transition.
- /critique --plans mode must not interfere with existing /critique behavior (no args = critique last output).

### Risks

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Skill-calls-skill doesn't work in Claude Code | High | Medium | Test with smoke-test before building all 8. Fallback: inline expansion |
| Artifact schema too rigid for future skills | Medium | Low | Schema is minimal (6 fields). `data` is freeform. Easy to extend |
| Phase 2 breaks live pipeline | High | Medium | Phase separation. Child skills are additive (new files). Orchestrator rewiring is atomic |
| Context savings less than expected | Medium | Low | Each child skill still loads Gemini/web tools. Savings come from not accumulating all results in one session |

## Environment

No external services. All MCP tools are local (Gemini, OpenMemory).

## Decisions

- **CLAUDE.md philosophy**: "How to think" not "what to do" — decision-41. Briefing patterns section is reference material, not CLAUDE.md template.
- **Critique mode vs separate skill**: /critique gets --plans flag, not a new /validate-plans skill. Avoids skill proliferation.
- **Quickfix promotion**: Extracted from /ship into standalone /quickfix skill. Accepts artifact chain for upstream context.
- **Phase split**: Child skills first (no conflict risk), orchestrator rewiring second (after running stories merge).
- **Test strategy in presearch**: /research extracts testable assertions, /briefing structures them, /plan-stories consumes them. Tests are planned, not invented.

## Constraints

- All files are within ~/.claude/ (this project)
- No changes to existing skill files in Phase 1 (except /critique for --plans mode)
- Must not break currently running pipeline
- Artifact temp files prefixed with `.` to stay out of git
- Router logic is reference material, not executable code — Claude reads it and makes decisions
