---
name: spec
description: >
  Interactive spec builder: takes a product name + natural language description and
  produces a full feature spec document (markdown) with machine-readable FeatureSpec JSON.
  Covers objective, user stories, requirements, acceptance criteria, constraints,
  integration points, out of scope, AI boundaries, and the JSON extract for /factory.
  Use when the user says "/spec <product> <description>", "/spec --edit path/to/spec.md",
  or "/spec --validate path/to/spec.md".
args:
  - name: args
    type: string
    description: >
      Product name + natural language feature description, or --edit/--validate
      with a path to an existing spec file.
---

# Spec Skill Invoked

User has requested: `/spec {{args}}`

---

## Step 0: Parse args

**Flags:**
- `--edit <path>` — load an existing spec for interactive editing. Strip flag + path.
- `--validate <path>` — validate spec against the target project's decisions without running factory. Strip flag + path.
- `--project-root <path>` — override project root for decision lookup and integration point discovery. Strip flag + path.

**Input modes (remaining tokens after flag stripping):**

1. **Edit mode**: `--edit` was provided. Read the file, display current spec, proceed to Step 2 for refinement.
2. **Validate mode**: `--validate` was provided. Read the file, run Step 4 (decision check) only, report and stop.
3. **Build mode** (default): First token is the product name. Everything after is the natural language description. If no description provided, ask:
   > "Describe the feature you want to add to <product>:"

---

## Step 1: Extract from description (build mode only)

From the natural language description, extract content for each of the 9 spec sections.

### 1a: Objective

One sentence: what the feature is and why it exists. If the user only described *what*, infer the *why* from context (e.g., "add contacts" → "so users don't re-enter recipient details for every document").

### 1b: User Stories

1-3 stories in the format: "As a [role], I want to [action] so that [benefit]."

Infer roles from the description. If no roles mentioned, use generic "user." If the product has teams/orgs, include an admin story.

### 1c: Requirements

Functional requirements as bullet points. Extract every concrete behavior mentioned in the description. Add obvious implied requirements (e.g., if "list contacts" is mentioned, pagination is implied).

### 1d: Acceptance Criteria

Testable given/when/then statements. One per requirement minimum. These must be behavioral — no implementation references (no function names, file paths, or technology choices).

### 1e: Constraints

Three categories combined in one section:

- **What NOT to build** — features the user explicitly excluded, or features that are obviously out of the current scope. If the user didn't mention exclusions, infer reasonable ones (e.g., "no bulk import for v1").
- **Project decisions that apply** — if `--project-root` is set and `decisions.sql` exists, parse it and list decisions relevant to this feature. If not available, note: "Run `/scout --bootstrap` first to detect project decisions."
- **Non-functional requirements** — only if the feature has specific NFRs beyond project defaults (e.g., "p99 latency under 200ms", "HIPAA compliant data handling"). Don't add generic NFRs like "must be fast" — those are noise.

### 1f: Integration Points

Existing code, services, or data models this feature connects to. If `--project-root` is set, scan for:
- Related models in the database schema (Prisma, SQL, etc.)
- Existing API routes or functions this feature would call or extend
- Shared utilities (auth, validation, error handling) the feature must use

If no project root available, ask: "Does this feature integrate with any existing code? (models, APIs, services)"

### 1g: Out of Scope

Explicitly excluded features. This prevents AI agents from hallucinating related functionality. If the user didn't mention exclusions, propose reasonable ones based on the feature (e.g., for "contacts": "contact groups, CRM sync, merge/dedup, CSV import").

Present these as proposals — the user can add or remove.

### 1h: Boundaries

Three-tier system for AI agent behavior during implementation:

- **Always do** — safe actions for this feature (e.g., "follow existing test patterns", "use project error handling")
- **Ask first** — high-impact decisions (e.g., "adding new dependencies", "changing shared models", "modifying auth logic")
- **Never do** — hard stops (e.g., "never expose sensitive fields in API responses", "never modify migration files from other features", "never bypass permission checks")

Infer from the feature description and project decisions. Sensitive fields get a "never expose" boundary automatically.

### 1i: FeatureSpec JSON

Extract the machine-readable FeatureSpec from the sections above:

- **product** — from args
- **pattern** — infer from description:
  - DB/CRUD/API/UI/form/list → `crud-ui`
  - External service/sync/webhook → `integration`
  - State machine/approval/lifecycle → `workflow`
  - Dashboard/metrics/reports → `analytics`
  - Add function/validator/module/extend → `library-extension`
  - If ambiguous, ask with equal-detail options
- **entity** — primary noun from objective
- **fields** — from requirements. Infer types: names → string, counts → number, flags → boolean, dates → date, status/role → enum (with values), FKs → reference. Sensitive fields marked.
- **permissions** — from constraints/user stories if access control mentioned
- **audit** — true if requirements or constraints mention logging/tracking
- **integrations** — from integration points if external services involved
- **ui** — from requirements if UI views mentioned. Empty for library-extension.

---

## Step 2: Present and refine

Display the full spec document:

```markdown
# <Entity> — Feature Spec

## Objective
<one sentence>

## User Stories
- As a <role>, I want to <action> so that <benefit>
- ...

## Requirements
- <requirement 1>
- <requirement 2>
- ...

## Acceptance Criteria
- Given <precondition>, when <action>, then <outcome>
- ...

## Constraints
**What NOT to build:**
- <exclusion>

**Project decisions:**
- [decision-N] <decision content>

**Non-functional (if non-default):**
- <specific NFR>

## Integration Points
- <model/service/utility this connects to>
- ...

## Out of Scope
- <excluded feature 1>
- <excluded feature 2>

## Boundaries
- ✅ Always: <safe actions>
- ⚠️ Ask first: <high-impact decisions>
- 🚫 Never: <hard stops>

## FeatureSpec
​```json
{
  "product": "...",
  "pattern": "...",
  ...
}
​```
```

Then ask:

```
Anything to change? (sections, fields, scope, etc. — or "good" to save)
```

**Refinement loop:**
- User requests changes → apply, re-display affected section
- User says "good" / "save" / "yes" → proceed to Step 3
- Max 5 rounds. After 5, proceed.

---

## Step 3: Decision conflict pre-check

Locate the target project's `decisions.sql`:
- `--project-root` flag value + `/.claude/decisions.sql`
- Current working directory + `/.claude/decisions.sql`
- If not found, skip: `"No decisions.sql found — skipping conflict pre-check. Run /scout --bootstrap to enable."`

If found, run conflict detection (same logic as `/factory` Step 0.75):
- Parse decisions from SQL
- Check FeatureSpec JSON against each decision
- Classify as CONFLICT or WARNING

**Report inline** (informational — don't block):

```
Decision pre-check:
  ✓ No conflicts
```

or:

```
Decision pre-check:
  ⚠ 3 conflicts (will surface in /factory for resolution):
    [decision-1] error-handling: spec implies generic errors, project uses AppError
    [decision-6] api-design: spec implies REST, project uses tRPC
    [decision-10] translations: spec has no i18n, project requires Lingui
```

Conflicts found here are already included in the Constraints section. `/factory` handles the actual adapt/change resolution.

---

## Step 4: Write spec file

Determine output path:
- If `--edit` mode: overwrite the original file
- If build mode: write to `specs/<entity-lowercase>.md` (relative to project root or cwd). Create `specs/` directory if needed.

Write the full markdown document. The FeatureSpec JSON is embedded in the `## FeatureSpec` section — `/factory` can extract it from there, or the user can copy it to a standalone `.json` file.

---

## Step 5: Report

```
Spec saved: <output-path>

  Objective: <one-line>
  Pattern: <pattern>
  Entity: <Entity>
  Fields: <count> (<names>)
  Stories: <count>
  Acceptance criteria: <count>
  Constraints: <count> (including <N> project decisions)
  Out of scope: <count> items
  Decision pre-check: <N conflicts, M warnings | clean>

Run: /factory specs/<entity>.md
  (or extract the FeatureSpec JSON and run /factory specs/<entity>.json)
```
