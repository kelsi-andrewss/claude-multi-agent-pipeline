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
  Bootstrap mode (--bootstrap <path>) scans an unfamiliar repo and generates
  CLAUDE.md, decisions.sql, and .claude/refs/ convention artifacts.
  Use when the user says "/scout <topic>", "/scout --clarify presearch/.clarify-foo.json",
  "/scout --research presearch/.research-foo.json", "/scout --deep <topic>",
  or "/scout --bootstrap /path/to/repo".
args:
  - name: args
    type: string
    description: >
      Topic (quoted string or free text), optional flags: --clarify <path> (path to
      .clarify-<slug>.json), --research <path> (path to .research-<slug>.json
      knowledge synthesis artifact from upstream deep research), --deep (increases
      exploration depth), --bootstrap <path> (scan unfamiliar repo and generate
      convention artifacts — incompatible with other flags).
---

# Scout Skill Invoked

User has requested: `/scout {{args}}`

---

## Step 0: Parse args

Parse `{{args}}` to extract:

- `--bootstrap <path>` -> path to a target repository for convention extraction. Optional.
- `--clarify <path>` -> path to a `.clarify-<slug>.json` artifact. Optional.
- `--research <path>` -> path to a `presearch/.research-<slug>.json` knowledge synthesis artifact. Optional.
- `--deep` -> increases exploration depth. Boolean.
- Everything remaining after flag stripping -> `topic`. Required unless `--bootstrap` is set.

**Bootstrap guard:** If `--bootstrap` is present alongside `--clarify`, `--research`, or `--deep`, stop with:
```
Error: --bootstrap is incompatible with --clarify, --research, and --deep.
Bootstrap mode performs its own full-repo scan. Run it standalone:
  /scout --bootstrap /path/to/repo
```

**Bootstrap validation:** If `--bootstrap` is present:
- If `<path>` does not exist, create it: `mkdir -p <path>`.
- Verify `<path>` is a directory. If not, stop with an error.
- If `<path>` is not a git repo (`git -C <path> rev-parse --git-dir` fails):
  - Initialize: `git -C <path> init`
  - If the directory has files, stage and commit them: `git -C <path> add -A && git -C <path> commit -m "initial commit"`
  - If empty, create a minimal commit so branches work: `git -C <path> commit --allow-empty -m "initial commit"`
  - Create dev branch: `git -C <path> branch dev`
  - Log: `"Initialized git repo at <path> with dev branch."`
- Set `bootstrap_mode = true`, `target_path = <path>`.
- `topic` is not required in bootstrap mode.
- Skip to Step 2b.

**Non-bootstrap topic:** If `--bootstrap` is not present and topic is empty after stripping flags, ask:
  ```
  AskUserQuestion: "What topic should I scout?"
  ```

**Slug derivation (non-bootstrap only):**
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

6. **Completeness check**: Find ALL occurrences of the pattern, function, component,
   or code path being changed. Don't stop at the first match — exhaust the search.
   Use multiple Grep queries with variations (aliases, re-exports, dynamic references).
   For each write target, answer: "Are there other places that do the same thing,
   call the same thing, or depend on the same thing?" List every occurrence found
   and flag any that might be missed.

7. **Blast radius**: For each write target, trace what depends on it — imports,
   callers, consumers, downstream data flows. Identify what could break if this
   file changes. Include: direct importers, test files that exercise this code,
   config files that reference it, and any runtime dependencies (e.g., API contracts,
   event listeners, database queries that assume a specific shape).

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

COMPLETENESS:
- For each write target: list ALL occurrences of the pattern/function/component found
- Flag any search strategies that might miss occurrences (dynamic imports, string references, etc.)
- Confidence level: "exhaustive" (all variants searched) or "best-effort" (some vectors couldn't be searched)

BLAST RADIUS:
- For each write target: what files import/call/depend on it?
- What tests exercise this code?
- What runtime contracts (APIs, events, DB schemas) could break?
- Downstream effects: if this change is wrong, what symptoms would appear and where?

GAPS:
- Areas where the codebase has no established pattern (greenfield)
- Missing tests or documentation
- Anything from the research gaps list that the codebase doesn't answer
```

---

## Step 2b: Bootstrap introspection (bootstrap_mode only)

Skip Steps 1, 2, 3, 4, 5, 6. Follow Steps 2b, 4b, 5b, 6b instead.

Read `skills/scout/bootstrap-prompt.md`. Replace `{{target_path}}` with the actual target path.

Launch a single foreground `Explore` agent targeting the external repository:

```
Agent(subagent_type="Explore", prompt=<contents of bootstrap-prompt.md with target_path interpolated>)
```

The explore agent returns structured JSON describing the target repo's conventions, architectural decisions, pitfalls, and patterns. Parse this JSON output for use in Step 4b.

If the agent's output is not valid JSON, attempt to extract the JSON block from its response. If still unparseable, stop with an error.

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
- `completeness` — all occurrences of the target pattern/code, with confidence level
- `blast_radius` — downstream dependencies, callers, and what could break

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

## Step 4b: Bootstrap synthesis (bootstrap_mode only)

Skip decision and memory queries -- the target repo is unfamiliar and has no recorded decisions in the current project's store.

Parse the explore agent's JSON output from Step 2b.

**Existing AI config check:** If `existing_ai_config.files_found` is non-empty, read each file from the target repo. Their contents are constraints -- the generated artifacts must not contradict existing AI instructions. Note them for the generators.

The parsed JSON is passed directly to the generator scripts in Step 5b.

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
    "completeness": {
      "confidence": "exhaustive | best-effort",
      "occurrences": [
        {
          "target": "string -- what was searched for",
          "locations": ["string -- file:line or file paths"],
          "search_strategies": ["string -- grep patterns, glob patterns used"],
          "blind_spots": ["string -- search vectors that couldn't be covered"]
        }
      ]
    },
    "blast_radius": [
      {
        "write_target": "string -- file being modified",
        "dependents": ["string -- files that import/call/depend on this"],
        "test_coverage": ["string -- test files that exercise this code"],
        "runtime_contracts": ["string -- APIs, events, DB schemas that could break"],
        "failure_symptoms": "string -- if this change is wrong, what breaks and where"
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

## Step 5b: Generate bootstrap artifacts (bootstrap_mode only)

Run the generator scripts with the explore agent's JSON output. Each generator reads JSON from stdin and writes its output.

### 5b-1: Generate CLAUDE.md

```bash
echo '<explore_json>' | python3 skills/scout/generators/claude_md.py
```

Capture the stdout output as the CLAUDE.md content.

### 5b-2: Generate decisions.sql

```bash
echo '<explore_json>' | python3 skills/scout/generators/decisions_sql.py <target_path>
```

Capture the stdout output as the decisions.sql content.

### 5b-3: Generate ref files

```bash
echo '<explore_json>' | python3 skills/scout/generators/refs.py <target_path>/.claude/refs
```

This writes files directly to the target's `.claude/refs/` directory. Stdout lists the generated filenames.

### 5b-3.5: Generate .gitignore

Generate a `.gitignore` for the target project with standard orchestration pipeline ignores. These files are written by hooks at runtime and cause merge conflicts if tracked.

If `<target_path>/.gitignore` already exists, append the pipeline section (fenced with comments). If it doesn't exist, create it.

**Pipeline ignores to include:**

```
# === Claude orchestration pipeline (auto-generated by scout --bootstrap) ===

# Tracking (written by hooks between every tool call)
tracking/events/
.claude/tracking/friction.json
.claude/tracking/charts.html
.claude/tracking/skill-telemetry.jsonl

# Plugin state (updated by hooks)
plugins/blocklist.json
plugins/known_marketplaces.json

# Pipeline artifacts (regenerated per session)
plans/
.ship-manifest.json
.scope-*.json
.clarify-*.json

# Database files (local state)
.claude/epics.db
.claude/epics.db-shm
.claude/epics.db-wal
.claude/run-state.db
.claude/run-state.db-shm
.claude/run-state.db-wal
.claude/decisions.db
.claude/decisions.db-shm
.claude/decisions.db-wal
.claude/openmemory.sqlite
.claude/openmemory.sqlite-wal
.claude/openmemory.sqlite-shm

# Generated sidecars
.claude/rendered-prefs.md

# Worktrees (coder agent isolation)
.claude/worktrees/

# Python
__pycache__/
*.pyc
.venv/

# OS
.DS_Store

# === End Claude orchestration pipeline ===
```

### 5b-4: Write artifacts to target repo

For each artifact, check whether the target path already exists:

- **CLAUDE.md**: Write to `<target_path>/.claude/CLAUDE.md`. If it already exists, write to `<target_path>/.claude/CLAUDE.generated.md` and warn.
- **decisions.sql**: Write to `<target_path>/.claude/decisions.sql`. If it already exists, write to `<target_path>/.claude/decisions.generated.sql` and warn.
- **refs/**: Already written by the refs generator. It skips existing files.
- **.gitignore**: Append to `<target_path>/.gitignore` if it exists, or create new. When appending, check if the `# === Claude orchestration pipeline` marker already exists — if so, skip (idempotent).

Create `<target_path>/.claude/` and `<target_path>/.claude/refs/` directories as needed before writing.

---

## Step 6: Report

```
Scout complete.

Topic: <topic>
Findings: <count> across <category count> categories
Decisions: <count> relevant recorded decisions
Write targets: <count> files (<list>)
Testable assertions: <count>
Completeness: <exhaustive | best-effort> (<N> occurrences mapped, <M> blind spots)
Blast radius: <count> write targets with <total dependents> downstream files
Conflicts: <count> (codebase vs research disagreements)
Gaps: <list or "none">

Output: presearch/.scout-<slug>.json
```

If `--research` was used: `Upstream: <research artifact path>`
If `--clarify` was used: `Upstream: <clarify artifact path>`

Do NOT prompt to run /briefing or any downstream skill. Routing is the orchestrator's job.

---

## Step 6b: Bootstrap report (bootstrap_mode only)

```
Bootstrap complete for: <project_name>
Target: <target_path>

Generated:
  CLAUDE.md — <line count> lines, <section count> sections
  decisions.sql — <decision count> decisions
  refs/ — <ref count> files (<list filenames>)
  .gitignore — pipeline ignores (<new|appended>)

<if existing files were detected:>
  WARNING: Existing files detected. Generated variants written:
    .claude/CLAUDE.generated.md (review and merge with existing CLAUDE.md)
    .claude/decisions.generated.sql (review and merge with existing decisions.sql)
</if>

Next steps:
  1. Review generated artifacts
  2. Edit CLAUDE.md — remove incorrect inferences, add project-specific knowledge
  3. Edit decisions.sql — promote confident decisions, remove speculative ones
  4. Commit .claude/ to the target repo
```

Do NOT prompt to run /briefing or any downstream skill. Routing is the orchestrator's job.
