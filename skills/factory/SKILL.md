---
name: factory
description: >
  Spec-driven feature decomposition: accepts a FeatureSpec JSON (product, pattern,
  entity, fields, permissions, integrations, UI) and decomposes it into dependency-ordered
  stages using deterministic pattern DAGs. Creates stories via PM tools and writes
  .ship-manifest.json for downstream /draft-plans and /run-stories consumption.
  Use when the user says "/factory spec.json", "/factory --pattern crud-ui <inline JSON>",
  or "/factory --dry-run spec.json".
args:
  - name: args
    type: string
    description: >
      Path to a FeatureSpec JSON file, or --pattern <pattern> followed by inline JSON.
      Optional flags: --dry-run (print decomposition without creating stories),
      --format <gauntlet|canonical|auto> (spec format, default auto).
---

# Factory Skill Invoked

User has requested: `/factory {{args}}`

---

## Step 0: Parse args and validate spec

Parse `{{args}}` to extract flags and input.

**Flags (strip before processing tokens):**
- `--dry-run` -- set `dry_run = true`. Prints the decomposition DAG without creating stories or writing a manifest.
- `--pattern <pattern>` -- override the `pattern` field in the spec. Next token after `--pattern` is the pattern name.
- `--format <format>` -- specify the input spec format. Accepted values: `gauntlet`, `canonical`, `auto` (default). Next token after `--format` is the format name. When omitted, defaults to `auto`.

**Input modes (remaining tokens after flag stripping):**

1. **File mode**: a token ends with `.json` and the file exists. Read the file and parse as JSON.
2. **Inline mode**: remaining text is treated as inline JSON. Parse it directly.
3. **No args**: error:
   ```
   Usage: /factory <spec.json | inline JSON> [--pattern <pattern>] [--format <format>] [--dry-run]

   Examples:
     /factory specs/payments.json
     /factory --dry-run specs/payments.json
     /factory --pattern crud-ui '{"product":"collabboard","entity":"Template",...}'
     /factory --format gauntlet specs/challenge.json
   ```

After parsing, proceed to Step 0.5 for format detection and normalization before validating the schema.

---

## Step 0.5: Format detection and normalization

This step runs BEFORE schema validation. It transforms the raw parsed JSON into canonical FeatureSpec form so that non-canonical input formats (e.g., Gauntlet challenge specs) pass validation without manual reformatting.

See [adapters.md](adapters.md) for the full adapter contract, built-in adapters, and worked examples.

**Format resolution:**

1. If `--format` was explicitly provided, use that format directly (`explicit` detection).
2. If `--format` is `auto` or was omitted, run the auto-detection heuristic chain.

**Auto-detection heuristics (evaluated in order, first match wins):**

- If any entry in `fields` has a `kind` key instead of `type` → `gauntlet`
- If `permissions` is a string (not an array) → `gauntlet`
- If `integrations` is a flat string array (elements are strings, not objects) → `gauntlet`
- If `pattern` contains an underscore instead of a hyphen → `gauntlet`
- If none of the above match → `canonical` (no transformation needed)
- If multiple signals match, that reinforces the `gauntlet` detection

**Gauntlet adapter normalization:**

- `pattern`: replace underscores with hyphens (`crud_ui` → `crud-ui`)
- `fields[].kind` → `fields[].type` (rename the key; preserve the value)
- `fields[].values` → preserve as-is (enum values are accepted by canonical schema)
- `permissions`: if a string, wrap in a single-element array (`"admin:write"` → `["admin:write"]`)
- `integrations`: if a flat string array, convert each element to an object with sensible defaults: `"vault"` → `{"service": "vault", "direction": "bidirectional", "events": ["sync"]}`
- All other fields pass through unchanged

**Canonical adapter:** Identity pass-through. No transformation.

**Idempotency:** Both adapters are idempotent. Running the gauntlet adapter on already-canonical input produces the same output (e.g., renaming `type` to `type` is a no-op, wrapping an already-array `permissions` is a no-op).

**Logging:** After normalization, log:
```
Format detected: <gauntlet|canonical> (via <auto|explicit>). Normalized <N> fields.
```
Where `<N>` is the count of fields that were actually transformed (0 for canonical pass-through).

---

## Step 0.5b: Schema validation (post-normalization)

Validate the **normalized** spec (output of Step 0.5), not the raw input.

**FeatureSpec schema validation:**

The normalized JSON must conform to the FeatureSpec shape:

```
{
  "product": string,            // required — target product identifier
  "pattern": string,            // required — one of: "crud-ui", "integration", "workflow", "analytics"
  "entity": string,             // required — primary entity name (e.g., "Template", "Payment")
  "fields": [                   // required — at least one field
    {
      "name": string,           // required
      "type": string,           // required — e.g., "string", "number", "boolean", "date", "reference"
      "required": boolean,      // optional, default true
      "sensitive": boolean,     // optional, default false
      "ui_type": string         // optional — e.g., "text", "select", "date-picker", "toggle"
    }
  ],
  "permissions": [string],      // optional — e.g., ["admin:write", "user:read"]
  "audit": boolean,             // optional, default false
  "integrations": [             // optional
    {
      "service": string,        // required if integrations present
      "direction": string,      // required — "inbound", "outbound", "bidirectional"
      "events": [string]        // required — at least one event name
    }
  ],
  "ui": {                       // optional — which UI views to generate
    "list": boolean,
    "detail": boolean,
    "form": boolean,
    "dashboard": boolean
  }
}
```

**Validation rules:**

1. `product`, `entity`, and `pattern` are required strings. Reject with: `"Missing required field: <field>"`
2. `pattern` must be one of: `crud-ui`, `integration`, `workflow`, `analytics`, `library-extension`. Reject with: `"Invalid pattern: '<value>'. Must be one of: crud-ui, integration, workflow, analytics, library-extension"`
3. `fields` must be a non-empty array. Each field must have `name` (string) and `type` (string). Reject with: `"fields[N]: missing required property '<prop>'"`
4. If `integrations` is present and non-empty, each entry must have `service`, `direction`, and `events` (non-empty array). Reject with: `"integrations[N]: missing required property '<prop>'"`
5. If `--pattern` flag was provided, it overrides `spec.pattern` (log: `"Pattern override: <flag value>"`).

If validation fails, print all errors (not just the first) and stop.

---

## Step 0.75: Decision conflict check

**Purpose:** Catch spec choices that conflict with the target project's recorded decisions before wasting tokens on planning and story creation. Fail fast.

**When to run:** After schema validation passes. Skip if `--dry-run` is set (dry-run doesn't create stories, so conflicts are informational only — log them but don't block).

**How:**

1. Locate the target project's decisions file. Check (in order):
   - `--project-root` flag value (if set) + `/.claude/decisions.sql`
   - Current working directory + `/.claude/decisions.sql`
   - If neither exists, skip this step (no decisions to check against). Log: `"No decisions.sql found — skipping conflict check."`

2. Parse the SQL file. Extract decision content and scope from INSERT statements:
   - Regex: `VALUES \(\d+, '([^']+)', '([^']+)'` captures (content, reasoning)
   - Build a list of `{id, content, reasoning, scope_type, scope_value}` objects

3. Check the normalized spec against each decision. Conflict detection rules:

   | Spec implies | Decision says | Conflict? |
   |---|---|---|
   | REST endpoints (generic CRUD pattern) | "tRPC for internal" (scope: api-design) | YES — spec's `rest_endpoints` stage must be renamed/adapted to tRPC |
   | Generic Error throwing | "AppError with codes" (scope: error-handling) | YES — generated code must use AppError, not throw Error |
   | `sensitive: true` with vault encryption | No vault decision exists | WARNING — project may not have vault; check for encryption patterns |
   | `ui` components with 'use client' | "No 'use client' directive" (scope: apps/remix/*) | YES — components must not use 'use client' |
   | Standard REST API routes | "Dual API: REST (public) + tRPC (internal)" (scope: api-design) | ADAPT — internal features use tRPC, not REST |

   The check is heuristic, not exhaustive. Match decision scope_type against spec implications:
   - `tech` scope with `api-design` value → check if spec implies REST vs tRPC
   - `tech` scope with `error-handling` value → note error pattern for stage generation
   - `pattern` scope → check if spec's implied file paths fall within the scope glob
   - `tech` scope with `translations` value → note i18n requirement for UI stages

4. For each conflict found, classify as:
   - **CONFLICT** — spec's default pattern differs from a recorded decision. Requires human choice.
   - **WARNING** — spec implies something the project may not support, but it's not a direct conflict. Example: `sensitive: true` but no vault infrastructure.

5. **Human-in-the-loop decision point.** If any CONFLICTs exist, present them ALL to the user in a single prompt. Do NOT silently adapt. The user needs to see what the spec implies vs what the project requires.

   Format:
   ```
   Decision conflicts found (N):

     [decision-1] error-handling: "AppError with string codes"
       Spec implies: generic Error throwing (CRUD+UI default)
       Options:
         (a) ADAPT — use AppError pattern, spec intent preserved
         (b) CHANGE DECISION — supersede decision-1 (requires rationale)

     [decision-6] api-design: "tRPC for internal features"
       Spec implies: REST API endpoints (CRUD+UI default)
       Options:
         (a) ADAPT — use tRPC routes instead of REST, spec intent preserved
         (b) CHANGE DECISION — supersede decision-6 (requires rationale)

     ...

   Enter choices (e.g., "all adapt", "1a 2a 3b", or review each):
   ```

   **Response handling:**
   - `"all adapt"` or `"adapt all"` — apply all adaptations, continue.
   - Per-conflict choices like `"1a 2b"` — apply adapts, prompt for rationale on changes.
   - `"b"` on any conflict — call `pm_supersede_decision(decision_id, rationale)` before continuing. The decision is permanently changed, not overridden per-spec.
   - If user picks (b), the old decision is superseded in the DB with the user's rationale. Future factory runs against this project won't hit the same conflict.

   **Why this matters:** The spec is the input contract. If the factory silently transforms it, the spec becomes misleading — it says "CRUD+UI" but the output is tRPC-shaped. The user should know exactly where the spec's defaults diverge from the project's conventions and consciously approve each adaptation.

   **Prompt quality rule:** Every option must have equal detail. Show concrete consequences (what happens, what files change, what gets skipped) for ALL options — not just the one you'd recommend. Biasing detail toward one option is steering, not informing. If using AskUserQuestion with previews, every option gets a preview of equal depth.

   **WARNINGs** do not require a choice — they are logged and included in the Step 5 report for awareness.

6. Store the resolved decisions (adapted or changed) as `project_decisions` for inclusion in the Step 2 planner prompt. This ensures Gemini sees the project's constraints when generating concrete file paths and tasks.

---

## Step 1: Decompose into stages

Based on `spec.pattern`, produce a dependency-ordered stage list using these fixed DAGs:

### CRUD+UI pattern

```
Stage 1: db_migration
  title: "<entity> — database migration"
  depends_on: []
  agent: architect
  description: Schema definition and migration for <entity> with fields from spec.

Stage 2: rest_endpoints
  title: "<entity> — REST API endpoints"
  depends_on: [db_migration]
  agent: architect
  description: CRUD endpoints for <entity>. Includes validation, error handling, permissions.

Stage 3: react_components
  title: "<entity> — React UI components"
  depends_on: [rest_endpoints]
  agent: architect
  description: UI views for <entity> based on spec.ui flags (list, detail, form, dashboard).

Stage 4: test_suite
  title: "<entity> — test suite"
  depends_on: [rest_endpoints, react_components]
  agent: architect
  description: Integration and unit tests covering API endpoints and UI components.

Stage 5: feature_flags_and_permissions
  title: "<entity> — feature flags and permissions"
  depends_on: [rest_endpoints]
  agent: quick-fixer
  description: Permission guards and feature flag wiring for <entity> operations.
```

### Integration pattern

```
Stage 1: integration_client
  title: "<entity> — <service> integration client"
  depends_on: []
  agent: architect
  description: Client module for <service> API. Handles auth, request/response mapping, retries.

Stage 2: sync_logic
  title: "<entity> — sync logic"
  depends_on: [integration_client]
  agent: architect
  description: Data synchronization between local <entity> and <service>. Event-driven per spec.integrations[].events.

Stage 3: error_handling
  title: "<entity> — integration error handling"
  depends_on: [sync_logic]
  agent: architect
  description: Error recovery, dead-letter queues, retry policies, alerting for <service> integration failures.

Stage 4: test_suite
  title: "<entity> — integration test suite"
  depends_on: [error_handling]
  agent: architect
  description: Contract tests, mock service tests, error scenario coverage for <service> integration.
```

### Workflow pattern

```
Stage 1: state_machine
  title: "<entity> — state machine"
  depends_on: []
  agent: architect
  description: State definitions, valid transitions, guards for <entity> lifecycle.

Stage 2: transition_handlers
  title: "<entity> — transition handlers"
  depends_on: [state_machine]
  agent: architect
  description: Side effects triggered by state transitions. Business logic per transition.

Stage 3: notifications
  title: "<entity> — notifications"
  depends_on: [transition_handlers]
  agent: architect
  description: Notification dispatch on state transitions. Channels, templates, recipient resolution.

Stage 4: test_suite
  title: "<entity> — workflow test suite"
  depends_on: [notifications]
  agent: architect
  description: State transition tests, notification delivery tests, guard validation.

Stage 5: admin_ui
  title: "<entity> — admin UI"
  depends_on: [transition_handlers]
  agent: architect
  description: Admin interface for managing <entity> workflow state, manual transitions, audit log.
```

### Library-extension pattern

```
Stage 1: implementation
  title: "<entity> — implementation"
  depends_on: []
  agent: architect
  description: Implement new functions/types for <entity> following existing module patterns. Add to the appropriate package (core or non-standard based on project conventions).

Stage 2: registration
  title: "<entity> — registration"
  depends_on: [implementation]
  agent: quick-fixer
  description: Wire new implementations into the existing registry/entry points. Update exports, maps, or init functions as needed.

Stage 3: test_suite
  title: "<entity> — test suite"
  depends_on: [implementation]
  agent: architect
  description: Unit tests following project test conventions (table-driven, property-based, etc.).
```

**When to use:** Adding functions, types, or modules to an existing library. No database, no HTTP, no UI. The project is consumed as a dependency, not deployed as a service.

**Merge rule for implementation + registration:** If both stages write to the same files (common when registration is a one-liner added to the implementation file), collapse them into a single stage. Registration as a separate stage only makes sense when the registry is in a different file than the implementation.

### Analytics pattern

```
Stage 1: aggregation_queries
  title: "<entity> — aggregation queries"
  depends_on: []
  agent: architect
  description: Data aggregation queries for <entity> metrics. Materialized views or query builders.

Stage 2: api_endpoints
  title: "<entity> — analytics API"
  depends_on: [aggregation_queries]
  agent: architect
  description: API endpoints serving aggregated <entity> data. Filtering, date ranges, pagination.

Stage 3: dashboard_components
  title: "<entity> — dashboard UI"
  depends_on: [api_endpoints]
  agent: architect
  description: Dashboard components visualizing <entity> analytics. Charts, tables, filters.

Stage 4: test_suite
  title: "<entity> — analytics test suite"
  depends_on: [dashboard_components]
  agent: architect
  description: Query correctness tests, API response validation, dashboard rendering tests.
```

### Stage enrichment

After selecting the pattern DAG, enrich each stage with spec-derived metadata:

1. **Write files**: Derive from the product's conventions. Call `pm_list_patterns(category=<product>)` to discover file path conventions. If no patterns found, use generic placeholders that /draft-plans agents will resolve via codebase reads.

2. **Acceptance criteria**: Generate per stage from the spec's fields and permissions. Format as behavioral given/when/then statements. These must be self-contained -- no references to implementation approach, function names, or file paths. Only behavioral expectations.

   Example for a `rest_endpoints` stage with entity "Template" and permission "admin:write":
   ```
   - Given a valid Template payload, when POST /api/templates is called by an admin, then a new Template is created and returned with status 201.
   - Given an unauthorized user, when POST /api/templates is called, then the request is rejected with status 403.
   ```

3. **Tasks**: Generate implementation tasks per stage. These are coder-facing and include specific file references, function signatures, and implementation details. They must be separable from acceptance criteria for holdout compliance.

4. **Conditional stages**:
   - If `spec.audit` is true, append an `audit_logging` stage to the DAG (depends on the stage that writes data -- typically `rest_endpoints` or `transition_handlers`). Agent: `quick-fixer`.
   - If `spec.permissions` is empty, skip `feature_flags_and_permissions` stage in CRUD+UI.
   - If `spec.ui` is absent or all flags are false, skip `react_components` / `dashboard_components` / `admin_ui` stages. Adjust downstream `test_suite` dependencies accordingly (remove the skipped stage from depends_on).

### Parallelism annotation

After building the DAG, identify stages that can run in parallel:
- Two stages are parallelizable if neither depends (directly or transitively) on the other.
- Store the parallel groups for the manifest and the dry-run report.

Example for CRUD+UI: `react_components` and `feature_flags_and_permissions` both depend on `rest_endpoints` but not on each other -- they are parallelizable.

---

## Step 2: Delegate to Gemini for stage content planning

For each stage in the DAG, delegate content planning to Gemini via a foreground planner agent.

Build the planner prompt:

```
Agent(subagent_type="planner", prompt="""
MODE: factory
PRODUCT: <spec.product>
ENTITY: <spec.entity>
PATTERN: <spec.pattern>
FIELDS: <spec.fields as JSON>
PERMISSIONS: <spec.permissions or []>
INTEGRATIONS: <spec.integrations or []>
AUDIT: <spec.audit or false>
UI: <spec.ui or {}>

STAGES:
<For each stage, include:>
  - stage_type: <type>
    title: <title>
    depends_on: [<dependency stage types>]
    agent: <agent>
    acceptance_criteria: <generated in Step 1>

DECOMPOSITION RULE: Minimize write-target file overlap across stages. Each stage owns its files exclusively. If two stages would share a write-target file, restructure to eliminate the overlap. Decomposition priority: file ownership > conceptual grouping.

For each stage, produce:
1. Concrete write_files (absolute paths based on product conventions)
2. Concrete read_files (files the coder needs to reference but not modify)
3. Detailed tasks (implementation steps, specific to the codebase)
4. Refined acceptance criteria (behavioral, no implementation references)

Return as structured JSON:
{
  "stages": [
    {
      "stage_type": "<type>",
      "title": "<title>",
      "write_files": ["<path>", ...],
      "read_files": ["<path>", ...],
      "tasks": ["<task 1>", "<task 2>", ...],
      "acceptance_criteria": ["<criterion 1>", ...],
      "agent": "<agent>"
    }
  ]
}
""")
```

Wait for the planner to return.

**On PLANNER_RESULT**: Merge Gemini's concrete file paths, tasks, and refined criteria back into the stage objects from Step 1. Gemini fills the content; the factory controls the structure and dependency graph.

**On PLANNER_ERROR**: Surface the error to the user. Do NOT fall back to direct MCP calls. Stop.

**If `dry_run = true`**: Skip this step entirely. Use the stage metadata from Step 1 as-is (write_files will be generic placeholders).

---

## Step 3: Create stories and write manifest

**Skip when `dry_run = true`** -- jump to Step 5.

### 3a: Create epic

Load tools:
```
ToolSearch: select:mcp__gemini__pm_create_epic,mcp__gemini__pm_create_story,mcp__gemini__pm_update_story
```

Create the epic:
```
pm_create_epic(title="/factory: <spec.entity> (<spec.pattern>)")
```

Store `epic_id` and `dev_branch` from the result.

### 3b: Create stories

For each stage in dependency order:

```
pm_create_story(
  title=<stage.title>,
  epic_id=<epic_id>,
  agent=<stage.agent>,
  write_files=<stage.write_files>,
  tasks=<stage.tasks>
)
```

After creation, record the mapping: `stage_type -> story_id`.

Then set `depends_on` by resolving stage dependencies to story IDs:
```
pm_update_story(
  story_id=<story_id>,
  depends_on=[<resolved story IDs from stage.depends_on>]
)
```

### 3c: Ensure holdout compliance

For each story created, verify that its metadata cleanly partitions into holdout sections:

- **Coder-visible** (`<!-- CODER_ONLY -->` / `<!-- END_CODER_ONLY -->`): tasks, write_files, read-only context, implementation notes.
- **Tester-visible** (`<!-- TESTER_ONLY -->` / `<!-- END_TESTER_ONLY -->`): (reserved for test agent content -- empty at creation time).
- **Shared** (no delimiters): title, context, what-changes table, acceptance criteria, verification, contract.

Acceptance criteria must contain no implementation references (no function names, no file paths, no technology choices). If any criterion references implementation details, rewrite it to behavioral form before storing.

This partitioning happens at the metadata level -- /draft-plans will write the actual plan files with delimiters. The factory ensures the data is clean for that downstream formatting.

### 3d: Write .ship-manifest.json

Derive slug from spec: `<entity>-<pattern>`, lowercase, hyphen-separated, max 40 chars.

Compute complexity: small (1 story), medium (2-4), large (5+).

```json
{
  "slug": "<entity>-<pattern>",
  "scope": {
    "files": <total write_files count across all stages>,
    "stories": <stage count>,
    "complexity": "<small | medium | large>"
  },
  "route_hint": "standard",
  "prev": null,
  "skill": "factory",
  "factory_spec": <original spec JSON, preserved for traceability>,
  "data": {
    "epic_id": "<epic_id>",
    "dev_branch": "dev",
    "stories": [
      {
        "id": "<story_id>",
        "title": "<stage title>",
        "agent": "<agent>",
        "detail_file": "<path>",
        "stage_type": "<stage type>",
        "depends_on": ["<story_id>", ...],
        "parallel_group": <0-based group index>
      }
    ]
  }
}
```

Write to `.ship-manifest.json` in the project root.

---

## Step 4: Validate manifest compatibility

Read the written `.ship-manifest.json` and confirm:

1. Every story has a non-empty `id`, `title`, `agent`.
2. Every `depends_on` reference resolves to a story ID present in the manifest.
3. The `data.stories` array contains the same fields /draft-plans expects: `id`, `title`, `agent`, `detail_file`.
4. The `slug`, `scope`, `route_hint`, `prev`, `skill`, and `data` top-level fields are present.

If any check fails, fix the manifest in place and log the correction.

---

## Step 5: Report

### Dry-run output

If `dry_run = true`, print the decomposition DAG and stop:

```
Factory decomposition (dry run): <entity> (<pattern>)

Stage DAG:
  [1] db_migration — "<entity> — database migration" (architect)
      depends: none
      write_files: <placeholder list>
      acceptance_criteria: N criteria
  [2] rest_endpoints — "<entity> — REST API endpoints" (architect)
      depends: [1] db_migration
      write_files: <placeholder list>
      acceptance_criteria: N criteria
  ...

Parallel groups:
  group 0: [1] db_migration
  group 1: [2] rest_endpoints
  group 2: [3] react_components, [5] feature_flags_and_permissions
  group 3: [4] test_suite

Total: N stages, M parallelizable groups
```

### Normal output

```
Factory complete: <entity> (<pattern>)

  Epic: <epic_id> — /factory: <entity> (<pattern>)
  Stories: <count> (<complexity>)

  Stage DAG:
    story-NNN  [1] db_migration                    architect   depends: none
    story-NNN  [2] rest_endpoints                   architect   depends: [1]
    story-NNN  [3] react_components                 architect   depends: [2]
    story-NNN  [4] test_suite                       architect   depends: [2, 3]
    story-NNN  [5] feature_flags_and_permissions    quick-fixer depends: [2]

  Parallel groups:
    group 0: story-NNN (db_migration)
    group 1: story-NNN (rest_endpoints)
    group 2: story-NNN (react_components), story-NNN (feature_flags_and_permissions)
    group 3: story-NNN (test_suite)

  Manifest: .ship-manifest.json
```

**If invoked standalone** (not from within /ship): prompt:
```
Draft plans? (/draft-plans .ship-manifest.json)
```

**If invoked from within /ship**: return silently -- the orchestrator reads the manifest and proceeds.

---

## Artifact contract

**Reads:** FeatureSpec JSON (file or inline)
**Writes:** `.ship-manifest.json` (one per invocation)
**DB side effects:** `pm_create_epic`, `pm_create_story`, `pm_update_story(depends_on)` for each stage

When invoked as a graph node by `/ship`, the caller proceeds to `/draft-plans` after this skill completes. When invoked standalone, the user decides next steps.
