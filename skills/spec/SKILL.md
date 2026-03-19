---
name: spec
description: >
  Interactive spec builder: takes a product name + natural language description and
  produces a validated FeatureSpec JSON. Handles pattern selection, field typing,
  decision conflict pre-check, and writes the spec file. Use when the user says
  "/spec <product> <description>", "/spec --edit path/to/spec.json", or
  "/spec --validate path/to/spec.json".
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
- `--edit <path>` — load an existing spec JSON for interactive editing. Strip flag + path.
- `--validate <path>` — validate an existing spec against the target project's decisions without running factory. Strip flag + path.
- `--project-root <path>` — override project root for decision lookup. Strip flag + path.

**Input modes (remaining tokens after flag stripping):**

1. **Edit mode**: `--edit` was provided. Read the JSON file, display current spec, proceed to Step 2 for interactive refinement.
2. **Validate mode**: `--validate` was provided. Read the JSON file, run Step 3 (decision check) only, report and stop.
3. **Build mode** (default): First token is the product name. Everything after is the natural language description. If no description provided, ask:
   > "Describe the feature you want to add to <product>:"

---

## Step 1: Understand the feature (build mode only)

From the natural language description, extract:

1. **Entity name** — the primary noun (e.g., "add contacts management" → Contact, "webhook notifications" → Webhook, "add semver validation" → Validator)

2. **Pattern detection** — infer from the description:
   - Mentions DB/CRUD/API/UI/form/list → `crud-ui`
   - Mentions external service/sync/webhook/integration → `integration`
   - Mentions state machine/approval/workflow/lifecycle → `workflow`
   - Mentions dashboard/metrics/analytics/reports → `analytics`
   - Mentions add function/validator/module/extend/library → `library-extension`
   - If ambiguous, ask the user with equal-detail options.

3. **Fields** — extract from description. For each mentioned attribute:
   - Infer type: names/labels → string, counts → number, flags → boolean, dates → date, status/role → enum, foreign references → reference
   - Infer required: explicitly optional → `required: false`, otherwise true
   - Infer sensitive: passwords/tokens/keys/SSN/phone → `sensitive: true`
   - If description mentions enum values, capture them in `values`

4. **Permissions** — if description mentions access control, roles, or permissions, extract as array. Otherwise empty.

5. **Audit** — if description mentions logging, audit trail, or tracking changes, set true. Otherwise false.

6. **Integrations** — if description mentions external services, extract with direction and events. Otherwise empty.

7. **UI** — if description mentions list/table/form/detail/dashboard views, set corresponding flags. If pattern is `library-extension`, leave empty.

---

## Step 2: Present and refine

Display the extracted spec as formatted JSON:

```
Spec for <product>:

{
  "product": "<product>",
  "pattern": "<pattern>",
  "entity": "<Entity>",
  "fields": [
    {"name": "<name>", "type": "<type>", ...},
    ...
  ],
  "permissions": [...],
  "audit": <bool>,
  "integrations": [...],
  "ui": {...}
}
```

Then ask:

```
Anything to change? (fields, pattern, permissions, etc. — or "good" to save)
```

**Refinement loop:**
- User says "add field X" → add it, re-display
- User says "remove field X" → remove it, re-display
- User says "change pattern to Y" → update, re-display
- User says "make X sensitive" → set sensitive: true on that field, re-display
- User says "add permission Z" → append to permissions array, re-display
- User says "good" / "save" / "looks good" / "yes" → proceed to Step 3
- Max 5 refinement rounds. After 5, proceed regardless.

---

## Step 3: Decision conflict pre-check

Locate the target project's `decisions.sql`:
- `--project-root` flag value + `/.claude/decisions.sql`
- Current working directory + `/.claude/decisions.sql`
- If not found, skip with: `"No decisions.sql found — skipping conflict pre-check."`

If found, run the same conflict detection logic as `/factory` Step 0.75:
- Parse decisions from SQL
- Check spec against each decision
- Classify as CONFLICT or WARNING

**Report conflicts inline** (don't block — this is a pre-check):

```
Decision pre-check:
  ✓ No conflicts (0 found)
```

or:

```
Decision pre-check:
  ⚠ 3 conflicts found (will surface in /factory for resolution):
    [decision-1] error-handling: spec implies generic errors, project uses AppError
    [decision-6] api-design: spec implies REST, project uses tRPC
    [decision-10] translations: spec has no i18n, project requires Lingui
  These will be presented as adapt/change choices when you run /factory.
```

This is informational — the user can still save the spec. `/factory` handles the actual resolution.

---

## Step 4: Write spec file

Determine output path:
- If `--edit` mode: overwrite the original file
- If build mode: write to `<project-root>/specs/<entity-lowercase>.json` or `specs/<entity-lowercase>.json` in cwd. Create `specs/` directory if needed.

Write the JSON with 2-space indentation.

---

## Step 5: Report

```
Spec saved: <output-path>

  Product: <product>
  Pattern: <pattern>
  Entity: <Entity>
  Fields: <count> (<list names>)
  Permissions: <list or "none">
  Audit: <yes/no>
  Integrations: <list or "none">
  UI: <list of enabled views or "none">
  Decision pre-check: <N conflicts, M warnings | clean>

Run: /factory <output-path>
```
