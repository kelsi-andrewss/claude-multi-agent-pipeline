---
name: clarify
description: "Detect project constraints, analyze ambiguities via Gemini, batch Q&A to the user, and write a typed JSON artifact (.clarify-<slug>.json) for downstream consumption. Use when the user says \"/clarify <topic>\", \"/clarify path/to/requirements.md\", \"/clarify --quick <topic>\", or \"/clarify --research <path> <topic>\"."
args:
  - name: args
    type: string
    description: "Topic (quoted string or free text), requirements file path, or flags (--quick, --research <path>)."
---

# Clarify Skill Invoked

User has requested: `/clarify {{args}}`

---

## Step 1: Parse args and detect mode

Parse `{{args}}` to determine mode and flags:

**Flags** (strip from args after detection):
- `--quick` → skip Q&A phase entirely, write artifact with empty decisions
- `--research <path>` → load upstream knowledge synthesis artifact from `<path>`. Expects a `.research-<slug>.json` file conforming to the knowledge synthesis schema.

**Research validation** (after flag stripping, if `--research` was provided):
1. Verify file exists at `<path>`.
2. Verify file is valid JSON with `skill: "research"` and `data.synthesized_findings`.
3. If validation fails: warn the user ("Research artifact at `<path>` is missing or malformed — proceeding without research context") and continue in standalone mode (no research data loaded).
4. If validation passes and `data.synthesized_findings` is empty: treat as standalone mode — no validation opening, no research context in Gemini prompt. Still set `prev` pointer.
5. Store the parsed research data for use in Steps 2.5 and 3.

**Mode detection** (after stripping flags):
1. **Requirements mode**: remaining arg is a file path ending `.md`, `.txt`, or similar, and the file exists → read it as seed requirements doc. The file contents become the topic.
2. **Idea mode**: everything else → treat as the topic/idea text.

**If no args and no topic**: prompt the user with `AskUser`: "What topic or feature should I clarify?" and stop until answered.

**Slug derivation**: from the topic text, generate a slug — lowercase, hyphenated, max 40 chars. Strip articles and filler words. Examples:
- "Add presence cursors to the canvas" → `add-presence-cursors`
- "path/to/auth-requirements.md" → slug from the first heading or filename stem

---

## Step 2: Existing project detection

Scan the current working directory for project markers:
- `package.json`, `pubspec.yaml`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `CLAUDE.md`

If found: read the relevant files to extract stack info (framework, language, existing dependencies, patterns). These become hard constraints — all downstream recommendations must fit the existing stack. Store as constraint entries with `type: "stack"`.

If nothing found: greenfield mode. The constraints array will contain no stack entries.

---

## Step 2.5: Research validation opening

**Skip if `--research` was not provided, research data failed validation, synthesized_findings is empty, or `--quick` flag is set.**

Present the research findings to the user in a single `AskUser` call:

```
Research on this topic found:

<For each key finding in data.synthesized_findings, one bullet>
- [finding summary] (source: [citation from data.citations])

<If data.conflicts is non-empty>
**Open questions from research:**
- [conflict: claim A vs claim B]

<If data.gaps is non-empty>
**Gaps — research couldn't determine:**
- [gap description]

Does this match your understanding? Anything to correct or add before we dig into design decisions?
```

Record the user's response:
- Corrections → store as constraints with `type: "user-override"`, `source: "user"`
- Confirmations → no action needed, findings are validated
- Additions → append to research context for the Gemini prompt in Step 3

---

## Step 3: Q&A

**Skip if `--quick` flag is set.** Proceed directly to Step 4 with empty decisions.

1. Load Gemini: `ToolSearch: select:mcp__gemini__analyze`
2. Call `analyze` with prompt — **use the research-aware variant when research data is loaded with non-empty synthesized_findings, otherwise use the standalone variant**:

   **Standalone variant** (no research, or empty findings):
   ```
   Analyze this project description. Identify:
   (a) ambiguities that need clarification
   (b) missing requirements implied but not stated
   (c) technical decision points where multiple valid approaches exist
   (d) why this work is integral to the project — what breaks, stalls, or degrades if it doesn't happen? If the upstream scope artifact includes a "problem" and "why" field, probe deeper on those. If they're missing or vague, this becomes a required clarification.

   For each decision point, present 2-3 options with tradeoffs.
   Scale your analysis to the input — a clear, specific request needs fewer questions than a vague idea.

   Existing stack constraints (hard requirements — do not contradict these):
   <constraints from Step 2, or "None — greenfield project">

   Input:
   <topic text or file contents>
   ```

   **Research-aware variant** (research data loaded with findings):
   ```
   Analyze this project description. You have access to prior research on this domain.

   Prior research findings (validated by user):
   <data.synthesized_findings, formatted as bullet list>
   <any user corrections from Step 2.5>

   Given this research context, identify:
   (a) ambiguities that need clarification — focus on DESIGN decisions, not domain understanding (research already covers that)
   (b) missing requirements implied but not stated
   (c) technical decision points where multiple valid approaches exist — use research findings to inform the tradeoffs
   (d) why this work is integral to the project — what breaks, stalls, or degrades if it doesn't happen? If the upstream scope artifact includes a "problem" and "why" field, probe deeper on those. If they're missing or vague, this becomes a required clarification.

   For each decision point, present 2-3 options with tradeoffs. Reference research findings where relevant.
   Scale your analysis to the input — a clear, specific request needs fewer questions than a vague idea.

   Existing stack constraints (hard requirements — do not contradict these):
   <constraints from Step 2, or "None — greenfield project">

   Input:
   <topic text or file contents>
   ```

3. Evaluate Gemini's output:
   - **If no ambiguities and <=1 decision point**: input was clear enough. Record any single decision Gemini surfaced (with its recommendation) and skip to Step 4. Do not ask the user anything.
   - **Otherwise**: batch all questions into a single `AskUser` call:

   ```
   I read through the requirements. A few things to resolve before moving forward:

   **Clarifications:**
   1. <ambiguity> — do you mean X or Y?
   2. <gap> — the doc doesn't mention Z. Should we include it?

   **Tech decisions:**
   3. <Decision area>: <Option A> (pro, con) vs <Option B> (pro, con). I'd pick <recommendation> — <reasoning>.
   ```

4. Wait for user response. Record each decision with area, choice, reasoning, and `source: "user"`.

5. If answers surface new ambiguities, ask ONE more round (max 2 rounds total). Format the follow-up the same way.

6. Proceed to Step 4 with all resolved decisions.

---

## Step 4: Write artifact

Write `.clarify-<slug>.json` in the current working directory.

**Schema** (conforms to `refs/artifact-contract.md`):

```json
{
  "slug": "<slug>",
  "skill": "clarify",
  "scope": {
    "files": <estimated number of write-target files>,
    "stories": <estimated number of stories>,
    "complexity": "<small|medium|large>"
  },
  "route_hint": "<quickfix|standard>",
  "prev": ["<research artifact path, if --research was provided and loaded successfully>"],
  "data": {
    "topic": "<original topic text or file path>",
    "input_summary": "<1-2 sentence summary of what the user wants>",
    "decisions": [
      {
        "area": "<decision area>",
        "choice": "<what was decided>",
        "reasoning": "<why>",
        "source": "<user|gemini|default>"
      }
    ],
    "constraints": [
      {
        "type": "<stack|requirement|scope>",
        "value": "<constraint description>",
        "source": "<detected|user|requirements-file>"
      }
    ]
  }
}
```

**Scope estimation**:
- Estimate `files` and `stories` from the topic complexity and number of decisions.
- Derive `complexity` per the artifact contract thresholds: small (<=3 files, 1 story), medium (4-10 files, 2-5 stories), large (>10 files or >5 stories). Complexity is the max of the two dimensions.

**Route hint logic**:
- `quickfix` when: `scope.files <= 3` AND `complexity == "small"` AND no unresolved ambiguities
- `standard` otherwise

**`--quick` mode**: decisions array is empty, scope is estimated from topic text alone (best effort), route_hint is computed normally.

**`prev` field**: `[]` when clarify runs standalone (no `--research` flag, or research artifact failed validation). When `--research` was provided and loaded successfully, set to `["<research artifact path>"]` — clarify is the chain root only when research is skipped.

---

## Step 5: Report

Output a summary:

```
Artifact: .clarify-<slug>.json
Decisions: <N> recorded (<M> from user, <K> from Gemini defaults)
Constraints: <N> detected
<If research was loaded> Research: loaded from <path> (<N> findings, <M> conflicts)
Scope: <files> files, <stories> stories, <complexity>
Route: <quickfix|standard>

Next: /scout <slug> (or /quickfix --context .clarify-<slug>.json for small scope)
```

---

## Edge cases

- **Empty topic with no args**: AskUser prompt fires before any Gemini call (Step 1)
- **Requirements file doesn't exist**: treat the path text as the topic in idea mode — it's an idea, not a file reference
- **No project markers found**: greenfield mode, constraints array contains no stack entries
- **Gemini unavailable**: fail with a clear error — Gemini analysis is the core value of this skill. Do not fall back to heuristics.
- **`--quick` on a vague topic**: artifact will have empty decisions and a rough scope estimate. Acceptable — downstream skills handle incomplete input.
- **`--research` with invalid path**: warn and proceed in standalone mode — never block on bad upstream input.
- **`--research` with `--quick`**: research is loaded for `prev` pointer but validation opening and Q&A are both skipped.
- **Research artifact has empty `synthesized_findings`**: treat as standalone mode — no validation opening, no research context in Gemini prompt. `prev` is still populated if the artifact loaded successfully.
