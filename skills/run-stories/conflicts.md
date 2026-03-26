# Conflict Detection

Called from [resolve.md](resolve.md) Step 2b.

## pm_check_conflicts pass

Load `ToolSearch: select:mcp__gemini__pm_check_conflicts`, then:

1. Collect ALL story IDs across all dependency groups and call `pm_check_conflicts(story_ids=[...])` once.
2. Apply conflict results to each dependency group: conflicting stories within the same group get serialized; different groups already run sequentially.
3. Read the detail file:
   - `conflicts`: list of `{file, stories}` write-write overlaps
   - `read_conflicts`: list of `{file, writer, reader}` write-read overlaps
   - `safe_parallel`: story IDs with no write-file overlaps
   - `sequential`: story IDs that must run after conflicting stories merge
4. Use `safe_parallel` as batch 0. Chain `sequential` stories after their conflicting partner.
5. For `read_conflicts`: ensure reader runs in a batch after writer's batch.
6. Within each batch, order by ID (lowest first) for determinism.

## Symbol-level granularity

Write targets support optional symbol annotations:
- `route.ts` — whole file (conflicts with ANY other `route.ts` target)
- `route.ts:queryPinecone` — specific function (conflicts only with same symbol or bare file)

**Rules:**
- `file` vs `file` → CONFLICT
- `file` vs `file:symbol` → CONFLICT (whole-file subsumes any symbol)
- `file:symbolA` vs `file:symbolB` → SAFE (different symbols)
- `file:symbolA` vs `file:symbolA` → CONFLICT

When pm_check_conflicts returns file-level conflicts, check if ALL stories use symbol-annotated targets. If all symbols are distinct, reclassify as `safe_parallel`.

## Hybrid git merge-tree confirmation

After pm_check_conflicts classifies stories, run a second pass on sequential pairs with existing branches:

```bash
CONFLICT_RESULT=$(bash ~/.claude/scripts/conflict-check.sh \
  --branch-a <story-a-branch> \
  --branch-b <story-b-branch> \
  --project-root <project-root>)
```

Parse the JSON:
- `severity` is `"green"` or `"yellow"` (`conflict: false`) → move from `sequential` to `safe_parallel`
- `severity` is `"red"` or `"black"` (`conflict: true`) → keep in `sequential`
- `status: "error"` → keep in `sequential` (conservative fallback)

Hybrid check is opportunistic — on first run, branches don't exist yet. Adds value on re-runs and sequential batches where batch 0 creates branches before batch 1 launches.
