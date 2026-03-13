---
name: research
description: >
  Deep web research via fan-out/fan-in parallelism. Claude and Gemini independently
  suggest research angles, deduped into 4-6, parallel web-researcher subagents
  investigate each angle, findings merged with conflict detection and citation tracking.
  Writes presearch/.research-<slug>.json knowledge synthesis artifact. Use when the
  user says "/research <topic>", "/research --scope .scope-foo.json <topic>",
  or "/research --deep <topic>".
args:
  - name: args
    type: string
    description: >
      Topic (quoted string or free text), optional flags: --scope <path> (path to
      .scope-<slug>.json), --deep (increases subagent maxTurns budget).
---

# Research Skill Invoked

User has requested: `/research {{args}}`

---

## Step 0: Parse args

Parse `{{args}}` to extract:

**Flags** (strip from args after detection):
- `--scope <path>` -- path to a `.scope-<slug>.json` artifact. Optional.
- `--deep` -- increases subagent turn budget. Boolean.

Everything remaining after flag stripping is the `topic`.

**If no topic and no --scope**: prompt the user with `AskUser`: "What topic should I research?" and stop until answered.

**Slug derivation**: from scope artifact's `slug` field if `--scope` provided, otherwise from topic text (lowercase, hyphenated, max 40 chars, strip articles and filler words).

---

## Step 1: Load scope context (if --scope)

If `--scope <path>` provided:
1. Read the file. Validate it has `skill: "scope"` and `data` with `topic`, `needs_research`.
2. Extract: `data.topic` (use as topic if none in args), `data.stack_detected`, `data.in_scope`, `data.out_of_scope`.
3. These become context constraints for angle generation -- angles must respect scope boundaries.

If `--scope` not provided: standalone mode. No upstream constraints.

If the file does not exist: error with "File not found: <path>. Run /scope first or provide a topic directly." and stop.

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

**Gemini angles** (via gemini_chat):

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

## Step 4: Fan-out -- parallel subagent dispatch

Launch one web-researcher subagent per angle. Launch all in a single message (parallel):

```
For each angle in the merged angle list:
  Agent tool call:
    subagent_type: "web-researcher"
    prompt: <angle-specific research brief>
    run_in_background: true
```

**Subagent research brief** (passed as prompt to each Agent call):

```
Research angle: <angle.angle>
Hypothesis: <angle.hypothesis>
Scope boundary (do NOT research): <angle.scope_boundary>

Search queries to start with:
<angle.queries, one per line>

Instructions:
- Start with these queries, then refine based on what you find.
- Follow the search-evaluate-synthesize loop: search, evaluate results for quality
  and relevance, narrow or expand focus, iterate.
- Prefer official documentation, academic papers, and primary sources over SEO content.
- Distill your findings into 500-1000 words maximum.
- Every claim must cite a source URL.
- Structure your output as JSON:
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

**--deep flag behavior:** When `--deep` is set, append to each subagent brief:
```
Deep mode: expand your search budget. Follow more links, check more sources, and
explore secondary references from authoritative sources you find.
```

**Rate limiting awareness:** 4-6 subagents hitting WebSearch simultaneously may trigger rate limits. This is expected -- subagents handle their own retries via the search-evaluate-refine loop. No explicit throttling at the orchestrator level.

Wait for all subagent results to return before proceeding.

---

## Step 5: Handle partial failures

If any subagent fails or returns empty/malformed results:
- Proceed with results from successful subagents.
- Record failed angles in the `gaps` array of the output artifact.
- Set `partial_research: true` in the artifact data.
- Do NOT retry failed subagents -- downstream skills handle partial data gracefully (decision-65).

If ALL subagents fail: write an artifact with empty findings, full gaps list, `partial_research: true`. Report the failure clearly. The pipeline continues -- clarify still works without research context.

---

## Step 6: Fan-in -- synthesis and merge

Run a synthesis pass over all successful subagent returns.

**6a. Deduplicate findings:**
- Compare claims across subagent results by semantic similarity.
- Merge duplicate claims, keeping the higher-confidence version and all source URLs.
- Group findings by theme (not by source angle) for the synthesized output.

**6b. Detect conflicts:**
- When two subagents report contradictory claims about the same topic:
  - Flag both positions with their sources.
  - Assess source credibility (official docs > academic papers > blog posts > forum answers).
  - Do NOT silently resolve -- record both sides in the `conflicts` array.
  - Additive merge with conflict flags, not consensus filtering (decision-64).

**6c. Track citations:**
- Every claim in synthesized_findings must trace to at least one source URL.
- Deduplicate URLs across subagent results.
- Rate each source: `authoritative` (official docs, academic), `informative` (quality blog, conference talk), `low-quality` (SEO content, outdated).

**6d. Identify gaps:**
- Angles that produced thin results (fewer than 2 findings).
- Topics multiple subagents flagged as under-documented.
- Claims with only low-quality sources.

**Source quality bias mitigation:** Explicitly check whether authoritative sources were found for key claims. If a finding is supported only by SEO-style content (listicles, content farms, affiliate sites), downgrade its confidence to `low` and add the topic to gaps.

**Context bloat mitigation:** Each subagent already distills to 500-1000 words. Synthesis further compresses by deduplicating across subagents. The final `synthesized_findings` array should contain 10-20 themed findings, not a dump of all subagent claims.

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
            "confidence": "high|medium|low"
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
        "claim_a": { "claim": "string", "source_urls": ["string"] },
        "claim_b": { "claim": "string", "source_urls": ["string"] },
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
- `scope`: always null fields -- research does not estimate implementation scope. That is briefing's job.
- `route_hint`: always null -- routing is the orchestrator's decision.
- `prev`: array containing scope artifact path if `--scope` was used, otherwise empty array `[]`. Always an array per artifact contract.
- `partial_research`: `true` if any subagent failed, `false` otherwise.
- `conflicts`: empty array if no contradictions found.
- `gaps`: empty array if all angles produced solid results.

---

## Step 8: Report

```
Research complete.

Topic: <topic>
Angles: <count> researched (<count from Claude>, <count from Gemini>, <count overlap>)
Findings: <count> across <theme count> themes
Citations: <count> sources (<authoritative count> authoritative)
Conflicts: <count>
Gaps: <list or "none">

Output: presearch/.research-<slug>.json
```

If `--scope` was used: `Upstream: <scope artifact path>`
If `partial_research` is true: `Warning: <N> angles failed -- results are partial. Gaps noted in artifact.`

Do NOT prompt to run downstream skills. Routing is the orchestrator's job.

---

## Edge cases

- **No topic and no --scope**: AskUser prompt fires in Step 0 before any generation.
- **Scope artifact does not exist**: error with actionable message -- "File not found: <path>. Run /scope first or provide a topic directly."
- **Gemini unavailable during angle generation**: proceed with Claude-only angles. Log to gaps: "Gemini unavailable -- angles from Claude only, may lack breadth." This is a degraded mode, not a failure (decision-65 spirit).
- **All subagents fail**: write artifact with empty findings, full gaps, `partial_research: true`. Report clearly. Pipeline continues.
- **Fewer than 4 angles after dedup**: use what is available. Do not pad -- researching 2-3 genuine angles beats researching 6 padded ones.
- **Topic produces 0 angles**: report "Could not decompose topic into research angles. Try a more specific topic or provide a scope artifact."
- **Subagent returns malformed JSON**: treat as failed subagent -- add angle to gaps, set `partial_research`. Do not crash parsing.
- **Rate limiting on WebSearch**: subagents handle their own retries. The orchestrator does not throttle dispatch -- simultaneous launch is the documented Agent tool behavior.
- **Context bloat from subagent returns**: each subagent is constrained to 500-1000 words. Synthesis further deduplicates. If total context still exceeds budget, prioritize high-confidence findings and drop low-quality-sourced claims.
