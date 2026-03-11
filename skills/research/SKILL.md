---
name: research
description: >
  Gemini seed research + web validation for a technical topic. Extracts testable
  assertions from findings. Reads .clarify-<slug>.json if provided. Writes
  .research-<slug>.json with raw findings, URLs, API shapes, and test-relevant
  edge cases. Use when the user says "/research <topic>",
  "/research --clarify presearch/.clarify-foo.json", or "/research --deep <topic>".
args:
  - name: args
    type: string
    description: >
      Topic (quoted string or free text), optional flags: --clarify <path> (path to
      .clarify-<slug>.json), --deep (double web search/fetch budget).
---

# Research Skill Invoked

User has requested: `/research {{args}}`

---

## Step 0: Parse args

Parse `{{args}}` to extract:

- `--clarify <path>` -> path to a `.clarify-<slug>.json` artifact. Optional. The value is the next token after `--clarify`.
- `--deep` -> flag to double web search/fetch budget. Boolean, no value.
- Everything remaining after flag stripping -> `topic`. Required. If empty after stripping flags, ask:
  ```
  AskUserQuestion: "What topic should I research?"
  ```
  Wait for the user's response before proceeding.

**Slug derivation:**
- If `--clarify` was provided and the artifact contains a `slug` field: use that slug.
- Otherwise: topic text lowercased, spaces to hyphens, non-alphanumeric stripped, truncated to 40 chars.

---

## Step 1: Load clarify context (if --clarify)

**If `--clarify <path>` was provided:**

1. Read the file at the given path using the Read tool.
2. Validate it matches the artifact contract:
   - Must have `slug` (string)
   - Must have `skill: "clarify"`
   - Must have `data` containing `decisions` (array) and `constraints` (array)
3. If validation fails, stop and report:
   ```
   Error: <path> is not a valid clarify artifact. Expected slug, skill="clarify", and data with decisions/constraints.
   ```
4. Extract from the artifact:
   - `data.decisions` -> resolved decisions (these are hard constraints for the Gemini prompt, not suggestions)
   - `data.constraints` -> constraints
   - `scope` -> scope metadata (files, stories, complexity)
   - `route_hint` -> routing hint
   - `slug` -> slug (overrides topic-derived slug)
   - `data.topic` -> use as topic if no topic was provided in args

**If not provided:** standalone mode. No upstream constraints. Proceed with topic only.

---

## Step 2: Seed research with Gemini

1. Load Gemini: `ToolSearch: select:mcp__gemini__gemini_chat`
2. Call `gemini_chat` with this research prompt:

```
You are a technical researcher. Given a project idea, identify:
- Key APIs/services needed (with endpoint shapes, auth flows)
- SDK packages (exact names, versions, install commands)
- Architecture patterns and framework recommendations
- Data models (entities, relationships, key fields)
- Known gotchas (rate limits, breaking changes, version incompatibilities)
- Testable assertions: for each finding, extract concrete claims that can be verified
  (API returns X shape, package requires Y version, rate limit is Z/minute, auth flow
  requires N steps). These must be specific enough to write a test or validation check.

Be specific — include real endpoint shapes, not guesses. Flag anything uncertain.

Topic: <topic text>
```

**If clarify context exists**, append to the prompt:
```
Hard constraints (from clarify phase — do not contradict these):
Decisions:
<list each decision: area, choice, reasoning>

Constraints:
<list each constraint: type, value>
```

3. Parse Gemini's response into structured categories: findings, api_shapes, packages, gotchas, testable_assertions. Hold these for cross-referencing in Step 3.

---

## Step 3: Web research

Extract search queries from Gemini's response. Focus on the most critical unknowns: API docs, SDK docs, framework guides, version compatibility.

1. Load web tools: `ToolSearch: select:WebSearch,WebFetch`
2. Run 2-4 `WebSearch` calls in parallel for the most important topics.
3. `WebFetch` the top results (prefer official docs) — max 3 fetches.
4. If `--deep`: double the budget (4-8 searches, up to 6 fetches).
5. If any searches or fetches fail, continue with whatever succeeded. Track gaps — these become entries in the output `gaps` array.

**Cross-reference** web results against Gemini's claims:
- Confirm or correct API shapes, package versions, endpoint URLs
- Update testable assertions with verified data
- Mark each assertion's confidence: `verified` (confirmed by official docs), `likely` (consistent with web results but not directly confirmed), `uncertain` (Gemini-only, no web corroboration)

---

## Step 4: Extract testable assertions

Review all findings (Gemini seed + web validation) and extract testable assertions in these categories:

- **api_edge_case**: rate limits, error response shapes, auth failure modes, pagination behavior
- **data_constraint**: required fields, valid ranges, relationships, uniqueness constraints
- **integration_boundary**: what can break between services, version compatibility requirements, protocol expectations
- **package_constraint**: minimum versions, peer dependency requirements, breaking changes between versions

Each assertion must be concrete enough to inform a test case. Structure:
```json
{
  "category": "api_edge_case | data_constraint | integration_boundary | package_constraint",
  "assertion": "string — the testable claim",
  "source": "gemini | web:<url> | both",
  "confidence": "verified | likely | uncertain"
}
```

Assertions that were confirmed by web research should cite the URL in source. Assertions from Gemini only should be marked `uncertain` unless the information is widely known and stable.

---

## Step 5: Write output artifact

Write the artifact to `presearch/.research-<slug>.json`.

**Schema** (follows the artifact contract from refs/skill-graph.md):

```json
{
  "slug": "<slug>",
  "scope": {
    "files": <number or null>,
    "stories": <number or null>,
    "complexity": "<small | medium | large> or null"
  },
  "route_hint": "<from clarify if available, else null>",
  "prev": "<clarify artifact path if --clarify was used, else null>",
  "skill": "research",
  "data": {
    "topic": "<original topic text>",
    "findings": [
      {
        "category": "api | package | architecture | data_model | gotcha",
        "summary": "string",
        "details": "string — full finding text",
        "source": "gemini | web | both"
      }
    ],
    "urls": [
      {
        "url": "string",
        "title": "string",
        "relevance": "string — what this URL confirmed or provided"
      }
    ],
    "api_shapes": [
      {
        "service": "string",
        "endpoint": "string",
        "method": "string",
        "auth": "string",
        "response_shape": "string or object"
      }
    ],
    "testable_assertions": [
      {
        "category": "api_edge_case | data_constraint | integration_boundary | package_constraint",
        "assertion": "string",
        "source": "gemini | web:<url> | both",
        "confidence": "verified | likely | uncertain"
      }
    ],
    "gaps": [
      "string — topics where web research failed or was incomplete"
    ]
  }
}
```

**Field rules:**
- If `scope` and `route_hint` came from the clarify artifact, preserve them as-is.
- If standalone (no `--clarify`): set scope fields to null, route_hint to null. The briefing skill determines these.
- `prev`: set to the clarify artifact path if `--clarify` was used, otherwise null.
- `gaps`: empty array if all web research succeeded.

---

## Step 6: Report

Print:
```
Research complete.

Topic: <topic>
Findings: <count> across <category count> categories
URLs: <count> sources consulted
API shapes: <count> documented
Testable assertions: <count> (<verified count> verified, <uncertain count> uncertain)
Gaps: <list or "none">

Output: presearch/.research-<slug>.json
```

If `--clarify` was used, also print: `Upstream: <clarify artifact path>`

Do NOT prompt to run /briefing or any downstream skill. This skill writes its artifact and reports. Routing is the orchestrator's job.
