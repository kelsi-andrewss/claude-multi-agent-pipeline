# Skill Graph

## Architecture

Graph-based skill composition. Nodes are skills. Edges are typed JSON artifacts conforming to `refs/artifact-contract.md`. Routers are decision points that read scope and route_hint to determine the next node.

Two pipelines share this graph:

- **/presearch pipeline**: clarify -> research -> briefing (produces `presearch/{slug}.md`)
- **/ship pipeline**: plan-stories -> draft-plans -> env-preflight -> run-stories -> verify

Any node can route to `/quickfix` when scope is small, short-circuiting the full pipeline.

## Router logic table

| After node | scope:small (<=3 files) | scope:standard | --argue flag |
|---|---|---|---|
| /clarify | -> /quickfix | -> /research | -> /argue then /research |
| /research | -> /quickfix | -> /briefing | -> /argue then /briefing |
| /briefing | -> /quickfix | -> /plan-stories | -- |
| /draft-plans | skip critique | -> /critique --plans | -- |
| /run-stories | skip verify | -> /verify | -- |

Routers always have final say over `route_hint`. The table above is the default policy; orchestrators can override based on flags or user directives.

## Scope thresholds

| Complexity | Files | Stories | Description |
|---|---|---|---|
| small | <=3 | 1 | Straightforward changes, single story |
| medium | 4-10 | 2-5 | Multiple files or stories |
| large | >10 | >5 | Either dimension exceeds medium |

Complexity is the max of the two dimensions.

## Skill inventory

| Skill | Reads | Writes | Parent orchestrator |
|---|---|---|---|
| /clarify | user input | `.clarify-{slug}.json` | /presearch |
| /research | `.clarify-{slug}.json` (if exists) | `.research-{slug}.json` | /presearch |
| /briefing | `.clarify-{slug}.json`, `.research-{slug}.json` | `presearch/{slug}.md` | /presearch |
| /plan-stories | `presearch/{slug}.md` | `.ship-manifest.json` | /ship |
| /draft-plans | `.ship-manifest.json` | `plans/*.md` | /ship |
| /env-preflight | `plans/*.md` | (no artifact -- side effects only) | /ship |
| /quickfix | artifact chain via --context | (inline -- no artifact) | /presearch or /ship |
| /verify | run-stories output | (no artifact -- pass/fail) | /ship |
| /critique | plans or agent output | (inline feedback) | /ship, /draft-plan |
| /presearch | user input | `presearch/{slug}.md` (via sub-skills) | main session |
| /ship | presearch output or user input | merged branch (via sub-skills) | main session |
| /run-stories | `plans/*.md`, stories DB | story branches | /ship |

## Artifact flow

```
/clarify    -> .clarify-{slug}.json
/research   -> .research-{slug}.json  (prev: [.clarify-{slug}.json] if exists)
/briefing   -> presearch/{slug}.md    (prev: [.clarify-{slug}.json, .research-{slug}.json])
/plan-stories -> .ship-manifest.json
/draft-plans  -> plans/*.md
/env-preflight -> (no artifact -- side effects only)
/quickfix     -> (inline -- reads artifact chain via --context)
/verify       -> (no artifact -- pass/fail)
```

## Entry points

Any node can be invoked standalone. When invoked without upstream artifacts, the skill operates with whatever context is provided inline (user message, --context flag, or piped input). This means:

- `/research` can run without a prior `/clarify` artifact
- `/briefing` can run with only a `/research` artifact (no `/clarify`)
- `/quickfix` can be invoked directly from the main session
- `/verify` can run against any branch, not just one produced by `/run-stories`

## Valid sequences

**Presearch pipeline**: clarify -> research -> briefing
**Ship pipeline**: plan-stories -> draft-plans -> env-preflight -> run-stories -> verify
**Shortcut**: any node can route to /quickfix when scope is small
**Standalone**: any node can be invoked independently with inline context
