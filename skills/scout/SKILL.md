---
name: scout
description: >
  Gemini seed scouting + web validation for implementation details. Finds APIs,
  packages, architecture patterns, and testable assertions. Accepts upstream
  knowledge context via --research flag. Parallel subagents (Gemini broad discovery,
  Claude deep extraction) with conflict detection and agent attribution.
  Reads .clarify-<slug>.json if provided. Writes .scout-<slug>.json with merged
  findings, URLs, API shapes, testable assertions, conflicts, and search queries.
  Use when the user says "/scout <topic>", "/scout --clarify presearch/.clarify-foo.json",
  "/scout --research presearch/.research-foo.json", or "/scout --deep <topic>".
args:
  - name: args
    type: string
    description: >
      Topic (quoted string or free text), optional flags: --clarify <path> (path to
      .clarify-<slug>.json), --research <path> (path to .research-<slug>.json
      knowledge synthesis artifact from upstream deep research), --deep (double
      search/fetch budgets for both agents).
---

# Scout Skill Invoked

User has requested: `/scout {{args}}`

---

## Step 0: Parse args

Parse `{{args}}` to extract:

- `--clarify <path>` -> path to a `.clarify-<slug>.json` artifact. Optional. The value is the next token after `--clarify`.
- `--research <path>` -> path to a `presearch/.research-<slug>.json` knowledge synthesis artifact. Optional. The value is the next token after `--research`.
- `--deep` -> flag to double search/fetch budgets for both agents. Boolean, no value.
- Everything remaining after flag stripping -> `topic`. Required. If empty after stripping flags, ask:
  ```
  AskUserQuestion: "What topic should I scout?"
  ```
  Wait for the user's response before proceeding.

**Slug derivation:**
- If `--clarify` was provided and the artifact contains a `slug` field: use that slug.
- If `--research` was provided and the artifact contains a `slug` field (and no slug from clarify): use that slug.
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
   - `data.decisions` -> resolved decisions (these are hard constraints for subagent prompts, not suggestions)
   - `data.constraints` -> constraints
   - `scope` -> scope metadata (files, stories, complexity)
   - `route_hint` -> routing hint
   - `slug` -> slug (overrides topic-derived slug)
   - `data.topic` -> use as topic if no topic was provided in args

**If not provided:** standalone mode. No upstream constraints. Proceed with topic only.

---

## Step 1.5: Load research context (if --research)

**If `--research <path>` was provided:**

1. Read the file at the given path using the Read tool.
2. Validate it matches the knowledge synthesis artifact contract:
   - Must have `slug` (string)
   - Must have `skill: "research"`
   - Must have `data` containing `synthesized_findings` (array) and `citations` (array)
3. If validation fails, stop and report:
   ```
   Error: <path> is not a valid research artifact. Expected slug, skill="research", and data with synthesized_findings/citations.
   ```
4. Extract from the artifact:
   - `data.synthesized_findings` -> domain knowledge findings (these inform what APIs/packages to scout for)
   - `data.citations` -> source URLs already discovered (avoid re-fetching)
   - `data.conflicts` -> unresolved conflicts to be aware of
   - `data.gaps` -> knowledge gaps that scout should try to fill
   - `slug` -> use as slug if no slug derived yet

**If not provided:** standalone mode. No upstream knowledge context.

---

## Step 2: Generate search focus areas

Analyze the topic (and clarify decisions if present, and research findings if present) to produce **3-5 specific search focus areas**. These focus areas are shared input to both subagent prompts, ensuring both agents cover the same dimensions without anchoring one to the other's findings.

Focus areas are short descriptions of what to investigate, NOT search queries. Agents derive their own queries from these. Examples:
- "Authentication flow and token management for <service>"
- "Rate limits and quota constraints for <API>"
- "Data model and schema requirements for <feature>"
- "Known breaking changes and migration paths for <package>"
- "Real-time sync architecture patterns for <use case>"

If `--clarify` was provided, the focus areas must reflect the clarify decisions. For example, if the decision was "use Firebase Auth, not Supabase Auth", the focus area should be about Firebase Auth specifically — not a generic "authentication options" focus area.

If `--research` was provided, prioritize focus areas that address the research gaps. Avoid duplicating focus areas for topics already well-covered by the upstream research findings -- focus on implementation specifics the domain research did not cover.

This is a reasoning-only step. No tool calls.

---

## Step 3: Launch parallel agents

Dispatch two background agents using the Agent tool with `run_in_background=true`. Both agents research independently — neither sees the other's work. This eliminates confirmation bias.

### Gemini agent

Launch: `Agent(subagent_type="gemini-researcher", prompt=<prompt below>, run_in_background=true)`

The Gemini agent prompt must be self-contained. Construct it as follows:

```
You are a technical researcher doing broad discovery on a topic. Your job is to find
as many relevant facts as possible across official docs, blog posts, StackOverflow,
GitHub issues, and release notes.

TOOLS: Use gemini_chat for all research. It has native Google Search grounding built in —
you do NOT need separate search tools.

TOPIC: <topic text>

SEARCH FOCUS AREAS (investigate all of these):
<numbered list of focus areas from Step 2>

BUDGET: Ask <BUDGET> research questions via gemini_chat. Each call should target a
different focus area or drill deeper into a promising finding. Prioritize breadth —
cover all focus areas before going deep on any one.

<if --clarify>
HARD CONSTRAINTS (from clarify phase — do NOT contradict these):
Decisions:
<list each decision: area, choice, reasoning>
Constraints:
<list each constraint: type, value>
</if --clarify>

<if --research>
Upstream knowledge context (from deep research phase):
Key findings:
<list synthesized_findings summaries>

Known gaps (prioritize scouting for these):
<list gaps>

Unresolved conflicts:
<list conflicts if any>

Use this domain knowledge to inform your implementation recommendations.
Focus on concrete APIs, packages, and architecture patterns that align with these findings.

Already-discovered URLs (skip these, find new sources):
<list citation URLs from research artifact>
</if --research>

OUTPUT: When done, write your findings to the file presearch/.scout-<slug>-gemini.json
using the Write tool. The file must be valid JSON matching this exact schema:

{
  "agent": "gemini",
  "slug": "<slug>",
  "status": "complete",
  "error": null,
  "claims": [
    {
      "text": "string — the factual claim, be specific (include numbers, versions, URLs)",
      "category": "api | package | architecture | data_model | gotcha",
      "source_urls": ["string — URLs that support this claim"],
      "search_queries": ["string — the queries that led to this claim"]
    }
  ]
}

If you encounter errors and can only partially complete, set "status": "partial" and
include whatever claims you gathered. If you fail completely, set "status": "failed"
and "error": "<what went wrong>".

RETURN: After writing the file, return ONLY this line:
DONE: <N> findings written to presearch/.scout-<slug>-gemini.json

Do NOT return the findings themselves. Do NOT ask questions. Do NOT use AskUserQuestion
or any interactive tools.
```

**Budget values:**
- Normal mode: `<BUDGET>` = "2-4"
- `--deep` mode: `<BUDGET>` = "4-8"

### Claude agent

Launch: `Agent(subagent_type="claude-researcher", prompt=<prompt below>, run_in_background=true)`

The Claude agent prompt must be self-contained. Construct it as follows:

```
You are a technical researcher doing deep extraction from web sources. Your job is to
find authoritative sources and extract precise, specific facts — API shapes, version
numbers, configuration requirements, exact error messages, code examples.

TOOLS: Use WebSearch to find sources, then WebFetch to extract content from the best results.

IMPORTANT — WebFetch needs targeted prompts. Do NOT use generic prompts like "summarize
this page". Instead, ask specific questions per fetch:
- "What is the authentication flow? What tokens are required? What are the token lifetimes?"
- "What are the rate limits? Are there different tiers? What happens when limits are exceeded?"
- "What is the response shape for the /api/v2/search endpoint? Include all fields."

IMPORTANT — Run WebSearch calls SEQUENTIALLY, not in parallel. Parallel searches trigger
429 rate limits. Do one search, process results, then do the next.

TOPIC: <topic text>

SEARCH FOCUS AREAS (investigate all of these):
<numbered list of focus areas from Step 2>

BUDGET:
- Run <SEARCH_BUDGET> WebSearch calls sequentially (one at a time)
- WebFetch the top <FETCH_BUDGET> results — prefer official docs, API references, GitHub repos
- For each fetch, ask specific extraction questions (not generic "summarize")

<if --clarify>
HARD CONSTRAINTS (from clarify phase — do NOT contradict these):
Decisions:
<list each decision: area, choice, reasoning>
Constraints:
<list each constraint: type, value>
</if --clarify>

<if --research>
Upstream knowledge context (from deep research phase):
Key findings:
<list synthesized_findings summaries>

Known gaps (prioritize scouting for these):
<list gaps>

Unresolved conflicts:
<list conflicts if any>

Use this domain knowledge to inform your implementation recommendations.
Focus on concrete APIs, packages, and architecture patterns that align with these findings.

Already-discovered URLs (skip these, find new sources):
<list citation URLs from research artifact>
</if --research>

OUTPUT: When done, write your findings to the file presearch/.scout-<slug>-claude.json
using the Write tool. The file must be valid JSON matching this exact schema:

{
  "agent": "claude",
  "slug": "<slug>",
  "status": "complete",
  "error": null,
  "claims": [
    {
      "text": "string — the factual claim, be specific (include numbers, versions, URLs)",
      "category": "api | package | architecture | data_model | gotcha",
      "source_urls": ["string — URLs that support this claim"],
      "search_queries": ["string — the queries that led to this claim"]
    }
  ]
}

If you encounter errors and can only partially complete, set "status": "partial" and
include whatever claims you gathered. If you fail completely, set "status": "failed"
and "error": "<what went wrong>".

RETURN: After writing the file, return ONLY this line:
DONE: <N> findings written to presearch/.scout-<slug>-claude.json

Do NOT return the findings themselves. Do NOT ask questions. Do NOT use AskUserQuestion
or any interactive tools.
```

**Budget values:**
- Normal mode: `<SEARCH_BUDGET>` = "2-4", `<FETCH_BUDGET>` = "max 3"
- `--deep` mode: `<SEARCH_BUDGET>` = "4-8", `<FETCH_BUDGET>` = "max 6"

---

## Step 4: Wait for agents and read intermediate files

Both agents were launched with `run_in_background=true`. Wait for notification that each agent has completed.

Once both agents have completed (or timed out), read the intermediate files:

1. Read `presearch/.scout-<slug>-gemini.json` using the Read tool.
2. Read `presearch/.scout-<slug>-claude.json` using the Read tool.

**Validate each file:**
- File exists and contains valid JSON
- Has `agent`, `slug`, `status`, and `claims` fields
- `status` is one of: `complete`, `partial`, `failed`

**Handle failure modes:**

- **Both succeed** (status `complete` or `partial`): Proceed to Step 5 with both datasets.
- **One fails** (file missing, invalid JSON, or `status: "failed"`): Proceed to Step 5 with the successful agent's data only. Set `partial_research = true`. Add to gaps: `"<agent> agent failed: <error message or 'file not found or invalid JSON'>"`.
- **Both fail**: Stop. Do not write a canonical artifact. Report:
  ```
  Scouting failed — both agents returned errors.

  Gemini: <error or "file not found">
  Claude: <error or "file not found">

  Suggestions:
  - Re-run with --deep for increased budgets
  - Check tool availability (gemini_chat, WebSearch, WebFetch)
  - Try a more specific topic
  ```

---

## Step 5: Merge findings

Combine both agents' claims into the canonical findings structure. If only one agent succeeded (partial failure), skip deduplication and conflict detection — attribute everything to the surviving agent.

### 5a: Transform claims to findings

Convert each intermediate `claim` to a canonical `finding`:

- `claim.text` -> split into `finding.summary` (first sentence or key assertion) and `finding.details` (full text)
- `claim.category` -> `finding.category` (direct mapping — same enum: `api`, `package`, `architecture`, `data_model`, `gotcha`)
- `claim.source_urls` -> contribute to the top-level `urls` array
- Set `finding.source`: gemini agent claims get `"gemini"`, claude agent claims get `"web"`
- Set `finding.agent_attribution`: `"gemini"` for gemini agent claims, `"claude"` for claude agent claims

### 5b: Deduplicate

Two findings are duplicates if they share the same `category` AND their `summary` text is substantially similar (same topic, same assertion, different phrasing).

Comparison method: normalize both summaries (lowercase, strip extra whitespace, remove trailing punctuation) and check if they describe the same fact. This is a structured text comparison — look for matching key terms, numbers, and subjects within the same category. Not NLP similarity scoring.

When duplicates are found:
- Keep the version with longer/more detailed `details` text
- Set `agent_attribution: "both"`
- Set `source: "both"`
- Merge `source_urls` from both findings

### 5c: Detect conflicts

After deduplication, scan remaining findings for contradictions. A conflict exists when two findings share the same `category` and are about the same subject, but assert different **concrete values**. Examples:
- Same API, different rate limits (100/min vs 1000/min)
- Same package, different minimum versions (v2.0 vs v3.0)
- Same service, different auth requirements (API key vs OAuth)

Conflicts are NOT:
- Different phrasing of the same fact (that's dedup — handled in 5b)
- One agent having info the other doesn't (that's complementary — both findings kept)
- Different aspects of the same topic (that's additive — both findings kept)

For each detected conflict, add to the `conflicts` array:
```json
{
  "subject": "string — what the conflict is about",
  "gemini_claim": "string — Gemini's assertion",
  "claude_claim": "string — Claude's assertion",
  "source_urls": {
    "gemini": ["URLs backing Gemini's claim"],
    "claude": ["URLs backing Claude's claim"]
  }
}
```

Conflicts are **surfaced, not resolved**. Both positions are preserved in findings. The downstream `/briefing` skill or human reviewer decides which is correct.

### 5d: Aggregate search queries

Collect all `search_queries` from both agents' claims into a top-level `search_queries` array. Deduplicate by exact string match (case-insensitive).

### 5e: Build urls array

Collect all `source_urls` from both agents' claims. Deduplicate by URL. For each URL, include:
- `url`: the URL string
- `title`: infer from the URL path or domain if no title available
- `relevance`: brief description of what this URL confirmed or provided

### 5f: Extract api_shapes and testable_assertions

From the merged findings:

**api_shapes**: Extract from findings with `category: "api"` that describe endpoint shapes. Structure:
```json
{
  "service": "string",
  "endpoint": "string",
  "method": "string",
  "auth": "string",
  "response_shape": "string or object"
}
```

**testable_assertions**: Extract from all findings where the claim is specific enough to verify. Structure:
```json
{
  "category": "api_edge_case | data_constraint | integration_boundary | package_constraint",
  "assertion": "string — the testable claim",
  "source": "gemini | web:<url> | both",
  "confidence": "verified | likely | uncertain"
}
```

Confidence levels:
- `verified`: claim confirmed by both agents or backed by official documentation URL
- `likely`: claim from one agent with a credible source URL
- `uncertain`: claim from one agent without source URL or from a non-authoritative source

---

## Step 6: Write canonical artifact

Write the merged output to `presearch/.scout-<slug>.json`.

**Schema:**

```json
{
  "slug": "<slug>",
  "scope": {
    "files": "<number or null>",
    "stories": "<number or null>",
    "complexity": "<small | medium | large | null>"
  },
  "route_hint": "<from clarify if available, else null>",
  "prev": ["<clarify artifact path if --clarify was used>", "<research artifact path if --research was used>"],
  "skill": "scout",
  "data": {
    "topic": "<original topic text>",
    "findings": [
      {
        "category": "api | package | architecture | data_model | gotcha",
        "summary": "string",
        "details": "string — full finding text",
        "source": "gemini | web | both",
        "agent_attribution": "gemini | claude | both"
      }
    ],
    "conflicts": [
      {
        "subject": "string",
        "gemini_claim": "string",
        "claude_claim": "string",
        "source_urls": {
          "gemini": ["string"],
          "claude": ["string"]
        }
      }
    ],
    "search_queries": ["string — all queries used by both agents, deduplicated"],
    "partial_research": false,
    "urls": [
      {
        "url": "string",
        "title": "string",
        "relevance": "string"
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
      "string — topics where scouting failed or was incomplete"
    ]
  }
}
```

**Field rules:**
- If `scope` and `route_hint` came from the clarify artifact, preserve them as-is.
- If standalone (no `--clarify`): set scope fields to null, route_hint to null. The briefing skill determines these.
- `prev`: array containing all upstream artifact paths. Include the clarify artifact path if `--clarify` was used, and the research artifact path if `--research` was used. Empty array if neither was used.
- `conflicts`: empty array if no conflicts detected.
- `search_queries`: aggregated from both agents, deduplicated.
- `partial_research`: `true` only if one agent failed. `false` by default.
- `gaps`: empty array if all scouting succeeded and both agents completed.

---

## Step 7: Report

Print:
```
Scout complete.

Topic: <topic>
Agents: <which agents completed> (e.g., "gemini + claude" or "claude only (gemini failed)")
Findings: <count> across <category count> categories (<gemini-only> gemini, <claude-only> claude, <both> both)
Conflicts: <count> (or "none")
URLs: <count> sources consulted
Search queries: <count> used
Testable assertions: <count> (<verified count> verified, <uncertain count> uncertain)
Gaps: <list or "none">

Output: presearch/.scout-<slug>.json
```

If `partial_research` is true, prepend:
```
WARNING: Partial scouting — <agent> agent failed. Results may have reduced coverage.
```

If `--research` was used, also print: `Upstream: <research artifact path>`
If `--clarify` was used, also print: `Upstream: <clarify artifact path>`

Do NOT prompt to run /briefing or any downstream skill. This skill writes its artifact and reports. Routing is the orchestrator's job.
