---
name: research
description: >
  Deep web research + full presearch pipeline. Runs /scope, then fan-out/fan-in web
  research (Claude + Gemini in parallel), then calls /presearch with the research
  artifact to complete the pipeline (clarify+scout -> briefing). Use when web research
  is needed before building. Use when the user says "/research <topic>",
  "/research --scope .scope-foo.json <topic>", or "/research --deep <topic>".
args:
  - name: args
    type: string
    description: >
      Topic (quoted string or free text), optional flags: --scope <path> (path to
      .scope-<slug>.json), --deep (increases research budgets for both models),
      --no-ship (produce briefing but don't prompt to ship), --quick (skip Q&A in clarify).
---

# Research Skill Invoked

User has requested: `/research {{args}}`

---

## Step 0: Parse args

Parse `{{args}}` to extract:

**Flags** (strip from args after detection):
- `--scope <path>` -- path to a `.scope-<slug>.json` artifact. Optional.
- `--deep` -- increases research budgets. Boolean. Also passed to /presearch.
- `--no-ship` -- produce briefing but don't prompt to ship. Passed to /presearch.
- `--quick` -- skip Q&A in clarify. Passed to /presearch.

Everything remaining after flag stripping is the `topic`.

**If no topic and no --scope**: prompt the user with `AskUser`: "What topic should I research?" and stop until answered.

**Slug derivation**: from scope artifact's `slug` field if `--scope` provided, otherwise from topic text (lowercase, hyphenated, max 40 chars, strip articles and filler words).

---

## Step 1: Scope

If `--scope <path>` provided:
1. Read the file. Validate it has `skill: "scope"` and `data` with `topic`, `needs_research`.
2. Extract: `data.topic` (use as topic if none in args), `data.stack_detected`, `data.in_scope`, `data.out_of_scope`.
3. These become context constraints for angle generation -- angles must respect scope boundaries.

If `--scope` NOT provided:
1. Invoke: `Skill: scope, args: "<topic>"`
2. After /scope completes, read `.scope-<slug>.json`. Update the local slug if the artifact produced a different one.
3. Set `scope_path = ".scope-<slug>.json"` for later use.
4. Extract the same fields as above for angle generation constraints.

If the scope file does not exist (when --scope was explicitly provided): error with "File not found: <path>." and stop.

---

## Step 2: Fan-out -- angle generation (Claude + Gemini)

Two independent angle generation calls. Neither sees the other's output.

**Claude angles** (main session inline reasoning -- no tool call needed):

Generate 3-5 research angles for the topic. Each angle is:
```json
{
  "angle": "string -- subtopic name",
  "queries": ["3-5 search query strings"],
  "hypothesis": "string -- what to validate",
  "scope_boundary": "string -- what NOT to research"
}
```

If scope constraints exist from Step 1, respect `out_of_scope` -- do not generate angles that fall outside scope boundaries.

**Gemini angles** (via gemini_chat -- launch in parallel with Claude's inline reasoning):

1. Load Gemini: `ToolSearch: select:mcp__gemini__gemini_chat`
2. Call `gemini_chat` with prompt:
```
You are a research decomposition specialist. Given a topic, suggest 3-5 independent
research angles that would build comprehensive understanding. Each angle should target
a different dimension of the topic (theoretical foundations, practical applications,
current state-of-the-art, common pitfalls, alternative approaches).

For each angle, provide:
- angle: subtopic name
- queries: 3-5 specific web search queries
- hypothesis: what you expect to find
- scope_boundary: what this angle should NOT cover

Topic: <topic>
<scope constraints if available from Step 1: in_scope, out_of_scope, stack_detected>
```

**Why independent generation matters:** Gemini's broad grounding catches angles Claude's training data may miss. Claude's reasoning catches conceptual angles Gemini's retrieval may skip. Additive merge maximizes coverage without confirmation bias (decision-64).

---

## Step 3: Dedup and merge angles

Merge Claude and Gemini angle lists:

1. Compare angles by semantic overlap -- angles targeting the same subtopic from both sources merge into one (keep the better queries from each, mark source as `"both"`).
2. Angles unique to one source pass through unchanged (mark source as `"claude"` or `"gemini"`).
3. Cap at 6 angles total. If more than 6 after dedup, prioritize by:
   (a) angles both sources identified (higher signal),
   (b) angles that cover scope-defined priorities,
   (c) drop the most speculative/niche angles.
4. If fewer than 4 angles after dedup, use what is available -- do not pad with artificial angles.

Output: array of 4-6 research angle objects, each with merged queries and source attribution.

---

## Step 4: Fan-out -- parallel research (Gemini + Claude)

Both models research simultaneously. Launch everything in a single message.

### 4a: Gemini research (via gemini_chat)

For each angle, call `gemini_chat` with grounded search. Gemini has native Google Search grounding -- it searches the web as part of its response.

Call `gemini_chat` once per angle (up to 6 calls, launched in parallel if the tool supports it, otherwise sequential):

```
Research this topic thoroughly using web search grounding.

Angle: <angle.angle>
Hypothesis: <angle.hypothesis>
Scope boundary (do NOT research): <angle.scope_boundary>
Starting queries: <angle.queries, one per line>

Return your findings as JSON:
{
  "angle": "<angle name>",
  "findings": [
    {"claim": "string -- specific factual claim", "source_url": "string", "confidence": "high|medium|low"}
  ],
  "key_insights": ["top 3 takeaways"],
  "gaps": ["topics you couldn't find reliable information on"]
}

Be specific. Include version numbers, API endpoints, exact limits, dates. Every claim must cite a source URL.
```

Budget:
- Normal: 1 `gemini_chat` call per angle
- `--deep`: 2 `gemini_chat` calls per angle (first broad, second drilling into findings)

### 4b: Claude research (via background subagents)

Launch one `general-purpose` subagent per angle, all in the same message with `run_in_background: true`:

```
For each angle:
  Agent(subagent_type="general-purpose", run_in_background=true, prompt=<brief>)
```

**Subagent research brief:**

```
You are a web researcher. Find authoritative sources on a specific topic and extract
precise facts.

Angle: <angle.angle>
Hypothesis: <angle.hypothesis>
Scope boundary (do NOT research): <angle.scope_boundary>
Starting queries: <angle.queries, one per line>

Instructions:
- Use WebSearch to find sources, then WebFetch to extract specific facts from the best results.
- Run WebSearch calls SEQUENTIALLY (parallel searches trigger 429 rate limits).
- For WebFetch, ask specific extraction questions -- not "summarize this page."
- Prefer official documentation, academic papers, and primary sources over SEO content.
- Be specific: version numbers, API shapes, exact limits, dates, code examples.

Budget: <SEARCH_BUDGET> WebSearch calls, WebFetch the top <FETCH_BUDGET> results.

When done, return ONLY a JSON object (no markdown fencing, no preamble):
{
  "angle": "<angle name>",
  "findings": [
    {"claim": "string", "source_url": "string", "confidence": "high|medium|low"}
  ],
  "key_insights": ["top 3 takeaways"],
  "sources_consulted": [{"url": "string", "title": "string", "quality": "authoritative|informative|low-quality"}],
  "gaps": ["topics you couldn't find reliable information on"]
}
```

Budget values:
- Normal: `<SEARCH_BUDGET>` = "2-3", `<FETCH_BUDGET>` = "2"
- `--deep`: `<SEARCH_BUDGET>` = "4-6", `<FETCH_BUDGET>` = "4"

---

## Step 5: Collect results

Wait for all Claude subagents to complete. Gemini results are already available (inline calls).

**For each angle, you now have up to two result sets:**
- Gemini's findings (from gemini_chat response)
- Claude subagent's findings (from agent return)

**Handle failures:**
- If a Gemini call fails: proceed with Claude results for that angle.
- If a Claude subagent fails or returns malformed output: proceed with Gemini results for that angle.
- If both fail for an angle: add the angle to `gaps`, set `partial_research: true`.
- If ALL angles fail completely: write artifact with empty findings, full gaps, `partial_research: true`. Report failure.

---

## Step 6: Fan-in -- synthesis and merge

### 6a: Deduplicate findings

Compare claims across Gemini and Claude results for each angle:
- Same claim from both models: merge, keep higher-confidence version, collect all source URLs, set `agent_attribution: "both"`.
- Unique claims: pass through, set `agent_attribution: "gemini"` or `"claude"`.

Then deduplicate across angles -- claims about the same fact from different angles merge.

Group findings by theme (not by source angle) for the synthesized output.

### 6b: Detect conflicts

When Gemini and Claude report contradictory claims about the same subject:
- Flag both positions with their sources.
- Assess source credibility (official docs > academic papers > blog posts > forum answers).
- Do NOT silently resolve -- record both sides in the `conflicts` array.
- Additive merge with conflict flags, not consensus filtering (decision-64).

### 6c: Track citations

- Every claim in synthesized_findings must trace to at least one source URL.
- Deduplicate URLs across all results.
- Rate each source: `authoritative` (official docs, academic), `informative` (quality blog, conference talk), `low-quality` (SEO content, outdated).

### 6d: Identify gaps

- Angles that produced thin results (fewer than 2 findings from both models combined).
- Topics both models flagged as under-documented.
- Claims with only low-quality sources.

**Source quality bias mitigation:** If a finding is supported only by SEO-style content, downgrade confidence to `low` and add the topic to gaps.

**Context bloat mitigation:** The final `synthesized_findings` array should contain 10-20 themed findings, not a dump of all raw claims.

---

## Step 7: Write output artifact

Write to `presearch/.research-<slug>.json`.

**Schema** (conforms to `refs/artifact-contract.md`):

```json
{
  "slug": "<slug>",
  "skill": "research",
  "scope": {
    "files": null,
    "stories": null,
    "complexity": null
  },
  "route_hint": null,
  "prev": ["<scope artifact path if --scope was used>"],
  "data": {
    "topic": "<original topic text>",
    "angles_generated": "<number of angles after dedup>",
    "partial_research": false,
    "synthesized_findings": [
      {
        "theme": "string -- grouping label",
        "claims": [
          {
            "claim": "string",
            "source_urls": ["string"],
            "confidence": "high|medium|low",
            "agent_attribution": "gemini|claude|both"
          }
        ],
        "key_insight": "string -- most important takeaway for this theme"
      }
    ],
    "angle_summaries": [
      {
        "angle": "string -- angle name",
        "source": "claude|gemini|both",
        "finding_count": "number",
        "key_insights": ["string"]
      }
    ],
    "citations": [
      {
        "url": "string",
        "title": "string",
        "quality": "authoritative|informative|low-quality",
        "referenced_by": ["angle names"]
      }
    ],
    "conflicts": [
      {
        "topic": "string -- what the conflict is about",
        "gemini_claim": {"claim": "string", "source_urls": ["string"]},
        "claude_claim": {"claim": "string", "source_urls": ["string"]},
        "credibility_assessment": "string -- which source is more authoritative and why"
      }
    ],
    "gaps": [
      "string -- topics with thin or no results"
    ]
  }
}
```

**Field rules:**
- `scope`: always null fields -- research does not estimate implementation scope.
- `route_hint`: always null -- routing is the orchestrator's decision.
- `prev`: array containing scope artifact path if `--scope` was used, otherwise `[]`.
- `partial_research`: `true` if any angle had both models fail, `false` otherwise.
- `conflicts`: empty array if no contradictions found.
- `gaps`: empty array if all angles produced solid results.

---

## Step 8: Report research phase

```
Research complete.

Topic: <topic>
Angles: <count> researched
Findings: <count> across <theme count> themes (<gemini-only> gemini, <claude-only> claude, <both> corroborated)
Citations: <count> sources (<authoritative count> authoritative)
Conflicts: <count>
Gaps: <list or "none">

Output: presearch/.research-<slug>.json
```

If `partial_research` is true: `Warning: partial results -- some angles failed. Gaps noted in artifact.`

---

## Step 9: Invoke /presearch with research artifact

Build the presearch args:
- Start with: `--scope <scope_path> --research presearch/.research-<slug>.json`
- If `--deep` flag is set: add `--deep`
- If `--quick` flag is set: add `--quick`
- If `--no-ship` flag is set: add `--no-ship`
- Append the topic at the end

Invoke:

```
Skill: presearch, args: "<constructed args> <topic>"
```

/presearch handles clarify+scout (parallel) -> briefing -> report internally. It will skip its own scope step because `--scope` is provided.

When /presearch completes, the full pipeline is done. Do NOT print an additional report -- /presearch already reported the briefing path and ship prompt.

---

## Edge cases

- **No topic and no --scope**: AskUser prompt fires in Step 0.
- **Scope artifact does not exist**: error with "File not found: <path>. Run /scope first or provide a topic directly."
- **Gemini unavailable**: proceed with Claude-only research. Log to gaps. Degraded mode, not failure (decision-65).
- **All subagents fail but Gemini succeeds**: write artifact with Gemini-only findings. Set `partial_research: true`.
- **All Gemini calls fail but subagents succeed**: write artifact with Claude-only findings. Set `partial_research: true`.
- **Fewer than 4 angles after dedup**: use what is available. Do not pad.
- **Subagent returns malformed output**: treat as failed for that angle. Add to gaps.
- **Rate limiting on WebSearch**: subagents handle their own retries.
