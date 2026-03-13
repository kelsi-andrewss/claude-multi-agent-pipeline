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

Name of the skill that produced this artifact. Matches the directory name under `skills/` (e.g., `clarify`, `research`, `briefing`).

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

Walking the artifact chain: follow `prev` pointers recursively to reconstruct the full context chain.

### data

Freeform object. Contents are skill-specific and documented in each skill's SKILL.md. The contract imposes no structure on `data` beyond requiring it to be a JSON object.

#### Research extensions

Research artifacts (`.research-<slug>.json`) include the following optional fields inside `data`. All are backward-compatible — artifacts that predate these fields remain valid.

##### partial_research

Type: `boolean`. Default: `false`.

When `true`, indicates research results are incomplete because one of the parallel research subagents failed. **Constraint:** when `partial_research` is `true`, the existing `gaps` array must contain at least one entry describing the failure (which agent failed, what error occurred).

##### agent_attribution

Type: `"gemini" | "claude" | "both"`. Default: omitted.

Set on individual entries in the `findings` array. Maps each finding back to its originating subagent. When both agents independently produce the same finding (matched by category and subject), attribution is `"both"`. Findings produced before this feature was introduced omit the field entirely — consumers should treat a missing `agent_attribution` as unknown provenance.

```json
{
  "findings": [
    {
      "agent_attribution": "gemini",
      "...existing fields..."
    },
    {
      "agent_attribution": "both",
      "...existing fields..."
    }
  ]
}
```

##### conflicts

Type: `array`. Default: `[]`.

Records disagreements between the Gemini and Claude subagents. Each entry captures both positions and their supporting sources so downstream consumers (e.g., `/briefing`) can surface contradictions rather than silently picking one.

Entry schema:

| Field | Type | Description |
|---|---|---|
| `subject` | `string` | What the conflict is about (e.g., "API rate limit for /v2/search") |
| `gemini_claim` | `string` | The Gemini agent's position |
| `claude_claim` | `string` | The Claude agent's position |
| `source_urls` | `{ gemini: string[], claude: string[] }` | Supporting URLs from each agent |

```json
{
  "conflicts": [
    {
      "subject": "Default timeout for WebSocket connections",
      "gemini_claim": "30 seconds",
      "claude_claim": "60 seconds",
      "source_urls": {
        "gemini": ["https://example.com/docs/ws"],
        "claude": ["https://example.com/api/reference#timeout"]
      }
    }
  ]
}
```

##### search_queries

Type: `string[]`. Default: `[]`.

Aggregates all search queries used by both subagents during the research process. Serves as an audit trail of the discovery path — useful for debugging coverage gaps, understanding what was searched, and reproducing results.

## File naming

- **Intermediate artifacts**: `.{skill}-{slug}.json` (dot-prefixed, gitignored)
- **Final briefings**: `presearch/{slug}.md` (human-readable markdown, tracked in git)

Examples:
- `.clarify-add-presence-cursors.json`
- `.research-add-presence-cursors.json`
- `presearch/add-presence-cursors.md`

## Conventions

- `prev` is always an array, even for single predecessor — no special-casing needed
- `route_hint` is advisory — routers have final say
- `scope.complexity` is derived from `scope.files` and `scope.stories` using the thresholds above
- Stale artifacts are cleaned up by the `/cleanup` skill
- Skills that produce no artifact (e.g., `/env-preflight`, `/verify`) document this in their SKILL.md
