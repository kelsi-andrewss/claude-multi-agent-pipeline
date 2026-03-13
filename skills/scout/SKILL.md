---
name: scout
description: >
  Project introspection for implementation planning. Reads the codebase, queries
  recorded decisions and OpenMemory, identifies existing patterns, constraints,
  and testable assertions. NO web research — that's /research's job. Scout answers
  "what does THIS project require?" not "what exists in the world?"
  Reads .clarify-<slug>.json and/or .research-<slug>.json if provided.
  Writes presearch/.scout-<slug>.json with findings, constraints, patterns, and
  testable assertions.
  Use when the user says "/scout <topic>", "/scout --clarify presearch/.clarify-foo.json",
  "/scout --research presearch/.research-foo.json", or "/scout --deep <topic>".
args:
  - name: args
    type: string
    description: >
      Topic (quoted string or free text), optional flags: --clarify <path> (path to
      .clarify-<slug>.json), --research <path> (path to .research-<slug>.json
      knowledge synthesis artifact from upstream deep research), --deep (increases
      exploration depth).
---

# Scout Skill Invoked

User has requested: `/scout {{args}}`

---

## Step 0: Parse args

Parse `{{args}}` to extract:

- `--clarify <path>` -> path to a `.clarify-<slug>.json` artifact. Optional.
- `--research <path>` -> path to a `presearch/.research-<slug>.json` knowledge synthesis artifact. Optional.
- `--deep` -> increases exploration depth. Boolean.
- Everything remaining after flag stripping -> `topic`. Required. If empty after stripping flags, ask:
  ```
  AskUserQuestion: "What topic should I scout?"
  ```

**Slug derivation:**
- If `--clarify` was provided and the artifact contains a `slug` field: use that slug.
- If `--research` was provided and the artifact contains a `slug` field (and no slug from clarify): use that slug.
- Otherwise: topic text lowercased, spaces to hyphens, non-alphanumeric stripped, truncated to 40 chars.

---

## Step 1: Load upstream context

### 1a: Clarify context (if --clarify)

Read the file. Validate it has `slug`, `skill: "clarify"`, and `data` with `decisions` and `constraints`.

Extract:
- `data.decisions` -> hard constraints for scouting (these are resolved, not suggestions)
- `data.constraints` -> project constraints
- `scope` -> scope metadata
- `slug` -> slug override

If validation fails, stop and report the error.

### 1b: Research context (if --research)

Read the file. Validate it has `slug`, `skill: "research"`, and `data` with `synthesized_findings`.

Extract:
- `data.synthesized_findings` -> domain knowledge (informs what patterns to look for)
- `data.gaps` -> knowledge gaps scout should try to fill from the codebase
- `slug` -> slug if not already set

If validation fails, stop and report the error.

### 1c: No upstream

If neither flag provided: standalone mode. Scout based on topic only.

---

## Step 2: Project introspection

Launch a single foreground `Explore` agent to introspect the project. This agent has access to Glob, Grep, Read, and all search tools — but NOT WebSearch, WebFetch, or Edit/Write.

```
Agent(subagent_type="Explore", prompt=<prompt below>)
```

**Explore agent prompt:**

```
You are a codebase analyst. Your job is to understand the project's existing patterns,
constraints, and architecture relevant to a specific topic. You do NOT search the web.
You ONLY look at the local project.

TOPIC: <topic text>

<if --clarify>
DECISIONS (hard constraints — do not contradict):
<list each decision: area, choice, reasoning>

CONSTRAINTS:
<list each constraint: type, value>
</if>

<if --research>
DOMAIN CONTEXT (from web research — use to guide what patterns to look for):
<list key findings summaries, max 10>

KNOWLEDGE GAPS (try to answer these from the codebase):
<list gaps>
</if>

INVESTIGATE ALL OF THE FOLLOWING:

1. **Relevant files**: Use Glob to find files related to the topic. Map the directory
   structure. Identify which files would be read vs written for this work.

2. **Existing patterns**: Use Grep to find how similar features are implemented.
   Look for naming conventions, error handling patterns, test patterns, import
   structures. Read 2-3 exemplar files to understand the established approach.

3. **Dependencies and constraints**: Check package.json / pubspec.yaml / requirements.txt /
   Cargo.toml for relevant dependencies. Note version constraints. Look for existing
   abstractions or utilities that must be reused.

4. **Protected files**: Read .claude/protected-files.md if it exists. Note any protected
   files relevant to the topic.

5. **Test patterns**: Find existing tests related to the topic area. Note the test
   framework, assertion style, and what's tested vs what isn't.

DEPTH: <"thorough" if --deep, "medium" otherwise>

OUTPUT: Return a structured summary with these sections:

RELEVANT FILES:
- List files that exist and are relevant, with one-line descriptions
- Separate into "read targets" (context) and "likely write targets" (would change)

EXISTING PATTERNS:
- How does the codebase handle similar concerns today?
- What abstractions/utilities exist that this work should use?
- What naming conventions apply?

CONSTRAINTS:
- Hard requirements from the codebase (must use X, cannot import Y, etc.)
- Version constraints from package manifests
- Protected files that cannot be modified

TEST LANDSCAPE:
- What test framework and patterns are used?
- What's the test coverage situation for this area?
- What assertion patterns are established?

GAPS:
- Areas where the codebase has no established pattern (greenfield)
- Missing tests or documentation
- Anything from the research gaps list that the codebase doesn't answer
```

---

## Step 3: Query decisions and memory

While the Explore agent runs (or after, if foreground), query for recorded decisions and semantic memory relevant to the topic.

### 3a: Decisions

Load tool: `ToolSearch: select:mcp__gemini__pm_list_decisions`

Call `pm_list_decisions` (no filter -- scan all). From the results, extract decisions relevant to the topic. Look for:
- Technology choices that constrain implementation
- Architectural decisions about patterns or approaches
- Rejected alternatives (things NOT to do)

### 3b: OpenMemory

Load tool: `ToolSearch: select:mcp__openmemory__openmemory_query`

Call `openmemory_query` with the topic text. Extract relevant memories:
- Prior implementation attempts
- Tool/model learnings relevant to the work
- Behavioral preferences that affect the approach

---

## Step 4: Synthesize findings

Combine the Explore agent's results with decisions and memory into the canonical scout artifact.

### 4a: Build findings

Transform the Explore agent's output into structured findings:

```json
{
  "category": "pattern | constraint | dependency | test | architecture",
  "summary": "string -- one-line finding",
  "details": "string -- full context",
  "files": ["string -- relevant file paths"],
  "source": "codebase | decision | memory"
}
```

Categories:
- `pattern` — existing implementation patterns the work must follow
- `constraint` — hard requirements (protected files, version locks, must-use abstractions)
- `dependency` — relevant packages, their versions, and what they provide
- `test` — test framework, patterns, coverage gaps
- `architecture` — structural decisions about how the codebase is organized

### 4b: Build testable assertions

From the findings, extract assertions specific enough to verify:

```json
{
  "assertion": "string -- the testable claim",
  "category": "pattern_conformance | dependency_constraint | test_coverage | architecture_boundary",
  "verification": "string -- how to verify this assertion",
  "source": "codebase | decision-<id> | memory"
}
```

### 4c: Identify conflicts with research

If `--research` was provided, check whether any codebase findings contradict the web research:
- Research says "use library X" but codebase already uses library Y for the same purpose
- Research suggests a pattern that conflicts with an established codebase convention
- Research recommends a version that conflicts with what's in the package manifest

Record these in `conflicts`.

---

## Step 5: Write canonical artifact

Write to `presearch/.scout-<slug>.json`.

**Schema:**

```json
{
  "slug": "<slug>",
  "scope": {
    "files": "<number of likely write-target files, or null>",
    "stories": null,
    "complexity": "<small | medium | large | null>"
  },
  "route_hint": "<from clarify if available, else null>",
  "prev": ["<clarify artifact path if used>", "<research artifact path if used>"],
  "skill": "scout",
  "data": {
    "topic": "<original topic text>",
    "findings": [
      {
        "category": "pattern | constraint | dependency | test | architecture",
        "summary": "string",
        "details": "string",
        "files": ["string"],
        "source": "codebase | decision | memory"
      }
    ],
    "decisions_relevant": [
      {
        "id": "string -- decision ID",
        "summary": "string -- what was decided",
        "impact": "string -- how it affects this work"
      }
    ],
    "testable_assertions": [
      {
        "assertion": "string",
        "category": "pattern_conformance | dependency_constraint | test_coverage | architecture_boundary",
        "verification": "string",
        "source": "string"
      }
    ],
    "write_targets": ["string -- files that would likely be modified"],
    "read_targets": ["string -- files needed for context"],
    "conflicts": [
      {
        "subject": "string -- what the conflict is about",
        "codebase_says": "string -- what the project does/requires",
        "research_says": "string -- what web research suggested",
        "resolution": "string -- which should win and why"
      }
    ],
    "gaps": [
      "string -- topics where codebase has no established pattern"
    ]
  }
}
```

**Field rules:**
- `scope`: estimated from write_targets count. null if standalone with no clear file targets.
- `prev`: array of upstream artifact paths used. Empty array if standalone.
- `conflicts`: empty array if no research was provided or no contradictions found.
- `decisions_relevant`: empty array if no relevant decisions found.
- `gaps`: empty array if all areas had established patterns.

---

## Step 6: Report

```
Scout complete.

Topic: <topic>
Findings: <count> across <category count> categories
Decisions: <count> relevant recorded decisions
Write targets: <count> files (<list>)
Testable assertions: <count>
Conflicts: <count> (codebase vs research disagreements)
Gaps: <list or "none">

Output: presearch/.scout-<slug>.json
```

If `--research` was used: `Upstream: <research artifact path>`
If `--clarify` was used: `Upstream: <clarify artifact path>`

Do NOT prompt to run /briefing or any downstream skill. Routing is the orchestrator's job.
