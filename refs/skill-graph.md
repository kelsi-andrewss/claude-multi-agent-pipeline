# Skill Graph

## Architecture

Graph-based skill composition. Nodes are skills. Edges are typed JSON artifacts conforming to `refs/artifact-contract.md`. Routers are decision points that read scope and route_hint to determine the next node.

Two pipelines share this graph:

- **/presearch pipeline**: scope -> clarify+scout (parallel) -> briefing (produces `presearch/{slug}.md`)
- **/research pipeline**: scope -> web research -> /presearch (produces `presearch/{slug}.md` with web research context)
- **/ship pipeline**: plan-stories -> draft-plans -> env-preflight -> run-stories -> verify

/research wraps /presearch — not the other way around. /presearch is the core pipeline (no web search). /research adds web search then delegates to /presearch.

Any node can route to `/quickfix` when scope is small, short-circuiting the full pipeline.

## Router logic table

| After node | scope:small (<=3 files) | scope:standard |
|---|---|---|
| /scope (in presearch) | -> /quickfix | -> clarify+scout |
| /scope (in research) | -> /quickfix | -> web research -> /presearch |
| /briefing | -> /quickfix | -> /plan-stories |
| /draft-plans | skip critique | -> /critique --plans |
| /run-stories | skip verify | -> /verify |

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
| /scope | user input | `.scope-{slug}.json` | /presearch, /research |
| /clarify | user input, `.research-{slug}.json` (if exists) | `.clarify-{slug}.json` | /presearch |
| /scout | `.scope-{slug}.json`, `.research-{slug}.json` (if exists) | `.scout-{slug}.json` | /presearch |
| /research | `.scope-{slug}.json` | `.research-{slug}.json` | main session (wraps /presearch) |
| /briefing | `.clarify-{slug}.json`, `.scout-{slug}.json`, `.research-{slug}.json` | `presearch/{slug}.md` | /presearch |
| /plan-stories | `presearch/{slug}.md` | `.ship-manifest.json` | /ship |
| /draft-plans | `.ship-manifest.json` | `plans/*.md` | /ship |
| /env-preflight | `plans/*.md` | (no artifact -- side effects only) | /ship |
| /quickfix | artifact chain via --context | (inline -- no artifact) | /presearch or /ship |
| /verify | run-stories output | (no artifact -- pass/fail) | /ship |
| /critique | plans or agent output | (inline feedback) | /ship, /draft-plan |
| /presearch | user input, `.scope-{slug}.json`, `.research-{slug}.json` (optional) | `presearch/{slug}.md` (via sub-skills) | main session or /research |
| /ship | presearch output or user input | merged branch (via sub-skills) | main session |
| /run-stories | `plans/*.md`, stories DB | story branches | /ship |

## Artifact flow

```
/scope      -> .scope-{slug}.json
/research   -> .research-{slug}.json  (prev: [.scope-{slug}.json])
/clarify    -> .clarify-{slug}.json
/scout      -> .scout-{slug}.json     (prev: [.scope-{slug}.json, .research-{slug}.json if exists])
/briefing   -> presearch/{slug}.md    (prev: [.clarify-{slug}.json, .scout-{slug}.json, .research-{slug}.json if exists])
/plan-stories -> .ship-manifest.json
/draft-plans  -> plans/*.md
/env-preflight -> (no artifact -- side effects only)
/quickfix     -> (inline -- reads artifact chain via --context)
/verify       -> (no artifact -- pass/fail)
```

## Entry points

Any node can be invoked standalone. When invoked without upstream artifacts, the skill operates with whatever context is provided inline (user message, --context flag, or piped input). This means:

- `/presearch` runs the full pipeline without web research (scope -> clarify+scout -> briefing)
- `/research` runs web research then delegates to /presearch for the rest
- `/briefing` can run with only a `/scout` artifact (no `/research`)
- `/quickfix` can be invoked directly from the main session
- `/verify` can run against any branch, not just one produced by `/run-stories`

## Valid sequences

**Presearch pipeline**: scope -> clarify+scout -> briefing
**Research pipeline**: scope -> web research -> presearch (scope -> clarify+scout -> briefing)
**Ship pipeline**: plan-stories -> draft-plans -> env-preflight -> run-stories -> verify
**Shortcut**: any node can route to /quickfix when scope is small
**Standalone**: any node can be invoked independently with inline context
