# Create Phase

**Skip entirely when `dry_run = true`** — jump to report.

## Step 3a: Create epic

```
ToolSearch: select:mcp__gemini__pm_create_epic,mcp__gemini__pm_create_story,mcp__gemini__pm_update_story
pm_create_epic(title="/factory: <entity> (<pattern>)")
```

Store `epic_id` and `dev_branch`.

## Step 3b: Create stories

For each stage in dependency order:
```
pm_create_story(title=<title>, epic_id=<epic_id>, agent=<agent>, write_files=<files>, tasks=<tasks>)
pm_update_story(story_id=<id>, depends_on=[<resolved story IDs>])
```

## Step 3c: Holdout compliance

Verify metadata partitions cleanly:
- **CODER_ONLY**: tasks, write_files, read-only context
- **TESTER_ONLY**: reserved (empty at creation)
- **Shared**: title, context, what-changes, acceptance criteria, verification, contract

Acceptance criteria must have no implementation references. Rewrite to behavioral form if needed.

## Step 3d: Write manifest

Slug: `<entity>-<pattern>`, lowercase, max 40 chars. Complexity: 1=small, 2-4=medium, 5+=large.

```json
{
  "slug": "<slug>",
  "scope": {"files": N, "stories": N, "complexity": "..."},
  "route_hint": "standard",
  "prev": null,
  "skill": "factory",
  "factory_spec": "<original spec>",
  "data": {
    "epic_id": "...", "dev_branch": "dev",
    "stories": [{"id": "...", "title": "...", "agent": "...", "detail_file": "...", "stage_type": "...", "depends_on": [...], "parallel_group": N}]
  }
}
```

## Step 4: Validate manifest

Confirm: every story has id/title/agent, depends_on resolves, all expected fields present. Fix in place if needed.

## Step 5: Report

**Dry-run:**
```
Factory decomposition (dry run): <entity> (<pattern>)
Stage DAG:
  [1] db_migration — "..." (architect), depends: none
  [2] rest_endpoints — "..." (architect), depends: [1]
Parallel groups: ...
Total: N stages, M groups
```

**Normal:**
```
Factory complete: <entity> (<pattern>)
  Epic: <epic_id>
  Stories: <count> (<complexity>)
  Stage DAG: ...
  Manifest: .ship-manifest.json
```

If standalone: prompt "Draft plans?" If from /ship: return silently.

## Artifact contract

**Reads:** FeatureSpec JSON
**Writes:** `.ship-manifest.json`
**DB:** pm_create_epic, pm_create_story, pm_update_story per stage
