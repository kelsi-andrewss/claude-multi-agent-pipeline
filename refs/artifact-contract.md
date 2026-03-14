# Artifact Contract

## Purpose

Skills exchange data through typed JSON artifact files. This contract defines the header schema that all artifacts share. Each skill documents its own `data` payload in its SKILL.md; this contract governs only the envelope.

## Schema

```json
{
  "slug": "string",
  "skill": "string",
  "scope": {
    "files": "number",
    "stories": "number",
    "complexity": "string"
  },
  "route_hint": "string | null",
  "prev": ["string"],
  "data": {}
}
```

## Field definitions

### slug

URL-safe identifier for the work unit. Derived from the epic or story title. Used in file naming and cross-references.

### skill

Name of the skill that produced this artifact. Matches the directory name under `skills/` (e.g., `scope`, `clarify`, `research`, `scout`, `briefing`).

### scope

Estimated size of the work unit. Three subfields:

- **files** — number of write-target files
- **stories** — number of stories expected
- **complexity** — one of `small`, `medium`, `large`

Complexity thresholds:

| Complexity | Files | Stories | Rule |
|---|---|---|---|
| small | <=3 | 1 | Straightforward changes, single story |
| medium | 4-10 | 2-5 | Multiple files or stories |
| large | >10 | >5 | Either dimension exceeds medium |

Complexity is the max of the two dimensions: 4 files and 1 story = medium (files drives it).

### route_hint

Advisory suggestion for which skill should run next. Routers always have final say — a `route_hint` is a suggestion, not an instruction. Set to `null` when the skill has no routing opinion.

### prev

Array of artifact file paths that this artifact depends on. Always an array, even for a single predecessor. Supports graph merges where a skill reads from multiple upstream artifacts (e.g., `/briefing` reads both `.clarify-{slug}.json` and `.research-{slug}.json`).

Walking the artifact chain: follow `prev` pointers recursively to reconstruct the full context chain. The standard pipeline chain is: scope -> research -> clarify + scout -> briefing. Not all links are present in every chain (research is conditional, scope is skipped in refine mode).

### data

Freeform object. Contents are skill-specific and documented in each skill's SKILL.md. The contract imposes no structure on `data` beyond requiring it to be a JSON object.

#### Research extensions

Research artifacts (`presearch/.research-<slug>.json`) include these fields inside `data`:

##### partial_research

Type: `boolean`. Default: `false`.

When `true`, indicates research results are incomplete because one or both models failed for some angles. **Constraint:** when `partial_research` is `true`, the `gaps` array must describe what failed.

##### agent_attribution

Type: `"gemini" | "claude" | "both"`. Default: omitted.

Set on individual claims in `synthesized_findings`. Maps each claim to its originating model. When both models independently find the same fact, attribution is `"both"`.

##### conflicts

Type: `array`. Default: `[]`.

Records disagreements between Gemini and Claude research results. Both positions and sources are preserved for downstream resolution by `/briefing`.

Entry schema:

| Field | Type | Description |
|---|---|---|
| `topic` | `string` | What the conflict is about |
| `gemini_claim` | `{ claim: string, source_urls: string[] }` | Gemini's position with sources |
| `claude_claim` | `{ claim: string, source_urls: string[] }` | Claude's position with sources |
| `credibility_assessment` | `string` | Which source is more authoritative and why |

#### Scout extensions

Scout artifacts (`presearch/.scout-<slug>.json`) include these fields inside `data`. Scout does project introspection — no web research.

##### conflicts (scout)

Type: `array`. Default: `[]`.

Records disagreements between codebase reality and upstream research suggestions. Each entry captures what the codebase requires vs what research recommended.

| Field | Type | Description |
|---|---|---|
| `subject` | `string` | What the conflict is about |
| `codebase_says` | `string` | What the project does/requires |
| `research_says` | `string` | What web research suggested |
| `resolution` | `string` | Which should win and why |

##### decisions_relevant

Type: `array`. Default: `[]`.

Recorded decisions from `pm_list_decisions` that affect the current work. Each entry has `id`, `summary`, and `impact`.

## File naming

- **Root-level intermediate artifacts**: `.{skill}-{slug}.json` (dot-prefixed, gitignored)
- **Presearch-directory intermediate artifacts**: `presearch/.{skill}-{slug}.json` (under presearch/, gitignored)
- **Final briefings**: `presearch/{slug}.md` (human-readable markdown, tracked in git)

Examples for the full pipeline:
- `.scope-add-presence-cursors.json` (scope artifact, root)
- `.clarify-add-presence-cursors.json` (clarify artifact, root)
- `presearch/.research-add-presence-cursors.json` (knowledge synthesis from /research)
- `presearch/.scout-add-presence-cursors.json` (implementation research from /scout)
- `presearch/add-presence-cursors.md` (final briefing)

## Skill-specific artifact schemas

### Scope artifact

- **File naming**: `.scope-<slug>.json` (dot-prefixed, root directory)
- **`skill`**: `"scope"`
- **`prev`**: always `[]` — scope is the chain root
- **`data` payload**:

| Field | Type | Description |
|---|---|---|
| `topic` | `string` | Original topic text |
| `what` | `string \| null` | What is being built (null if `--skip-qa`) |
| `audience` | `string \| null` | Who it's for (null if `--skip-qa`) |
| `platform` | `string \| null` | Target platform (null if `--skip-qa`) |
| `in_scope` | `string[] \| null` | Must-include items (null if `--skip-qa`) |
| `out_of_scope` | `string[] \| null` | Explicitly excluded items (null if `--skip-qa`) |
| `stack_detected` | `array` | Detected project stack markers |
| `needs_research` | `boolean` | Whether /research should run before clarify |
| `complexity_reasoning` | `string` | One sentence explaining the classification |

### Knowledge synthesis artifact (from /research)

- **File naming**: `presearch/.research-<slug>.json` (under presearch/, intermediate)
- **`skill`**: `"research"`
- **`prev`**: `["<scope artifact path>"]` if `--scope` was used, else `[]`
- **`scope`**: always null fields — research does not estimate implementation scope
- **`route_hint`**: always null — routing is the orchestrator's decision
- **`data` payload**:

| Field | Type | Description |
|---|---|---|
| `topic` | `string` | Original topic text |
| `angles_generated` | `number` | Number of angles after dedup |
| `partial_research` | `boolean` | Whether any subagent failed |
| `synthesized_findings` | `array` | Themed findings with claims, sources, confidence |
| `angle_summaries` | `array` | Per-angle summaries with source attribution |
| `citations` | `array` | Deduplicated source URLs with quality ratings |
| `conflicts` | `array` | Disagreements between subagents |
| `gaps` | `string[]` | Topics with thin or no results |

Note: This is the NEW /research skill's output (deep web research with fan-out/fan-in parallelism), distinct from the old /research (now /scout).

### Scout artifact (project introspection)

- **File naming**: `presearch/.scout-<slug>.json`
- **`skill`**: `"scout"`
- **`prev`**: array containing upstream artifact paths (clarify and/or research if provided)
- **`data` payload**:

| Field | Type | Description |
|---|---|---|
| `topic` | `string` | Original topic text |
| `findings` | `array` | Codebase findings with category, summary, details, files, source |
| `decisions_relevant` | `array` | Recorded decisions that affect this work |
| `testable_assertions` | `array` | Verifiable claims from codebase analysis |
| `write_targets` | `string[]` | Files that would likely be modified |
| `read_targets` | `string[]` | Files needed for context |
| `conflicts` | `array` | Codebase vs research disagreements (if research provided) |
| `gaps` | `string[]` | Areas with no established codebase pattern |

Scout does NOT do web research. It introspects the project: reads code, queries the decisions DB (`pm_list_decisions`), and searches OpenMemory. Web research is `/research`'s job.

### Artifact chain

The standard pipeline produces this chain (not all links present in every run):

```
.scope-<slug>.json          prev: []
       |
       v
presearch/.research-<slug>.json   prev: [".scope-<slug>.json"]     (conditional)
       |
       v
.clarify-<slug>.json        prev: ["presearch/.research-<slug>.json"]  (or [] if research skipped)
       +
presearch/.scout-<slug>.json     prev: [".clarify-<slug>.json", "presearch/.research-<slug>.json"]
       |
       v
presearch/<slug>.md          (briefing walks the full chain via prev pointers)
```

Briefing walks the `prev` pointers from the scout artifact to reconstruct the full context. When research was skipped, the chain is shorter: scope -> clarify + scout -> briefing.

## Conventions

- `prev` is always an array, even for single predecessor — no special-casing needed
- `route_hint` is advisory — routers have final say
- `scope.complexity` is derived from `scope.files` and `scope.stories` using the thresholds above
- Stale artifacts are cleaned up by the `/cleanup` skill
- Skills that produce no artifact (e.g., `/env-preflight`, `/verify`) document this in their SKILL.md
- During the transition period, consumers should accept both `skill: "research"` and `skill: "scout"` when looking for scout artifacts, as old artifacts may still exist with the old skill name
