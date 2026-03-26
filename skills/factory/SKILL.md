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

## Phases

Read each phase file as you enter it.

1. **Validate** → Read [validate.md](validate.md)
   - Parse args, detect format (gauntlet/canonical)
   - Normalize via [adapters.md](adapters.md)
   - Schema validation, decision conflict check

2. **Decompose** → Read [decompose.md](decompose.md)
   - Select pattern DAG (crud-ui, integration, workflow, analytics, library-extension)
   - Enrich stages with write_files, acceptance criteria, tasks
   - Delegate to Gemini planner for concrete content

3. **Create** → Read [create.md](create.md)
   - Skip if `--dry-run`
   - Create epic and stories in DB
   - Holdout compliance, write manifest, validate, report

## Child files
- [validate.md](validate.md) — Args, format detection, schema validation, decision conflicts
- [adapters.md](adapters.md) — Format adapter contract, gauntlet/canonical normalization
- [decompose.md](decompose.md) — Pattern DAGs, stage enrichment, Gemini planning
- [create.md](create.md) — Epic/story creation, manifest assembly, report
